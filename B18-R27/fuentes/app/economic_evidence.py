"""Authenticated P06 provider scope and private PDF evidence registration.

Registration preserves originals and provenance. It does not verify that a
catalog tariff applies to a billed row or create an economic verification.
"""

from __future__ import annotations

import hashlib
from .revision_scope import revision_table, next_ordinal

from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from .consistent_reads import consistent_read
from .db import transaction
from .review import _batch
from .security import now_utc
from .service import Problem, authorized_dataset, check_version, event, validate_filename
from .storage import MAX_SOURCE_BYTES, publish_bytes, read_verified
from .values_v1 import source_db


def _registered_values(conn: sqlite3.Connection, dataset_id: str, source_id: str) -> sqlite3.Row:
    source = conn.execute("SELECT id, source_sha256, cut_label FROM source_registry WHERE id = ? "
                          "AND dataset_id = ? AND kind = 'values' AND status = 'registered'",
                          (source_id, dataset_id)).fetchone()
    if source is None:
        raise Problem(404, "Fuente de valores registrada inexistente")
    return source


def confirm_provider_scope(conn: sqlite3.Connection, root: Path, token_hash: str,
                           dataset_id: str, batch_id: str, source_id: str,
                           provider: str, billing_unit: str, confirmation_note: str,
                           expected_dataset_version: int,
                           expected_revision_version: int, billing_unit_note: str | None = None) -> dict:
    """Record an explicit provider decision; 'unverified' keeps unit unresolved."""
    if provider != "HPC":
        raise Problem(422, "Este recorrido de facturación admite únicamente el prestador HPC")
    if (not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", provider) or
            billing_unit not in ("unverified", "practice") or
            not 10 <= len(confirmation_note.strip()) <= 2000):
        raise Problem(422, "Alcance, unidad o fundamento inválido")
    with transaction(conn):
        user, dataset = authorized_dataset(conn, token_hash, dataset_id, "admin")
        check_version(dataset, expected_dataset_version)
        batch = _batch(conn, dataset_id, batch_id)
        if batch["revision_version"] != expected_revision_version:
            raise Problem(409, "La revisión cambió; actualizá la vista")
        if batch["state"] == "cerrada":
            raise Problem(409, "La revisión está cerrada")
        if billing_unit == "practice":
            if (not isinstance(billing_unit_note, str) or not 20 <= len(billing_unit_note.strip()) <= 800
                    or len(confirmation_note.strip()) > 1000):
                raise Problem(422, "Documentá la unidad de la cantidad facturada y su respaldo; no basta elegir práctica")
            invoice = conn.execute("SELECT source_sha256 FROM batches WHERE id=? AND dataset_id=?", (batch_id,dataset_id)).fetchone()
            try:
                read_verified(root, invoice['source_sha256'])
            except (OSError, RuntimeError) as exc:
                raise Problem(409, "No se pudo verificar la factura que respalda la declaración de unidad") from exc
            confirmation_note = (confirmation_note.strip() + "\nUnidad de facturación declarada: práctica. "
                + billing_unit_note.strip() + "\nFactura original SHA-256: " + invoice['source_sha256']
                + ". No acredita autorización, cobertura ni equivalencia clínica.")
        source = _registered_values(conn, dataset_id, source_id)
        try:
            catalog = source_db(read_verified(root, source["source_sha256"]))
            try:
                exists = catalog.execute("SELECT 1 FROM hpc_catalog_providers WHERE id = ?",
                                         (provider,)).fetchone() is not None
            finally:
                catalog.close()
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
            raise Problem(409, "No se pudo comprobar el prestador en el original V1") from exc
        if not exists:
            raise Problem(422, "El prestador no existe en la fuente de valores")
        previous = conn.execute("SELECT id, ordinal, provider, billing_unit, confirmation_note, source_id "
                                f"FROM {revision_table(conn, 'batch_provider_scope_history')} WHERE batch_id = ? "
                                "ORDER BY ordinal DESC LIMIT 1", (batch_id,)).fetchone()
        if previous and (previous["provider"], previous["billing_unit"],
                         previous["confirmation_note"], previous["source_id"]) == (
                             provider, billing_unit, confirmation_note.strip(), source_id):
            return {"id": previous["id"], "ordinal": previous["ordinal"],
                    "provider": provider, "billing_unit": billing_unit,
                    "source_id": source_id, "cut_label": source["cut_label"],
                    "dataset_version": expected_dataset_version,
                    "revision_version": expected_revision_version, "created": False}
        history_id = str(uuid4())
        ordinal = next_ordinal(conn, 'batch_provider_scope_history', 'batch_id=?', (batch_id,))
        stamp = now_utc()
        conn.execute("INSERT INTO batch_provider_scope_history VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (history_id, batch_id, ordinal, previous["id"] if previous else None,
                      source_id, provider, billing_unit, confirmation_note.strip(), user["id"], stamp))
        conn.execute("INSERT INTO batch_provider_scopes VALUES (?, ?, ?, ?, ?, ?) "
                     "ON CONFLICT(batch_id) DO UPDATE SET provider = excluded.provider, "
                     "billing_unit = excluded.billing_unit, confirmation_note = excluded.confirmation_note, "
                     "confirmed_by = excluded.confirmed_by, confirmed_at = excluded.confirmed_at",
                     (batch_id, provider, billing_unit, confirmation_note.strip(), user["id"], stamp))
        conn.execute("UPDATE datasets SET version = version + 1 WHERE id = ?", (dataset_id,))
        conn.execute("UPDATE revisions SET version = version + 1 WHERE id = ?", (batch["revision_id"],))
        event(conn, user["id"], "provider_scope_confirmed", "batch", batch_id)
    return {"id": history_id, "ordinal": ordinal, "provider": provider,
            "billing_unit": billing_unit, "source_id": source_id, "cut_label": source["cut_label"],
            "dataset_version": expected_dataset_version + 1,
            "revision_version": expected_revision_version + 1, "created": True}


def provider_scope_history(conn: sqlite3.Connection, token_hash: str,
                           dataset_id: str, batch_id: str) -> dict:
    def read():
        _, dataset = authorized_dataset(conn, token_hash, dataset_id, "reviewer")
        batch = _batch(conn, dataset_id, batch_id)
        history = [dict(item) for item in conn.execute(
            "SELECT h.id, h.ordinal, h.previous_id, h.source_id, s.cut_label, h.provider, "
            "h.billing_unit, h.confirmation_note, h.actor_id, h.created_at "
            f"FROM {revision_table(conn, 'batch_provider_scope_history')} h JOIN source_registry s ON s.id = h.source_id "
            "WHERE h.batch_id = ? ORDER BY h.ordinal", (batch_id,))]
        return {"revision_id": batch["revision_id"], "revision_version": batch["revision_version"],
                "history": history, "current": history[-1] if history else None,
                "dataset_version": dataset["version"], "revision_state": batch["state"], "period": batch["period"]}
    return consistent_read(conn, token_hash, dataset_id, read)


def register_evidence_pdf(conn: sqlite3.Connection, root: Path, token_hash: str,
                          dataset_id: str, source_id: str, expected_dataset_version: int,
                          original_name: str, category: str, provenance_note: str,
                          expected_sha256: str, content: bytes) -> tuple[dict, bool]:
    original_name = validate_filename(original_name)
    if (not original_name.lower().endswith(".pdf") or
            category not in {"agreement", "nomenclator"} or
            not 10 <= len(provenance_note.strip()) <= 2000 or
            not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)):
        raise Problem(422, "Metadatos de PDF inválidos")
    if (not 20 <= len(content) <= MAX_SOURCE_BYTES or
            not content.startswith(b"%PDF-") or b"%%EOF" not in content[-2048:]):
        raise Problem(422, "Archivo PDF inválido o demasiado grande")
    digest = hashlib.sha256(content).hexdigest()
    if digest != expected_sha256:
        raise Problem(422, "El SHA-256 del PDF no coincide")
    # Avoid publishing on an already stale or unauthorized request.
    _, visible = authorized_dataset(conn, token_hash, dataset_id, "admin")
    check_version(visible, expected_dataset_version)
    source = _registered_values(conn, dataset_id, source_id)
    try:
        published = publish_bytes(root, content)
    except ValueError as exc:
        raise Problem(422, str(exc)) from exc
    with transaction(conn):
        user, dataset = authorized_dataset(conn, token_hash, dataset_id, "admin")
        check_version(dataset, expected_dataset_version)
        source = _registered_values(conn, dataset_id, source_id)
        prior = conn.execute("SELECT id, source_id, original_name, category, provenance_note, "
                             "source_match FROM evidence_documents WHERE dataset_id = ? AND sha256 = ?",
                             (dataset_id, digest)).fetchone()
        if prior:
            if (prior["source_id"], prior["original_name"], prior["category"],
                    prior["provenance_note"]) != (source_id, original_name, category,
                                                   provenance_note.strip()):
                raise Problem(409, "El mismo PDF ya está registrado con otros metadatos")
            return {"id": prior["id"], "sha256": digest, "source_id": source_id,
                    "source_match": prior["source_match"], "cut_label": source["cut_label"],
                    "dataset_version": expected_dataset_version}, False
        try:
            catalog = source_db(read_verified(root, source["source_sha256"]))
            try:
                columns = {r[1] for r in catalog.execute("PRAGMA table_info(hpc_catalog_documents)")}
                exact = ("sha256" in columns and catalog.execute(
                    "SELECT 1 FROM hpc_catalog_documents WHERE sha256 = ?", (digest,)).fetchone() is not None)
            finally:
                catalog.close()
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
            raise Problem(409, "No se pudo comprobar el catálogo original") from exc
        match = "catalog_hash_match" if exact else "no_catalog_hash"
        existing_file = conn.execute("SELECT byte_count, relative_path FROM stored_files WHERE sha256 = ?",
                                     (digest,)).fetchone()
        if existing_file is None:
            conn.execute("INSERT INTO stored_files VALUES (?, ?, ?, ?)", (*published, now_utc()))
        elif (existing_file["byte_count"], existing_file["relative_path"]) != published[1:]:
            raise RuntimeError("Metadatos de archivo privado inconsistentes")
        document_id = str(uuid4())
        conn.execute("INSERT INTO evidence_documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (document_id, dataset_id, source_id, digest, original_name, category,
                      match, provenance_note.strip(), user["id"], now_utc()))
        conn.execute("UPDATE datasets SET version = version + 1 WHERE id = ?", (dataset_id,))
        event(conn, user["id"], "evidence_pdf_registered", "evidence_document", document_id)
    return {"id": document_id, "sha256": digest, "source_id": source_id,
            "source_match": match, "cut_label": source["cut_label"],
            "dataset_version": expected_dataset_version + 1}, True


def list_evidence_documents(conn: sqlite3.Connection, token_hash: str, dataset_id: str) -> list[dict]:
    authorized_dataset(conn, token_hash, dataset_id, "reviewer")
    return [dict(item) for item in conn.execute(
        "SELECT d.id, d.source_id, s.cut_label, d.sha256, d.original_name, d.category, "
        "d.source_match, d.provenance_note, d.registered_by, d.registered_at "
        "FROM evidence_documents d JOIN source_registry s ON s.id = d.source_id "
        "WHERE d.dataset_id = ? ORDER BY d.registered_at, d.id", (dataset_id,))]


def evidence_pdf_bytes(conn: sqlite3.Connection, root: Path, token_hash: str,
                       dataset_id: str, document_id: str) -> tuple[bytes, str]:
    authorized_dataset(conn, token_hash, dataset_id, "reviewer")
    document = conn.execute("SELECT sha256, original_name FROM evidence_documents WHERE id = ? "
                            "AND dataset_id = ?", (document_id, dataset_id)).fetchone()
    if document is None:
        raise Problem(404, "Documento inexistente")
    try:
        return read_verified(root, document["sha256"]), document["sha256"]
    except (OSError, RuntimeError) as exc:
        raise Problem(409, "El original privado no está disponible o no coincide") from exc

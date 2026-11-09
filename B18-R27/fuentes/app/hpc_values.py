"""Versioned HPC value assertions linked to registered agreement PDFs.

These records are human-entered references. They do not alter V1 or run controls.
Row applicability is separate; a dated new version affects its dependants and
requires explicit confirmation and analysis before producing current results.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from .db import transaction
from .security import now_utc
from .service import Problem, authorized_dataset, check_version, event
from .storage import read_verified
from .values_v1 import source_db, json_safe_catalog_amount, catalog_amount_literal


def _source(conn: sqlite3.Connection, dataset_id: str, source_id: str) -> sqlite3.Row:
    source = conn.execute("SELECT id, source_sha256, cut_label FROM source_registry "
                          "WHERE dataset_id = ? AND id = ? AND kind = 'values' AND status = 'registered'",
                          (dataset_id, source_id)).fetchone()
    if source is None:
        raise Problem(404, "Fuente de valores inexistente")
    return source


def _tariff(root: Path, source: sqlite3.Row, tariff_seq: int) -> dict:
    try:
        catalog = source_db(read_verified(root, source["source_sha256"]))
        try:
            row = catalog.execute("SELECT seq, code, provider, amount_cents, valid_from, valid_until "
                                  "FROM hpc_catalog_tariffs WHERE seq = ? AND provider = 'HPC'",
                                  (tariff_seq,)).fetchone()
            if not row:
                return {}
            tariff = dict(row)
            tariff['amount_literal'] = catalog_amount_literal(tariff['amount_cents'])
            tariff['amount_cents'] = json_safe_catalog_amount(tariff['amount_cents'])
            return tariff
        finally:
            catalog.close()
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
        raise Problem(409, "No se pudo verificar el catálogo original") from exc


def value_history(conn: sqlite3.Connection, root: Path, token_hash: str,
                  dataset_id: str, source_id: str, tariff_seq: int) -> dict:
    authorized_dataset(conn, token_hash, dataset_id, "reviewer")
    source = _source(conn, dataset_id, source_id)
    tariff = _tariff(root, source, tariff_seq)
    if not tariff:
        raise Problem(404, "Arancel HPC inexistente en el original")
    rows = conn.execute(
        "SELECT v.id, v.ordinal, v.previous_id, v.code, v.amount_ars, v.unit_label, v.effective_from, "
        "v.document_id, v.document_sha256, v.page_number, v.excerpt, v.reason, "
        "v.created_at, u.username AS actor_username FROM hpc_value_versions v "
        "JOIN users u ON u.id = v.actor_id WHERE v.dataset_id = ? AND v.source_id = ? "
        "AND v.tariff_seq = ? ORDER BY v.ordinal",
        (dataset_id, source_id, tariff_seq)).fetchall()
    status_history = []
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='hpc_value_status_versions'").fetchone():
        status_history = [dict(row) for row in conn.execute(
            "SELECT v.*,u.username AS actor_username FROM hpc_value_status_versions v JOIN users u ON u.id=v.actor_id "
            "WHERE v.dataset_id=? AND v.source_id=? AND v.tariff_seq=? ORDER BY v.ordinal",
            (dataset_id,source_id,tariff_seq))]
    return {"status_history": status_history, "source_id": source_id, "source_sha256": source["source_sha256"],
            "cut_label": source["cut_label"], "tariff": tariff,
            "versions": [dict(row) for row in rows],
            "use_limit": "Referencia ingresada con documento; aplicabilidad por prestación no determinada"}


def save_value_version(conn: sqlite3.Connection, root: Path, token_hash: str,
                       dataset_id: str, source_id: str, *, expected_dataset_version: int,
                       tariff_seq: int, code: str, amount_ars: str, unit_label: str, effective_from: str,
                       document_id: str, page_number: int, excerpt: str, reason: str) -> dict:
    if (tariff_seq < 1 or not code or len(code) > 64 or code != code.strip()
            or page_number < 1 or page_number > 10000
            or not 2 <= len(unit_label.strip()) <= 100
            or not 10 <= len(excerpt.strip()) <= 2000
            or not 10 <= len(reason.strip()) <= 2000):
        raise Problem(422, "Datos o localizador del valor inválidos")
    try:
        if date.fromisoformat(effective_from).isoformat() != effective_from:
            raise ValueError()
    except ValueError:
        raise Problem(422, "Fecha de inicio inválida") from None
    if not re.fullmatch(r"(?:0|[1-9][0-9]{0,11})\.[0-9]{2}", amount_ars):
        raise Problem(422, "Indicá el importe exacto en ARS con dos decimales")
    try:
        money = Decimal(amount_ars)
    except InvalidOperation:
        raise Problem(422, "Importe inválido") from None
    if money <= 0:
        raise Problem(422, "El importe debe ser positivo")
    _, visible = authorized_dataset(conn, token_hash, dataset_id, "admin")
    check_version(visible, expected_dataset_version)
    source = _source(conn, dataset_id, source_id)
    tariff = _tariff(root, source, tariff_seq)
    if not tariff or tariff["code"] != code:
        raise Problem(422, "Código/arancel HPC no coincide con el original")
    document = conn.execute(
        "SELECT id, sha256 FROM evidence_documents WHERE id = ? AND dataset_id = ? "
        "AND source_id = ? AND category = 'agreement'", (document_id, dataset_id, source_id)).fetchone()
    if document is None:
        raise Problem(422, "Seleccioná un PDF de convenio registrado para esta fuente")
    try:
        read_verified(root, document["sha256"])
    except (OSError, RuntimeError) as exc:
        raise Problem(409, "El PDF registrado no se pudo verificar") from exc
    with transaction(conn):
        actor, dataset = authorized_dataset(conn, token_hash, dataset_id, "admin")
        check_version(dataset, expected_dataset_version)
        current_source = _source(conn, dataset_id, source_id)
        current_document = conn.execute(
            "SELECT sha256 FROM evidence_documents WHERE id = ? AND dataset_id = ? "
            "AND source_id = ? AND category = 'agreement'", (document_id, dataset_id, source_id)).fetchone()
        if (current_source["source_sha256"] != source["source_sha256"] or
                current_document is None or current_document["sha256"] != document["sha256"]):
            raise Problem(409, "El respaldo cambió durante la preparación; actualizá la vista")
        version_id, ordinal = _insert_value_version(conn, actor['id'], dataset_id, source_id,
            tariff_seq=tariff_seq, code=code, amount_ars=str(money), unit_label=unit_label,
            effective_from=effective_from, document_id=document_id, document_sha256=document['sha256'],
            page_number=page_number, excerpt=excerpt, reason=reason)
        conn.execute("UPDATE datasets SET version = version + 1 WHERE id = ?", (dataset_id,))
    return {"id": version_id, "ordinal": ordinal, "source_id": source_id,
            "cut_label": source["cut_label"], "dataset_version": expected_dataset_version + 1,
            "use_limit": "No ejecuta análisis ni crea propuestas. Una versión aplicable afecta sus referencias por fila; requiere confirmación y análisis explícitos"}


def _insert_value_version(conn, actor_id, dataset_id, source_id, *, tariff_seq, code,
                          amount_ars, unit_label, effective_from, document_id,
                          document_sha256, page_number, excerpt, reason):
    """Caller owns transaction and has validated every value and its evidence."""
    if not conn.in_transaction:
        raise RuntimeError('Value insertion requires an owned transaction')
    previous = conn.execute(
        "SELECT id, ordinal, effective_from FROM hpc_value_versions "
        "WHERE dataset_id = ? AND source_id = ? AND tariff_seq = ? "
        "ORDER BY ordinal DESC LIMIT 1", (dataset_id, source_id, tariff_seq)).fetchone()
    if previous and effective_from < previous["effective_from"]:
        raise Problem(409, "La fecha antecede a una versión ya registrada; revisá la historia")
    version_id = str(uuid4())
    ordinal = previous["ordinal"] + 1 if previous else 1
    conn.execute(
        "INSERT INTO hpc_value_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (version_id, dataset_id, source_id, tariff_seq, code, ordinal,
         previous["id"] if previous else None, amount_ars, unit_label.strip(), effective_from,
         document_id, document_sha256, page_number, excerpt.strip(),
         reason.strip(), actor_id, now_utc()))
    event(conn, actor_id, "hpc_value_version_recorded", "hpc_value_version", version_id)
    return version_id, ordinal

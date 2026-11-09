"""Transactional P06 proposal persistence; no public write route yet.

Verification records and provider scopes are server records. Their creation
requires a separate evidence workflow; request bodies cannot create them here.
"""

from __future__ import annotations

from .revision_scope import revision_table

from datetime import date
from decimal import Decimal
import json
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from .controls import _run_summary
from .db import transaction
from .monetary_gate import (EconomicReference, GateBlocked, ProposedComponent,
                            RowContext, consolidate_current)
from .review import _batch, _decision_status, _latest_run, _result
from .security import now_utc
from .service import Problem, authorized_dataset, check_version, event
from .storage import read_verified
from .values_v1 import source_db
from .eligibility import effective_row
from .dependencies import result_affected
from .documentary_assessments import reference_documentary_dependency
from .proposal_freshness import (BASIS_VERSION, ProposalEvaluator, VERIFICATION_FIELDS,
                                 document_basis, provider_basis, row_basis, value_source_basis)


def _work_basis(conn: sqlite3.Connection, import_id: str, source_row: int) -> dict:
    return {item["field"]: item["latest_change_id"] for item in conn.execute(
        "SELECT field, latest_change_id FROM work_fields WHERE import_id = ? AND source_row = ?",
        (import_id, source_row))}


def proposal_history(conn: sqlite3.Connection, root: Path, token_hash: str, dataset_id: str,
                     batch_id: str, source_row: int) -> dict:
    """Read consistent history and evaluate only the latest row/revision version."""
    authorized_dataset(conn, token_hash, dataset_id, "reviewer")
    conn.execute("BEGIN")
    try:
        _, dataset = authorized_dataset(conn, token_hash, dataset_id, "reviewer")
        batch = _batch(conn, dataset_id, batch_id)
        if conn.execute("SELECT 1 FROM invoice_rows WHERE import_id = ? AND source_row = ?",
                        (batch["import_id"], source_row)).fetchone() is None:
            raise Problem(404, "Fila inexistente")
        records = conn.execute("SELECT * FROM proposal_versions WHERE import_id = ? AND revision_id = ? "
                               "AND source_row = ? ORDER BY ordinal",
                               (batch["import_id"], batch["revision_id"], source_row)).fetchall()
        versions = [{"id": item["id"], "ordinal": item["ordinal"],
                 "previous_id": item["previous_id"], "run_id": item["run_id"],
                 "amount_ars_at_save": item["amount_ars"], "currency": item["currency"],
                 "payload_at_save": json.loads(item["payload_json"]),
                 "actor_id": item["actor_id"], "created_at": item["created_at"]}
                    for item in records]
        evaluation = ProposalEvaluator(conn, root, dataset_id, batch_id, batch).evaluate(records[-1]) if records else None
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    _, current_dataset = authorized_dataset(conn, token_hash, dataset_id, "reviewer")
    current_batch = _batch(conn, dataset_id, batch_id)
    if current_dataset["version"] != dataset["version"] or current_batch["revision_version"] != batch["revision_version"]:
        raise Problem(409, "La revisión cambió durante la lectura; actualizá la vista")
    return {"source_row": source_row, "revision_id": batch["revision_id"],
            "dataset_version": dataset["version"], "revision_version": batch["revision_version"],
            "current_proposal": evaluation if evaluation and evaluation["current_component_count"] else None,
            "latest_evaluation": evaluation, "versions": versions,
            "note": "Solo la última versión aporta sus componentes vigentes; los afectados conservan historia."}


def withdraw_economic_verification(conn: sqlite3.Connection, token_hash: str, dataset_id: str,
                                    verification_id: str, expected_dataset_version: int, reason: str) -> dict:
    """Internal withdrawal; reevaluation must create another verification record."""
    if not 10 <= len(reason.strip()) <= 2000:
        raise Problem(422, "Se requiere fundamento para retirar la referencia")
    with transaction(conn):
        user, dataset = authorized_dataset(conn, token_hash, dataset_id, "reviewer")
        check_version(dataset, expected_dataset_version)
        reference = conn.execute("SELECT id FROM economic_verifications WHERE id = ? AND dataset_id = ?",
                                 (verification_id, dataset_id)).fetchone()
        if reference is None:
            raise Problem(404, "Referencia económica inexistente")
        if conn.execute("SELECT 1 FROM economic_verification_withdrawals WHERE verification_id = ?",
                        (verification_id,)).fetchone():
            raise Problem(409, "La referencia ya fue retirada; una reevaluación requiere otro registro")
        withdrawal_id = str(uuid4())
        conn.execute("INSERT INTO economic_verification_withdrawals VALUES (?, ?, ?, ?, ?)",
                     (withdrawal_id, verification_id, reason.strip(), user["id"], now_utc()))
        conn.execute("UPDATE economic_verifications SET active = 0 WHERE id = ?", (verification_id,))
        conn.execute("UPDATE datasets SET version = version + 1 WHERE id = ?", (dataset_id,))
        event(conn, user["id"], "economic_verification_withdrawn", "economic_verification", verification_id)
    return {"id": withdrawal_id, "dataset_version": expected_dataset_version + 1}


def save_verified_proposal(conn: sqlite3.Connection, root: Path, token_hash: str,
                           dataset_id: str, batch_id: str, source_row: int,
                           expected_dataset_version: int, expected_revision_version: int,
                           component_specs: tuple[dict, ...]) -> dict:
    """Save one immutable version using only references already verified on server.

    Each spec has decision_id, verification_id, rubric, unit_start, unit_end,
    billed_scope_ars and optional adjustment fields. The service rechecks every
    dependency under BEGIN IMMEDIATE before it writes anything.
    """
    if not 1 <= len(component_specs) <= 100:
        raise Problem(422, "Se requieren entre 1 y 100 componentes")
    with transaction(conn):
        user, dataset = authorized_dataset(conn, token_hash, dataset_id, "reviewer")
        check_version(dataset, expected_dataset_version)
        batch = _batch(conn, dataset_id, batch_id)
        if batch["revision_version"] != expected_revision_version:
            raise Problem(409, "La revisión cambió; actualizá la vista")
        if batch["state"] == "cerrada":
            raise Problem(409, "La revisión está cerrada")
        from .authorization_controls import synthetic_batch
        if synthetic_batch(conn,batch_id):
            raise Problem(409, 'Un lote declarado ficticio no admite propuestas monetarias reales')
        scope = conn.execute("SELECT h.id, h.source_id, h.provider, h.billing_unit "
                             f"FROM {revision_table(conn, 'batch_provider_scope_history')} h WHERE h.batch_id = ? "
                             "ORDER BY h.ordinal DESC LIMIT 1", (batch_id,)).fetchone()
        if scope is None:
            raise Problem(409, "Falta confirmar el prestador y la unidad del lote")
        row = conn.execute("SELECT * FROM invoice_rows WHERE import_id = ? AND source_row = ?",
                           (batch["import_id"], source_row)).fetchone()
        if row is None:
            raise Problem(404, "Fila inexistente")
        row = effective_row(row, batch["period"])
        if row["disposition"] != "included":
            raise Problem(422, "La fila está excluida o tiene alcance indeterminado")
        fields = json.loads(row["permitted_json"])
        for item in conn.execute("SELECT field, value_json FROM work_fields WHERE import_id = ? "
                                 "AND source_row = ?", (batch["import_id"], source_row)):
            fields[item["field"]] = json.loads(item["value_json"])
        latest = _latest_run(conn, batch["revision_id"])
        if latest is None:
            raise Problem(409, "Primero ejecutá el análisis")
        summary = _run_summary(conn, dataset_id, latest["id"])
        snapshot_sources = {(s["id"], s["source_sha256"]) for s in summary["snapshot"]["sources"]
                            if s["kind"] == "values" and s["status"] == "registered"}
        if not any(source_id == scope["source_id"] for source_id, _ in snapshot_sources):
            raise Problem(409, "El alcance del prestador requiere actualizar la fuente de valores")
        values = value_source_basis(conn, dataset_id)
        if values != [s for s in summary["snapshot"]["sources"] if s["kind"] == "values"]:
            raise Problem(409, "Las fuentes de valores cambiaron; actualizá el análisis antes de guardar")
        prepared = []
        verification_snapshots = []
        decisions = set()
        source_cache: dict[str, sqlite3.Connection] = {}
        try:
            for spec in component_specs:
                decision = conn.execute(
                    "SELECT d.id, d.alert_id, d.rule_code, d.state, a.source_row, a.revision_id "
                    "FROM review_decisions d JOIN alerts a ON a.id = d.alert_id WHERE d.id = ?",
                    (spec.get("decision_id"),)).fetchone()
                if (decision is None or decision["source_row"] != source_row or
                        decision["revision_id"] != batch["revision_id"] or
                        decision["state"] != "confirmada" or result_affected(summary, source_row, decision["rule_code"]) or
                        _decision_status(conn, decision["alert_id"], latest["id"]) !=
                        ("confirmada", decision["id"])):
                    raise Problem(409, "La decisión no está confirmada y vigente para esta fila")
                result = _result(conn, latest["id"], source_row, decision["rule_code"])
                if result is None or result["result"] != "con_indicios":
                    raise Problem(409, "El hallazgo requiere un análisis vigente")
                verification = conn.execute(
                    "SELECT v.*, s.cut_label, s.status, s.kind, s.source_sha256 AS registered_sha "
                    "FROM economic_verifications v JOIN source_registry s ON s.id = v.source_id "
                    "WHERE v.id = ? AND v.dataset_id = ? AND s.dataset_id = ?",
                    (spec.get("verification_id"), dataset_id, dataset_id)
                ).fetchone()
                if (verification is None or not verification["active"] or
                        verification["status"] != "registered" or verification["kind"] != "values" or
                        verification["source_sha256"] != verification["registered_sha"] or
                        (verification["source_id"], verification["source_sha256"]) not in snapshot_sources):
                    raise Problem(409, "La referencia económica no está vigente en el conjunto")
                if conn.execute("SELECT 1 FROM economic_verification_withdrawals WHERE verification_id = ?",
                                (verification["id"],)).fetchone():
                    raise Problem(409, "La referencia económica fue retirada")
                if conn.execute(
                    "SELECT 1 FROM evidence_documents WHERE dataset_id = ? AND source_id = ? "
                    "AND sha256 = ?", (dataset_id, verification["source_id"],
                                      verification["evidence_sha256"])).fetchone() is None:
                    raise Problem(409, "El PDF de la referencia no está registrado en el conjunto")
                # Both immutable bytes must exist and match the recorded hashes.
                try:
                    evidence = read_verified(root, verification["evidence_sha256"])
                    if not evidence.startswith(b"%PDF-"):
                        raise ValueError("evidence_not_pdf")
                    if verification["source_sha256"] not in source_cache:
                        source_cache[verification["source_sha256"]] = source_db(
                            read_verified(root, verification["source_sha256"]))
                except (OSError, RuntimeError, ValueError) as exc:
                    raise Problem(409, "Falta el original verificable de la referencia") from exc
                match = re.fullmatch(r"hpc_catalog_tariffs\.seq=(\d+)", verification["tariff_locator"])
                if match is None:
                    raise Problem(422, "Localizador arancelario inválido")
                tariff = source_cache[verification["source_sha256"]].execute(
                    "SELECT provider, code, amount_cents, valid_from, valid_until "
                    "FROM hpc_catalog_tariffs WHERE seq = ?", (int(match.group(1)),)).fetchone()
                if (tariff is None or tariff["provider"] != verification["provider"] or
                        tariff["code"] != verification["code_complete"] or
                        Decimal(tariff["amount_cents"]) != Decimal(verification["rate_ars"]) * 100 or
                        tariff["valid_from"] != verification["valid_from"] or
                        (tariff["valid_until"] is not None and
                         verification["verified_through"] > tariff["valid_until"])):
                    raise Problem(409, "La referencia no coincide con el arancel original")
                reference = EconomicReference(
                    verification["source_id"], verification["source_sha256"],
                    verification["cut_label"], verification["tariff_locator"],
                    verification["provider"], verification["code_complete"],
                    verification["currency"], verification["economic_unit"],
                    Decimal(verification["rate_ars"]), date.fromisoformat(verification["valid_from"]),
                    date.fromisoformat(verification["verified_through"]),
                    True, verification["applicability_note"])
                prepared.append(ProposedComponent(
                    source_row, decision["id"], decision["rule_code"], spec.get("rubric"),
                    Decimal(str(spec.get("unit_start"))), Decimal(str(spec.get("unit_end"))),
                    Decimal(str(spec.get("billed_scope_ars"))), reference,
                    Decimal(str(spec["adjusted_ars"])) if spec.get("adjusted_ars") is not None else None,
                    spec.get("adjustment_calculation"), spec.get("adjustment_reason")))
                verification_snapshots.append({key: verification[key] for key in VERIFICATION_FIELDS})
                decisions.add((decision["id"], decision["rule_code"]))
        except (ArithmeticError, ValueError, TypeError, sqlite3.Error) as exc:
            if isinstance(exc, Problem):
                raise
            raise Problem(422, "Componente o referencia inválida") from exc
        finally:
            for source in source_cache.values():
                source.close()
        try:
            context = RowContext(source_row, scope["provider"], str(fields.get("E") or ""),
                                 date.fromisoformat(row["practice_date"]), Decimal(str(fields.get("G"))),
                                 Decimal(row["honorarios_ars"]), Decimal(row["derechos_ars"]),
                                 Decimal(row["total_ars"]), scope["billing_unit"],
                                 row["disposition"] == "included", frozenset(decisions),
                                 frozenset(snapshot_sources))
            payload = consolidate_current(context, tuple(prepared))
        except (GateBlocked, ValueError, TypeError, ArithmeticError) as exc:
            reason = exc.code if isinstance(exc, GateBlocked) else "row_data_invalid"
            raise Problem(422, f"Propuesta sin respaldo suficiente: {reason}") from exc
        previous = conn.execute("SELECT id, ordinal FROM proposal_versions WHERE import_id = ? "
                                "AND source_row = ? ORDER BY ordinal DESC LIMIT 1",
                                (batch["import_id"], source_row)).fetchone()
        if previous:
            prior = conn.execute('SELECT payload_json FROM proposal_versions WHERE id=?',(previous['id'],)).fetchone()
            if json.loads(prior['payload_json']).get('format_version') == 3:
                raise Problem(409,'La propuesta usa una referencia por fila; requiere su circuito de revisión vigente')
        proposal_id = str(uuid4())
        ordinal = previous["ordinal"] + 1 if previous else 1
        # Preserve the exact verification IDs as well as the normalized calculation.
        payload["verification_snapshots"] = verification_snapshots
        payload["format_version"] = 2
        original_sha = conn.execute("SELECT source_sha256 FROM batches WHERE id = ?", (batch_id,)).fetchone()[0]
        try:
            read_verified(root, original_sha)
        except (OSError, RuntimeError, ValueError) as exc:
            raise Problem(409, "El original del lote no está disponible o no coincide") from exc
        payload["basis"] = {"version": BASIS_VERSION, "invoice_sha256": original_sha,
                             "run_sha256": summary["snapshot_sha256"], "row": row_basis(conn, row, fields),
                             "provider_scope": provider_basis(conn, batch_id), "value_sources": values}
        for component, spec, verification in zip(payload["components"], component_specs, verification_snapshots):
            cotejo = reference_documentary_dependency(conn, root, dataset_id, verification)
            if cotejo and not cotejo['usable_match']:
                raise Problem(409, 'El cotejo documental del arancel requiere revisión antes de guardar un importe')
            component["component_id"] = str(uuid4())
            component['documentary_assessment_id_at_save'] = cotejo['id'] if cotejo else None
            component["verification_id"] = spec["verification_id"]
            component["document_snapshot"] = document_basis(conn, dataset_id, verification["source_id"],
                                                             verification["evidence_sha256"])
        conn.execute("INSERT INTO proposal_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (proposal_id, batch["revision_id"], batch["import_id"], source_row, ordinal,
                      previous["id"] if previous else None, latest["id"], scope["provider"],
                      json.dumps(_work_basis(conn, batch["import_id"], source_row), sort_keys=True),
                      payload["amount_ars"], "ARS", json.dumps(payload, ensure_ascii=False, sort_keys=True),
                      user["id"], now_utc()))
        conn.execute("UPDATE datasets SET version = version + 1 WHERE id = ?", (dataset_id,))
        conn.execute("UPDATE revisions SET version = version + 1 WHERE id = ?", (batch["revision_id"],))
        event(conn, user["id"], "proposal_saved", "proposal", proposal_id)
    return {"id": proposal_id, "ordinal": ordinal, "previous_id": previous["id"] if previous else None,
            "amount_ars": payload["amount_ars"], "currency": "ARS",
            "dataset_version": expected_dataset_version + 1,
            "revision_version": expected_revision_version + 1}

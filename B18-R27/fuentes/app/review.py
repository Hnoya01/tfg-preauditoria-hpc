"""P05 alerts, human decisions, and versioned interpretation changes."""

from __future__ import annotations

from .revision_scope import revision_table

from decimal import Decimal, InvalidOperation
from contextlib import nullcontext
import hashlib
import json
import sqlite3
from uuid import uuid4

from .db import transaction
from .consistent_reads import consistent_read
from .security import now_utc
from .service import Problem, authorized_dataset, check_version, event
from .eligibility import effective_row
from .dependencies import dependency_changes, result_affected


EDITABLE = {"B": 100, "C": 100, "E": 64, "G": 40, "K": 500}
DECISION_STATES = {"confirmada", "descartada", "no_concluyente"}


def _batch(conn: sqlite3.Connection, dataset_id: str, batch_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT i.id AS import_id, i.revision_id, i.period, r.state, r.version AS revision_version "
                       f"FROM {revision_table(conn, 'invoice_imports')} i JOIN batches b ON b.id = i.batch_id "
                       "JOIN revisions r ON r.id = i.revision_id "
                       "WHERE b.id = ? AND b.dataset_id = ?", (batch_id, dataset_id)).fetchone()
    if row is None:
        raise Problem(404, "Lote importado inexistente")
    return row


def _latest_run(conn: sqlite3.Connection, revision_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT id, snapshot_json FROM control_runs WHERE revision_id = ? "
                        "ORDER BY created_at DESC, rowid DESC LIMIT 1", (revision_id,)).fetchone()


def _result(conn: sqlite3.Connection, run_id: str, source_row: int, rule_code: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM control_results WHERE run_id = ? AND source_row = ? "
                        "AND rule_code = ?", (run_id, source_row, rule_code)).fetchone()


def _same_result(old: sqlite3.Row, current: sqlite3.Row) -> bool:
    return all(old[key] == current[key] for key in
               ("rule_version", "result", "reason_code", "evidence_json", "difference_ars", "currency"))


def _dependencies_same(conn: sqlite3.Connection, old_run_id: str, new_run_id: str,
                       rule_code: str, source_row: int, cache: dict) -> bool:
    key = (old_run_id, new_run_id)
    if key in cache:
        return not result_affected(cache[key], source_row, rule_code)
    old = json.loads(conn.execute("SELECT snapshot_json FROM control_runs WHERE id = ?",
                                  (old_run_id,)).fetchone()[0])
    new = json.loads(conn.execute("SELECT snapshot_json FROM control_runs WHERE id = ?",
                                  (new_run_id,)).fetchone()[0])
    cache[key] = dependency_changes(conn, old, new)
    return not result_affected(cache[key], source_row, rule_code)


def materialize_alerts(conn: sqlite3.Connection, run_id: str) -> int:
    """Run inside the caller's transaction; preserve each logical alert across analyses."""
    run = conn.execute("SELECT revision_id, import_id FROM control_runs WHERE id = ?", (run_id,)).fetchone()
    if run is None:
        raise Problem(404, "Análisis inexistente")
    created = 0
    for result in conn.execute("SELECT source_row, rule_code FROM control_results "
                               "WHERE run_id = ? AND result = 'con_indicios' ORDER BY source_row, rule_code",
                               (run_id,)):
        alert_id = str(uuid4())
        cursor = conn.execute("INSERT OR IGNORE INTO alerts "
                              "(id, revision_id, import_id, source_row, rule_code, first_run_id, version, created_at) "
                              "VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
                              (alert_id, run["revision_id"], run["import_id"],
                               result["source_row"], result["rule_code"], run_id, now_utc()))
        created += cursor.rowcount
    # Explicit reuse records preserve the human origin; changed evidence returns to pending.
    dependency_cache = {}
    for alert in conn.execute("SELECT id, source_row, rule_code FROM alerts WHERE revision_id = ?",
                              (run["revision_id"],)):
        current = _result(conn, run_id, alert["source_row"], alert["rule_code"])
        if current is None or current["result"] != "con_indicios":
            continue
        decision = conn.execute("SELECT * FROM review_decisions WHERE alert_id = ? "
                                "ORDER BY created_at DESC, rowid DESC LIMIT 1", (alert["id"],)).fetchone()
        if decision is None or decision["run_id"] == run_id:
            continue
        old_result = _result(conn, decision["run_id"], alert["source_row"], alert["rule_code"])
        if old_result is None or not _same_result(old_result, current):
            continue
        if not _dependencies_same(conn, decision["run_id"], run_id, alert["rule_code"], alert["source_row"], dependency_cache):
            continue
        conn.execute("INSERT OR IGNORE INTO decision_reuses VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (str(uuid4()), alert["id"], decision["id"], run_id,
                      alert["source_row"], alert["rule_code"], now_utc()))
    return created


def prepare_existing_alerts(conn: sqlite3.Connection, token_hash: str, dataset_id: str,
                            batch_id: str, expected_version: int) -> dict:
    with transaction(conn):
        user, dataset = authorized_dataset(conn, token_hash, dataset_id, "reviewer")
        check_version(dataset, expected_version)
        batch = _batch(conn, dataset_id, batch_id)
        if batch["state"] == "cerrada":
            raise Problem(409, "La revisión está cerrada")
        latest = _latest_run(conn, batch["revision_id"])
        if latest is None:
            raise Problem(409, "Primero ejecutá el análisis")
        created = materialize_alerts(conn, latest["id"])
        if created:
            conn.execute("UPDATE datasets SET version = version + 1 WHERE id = ?", (dataset_id,))
            conn.execute("UPDATE revisions SET version = version + 1 WHERE id = ?", (batch["revision_id"],))
            event(conn, user["id"], "alerts_materialized", "control_run", latest["id"])
    return {"run_id": latest["id"], "created": created,
            "dataset_version": expected_version + (1 if created else 0)}


def _decision_status(conn: sqlite3.Connection, alert_id: str, run_id: str | None) -> tuple[str, str | None]:
    if run_id is None:
        return "pendiente", None
    direct = conn.execute("SELECT id, state FROM review_decisions WHERE alert_id = ? AND run_id = ? "
                          "ORDER BY created_at DESC, rowid DESC LIMIT 1", (alert_id, run_id)).fetchone()
    if direct:
        return direct["state"], direct["id"]
    reused = conn.execute("SELECT d.id, d.state FROM decision_reuses r "
                          "JOIN review_decisions d ON d.id = r.decision_id "
                          "WHERE r.alert_id = ? AND r.run_id = ?", (alert_id, run_id)).fetchone()
    return (reused["state"], reused["id"]) if reused else ("pendiente", None)


def list_alerts(conn: sqlite3.Connection, token_hash: str, dataset_id: str,
                batch_id: str, offset: int = 0, limit: int = 50,
                include_historical: bool = False, *, after_read=None) -> dict:
    return consistent_read(conn,token_hash,dataset_id,
        lambda:_list_alerts(conn,token_hash,dataset_id,batch_id,offset,limit,include_historical),after_read=after_read)


def _list_alerts(conn,token_hash,dataset_id,batch_id,offset,limit,include_historical):
    authorized_dataset(conn, token_hash, dataset_id, "reviewer")
    if not 0 <= offset <= 1_000_000 or not 1 <= limit <= 100:
        raise Problem(422, "Paginación inválida")
    batch = _batch(conn, dataset_id, batch_id)
    latest = _latest_run(conn, batch["revision_id"])
    summary = None
    if latest:
        from .controls import run_summary
        summary = run_summary(conn, token_hash, dataset_id, latest["id"])
    rows = conn.execute("SELECT a.id, a.source_row, a.rule_code, a.version, a.first_run_id, "
                        "x.disposition, x.disposition_reason, x.practice_date, x.permitted_json "
                        "FROM alerts a JOIN invoice_rows x ON x.import_id = a.import_id "
                        "AND x.source_row = a.source_row WHERE a.revision_id = ? "
                        "ORDER BY a.source_row, a.rule_code", (batch["revision_id"],)).fetchall()
    items = []
    outside = 0
    for alert in rows:
        eligibility = effective_row(alert, batch["period"])
        if eligibility["disposition"] != "included":
            outside += 1
            if not include_historical:
                continue
        current = _result(conn, latest["id"], alert["source_row"], alert["rule_code"]) if latest else None
        decision, decision_id = _decision_status(conn, alert["id"], latest["id"] if latest else None)
        fresh = "requires_update" if summary and result_affected(summary, alert["source_row"], alert["rule_code"]) else "current"
        if eligibility["disposition"] != "included":
            fresh = "outside_scope"
        if current is None or current["result"] != "con_indicios" or fresh != "current":
            decision, decision_id = "pendiente", None
        items.append({"id": alert["id"], "source_row": alert["source_row"],
                      "rule_code": alert["rule_code"], "version": alert["version"],
                      "current_result": current["result"] if current else None,
                      "disposition": eligibility["disposition"],
                      "disposition_reason": eligibility["disposition_reason"],
                      "freshness": fresh, "decision": decision, "decision_id": decision_id})
    total = len(items)
    return {"total": total, "offset": offset, "limit": limit,
            "historical_outside_scope_count": outside, "logical_alert_history_total": len(rows),
            "latest_run_id": latest["id"] if latest else None,
            "revision_version": batch["revision_version"], "items": items[offset:offset + limit]}


def alert_detail(conn: sqlite3.Connection, token_hash: str, dataset_id: str,
                 alert_id: str) -> dict:
    # One WAL snapshot for evidence, fields, decisions and their versions.
    conn.execute('BEGIN')
    try:
        _, dataset = authorized_dataset(conn, token_hash, dataset_id, 'reviewer')
        response = _alert_detail(conn, token_hash, dataset_id, alert_id)
        response['dataset_version'] = dataset['version']
    finally:
        conn.rollback()
    # Recheck outside the snapshot: revoked access must not disclose the read.
    _, current = authorized_dataset(conn, token_hash, dataset_id, 'reviewer')
    check_version(current, response['dataset_version'])
    if _batch(conn, dataset_id, response['batch_id'])['revision_version'] != response['revision_version']:
        raise Problem(409, 'La revisión cambió durante la consulta; actualizar')
    return response


def _alert_detail(conn: sqlite3.Connection, token_hash: str, dataset_id: str,
                  alert_id: str) -> dict:
    authorized_dataset(conn, token_hash, dataset_id, "reviewer")
    alert = conn.execute(f"SELECT a.*, i.batch_id FROM alerts a JOIN {revision_table(conn, 'invoice_imports')} i ON i.id = a.import_id "
                         "JOIN batches b ON b.id = i.batch_id WHERE a.id = ? AND b.dataset_id = ?",
                         (alert_id, dataset_id)).fetchone()
    if alert is None:
        raise Problem(404, "Alerta inexistente")
    batch = _batch(conn, dataset_id, alert["batch_id"])
    if batch['revision_id'] != alert['revision_id']:
        raise Problem(409, 'Alerta de revisión anterior; consultar su exportación congelada en el historial')
    latest = _latest_run(conn, alert["revision_id"])
    current = _result(conn, latest["id"], alert["source_row"], alert["rule_code"]) if latest else None
    from .controls import run_summary
    summary = run_summary(conn, token_hash, dataset_id, latest["id"]) if latest else None
    freshness = "requires_update" if summary and result_affected(summary, alert["source_row"], alert["rule_code"]) else "current"
    decision, decision_id = _decision_status(conn, alert_id, latest["id"] if latest else None)
    if current is None or current["result"] != "con_indicios" or freshness != "current":
        decision, decision_id = "pendiente", None
    invoice = conn.execute("SELECT permitted_json, honorarios_ars, derechos_ars, total_ars, "
                           "practice_date, disposition, disposition_reason FROM invoice_rows WHERE import_id = ? AND source_row = ?",
                           (alert["import_id"], alert["source_row"])).fetchone()
    invoice = effective_row(invoice, batch["period"])
    if invoice["disposition"] != "included":
        freshness, decision, decision_id = "outside_scope", "pendiente", None
    fields = json.loads(invoice["permitted_json"])
    for edit in conn.execute("SELECT field, value_json FROM work_fields WHERE import_id = ? AND source_row = ?",
                             (alert["import_id"], alert["source_row"])):
        fields[edit["field"]] = json.loads(edit["value_json"])
    history = [dict(row) for row in conn.execute(
        "SELECT d.id, d.run_id, d.state, d.foundation, d.evidence_note, d.previous_id, "
        "d.group_id, u.username AS actor, d.created_at FROM review_decisions d "
        "JOIN users u ON u.id = d.actor_id WHERE d.alert_id = ? ORDER BY d.created_at, d.rowid",
        (alert_id,))]
    reuses = [dict(row) for row in conn.execute(
        "SELECT decision_id, run_id, created_at FROM decision_reuses WHERE alert_id = ? ORDER BY created_at",
        (alert_id,))]
    return {"id": alert_id, "batch_id": alert["batch_id"], "source_row": alert["source_row"],
            "rule_code": alert["rule_code"], "version": alert["version"],
            "revision_version": batch["revision_version"], "latest_run_id": latest["id"] if latest else None,
            "result": current["result"] if current else None,
            "reason_code": current["reason_code"] if current else None,
            "evidence": json.loads(current["evidence_json"]) if current else None,
            "freshness": freshness, "decision": decision, "decision_id": decision_id,
            "invoice": {"fields": {k: fields.get(k) for k in ("B", "C", "E", "F", "G", "H", "I", "K")},
                        "honorarios_ars": invoice["honorarios_ars"],
                        "derechos_ars": invoice["derechos_ars"], "total_ars": invoice["total_ars"],
                        "practice_date": invoice["practice_date"],
                        "disposition": invoice["disposition"],
                        "disposition_reason": invoice["disposition_reason"],
                        "eligibility_reasons": invoice["eligibility_reasons"]},
            "history": history, "reuses": reuses}


def selection_basis(dataset_id, batch_id, dataset_version, revision_version, run_id, records):
    if len({(r['rule_code'], r['reason_code']) for r in records}) > 1:
        raise Problem(422, 'Los avisos tienen controles o motivos distintos; revisalos por separado')
    payload = [dataset_id, batch_id, dataset_version, revision_version, run_id,
               sorted(records, key=lambda r: r['id'])]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def selection_record(alert, result):
    return {'id': alert['id'], 'expected_version': alert['version'], 'source_row': alert['source_row'],
            'rule_code': alert['rule_code'], 'reason_code': result['reason_code'],
            'rule_version': result['rule_version'], 'evidence_json': result['evidence_json']}


def decide_alerts(conn: sqlite3.Connection, token_hash: str, dataset_id: str,
                  batch_id: str, expected_dataset_version: int, expected_revision_version: int,
                  items: list[dict], state: str, foundation: str,
                  evidence_note: str | None, *, preview_sha256: str | None = None, _within_transaction: bool = False, _transaction_summary: dict | None = None) -> dict:
    if _within_transaction and not conn.in_transaction:
        raise RuntimeError('Internal decision requires an active transaction')
    if state not in DECISION_STATES or not 10 <= len(foundation.strip()) <= 4000:
        raise Problem(422, "Decisión o fundamento inválido")
    if state == "confirmada" and (not evidence_note or not 10 <= len(evidence_note.strip()) <= 4000):
        raise Problem(422, "Confirmar requiere evidencia adicional explícita")
    if not 1 <= len(items) <= 100 or len({x.get("id") for x in items}) != len(items):
        raise Problem(422, "Seleccioná entre 1 y 100 alertas distintas")
    with (nullcontext() if _within_transaction else transaction(conn)):
        user, dataset = authorized_dataset(conn, token_hash, dataset_id, "reviewer")
        check_version(dataset, expected_dataset_version)
        batch = _batch(conn, dataset_id, batch_id)
        if batch["revision_version"] != expected_revision_version:
            raise Problem(409, "La revisión cambió; actualizá la vista")
        if batch["state"] == "cerrada":
            raise Problem(409, "La revisión está cerrada")
        latest = _latest_run(conn, batch["revision_id"])
        if latest is None:
            raise Problem(409, "Primero ejecutá el análisis")
        from .controls import run_summary
        if _transaction_summary is not None:
            if not _within_transaction or _transaction_summary['id'] != latest['id']:
                raise RuntimeError('Summary must belong to the active transaction and run')
            summary = _transaction_summary
        else:
            summary = run_summary(conn, token_hash, dataset_id, latest["id"])
        prepared = []
        records = []
        for item in items:
            alert = conn.execute("SELECT * FROM alerts WHERE id = ? AND revision_id = ?",
                                 (item.get("id"), batch["revision_id"])).fetchone()
            if alert is None:
                raise Problem(404, "Alerta seleccionada inexistente")
            if alert["version"] != item.get("expected_version"):
                raise Problem(409, "Una alerta cambió; actualizá la selección")
            original = conn.execute("SELECT * FROM invoice_rows WHERE import_id = ? AND source_row = ?",
                                     (alert["import_id"], alert["source_row"])).fetchone()
            if effective_row(original, batch["period"])["disposition"] != "included":
                raise Problem(409, "Una alerta corresponde a una fila fuera del alcance actual")
            result = _result(conn, latest["id"], alert["source_row"], alert["rule_code"])
            if result is None or result["result"] != "con_indicios" or result_affected(summary, alert["source_row"], alert["rule_code"]):
                raise Problem(409, "Una alerta requiere actualizar el análisis")
            prior = conn.execute("SELECT id FROM review_decisions WHERE alert_id = ? "
                                 "ORDER BY created_at DESC, rowid DESC LIMIT 1", (alert["id"],)).fetchone()
            prepared.append((alert, prior["id"] if prior else None))
            records.append(selection_record(alert, result))
        if preview_sha256 is not None and preview_sha256 != selection_basis(dataset_id, batch_id,
                expected_dataset_version, expected_revision_version, latest['id'], records):
            raise Problem(409, 'La selección no coincide con la vista previa; volvé a revisarla')
        group_id = str(uuid4()) if len(prepared) > 1 else None
        created = []
        stamp = now_utc()
        for alert, prior_id in prepared:
            decision_id = str(uuid4())
            conn.execute("INSERT INTO review_decisions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (decision_id, alert["id"], latest["id"], alert["source_row"],
                          alert["rule_code"], state, foundation.strip(),
                          evidence_note.strip() if evidence_note else None, prior_id,
                          group_id, user["id"], stamp))
            conn.execute("UPDATE alerts SET version = version + 1 WHERE id = ?", (alert["id"],))
            created.append(decision_id)
        conn.execute("UPDATE datasets SET version = version + 1 WHERE id = ?", (dataset_id,))
        conn.execute("UPDATE revisions SET version = version + 1 WHERE id = ?", (batch["revision_id"],))
        event(conn, user["id"], "alerts_decided", "revision", batch["revision_id"])
    return {"decision_ids": created, "group_id": group_id,
            "dataset_version": expected_dataset_version + 1,
            "revision_version": expected_revision_version + 1}


def change_work_field(conn: sqlite3.Connection, token_hash: str, dataset_id: str,
                      batch_id: str, source_row: int, field: str, value: str,
                      reason: str, expected_dataset_version: int,
                      expected_revision_version: int) -> dict:
    if field not in EDITABLE or not 10 <= len(reason.strip()) <= 4000:
        raise Problem(422, "Campo o motivo inválido")
    if not isinstance(value, str) or len(value) > EDITABLE[field] or "\x00" in value:
        raise Problem(422, "Valor inválido")
    value = value.strip()
    if field == "E" and not value:
        raise Problem(422, "El código completo no puede estar vacío")
    if field == "G":
        try:
            quantity = Decimal(value)
        except InvalidOperation:
            raise Problem(422, "Cantidad inválida") from None
        if not quantity.is_finite() or quantity < 0 or quantity.as_tuple().exponent < -6:
            raise Problem(422, "Cantidad inválida")
        value = format(quantity, "f")
    with transaction(conn):
        user, dataset = authorized_dataset(conn, token_hash, dataset_id, "reviewer")
        check_version(dataset, expected_dataset_version)
        batch = _batch(conn, dataset_id, batch_id)
        if batch["revision_version"] != expected_revision_version:
            raise Problem(409, "La revisión cambió; actualizá la vista")
        if batch["state"] == "cerrada":
            raise Problem(409, "La revisión está cerrada")
        row = conn.execute("SELECT permitted_json, disposition, disposition_reason, practice_date FROM invoice_rows WHERE import_id = ? "
                           "AND source_row = ?", (batch["import_id"], source_row)).fetchone()
        if row is None or effective_row(row, batch["period"])["disposition"] != "included":
            raise Problem(422, "Solo puede corregirse una fila incluida")
        original = json.loads(row["permitted_json"]).get(field)
        previous = conn.execute("SELECT value_json FROM work_fields WHERE import_id = ? "
                                "AND source_row = ? AND field = ?",
                                (batch["import_id"], source_row, field)).fetchone()
        previous_value = json.loads(previous["value_json"]) if previous else original
        if str(previous_value or "").strip() == value:
            raise Problem(409, "El valor de trabajo ya coincide")
        change_id = str(uuid4())
        conn.execute("INSERT INTO work_changes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (change_id, batch["revision_id"], batch["import_id"], source_row, field,
                      json.dumps(previous_value, ensure_ascii=False), json.dumps(value, ensure_ascii=False),
                      reason.strip(), user["id"], now_utc()))
        scoped = conn.execute('PRAGMA user_version').fetchone()[0] >= 21
        target = 'revision_work_fields' if scoped else 'work_fields'
        prefix = '?, ' if scoped else ''
        key = 'revision_id, ' if scoped else ''
        conn.execute(f"INSERT INTO {target} VALUES ({prefix}?, ?, ?, ?, ?) "
                     f"ON CONFLICT({key}import_id, source_row, field) DO UPDATE SET "
                     "value_json = excluded.value_json, latest_change_id = excluded.latest_change_id",
                     ((batch['revision_id'],) if scoped else ()) +
                     (batch["import_id"], source_row, field, json.dumps(value, ensure_ascii=False), change_id))
        conn.execute("UPDATE control_runs SET freshness = 'requires_update' WHERE revision_id IN (SELECT id FROM revisions WHERE state != 'cerrada') AND dataset_id = ? "
                     f"AND import_id IN (SELECT i.id FROM {revision_table(conn, 'invoice_imports')} i "
                     "JOIN batches b ON b.id = i.batch_id WHERE b.dataset_id = ? AND i.period = ?)",
                     (dataset_id, dataset_id, batch["period"]))
        conn.execute("UPDATE datasets SET version = version + 1 WHERE id = ?", (dataset_id,))
        conn.execute("UPDATE revisions SET version = version + 1 WHERE id = ?", (batch["revision_id"],))
        event(conn, user["id"], "work_field_changed", "invoice_row", f"{batch['import_id']}:{source_row}")
    return {"change_id": change_id, "source_row": source_row, "field": field,
            "dataset_version": expected_dataset_version + 1,
            "revision_version": expected_revision_version + 1}


def work_field_history(conn: sqlite3.Connection, token_hash: str, dataset_id: str,
                       batch_id: str, source_row: int) -> list[dict]:
    authorized_dataset(conn, token_hash, dataset_id, "reviewer")
    batch = _batch(conn, dataset_id, batch_id)
    return [{**{k: row[k] for k in row.keys() if k not in ("previous_json", "new_json")},
             "previous": json.loads(row["previous_json"]), "new": json.loads(row["new_json"])}
            for row in conn.execute("SELECT c.id, c.field, c.previous_json, c.new_json, c.reason, "
                                    "u.username AS actor, c.created_at, c.revision_id FROM work_changes c "
                                    "JOIN users u ON u.id = c.actor_id WHERE c.import_id = ? AND c.source_row = ? "
                                    "ORDER BY c.created_at, c.rowid", (batch["import_id"], source_row))]

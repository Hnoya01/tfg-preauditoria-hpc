"""Transactional dataset, source, and X1 import operations."""

from __future__ import annotations

from .revision_scope import revision_table

from pathlib import Path
import sqlite3
from typing import Callable
from uuid import uuid4

from .db import transaction
from .security import current_session, now_utc
from .storage import publish_bytes, read_verified
from .invoice_x1 import parse_x1
from .eligibility import eligibility_summary


class Problem(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(message)


ROLE_LEVEL = {"viewer": 1, "reviewer": 2, "admin": 3}


def actor(conn: sqlite3.Connection, token_hash: str, *, touch: bool = False) -> sqlite3.Row:
    user = current_session(conn, token_hash, touch=touch)
    if user is None:
        raise Problem(401, "Sesión ausente o vencida")
    return user


def authorized_dataset(conn: sqlite3.Connection, token_hash: str, dataset_id: str, minimum: str,
                       *, touch: bool = False):
    user = actor(conn, token_hash, touch=touch)
    dataset = conn.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
    if dataset is None:
        raise Problem(404, "Conjunto inexistente")
    if user["role"] != "admin":
        access = conn.execute(
            "SELECT role FROM dataset_access WHERE dataset_id = ? AND user_id = ?",
            (dataset_id, user["id"]),
        ).fetchone()
        if access is None or ROLE_LEVEL[access["role"]] < ROLE_LEVEL[minimum]:
            raise Problem(403, "Permiso insuficiente")
    return user, dataset


def check_version(dataset: sqlite3.Row, expected: int) -> None:
    if dataset["version"] != expected:
        raise Problem(409, "La versión cambió; actualizá la vista antes de guardar")


def event(conn: sqlite3.Connection, user_id: str, action: str, entity_type: str, entity_id: str) -> None:
    conn.execute(
        "INSERT INTO audit_events VALUES (?, ?, ?, ?, ?, ?)",
        (str(uuid4()), user_id, action, entity_type, entity_id, now_utc()),
    )


def create_dataset(conn: sqlite3.Connection, token_hash: str, label: str) -> dict:
    label = label.strip()
    if not 1 <= len(label) <= 120:
        raise Problem(422, "Nombre de conjunto inválido")
    with transaction(conn):
        user = actor(conn, token_hash)
        if user["role"] != "admin":
            raise Problem(403, "Permiso insuficiente")
        dataset_id = str(uuid4())
        conn.execute(
            "INSERT INTO datasets(id, label, version, created_by, created_at) VALUES (?, ?, 1, ?, ?)",
            (dataset_id, label, user["id"], now_utc()),
        )
        event(conn, user["id"], "dataset_created", "dataset", dataset_id)
    return {"id": dataset_id, "label": label, "version": 1}


def list_datasets(conn: sqlite3.Connection, token_hash: str) -> list[dict]:
    user = actor(conn, token_hash)
    if user["role"] == "admin":
        rows = conn.execute("SELECT id, label, version FROM datasets ORDER BY created_at, id").fetchall()
    else:
        rows = conn.execute(
            "SELECT d.id, d.label, d.version FROM datasets d "
            "JOIN dataset_access a ON a.dataset_id = d.id "
            "WHERE a.user_id = ? ORDER BY d.created_at, d.id", (user["id"],)
        ).fetchall()
    return [dict(row) for row in rows]


def rename_dataset(conn: sqlite3.Connection, token_hash: str, dataset_id: str, expected: int, label: str) -> dict:
    label = label.strip()
    if not 1 <= len(label) <= 120:
        raise Problem(422, "Nombre de conjunto inválido")
    with transaction(conn):
        user, dataset = authorized_dataset(conn, token_hash, dataset_id, "admin")
        check_version(dataset, expected)
        version = expected + 1
        conn.execute("UPDATE datasets SET label = ?, version = ? WHERE id = ?", (label, version, dataset_id))
        event(conn, user["id"], "dataset_renamed", "dataset", dataset_id)
    return {"id": dataset_id, "label": label, "version": version}


def grant_access(conn: sqlite3.Connection, token_hash: str, dataset_id: str, expected: int,
                 username: str, role: str, invoice_duty: str | None = None) -> dict:
    if invoice_duty is not None and (role != "reviewer" or invoice_duty not in ("administrative","auditor")):
        raise Problem(422, "Función de revisión inválida")
    if role not in ROLE_LEVEL:
        raise Problem(422, "Rol inválido")
    with transaction(conn):
        user, dataset = authorized_dataset(conn, token_hash, dataset_id, "admin")
        check_version(dataset, expected)
        target = conn.execute(
            "SELECT id FROM users WHERE username = ? COLLATE NOCASE AND active = 1", (username,)
        ).fetchone()
        if target is None:
            raise Problem(404, "Cuenta inexistente")
        conn.execute(
            "INSERT INTO dataset_access(dataset_id, user_id, role) VALUES (?, ?, ?) "
            "ON CONFLICT(dataset_id, user_id) DO UPDATE SET role = excluded.role",
            (dataset_id, target["id"], role),
        )
        if invoice_duty or role != 'reviewer':
            conn.execute('DELETE FROM invoice_review_duties WHERE dataset_id=? AND user_id=?',(dataset_id,target['id']))
            if invoice_duty:
                conn.execute('INSERT INTO invoice_review_duties VALUES(?,?,?)',(dataset_id,target['id'],invoice_duty))
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (target["id"],))
        conn.execute("UPDATE datasets SET version = version + 1 WHERE id = ?", (dataset_id,))
        event(conn, user["id"], "access_changed", "dataset", dataset_id)
    return {"dataset_id": dataset_id, "version": expected + 1, "username": username, "role": role}


def validate_filename(name: str) -> str:
    if not name or len(name) > 255 or any(ch in name for ch in "/\\\r\n\x00"):
        raise Problem(422, "Nombre de archivo inválido")
    return name


def create_batch(conn: sqlite3.Connection, root: Path, token_hash: str, dataset_id: str,
                 expected: int, filename: str, content: bytes,
                 after_publish: Callable[[], None] | None = None) -> tuple[dict, bool]:
    filename = validate_filename(filename)
    # Check before writing bytes, then recheck inside the commit transaction.
    _, visible_dataset = authorized_dataset(conn, token_hash, dataset_id, "reviewer")
    check_version(visible_dataset, expected)
    try:
        digest, byte_count, relative = publish_bytes(root, content)
    except ValueError as exc:
        raise Problem(422, str(exc)) from exc
    if after_publish is not None:
        after_publish()
    with transaction(conn):
        user, dataset = authorized_dataset(conn, token_hash, dataset_id, "reviewer")
        check_version(dataset, expected)
        previous_file = conn.execute("SELECT byte_count, relative_path FROM stored_files WHERE sha256 = ?", (digest,)).fetchone()
        if previous_file is None:
            conn.execute(
                "INSERT INTO stored_files VALUES (?, ?, ?, ?)",
                (digest, byte_count, relative, now_utc()),
            )
        elif previous_file["byte_count"] != byte_count or previous_file["relative_path"] != relative:
            raise RuntimeError("Stored file metadata conflict")
        previous = conn.execute(
            "SELECT id, source_sha256, state FROM batches WHERE dataset_id = ? AND source_sha256 = ?",
            (dataset_id, digest),
        ).fetchone()
        if previous is not None:
            return {"id": previous["id"], "sha256": digest, "state": previous["state"],
                    "dataset_version": expected}, False
        batch_id = str(uuid4())
        conn.execute(
            "INSERT INTO batches(id, dataset_id, source_sha256, original_name, state, created_by, created_at) "
            "VALUES (?, ?, ?, ?, 'staged', ?, ?)",
            (batch_id, dataset_id, digest, filename, user["id"], now_utc()),
        )
        conn.execute("UPDATE datasets SET version = version + 1 WHERE id = ?", (dataset_id,))
        event(conn, user["id"], "batch_staged", "batch", batch_id)
    return {"id": batch_id, "sha256": digest, "state": "staged", "dataset_version": expected + 1}, True


def batch_metadata(conn: sqlite3.Connection, token_hash: str, dataset_id: str, batch_id: str) -> dict:
    _, dataset = authorized_dataset(conn, token_hash, dataset_id, "reviewer")
    batch = conn.execute(
        "SELECT id, source_sha256, state, original_name FROM batches WHERE id = ? AND dataset_id = ?",
        (batch_id, dataset_id),
    ).fetchone()
    if batch is None:
        raise Problem(404, "Lote inexistente")
    return {"id": batch["id"], "sha256": batch["source_sha256"], "state": batch["state"],
            "original_name": batch["original_name"], "dataset_version": dataset["version"]}


def list_batches(conn: sqlite3.Connection, token_hash: str, dataset_id: str) -> list[dict]:
    user,_=authorized_dataset(conn, token_hash, dataset_id, "reviewer")
    delivered={}
    closed={}
    audit_workflow=False
    duty=None
    if conn.execute('PRAGMA user_version').fetchone()[0]>=36:
        from .invoice_handoff import assigned_duty
        duty=assigned_duty(conn,user,dataset_id)
        delivered=dict(conn.execute('SELECT r.batch_id,h.sent_at FROM invoice_handoffs h JOIN revisions r ON r.id=h.revision_id '
                                    'JOIN batches b ON b.id=r.batch_id WHERE b.dataset_id=? AND NOT EXISTS '
                                    '(SELECT 1 FROM revisions n WHERE n.batch_id=r.batch_id AND n.ordinal>r.ordinal)',(dataset_id,)))
    if conn.execute('PRAGMA user_version').fetchone()[0]>=37:
        audit_workflow=bool(conn.execute('SELECT 1 FROM invoice_review_duties WHERE dataset_id=? LIMIT 1',(dataset_id,)).fetchone())
        closed=dict(conn.execute('SELECT b.id,c.closed_at FROM audit_invoice_closures c JOIN revisions r ON r.id=c.revision_id '
                                 'JOIN batches b ON b.id=r.batch_id WHERE b.dataset_id=? AND NOT EXISTS '
                                 '(SELECT 1 FROM revisions n WHERE n.batch_id=r.batch_id AND n.ordinal>r.ordinal)',(dataset_id,)))
    rows = conn.execute(
        "SELECT b.id, b.original_name, b.source_sha256, i.id AS import_id, i.period, i.row_count, "
        "i.included_count, i.excluded_count, i.indeterminate_count, i.eligibility_version "
        f"FROM batches b LEFT JOIN {revision_table(conn, 'invoice_imports')} i ON i.batch_id = b.id "
        "WHERE b.dataset_id = ? ORDER BY b.created_at, b.id", (dataset_id,)
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["handoff_received_at"]=delivered.get(item["id"])
        item["audit_workflow"]=audit_workflow
        item["audit_closed_at"]=closed.get(item["id"])
        item["invoice_duty"]=duty
        if item['import_id'] and conn.execute('PRAGMA user_version').fetchone()[0]>=39:
            preparation=conn.execute("""SELECT
                EXISTS(SELECT 1 FROM control_runs t WHERE t.revision_id=i.revision_id AND t.technical_state='completed') AS analyzed,
                EXISTS(SELECT 1 FROM current_authorization_match_scopes s
                       JOIN json_each(s.capture_ids_json) keys JOIN authorization_captures c ON c.id=keys.value
                       WHERE s.batch_id=i.batch_id AND c.source_system='HPC-CSV'
                         AND s.ordinal=(SELECT max(v.ordinal) FROM current_authorization_match_scopes v WHERE v.batch_id=i.batch_id)) AS csv_selected
                FROM current_invoice_imports i WHERE i.id=?""",(item['import_id'],)).fetchone()
            item.update(dict(preparation))
        if item["import_id"]:
            item["classification_at_import"] = {key: item[key] for key in
                ("included_count", "excluded_count", "indeterminate_count", "eligibility_version")}
            item.update(eligibility_summary(conn, item["import_id"], item["period"]))
        result.append(item)
    return result


def batch_content(conn: sqlite3.Connection, root: Path, token_hash: str, dataset_id: str, batch_id: str) -> tuple[bytes, str]:
    metadata = batch_metadata(conn, token_hash, dataset_id, batch_id)
    return read_verified(root, metadata["sha256"]), metadata["sha256"]


def preview_invoice(conn: sqlite3.Connection, root: Path, token_hash: str,
                    dataset_id: str, batch_id: str, period: str) -> dict:
    content, sha256 = batch_content(conn, root, token_hash, dataset_id, batch_id)
    try:
        parsed = parse_x1(content, period)
    except ValueError as exc:
        raise Problem(422, str(exc)) from exc
    return {**parsed.summary, "source_sha256": sha256, "batch_id": batch_id}


def confirm_invoice(conn: sqlite3.Connection, root: Path, token_hash: str,
                    dataset_id: str, batch_id: str, period: str, expected: int,
                    after_parse: Callable[[], None] | None = None) -> tuple[dict, bool]:
    _, visible = authorized_dataset(conn, token_hash, dataset_id, "reviewer")
    check_version(visible, expected)
    batch = conn.execute("SELECT source_sha256 FROM batches WHERE id = ? AND dataset_id = ?",
                         (batch_id, dataset_id)).fetchone()
    if batch is None:
        raise Problem(404, "Lote inexistente")
    existing = conn.execute(f"SELECT * FROM {revision_table(conn, 'invoice_imports')} WHERE batch_id = ?", (batch_id,)).fetchone()
    if existing is not None:
        if existing["period"] != period:
            raise Problem(409, "El lote ya se importó con otro período confirmado")
        return invoice_metadata(conn, token_hash, dataset_id, batch_id), False
    try:
        parsed = parse_x1(read_verified(root, batch["source_sha256"]), period)
    except ValueError as exc:
        raise Problem(422, str(exc)) from exc
    summary = parsed.summary
    if not summary["can_confirm"]:
        raise Problem(422, "No se pudo incorporar X1 fielmente; revisá los bloqueos de la vista previa")
    if after_parse is not None:
        after_parse()
    with transaction(conn):
        user, current = authorized_dataset(conn, token_hash, dataset_id, "reviewer")
        check_version(current, expected)
        # Recheck the immutable digest and import identity at the commit boundary.
        current_batch = conn.execute("SELECT source_sha256 FROM batches WHERE id = ? AND dataset_id = ?",
                                     (batch_id, dataset_id)).fetchone()
        if current_batch is None or current_batch["source_sha256"] != batch["source_sha256"]:
            raise Problem(409, "El origen del lote cambió")
        if conn.execute(f"SELECT 1 FROM {revision_table(conn, 'invoice_imports')} WHERE batch_id = ?", (batch_id,)).fetchone():
            raise Problem(409, "El lote ya fue importado")
        revision_id, import_id = str(uuid4()), str(uuid4())
        conn.execute("INSERT INTO revisions(id, batch_id, ordinal, state, version, created_at) "
                     "VALUES (?, ?, 1, 'preparacion', 1, ?)", (revision_id, batch_id, now_utc()))
        conn.execute(
            "INSERT INTO invoice_imports (id, batch_id, revision_id, period, sheet_name, row_count, "
            "included_count, excluded_count, indeterminate_count, honorarios_ars, derechos_ars, "
            "total_ars, created_by, created_at, eligibility_version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (import_id, batch_id, revision_id, period, summary["sheet"], summary["physical_rows"],
             summary["included"], summary["excluded"], summary["indeterminate"],
             summary["honorarios_ars"], summary["derechos_ars"], summary["total_ars"],
             user["id"], now_utc(), summary["eligibility_version"]),
        )
        conn.executemany(
            "INSERT INTO invoice_rows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ((import_id, *row) for row in parsed.rows),
        )
        conn.execute("UPDATE control_runs SET freshness = 'requires_update' WHERE revision_id IN (SELECT id FROM revisions WHERE state != 'cerrada') AND dataset_id = ? "
                     "AND freshness = 'current' AND import_id IN ("
                     f"SELECT i.id FROM {revision_table(conn, 'invoice_imports')} i JOIN batches b ON b.id = i.batch_id "
                     "WHERE b.dataset_id = ? AND i.period = ?)", (dataset_id, dataset_id, period))
        conn.execute("UPDATE datasets SET version = version + 1 WHERE id = ?", (dataset_id,))
        event(conn, user["id"], "invoice_x1_imported", "invoice_import", import_id)
    return {"id": import_id, "batch_id": batch_id, "revision_id": revision_id,
            "period": period, "dataset_version": expected + 1, **summary}, True


def invoice_metadata(conn: sqlite3.Connection, token_hash: str, dataset_id: str, batch_id: str) -> dict:
    authorized_dataset(conn, token_hash, dataset_id, "reviewer")
    row = conn.execute(f"SELECT i.* FROM {revision_table(conn, 'invoice_imports')} i JOIN batches b ON b.id = i.batch_id "
                       "WHERE b.id = ? AND b.dataset_id = ?", (batch_id, dataset_id)).fetchone()
    if row is None:
        raise Problem(404, "Importación inexistente")
    result = dict(row)
    result["classification_at_import"] = {key: result[key] for key in
        ("included_count", "excluded_count", "indeterminate_count", "eligibility_version")}
    result.update(eligibility_summary(conn, row["id"], row["period"]))
    return result

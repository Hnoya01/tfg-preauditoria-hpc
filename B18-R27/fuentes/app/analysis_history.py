"""MD07 durable captures and prepared results, separate from published runs."""
import json
from pathlib import Path
from uuid import uuid4

from .db import connect, transaction
from .security import now_utc
from .service import Problem, authorized_dataset, check_version


def capture_analysis(conn, token_hash, dataset_id, snapshot, serialized, digest, version):
    # The evaluator holds a WAL read snapshot. A separate short writer persists
    # that exact capture before evaluation without upgrading the read transaction.
    database = next(row[2] for row in conn.execute('PRAGMA database_list') if row[1] == 'main')
    writer = connect(Path(database).parent)
    identity = str(uuid4())
    try:
        with transaction(writer):
            user, dataset = authorized_dataset(writer, token_hash, dataset_id, 'reviewer')
            check_version(dataset, version)
            writer.execute("INSERT INTO analysis_history(id,dataset_id,revision_id,import_id,snapshot_sha256,"
                           "snapshot_json,actor_id,created_at,state) VALUES(?,?,?,?,?,?,?,?,'captured')",
                           (identity, dataset_id, snapshot['revision_id'], snapshot['import_id'], digest,
                            serialized, user['id'], now_utc()))
    finally:
        writer.close()
    return identity


def save_prepared(conn, identity, staged):
    # Once all rows were computed, preserve them even if publication is rejected.
    with transaction(conn):
        staged.seek(0)
        conn.executemany('INSERT INTO analysis_history_results VALUES(?,?,?,?,?,?,?,?,?,?)',
                         (json.loads(line) for line in staged))
        conn.execute("UPDATE analysis_history SET state='prepared' WHERE id=?", (identity,))


def history(conn, token_hash, dataset_id, *, batch_id=None, identity=None, offset=0, limit=50):
    if not 0 <= offset <= 2**63 - 1 or not 1 <= limit <= 100:
        raise Problem(422, 'Paginación inválida')
    conn.execute('BEGIN')
    try:
        _, dataset = authorized_dataset(conn, token_hash, dataset_id, 'reviewer')
        if identity is None:
            from .review import _batch
            batch = _batch(conn, dataset_id, batch_id)
            rows = conn.execute('SELECT id,state,reason_code,created_at,published_run_id,snapshot_sha256 '
                                'FROM analysis_history WHERE dataset_id=? AND revision_id=? '
                                'ORDER BY created_at DESC,rowid DESC LIMIT ? OFFSET ?',
                                (dataset_id, batch['revision_id'], limit, offset)).fetchall()
            total = conn.execute('SELECT count(*) FROM analysis_history WHERE dataset_id=? AND revision_id=?',
                                 (dataset_id, batch['revision_id'])).fetchone()[0]
            result = {'items': [dict(r) for r in rows], 'total': total, 'offset': offset, 'limit': limit}
        else:
            row = conn.execute('SELECT * FROM analysis_history WHERE id=? AND dataset_id=?',
                               (identity, dataset_id)).fetchone()
            if row is None:
                raise Problem(404, 'Captura histórica inexistente')
            result = dict(row)
            result['snapshot'] = json.loads(result.pop('snapshot_json'))
            result['results'] = [dict(r) for r in conn.execute(
                'SELECT * FROM analysis_history_results WHERE run_id=? ORDER BY source_row,rule_code LIMIT ? OFFSET ?',
                (identity, limit, offset))]
            result['total'] = conn.execute('SELECT count(*) FROM analysis_history_results WHERE run_id=?', (identity,)).fetchone()[0]
            result.update(offset=offset, limit=limit)
        result['operational'] = False  # This endpoint never authorizes decisions.
    finally:
        conn.rollback()
    _, current = authorized_dataset(conn, token_hash, dataset_id, 'reviewer')
    check_version(current, dataset['version'])
    return result

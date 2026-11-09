"""An operator may acknowledge the same CSV unit being used on a previous row."""
import json
from uuid import uuid4
from .authorization_matching import csv_queue_coverage, _context
from .db import transaction
from .review import _batch
from .security import now_utc
from .service import Problem, authorized_dataset, check_version, event


def history(conn, revision_id, source_row=None):
    sql = ('SELECT r.*,u.username AS actor FROM csv_coverage_reviews r '
           'JOIN users u ON u.id=r.actor_id WHERE r.revision_id=?')
    args = [revision_id]
    if source_row is not None:
        sql += ' AND r.source_row=?'
        args.append(source_row)
    records = []
    for row in conn.execute(sql+' ORDER BY r.rowid', args):
        record = dict(row)
        record['evidence'] = json.loads(record.pop('evidence_json'))
        record.pop('request_id')
        records.append(record)
    return records


def acknowledge(conn, root, token, dataset_id, batch_id, number, *, version, revision_id,
                revision_version, evidence_sha256, request_id, note):
    note = note.strip()
    if not 10 <= len(note) <= 2000:
        raise Problem(422,'Indicá qué evidencia revisaste.')
    with transaction(conn):
        actor, ds = authorized_dataset(conn, token, dataset_id, 'reviewer')
        batch = _batch(conn, dataset_id, batch_id)
        if batch['revision_id'] != revision_id:
            raise Problem(409,'La revisión cambió. Volvé a abrir la prestación.')
        previous = conn.execute('SELECT * FROM csv_coverage_reviews WHERE actor_id=? AND request_id=?',
                                (actor['id'],request_id)).fetchone()
        if previous:
            if (previous['revision_id'],previous['source_row'],previous['evidence_sha256'],previous['note']) != (
                    revision_id,number,evidence_sha256,note):
                raise Problem(409,'La operación ya identifica otra revisión del aval.')
            return {'id':previous['id'],'replayed':True,'dataset_version':ds['version'],
                    'revision_version':batch['revision_version']}
        check_version(ds,version)
        if batch['state']=='cerrada' or batch['revision_version']!=revision_version:
            raise Problem(409,'La revisión cambió o está cerrada.')
        context = _context(conn,root,dataset_id,batch_id)
        signals = csv_queue_coverage(conn,root,dataset_id,batch_id,[{'source_row':number}],source_context=context)
        signal = signals.get((batch['import_id'],number),{})
        if signal.get('status')!='already_used' or signal.get('review_basis')!=evidence_sha256:
            raise Problem(409,'Cambió el aval o la prestación. Volvé a consultar la evidencia.')
        if signal.get('reviewed'):
            raise Problem(409,'El aviso ya fue revisado con esta evidencia.')
        scope, captures, _ = context
        evidence = {'status':signal['status'],'previous_rows':signal['previous_rows'],
                    'scope_id':scope['id'],'capture_ids':[c['id'] for c in captures]}
        identity = str(uuid4())
        conn.execute('INSERT INTO csv_coverage_reviews VALUES (?,?,?,?,?,?,?,?,?)',
                     (identity,revision_id,number,evidence_sha256,json.dumps(evidence),note,
                      actor['id'],now_utc(),request_id))
        conn.execute('UPDATE datasets SET version=version+1 WHERE id=?',(dataset_id,))
        conn.execute('UPDATE revisions SET version=version+1 WHERE id=?',(revision_id,))
        event(conn,actor['id'],'csv_coverage_reviewed','csv_coverage_review',identity)
        return {'id':identity,'replayed':False,'dataset_version':version+1,'revision_version':revision_version+1}

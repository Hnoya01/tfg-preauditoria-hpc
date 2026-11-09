"""Internal HPC requests. A request never creates a rate or a category."""
import json
from .storage import read_verified
from uuid import uuid4
from .consistent_reads import consistent_read
from .db import transaction
from .proposal_freshness import provider_basis
from .review import _batch
from .service import Problem,authorized_dataset,check_version,event,now_utc


def row_context(conn,dataset_id,batch_id,number):
    batch=_batch(conn,dataset_id,batch_id)
    scope=provider_basis(conn,batch_id)
    if not scope or scope['provider']!='HPC':raise Problem(409,'Confirmá el alcance HPC del lote.')
    raw=conn.execute('SELECT permitted_json FROM invoice_rows WHERE import_id=? AND source_row=?',
                     (batch['import_id'],number)).fetchone()
    if not raw:raise Problem(404,'Prestación inexistente.')
    fields=json.loads(raw[0])
    for w in conn.execute('SELECT field,value_json FROM work_fields WHERE import_id=? AND source_row=?',(batch['import_id'],number)):
        fields[w['field']]=json.loads(w['value_json'])
    return batch,scope,fields


def category_history(conn,token,dataset_id,batch_id,number):
    def read():
        batch,_,fields=row_context(conn,dataset_id,batch_id,number)
        cutoff=None
        if batch['state']=='cerrada':
            row=conn.execute("SELECT json_extract(manifest_json,'$.dataset.version') FROM revision_closures WHERE revision_id=?",(batch['revision_id'],)).fetchone()
            cutoff=row[0] if row and row[0] is not None else 0
        return [dict(r) for r in conn.execute('SELECT h.ordinal,h.family,h.reason,h.source_file,h.source_sha256,h.sheet,h.source_row,h.source_column,'
                'h.created_at,u.username FROM hpc_category_history h JOIN users u ON u.id=h.actor_id '
                'WHERE h.dataset_id=? AND h.code=? AND (? IS NULL OR h.dataset_version<=?) ORDER BY h.ordinal',
                (dataset_id,fields.get('E'),cutoff,cutoff))]
    return consistent_read(conn,token,dataset_id,read)


def history_file(conn,root,token,dataset_id,batch_id,number,ordinal):
    def read():
        rows=category_history(conn,token,dataset_id,batch_id,number)
        row=next((r for r in rows if r['ordinal']==ordinal),None)
        if not row:raise Problem(404,'Versión inexistente en esta revisión.')
        try:return row['source_file'],read_verified(root,row['source_sha256'])
        except (OSError,ValueError,RuntimeError) as exc:raise Problem(409,'El respaldo no se pudo verificar.') from exc
    return consistent_read(conn,token,dataset_id,read)


def target(conn,dataset_id,source_id,kind,code):
    if kind=='category':
        row=conn.execute('SELECT ordinal FROM hpc_category_history WHERE dataset_id=? AND code=? ORDER BY ordinal DESC LIMIT 1',(dataset_id,code)).fetchone()
        return f'{code} · versión {row[0]}' if row else None
    row=conn.execute('SELECT p.id FROM local_hpc_practices p WHERE dataset_id=? AND source_id=? AND code=? '
                     'AND (SELECT active FROM local_hpc_versions WHERE practice_id=p.id ORDER BY ordinal DESC LIMIT 1)=1',
                     (dataset_id,source_id,code)).fetchone()
    return row[0] if row else None


def create(conn,token,dataset_id,batch_id,number,*,version,revision,code,kind,reason):
    with transaction(conn):
        actor,ds=authorized_dataset(conn,token,dataset_id,'reviewer');check_version(ds,version)
        batch,scope,fields=row_context(conn,dataset_id,batch_id,number)
        if batch['state']=='cerrada' or batch['revision_version']!=revision or not code or fields.get('E')!=code:
            raise Problem(409,'La fila cambió o la revisión está cerrada.')
        if kind not in ('category','agreement') or not 10<=len(reason.strip())<=2000:raise Problem(422,'Elegí el tipo y explicá el motivo.')
        if target(conn,dataset_id,scope['source_id'],kind,code):raise Problem(409,'Ya existe el alta para ese código.')
        pending=conn.execute('SELECT r.id FROM practice_requests r LEFT JOIN practice_request_outcomes o ON o.request_id=r.id '
                   'WHERE r.dataset_id=? AND r.code=? AND r.kind=? AND (?=\'category\' OR r.source_id=?) AND o.request_id IS NULL',
                   (dataset_id,code,kind,kind,scope['source_id'])).fetchone()
        if pending:raise Problem(409,'Ya hay una solicitud pendiente. Consultá Solicitudes de alta.')
        identity=str(uuid4())
        conn.execute('INSERT INTO practice_requests VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                     (identity,dataset_id,batch_id,scope['source_id'],number,code,fields.get('K') or '',kind,reason.strip(),actor['id'],now_utc()))
        conn.execute('UPDATE datasets SET version=version+1 WHERE id=?',(dataset_id,))
        event(conn,actor['id'],'practice_requested','practice_request',identity)
        return {'id':identity,'dataset_version':version+1}


def listing(conn,token,dataset_id):
    def read():
        _,ds=authorized_dataset(conn,token,dataset_id,'reviewer')
        rows=conn.execute('SELECT r.*,u.username AS requester,b.original_name,o.state,o.reason AS answer,o.target,o.created_at AS answered_at,'
                          'a.username AS answered_by FROM practice_requests r JOIN users u ON u.id=r.actor_id JOIN batches b ON b.id=r.batch_id '
                          'LEFT JOIN practice_request_outcomes o ON o.request_id=r.id LEFT JOIN users a ON a.id=o.actor_id '
                          'WHERE r.dataset_id=? ORDER BY (o.state IS NULL) DESC,r.created_at DESC,r.rowid DESC',(dataset_id,))
        return {'items':[dict(row) for row in rows],'dataset_version':ds['version']}
    return consistent_read(conn,token,dataset_id,read)


def answer(conn,token,dataset_id,identity,*,version,state,reason):
    with transaction(conn):
        actor,ds=authorized_dataset(conn,token,dataset_id,'admin');check_version(ds,version)
        req=conn.execute('SELECT * FROM practice_requests WHERE id=? AND dataset_id=?',(identity,dataset_id)).fetchone()
        if not req:raise Problem(404,'Solicitud inexistente.')
        if conn.execute('SELECT 1 FROM practice_request_outcomes WHERE request_id=?',(identity,)).fetchone():
            raise Problem(409,'La solicitud ya tiene respuesta.')
        if state not in ('registered','declined') or not 10<=len(reason.strip())<=2000:raise Problem(422,'Indicá el resultado y el motivo.')
        linked=None
        if state=='registered':
            linked=target(conn,dataset_id,req['source_id'],req['kind'],req['code'])
            if linked is None:raise Problem(409,'Primero registrá el alta documentada para este código y alcance.')
        conn.execute('INSERT INTO practice_request_outcomes VALUES (?,?,?,?,?,?)',(identity,state,linked,reason.strip(),actor['id'],now_utc()))
        conn.execute('UPDATE datasets SET version=version+1 WHERE id=?',(dataset_id,))
        event(conn,actor['id'],'practice_request_answered','practice_request',identity)
        return {'dataset_version':version+1}

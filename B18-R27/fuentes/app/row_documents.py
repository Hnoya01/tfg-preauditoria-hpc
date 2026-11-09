"""Manual documentary support. Upload/read does not establish clinical compliance."""
import hashlib
import json
import re
from uuid import uuid4
from .db import transaction
from .consistent_reads import consistent_read
from .review import _batch
from .security import now_utc
from .service import Problem, authorized_dataset, check_version, event, validate_filename
from .storage import publish_bytes, read_verified

MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
LIMIT = 'Documento aportado para revisión manual; no acredita autorización, realización ni cumplimiento clínico y no ejecuta controles.'


def _text(value, minimum, maximum):
    if not isinstance(value,str) or not minimum <= len(value.strip()) <= maximum or '\x00' in value:
        raise Problem(422,'Texto documental inválido')
    return value.strip()


def _context(conn, token, dataset_id, batch_id, source_row):
    actor,dataset=authorized_dataset(conn,token,dataset_id,'reviewer')
    batch=_batch(conn,dataset_id,batch_id)
    if conn.execute('SELECT 1 FROM invoice_rows WHERE import_id=? AND source_row=?',(batch['import_id'],source_row)).fetchone() is None:
        raise Problem(404,'Fila inexistente')
    return actor,dataset,batch


def _writable(dataset,batch,dataset_version,revision_version,revision_id):
    check_version(dataset,dataset_version)
    if batch['revision_id']!=revision_id or batch['revision_version']!=revision_version or batch['state']=='cerrada':
        raise Problem(409,'La revisión cambió o está cerrada; actualizá la vista')


def _stamp(conn,dataset_id,batch):
    conn.execute('UPDATE datasets SET version=version+1 WHERE id=?',(dataset_id,))
    conn.execute('UPDATE revisions SET version=version+1 WHERE id=?',(batch['revision_id'],))


def _hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def _retry(conn,table,actor_id,request_id,digest):
    row=conn.execute(f'SELECT id,request_sha256 FROM {table} WHERE actor_id=? AND request_id=?',(actor_id,request_id)).fetchone()
    if row and row['request_sha256']!=digest: raise Problem(409,'Identificador de operación reutilizado con otro contenido')
    return row


def _result(identifier,dataset,batch,created):
    return {'id':identifier,'created':created,'dataset_version':dataset['version']+int(created),
            'revision_version':batch['revision_version']+int(created),'use_limit':LIMIT}


def register(conn,root,token,dataset_id,batch_id,source_row,*,expected_dataset_version,expected_revision_version,
             revision_id,request_id,category,original_name,provenance,expected_sha256,content):
    request_id=_text(request_id,16,100);provenance=_text(provenance,10,2000)
    original_name=validate_filename(original_name)
    if category not in ('informe','autorizacion') or not original_name.lower().endswith('.pdf'):
        raise Problem(422,'Categoría o nombre de PDF inválido')
    if len(content)>MAX_DOCUMENT_BYTES: raise Problem(413,'El PDF supera 10 MiB')
    if len(content)<20 or not content.startswith(b'%PDF-') or b'%%EOF' not in content[-2048:]:
        raise Problem(422,'No se reconoce un PDF completo')
    sha=hashlib.sha256(content).hexdigest()
    if expected_sha256!=sha: raise Problem(422,'El hash del PDF no coincide')
    payload={k:v for k,v in locals().copy().items() if k not in ('conn','root','token','content')}
    digest=_hash(payload)
    with transaction(conn):
        actor,dataset,batch=_context(conn,token,dataset_id,batch_id,source_row)
        old=_retry(conn,'row_documents',actor['id'],request_id,digest)
        if old:return _result(old['id'],dataset,batch,False)
        _writable(dataset,batch,expected_dataset_version,expected_revision_version,revision_id)
        duplicate=conn.execute('SELECT id FROM row_documents WHERE import_id=? AND source_row=? AND category=? AND sha256=?',
            (batch['import_id'],source_row,category,sha)).fetchone()
        if duplicate:return _result(duplicate['id'],dataset,batch,False)
        try: sha,size,relative=publish_bytes(root,content)
        except (OSError,RuntimeError) as exc:raise Problem(409,'No se pudo conservar el original') from exc
        stamp=now_utc();identifier=str(uuid4())
        conn.execute('INSERT OR IGNORE INTO stored_files VALUES (?,?,?,?)',(sha,size,relative,stamp))
        conn.execute('INSERT INTO row_documents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (identifier,dataset_id,batch['import_id'],source_row,revision_id,category,sha,original_name,provenance,actor['id'],stamp,request_id,digest))
        _stamp(conn,dataset_id,batch);event(conn,actor['id'],'row_document_registered','row_document',identifier)
        return _result(identifier,dataset,batch,True)


def records(conn,import_id,source_row,revision_id=None):
    if conn.execute('PRAGMA user_version').fetchone()[0]<28:return []
    items=[]
    cutoff=conn.execute('SELECT ordinal FROM revisions WHERE id=?',(revision_id,)).fetchone()[0] if revision_id else 2147483647
    for row in conn.execute('SELECT d.*,u.username AS actor_username FROM row_documents d JOIN users u ON u.id=d.actor_id WHERE import_id=? AND source_row=? AND (SELECT ordinal FROM revisions WHERE id=d.revision_id)<=? ORDER BY d.created_at,d.rowid',(import_id,source_row,cutoff)):
        item=dict(row);item.pop('request_sha256');item.pop('request_id')
        item['reviews']=[dict(r) for r in conn.execute('SELECT r.id,r.revision_id,r.note,r.created_at,u.username AS actor_username FROM row_document_reviews r JOIN users u ON u.id=r.actor_id WHERE document_id=? AND (SELECT ordinal FROM revisions WHERE id=r.revision_id)<=? ORDER BY r.created_at,r.rowid',(row['id'],cutoff))]
        item['state']='revisado_manualmente' if item['reviews'] else 'aportado_sin_revisar'
        items.append(item)
    return items


def summary(conn,import_id,source_row,revision_id=None):
    items=records(conn,import_id,source_row,revision_id)
    return {category: {'count':len(group),'state':('no_aportado' if not group else 'revisado_manualmente' if all(d['reviews'] for d in group) else 'aportado_sin_revisar')} for category in ('informe','autorizacion') for group in [[d for d in items if d['category']==category]]}



def batch_summary(conn, import_id, revision_id):
    """Bounded aggregate query, independent of invoice row count. No file reads/writes."""
    if conn.execute('PRAGMA user_version').fetchone()[0] < 28:
        return {}
    cutoff = conn.execute('SELECT ordinal FROM revisions WHERE id=?', (revision_id,)).fetchone()
    if cutoff is None:
        raise Problem(404, 'Revisión inexistente')
    result = {}
    rows = conn.execute(
        "WITH reviewed_documents AS (SELECT DISTINCT r.document_id "
        "FROM row_document_reviews r JOIN revisions rr ON rr.id=r.revision_id "
        "JOIN row_documents rd ON rd.id=r.document_id WHERE rd.import_id=? AND rr.ordinal<=?) "
        "SELECT d.source_row,d.category,count(*) AS total,"
        "sum(CASE WHEN reviewed.document_id IS NOT NULL THEN 1 ELSE 0 END) AS reviewed "
        "FROM row_documents d JOIN revisions dr ON dr.id=d.revision_id "
        "LEFT JOIN reviewed_documents reviewed ON reviewed.document_id=d.id "
        "WHERE d.import_id=? AND dr.ordinal<=? GROUP BY d.source_row,d.category",
        (import_id, cutoff['ordinal'], import_id, cutoff['ordinal']))
    for row in rows:
        result.setdefault(row['source_row'], {})[row['category']] = {
            'count': row['total'],
            'state': 'revisado_manualmente' if row['reviewed'] == row['total'] else 'aportado_sin_revisar'}
    return result


def empty_summary():
    return {category: {'count': 0, 'state': 'no_aportado'} for category in ('informe', 'autorizacion')}

def history(conn,token,dataset_id,batch_id,source_row):
    def read():
        _,dataset,batch=_context(conn,token,dataset_id,batch_id,source_row)
        return {'items':records(conn,batch['import_id'],source_row,batch['revision_id']),'summary':summary(conn,batch['import_id'],source_row,batch['revision_id']),
                'dataset_version':dataset['version'],'revision_version':batch['revision_version'],'revision_id':batch['revision_id'],
                'writable':batch['state']!='cerrada','use_limit':LIMIT}
    return consistent_read(conn,token,dataset_id,read)


def review(conn,root,token,dataset_id,batch_id,source_row,document_id,*,expected_dataset_version,expected_revision_version,revision_id,request_id,note):
    request_id=_text(request_id,16,100);note=_text(note,10,2000)
    digest=_hash({k:v for k,v in locals().copy().items() if k not in ('conn','root','token')})
    with transaction(conn):
        actor,dataset,batch=_context(conn,token,dataset_id,batch_id,source_row)
        old=_retry(conn,'row_document_reviews',actor['id'],request_id,digest)
        if old:return _result(old['id'],dataset,batch,False)
        _writable(dataset,batch,expected_dataset_version,expected_revision_version,revision_id)
        document=conn.execute('SELECT sha256 FROM row_documents WHERE id=? AND dataset_id=? AND import_id=? AND source_row=?',(document_id,dataset_id,batch['import_id'],source_row)).fetchone()
        if document is None:raise Problem(404,'Documento inexistente en esta fila')
        try:read_verified(root,document['sha256'])
        except (OSError,RuntimeError) as exc:raise Problem(409,'El original no supera la comprobación de integridad') from exc
        identifier=str(uuid4())
        conn.execute('INSERT INTO row_document_reviews VALUES (?,?,?,?,?,?,?,?)',(identifier,document_id,revision_id,note,actor['id'],now_utc(),request_id,digest))
        _stamp(conn,dataset_id,batch);event(conn,actor['id'],'row_document_manually_reviewed','row_document',document_id)
        return _result(identifier,dataset,batch,True)


def original(conn,root,token,dataset_id,document_id):
    authorized_dataset(conn,token,dataset_id,'reviewer')
    row=conn.execute('SELECT sha256 FROM row_documents WHERE id=? AND dataset_id=?',(document_id,dataset_id)).fetchone()
    if row is None:raise Problem(404,'Documento inexistente')
    try:return read_verified(root,row['sha256']),row['sha256']
    except (OSError,RuntimeError) as exc:raise Problem(409,'El original no supera la comprobación de integridad') from exc


def export_records(conn,import_id,revision_id):
    """Stable revision-bounded metadata and manual reading history for frozen ZIPs."""
    if conn.execute('PRAGMA user_version').fetchone()[0]<28:return []
    result=[]
    for row in conn.execute('SELECT DISTINCT source_row FROM row_documents WHERE import_id=? ORDER BY source_row',(import_id,)):
        result.extend(records(conn,import_id,row['source_row'],revision_id))
    return result

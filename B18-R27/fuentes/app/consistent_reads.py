"""Public multi-query reads own one snapshot and recheck access outside it."""
from .service import authorized_dataset,check_version,Problem


def consistent_read(conn,token,dataset_id,reader,*,after_read=None):
    if conn.in_transaction:
        authorized_dataset(conn,token,dataset_id,'reviewer')
        return reader()
    conn.execute('BEGIN')
    try:
        _,dataset=authorized_dataset(conn,token,dataset_id,'reviewer')
        versions=_revisions(conn,dataset_id)
        result=reader()
    finally:conn.rollback()
    if after_read:after_read()
    _,current=authorized_dataset(conn,token,dataset_id,'reviewer')
    check_version(current,dataset['version'])
    if _revisions(conn,dataset_id)!=versions:raise Problem(409,'La revisión cambió durante la lectura; actualizar')
    return result


def _revisions(conn,dataset_id):
    return [tuple(r) for r in conn.execute('SELECT r.id,r.version,r.state FROM revisions r '
            'JOIN batches b ON b.id=r.batch_id WHERE b.dataset_id=? ORDER BY r.id',(dataset_id,))]

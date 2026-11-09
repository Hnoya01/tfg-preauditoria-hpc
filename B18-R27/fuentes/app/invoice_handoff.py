"""Close administrative editing of a revision and deliver its decisions to the auditor."""
from decimal import Decimal
from .consistent_reads import consistent_read
from .db import transaction
from .review import _batch
from .security import now_utc
from .service import Problem, authorized_dataset, check_version, event

LOCK_MESSAGE = 'La factura ya pasó al auditor. La revisión administrativa está cerrada.'


def assigned_duty(conn, user, dataset_id):
    if user['role'] == 'admin':
        return 'admin'
    row = conn.execute('SELECT duty FROM invoice_review_duties WHERE dataset_id=? AND user_id=?',
                       (dataset_id,user['id'])).fetchone()
    return row['duty'] if row and user['role']=='reviewer' else None


def receipt(conn, revision_id):
    return conn.execute('SELECT h.*,u.username AS sender FROM invoice_handoffs h JOIN users u '
                        'ON u.id=h.actor_id WHERE h.revision_id=?',(revision_id,)).fetchone()


def handoff_stage(conn,revision):
    return 'closed' if conn.execute('SELECT 1 FROM audit_invoice_closures WHERE revision_id=?',(revision,)).fetchone() else 'auditor'


def public_receipt(record):
    return {key:record[key] for key in ('revision_id','sent_at','sender','receipt_count','debit_total_ars')}


def assess(conn, root, token, dataset_id, batch_id, *, collect=False):
    from .practice_board import practice_search
    # Match the entire imaging queue, even if the operator is on a later page or has filters active.
    filters={'family':'images','scope':'included','view':'exceptions','limit':1}
    if collect:
        filters['_handoff_members']=True
    board=practice_search(conn,token,dataset_id,batch_id,filters,root=root)
    assessment=assessment_for_board(conn,batch_id,board)
    if collect:
        assessment['scope']=board['_audit_scope']
    return assessment,board.get('_handoff_members',[])


def assessment_for_board(conn,batch_id,board):
    counts=board['row_decision_counts']
    batch=board['batch']
    reason=None
    if batch['revision_state']=='cerrada':
        reason='La revisión ya tiene un cierre definitivo.'
    elif batch['provider']!='HPC' or not board['classification']['available'] or board['classification']['source_unavailable']:
        reason='Falta confirmar HPC o verificar la clasificación de Imágenes.'
    elif batch['run_technical_state']!='completed':
        reason='Falta analizar la factura.'
    elif conn.execute("SELECT 1 FROM processing_attempts WHERE batch_id=? AND state IN ('queued','running')",(batch_id,)).fetchone():
        reason='Esperá a que termine el procesamiento de la factura.'
    elif counts['pending']:
        n=counts['pending']
        reason=f'Queda 1 prestación de Imágenes pendiente.' if n==1 else f'Quedan {n} prestaciones de Imágenes pendientes.'
    return {'pending':counts['pending'],'reviewed':counts['reviewed'],'reason':reason}


def board_status(conn,user,dataset_id,batch_id,batch,board):
    duty=assigned_duty(conn,user,dataset_id)
    base={'duty':duty,'dataset_version':board['dataset_version'],'revision_id':batch['revision_id'],
          'revision_version':batch['revision_version'],'can_send':False}
    record=receipt(conn,batch['revision_id'])
    if record:
        return {**base,'state':handoff_stage(conn,record['revision_id']),'receipt':public_receipt(record)}
    if duty not in ('administrative','admin'):
        return {**base,'state':'administrative'}
    f=board['filters']
    # Sort, pagination and the reason chip do not change the counters. Other filters can.
    if (f.get('scope','included')=='included' and f.get('family')=='images'
        and f.get('view') in ('exceptions','row_reviewed') and not f.get('rules')
        and not any(f.get(k) for k in ('rule','reason','state','decision','code','text','search','date_from','date_to','_number'))
        and all(f.get(k,'all')=='all' for k in ('report_document_state','authorization_document_state','reference_comparison_state','csv_review_state'))):
        assessment=assessment_for_board(conn,batch_id,board)
        return {**base,**assessment,'state':'administrative','can_send':not assessment['reason']}
    return None


def status(conn,root,token,dataset_id,batch_id):
    def read():
        user,ds=authorized_dataset(conn,token,dataset_id,'reviewer')
        batch=_batch(conn,dataset_id,batch_id)
        duty=assigned_duty(conn,user,dataset_id)
        base={'duty':duty,'dataset_version':ds['version'],'revision_id':batch['revision_id'],
              'revision_version':batch['revision_version'],'can_send':False}
        record=receipt(conn,batch['revision_id'])
        if record:
            return {**base,'state':handoff_stage(conn,record['revision_id']),'receipt':public_receipt(record)}
        if duty not in ('admin','administrative'):
            return {**base,'state':'administrative'}
        assessment,_=assess(conn,root,token,dataset_id,batch_id)
        return {**base,**assessment,'state':'administrative','can_send':not assessment['reason']}
    return consistent_read(conn,token,dataset_id,read)


def send(conn,root,token,dataset_id,batch_id,body):
    with transaction(conn):
        user,ds=authorized_dataset(conn,token,dataset_id,'reviewer')
        if assigned_duty(conn,user,dataset_id) not in ('administrative','admin'):
            raise Problem(403,'Solo la función administrativa puede pasar la factura al auditor.')
        batch=_batch(conn,dataset_id,batch_id)
        revision=batch['revision_id']
        if revision!=body['revision_id']:
            raise Problem(409,'Cambió la revisión de la factura.')
        prior=receipt(conn,revision)
        if prior:
            if prior['actor_id']==user['id'] and prior['request_id']==body['request_id']:
                return public_receipt(prior)
            raise Problem(409,LOCK_MESSAGE)
        check_version(ds,body['expected_dataset_version'])
        if batch['revision_version']!=body['expected_revision_version']:
            raise Problem(409,'La revisión cambió. Actualizá la factura.')
        if conn.execute('SELECT 1 FROM invoice_handoffs WHERE actor_id=? AND request_id=?',(user['id'],body['request_id'])).fetchone():
            raise Problem(409,'La operación identifica otra factura.')
        assessment,members=assess(conn,root,token,dataset_id,batch_id,collect=True)
        if assessment['reason']:
            raise Problem(409,assessment['reason'])
        total=sum((Decimal(row['amount_ars']) for row in members),Decimal(0))
        conn.execute('UPDATE revisions SET version=version+1 WHERE id=?',(revision,))
        conn.execute('UPDATE datasets SET version=version+1 WHERE id=?',(dataset_id,))
        conn.execute('INSERT INTO invoice_handoffs VALUES(?,?,?,?,?,?)',
                     (revision,user['id'],now_utc(),body['request_id'],len(members),format(total,'.2f')))
        conn.executemany('INSERT INTO invoice_handoff_rows VALUES(?,?,?,?,?,?,?,?)',
                         [(revision,r['source_row'],r['ordinal'],r['practice_date'],r['order_number'],
                           r['code'],r['description'],r['total_ars']) for r in members])
        from .invoice_audit import save_scope
        save_scope(conn,revision,assessment['scope'])
        event(conn,user['id'],'invoice_passed_to_auditor','revision',revision)
        return public_receipt(receipt(conn,revision))


def inbox(conn,token,dataset_id):
    def read():
        user,_=authorized_dataset(conn,token,dataset_id,'reviewer')
        if assigned_duty(conn,user,dataset_id) not in ('auditor','admin'):
            raise Problem(403,'Se requiere la función de auditor.')
        rows=conn.execute('SELECT b.id AS batch_id,b.original_name,h.revision_id,h.receipt_count,h.debit_total_ars,h.sent_at,c.closed_at '
                          'FROM invoice_handoffs h JOIN revisions r ON r.id=h.revision_id JOIN batches b ON b.id=r.batch_id '
                          'LEFT JOIN audit_invoice_closures c ON c.revision_id=h.revision_id '
                          'WHERE b.dataset_id=? ORDER BY (c.closed_at IS NOT NULL),h.sent_at DESC,h.revision_id',(dataset_id,)).fetchall()
        return {'items':[dict(r) for r in rows]}
    return consistent_read(conn,token,dataset_id,read)


def received(conn,token,dataset_id,batch_id,offset,limit):
    def read():
        user,_=authorized_dataset(conn,token,dataset_id,'reviewer')
        if assigned_duty(conn,user,dataset_id) not in ('auditor','admin','administrative'):
            raise Problem(403,'Sin función asignada para consultar el pase.')
        revision=_batch(conn,dataset_id,batch_id)['revision_id']
        record=receipt(conn,revision)
        if not record:
            raise Problem(404,'La factura todavía está en revisión administrativa.')
        rows=conn.execute('SELECT s.source_row,s.practice_date,s.order_number,s.code,s.description,s.billed_ars,'
                          'd.ordinal,d.action,d.amount_ars,d.reason,d.correction_note,u.username AS actor '
                          'FROM invoice_handoff_rows s JOIN invoice_row_decisions d USING(revision_id,source_row,ordinal) '
                          'JOIN users u ON u.id=d.actor_id WHERE s.revision_id=? ORDER BY s.source_row LIMIT ? OFFSET ?',
                          (revision,limit,offset)).fetchall()
        return {**public_receipt(record),'offset':offset,'limit':limit,'items':[dict(r) for r in rows]}
    return consistent_read(conn,token,dataset_id,read)


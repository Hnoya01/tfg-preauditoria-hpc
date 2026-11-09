"""Cierre humano de Imágenes. No ejecuta operaciones sobre sistemas institucionales."""
import hashlib
import json
import re
from decimal import Decimal
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from .consistent_reads import consistent_read
from .db import transaction
from .invoice_handoff import assigned_duty, assess, receipt
from .review import _batch
from .security import now_utc
from .service import Problem, authorized_dataset, check_version, event


def money(value):
    return format(value,'.2f')


def amount(text):
    if not isinstance(text,str) or not re.fullmatch(r'[0-9]{1,16}(?:[.][0-9]{1,2})?',text):
        raise Problem(422,'Ingresá un importe no negativo en ARS, con hasta dos decimales.')
    return Decimal(text)


def scope_snapshot(conn,import_id,rows):
    images=sorted((r['source_row'],r['total_ars']) for r in rows
                  if r['disposition']=='included' and r['family']=='images')
    invoice=sum((Decimal(r[0]) for r in conn.execute('SELECT total_ars FROM invoice_rows WHERE import_id=?',(import_id,))),Decimal(0))
    return {'invoice_ars':money(invoice),'images_ars':money(sum((Decimal(v) for _,v in images),Decimal(0))),
            'image_count':len(images),'scope_hash':hashlib.sha256(json.dumps(images).encode()).hexdigest()}


def save_scope(conn,revision,scope):
    conn.execute('INSERT INTO audit_invoice_scope VALUES(?,?,?,?,?)',
                 (revision,scope['invoice_ars'],scope['images_ars'],scope['image_count'],scope['scope_hash']))


def frozen_scope(conn,rev):
    row=conn.execute('SELECT invoice_ars,images_ars,image_count,scope_hash FROM audit_invoice_scope WHERE revision_id=?',(rev,)).fetchone()
    return dict(row) if row else None


def verify_evidence(conn,root,token,ds,batch,rev):
    check,members=assess(conn,root,token,ds,batch,collect=True)
    expected={tuple(r) for r in conn.execute('SELECT source_row,ordinal FROM invoice_handoff_rows WHERE revision_id=?',(rev,))}
    if check['reason'] or {(m['source_row'],m['ordinal']) for m in members}!=expected:
        raise Problem(409,'El pase ya no coincide con la evidencia vigente. No se puede confirmar el cierre.')
    scope=check['scope']
    old=frozen_scope(conn,rev)
    if old and old!=scope:
        raise Problem(409,'Cambió el alcance de Imágenes desde el pase. No se puede confirmar el cierre.')
    return scope


def access(conn,token,ds,batch,*,audit=False):
    user,dataset=authorized_dataset(conn,token,ds,'reviewer')
    duty=assigned_duty(conn,user,ds)
    if duty not in (('auditor',) if audit else ('auditor','administrative','admin')):
        raise Problem(403,'Se requiere la función de auditor asignada a esta factura.')
    rev=_batch(conn,ds,batch)['revision_id']
    if not receipt(conn,rev):
        raise Problem(409,'Primero debe cerrarse la revisión administrativa.')
    return user,dataset,rev,duty


def rows(conn,rev):
    result=[dict(r) for r in conn.execute("""
        SELECT s.source_row,s.practice_date,s.order_number,s.code,s.description,s.billed_ars,
               d.action,d.amount_ars,d.reason,d.basis_json,coalesce(a.amount_ars,d.amount_ars) final_ars,
               coalesce(a.reason,d.reason) final_reason,coalesce(a.seq,0) adjustments
          FROM invoice_handoff_rows s JOIN invoice_row_decisions d USING(revision_id,source_row,ordinal)
          LEFT JOIN audit_adjustments a ON a.revision_id=s.revision_id AND a.source_row=s.source_row
            AND a.seq=(SELECT max(v.seq) FROM audit_adjustments v
                       WHERE v.revision_id=s.revision_id AND v.source_row=s.source_row)
          WHERE s.revision_id=? ORDER BY s.source_row""",(rev,))]
    for row in result:
        budget=json.loads(row.pop('basis_json')).get('budget') or {}
        row['budget_note']=('Presupuesto en ARS '+budget['authorized_ars']+' · '+budget['locator']+' · '+budget['reason']) if budget.get('link_id') else None
    return result


def totals(scope,items):
    debit=sum((Decimal(r['final_ars']) for r in items),Decimal(0))
    return {**{k:scope[k] for k in ('invoice_ars','images_ars','image_count')},
            'debit_ars':money(debit),'net_ars':money(Decimal(scope['images_ars'])-debit),
            'debited_count':sum(Decimal(r['final_ars'])>0 for r in items)}


def closure(conn,rev):
    return conn.execute('SELECT c.closed_at,c.request_id,c.actor_id,c.debit_ars,c.net_ars,c.debited_count,u.username AS auditor '
                        'FROM audit_invoice_closures c JOIN users u ON u.id=c.actor_id WHERE revision_id=?',(rev,)).fetchone()


def public_close(record):
    return {k:record[k] for k in ('closed_at','auditor','debit_ars','net_ars','debited_count')}


def summary(conn,root,token,ds,batch,offset,limit):
    def read():
        _,dataset,rev,duty=access(conn,token,ds,batch)
        scope=frozen_scope(conn,rev) or verify_evidence(conn,root,token,ds,batch,rev)
        items=rows(conn,rev)
        record=closure(conn,rev)
        return {**totals(scope,items),'revision_id':rev,'dataset_version':dataset['version'],
                'closed':public_close(record) if record else None,'can_adjust':duty=='auditor' and not record,
                'receipt_count':len(items),'items':items[offset:offset+limit],'offset':offset,'limit':limit}
    return consistent_read(conn,token,ds,read)


def adjust(conn,token,ds,batch,number,body):
    with transaction(conn):
        user,dataset,rev,_=access(conn,token,ds,batch,audit=True)
        if body['revision_id']!=rev or closure(conn,rev):
            raise Problem(409,'La revisión cambió o ya está cerrada.')
        check_version(dataset,body['expected_dataset_version'])
        row=next((r for r in rows(conn,rev) if r['source_row']==number),None)
        if not row:
            raise Problem(404,'La prestación no forma parte del pase.')
        value=amount(body['amount_ars'])
        reason=body['reason'].strip()
        if not reason or ILLEGAL_CHARACTERS_RE.search(reason) or any(c in reason for c in ('\ufffe','\uffff')):
            raise Problem(422,'Indicá un motivo final válido para el ajuste.')
        if value>Decimal(row['billed_ars']):
            raise Problem(422,'El débito no puede superar lo facturado por esta prestación.')
        if value!=Decimal(row['final_ars']) and reason==row['final_reason']:
            raise Problem(422,'Al cambiar el importe, indicá el motivo del ajuste.')
        if value==Decimal(row['final_ars']) and reason==row['final_reason']:
            raise Problem(422,'No hay cambios para guardar.')
        conn.execute('INSERT INTO audit_adjustments VALUES(?,?,?,?,?,?,?)',
                     (rev,number,row['adjustments']+1,user['id'],now_utc(),money(value),reason))
        conn.execute('UPDATE datasets SET version=version+1 WHERE id=?',(ds,))
        event(conn,user['id'],'invoice_auditor_adjusted','revision',rev)
        return {'source_row':number,'amount_ars':money(value),'dataset_version':dataset['version']+1}


def workbook(items,batch,rev):
    wb=Workbook();sheet=wb.active;sheet.title='Débitos de Imágenes'
    wb.properties.title='Cierre de preauditoría de Imágenes HPC'
    wb.properties.description=f'Lote {batch}; revisión {rev}. Importes en ARS.'
    sheet.append(['Orden','Importe final (ARS)','Motivo final'])
    for cell in sheet[1]:cell.font=Font(bold=True)
    for r in items:
        if Decimal(r['final_ars'])<=0:continue
        sheet.append([r['order_number'],Decimal(r['final_ars']),r['final_reason']])
        line=sheet.max_row
        # Text from sources and operator input is never an Excel formula.
        for col in ('A','C'):sheet[f'{col}{line}'].data_type='s'
        sheet[f'B{line}'].number_format='#,##0.00'
    sheet.freeze_panes='A2';sheet.auto_filter.ref=sheet.dimensions
    for col,width in [('A',24),('B',23),('C',85)]:sheet.column_dimensions[col].width=width
    buf=BytesIO();wb.save(buf);wb.close()
    return buf.getvalue()


def confirm(conn,root,token,ds,batch,body):
    with transaction(conn):
        user,dataset,rev,_=access(conn,token,ds,batch,audit=True)
        if body['revision_id']!=rev:
            raise Problem(409,'Cambió la revisión de la factura.')
        expected=amount(body['expected_debit_ars'])
        prior=closure(conn,rev)
        if prior:
            if prior['actor_id']==user['id'] and prior['request_id']==body['request_id'] and expected==Decimal(prior['debit_ars']):
                return public_close(prior)
            raise Problem(409,'La factura ya tiene un cierre confirmado.')
        check_version(dataset,body['expected_dataset_version'])
        if conn.execute('SELECT 1 FROM audit_invoice_closures WHERE actor_id=? AND request_id=?',(user['id'],body['request_id'])).fetchone():
            raise Problem(409,'La confirmación identifica otra factura.')
        scope=verify_evidence(conn,root,token,ds,batch,rev)
        if not frozen_scope(conn,rev):save_scope(conn,rev,scope)
        items=rows(conn,rev);total=totals(scope,items)
        if expected!=Decimal(total['debit_ars']):
            raise Problem(409,'El total cambió. Actualizá el resumen antes de confirmar.')
        payload=workbook(items,batch,rev)
        from .image_reports import freeze
        freeze(conn,root,token,ds,batch,rev,user,payload)
        conn.execute('INSERT INTO audit_invoice_closures VALUES(?,?,?,?,?,?,?,?,?)',
                     (rev,user['id'],now_utc(),body['request_id'],total['debit_ars'],total['net_ars'],total['debited_count'],
                      payload,hashlib.sha256(payload).hexdigest()))
        conn.execute('UPDATE datasets SET version=version+1 WHERE id=?',(ds,))
        event(conn,user['id'],'invoice_auditor_closed','revision',rev)
        return public_close(closure(conn,rev))


def download(conn,token,ds,batch,revision=None):
    def read():
        user,_=authorized_dataset(conn,token,ds,'reviewer')
        if assigned_duty(conn,user,ds)!='auditor':
            raise Problem(403,'Se requiere la función de auditor.')
        current=_batch(conn,ds,batch)
        rev=revision or current['revision_id']
        if not conn.execute('SELECT 1 FROM revisions WHERE batch_id=? AND id=?',(batch,rev)).fetchone():
            raise Problem(404,'Revisión inexistente en esta factura.')
        record=conn.execute('SELECT workbook,sha256 FROM audit_invoice_closures WHERE revision_id=?',(rev,)).fetchone()
        if not record:raise Problem(409,'El Excel se habilita después del cierre del auditor.')
        content=record['workbook']
        if hashlib.sha256(content).hexdigest()!=record['sha256']:
            raise Problem(409,'No se pudo verificar el Excel conservado.')
        return content
    return consistent_read(conn,token,ds,read)


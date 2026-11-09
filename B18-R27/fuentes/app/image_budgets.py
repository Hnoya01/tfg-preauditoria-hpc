"""Versioned allocation of an order budget to one verified imaging item."""
from decimal import Decimal
from .db import transaction
from .security import now_utc
from .service import Problem, authorized_dataset, check_version, event


def apply_links(conn,dataset,group,signals):
    for row in group:
        signal=signals[row['key']]
        if not signal.get('order_id') or not signal.get('source_sha256'):
            continue
        link=conn.execute("""SELECT l.*,u.username actor FROM image_budget_links l JOIN users u ON u.id=l.actor_id
            JOIN current_invoice_imports i ON i.revision_id=l.revision_id
            WHERE l.dataset_id=? AND l.capture_sha=? AND l.order_id=? ORDER BY l.id DESC LIMIT 1""",
            (dataset,signal['source_sha256'],signal['order_id'])).fetchone()
        if not link:continue
        if link['item_locator']!=signal.get('locator'):
            if (signal.get('budget') or {}).get('status')=='por_verificar':
                signal['budget']={**signal['budget'],'status':'otro_item','assigned_link_id':link['id'], 'reason':'El presupuesto se vinculó a otra práctica de la orden.'}
            continue
        current=conn.execute('SELECT revision_id FROM current_invoice_imports WHERE id=?',(row['key'][0],)).fetchone()
        if (not current or link['revision_id']!=current[0] or link['source_row']!=row['key'][1]
                or link['performed_on']!=row['day'].isoformat() or link['units']!=Decimal(str(row['quantity']))
                or signal['status'] not in ('one_unit_supported','units_supported')):
            continue
        billed=Decimal(row['billed'])
        excess=max(Decimal('0'),billed-Decimal(link['amount_ars']))
        signal['budget']={**(signal.get('budget') or {}),'status':'over' if excess else 'within',
            'authorized_ars':link['amount_ars'],'billed_ars':format(billed,'.2f'),'excess_ars':format(excess,'.2f'),
            'order_id':link['order_id'],'locator':link['locator'],'reason':link['reason'],'actor':link['actor'],
            'link_id':link['id'],'authorized_on':signal['authorization_date'],'performed_on':signal['performed_on']}


def bind(conn,root,token,ds,batch,number,body):
    from .row_decisions import detail,has_duty,money
    from .authorization_matching import page_correspondence
    with transaction(conn):
        user,dataset=authorized_dataset(conn,token,ds,'reviewer')
        if not has_duty(conn,user,ds):raise Problem(403,'Se requiere función administrativa.')
        check_version(dataset,body['expected_dataset_version'])
        info=detail(conn,root,token,ds,batch,number)
        if not info['can_write'] or info['revision_id']!=body['revision_id'] or info['evidence_hash']!=body['evidence_hash']:
            raise Problem(409,'Cambió la prestación o la factura ya pasó al auditor.')
        sig=(page_correspondence(conn,root,ds,batch,[number])[number].get('panel_signal') or {}).get('csv_coverage') or {}
        budget=sig.get('budget') or {}
        amount=money(body['amount_ars'])
        if sig.get('status') not in ('one_unit_supported','units_supported') or not sig.get('order_id') or not budget:
            raise Problem(422,'Hace falta un aval individual y un presupuesto localizado en esa orden.')
        if amount is None or not body['locator'].strip() or not body['reason'].strip():
            raise Problem(422,'Indicá el total en ARS, dónde lo verificaste y el motivo.')
        rev=info['revision_id']
        units=sig.get('billed_units',1)
        if units!=sig.get('order_units',1):
            raise Problem(422,'La fila debe comprender toda la cantidad del presupuesto.')
        other=conn.execute("""SELECT l.revision_id,l.source_row,l.item_locator FROM image_budget_links l
          JOIN current_invoice_imports i ON i.revision_id=l.revision_id
          WHERE l.dataset_id=? AND l.capture_sha=? AND l.order_id=? ORDER BY l.id DESC LIMIT 1""",
            (ds,sig['source_sha256'],sig['order_id'])).fetchone()
        if other and tuple(other)!=(rev,number,sig['locator']):
            if other[0]!=rev or not body.get('replace_link') or budget.get('assigned_link_id')!=body['replace_link']:
                raise Problem(409,'Ese presupuesto ya está vinculado. Para corregirlo indicá la asignación anterior y el fundamento.')
        if body.get('replace_link') and budget.get('assigned_link_id')!=body['replace_link']:
            raise Problem(409,'La asignación que intentás corregir cambió.')
        code=conn.execute("SELECT json_extract(r.permitted_json,'$.E') FROM invoice_rows r JOIN current_invoice_imports i ON i.id=r.import_id WHERE i.revision_id=? AND r.source_row=?",(rev,number)).fetchone()[0]
        edit=conn.execute("SELECT value_json FROM work_fields w JOIN current_invoice_imports i ON i.id=w.import_id WHERE i.revision_id=? AND w.source_row=? AND w.field='E'",(rev,number)).fetchone()
        if edit:
            import json
            code=json.loads(edit[0])
        conn.execute("""INSERT INTO image_budget_links(revision_id,source_row,dataset_id,capture_sha,order_id,practice_code,item_locator,performed_on,units,amount_ars,locator,reason,actor_id,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(rev,number,ds,sig['source_sha256'],sig['order_id'],code,sig['locator'],
            sig['performed_on'],units,format(amount,'.2f'),body['locator'].strip(),body['reason'].strip(),user['id'],now_utc()))
        conn.execute('UPDATE datasets SET version=version+1 WHERE id=?',(ds,))
        conn.execute('UPDATE revisions SET version=version+1 WHERE id=?',(rev,))
        event(conn,user['id'],'image_budget_linked','revision',rev)
    return {'saved':True}

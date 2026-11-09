"""Functional regressions for the imaging queue. Entirely fictitious."""
import unittest
from datetime import date
from io import BytesIO
from zipfile import ZipFile
from tests import test_invoice_audit as audit
from app.csv_coverage import assess_group
from app.row_decisions import authorization_shortfall
from app.report_pdf import make_pdf


class Dates(unittest.TestCase):
    def line(self,d,*,qty=1,inc=None):
        return dict(day=date.fromisoformat(d),key=('batch',d),quantity=qty,batch_id='batch',
            description='TAC',hpc=True,uncertain=False,incorporation={'value':inc,'origin':'test'} if inc else None)

    def order(self,d,cap=2,ident='A'):
        return dict(day=date.fromisoformat(d[:10]),decided_at=d,origin='test',reference=(ident,0,0),
            locator='order item',sha256='fixture',authorized=True,rejected=False,provider='HPC',
            unique=True,description='TAC',authorized_units=cap)
    def test_occasions_second_order_dates_and_limits(self):
        first=self.line('2026-08-02');later=self.line('2026-08-04')
        orders=[self.order('2026-07-02')]
        cases=assess_group([later,first],orders)
        self.assertEqual([cases[r['key']]['status'] for r in (first,later)],['units_supported','already_used'])
        cases=assess_group([later,first],orders+[self.order('2026-08-03',1,'B')])
        self.assertEqual([cases[r['key']]['status'] for r in (first,later)],['units_supported','one_unit_supported'])
        self.assertEqual(assess_group([self.line('2026-08-31',qty=2)],orders).popitem()[1]['covered_units'],2)
        self.assertEqual(assess_group([self.line('2026-09-01')],orders).popitem()[1]['status'],'outside_window')
    def test_two_units_share_one_explicit_total(self):
        from tests.test_csv_budget import check,CLAUSE,CODE,DESC
        movement='Resolución por ítems - AUTORIZAR: '+CODE+' - '+DESC+' x2 por un total autorizado de ARS 200.000'
        b=check(movement,quantity=2)[0]
        self.assertEqual((b['authorized_ars'],b['excess_ars']),('200000.00','250000.00'))
        self.assertEqual(check(movement,quantity=1)[0]['status'],'por_verificar')
    def test_consolidation(self):
        order=self.order('2026-08-03T14:30',1)
        for inc,expected in [('2026-08-04','one_unit_supported'),(None,'temporal_pending'),
                ('2026-08-02','temporal_late'),('2026-08-03','temporal_pending'),
                ('2026-08-03T15:00','one_unit_supported'),('2026-08-03T14:00','temporal_late')]:
            with self.subTest(inc=inc):
                sig=assess_group([self.line('2026-08-02',inc=inc)],[order]).popitem()[1]
                self.assertEqual(sig['status'],expected)
                self.assertIsNone(authorization_shortfall(100,dict(sig,export_scope='complete')))


class Integrated(unittest.TestCase):
    setUpClass=classmethod(audit.AuditTests.setUpClass.__func__)
    setUp=audit.AuditTests.setUp
    login=audit.AuditTests.login
    info=audit.AuditTests.info
    status=audit.AuditTests.status
    ready=audit.AuditTests.ready
    body=audit.AuditTests.body
    submit=audit.AuditTests.submit
    decision=audit.AuditTests.decision
    url=audit.AuditTests.url
    page=audit.AuditTests.page
    pass_invoice=audit.AuditTests.pass_invoice
    closing=audit.AuditTests.closing
    close=audit.AuditTests.close

    def test_filter_projection_invalidates_after_other_connection_commits(self):
        from app.board_projection import BoardProjection
        from app.practice_board import practice_search
        from app.security import token_digest
        from app.db import connect
        proj=BoardProjection(self.root,min_rows=1);self.addCleanup(proj.close)
        token=token_digest(self.client.cookies.get('tfg_session'))
        def read():
            return practice_search(self.c,token,self.ds,self.batch,{'view':'exceptions','family':'images','sort':'priority'},root=self.root,projection=proj)
        first=read();self.assertIsNotNone(proj.entry)
        first['items'][0]['description']='Cambio solo en respuesta'
        second=read()
        self.assertNotEqual(second['items'][0]['description'],'Cambio solo en respuesta')
        change=self.client.post(self.base+'/rows/2/work-fields',headers=self.h,json={
            'expected_dataset_version':second['dataset_version'],'expected_revision_version':second['batch']['revision_version'],
            'field':'K','value':'Descripción ficticia corregida','reason':'Corrección de prueba en otra conexión.'})
        self.assertIn(change.status_code,(200,201),change.text)
        latest=read()
        self.assertGreater(latest['dataset_version'],second['dataset_version'])
        self.assertEqual(next(r for r in latest['items'] if r['source_row']==2)['description'],'Descripción ficticia corregida')
    def test_closed_reports_unchanged_after_new_revision(self):
        url=self.base+'/observations.pdf'
        self.assertIn(b'Provisional',self.client.get(url).content)
        self.pass_invoice()
        closed=self.closing();self.assertEqual(self.close(closed).status_code,200)
        rev=closed['revision_id'];params={'revision_id':rev}
        excel=self.client.get(self.url+'/excel',params=params)
        pdf=self.client.get(url,params=params)
        self.assertEqual((pdf.status_code,excel.status_code),(200,200))
        self.assertIn(b'Cierre',pdf.content);self.assertIn(b'250.000,00',pdf.content)
        self.login('demo-administrativo')
        h=self.client.get(self.base+'/revisions').json()
        req=dict(previous_revision_id=rev,expected_dataset_version=h['dataset_version'],
            expected_revision_version=h['revision_version'],reason='Nueva evidencia ficticia recibida.')
        successor=self.client.post(self.base+'/revisions',json=req,headers=self.h)
        self.assertEqual(successor.status_code,201,successor.text)
        self.assertEqual(self.client.post(self.base+'/revisions',json=req,headers=self.h).status_code,409)
        from app.authorization_imports import stage_authorization,preview_authorization,confirm_authorization
        from app.authorization_matching import save_scope
        from app.security import token_digest
        from tests.test_hpc_csv_intake import row,encode
        self.login('demo-admin')
        token=token_digest(self.client.cookies.get('tfg_session'))
        v=lambda:self.c.execute('SELECT version FROM datasets WHERE id=?',(self.ds,)).fetchone()[0]
        inbox,_=stage_authorization(self.c,self.root,token,self.ds,v(),'posterior-ficticio.csv',encode([row(orden_hpc='NUEVA')]))
        preview=preview_authorization(self.c,self.root,token,self.ds,inbox['id'])
        capture,_=confirm_authorization(self.c,self.root,token,self.ds,inbox['id'],v(),preview['preview_sha256'],'Evidencia nueva de prueba posterior al cierre.')
        save_scope(self.c,self.root,token,self.ds,self.batch,v(),[capture['id']],'real_unvalidated','Nueva captura en revisión sucesora ficticia.')
        self.assertEqual(self.client.get(url,params=params).content,pdf.content)
        self.login('demo-auditor')
        self.assertEqual(self.client.get(self.url+'/excel',params=params).content,excel.content)
        self.assertEqual(self.c.execute('SELECT count(*) FROM batches').fetchone()[0],1)
        self.c.execute("DELETE FROM invoice_review_duties WHERE dataset_id=? AND duty='auditor'",(self.ds,))
        self.assertEqual(self.client.get(url,params=params).status_code,403)
        self.assertEqual(self.client.get(self.url+'/excel',params=params).status_code,403)
        self.assertEqual(self.client.get(self.base+'/export-closed',params=params).status_code,403)

    def test_prior_auditor_workbook_can_be_followed_by_new_review(self):
        from unittest.mock import patch
        self.pass_invoice()
        with patch('app.image_reports.freeze',return_value=None):
            self.assertEqual(self.close(self.closing()).status_code,200)
        self.login('demo-administrativo')
        h=self.client.get(self.base+'/revisions').json()
        self.assertIn(b'Cierre anterior a R22',self.client.get(self.base+'/observations.pdf').content)
        r=self.client.post(self.base+'/revisions',headers=self.h,json=dict(previous_revision_id=h['revision_id'],
            expected_dataset_version=h['dataset_version'],expected_revision_version=h['revision_version'],reason='Nuevo respaldo de prueba.'))
        self.assertEqual(r.status_code,201,r.text)
        self.assertEqual(self.c.execute('SELECT count(*) FROM revision_closures').fetchone()[0],1)
    def test_resonance_keeps_tariff_and_eco_has_its_own_budget(self):
        from scripts.create_r22_mixed import prepare
        from app.security import token_digest
        self.login('demo-admin')
        ds,bid=prepare(self.c,self.root,token_digest(self.client.cookies.get('tfg_session')))
        self.login('demo-administrativo')
        path=f'/api/datasets/{ds}/batches/{bid}'
        def board(view):
            result=self.client.post(path+'/practice-search',headers=self.h,json={'family':'images','view':view,'sort':'priority'})
            self.assertEqual(result.status_code,200,result.text)
            return {r['source_row']:r for r in result.json()['items']}
        original=board('all')
        self.assertEqual(original[2]['applicable_tariff']['total_ars'],'120000.00')
        self.assertEqual(original[3]['authorization']['panel_signal']['csv_coverage']['budget']['status'],'por_verificar')
        eco=self.client.get(path+'/rows/3/administrative-decision').json()
        req=dict(expected_dataset_version=eco['dataset_version'],revision_id=eco['revision_id'],evidence_hash=eco['evidence_hash'],
            amount_ars='200000.00',locator='MIXTA-22, anexo ecografía',reason='Presupuesto propio de la ecografía TV.')
        saved=self.client.post(path+'/rows/3/budget-link',json=req,headers=self.h)
        self.assertEqual(saved.status_code,200,saved.text)
        after=board('all')
        self.assertEqual(after[2]['applicable_tariff']['total_ars'],'120000.00')
        self.assertNotIn('authorized_ars',after[2]['authorization']['panel_signal']['csv_coverage'].get('budget') or {})
        self.assertEqual(after[3]['administrative_decision']['proposal']['amount_ars'],'250000.00')
        self.assertEqual(set(board('exceptions')),{3})

    def test_unconfirmed_other_lot_cannot_spend_the_hpc_order(self):
        from app.authorization_matching import save_scope
        from app.service import create_batch,confirm_invoice
        from app.security import token_digest
        from tests.test_p02 import book
        from openpyxl import load_workbook
        self.login('demo-admin')
        token=token_digest(self.client.cookies.get('tfg_session'))
        v=lambda:self.c.execute('SELECT version FROM datasets WHERE id=?',(self.ds,)).fetchone()[0]
        wb=load_workbook(BytesIO(book([('01/08/2026',30,0,30)])))
        for col,val in [(3,'000111/1'),(5,'1234567890'),(7,1),(11,'TAC TRIDIMENSIONAL')]:
            wb.active.cell(2,col).value=val
        buf=BytesIO();wb.save(buf);wb.close()
        lot,_=create_batch(self.c,self.root,token,self.ds,v(),'ficticio-sin-prestador.xlsx',buf.getvalue())
        confirm_invoice(self.c,self.root,token,self.ds,lot['id'],'2026-08',v())
        cap=self.c.execute('SELECT id FROM authorization_captures').fetchone()[0]
        save_scope(self.c,self.root,token,self.ds,lot['id'],v(),[cap],'real_unvalidated','Otra factura ficticia cuyo prestador no fue confirmado.')
        self.login('demo-administrativo')
        endpoint=self.base+'/practice-search'
        page=self.client.post(endpoint,headers=self.h,json={'family':'images','view':'all'}).json()
        row=next(r for r in page['items'] if r['source_row']==2)
        self.assertEqual(row['authorization']['panel_signal']['csv_coverage']['status'],'needs_review')
        self.assertIsNone(self.info(2)['proposal'])

    def test_verified_budget_on_one_item(self):
        from app.authorization_imports import stage_authorization,preview_authorization,confirm_authorization
        from app.authorization_matching import save_scope
        from app.security import token_digest
        from tests.test_hpc_csv_intake import row,encode
        self.login('demo-admin')
        token=token_digest(self.client.cookies.get('tfg_session'))
        v=lambda:self.c.execute('SELECT version FROM datasets WHERE id=?',(self.ds,)).fetchone()[0]
        orders=encode([row(orden_hpc='MULTI',afiliado='000111/1',
            practicas='1234567890 -- TAC TRIDIMENSIONAL,2222222222 -- Resonancia,',
            movimientos='02/07/2026 12:00 | Administrativo ficticio | AUTORIZADO | Resolución por ítems - AUTORIZAR: 1234567890; AUTORIZAR: 2222222222',
            observacion='Presupuesto total autorizado ARS 200.000 para verificar.')])
        up,_=stage_authorization(self.c,self.root,token,self.ds,v(),'ficticio.csv',orders)
        pre=preview_authorization(self.c,self.root,token,self.ds,up['id'])
        cap,_=confirm_authorization(self.c,self.root,token,self.ds,up['id'],v(),pre['preview_sha256'],'Cotejo ficticio de presupuesto.')
        save_scope(self.c,self.root,token,self.ds,self.batch,v(),[cap['id']],'real_unvalidated','Captura ficticia seleccionada.')
        self.login('demo-administrativo')
        info=self.info()
        self.assertEqual(info['budget']['status'],'por_verificar')
        req=dict(expected_dataset_version=info['dataset_version'],revision_id=info['revision_id'],
            evidence_hash=info['evidence_hash'],amount_ars='200000',locator='Orden MULTI, anexo ficticio, ítem 1',reason='Importe propio del ítem verificado en el anexo.')
        url=self.base+'/rows/2/budget-link'
        self.assertEqual(self.client.post(url,json=req,headers=self.h).status_code,200)
        self.assertEqual(self.client.post(url,json=req,headers=self.h).status_code,409)
        info=self.info()
        self.assertEqual(info['budget']['authorized_ars'],'200000.00')
        self.assertEqual(info['proposal']['amount_ars'],'250000.00')
        self.assertEqual(info['budget']['locator'],req['locator'])
        self.assertNotIn('authorized_ars',(self.info(3).get('budget') or {}))
        self.login('demo-auditor')
        self.assertEqual(self.client.post(url,json={**req,'expected_dataset_version':info['dataset_version']},headers=self.h).status_code,403)


class Priority(unittest.TestCase):
    def test_high_then_amount_then_source(self):
        from app.practice_board import review_priority
        def item(n,m):
            return {'source_row':n,'total_ars':'100.00','honorarios_ars':m,'derechos_ars':'0.00',
                '_facets':[], 'alerts':[{'rule_code':'RN13','current':True}] if m else []}
        rows=[item(1,None),item(51,'75.00'),item(98,'10.00'),item(3,'75.00')]
        self.assertEqual([r['source_row'] for r in sorted(rows,key=lambda r:review_priority(r,{},{}))],[98,3,51,1])

class Pdf(unittest.TestCase):
    def test_multiple_pages(self):
        pdf=make_pdf('Observaciones',[f'Fila {n} - importe y motivo' for n in range(125)])
        self.assertIn(b'/Count 3',pdf);self.assertIn(b'Fila 124',pdf)

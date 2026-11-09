"""All CSVs, invoices and identities here are invented. No network listeners."""
from datetime import date
from io import BytesIO
import unittest

from openpyxl import load_workbook
from app.authorization_matching import page_correspondence, save_scope
from app.authorization_source import parse_authorization_source
from app.csv_budget import assess_budgets, source_budgets
from app.csv_coverage import dated_item, assess_group
from app.db import connect
from app.practice_board import practice_search
from app.service import create_batch,confirm_invoice
from app.economic_evidence import confirm_provider_scope
from app.review import _batch
from app.authorization_imports import stage_authorization,preview_authorization,confirm_authorization
from scripts.create_review_journey_demo import fictional_budget_capture
from tests.test_hpc_csv_intake import row, encode
from tests.test_p02 import book
from tests import test_economic_evidence as fixtures

CODE='1234567890'
DESC='TAC TRIDIMENSIONAL'
EVENT='02/07/2026 12:00 | FICTICIO | AUTORIZADO | '
CLAUSE='Resolución por ítems - AUTORIZAR: '+CODE+' - '+DESC+' por un total autorizado de '


def check(movement=CLAUSE+'ARS 200.000', *, raw_changes=None, billed='450000.00', quantity=1,
          day='2026-08-02', hpc=True, affiliate='000111/1', repeat=False, genuine=True):
    fields={'afiliado':'000111/1','practicas':CODE+' -- '+DESC+',','movimientos':EVENT+movement}
    src=encode([row(**{**fields, **(raw_changes or {})})])
    orders=parse_authorization_source(src).canonical['orders']
    budget=source_budgets(src,orders) if genuine else {}
    item=dated_item({'id':'fixture','source_sha256':'a'*64,'_budget_orders':budget},0,orders[0],0,orders[0]['items'][0],True)
    rows=[dict(key=('imp',2),batch_id='test',day=date.fromisoformat(day),description=DESC,
               quantity=quantity,hpc=hpc,affiliate=affiliate,billed=billed,uncertain=False)]
    if repeat:rows.append({**rows[0],'key':('imp',3),'day':date(2026,8,4)})
    results=assess_group(rows,[item])
    assess_budgets(rows,[item],results)
    return [v.get('budget') for v in results.values()]


class BudgetChecks(unittest.TestCase):
    def test_exact_excess_and_source(self):
        b=check()[0]
        self.assertEqual((b['status'],b['authorized_ars'],b['billed_ars'],b['excess_ars']),('over','200000.00','450000.00','250000.00'))
        self.assertEqual(b['movement_actor'], 'FICTICIO')
        self.assertEqual((b['order_id'],b['csv_row'],b['authorized_on']),('TEST-1',2,'2026-07-02'))

    def test_cents_equality_under_and_zero(self):
        for billed,status,excess in [('200000.11','over','0.01'),('200000.10','within','0.00'),('10.00','within','0.00')]:
            with self.subTest(billed=billed):
                b=check(CLAUSE+'$200.000,10 ARS',billed=billed)[0]
                self.assertEqual((b['status'],b['excess_ars']),(status,excess))
        self.assertEqual(check(CLAUSE+'ARS 0')[0]['excess_ars'],'450000.00')

    def test_quote_shared_conditions_currency_rejection_and_corrections(self):
        for movement,raw in [
            ('Se solicita presupuesto de ARS 200.000',{}),(CLAUSE+'$200.000',{}),(CLAUSE+'USD 200.000',{}),
            (CLAUSE+'ARS 200.000 para toda la orden',{}),(CLAUSE+'ARS 200.000 si se presenta respaldo',{}),
            (CLAUSE+'ARS 200.000',{'practicas':CODE+' -- '+DESC+',2222222222 -- Otro estudio ficticio,'}),
            (CLAUSE+'ARS 200.000',{'historial_original':'Rectificado: consultar orden.'}),
            (CLAUSE+'ARS 200.000\n03/07/2026 12:00 | FICTICIO | RECHAZADO | Anulado',{}),
            ('Resolución por ítems - NO AUTORIZAR: '+CODE+' - importe solicitado ARS 200.000',{}),
            (CLAUSE+'ARS 200,000',{})]:
            with self.subTest(movement=movement,fields=list(raw)):
                b=check(movement,raw_changes=raw)[0]
                self.assertEqual(b['status'],'por_verificar')
                self.assertNotIn('excess_ars',b)

    def test_scope_identity_window_quantity_and_reuse(self):
        for args in [dict(day='2026-09-01'),dict(hpc=False),dict(quantity=2),dict(affiliate='00111/1'),dict(billed=None)]:
            with self.subTest(args=args):
                b=check(**args)[0]
                self.assertEqual(b['status'],'por_verificar');self.assertNotIn('authorized_ars',b)
        self.assertEqual(check(day='2026-08-31')[0]['status'],'over')
        a,b=check(repeat=True)
        self.assertEqual(a['status'],'over');self.assertEqual(b['status'],'por_verificar')
        self.assertNotIn('excess_ars',b)

    def test_expired_order_cannot_hide_current_budget_or_supply_an_unpriced_one(self):
        def source(when,locator,budget):
            return dict(day=date.fromisoformat(when),reference=('sha',0,locator),sha256='sha',locator=str(locator),
                        budget=budget,authorized=True,rejected=False,provider='HPC',unique=True,description=DESC,affiliate='FICT')
        price=dict(order_id='DEMO',csv_row=2,amount_ars='200000.00')
        r=dict(day=date(2026,8,2),key=('imp',2),batch_id='test',quantity=1,uncertain=False,description=DESC,
               hpc=True,affiliate='FICT',billed='450000.00')
        old=source('2026-05-01',1,price)
        for other,expected in [(source('2026-07-02',2,price),'over'),(source('2026-07-02',2,None),None)]:
            signals=assess_group([r],[old,other])
            assess_budgets([r],[old,other],signals)
            self.assertEqual((signals[r['key']].get('budget') or {}).get('status'),expected)

    def test_absence_and_non_platform_json(self):
        self.assertIsNone(check('Resolución por ítems - AUTORIZAR: '+CODE)[0])
        self.assertIsNone(check(genuine=False)[0])
        self.assertIsNone(check('Precio de listado ARS 220.000',raw_changes={'practicas':CODE+' -- '+DESC+' $ 220.000,'})[0])


class BudgetIntegration(unittest.TestCase):
    def test_import_board_filter_detail_and_replaced_capture(self):
        f=fixtures.EconomicEvidenceTests();f.setUp();self.addCleanup(f.tearDown)
        c=connect(f.root);self.addCleanup(c.close);ds=f.dataset['id']
        v=lambda:c.execute('SELECT version FROM datasets WHERE id=?',(ds,)).fetchone()[0]
        capture=fictional_budget_capture(c,f.root,f.digest,ds,v())
        wb=load_workbook(BytesIO(book([('02/08/2026',400000,50000,450000)])))
        for col,val in [(3,'000111/1'),(5,CODE),(7,1),(11,DESC)]:wb.active.cell(2,col).value=val
        stream=BytesIO();wb.save(stream);wb.close()
        batch,_=create_batch(c,f.root,f.digest,ds,v(),'FICTICIO_TAC.xlsx',stream.getvalue());bid=batch['id']
        confirm_invoice(c,f.root,f.digest,ds,bid,'2026-08',v())
        save_scope(c,f.root,f.digest,ds,bid,v(),[capture],'real_unvalidated','Fuente ficticia de presupuesto.')
        def search():
            return practice_search(c,f.digest,ds,bid,dict(view='exceptions',csv_review_state='budget',saved_source_row=2),root=f.root)
        def detail():
            res=f.client.get(f'/api/datasets/{ds}/batches/{bid}/rows/2/authorization-correspondence')
            self.assertEqual(res.status_code,200)
            return res.json().get('csv_coverage') or {}
        self.assertEqual(detail()['budget']['status'],'por_verificar')
        source=c.execute("SELECT id FROM source_registry WHERE dataset_id=? AND kind='values'",(ds,)).fetchone()[0]
        confirm_provider_scope(c,f.root,f.digest,ds,bid,source,'HPC','unverified','Factura HPC ficticia para verificar presupuesto.',v(),_batch(c,ds,bid)['revision_version'])
        data=search();self.assertEqual(data['filtered_total'],1)
        target=data['items'][0];budget=target['authorization']['panel_signal']['csv_coverage']['budget']
        self.assertEqual(budget['excess_ars'],'250000.00');self.assertEqual(detail()['budget'],budget)
        self.assertEqual(target['exception_reasons'],['Revisar presupuesto CSV'])
        self.assertIn('Contrastar el presupuesto de la orden',data['saved_row_status']['pending'])
        self.assertIsNone(target['debit_proposal']);self.assertEqual(c.execute('SELECT count(*) FROM proposal_versions').fetchone()[0],0)
        changed=encode([row(afiliado='000111/1',fecha_orden='2026-07-02',fecha_orden_original='02/07/2026',
                       practicas=CODE+' -- '+DESC+',',movimientos=EVENT+'Presupuesto solicitado de ARS 200.000')])
        u,_=stage_authorization(c,f.root,f.digest,ds,v(),'ficticio.csv',changed)
        p=preview_authorization(c,f.root,f.digest,ds,u['id'])
        new,_=confirm_authorization(c,f.root,f.digest,ds,u['id'],v(),p['preview_sha256'],'Reemplazo ficticio de captura.')
        self.assertNotIn('budget',detail());self.assertEqual(search()['filtered_total'],0)
        save_scope(c,f.root,f.digest,ds,bid,v(),[new['id']],'real_unvalidated','Seleccionada la captura ficticia corregida.')
        self.assertEqual(detail()['budget']['status'],'por_verificar')
        self.assertNotIn('excess_ars',detail()['budget'])


import unittest
from datetime import date
from io import BytesIO
from openpyxl import load_workbook
from tests.test_p02 import book
from tests.test_hpc_csv_intake import row, encode
from tests import test_economic_evidence as fixture
from app.db import connect
from app.service import create_batch,confirm_invoice
from app.authorization_matching import page_correspondence,save_scope
from app.authorization_imports import stage_authorization,preview_authorization,confirm_authorization
from app.csv_coverage import assess_group


class CsvValidityTests(unittest.TestCase):
    def test_boundaries_and_ambiguity(self):
        item=dict(reference=('capture',0,0),locator='item',sha256='ficticio',day=date(2026,7,2),
                  authorized=True,rejected=False,unique=True,description='TAC ficticia',provider='HPC')
        def rows(*days,quantity=1):
            return [dict(day=date.fromisoformat(d),key=('imp',i),batch_id='lote',quantity=quantity,
                         description='TAC ficticia',uncertain=False) for i,d in enumerate(days)]
        def states(claims, items):
            return [r['status'] for r in assess_group(claims,items).values()]
        self.assertEqual(states(rows('2026-07-01','2026-08-31','2026-09-01'),[item]),
                         ['temporal_pending','needs_review','outside_window'])
        self.assertEqual(states(rows('2026-07-02',quantity=2),[item]),['one_unit_only'])
        self.assertEqual(states(rows('2026-08-02','2026-08-02','2026-08-04'),[item]),['needs_review']*3)
        self.assertEqual(states(rows('2026-08-02'),[item,{**item,'reference':('capture',1,0)}]),['needs_review'])
        self.assertEqual(states(rows('2026-08-02'),[{**item,'authorized':False,'rejected':True}]),['declared_rejected'])

    def test_csv_july_authorization_two_august_invoices(self):
        f=fixture.EconomicEvidenceTests();f.setUp()
        try:
            conn=connect(f.root)
            try:
                ds=f.dataset['id'];v=lambda:conn.execute('SELECT version FROM datasets WHERE id=?',(ds,)).fetchone()[0]
                code='1234567890';desc='TAC ficticia';patient='000111/1'
                src=encode([row(afiliado=patient,practicas=f'{code} -- {desc},',movimientos=f'02/07/2026 12:00 | Ficticio | AUTORIZADO | Resolución por ítems - AUTORIZAR: {code}')])
                upload,_=stage_authorization(conn,f.root,f.digest,ds,v(),'ficticio.csv',src)
                preview=preview_authorization(conn,f.root,f.digest,ds,upload['id'])
                cap,_=confirm_authorization(conn,f.root,f.digest,ds,upload['id'],v(),preview['preview_sha256'],'Prueba ficticia de autorización.')
                batches=[]
                for day in ('04/08/2026','02/08/2026'):
                    wb=load_workbook(BytesIO(book([(day,10,20,30)])));sheet=wb.active
                    for col,val in [(3,patient),(5,int(code)),(7,1),(11,desc)]:sheet.cell(2,col).value=val
                    content=BytesIO();wb.save(content);wb.close()
                    batch,_=create_batch(conn,f.root,f.digest,ds,v(),'ficticio.xlsx',content.getvalue());bid=batch['id'];batches.append(bid)
                    confirm_invoice(conn,f.root,f.digest,ds,bid,'2026-08',v())
                    save_scope(conn,f.root,f.digest,ds,bid,v(),[cap['id']],'real_unvalidated','CSV ficticio para comprobar vigencia.')
                def signal(bid):
                    return page_correspondence(conn,f.root,ds,bid,[2])[2]['panel_signal']['csv_coverage']
                self.assertEqual(signal(batches[0])['status'],'already_used')
                self.assertEqual(signal(batches[0])['previous_rows'][0]['batch_id'],batches[1])
                self.assertEqual(signal(batches[1])['status'],'one_unit_supported')
                self.assertEqual(signal(batches[1])['elapsed_days'],31)
                from app.practice_board import practice_search
                def queue(bid):
                    return practice_search(conn,f.digest,ds,bid,{'view':'exceptions'},root=f.root)
                self.assertIn('Revisar aval CSV',queue(batches[0])['items'][0]['exception_reasons'])
                self.assertIn('El aval del 02/07 ya respalda la prestación del 02/08.',queue(batches[0])['items'][0]['exception_details'])
                self.assertFalse(any('Autorizaciones:' in msg for msg in queue(batches[0])['source_notices']))
                self.assertEqual(queue(batches[1])['filtered_total'],0)
                for view in ('exceptions','all','referred'):
                    hidden=practice_search(conn,f.digest,ds,batches[0],
                        {'view':view,'code':'sin-coincidencia','saved_source_row':2},root=f.root)
                    self.assertFalse(hidden['items'])
                    self.assertTrue(hidden['saved_row_status']['in_exceptions'])
                    self.assertEqual(hidden['saved_row_status']['pending'],['Revisar el aval CSV'])
                outside=practice_search(conn,f.digest,ds,batches[0],
                    {'view':'exceptions','scope':'excluded','saved_source_row':2},root=f.root)
                self.assertEqual(outside['scope_total'],0)
                self.assertEqual(outside['saved_row_status']['pending'],['Revisar el aval CSV'])
                self.assertEqual(conn.execute('SELECT count(*) FROM proposal_versions').fetchone()[0],0)
            finally:conn.close()
        finally:f.tearDown()

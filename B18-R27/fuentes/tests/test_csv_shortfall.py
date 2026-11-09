"""Integración con el Excel, el CSV y el catálogo ficticios de la planilla de R20."""
import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from tests import test_row_decisions as operator
from scripts.create_review_journey_demo import main


class ShortfallTests(unittest.TestCase):
    setUp=operator.RowDecisionTests.setUp
    login=operator.RowDecisionTests.login
    board=operator.RowDecisionTests.board
    info=operator.RowDecisionTests.info

    @classmethod
    def setUpClass(cls):
        name='r20-tests-'+uuid4().hex
        with patch.object(sys,'argv',['demo','--cobertura-csv','--name',name]),contextlib.redirect_stdout(io.StringIO()):
            main()
        cls.sample=Path(__file__).resolve().parents[1]/'.tmp'/name
        cls.passwords=dict(l.split(': ',1) for l in (cls.sample/'credenciales-demo.txt').read_text().splitlines())

    def selection(self,start=None,end=None,ids=None):
        current=self.client.get(self.base+'/authorization-scope').json()
        return self.client.post(self.base+'/authorization-scope',headers=self.h,json={
            'expected_version':current['dataset_version'],'capture_ids':ids or current['current']['capture_ids'],
            'mode':(current['current'] or {}).get('mode','real_unvalidated'),'note':'Cotejo ficticio de la exportación completa.',
            'csv_complete_from':start,'csv_complete_until':end})

    def accept_body(self,n):
        info=self.info(n)
        return dict(expected_dataset_version=info['dataset_version'],expected_revision_version=info['revision_version'],
                    revision_id=info['revision_id'],evidence_hash=info['evidence_hash'],request_id=str(uuid4()),action='accept')

    def accept(self,n,body):
        return self.client.post(self.base+f'/rows/{n}/administrative-decision',headers=self.h,json=body)

    def test_three_rows_and_human_confirmation(self):
        pending=self.board()
        self.assertEqual(pending['row_decision_counts'],{'reviewed':0,'pending':3})
        by_number={r['source_row']:r for r in pending['items']}
        expected=[(2,'no_aval','100000.00'),(3,'one_unit_only','100000.00'),(4,'coverage_pending',None)]
        for n,status,amount in expected:
            row=by_number[n]
            self.assertEqual(row['authorization']['panel_signal']['csv_coverage']['status'],status)
            proposal=row['administrative_decision']['proposal']
            self.assertEqual(proposal and proposal['amount_ars'],amount)
            self.assertEqual(self.info(n)['proposal'],proposal)
        self.assertIn('1 de 2 autorizada',self.info(3)['proposal']['reason'])
        self.assertEqual(by_number[3]['total_ars'],'200000.00')
        self.assertEqual(self.accept(4,self.accept_body(4)).status_code,422)
        self.assertEqual(self.c.execute('SELECT count(*) FROM invoice_row_decisions').fetchone()[0],0)
        self.assertEqual(self.c.execute('SELECT count(*) FROM audit_invoice_closures').fetchone()[0],0)
        self.assertEqual(self.accept(3,self.accept_body(3)).status_code,201)
        self.assertEqual(self.board('row_reviewed')['items'][0]['administrative_decision']['previous']['amount_ars'],'100000.00')

    def test_full_sixty_days_and_no_negative_proposal_from_an_incomplete_export(self):
        for start,end in [('2026-06-04','2026-08-31'),('2026-06-03','2026-08-01'),(None,None)]:
            res=self.selection(start,end);self.assertEqual(res.status_code,200,res.text)
            self.assertIsNone(self.info(2)['proposal'])
            self.assertIsNone(self.info(3)['proposal'])
        res=self.selection('2026-06-03','2026-08-02');self.assertEqual(res.status_code,200,res.text)
        self.assertEqual(self.info(3)['proposal']['amount_ars'],'100000.00')
        self.assertIsNone(self.info(4)['proposal'])
        self.assertEqual(self.selection('2026-06-03',None).status_code,422)
        self.assertEqual(self.selection('2026-09-01','2026-06-03').status_code,422)

    def test_new_scope_reopens_saved_decision_and_refuses_old_form(self):
        stale=self.accept_body(2)
        self.assertEqual(self.accept(2,stale).status_code,201)
        self.assertEqual(self.selection().status_code,200)
        info=self.info(2)
        self.assertFalse(info['current']);self.assertIsNone(info['proposal'])
        self.assertEqual(info['previous']['amount_ars'],'100000.00')
        stale['request_id']=str(uuid4())
        self.assertEqual(self.accept(2,stale).status_code,409)

    def test_quarantine_prevents_absence_even_with_period_confirmed(self):
        from app.authorization_imports import stage_authorization,preview_authorization,confirm_authorization
        from app.security import token_digest
        from tests.test_hpc_csv_intake import row,encode
        self.login('demo-admin')
        token=token_digest(self.client.cookies.get('tfg_session'));scope=self.client.get(self.base+'/authorization-scope').json()
        raw=encode([row(afiliado='000111/1',orden_hpc='A'),row(afiliado='',orden_hpc='B')])
        upload,_=stage_authorization(self.c,self.root,token,self.ds,scope['dataset_version'],'FICTICIO-parcial.csv',raw)
        preview=preview_authorization(self.c,self.root,token,self.ds,upload['id'])
        version=self.client.get(self.base+'/authorization-scope').json()['dataset_version']
        capture,_=confirm_authorization(self.c,self.root,token,self.ds,upload['id'],version,preview['preview_sha256'],'CSV de prueba con una orden en cuarentena.')
        response=self.selection('2026-05-01','2026-08-31',[capture['id']]);self.assertEqual(response.status_code,200,response.text)
        self.assertIsNone(self.info(2)['proposal'])
        self.assertIn('registros',self.client.get(self.base+'/authorization-scope').json()['csv_export_limitation'])

    def test_one_authorization_not_reused_in_a_second_invoice(self):
        from openpyxl import load_workbook
        from app.service import create_batch,confirm_invoice
        from app.controls import run_controls
        from app.economic_evidence import confirm_provider_scope
        from app.review import _batch
        from app.security import token_digest
        from tests.test_p02 import book
        self.login('demo-admin')
        token=token_digest(self.client.cookies.get('tfg_session'))
        def version():
            return self.client.get(self.base+'/authorization-scope').json()['dataset_version']
        ids=self.client.get(self.base+'/authorization-scope').json()['current']['capture_ids']
        wb=load_workbook(io.BytesIO(book([('03/08/2026',80000,20000,100000),('03/08/2026',8000,2000,10000)])))
        for n,code,desc,affiliate in [(2,'1234567890','TAC TRIDIMENSIONAL','000111/1'),(3,'654321','Laboratorio ficticio','000777/1')]:
            for column,v in [(3,affiliate),(5,code),(7,1),(11,desc)]:
                wb.active.cell(n,column).value=v
        stream=io.BytesIO();wb.save(stream);wb.close()
        batch,_=create_batch(self.c,self.root,token,self.ds,version(),'FICTICIO_repeticion.xlsx',stream.getvalue())
        imported,_=confirm_invoice(self.c,self.root,token,self.ds,batch['id'],'2026-08',batch['dataset_version'])
        source=self.c.execute("SELECT id FROM source_registry WHERE dataset_id=? AND kind='values'",(self.ds,)).fetchone()[0]
        scope=confirm_provider_scope(self.c,self.root,token,self.ds,batch['id'],source,'HPC','unverified','Prestador de prueba confirmado.',
                                     imported['dataset_version'],_batch(self.c,self.ds,batch['id'])['revision_version'])
        first=self.base;self.base=f'/api/datasets/{self.ds}/batches/'+batch['id']
        self.assertEqual(self.selection('2026-06-03','2026-08-03',ids).status_code,200)
        run_controls(self.c,token,self.ds,batch['id'],version())
        later=self.info(2)
        self.assertEqual(later['proposal']['amount_ars'],'100000.00')
        self.assertIn('ya respaldó',later['proposal']['reason'])
        lab=self.client.get(self.base+'/rows/3/authorization-correspondence').json()
        self.assertIsNone(lab.get('csv_coverage'))
        self.base=first
        self.assertEqual(self.info(3)['proposal']['amount_ars'],'100000.00')

    def test_possible_code_or_description_relation_is_pending(self):
        from app.csv_export import ExportCoverage
        class Relations:
            def aliases(self,code):
                return [{'authorization_code':'9999999999'}] if code=='8765432100' else []
        scope=self.client.get(self.base+'/authorization-scope').json()['current']
        capture=self.c.execute('SELECT * FROM authorization_captures LIMIT 1').fetchone()
        def candidate(text):
            return [(None,None,None,None,{'description':text},True)]
        index={('1111','1234567890'):candidate('TAC abdomen'),('1111','9999999999'):candidate('Ecografía')}
        export=ExportCoverage(self.c,scope,[capture],index,Relations)
        for code,desc in [('123456','Otro'),('1234560000','Distinta'),('1111111111','TAC ABDOMEN'),('8765432100','Otra')]:
            self.assertTrue(export.uncertain_identity('1111',code,desc,False))
        self.assertTrue(export.uncertain_identity(None,'1234567890','TAC',False))
        self.assertTrue(export.uncertain_identity('1111','1234567890','TAC',True))



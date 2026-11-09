"""Full-invoice handoff using the two fictitious TAC and separate operator accounts."""
import unittest
from uuid import uuid4
from tests import test_row_decisions as fixture


class HandoffTests(unittest.TestCase):
    setUpClass=classmethod(fixture.RowDecisionTests.setUpClass.__func__)
    setUp=fixture.RowDecisionTests.setUp
    login=fixture.RowDecisionTests.login
    board=fixture.RowDecisionTests.board
    info=fixture.RowDecisionTests.info

    def status(self):
        r=self.client.get(self.base+'/handoff')
        self.assertEqual(r.status_code,200,r.text)
        return r.json()

    def body(self):
        s=self.status()
        return {'expected_dataset_version':s['dataset_version'],'expected_revision_version':s['revision_version'],
                'revision_id':s['revision_id'],'request_id':str(uuid4())}

    def submit(self,body):
        return self.client.post(self.base+'/handoff',json=body,headers=self.h)

    def decision(self,n,action,reason='',**extra):
        row=self.info(n)
        data={'expected_dataset_version':row['dataset_version'],'expected_revision_version':row['revision_version'],
              'revision_id':row['revision_id'],'evidence_hash':row['evidence_hash'],'request_id':str(uuid4()),
              'action':action,'reason':reason,**extra}
        return self.client.post(self.base+f'/rows/{n}/administrative-decision',json=data,headers=self.h)

    def ready(self):
        for response in (self.decision(2,'accept'), self.decision(3,'none','Cotejo ficticio sin débito')):
            self.assertEqual(response.status_code,201,response.text)
        self.assertTrue(self.status()['can_send'])

    def test_global_count_even_when_filters_hide_both_rows(self):
        self.assertEqual(self.status()['pending'],2)
        self.assertFalse(self.status()['can_send'])
        self.assertEqual(self.board(search='sin-coincidencias')['filtered_total'],0)
        self.assertEqual(self.submit(self.body()).status_code,409)
        self.assertEqual(self.decision(2,'accept').status_code,201)
        self.assertEqual(self.status()['pending'],1)
        self.assertEqual(self.submit(self.body()).status_code,409)
        self.assertEqual(self.c.execute('SELECT count(*) FROM invoice_handoffs').fetchone()[0],0)

    def test_pass_is_atomic_and_auditor_receives_latest_including_zero(self):
        self.ready()
        old=self.body()
        self.assertEqual(self.decision(2,'partial','Rectificación ficticia',partial_ars='100000.50').status_code,201)
        self.assertEqual(self.submit(old).status_code,409)
        body=self.body()
        result=self.submit(body);self.assertEqual(result.status_code,201,result.text)
        self.assertEqual(self.submit(body).json(),result.json())
        self.assertEqual(self.submit({**body,'request_id':str(uuid4())}).status_code,409)
        self.assertFalse(self.info()['can_write'])
        self.assertEqual(self.decision(2,'total','Corrección tardía').status_code,409)
        # Legacy edit entry point remains locked even from an already open form.
        self.assertEqual(self.client.post(self.base+'/rows/2/work-fields',headers=self.h,json={
            'expected_dataset_version':self.status()['dataset_version'],'expected_revision_version':self.status()['revision_version'],
            'field':'K','value':'Cambio tardío','reason':'Cambio ficticio posterior'}).status_code,409)
        self.assertEqual(self.c.execute('SELECT count(*) FROM revision_closures').fetchone()[0],0)
        self.assertEqual(self.client.get(f'/api/datasets/{self.ds}/auditor-handoffs').status_code,403)
        self.login('demo-auditor')
        inbox=self.client.get(f'/api/datasets/{self.ds}/auditor-handoffs').json()['items']
        self.assertEqual(len(inbox),1)
        self.assertEqual((inbox[0]['batch_id'],inbox[0]['receipt_count'],inbox[0]['debit_total_ars']),(self.batch,2,'100000.50'))
        pages=[self.client.get(self.base+'/handoff/decisions',params={'offset':i,'limit':1}).json() for i in range(2)]
        self.assertEqual([p['items'][0]['source_row'] for p in pages],[2,3])
        self.assertEqual([p['items'][0]['amount_ars'] for p in pages],['100000.50','0.00'])
        self.assertEqual([p['items'][0]['reason'] for p in pages],['Rectificación ficticia','Cotejo ficticio sin débito'])
        self.assertEqual(pages[0]['items'][0]['ordinal'],2)

    def test_auditor_cannot_send_and_permissions_are_checked(self):
        self.ready();body=self.body()
        self.assertEqual(self.client.post(self.base+'/handoff',json=body,headers={'Origin':fixture.ORIGIN}).status_code,403)
        self.login('demo-auditor')
        self.assertFalse(self.status()['can_send'])
        self.assertEqual(self.submit(body).status_code,403)
        self.assertEqual(self.client.get(self.base+'/handoff/decisions').status_code,404)
        self.assertEqual(self.client.get(f'/api/datasets/{self.ds}/auditor-handoffs').json()['items'],[])

    def test_pending_laboratory_row_is_outside_the_handoff(self):
        from io import BytesIO
        from openpyxl import load_workbook
        from app.controls import run_controls
        from app.economic_evidence import confirm_provider_scope
        from app.review import _batch
        from app.security import token_digest
        from app.service import create_batch,confirm_invoice
        from tests.test_p02 import book
        self.login('demo-admin')
        token=token_digest(self.client.cookies.get('tfg_session'))
        wb=load_workbook(BytesIO(book([('02/08/2026',10,20,39),('04/08/2026',10,20,39)])))
        ws=wb.active
        ws['E2']='123456';ws['K2']='Ecografía ficticia'
        ws['E3']='654321';ws['K3']='Laboratorio ficticio'
        stream=BytesIO();wb.save(stream);wb.close()
        ds_version=self.status()['dataset_version']
        batch,_=create_batch(self.c,self.root,token,self.ds,ds_version,'FICTICIO_MIXTO.xlsx',stream.getvalue())
        self.batch=batch['id'];self.base=f'/api/datasets/{self.ds}/batches/{self.batch}'
        imported,_=confirm_invoice(self.c,self.root,token,self.ds,self.batch,'2026-08',batch['dataset_version'])
        source=self.c.execute("SELECT id FROM source_registry WHERE dataset_id=? AND kind='values'",(self.ds,)).fetchone()[0]
        scope=confirm_provider_scope(self.c,self.root,token,self.ds,self.batch,source,'HPC','unverified','Prestador HPC ficticio comprobado.',
                                     imported['dataset_version'],_batch(self.c,self.ds,self.batch)['revision_version'])
        run_controls(self.c,token,self.ds,self.batch,scope['dataset_version'])
        self.login('demo-administrativo')
        self.assertEqual(self.status()['pending'],1)
        self.assertEqual(self.decision(2,'none','Cotejo ficticio por Imágenes').status_code,201)
        other=self.client.post(self.base+'/practice-search',headers=self.h,json={'view':'exceptions','family':'other'}).json()
        self.assertEqual([r['source_row'] for r in other['items']],[3])
        self.assertTrue(self.status()['can_send'])
        result=self.submit(self.body());self.assertEqual(result.status_code,201,result.text)
        self.assertEqual(result.json()['receipt_count'],1)

    def test_evidence_is_rechecked_at_send_without_version_bump(self):
        self.ready();body=self.body()
        sha=self.c.execute('SELECT u.source_sha256 FROM authorization_captures c JOIN authorization_uploads u ON u.id=c.upload_id').fetchone()[0]
        from app.storage import object_path
        object_path(self.root,sha).write_bytes(b'fictitious source changed')
        self.assertFalse(self.status()['can_send'])
        self.assertEqual(self.submit(body).status_code,409)
        self.assertEqual(self.c.execute('SELECT count(*) FROM invoice_handoff_rows').fetchone()[0],0)

    def test_mid_transfer_failure_rolls_back_versions_and_receipt(self):
        self.ready();body=self.body()
        self.c.execute("CREATE TRIGGER fictitious_failure BEFORE INSERT ON invoice_handoff_rows WHEN NEW.source_row=3 "
                       "BEGIN SELECT RAISE(ABORT,'fictitious receipt failure'); END")
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            self.submit(body)
        current=self.status()
        self.assertTrue(current['can_send'])
        self.assertEqual(current['revision_version'],body['expected_revision_version'])
        self.assertEqual(current['dataset_version'],body['expected_dataset_version'])
        self.assertEqual(self.c.execute('SELECT count(*) FROM invoice_handoff_rows').fetchone()[0],0)


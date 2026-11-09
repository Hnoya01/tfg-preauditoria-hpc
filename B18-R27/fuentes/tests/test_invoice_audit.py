"""Two fictitious TAC; all API writes and workbook bytes stay inside the test copy."""
from io import BytesIO
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from openpyxl import load_workbook
from app import invoice_audit
from tests import test_invoice_handoff as h


class AuditTests(TestCase):
    setUpClass=classmethod(h.HandoffTests.setUpClass.__func__)
    setUp=h.HandoffTests.setUp
    login=h.HandoffTests.login
    info=h.HandoffTests.info
    status=h.HandoffTests.status
    ready=h.HandoffTests.ready
    body=h.HandoffTests.body
    submit=h.HandoffTests.submit
    decision=h.HandoffTests.decision

    @property
    def url(self):
        return self.base+'/handoff/audit'

    def pass_invoice(self,*,login=True):
        self.ready();r=self.submit(self.body());self.assertEqual(r.status_code,201,r.text)
        if login:self.login('demo-auditor')

    def page(self,**query):
        r=self.client.get(self.url,params=query);self.assertEqual(r.status_code,200,r.text)
        return r.json()

    def version(self):
        p=self.page()
        return {'revision_id':p['revision_id'],'expected_dataset_version':p['dataset_version']}

    def adjust(self,number=2,value='200000.00',reason='Importe cotejado por auditor ficticio',version=None):
        return self.client.post(self.url+f'/rows/{number}',headers=self.h,json={
            **(version or self.version()),'amount_ars':value,'reason':reason})

    def closing(self):
        p=self.page()
        return {'revision_id':p['revision_id'],'expected_dataset_version':p['dataset_version'],
                'request_id':str(uuid4()),'expected_debit_ars':p['debit_ars']}

    def close(self,body):
        return self.client.post(self.url+'/close',headers=self.h,json=body)

    def test_two_tacs_adjust_close_once_and_download_immutable_workbook(self):
        self.pass_invoice()
        self.assertEqual(self.page()['debit_ars'],'250000.00')
        self.assertEqual(self.client.get(self.url+'/excel').status_code,409)
        reason='Presupuesto ficticio cotejado: débito final de la primera TAC'
        res=self.adjust(reason=reason);self.assertEqual(res.status_code,200,res.text)
        p=self.page(limit=1,offset=1)
        self.assertEqual((p['invoice_ars'],p['images_ars'],p['debit_ars'],p['net_ars'],p['debited_count']),
                         ('900000.00','900000.00','200000.00','700000.00',1))
        self.assertEqual(p['items'][0]['final_ars'],'0.00')
        original=self.page()['items'][0]
        self.assertEqual(original['amount_ars'],'250000.00');self.assertIn('DEMO-PRES-01',original['reason'])
        body=self.closing();r=self.close(body);self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.close(body).json(),r.json())
        self.assertEqual(self.close({**body,'request_id':str(uuid4())}).status_code,409)
        self.assertEqual(self.adjust().status_code,409)
        self.assertEqual(self.status()['state'],'closed')
        self.assertFalse(self.page()['can_adjust'])
        self.assertEqual(self.c.execute('SELECT state FROM revisions WHERE id=?',(body['revision_id'],)).fetchone()[0],'cerrada')
        x=self.client.get(self.url+'/excel');self.assertEqual(x.status_code,200,x.text[:0])
        self.assertIn('attachment',x.headers['Content-Disposition'])
        self.assertEqual(x.content,self.client.get(self.url+'/excel').content)
        wb=load_workbook(BytesIO(x.content));ws=wb.active
        self.assertEqual(list(ws.values),[('Orden','Importe final (ARS)','Motivo final'),
                         (original['order_number'],200000,reason)])
        self.assertEqual(ws['B2'].data_type,'n');wb.close()
        self.assertEqual(self.c.execute('SELECT count(*) FROM audit_invoice_closures').fetchone()[0],1)
        self.assertEqual(self.c.execute('SELECT count(*) FROM invoice_row_decisions').fetchone()[0],2)

    def test_stale_adjustment_stale_total_out_of_bounds_and_final_reason(self):
        self.pass_invoice()
        old=self.version();old_close=self.closing()
        for bad in ['-1','NaN','450000.01','1.111']:
            self.assertEqual(self.adjust(value=bad).status_code,422)
        self.assertEqual(self.adjust(reason=' ').status_code,422)
        self.assertEqual(self.adjust(reason=self.page()['items'][0]['reason']).status_code,422)
        self.assertEqual(self.adjust(number=555).status_code,404)
        self.assertEqual(self.adjust().status_code,200)
        self.assertEqual(self.adjust(version=old,value='7').status_code,409)
        self.assertEqual(self.close(old_close).status_code,409)
        self.assertEqual(self.close({**self.closing(),'expected_debit_ars':'0.00'}).status_code,409)
        self.assertEqual(self.adjust(value='200000',reason='Solo cambia el fundamento final').status_code,200)
        self.assertEqual([r[0] for r in self.c.execute('SELECT reason FROM audit_adjustments ORDER BY seq')],
                         ['Importe cotejado por auditor ficticio','Solo cambia el fundamento final'])

    def test_permissions_before_after_handoff_and_csrf(self):
        self.login('demo-auditor')
        self.assertEqual(self.client.get(self.url).status_code,409)
        self.login('demo-administrativo')
        self.assertEqual(self.client.post(self.base+'/closure-preview',headers=self.h).status_code,409)
        self.pass_invoice(login=False)
        for role in ['demo-administrativo','demo-admin']:
            self.login(role);self.assertFalse(self.page()['can_adjust'])
            self.assertEqual(self.adjust().status_code,403)
            self.assertEqual(self.close(self.closing()).status_code,403)
            self.assertEqual(self.client.get(self.url+'/excel').status_code,403)
        self.login('demo-auditor');body=self.closing()
        self.assertEqual(self.client.post(self.url+'/close',json=body,headers={'Origin':h.fixture.ORIGIN}).status_code,403)

    def test_unchanged_decisions_and_zero_debit_workbook(self):
        self.pass_invoice()
        original=self.page()['items']
        self.assertEqual(original[1]['reason'],original[1]['final_reason'])
        self.assertEqual(self.adjust(value='0',reason='Se descarta el importe tras el cotejo').status_code,200)
        result=self.close(self.closing());self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['debited_count'],0)
        wb=load_workbook(BytesIO(self.client.get(self.url+'/excel').content))
        self.assertEqual(wb.active.max_row,1);wb.close()

    def test_workbook_failure_rolls_back_then_retries_without_extra_close(self):
        self.pass_invoice();body=self.closing()
        with patch.object(invoice_audit,'workbook',side_effect=RuntimeError('fallo ficticio')):
            with self.assertRaises(RuntimeError):self.close(body)
        self.assertEqual(self.page()['dataset_version'],body['expected_dataset_version'])
        self.assertIsNone(self.page()['closed']);self.assertEqual(self.client.get(self.url+'/excel').status_code,409)
        self.assertEqual(self.close(body).status_code,200)
        wb=load_workbook(BytesIO(self.client.get(self.url+'/excel').content))
        self.assertEqual(wb.active['C2'].value,self.page()['items'][0]['reason']);wb.close()

    def test_two_concurrent_confirmations_publish_one_closure(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor
        from app.db import connect
        from app.security import token_digest
        from app.service import Problem
        self.pass_invoice();body=self.closing();barrier=threading.Barrier(2)
        token=token_digest(self.client.cookies.get('tfg_session'))
        def attempt():
            c=connect(self.root)
            try:
                barrier.wait(timeout=10)
                invoice_audit.confirm(c,self.root,token,self.ds,self.batch,{**body,'request_id':str(uuid4())})
                return 200
            except Problem as exc:return exc.status
            finally:c.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            calls=[pool.submit(attempt) for _ in range(2)]
            self.assertEqual(sorted(x.result() for x in calls),[200,409])
        self.assertEqual(self.c.execute('SELECT count(*) FROM audit_invoice_closures').fetchone()[0],1)

    def test_changed_evidence_blocks_close(self):
        self.pass_invoice();body=self.closing()
        sha=self.c.execute('SELECT u.source_sha256 FROM authorization_captures c JOIN authorization_uploads u ON u.id=c.upload_id').fetchone()[0]
        from app.storage import object_path
        object_path(self.root,sha).write_bytes(b'changed synthetic csv')
        self.assertEqual(self.close(body).status_code,409)
        self.assertIsNone(self.page()['closed'])

    def test_totals_include_unflagged_images_not_other_areas_or_excluded(self):
        imported=self.c.execute('SELECT id FROM invoice_imports LIMIT 1').fetchone()[0]
        fake=[{'source_row':n,'disposition':s,'family':f,'total_ars':v} for n,s,f,v in [
            (2,'included','images','450000.00'),(3,'included','images','123.45'),
            (4,'excluded','images','80.00'),(5,'included','other','10.00')]]
        scope=invoice_audit.scope_snapshot(self.c,imported,fake)
        summary=invoice_audit.totals(scope,[{'final_ars':'200000.00'}])
        self.assertEqual((summary['invoice_ars'],summary['image_count'],summary['images_ars'],summary['net_ars']),
                         ('900000.00',2,'450123.45','250123.45'))

    def test_same_order_keeps_two_rows_and_formula_like_text_is_literal(self):
        items=[{'order_number':'00017','final_ars':v,'final_reason':'=2+2'} for v in ('123.45','160.50')]
        wb=load_workbook(BytesIO(invoice_audit.workbook(items,'synthetic','rev')))
        ws=wb.active
        self.assertEqual(list(ws.values)[1:],[('00017',123.45,'=2+2'),('00017',160.50,'=2+2')])
        self.assertEqual((ws['C2'].data_type,ws['A3'].data_type),('s','s'));wb.close()


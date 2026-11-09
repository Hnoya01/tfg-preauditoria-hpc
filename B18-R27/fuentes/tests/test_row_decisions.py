"""Administrative decisions exercised against a generated fictitious invoice and CSV."""
import contextlib
import io
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.api import create_app
from app.db import connect
from app.row_decisions import candidates,resolve
from app.service import Problem
from decimal import Decimal
from scripts.create_review_journey_demo import main

ORIGIN='http://127.0.0.1:17309'


class RowDecisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        name='r17-tests-'+uuid4().hex
        with patch.object(sys,'argv',['demo','--presupuesto','--name',name]),contextlib.redirect_stdout(io.StringIO()):
            main()
        cls.sample=Path(__file__).resolve().parents[1]/'.tmp'/name
        cls.passwords=dict(l.split(': ',1) for l in (cls.sample/'credenciales-demo.txt').read_text().splitlines())

    def setUp(self):
        temp=tempfile.TemporaryDirectory(dir=self.sample.parent);self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        shutil.copytree(self.sample,self.root,dirs_exist_ok=True)
        self.c=connect(self.root);self.addCleanup(self.c.close)
        self.ds,self.batch=self.c.execute('SELECT dataset_id,id FROM batches').fetchone()
        self.base=f'/api/datasets/{self.ds}/batches/{self.batch}'
        self.client=self.enterContext(TestClient(create_app(self.root,public_origin=ORIGIN,local_http=True),base_url=ORIGIN))
        self.login('demo-administrativo')

    def login(self,name):
        self.client.cookies.clear()
        r=self.client.post('/api/session',json={'username':name,'password':self.passwords[name]},headers={'Origin':ORIGIN})
        self.assertEqual(r.status_code,200,r.text)
        self.h={'Origin':ORIGIN,'X-CSRF-Token':r.json()['csrf_token']}

    def info(self,n=2):
        r=self.client.get(self.base+f'/rows/{n}/administrative-decision')
        self.assertEqual(r.status_code,200,r.text);return r.json()

    def board(self,view='exceptions',**kwargs):
        r=self.client.post(self.base+'/practice-search',json={'family':'images','view':view,**kwargs},headers=self.h)
        self.assertEqual(r.status_code,200,r.text);return r.json()

    def body(self,action,**changes):
        i=self.info()
        return dict({'expected_dataset_version':i['dataset_version'],'expected_revision_version':i['revision_version'],
                    'revision_id':i['revision_id'],'evidence_hash':i['evidence_hash'],'request_id':str(uuid4()),
                    'action':action},**changes)

    def post(self,body):
        return self.client.post(self.base+'/rows/2/administrative-decision',json=body,headers=self.h)

    def test_accept_once_and_next(self):
        self.assertEqual(self.info()['proposal']['amount_ars'],'250000.00')
        body=self.body('accept')
        r=self.post(body);self.assertEqual(r.status_code,201,r.text)
        self.assertEqual(r.json()['amount_ars'],'250000.00')
        self.assertTrue(self.post(body).json()['replayed'])
        next_page=self.board(after_source_row=2,saved_source_row=2,limit=1)
        self.assertEqual(next_page['next_source_row'],3)
        self.assertFalse(next_page['saved_row_status']['in_exceptions'])
        self.assertEqual(next_page['row_decision_counts'],{'pending':1,'reviewed':1})
        self.assertEqual(self.board('row_reviewed')['items'][0]['source_row'],2)
        info=self.info()
        self.assertEqual(len(info['history']),1)
        self.assertIn('DEMO-PRES-01',info['history'][0]['reason'])
        self.assertTrue(info['current'])
        self.assertEqual(self.c.execute('SELECT count(*) FROM proposal_versions').fetchone()[0],0)
        self.assertEqual(self.c.execute('SELECT count(*) FROM revision_closures').fetchone()[0],0)

    def test_no_spoofed_amount_csrf_or_cross_row_retry(self):
        b=self.body('accept')
        denied=self.client.post(self.base+'/rows/2/administrative-decision',json=b,headers={'Origin':ORIGIN})
        self.assertEqual(denied.status_code,403)
        self.assertEqual(self.post({**b,'amount_ars':'1.00'}).status_code,422)
        self.assertEqual(self.post({**b,'evidence_hash':'0'*64}).status_code,409)
        self.assertEqual(self.post(b).status_code,201)
        self.assertEqual(self.post({**b,'action':'total','reason':'Otra decisión'}).status_code,409)
        other=self.client.post(self.base+'/rows/3/administrative-decision',json=b,headers=self.h)
        self.assertEqual(other.status_code,409)
        self.assertEqual(self.request_history_length(),1)

    def test_partial_total_none_and_history(self):
        for action,amount,partial in [('partial','100000.50','100000.50'),('total','450000.00',None),('none','0.00',None)]:
            fields={'reason':'Revisión ficticia por '+action}
            if partial:fields['partial_ars']=partial
            r=self.post(self.body(action,**fields));self.assertEqual(r.status_code,201,r.text)
            self.assertEqual(r.json()['amount_ars'],amount)
        h=self.info()['history'];self.assertEqual([x['action'] for x in h],['none','total','partial'])
        self.assertEqual(self.post(self.body('accept')).status_code,422)
        r=self.post(self.body('accept',reason='Corrijo tras cotejar el presupuesto ficticio'))
        self.assertEqual(r.status_code,201,r.text)
        h=self.info()['history'][0];self.assertIn('presupuesto',h['reason']);self.assertIn('Corrijo',h['correction_note'])

    def test_required_reason_bounds_and_closed_revision(self):
        for a in ['partial','total','none']:
            self.assertEqual(self.post(self.body(a)).status_code,422)
        for amount in ['-1','0','450000.00','450000.01','1.001','NaN','Infinity']:
            r=self.post(self.body('partial',partial_ars=amount,reason='Importe bajo prueba'))
            self.assertEqual(r.status_code,422,r.text)
        self.assertEqual(self.info()['history'],[])
        original=self.body('accept')
        self.c.execute("UPDATE revisions SET state='cerrada' WHERE id=?",(original['revision_id'],))
        self.assertEqual(self.post(original).status_code,409)

    def test_auditor_cannot_save_and_concurrent_correction_cannot_overwrite(self):
        old=self.body('total',reason='Propuesta alternativa ficticia')
        self.assertEqual(self.post(self.body('accept')).status_code,201)
        self.assertEqual(self.post(old).status_code,409)
        self.login('demo-auditor')
        self.assertFalse(self.info()['can_write'])
        self.assertEqual(self.post(self.body('none',reason='Intento de otra función')).status_code,403)
        self.assertEqual(len(self.info()['history']),1)

    def test_changed_source_returns_row_to_pending(self):
        self.assertEqual(self.post(self.body('accept')).status_code,201)
        capture=self.c.execute('SELECT u.source_sha256 FROM authorization_captures c JOIN authorization_uploads u ON c.upload_id=u.id').fetchone()[0]
        from app.storage import object_path
        object_path(self.root,capture).write_bytes(b'changed fictitious source')
        self.assertFalse(self.info()['current'])
        self.assertIn(2,[r['source_row'] for r in self.board()['items']])
        self.assertEqual(self.board('row_reviewed')['filtered_total'],0)
        self.assertIsNone(self.info()['proposal'])
        self.assertEqual(self.request_history_length(),1)

    def request_history_length(self):
        return self.c.execute('SELECT count(*) FROM invoice_row_decisions').fetchone()[0]

    def test_conflicting_tariffs_require_an_explicit_eligible_choice(self):
        csv={'budget':{'status':'over','order_id':'FICT','authorized_ars':'200000.00'}}
        ref={'candidate_total_if_ars_and_same_unit':'175000.00'}
        opts,conflict,proposal=candidates(Decimal('450000'),csv,ref,None,None)
        self.assertTrue(conflict);self.assertIsNone(proposal)
        info={'choices':opts,'conflict':conflict,'proposal':proposal,'billed_ars':'450000','blocked':False,'previous':None}
        for choice in [None,'agreement']:
            with self.assertRaises(Problem):resolve(info,{'action':'accept','reference':choice})
        with self.assertRaises(Problem):
            resolve(info,{'action':'accept','reference':'budget'})
        self.assertEqual(resolve(info,{'action':'accept','reference':'budget','reason':'El total individual consta en la orden.'})[0],Decimal('250000'))
        confirmed={'current':True,'basis':{'candidate':{'rate_ars':'175000.00'}},'confirmation':{'covered_quantity':'1'}}
        info['choices'],_,_=candidates(Decimal('450000'),csv,ref,confirmed,None)
        self.assertEqual(resolve(info,{'action':'accept','reference':'agreement','reason':'Convenio aplicable acreditado.'})[0],Decimal('275000'))


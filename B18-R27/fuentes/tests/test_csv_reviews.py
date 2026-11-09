import json
import unittest
from io import BytesIO
from uuid import uuid4
from openpyxl import load_workbook
from app.authorization_imports import stage_authorization, preview_authorization, confirm_authorization
from app.authorization_matching import save_scope
from app.controls import run_controls
from app.db import connect
from app.service import create_batch, confirm_invoice
from tests import test_economic_evidence as fixtures
from tests.test_hpc_csv_intake import row, encode
from tests.test_p02 import book


class CsvReviewTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.EconomicEvidenceTests()
        self.f.setUp()
        self.addCleanup(self.f.tearDown)
        self.conn = connect(self.f.root)
        self.addCleanup(self.conn.close)
        self.ds = self.f.dataset['id']
        self.code = '1234567890'
        self.patient = '000111/1'
        self.capture = self.make_capture()
        self.a = self.invoice('04/08/2026',39)
        self.b = self.invoice('02/08/2026',30)
        run_controls(self.conn,self.f.digest,self.ds,self.a,self.version())
        self.url = f'/api/datasets/{self.ds}/batches/{self.a}'

    def version(self):
        return self.conn.execute('SELECT version FROM datasets WHERE id=?',(self.ds,)).fetchone()[0]

    def make_capture(self, second=None):
        def order(identity, date, warning):
            return row(orden_hpc=identity, afiliado=self.patient, fecha_orden='2026-07-02',
                       fecha_orden_original='02/07/2026', practicas=f'{self.code} -- TAC de abdomen,',
                       advertencias=json.dumps(warning),
                       movimientos=f'{date} 12:00 | Ficticio | AUTORIZADO | Resolución por ítems - AUTORIZAR: {self.code}')
        orders = [order('FICT-A','02/07/2026',[])]
        if second:
            orders.append(order('FICT-B','03/08/2026',['requiere cotejo'] if second=='partial' else []))
        upload,_ = stage_authorization(self.conn,self.f.root,self.f.digest,self.ds,self.version(),'Ficticio.csv',encode(orders))
        preview = preview_authorization(self.conn,self.f.root,self.f.digest,self.ds,upload['id'])
        cap,_ = confirm_authorization(self.conn,self.f.root,self.f.digest,self.ds,upload['id'],self.version(),
                                      preview['preview_sha256'],'Fuente ficticia para comprobar el aval.')
        return cap['id']

    def invoice(self,day,total):
        wb = load_workbook(BytesIO(book([(day,10,20,total)])))
        for col,value in [(3,self.patient),(5,self.code),(7,1),(11,'TAC de abdomen')]:
            wb.active.cell(2,col).value = value
        buf = BytesIO()
        wb.save(buf)
        wb.close()
        batch,_ = create_batch(self.conn,self.f.root,self.f.digest,self.ds,self.version(),'FICT.xlsx',buf.getvalue())
        bid = batch['id']
        confirm_invoice(self.conn,self.f.root,self.f.digest,self.ds,bid,'2026-08',self.version())
        self.scope(bid,self.capture)
        return bid

    def scope(self, bid, cap):
        save_scope(self.conn,self.f.root,self.f.digest,self.ds,bid,self.version(),[cap],'real_unvalidated','Cotejo ficticio de la factura.')

    def detail(self):
        res=self.f.client.get(self.url+'/rows/2/authorization-correspondence')
        self.assertEqual(res.status_code,200,res.text)
        return res.json()

    def board(self):
        res=self.f.client.post(self.url+'/practice-search',headers=self.f.headers(),json={'view':'exceptions','saved_source_row':2})
        self.assertEqual(res.status_code,200,res.text)
        return res.json()

    def body(self):
        d=self.detail()
        return dict(version=d['dataset_version'],revision_id=d['revision_id'],revision_version=d['revision_version'],
                    evidence_sha256=d['csv_coverage']['review_basis'],request_id=str(uuid4()),
                    note='El aval del 2 de julio corresponde a la primera prestación ficticia.')

    def test_review_acknowledges_only_current_csv_warning_and_reopens_on_changed_source(self):
        url=self.url+'/rows/2/csv-coverage-review'
        body=self.body()
        def post(data):return self.f.client.post(url,json=data,headers=self.f.headers())
        self.assertEqual(self.f.client.post(url,json=body).status_code,403)
        self.assertEqual(post({**body,'version':body['version']-1}).status_code,409)
        d=post(body)
        self.assertEqual(d.status_code,201,d.text)
        self.assertTrue(post(body).json()['replayed'])
        self.assertEqual(post({**body,'note':'Otra justificación ficticia.'}).status_code,409)
        self.assertEqual(len(self.detail()['csv_review_history']),1)
        self.assertTrue(self.detail()['csv_coverage']['reviewed'])
        self.assertEqual(self.board()['items'][0]['exception_reasons'],['Aviso pendiente de decisión'])
        partial=self.make_capture(second='partial')
        for bid in (self.a,self.b):self.scope(bid,partial)
        self.assertFalse(self.detail()['csv_coverage']['reviewed'])
        self.assertIn('Revisar aval CSV',self.board()['items'][0]['exception_reasons'])
        self.assertEqual(sum('CSV parcial: 1 registro' in s for s in self.board()['source_notices']),1)
        current=self.body()
        self.assertEqual(post({**current,'evidence_sha256':body['evidence_sha256']}).status_code,409)
        self.assertEqual(post(current).status_code,201)
        full=self.make_capture(second='usable')
        for bid in (self.a,self.b):self.scope(bid,full)
        current=self.detail()
        self.assertEqual(current['csv_coverage']['status'],'one_unit_supported')
        self.assertEqual(len(current['csv_review_history']),2)
        self.assertFalse(any('CSV parcial' in s for s in self.board()['source_notices']))
        self.assertEqual(self.conn.execute('SELECT count(*) FROM proposal_versions').fetchone()[0],0)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM review_decisions').fetchone()[0],0)

    def test_resolving_last_material_alert_then_acknowledging_csv_leaves_exceptions(self):
        url=self.url+'/rows/2/observations'
        page=self.f.client.get(url).json()
        body=dict(expected_dataset_version=page['dataset_version'],expected_revision_version=page['revision_version'],
                  revision_id=page['revision_id'],run_id=page['run_id'],request_id=str(uuid4()),rule_code='RN13',
                  action='resolve',duty='administrative',foundation='El total difiere por nueve pesos.',
                  evidence_note='Hoja1, O2 a Q2: 10 y 20 frente a 39.',decision='confirmada')
        res=self.f.client.post(url,headers=self.f.headers(),json=body)
        self.assertEqual(res.status_code,201,res.text)
        self.assertEqual(self.board()['saved_row_status']['pending'],['Revisar el aval CSV'])
        res=self.f.client.post(self.url+'/rows/2/csv-coverage-review',headers=self.f.headers(),json=self.body())
        self.assertEqual(res.status_code,201,res.text)
        self.assertEqual(self.board()['filtered_total'],0)
        self.assertFalse(self.board()['saved_row_status']['in_exceptions'])
        self.assertEqual(self.detail()['csv_coverage']['status'],'already_used')

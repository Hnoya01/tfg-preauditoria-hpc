"""Fictional documentary-state filtering; no medical conclusion or analysis writes."""
import unittest
from uuid import uuid4
from unittest.mock import patch
from app.db import connect
from app.row_documents import batch_summary,summary
from app.practice_board import practice_search
from app.service import Problem
from tests import test_row_documents as fixtures

class DocumentFilterTests(unittest.TestCase):
    setUp=fixtures.RowDocumentTests.setUp
    tearDown=fixtures.RowDocumentTests.tearDown
    headers=fixtures.RowDocumentTests.headers
    import_book=fixtures.RowDocumentTests.import_book
    run_url=fixtures.RowDocumentTests.run_url
    base=fixtures.RowDocumentTests.base
    search=fixtures.RowDocumentTests.search
    alerts=fixtures.RowDocumentTests.alerts
    decide=fixtures.RowDocumentTests.decide
    url=fixtures.RowDocumentTests.url
    upload=fixtures.RowDocumentTests.upload
    def test_combined_family_filter_and_pages_count_entire_selection(self):
        result=self.upload();self.assertEqual(result.status_code,201,result.text)
        with patch('app.practice_board.catalog_families',return_value=({}, {}, {'available':True,'sources':[],'source_unavailable':False})),patch('app.practice_board.classify_family',return_value=('images','fixture')):
            page=self.search(family='images',report_document_state='aportado_sin_revisar',authorization_document_state='no_aportado',limit=1)
            self.assertEqual(page['filtered_total'],1);self.assertEqual(page['items'][0]['source_row'],2)
            self.assertEqual(page['items'][0]['patient_group_total'],1)
            self.assertEqual(self.search(family='images',report_document_state='aportado_sin_revisar',offset=1,limit=1)['items'],[])
            absent=self.search(family='images',report_document_state='no_aportado')
            self.assertEqual([r['source_row'] for r in absent['items']],[3])
        self.assertEqual(self.search(report_document_state='revisado_manualmente')['filtered_total'],0)
        page=self.client.get(self.url()).json()
        body={'revision_id':page['revision_id'],'expected_dataset_version':page['dataset_version'],'expected_revision_version':page['revision_version'],'request_id':str(uuid4()),'note':'Lectura documental ficticia, no conclusión clínica'}
        checked=self.client.post(self.url()+f'/{result.json()["id"]}/reviews',json=body,headers=self.headers())
        self.assertEqual(checked.status_code,200,checked.text)
        self.assertEqual(self.search(report_document_state='revisado_manualmente')['filtered_total'],1)
        self.assertEqual(self.search(authorization_document_state='aportado_sin_revisar')['filtered_total'],0)
    def test_bulk_query_bounded_and_matches_summary_without_writes(self):
        self.assertEqual(self.upload().status_code,201)
        conn=connect(self.root)
        from app.review import _batch
        batch=_batch(conn,self.dataset['id'],self.batch)
        count=conn.total_changes;statements=[];conn.set_trace_callback(statements.append)
        aggregate=batch_summary(conn,batch['import_id'],batch['revision_id'])
        conn.set_trace_callback(None)
        self.assertLessEqual(len(statements),3)
        self.assertEqual(aggregate[2]['informe'],summary(conn,batch['import_id'],2,batch['revision_id'])['informe'])
        self.assertEqual(conn.total_changes,count)
        before={t:conn.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in ('control_runs','review_decisions','proposal_versions')}
        for state in ('no_aportado','aportado_sin_revisar','revisado_manualmente'):
            practice_search(conn,self.digest,self.dataset['id'],self.batch,{'report_document_state':state},root=self.root)
        self.assertEqual(before,{t:conn.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in before});conn.close()
    def test_strict_payload_invalid_state_and_csrf(self):
        route=self.base()+'/practice-search'
        for payload in ({'report_document_state':'approved'},{'authorization_document_state':'approved'},{'medical_compliant':True}):
            self.assertEqual(self.client.post(route,json=payload,headers=self.headers()).status_code,422)
        self.assertEqual(self.client.post(route,json={'report_document_state':'no_aportado'}).status_code,403)
    def test_version_recheck_and_revocation_still_block_filtered_results(self):
        conn=connect(self.root)
        def change():conn.execute('UPDATE datasets SET version=version+1 WHERE id=?',(self.dataset['id'],))
        with self.assertRaises(Problem) as changed:
            practice_search(conn,self.digest,self.dataset['id'],self.batch,{'report_document_state':'no_aportado'},root=self.root,after_read=change)
        self.assertEqual(changed.exception.status,409)
        def revoke():conn.execute('DELETE FROM sessions WHERE token_hash=?',(self.digest,))
        with self.assertRaises(Problem) as denied:
            practice_search(conn,self.digest,self.dataset['id'],self.batch,{'report_document_state':'no_aportado'},root=self.root,after_read=revoke)
        self.assertEqual(denied.exception.status,401);conn.close()

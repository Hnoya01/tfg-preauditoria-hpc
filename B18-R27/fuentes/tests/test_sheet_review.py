"""B-UI2 preview/commit semantics with fictional cases only."""

import unittest

from app.db import connect
from app.practice_board import decision_preview
from app.security import create_user
from app.service import Problem
from tests import test_practice_board as fixture
from tests.test_p02 import book, PASSWORD, ORIGIN
from fastapi.testclient import TestClient
from app.api import create_app


class SheetDecisionTests(unittest.TestCase):
    setUp=fixture.PracticeBoardTests.setUp
    tearDown=fixture.PracticeBoardTests.tearDown
    headers=fixture.PracticeBoardTests.headers
    import_book=fixture.PracticeBoardTests.import_book
    run_url=fixture.PracticeBoardTests.run_url
    base=fixture.PracticeBoardTests.base
    search=fixture.PracticeBoardTests.search

    def selection(self):
        page=self.search()
        return {'expected_dataset_version':page['dataset_version'],'expected_revision_version':page['batch']['revision_version'],
                'items':[{'id':a['id'],'expected_version':a['version']} for row in page['items'] for a in row['alerts'] if a['current']]}

    def preview(self,body=None):
        return self.client.post(self.base()+'/decision-preview',json=body or self.selection(),headers=self.headers())

    def save(self,body,sha,**overrides):
        return self.client.post(self.base()+'/decisions',headers=self.headers(),json={**body,'preview_sha256':sha,
            'state':'no_concluyente','foundation':'Fundamento ficticio común cotejado caso por caso.',**overrides})

    def test_explicit_preview_is_read_only_and_commit_keeps_individual_history(self):
        body=self.selection();preview=self.preview(body)
        self.assertEqual(preview.status_code,200,preview.text)
        data=preview.json();self.assertEqual(data['count'],2)
        self.assertIsNone(data['proposal_amount_ars']);self.assertFalse(data['decision_written'])
        conn=connect(self.root)
        self.assertEqual(conn.execute('SELECT count(*) FROM review_decisions').fetchone()[0],0);conn.close()
        self.assertEqual({i['rule_code'] for i in data['items']},{'RN17'})
        saved=self.save(body,data['preview_sha256']);self.assertEqual(saved.status_code,200,saved.text)
        self.assertEqual(len(saved.json()['decision_ids']),2)
        page=self.search()
        self.assertTrue(all(i['decision']=='no_concluyente' for i in page['items']))
        conn=connect(self.root)
        self.assertEqual(conn.execute('SELECT count(DISTINCT group_id) FROM review_decisions').fetchone()[0],1)
        self.assertEqual(conn.execute('SELECT count(*) FROM proposal_versions').fetchone()[0],0);conn.close()
        self.assertEqual(self.save(body,data['preview_sha256']).status_code,409)

    def test_preview_cannot_be_reused_for_another_selection_and_confirm_requires_evidence(self):
        body=self.selection();preview=self.preview(body).json()
        self.assertEqual(self.save({**body,'items':body['items'][:1]},preview['preview_sha256']).status_code,409)
        self.assertEqual(self.save(body,preview['preview_sha256'],state='confirmada').status_code,422)
        self.assertEqual(self.save(body,preview['preview_sha256'],state='confirmada',evidence_note='Evidencia ficticia explícita de cada candidato revisado.').status_code,200)

    def test_mixed_controls_are_rejected_before_any_write(self):
        self.batch=self.import_book(book([('15/08/2026',10,20,99),('16/08/2026',10,20,30)]),'MIXTO_FICTICIO.xlsx')
        analyzed=self.client.post(self.run_url(),json={'expected_version':self.dataset['version']},headers=self.headers())
        self.assertEqual(analyzed.status_code,201,analyzed.text);self.dataset['version']+=1
        body=self.selection();self.assertGreater(len(body['items']),1)
        response=self.preview(body);self.assertEqual(response.status_code,422,response.text)
        self.assertEqual(self.save(body,'0'*64).status_code,422)
        conn=connect(self.root)
        self.assertEqual(conn.execute('SELECT count(*) FROM review_decisions').fetchone()[0],0);conn.close()

    def test_preview_permissions_csrf_and_versions_revalidated(self):
        body=self.selection()
        self.assertEqual(self.client.post(self.base()+'/decision-preview',json=body,headers={'Origin':ORIGIN}).status_code,403)
        conn=connect(self.root)
        create_user(conn,'unassigned',PASSWORD,'reviewer')
        conn.close()
        for name in ('viewer','unassigned'):
            with TestClient(create_app(self.root,public_origin=ORIGIN),base_url=ORIGIN) as other:
                login=other.post('/api/session',headers={'Origin':ORIGIN},json={'username':name,'password':PASSWORD}).json()
                self.assertEqual(other.post(self.base()+'/decision-preview',json=body,headers={'Origin':ORIGIN,'X-CSRF-Token':login['csrf_token']}).status_code,403)
        conn=connect(self.root)
        def change():
            other=connect(self.root);other.execute('UPDATE datasets SET version=version+1 WHERE id=?',(self.dataset['id'],));other.close()
        with self.assertRaises(Problem) as conflict:
            decision_preview(conn,self.digest,self.dataset['id'],self.batch,**body,after_read=change)
        self.assertEqual(conflict.exception.status,409);conn.close()

    def test_a_changed_member_makes_the_entire_action_fail(self):
        body=self.selection();preview=self.preview(body).json()
        conn=connect(self.root)
        conn.execute('UPDATE alerts SET version=version+1 WHERE id=?',(body['items'][-1]['id'],));conn.close()
        self.assertEqual(self.save(body,preview['preview_sha256']).status_code,409)
        conn=connect(self.root)
        self.assertEqual(conn.execute('SELECT count(*) FROM review_decisions').fetchone()[0],0);conn.close()

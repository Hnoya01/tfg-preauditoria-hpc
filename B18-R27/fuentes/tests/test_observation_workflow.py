"""Synthetic internal workflow: partial resolution, access, races and recovery."""
import json
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4
from pathlib import Path
from io import BytesIO
from zipfile import ZipFile
from tests import test_p05 as fixture
from tests.test_p02 import book, PASSWORD, ORIGIN
from tests.temp_support import TemporaryDirectory
from app.db import connect,migrate,MIGRATIONS,backup_before_upgrade
from app.security import create_user,issue_session,token_digest
from app.observation_workflow import save,page
from app.service import Problem


class ObservationTests(unittest.TestCase):
    for name in ('setUp','tearDown','headers','import_book','run_url','alerts'):
        locals()[name]=getattr(fixture.P05Tests,name)
    del name

    def base(self):return f'/api/datasets/{self.dataset["id"]}/batches/{self.batch}'
    def url(self):return self.base()+'/rows/2/observations'
    def page(self):
        r=self.client.get(self.url());self.assertEqual(r.status_code,200,r.text);return r.json()
    def body(self,action='refer',duty='administrative',rule='RN17',**extra):
        p=self.page()
        return dict(expected_dataset_version=p['dataset_version'],expected_revision_version=p['revision_version'],
            revision_id=p['revision_id'],run_id=p['run_id'],request_id=str(uuid4()),rule_code=rule,
            action=action,duty=duty,foundation='FICTICIO: ¿son prestaciones distintas según las dos constancias?',
            evidence_note='FICTICIO: comprobé identidad y fechas; falta valorar las dos constancias.',decision=None,**extra)
    def post(self,body):return self.client.post(self.url(),headers=self.headers(),json=body)
    def ok(self,body):
        r=self.post(body);self.assertEqual(r.status_code,201,r.text);return r.json()
    def item(self,rule='RN17'):return next(i for i in self.page()['items'] if i['rule_code']==rule)
    def with_sum(self):
        self.batch=self.import_book(book([('15/08/2026',10,20,39)]),'FICTICIO suma y repeticion.xlsx')
        r=self.client.post(self.run_url(),headers=self.headers(),json={'expected_version':self.dataset['version']});self.assertEqual(r.status_code,201,r.text)
        self.dataset['version']+=1

    def test_auditor_closes_only_consulted_observation(self):
        self.with_sum();self.ok(self.body())
        b=self.body('resolve','auditor');b['decision']='descartada';self.ok(b)
        self.assertEqual(self.item()['state'],'resolved');self.assertEqual(self.item('RN13')['state'],'pending')
        c=connect(self.root)
        try:
            self.assertEqual(c.execute('SELECT count(*) FROM review_decisions').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT count(*) FROM revision_closures').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT count(*) FROM proposal_versions').fetchone()[0],0)
        finally:c.close()
        with ZipFile(BytesIO(self.client.get(self.base()+'/export-provisional').content)) as z:
            self.assertEqual(len(z.read('observation_events.jsonl').splitlines()),2)

    def test_advance_after_resolving_last_alert_uses_current_membership_and_history(self):
        def board(**filters):
            result=self.client.post(self.base()+'/practice-search',headers=self.headers(),
                                    json={'view':'exceptions','limit':1,**filters})
            self.assertEqual(result.status_code,200,result.text)
            return result.json()
        before=board()
        self.assertEqual(before['filtered_total'],2)
        body=self.body('resolve');body['decision']='descartada'
        from app import observation_workflow, controls
        with patch.object(observation_workflow,'_run_summary',wraps=observation_workflow._run_summary) as first, \
             patch.object(controls,'_run_summary',wraps=controls._run_summary) as second:
            saved=self.ok(body)
            self.assertEqual(first.call_count,1)
            self.assertEqual(second.call_count,0)
        after=board(after_source_row=2,saved_source_row=2)
        self.assertFalse(after['saved_row_status']['in_exceptions'])
        self.assertEqual(after['saved_row_status']['pending'],[])
        self.assertEqual(after['saved_row_status']['inconclusive'],5)
        self.assertEqual(after['saved_row_status']['unevaluated'],1)
        self.assertEqual(after['dataset_version'],saved['dataset_version'])
        self.assertEqual(after['filtered_total'],1)
        self.assertEqual(after['next_source_row'],3)
        self.assertEqual([r['source_row'] for r in after['items']],[3])
        self.assertEqual(after['next_review'],self.client.get(self.base()+'/rows/3/observations').json())
        self.assertEqual(self.item()['state'],'resolved')
        self.assertIsNone(board(after_source_row=3)['next_review'])

    def test_admin_can_resolve_sum_and_information_without_debit(self):
        self.with_sum()
        for rule in ('RN13','RN09','RN14'):
            b=self.body('resolve',rule=rule);b['decision']='descartada';self.ok(b)
            self.assertEqual(self.item(rule)['state'],'resolved')
        c=connect(self.root)
        try:self.assertEqual(c.execute('SELECT count(*) FROM proposal_versions').fetchone()[0],0)
        finally:c.close()

    def test_information_request_response_do_not_resolve(self):
        self.ok(self.body());self.ok(self.body('request_info','auditor'))
        self.assertEqual(self.item()['state'],'waiting_information')
        bad=self.body('resolve','auditor');bad['decision']='descartada';self.assertEqual(self.post(bad).status_code,409)
        self.ok(self.body('provide_info'))
        self.assertEqual(self.item()['state'],'referred')
        self.assertEqual([h['action'] for h in self.item()['history']],['refer','request_info','provide_info'])
        self.assertEqual(self.item()['decision'],'pendiente')

    def test_lost_response_exact_retry_and_changed_body(self):
        b=self.body();first=self.ok(b);again=self.ok(b)
        self.assertTrue(again['replayed']);self.assertEqual(first['id'],again['id'])
        self.assertEqual(len(self.item()['history']),1)
        self.assertEqual(self.post({**b,'foundation':'FICTICIO: otra pregunta concreta.'}).status_code,409)
        b=self.body('resolve','auditor');b['decision']='descartada';first=self.ok(b);self.assertEqual(first['id'],self.ok(b)['id'])
        self.assertEqual(len(self.item()['history']),2)

    def test_two_writers_only_one_commits(self):
        b=self.body();barrier=Barrier(2)
        def worker(request_id):
            c=connect(self.root)
            try:
                barrier.wait()
                try:save(c,self.digest,self.dataset['id'],self.batch,2,**{**b,'request_id':request_id});return 201
                except Problem as e:return e.status
            finally:c.close()
        with ThreadPoolExecutor(2) as pool:
            results=list(pool.map(worker,[str(uuid4()),str(uuid4())]))
        self.assertEqual(sorted(results),[201,409]);self.assertEqual(len(self.item()['history']),1)

    def test_atomic_failure_restores_decision_and_versions(self):
        b=self.body('resolve');b['decision']='descartada';before=self.page()
        c=connect(self.root)
        try:
            with patch('app.observation_workflow.event',side_effect=RuntimeError('FICTICIO fallo')):
                with self.assertRaises(RuntimeError):save(c,self.digest,self.dataset['id'],self.batch,2,**b)
            self.assertEqual(c.execute('SELECT count(*) FROM review_decisions').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT count(*) FROM observation_events').fetchone()[0],0)
        finally:c.close()
        self.assertEqual(before,self.page())

    def test_permissions_revocation_csrf_and_own_auditor_account(self):
        c=connect(self.root)
        try:
            reviewer=create_user(c,'auditor-ficticio',PASSWORD,'reviewer');token,_=issue_session(c,reviewer);token=token_digest(token)
            with self.assertRaises(Problem):page(c,token,self.dataset['id'],self.batch,2)
            c.execute('INSERT INTO dataset_access VALUES(?,?,?)',(self.dataset['id'],reviewer,'reviewer'))
            self.ok(self.body());b=self.body('resolve','auditor');b['decision']='descartada'
            result=save(c,token,self.dataset['id'],self.batch,2,**b)
            self.assertEqual(self.item()['history'][-1]['actor'],'auditor-ficticio')
            c.execute('DELETE FROM dataset_access WHERE user_id=?',(reviewer,))
            with self.assertRaises(Problem):save(c,token,self.dataset['id'],self.batch,2,**b)
        finally:c.close()
        self.assertEqual(self.client.post(self.url(),json=self.body()).status_code,403)

    def test_stale_evidence_and_versions_reject_without_erasing_history(self):
        self.ok(self.body());b=self.body('resolve','auditor');b['decision']='descartada'
        r=self.client.post(self.base()+'/rows/2/work-fields',headers=self.headers(),json={
            'field':'B','value':'999999','reason':'FICTICIO: nueva evidencia sobre la orden.',
            'expected_dataset_version':b['expected_dataset_version'],'expected_revision_version':b['expected_revision_version']})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.post(b).status_code,409)
        self.assertEqual(self.item()['state'],'requires_update');self.assertEqual(len(self.item()['history']),1)
        fresh=self.body('resolve','auditor');fresh['decision']='descartada'
        self.assertEqual(self.post(fresh).status_code,409)

    def test_equivalent_reanalysis_reuses_internal_resolution_with_provenance(self):
        b=self.body('resolve',rule='RN09');b['decision']='descartada';self.ok(b)
        before=self.page()
        changed=self.client.post(self.base()+'/rows/3/work-fields',headers=self.headers(),json={'field':'K','value':'Descripción ficticia aclarada','reason':'FICTICIO: aclaración ajena a la fila 2.','expected_dataset_version':before['dataset_version'],'expected_revision_version':before['revision_version']})
        self.assertEqual(changed.status_code,200,changed.text)
        before=self.page()
        r=self.client.post(self.run_url(),headers=self.headers(),json={'expected_version':before['dataset_version']})
        self.assertEqual(r.status_code,201,r.text)
        item=self.item('RN09');self.assertEqual(item['state'],'resolved')
        if self.page()['run_id']!=before['run_id']:self.assertTrue(item['reused'])
        self.assertEqual(len(item['history']),1)

    def test_close_and_successor_keep_export_and_replay_without_new_events(self):
        from tests import test_revisions as revisions
        f=revisions.NewRevisionTests();f.setUp()
        try:
            url=f.base()+'/rows/2/observations';p=f.client.get(url).json()
            body=dict(expected_dataset_version=p['dataset_version'],expected_revision_version=p['revision_version'],
                revision_id=p['revision_id'],run_id=p['run_id'],request_id=str(uuid4()),rule_code='RN17',action='refer',
                duty='administrative',foundation='FICTICIO: consulta por coincidencia documental.',
                evidence_note='FICTICIO: identidad comprobada; falta cotejar constancias.',decision=None)
            result=f.client.post(url,headers=f.headers(),json=body);self.assertEqual(result.status_code,201,result.text)
            f.dataset['version']=result.json()['dataset_version'];closed,frozen=f.freeze()
            self.assertTrue(f.client.post(url,headers=f.headers(),json=body).json()['replayed'])
            self.assertEqual(f.client.post(url,headers=f.headers(),json={**body,'request_id':str(uuid4())}).status_code,409)
            self.assertEqual(f.client.get(f.base()+'/export-closed').content,frozen)
            with ZipFile(BytesIO(frozen)) as archive:self.assertEqual(len(archive.read('observation_events.jsonl').splitlines()),1)
        finally:f.tearDown()

    def test_migration_additive_rollback_backup_and_immutable(self):
        with TemporaryDirectory() as t:
            root=Path(t);c=connect(root)
            try:
                migrate(c,MIGRATIONS[:26]);before=[tuple(r) for r in c.execute('SELECT * FROM users')]
                backup=backup_before_upgrade(c,root)
                with self.assertRaises(sqlite3.Error):migrate(c,MIGRATIONS[:26]+((27,dict(MIGRATIONS)[27]+('INVALID SQL',)),),allow_existing_upgrade=True)
                self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0],26)
                self.assertIsNone(c.execute("SELECT name FROM sqlite_master WHERE name='observation_events'").fetchone())
                self.assertEqual(migrate(c,MIGRATIONS[:27],allow_existing_upgrade=True),27)
                self.assertEqual(before,[tuple(r) for r in c.execute('SELECT * FROM users')]);self.assertIsNone(c.execute('PRAGMA foreign_key_check').fetchone())
                old=sqlite3.connect(backup/'app.sqlite3')
                try:self.assertEqual(old.execute('PRAGMA user_version').fetchone()[0],26)
                finally:old.close()
            finally:c.close()
        self.ok(self.body());c=connect(self.root)
        try:
            for sql in ('DELETE FROM observation_events',"UPDATE observation_events SET foundation='otra pregunta ficticia'"):
                with self.assertRaises(sqlite3.IntegrityError):c.execute(sql)
        finally:c.close()

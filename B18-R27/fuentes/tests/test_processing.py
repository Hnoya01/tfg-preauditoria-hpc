"""B-PROG uses fictional inputs, short test leases and real independent processes."""
from concurrent.futures import ThreadPoolExecutor
import json
import multiprocessing
import threading
import time
import unittest
from uuid import uuid4
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.api import create_app
from app.db import connect
from app.processing import ProcessingManager,claim,execute
from app.security import create_user
from tests import test_p04 as fixture
from tests.test_p02 import ORIGIN,PASSWORD
from tests.processing_worker import (gated_worker,racing_claim,racing_retry,
                                     pre_execution_worker,worker_stage_diagnostic)


class ProcessingTests(unittest.TestCase):
    headers=fixture.P04Tests.headers
    tearDown=fixture.P04Tests.tearDown

    def setUp(self):
        fixture.P04Tests.setUp(self)
        self.client.app.state.processing_manager.close()

    def url(self,suffix=''):
        return f'/api/datasets/{self.dataset["id"]}/batches/{self.batch}/processing-attempts'+suffix

    def history(self):
        response=self.client.get(self.url());self.assertEqual(response.status_code,200,response.text);return response.json()

    def body(self):
        context=self.history()
        return {'expected_dataset_version':context['dataset_version'],'expected_revision_version':context['revision_version'],'request_key':str(uuid4())}

    def enqueue(self,body=None):
        response=self.client.post(self.url(),json=body or self.body(),headers=self.headers())
        self.assertIn(response.status_code,(200,202),response.text);return response.json()

    def status(self,identity):
        response=self.client.get(self.url('/'+identity));self.assertEqual(response.status_code,200,response.text);return response.json()

    def claim(self,**kwargs):
        conn=connect(self.root)
        try:return claim(conn,'fictional-owner',**kwargs)
        finally:conn.close()

    def retry(self,job,body=None):
        return self.client.post(self.url('/'+job['id']+'/retry'),headers=self.headers(),json=body or {'request_key':str(uuid4()),'expected_attempt_version':job['version']})

    def counts(self):
        conn=connect(self.root)
        try:return tuple(conn.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('control_runs','control_results','processing_attempts'))
        finally:conn.close()

    def test_progress_publication_and_idempotent_receipt_and_result_reuse(self):
        body=self.body();queued=self.enqueue(body);self.assertEqual(queued['state'],'queued')
        self.assertEqual(queued['total_rows'],4);self.assertEqual(queued['processed_rows'],0)
        self.assertNotIn('session_hash',queued);self.assertNotIn('owner_id',queued)
        stages=[];execute(self.root,self.claim(),progress_hook=lambda s,n,t:stages.append((s,n,t)))
        completed=self.status(queued['id']);self.assertEqual(completed['state'],'completed')
        self.assertEqual(completed['processed_rows'],4);self.assertEqual(completed['result_created'],1)
        self.assertEqual(self.counts(),(1,44,1))
        self.assertIn(('evaluating',4,4),stages)
        self.assertEqual(self.enqueue(body)['id'],queued['id'])  # Original expected version is now old.
        second=self.enqueue();execute(self.root,self.claim())
        reused=self.status(second['id']);self.assertEqual(reused['state'],'completed')
        self.assertEqual(reused['result_created'],0);self.assertEqual(reused['processed_rows'],0)
        self.assertEqual(reused['result_run_id'],completed['result_run_id']);self.assertEqual(self.counts(),(1,44,2))

    def test_one_active_and_only_one_worker_claim(self):
        original=self.enqueue()
        self.assertEqual(self.client.post(self.url(),json=self.body(),headers=self.headers()).status_code,409)
        def worker(owner):
            conn=connect(self.root)
            try:return claim(conn,owner)
            finally:conn.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            rows=list(pool.map(worker,('fictional-a','fictional-b')))
        self.assertEqual(sum(r is not None for r in rows),1)
        self.assertEqual(next(r for r in rows if r)['id'],original['id'])
        conn=connect(self.root);conn.execute('UPDATE processing_attempts SET lease_until=? WHERE id=?',(time.time()-1,original['id']));conn.close()
        old=self.status(original['id']);ctx=multiprocessing.get_context('spawn')
        def race(target,payloads):
            start=ctx.Event();readers=[];children=[];signals=[]
            try:
                for payload in payloads:
                    reader,writer=ctx.Pipe(duplex=False);ready=ctx.Event()
                    process=ctx.Process(target=target,args=(str(self.root.resolve()),ready,start,writer,payload))
                    process.start();writer.close();readers.append(reader);children.append(process);signals.append(ready)
                self.assertTrue(all(signal.wait(10) for signal in signals));start.set()
                result=[]
                for reader in readers:self.assertTrue(reader.poll(10));result.append(reader.recv())
                for process in children:process.join(5);self.assertEqual(process.exitcode,0)
                return result
            finally:
                for process in children:
                    if process.is_alive():process.terminate()
                    process.join(5)
                for reader in readers:reader.close()
        arguments=[{'token_hash':self.digest,'dataset_id':self.dataset['id'],'batch_id':self.batch,'attempt_id':old['id'],
                    'request_key':str(uuid4()),'expected_attempt_version':old['version']} for _ in range(2)]
        retried=race(racing_retry,arguments)
        self.assertEqual(retried[0][0],retried[1][0]);self.assertEqual(sum(created for _,created in retried),1)
        claimed=race(racing_claim,('fictional-process-a','fictional-process-b'))
        self.assertEqual(sum(identity is not None for identity in claimed),1)
        self.assertEqual(next(identity for identity in claimed if identity),retried[0][0])

    def test_expired_attempt_is_readable_and_retry_has_single_lineage_child(self):
        original=self.enqueue();job=self.claim()
        conn=connect(self.root);conn.execute('UPDATE processing_attempts SET lease_until=? WHERE id=?',(time.time()-1,job['id']));conn.close()
        stale=self.status(original['id']);self.assertEqual(stale['state'],'interrupted');self.assertTrue(stale['can_retry'])
        conn=connect(self.root);self.assertEqual(conn.execute('SELECT state FROM processing_attempts').fetchone()[0],'running');conn.close()
        body={'request_key':str(uuid4()),'expected_attempt_version':stale['version']}
        first=self.retry(stale,body);self.assertEqual(first.status_code,202,first.text)
        self.assertEqual(self.retry(stale,body).json()['id'],first.json()['id'])
        self.assertEqual(self.retry(stale).json()['id'],first.json()['id'])
        execute(self.root,job)  # The old lease cannot publish after an explicit retry.
        execute(self.root,self.claim())
        child=self.status(first.json()['id']);self.assertEqual(child['state'],'completed')
        self.assertEqual(child['previous_id'],stale['id']);self.assertEqual(self.counts(),(1,44,2))

    def test_version_or_permission_change_prevents_publication(self):
        queued=self.enqueue()
        def change(stage,done,total):
            if stage=='evaluating' and done==0:
                conn=connect(self.root);conn.execute('UPDATE datasets SET version=version+1 WHERE id=?',(self.dataset['id'],));conn.close()
        execute(self.root,self.claim(),progress_hook=change)
        blocked=self.status(queued['id']);self.assertEqual(blocked['state'],'blocked');self.assertFalse(blocked['can_retry'])
        self.assertEqual(self.counts()[:2],(0,0));self.assertEqual(self.retry(blocked).status_code,409)
        next_job=self.enqueue()
        def revoke(stage,done,total):
            if stage=='evaluating' and done==0:
                conn=connect(self.root);conn.execute('DELETE FROM sessions WHERE token_hash=?',(self.digest,));conn.close()
        execute(self.root,self.claim(),progress_hook=revoke)
        conn=connect(self.root)
        row=conn.execute('SELECT state,error_code FROM processing_attempts WHERE id=?',(next_job['id'],)).fetchone()
        self.assertEqual(tuple(row),('blocked','permission_changed'));conn.close();self.assertEqual(self.counts()[:2],(0,0))

    def test_technical_error_is_sanitized_and_explicit_retry_keeps_failed_attempt(self):
        queued=self.enqueue()
        with patch('app.processing.run_controls',side_effect=ValueError('PRIVATE_FICTITIOUS_IDENTIFIER')):
            execute(self.root,self.claim())
        failed=self.status(queued['id']);self.assertEqual(failed['state'],'failed');self.assertTrue(failed['can_retry'])
        self.assertNotIn('PRIVATE_FICTITIOUS_IDENTIFIER',str(failed))
        response=self.retry(failed);self.assertEqual(response.status_code,202,response.text)
        execute(self.root,self.claim());self.assertEqual(self.status(response.json()['id'])['state'],'completed')
        self.assertEqual(self.status(queued['id'])['state'],'failed')

    def test_graceful_stop_and_initial_revision_fence(self):
        queued=self.enqueue();stop=threading.Event();stop.set();execute(self.root,self.claim(),stop)
        self.assertEqual(self.status(queued['id'])['state'],'interrupted');self.assertEqual(self.counts()[:2],(0,0))
        child=self.retry(self.status(queued['id'])).json()
        conn=connect(self.root);conn.execute('UPDATE revisions SET version=version+1');conn.close()
        execute(self.root,self.claim())
        self.assertEqual(self.status(child['id'])['state'],'blocked');self.assertEqual(self.counts()[:2],(0,0))
        final=self.enqueue();job=self.claim()
        def expire_at_publication(conn,run_id):
            conn.execute("UPDATE sessions SET expires_at='2000-01-01T00:00:00+00:00' WHERE token_hash=?",(job['session_hash'],))
        execute(self.root,job,publication_hook=expire_at_publication)
        result=self.status(final['id']);self.assertEqual(result['state'],'blocked');self.assertEqual(result['error_code'],'permission_changed')
        self.assertEqual(self.counts()[:2],(0,0))
        wrong_basis=self.enqueue();job=self.claim();job['input_sha256']='0'*64
        execute(self.root,job)
        result=self.status(wrong_basis['id']);self.assertEqual(result['state'],'blocked');self.assertEqual(result['error_code'],'inputs_changed')
        self.assertEqual(self.counts()[:2],(0,0))

    def test_permissions_cross_resource_and_csrf(self):
        body=self.body();self.assertEqual(self.client.post(self.url(),json=body,headers={'Origin':ORIGIN}).status_code,403)
        queued=self.enqueue()
        conn=connect(self.root);create_user(conn,'unassigned',PASSWORD,'reviewer');create_user(conn,'viewer',PASSWORD,'viewer');conn.close()
        for user in ('unassigned','viewer'):
            with TestClient(create_app(self.root,public_origin=ORIGIN,processing_enabled=False),base_url=ORIGIN) as other:
                login=other.post('/api/session',json={'username':user,'password':PASSWORD},headers={'Origin':ORIGIN}).json()
                self.assertEqual(other.get(self.url()).status_code,403)
                self.assertEqual(other.post(self.url(),json=body,headers={'Origin':ORIGIN,'X-CSRF-Token':login['csrf_token']}).status_code,403)
        other=self.client.post('/api/datasets',json={'label':'Otro conjunto ficticio'},headers=self.headers()).json()
        wrong=f'/api/datasets/{other["id"]}/batches/{self.batch}/processing-attempts/{queued["id"]}'
        self.assertEqual(self.client.get(wrong).status_code,404)

    def test_background_manager_processes_a_request_without_another_http_action(self):
        queued=self.enqueue()
        with TestClient(create_app(self.root,public_origin=ORIGIN,processing_enabled=False),base_url=ORIGIN) as probe:
            probe.post('/api/session',json={'username':'owner','password':PASSWORD},headers={'Origin':ORIGIN})
            self.assertEqual(probe.get(self.url()).status_code,200);time.sleep(.3)
            self.assertEqual(self.status(queued['id'])['state'],'queued');self.assertEqual(self.counts()[:2],(0,0))
        manager=ProcessingManager(self.root);manager.start()
        try:
            deadline=time.monotonic()+8
            while time.monotonic()<deadline and self.status(queued['id'])['state'] in ('queued','running'):
                time.sleep(.03)
            self.assertEqual(self.status(queued['id'])['state'],'completed')
        finally:manager.close()

    def test_access_revoked_from_original_reviewer_blocks_publication(self):
        conn=connect(self.root);reviewer=create_user(conn,'assigned_reviewer',PASSWORD,'reviewer');conn.close()
        granted=self.client.post(f'/api/datasets/{self.dataset["id"]}/access',headers=self.headers(),json={
            'username':'assigned_reviewer','role':'reviewer','expected_version':self.dataset['version']})
        self.assertEqual(granted.status_code,200,granted.text)
        with TestClient(create_app(self.root,public_origin=ORIGIN,processing_enabled=False),base_url=ORIGIN) as other:
            login=other.post('/api/session',json={'username':'assigned_reviewer','password':PASSWORD},headers={'Origin':ORIGIN}).json()
            body=self.body();queued=other.post(self.url(),json=body,headers={'Origin':ORIGIN,'X-CSRF-Token':login['csrf_token']})
            self.assertEqual(queued.status_code,202,queued.text)
            def revoke(stage,done,total):
                if stage=='evaluating' and done==0:
                    conn=connect(self.root);conn.execute('DELETE FROM dataset_access WHERE dataset_id=? AND user_id=?',(self.dataset['id'],reviewer));conn.close()
            execute(self.root,self.claim(),progress_hook=revoke)
            result=self.status(queued.json()['id']);self.assertEqual(result['state'],'blocked')
            self.assertEqual(result['error_code'],'permission_changed');self.assertEqual(self.counts()[:2],(0,0))

    def test_failed_attempt_preserves_independent_existing_controls(self):
        analyzed=self.client.post(f'/api/datasets/{self.dataset["id"]}/batches/{self.batch}/control-runs',headers=self.headers(),json={'expected_version':self.dataset['version']})
        self.assertEqual(analyzed.status_code,201,analyzed.text);run_id=analyzed.json()['id']
        work=f'/api/datasets/{self.dataset["id"]}/batches/{self.batch}/rows/2/work-fields'
        def edit(value):
            context=self.history()
            changed=self.client.post(work,headers=self.headers(),json={'field':'K','value':value,'reason':'Corrección ficticia de descripción con evidencia.',
                'expected_dataset_version':context['dataset_version'],'expected_revision_version':context['revision_version']})
            self.assertEqual(changed.status_code,200,changed.text)
        edit('Descripción ficticia primera revisión');queued=self.enqueue()
        def change(stage,done,total):
            if stage=='evaluating' and done==0:edit('Descripción ficticia segunda revisión')
        execute(self.root,self.claim(),progress_hook=change)
        self.assertEqual(self.status(queued['id'])['state'],'blocked');self.assertEqual(self.counts()[:2],(1,44))
        summary=self.client.get(f'/api/datasets/{self.dataset["id"]}/control-runs/{run_id}').json()
        from app.dependencies import result_affected
        self.assertFalse(result_affected(summary,2,'RN13'));self.assertFalse(result_affected(summary,2,'RN17'))
        self.assertTrue(result_affected(summary,2,'RN09'))

    def crash(self,phase):
        conn=connect(self.root);create_user(conn,'observer',PASSWORD,'reviewer');conn.close()
        granted=self.client.post(f'/api/datasets/{self.dataset["id"]}/access',headers=self.headers(),json={
            'username':'observer','role':'reviewer','expected_version':self.dataset['version']})
        self.assertEqual(granted.status_code,200,granted.text)
        observer=TestClient(create_app(self.root,public_origin=ORIGIN,processing_enabled=False),base_url=ORIGIN);observer.__enter__()
        observer.post('/api/session',json={'username':'observer','password':PASSWORD},headers={'Origin':ORIGIN})
        queued=self.enqueue();ctx=multiprocessing.get_context('spawn');ready,release=ctx.Event(),ctx.Event()
        worker=ctx.Process(target=gated_worker,args=(str(self.root.resolve()),ready,release,phase));worker.start()
        try:
            reached=ready.wait(10)
            detail='' if reached else json.dumps(worker_stage_diagnostic(self.root,queued['id'],worker),sort_keys=True)
            self.assertTrue(reached,'Worker did not reach controlled stage; '+detail)
            started=time.monotonic()
            for client in (self.client,observer):self.assertEqual(client.get(self.url()).status_code,200)
            self.assertLess(time.monotonic()-started,3)
            self.assertEqual(self.counts()[:2],(0,0))
            worker.terminate();worker.join(5);self.assertFalse(worker.is_alive())
            deadline=time.monotonic()+4
            while time.monotonic()<deadline and self.status(queued['id'])['state']=='running':time.sleep(.03)
            self.assertEqual(self.status(queued['id'])['state'],'interrupted')
            manager=ProcessingManager(self.root);manager.start()
            try:
                time.sleep(.3);self.assertEqual(self.counts()[:2],(0,0))  # Restart does not retry failed work.
            finally:manager.close()
            old=self.status(queued['id']);result=self.retry(old);self.assertEqual(result.status_code,202,result.text)
            execute(self.root,self.claim());self.assertEqual(self.status(result.json()['id'])['state'],'completed')
            self.assertEqual(self.counts(),(1,44,2))
        finally:
            # A killed process may leave Event's condition unusable on Windows.
            # Never signal that IPC object after terminating its waiter.
            if worker.is_alive():worker.terminate()
            worker.join(5)
            observer.__exit__(None,None,None)

    def test_real_process_interruption_during_preparation(self):self.crash('preparation')
    def test_real_process_interruption_during_publication_rolls_back_everything(self):self.crash('publication')

    def test_expired_claim_before_execution_reports_early_exit_without_publication(self):
        queued=self.enqueue();ctx=multiprocessing.get_context('spawn')
        claimed,proceed,evaluated=ctx.Event(),ctx.Event(),ctx.Event()
        worker=ctx.Process(target=pre_execution_worker,args=(str(self.root.resolve()),claimed,proceed,evaluated))
        worker.start()
        try:
            self.assertTrue(claimed.wait(10),'Worker did not claim the fictional attempt')
            conn=connect(self.root)
            try:conn.execute('UPDATE processing_attempts SET lease_until=? WHERE id=?',(time.time()-1,queued['id']))
            finally:conn.close()
            proceed.set();worker.join(10)
            self.assertFalse(worker.is_alive());self.assertEqual(worker.exitcode,0)
            self.assertFalse(evaluated.is_set())
            self.assertEqual(self.counts(),(0,0,1))
            diagnostic=worker_stage_diagnostic(self.root,queued['id'],worker)
            self.assertEqual(diagnostic,{'worker_alive':False,'worker_exitcode':0,
                'state':'interrupted','stage':'validating','error_code':'activity_lost',
                'error_type':'AttemptInterrupted','processed_rows':0})
        finally:
            if worker.is_alive():worker.terminate()
            worker.join(5)

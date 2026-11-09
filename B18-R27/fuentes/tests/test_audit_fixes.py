"""R1–R7 regressions: fictional data, unchanged negative controls."""
from contextlib import contextmanager
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import hashlib
import os
import subprocess
import sys
import multiprocessing
import unittest
from unittest.mock import patch
from uuid import uuid4
from zipfile import ZipFile

from app.db import connect
from app.service import Problem
from tests import test_revisions as fixture
from tests import test_authorization_controls as auth
from tests.test_p02 import book


@contextmanager
def authorization_case(count=2):
    x=auth.IntegratedAuthorizationTests();x.setUp()
    try:
        cap=x.add_capture();x.batch=x.import_book(book([('15/08/2026',10,20,30,'A')]*count),'AUDITORIA_FICTICIA.xlsx')
        x.select([cap]);yield x
    finally:x.tearDown()


class ClosureBasisAuditTests(unittest.TestCase):
    def test_capture_bytes_grow_linearly_and_no_global_engine_in_members(self):
        from app.closure import _context,_dump
        sizes=[]
        for count in (8,16,32):
            with authorization_case(count) as x:
                page=x.client.post(x.base()+'/closure-preview',headers=x.headers()).json()
                c=connect(x.root)
                try:
                    _,groups,_,_=_context(c,x.digest,x.dataset['id'],x.batch)
                    members=[m for g in groups.values() for m in g['members']]
                    self.assertFalse(any('authorizations' in m['input_basis'] for m in members))
                    group=page['limitations'][0]
                    r=x.client.post(x.base()+'/closure-limitations',headers=x.headers(),json={
                        'expected_dataset_version':page['dataset_version'],'expected_revision_version':page['revision_version'],
                        'group_key':group['group_key'],'scope_sha256':group['scope_sha256'],'foundation':'FICTICIO fundamento común verificable.'})
                    self.assertEqual(r.status_code,201,r.text)
                    stored=c.execute('SELECT sum(length(evaluation_json)) FROM limitation_controls').fetchone()[0]
                    captured=c.execute('SELECT sum(length(payload_json)) FROM closure_input_captures').fetchone()[0]
                    sizes.append(sum(len(_dump(m).encode()) for m in members)+stored+captured)
                finally:c.close()
        self.assertLess(sizes[1]/sizes[0],2.2);self.assertLess(sizes[2]/sizes[1],2.2)

    def test_rn11_peer_change_preserves_rn10_foundation_but_real_rn10_change_does_not(self):
        with authorization_case() as x:
            for row in (2,3):x.link(x.evidence(row));x.declare(row)
            x.analyze()
            def preview():return x.client.post(x.base()+'/closure-preview',headers=x.headers()).json()
            page=preview();group=next(g for g in page['limitations'] if g['rule_codes']==['RN10'])
            saved=x.client.post(x.base()+'/closure-limitations',headers=x.headers(),json={
                'expected_dataset_version':page['dataset_version'],'expected_revision_version':page['revision_version'],
                'group_key':group['group_key'],'scope_sha256':group['scope_sha256'],'foundation':'FICTICIO incorporación temporal no acreditada.'})
            self.assertEqual(saved.status_code,201,saved.text)
            x.change(3,'G','3');x.analyze()
            same=next(g for g in preview()['limitations'] if g['rule_codes']==['RN10'])
            self.assertEqual(same['scope_sha256'],group['scope_sha256']);self.assertEqual(same['justification']['id'],saved.json()['id'])
            self.assertEqual(x.declare(2,kind='incorporation',value='2026-08-16').status_code,200)
            changed=preview()
            self.assertTrue(any(g['justification'] is None for g in changed['limitations']))
            self.assertNotIn(saved.json()['id'],[g['justification']['id'] for g in changed['limitations'] if g['justification']])


class AuditWorkflowTests(unittest.TestCase):
    setUp=fixture.NewRevisionTests.setUp
    tearDown=fixture.NewRevisionTests.tearDown
    headers=fixture.NewRevisionTests.headers
    import_book=fixture.NewRevisionTests.import_book
    run_url=fixture.NewRevisionTests.run_url
    alerts=fixture.NewRevisionTests.alerts
    decide=fixture.NewRevisionTests.decide
    base=fixture.NewRevisionTests.base
    preview=fixture.NewRevisionTests.preview
    resolve_alerts=fixture.NewRevisionTests.resolve_alerts
    justify=fixture.NewRevisionTests.justify
    close=fixture.NewRevisionTests.close
    history=fixture.NewRevisionTests.history
    freeze=fixture.NewRevisionTests.freeze
    start=fixture.NewRevisionTests.start

    def release(self):
        from scripts.release_snapshot import build_release
        path=self.root/'application.zip';build_release(Path.cwd(),path,synthetic=True);return path

    def test_legacy_open_foundation_requires_explicit_reconfirmation(self):
        p=self.preview();g=p['limitations'][0];c=connect(self.root)
        try:
            actor=c.execute("SELECT id FROM users WHERE username='owner'").fetchone()[0]
            c.execute('INSERT INTO review_limitations VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                ('legacy-foundation',p['revision_id'],g['group_key'],g['scope_sha256'],json.dumps(g['rule_codes']),g['reason_code'],
                 'FICTICIO fundamento anterior conservado.',1,None,actor,'2026-10-27'))
        finally:c.close()
        updated=self.preview();item=next(x for x in updated['limitations'] if x['group_key']==g['group_key'])
        self.assertIsNone(item['justification']);self.assertTrue(item['legacy_reconfirmation_required'])
        r=self.client.post(self.base()+'/closure-limitations',headers=self.headers(),json={
            'expected_dataset_version':updated['dataset_version'],'expected_revision_version':updated['revision_version'],
            'group_key':item['group_key'],'scope_sha256':item['scope_sha256'],'foundation':item['legacy_foundation']})
        self.assertEqual(r.status_code,201,r.text)
        c=connect(self.root)
        try:
            self.assertEqual(c.execute('SELECT previous_id FROM review_limitations WHERE id=?',(r.json()['id'],)).fetchone()[0],'legacy-foundation')
            self.assertIsNone(c.execute("SELECT 1 FROM limitation_formats WHERE limitation_id='legacy-foundation'").fetchone())
        finally:c.close()

    def test_scope_api_persistence_frozen_export_and_closed_summary_agree(self):
        self.resolve_alerts();page=self.justify();g=page['limitations'][0]
        response=self.client.get(self.base()+'/closure-members',params={'group_key':g['group_key'],'scope_sha256':g['scope_sha256'],'limit':2})
        self.assertEqual(response.status_code,200,response.text);scope=response.json()
        self.assertEqual(len(scope['items']),min(2,scope['total']))
        r=self.close(page);self.assertEqual(r.status_code,201,r.text)
        first=self.client.get(self.base()+'/export-closed').content
        with ZipFile(BytesIO(first)) as archive:
            record=next(json.loads(line) for line in archive.read('closure_limitations.jsonl').splitlines() if json.loads(line)['limitation']['group_key']==g['group_key'])
            self.assertEqual(scope['items'],record['members'][:2])
            captures=[json.loads(line) for line in archive.read('closure_input_captures.jsonl').splitlines()]
            self.assertEqual(len(captures),len({x['sha256'] for x in captures}))
        c=connect(self.root)
        try:
            stored=[json.loads(x[0]) for x in c.execute('SELECT evaluation_json FROM limitation_controls WHERE limitation_id=? ORDER BY source_row,rule_code',(g['justification']['id'],))]
            self.assertEqual(stored,record['members'])
            c.execute('UPDATE datasets SET version=version+1 WHERE id=?',(self.dataset['id'],))
        finally:c.close()
        closed=self.preview();self.assertTrue(closed['frozen']);self.assertTrue(closed['limitations'])
        self.assertEqual(self.client.get(self.base()+'/export-closed').content,first)

    def test_failed_publication_is_preserved_classified_and_backup_restores_it(self):
        from app.closure import close
        from scripts.recovery_data import make_backup,bundle_backup,restore_archive,fingerprint
        self.resolve_alerts();p=self.justify()
        def conflict():
            c=connect(self.root);c.execute('UPDATE datasets SET version=version+1 WHERE id=?',(self.dataset['id'],));c.close()
        c=connect(self.root)
        try:
            with self.assertRaises(Problem):close(c,self.root,self.digest,self.dataset['id'],self.batch,p['dataset_version'],p['revision_version'],p['preview_sha256'],[g['justification']['id'] for g in p['limitations']],after_prepare=conflict)
            self.assertEqual(c.execute('SELECT count(*) FROM revision_closures').fetchone()[0],0)
        finally:c.close()
        state=fingerprint(self.root);self.assertTrue(state['unregistered_objects'])
        self.assertEqual(fingerprint(self.root),state)
        backup=self.root/'backups'/'negative';m,sha=make_backup(self.root,backup,self.release(),data_kind='synthetic')
        archive=self.root/'negative.zip';bundle_backup(backup,archive);target=self.root/'restore-negative'
        restore_archive(archive,target,sha,self.root)
        self.assertEqual(fingerprint(target),state)
        for obj in state['unregistered_objects']:self.assertEqual((self.root/obj['relative_path']).read_bytes(),(target/obj['relative_path']).read_bytes())

    def test_two_downloads_log_preparation_not_receipt_and_errors_do_not_log_success(self):
        old,frozen=self.freeze();c=connect(self.root)
        def events():return [dict(r) for r in c.execute("SELECT * FROM audit_events WHERE action='closed_export_response_prepared'")]
        try:
            before=len(events())
            for _ in range(2):self.assertEqual(self.client.get(self.base()+'/export-closed').content,frozen)
            self.assertEqual(len(events()),before+2)
            from fastapi.testclient import TestClient
            from app.api import create_app
            from tests.test_p02 import ORIGIN,PASSWORD
            with TestClient(create_app(self.root,public_origin=ORIGIN,processing_enabled=False),base_url=ORIGIN) as viewer:
                self.assertEqual(viewer.post('/api/session',headers={'Origin':ORIGIN},json={'username':'viewer','password':PASSWORD}).status_code,200)
                self.assertEqual(viewer.get(self.base()+'/export-closed').status_code,403)
                self.assertEqual(viewer.get(self.base()+'/closure-summary').status_code,403)
            self.assertEqual(len(events()),before+2)
            for item in events():
                payload=json.loads(item['entity_id']);self.assertEqual(payload['revision_id'],old['revision_id']);self.assertEqual(payload['archive_sha256'],old['archive_sha256'])
                self.assertIn('not_client_receipt',payload['semantics']);self.assertNotIn('session',payload)
            with patch('app.closure.read_verified',side_effect=OSError('FICTICIO fallo de lectura')):
                from app.closure import download
                with self.assertRaises(OSError):download(c,self.root,self.digest,self.dataset['id'],self.batch)
            self.assertEqual(len(events()),before+2)
            self.assertEqual(self.client.get(self.base()+'/export-closed?revision_id=unknown').status_code,404)
            self.assertEqual(len(events()),before+2)
        finally:c.close()

    def test_public_lists_and_summaries_revalidate_changes_and_revocation(self):
        from app.review import list_alerts
        from app.controls import list_runs,run_summary
        readers=[lambda c,hook:list_alerts(c,self.digest,self.dataset['id'],self.batch,after_read=hook),
                 lambda c,hook:list_runs(c,self.digest,self.dataset['id'],self.batch,after_read=hook),
                 lambda c,hook:run_summary(c,self.digest,self.dataset['id'],self.run['id'],after_read=hook)]
        for read in readers:
            def change():
                other=connect(self.root);other.execute('UPDATE datasets SET version=version+1 WHERE id=?',(self.dataset['id'],));other.close()
            c=connect(self.root)
            try:
                with self.assertRaises(Problem) as e:read(c,change)
                self.assertEqual(e.exception.status,409);self.assertFalse(c.in_transaction)
            finally:c.close()

        for read in readers:
            # Roll back revocation after each independent permission barrier.
            c=connect(self.root);session=dict(c.execute('SELECT * FROM sessions WHERE token_hash=?',(self.digest,)).fetchone())
            def revoke():
                other=connect(self.root);other.execute('DELETE FROM sessions WHERE token_hash=?',(self.digest,));other.close()
            try:
                with self.assertRaises(Problem) as e:read(c,revoke)
                self.assertEqual(e.exception.status,401)
                c.execute('INSERT INTO sessions VALUES('+','.join('?' for _ in session)+')',tuple(session.values()))
            finally:c.close()

    def test_integrated_conflict_two_reviews_backup_and_own_restored_application(self):
        from app.closure import close
        from scripts.recovery_data import make_backup,bundle_backup,restore_archive,fingerprint
        from tests import test_hpc_comparison as values
        from tests.test_p02 import PASSWORD
        selected=[{'id':a['id'],'expected_version':a['version']} for a in self.alerts()['items']]
        first_decision=self.decide(selected,state='confirmada',foundation='FICTICIO primera revisión confirma el indicio de ensayo.',evidence_note='FICTICIO evidencia inventada para probar historia, sin efectos económicos.')
        self.assertEqual(first_decision.status_code,200,first_decision.text);self.dataset['version']=first_decision.json()['dataset_version']
        p=self.justify()
        c=connect(self.root)
        try:
            with patch('app.closure.event',side_effect=RuntimeError('FICTICIO rollback after publication')):
                with self.assertRaises(RuntimeError):close(c,self.root,self.digest,self.dataset['id'],self.batch,p['dataset_version'],p['revision_version'],p['preview_sha256'],[g['justification']['id'] for g in p['limitations']])
            self.assertEqual(c.execute('SELECT count(*) FROM revision_closures').fetchone()[0],0)
        finally:c.close()
        extra=fingerprint(self.root)['unregistered_objects'];self.assertTrue(extra);self.assertEqual(fingerprint(self.root)['unregistered_objects'],extra)
        self.dataset['version']=self.preview()['dataset_version'];source=values.HpcComparisonTests.register_fictional_hpc(self)
        pdf=b'%PDF-1.4\nFICTICIO documento de convenio para recuperacion\n%%EOF\n'
        c=connect(self.root)
        try:
            from app.economic_evidence import register_evidence_pdf
            doc,_=register_evidence_pdf(c,self.root,self.digest,self.dataset['id'],source,self.dataset['version'],
                'CONVENIO_FICTICIO.pdf','agreement','FICTICIO evidencia local de recuperacion.',hashlib.sha256(pdf).hexdigest(),pdf)
            self.dataset['version']=doc['dataset_version']
        finally:c.close()
        p=self.justify();first=self.close(p);self.assertEqual(first.status_code,201,first.text)
        bytes1=self.client.get(self.base()+'/export-closed').content
        opened=self.start();self.assertEqual(opened.status_code,201,opened.text);self.dataset['version']=opened.json()['dataset_version']
        analyzed=self.client.post(self.run_url(),headers=self.headers(),json={'expected_version':self.dataset['version']})
        self.assertEqual(analyzed.status_code,201,analyzed.text);self.dataset['version']=self.preview()['dataset_version']
        selected=[{'id':a['id'],'expected_version':a['version']} for a in self.alerts()['items']]
        decided=self.decide(selected,state='descartada',foundation='FICTICIO segunda revisión con decisión distinta.')
        self.assertEqual(decided.status_code,200,decided.text);self.dataset['version']=decided.json()['dataset_version']
        page=self.preview();changed=self.client.post(self.base()+'/rows/2/work-fields',headers=self.headers(),json={
            'expected_dataset_version':page['dataset_version'],'expected_revision_version':page['revision_version'],
            'field':'G','value':'5','reason':'FICTICIO corrección propia de segunda revisión.'})
        self.assertEqual(changed.status_code,200,changed.text)
        detail=self.client.get(self.base()+'/rows/2/practice-detail')
        self.assertEqual(detail.status_code,200,detail.text);history=detail.json()
        self.assertEqual({d['origin_revision_ordinal'] for d in history['decision_history']},{1,2})
        self.assertTrue(any(d['origin_closure_id'] for d in history['decision_history'] if d['origin_revision_ordinal']==1))
        self.assertEqual(history['interpretation_history'][-1]['origin_revision_ordinal'],2)
        p=self.justify();second=self.close(p);self.assertEqual(second.status_code,201,second.text)
        bytes2=self.client.get(self.base()+'/export-closed').content
        self.assertEqual(self.client.get(self.base()+'/export-closed',params={'revision_id':first.json()['revision_id']}).content,bytes1)
        release=self.release();backup=self.root/'backups'/'complete';m,sha=make_backup(self.root,backup,release,data_kind='synthetic')
        self.assertEqual(m['application']['schema'],27);self.assertTrue(m['logical_state']['unregistered_objects'])
        archive=self.root/'complete.zip';bundle_backup(backup,archive);target=self.root/'restored-complete'
        restore_archive(archive,target,sha,self.root)
        self.assertEqual(fingerprint(target),m['logical_state'])
        instructions=self.root/'probe-input.json';output=self.root/'probe-result.json'
        instructions.write_text(json.dumps({'dataset_id':self.dataset['id'],'batch_id':self.batch,'closures':[
            {'revision_id':first.json()['revision_id'],'sha256':hashlib.sha256(bytes1).hexdigest()},
            {'revision_id':second.json()['revision_id'],'sha256':hashlib.sha256(bytes2).hexdigest()}]}))
        code="import sys;sys.path.insert(0,sys.argv.pop(1));from tests.restored_probe import main;main()"
        env={**os.environ,'TFG_PROBE_PASSWORD':PASSWORD,'TFG_PROBE_OLD_COOKIE':self.client.cookies.get('tfg_session')}
        result=subprocess.run([sys.executable,'-I','-B','-c',code,str((target/'application').resolve()),str(target.resolve()),str(instructions.resolve()),str(output.resolve())],
            cwd=target,env=env,capture_output=True,text=True,timeout=45)
        self.assertEqual(result.returncode,0,result.stderr)
        evidence=json.loads(output.read_text());self.assertTrue(evidence['two_closed_hashes_intact'])
        Path('.test-results/audit-restored-application.json').write_text(json.dumps(evidence,indent=2))

    def test_two_closures_and_backup_preserve_pending_publications_and_retry(self):
        from tests.closure_concurrency import supervise
        from scripts.recovery_data import bundle_backup,restore_archive,fingerprint
        self.resolve_alerts();first=self.batch;self.justify()
        batches=self.client.get(f'/api/datasets/{self.dataset["id"]}/batches').json()
        second=next(b['id'] for b in batches if b['id']!=first)
        self.batch=second;self.justify();pages={}
        for identity in (first,second):self.batch=identity;pages[identity]=self.preview()
        release=self.release()
        outcome=supervise({'root':str(self.root.resolve()),'digest':self.digest,
            'dataset':self.dataset['id'],'pages':pages,'release':str(release.resolve())},
            Path('.test-results')/('closure-concurrency-'+uuid4().hex))
        results=outcome['results'];m=outcome['manifest'];sha=outcome['sha']
        backup=self.root/'backups'/'concurrent'
        self.assertEqual(len(m['logical_state']['unregistered_objects']),2)
        self.assertEqual(m['logical_state']['tables']['revision_closures']['count'],0)
        self.assertEqual(sorted(str(status) for _,status in results),['409','closed'])
        self.batch=next(identity for identity,status in results if status==409)
        p=self.preview();retried=self.close(p);self.assertEqual(retried.status_code,201,retried.text)
        archive=self.root/'concurrent.zip';bundle_backup(backup,archive);target=self.root/'restored-concurrent'
        restore_archive(archive,target,sha,self.root);self.assertEqual(fingerprint(target),m['logical_state'])
        c=connect(self.root)
        try:self.assertEqual(c.execute('SELECT count(*) FROM revision_closures').fetchone()[0],2)
        finally:c.close()

    def test_registered_missing_or_altered_is_not_reclassified_as_an_extra(self):
        from scripts.recovery_data import fingerprint
        c=connect(self.root);row=c.execute('SELECT relative_path FROM stored_files LIMIT 1').fetchone();c.close()
        path=self.root/row['relative_path'];content=path.read_bytes()
        try:
            path.write_bytes(b'FICTICIO altered registered object')
            with self.assertRaisesRegex(RuntimeError,'ausente o alterado'):fingerprint(self.root)
        finally:path.write_bytes(content)
        missing=path.with_name(path.name+'.missing')
        path.rename(missing)
        try:
            with self.assertRaisesRegex(RuntimeError,'ausente o alterado'):fingerprint(self.root)
        finally:missing.rename(path)

    def test_release_schema_metadata_must_match_its_real_code(self):
        from scripts.recovery_data import source_archive,make_backup
        release=self.release();bad=self.root/'incompatible.zip'
        with ZipFile(release) as original,ZipFile(bad,'w') as target:
            for info in original.infolist():
                content=original.read(info.filename)
                if info.filename=='SOURCE_MANIFEST.json':
                    manifest=json.loads(content);manifest['schema_version']=21;content=json.dumps(manifest).encode()
                target.writestr(info,content)
        with self.assertRaisesRegex(RuntimeError,'Esquema declarado'):source_archive(bad)
        with self.assertRaises(RuntimeError):make_backup(self.root,self.root/'backups'/'wrong-schema',bad,data_kind='synthetic')
        from scripts.release_snapshot import build_release
        old=self.root/'actual-old-release.zip';build_release(Path.cwd(),old,commit='76f18c37d9601641c555c6f10dae64b0360c8ad2')
        self.assertEqual(source_archive(old)['schema_version'],21)
        with self.assertRaisesRegex(RuntimeError,'incompatibles'):make_backup(self.root,self.root/'backups'/'actual-incompatible',old,data_kind='synthetic')

    def test_object_gate_excludes_another_process_and_releases_after_crash(self):
        from app.object_gate import object_gate
        from tests.processing_worker import hold_object_gate
        ctx=multiprocessing.get_context('spawn');ready,release=ctx.Event(),ctx.Event()
        worker=ctx.Process(target=hold_object_gate,args=(str(self.root.resolve()),ready,release));worker.start()
        try:
            self.assertTrue(ready.wait(10))
            with self.assertRaises(sqlite3.OperationalError) as error:
                with object_gate(self.root,timeout=0):pass
            self.assertEqual(error.exception.sqlite_errorcode,sqlite3.SQLITE_BUSY)
            worker.terminate();worker.join(5);self.assertFalse(worker.is_alive())
            with object_gate(self.root,timeout=.2):pass
        finally:
            if worker.is_alive():worker.terminate()
            worker.join(5)

    def test_concurrent_reviewer_decision_during_list_read_is_rejected_then_read_coherently(self):
        from app import review
        from app.security import create_user,issue_session,token_digest
        from tests.test_p02 import PASSWORD
        c=connect(self.root)
        actor=create_user(c,'second-reviewer',PASSWORD,'reviewer');c.close()
        p=self.preview();grant=self.client.post(f'/api/datasets/{self.dataset["id"]}/access',headers=self.headers(),json={
            'username':'second-reviewer','role':'reviewer','expected_version':p['dataset_version']})
        self.assertEqual(grant.status_code,200,grant.text)
        c=connect(self.root);token,_=issue_session(c,actor);c.close()
        p=self.preview();alert=self.alerts()['items'][0];original=review._decision_status;changed=False
        def barrier(*args,**kwargs):
            nonlocal changed
            value=original(*args,**kwargs)
            if not changed:
                changed=True;other=connect(self.root)
                try:review.decide_alerts(other,token_digest(token),self.dataset['id'],self.batch,p['dataset_version'],p['revision_version'],
                    [{'id':alert['id'],'expected_version':alert['version']}],'descartada','FICTICIO decisión concurrente de otro revisor.',None)
                finally:other.close()
            return value
        c=connect(self.root)
        try:
            with patch('app.review._decision_status',side_effect=barrier):
                with self.assertRaises(Problem) as error:review.list_alerts(c,self.digest,self.dataset['id'],self.batch)
            self.assertEqual(error.exception.status,409)
            self.assertEqual(c.execute('SELECT actor_id FROM review_decisions ORDER BY created_at DESC LIMIT 1').fetchone()[0],actor)
        finally:c.close()
        response=self.alerts();self.assertEqual({a['decision'] for a in response['items']},{'descartada','pendiente'})


class AuditMigrationTests(unittest.TestCase):
    def test_real_legacy_closed_zip_survives_upgrade_and_active_foundations_require_confirmation(self):
        from scripts.release_snapshot import build_release
        from app.db import migrate,backup_before_upgrade
        from app.api import create_app
        from fastapi.testclient import TestClient
        from tests.temp_support import TemporaryDirectory
        from tests.test_p02 import ORIGIN,PASSWORD
        with TemporaryDirectory(dir='.tmp') as directory:
            root=Path(directory).resolve();release=root/'legacy.zip';oldapp=root/'legacy-code';oldapp.mkdir()
            build_release(Path.cwd(),release,commit='76f18c37d9601641c555c6f10dae64b0360c8ad2')
            with ZipFile(release) as archive:archive.extractall(oldapp)
            active=root/'legacy-active';closed=root/'legacy-closed';meta=root/'legacy-meta.json'
            code='''import json,shutil,sqlite3,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from tests.test_revisions import NewRevisionTests
from app import db
assert Path(db.__file__).resolve().is_relative_to(Path(sys.argv[1]))
x=NewRevisionTests();x.setUp()
def copy(dest):
 dest=Path(dest);dest.mkdir();src=sqlite3.connect(x.root/'app.sqlite3');out=sqlite3.connect(dest/'app.sqlite3');src.backup(out);src.close();out.close();shutil.copytree(x.root/'objects',dest/'objects')
try:
 x.resolve_alerts();page=x.justify();copy(sys.argv[2]);r=x.close(page);assert r.status_code==201,r.text;copy(sys.argv[3]);Path(sys.argv[4]).write_text(json.dumps({'dataset_id':x.dataset['id'],'batch_id':x.batch,**r.json()}))
finally:x.tearDown()
'''
            result=subprocess.run([sys.executable,'-I','-B','-c',code,str(oldapp),str(active),str(closed),str(meta)],cwd=root,capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr);info=json.loads(meta.read_text())
            for target in (active,closed):
                c=connect(target)
                try:backup_before_upgrade(c,target);migrate(c,allow_existing_upgrade=True)
                finally:c.close()
                with TestClient(create_app(target,public_origin=ORIGIN,processing_enabled=False),base_url=ORIGIN) as client:
                    login=client.post('/api/session',headers={'Origin':ORIGIN},json={'username':'owner','password':PASSWORD})
                    headers={'Origin':ORIGIN,'X-CSRF-Token':login.json()['csrf_token']}
                    base=f'/api/datasets/{info["dataset_id"]}/batches/{info["batch_id"]}'
                    page=client.post(base+'/closure-preview',headers=headers).json()
                    if target==active:
                        self.assertTrue(all(g['legacy_reconfirmation_required'] and g['justification'] is None for g in page['limitations']))
                    else:
                        frozen=client.get(base+'/export-closed');self.assertEqual(frozen.status_code,200)
                        self.assertEqual(hashlib.sha256(frozen.content).hexdigest(),info['archive_sha256'])
                        self.assertEqual(page['basis_format'],'legacy-v1');self.assertTrue(page['frozen'])

    def test_v21_additive_migration_keeps_legacy_history_and_rolls_back_failure(self):
        from app.db import MIGRATIONS,migrate,backup_before_upgrade
        from app.security import create_user
        from tests.temp_support import TemporaryDirectory
        from tests.test_p02 import PASSWORD
        with TemporaryDirectory(dir='.tmp') as directory:
            root=Path(directory);c=connect(root)
            try:
                old=tuple(m for m in MIGRATIONS if m[0]<=21);migrate(c,migrations=old)
                actor=create_user(c,'migration-audit',PASSWORD,'admin');backup=backup_before_upgrade(c,root)
                broken=old+((22,dict(MIGRATIONS)[22]+('INVALID SQL',)),)
                with self.assertRaises(sqlite3.OperationalError):migrate(c,migrations=broken,allow_existing_upgrade=True)
                self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0],21)
                self.assertIsNone(c.execute("SELECT 1 FROM sqlite_master WHERE name='closure_input_captures'").fetchone())
                self.assertEqual(migrate(c,migrations=old+((22,dict(MIGRATIONS)[22]),),allow_existing_upgrade=True),22)
                self.assertEqual(c.execute('SELECT id FROM users').fetchone()[0],actor)
                self.assertIsNone(c.execute('PRAGMA foreign_key_check').fetchone())
                self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok')
                saved=sqlite3.connect(backup/'app.sqlite3')
                try:self.assertEqual(saved.execute('PRAGMA user_version').fetchone()[0],21)
                finally:saved.close()
            finally:c.close()

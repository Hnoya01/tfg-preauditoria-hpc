"""RN26: fictional correspondence, isolation, races and frozen exports."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch
from uuid import uuid4
from zipfile import ZipFile

from fastapi.testclient import TestClient
from app.api import create_app
from app.db import connect, migrate, MIGRATIONS, backup_before_upgrade
from app.medical_consultations import save, history
from app.security import now_utc
from app.service import Problem
from tests.test_p02 import ORIGIN, PASSWORD, book
from tests import test_revisions as fixture
from tests.temp_support import TemporaryDirectory


class MedicalConsultationTests(unittest.TestCase):
    for name in ('setUp','tearDown','headers','import_book','run_url','alerts','decide','base',
                 'preview','resolve_alerts','justify','close','freeze','start','history'):
        locals()[name] = getattr(fixture.NewRevisionTests, name)
    del name

    def url(self, row=2): return self.base()+f'/rows/{row}/consultations'

    def page(self):
        r=self.client.get(self.url());self.assertEqual(r.status_code,200,r.text);return r.json()

    def body(self, **extra):
        p=self.page()
        return dict(expected_dataset_version=p['dataset_version'],expected_revision_version=p['revision_version'],
                    revision_id=p['revision_id'],request_id=str(uuid4()),**extra)

    def ask(self):
        b=self.body(question='FICTICIO: aclarar el respaldo documental de esta práctica.')
        r=self.client.post(self.url(),headers=self.headers(),json=b)
        self.assertEqual(r.status_code,201,r.text);self.dataset['version']=r.json()['dataset_version']
        return r.json()['id'],b

    def answer_body(self):
        return self.body(author_name='Dra. Emisora Ficticia',responded_at=now_utc(),channel='email',
                         provenance='FICTICIO: correo de ensayo identificado como respuesta 01.',
                         response='FICTICIO: aclaración externa que requiere revisión humana.')

    def answer(self, identity, body=None):
        return self.client.post(self.url()+f'/{identity}/responses',headers=self.headers(),json=body or self.answer_body())

    def test_external_author_registrar_history_and_no_automatic_effect(self):
        c=connect(self.root)
        tables=('alerts','review_decisions','control_runs','invoice_rows','authorization_link_versions','proposal_versions')
        try: before={t:[tuple(r) for r in c.execute(f'SELECT * FROM {t}')] for t in tables}
        finally:c.close()
        identity,_=self.ask()
        for _ in range(2):
            r=self.answer(identity);self.assertEqual(r.status_code,201,r.text)
        p=self.page();item=p['items'][0]
        self.assertEqual(item['status'],'response_recorded');self.assertEqual(len(item['responses']),2)
        self.assertEqual(item['responses'][0]['author_name'],'Dra. Emisora Ficticia')
        self.assertEqual(item['responses'][0]['registrar_username'],'owner')
        self.assertIn('original_fields',item['context'])
        c=connect(self.root)
        try:
            for t in tables:self.assertEqual(before[t],[tuple(r) for r in c.execute(f'SELECT * FROM {t}')],t)
            self.assertEqual(c.execute("SELECT count(*) FROM audit_events WHERE action IN ('medical_consultation_recorded','external_response_recorded')").fetchone()[0],3)
        finally:c.close()

    def test_lost_response_retry_and_reused_key_different_body(self):
        identity,body=self.ask()
        replay=self.client.post(self.url(),headers=self.headers(),json=body)
        self.assertEqual(replay.status_code,201,replay.text);self.assertEqual(replay.json()['id'],identity)
        self.assertTrue(replay.json()['replayed'])
        bad=self.client.post(self.url(),headers=self.headers(),json={**body,'question':'FICTICIO otra consulta diferente.'})
        self.assertEqual(bad.status_code,409)
        answer=self.answer_body();first=self.answer(identity,answer);second=self.answer(identity,answer)
        self.assertEqual(first.json()['id'],second.json()['id']);self.assertTrue(second.json()['replayed'])
        self.assertEqual(len(self.page()['items'][0]['responses']),1)

    def test_new_consultation_scope_only_inpatient_without_side_effects(self):
        for kind,day,allowed in [('I','15/08/2026',False),(' i ','15/07/2026',False),
                                  ('A','15/08/2026',True),('C','15/08/2026',True),
                                  ('A','15/07/2026',True),('X','15/08/2026',True)]:
            with self.subTest(kind=kind,day=day):
                self.dataset['version']=self.page()['dataset_version']
                self.batch=self.import_book(book([(day,10,20,30,kind)]),'FICTICIO alcance.xlsx')
                page=self.page();self.assertEqual(page['can_create_consultation'],allowed)
                body=self.body(question='FICTICIO consulta sobre alcance explícito.')
                c=connect(self.root)
                try:
                    before={t:[tuple(r) for r in c.execute(f'SELECT * FROM {t} ORDER BY rowid')] for t in
                            ('medical_consultations','audit_events','datasets','revisions')}
                    response=self.client.post(self.url(),headers=self.headers(),json=body)
                    self.assertEqual(response.status_code,201 if allowed else 422,response.text)
                    if not allowed:
                        self.assertEqual(page['creation_block_reason'],'internacion_fuera_de_alcance')
                        for t,rows in before.items():self.assertEqual(rows,[tuple(r) for r in c.execute(f'SELECT * FROM {t} ORDER BY rowid')])
                finally:c.close()

    def test_historical_reception_keeps_registration_export_close_and_replay(self):
        identity,_=self.ask();body=self.answer_body();body['responded_at']='2020-01-01T10:30:01-03:00'
        answer=self.answer(identity,body);self.assertEqual(answer.status_code,201,answer.text)
        item=self.page()['items'][0];record=item['responses'][0]
        self.assertEqual(record['responded_at'],'2020-01-01T13:30:01+00:00')
        self.assertLess(record['responded_at'],item['created_at']);self.assertGreaterEqual(record['created_at'],item['created_at'])
        export=self.client.get(self.base()+'/export-provisional')
        with ZipFile(BytesIO(export.content)) as z:
            exported=json.loads(z.read('medical_consultations.jsonl').decode().splitlines()[0])
        self.assertEqual(exported['responses'][0],record)
        self.dataset['version']=self.page()['dataset_version'];closed,frozen=self.freeze()
        with ZipFile(BytesIO(frozen)) as z:
            self.assertEqual(json.loads(z.read('medical_consultations.jsonl').decode().splitlines()[0])['responses'][0],record)
        version=self.page()['dataset_version'];replay=self.answer(identity,body)
        self.assertEqual(replay.status_code,201,replay.text);self.assertTrue(replay.json()['replayed'])
        self.assertEqual(replay.json()['id'],answer.json()['id']);self.assertEqual(self.page()['dataset_version'],version)
        self.assertEqual(self.answer(identity,{**body,'request_id':str(uuid4())}).status_code,409)
        self.assertEqual(self.client.get(self.base()+'/export-closed').content,frozen)

    def test_v25_to_v26_rollback_history_inpatient_replay_and_old_closure(self):
        old=MedicalConsultationTests()
        with patch('tests.test_p05.migrate',side_effect=lambda c:migrate(c,MIGRATIONS[:25])), patch('app.api.migrate',side_effect=lambda c:migrate(c,MIGRATIONS[:25])):
            old.setUp()
        try:
            first,_=old.ask();self.assertEqual(old.answer(first).status_code,201)
            old.dataset['version']=old.page()['dataset_version'];closed,frozen=old.freeze();closed_batch=old.batch
            old.dataset['version']=old.page()['dataset_version']
            old.batch=old.import_book(book([('15/08/2026',10,20,30,'I')]),'FICTICIO internacion anterior.xlsx')
            # Seed correspondence under the explicitly previous creation policy.
            with patch('app.medical_consultations._inpatient',return_value=False):identity,request=old.ask()
            c=connect(old.root)
            try:
                tables=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
                before={t:[tuple(r) for r in c.execute(f'SELECT * FROM "{t}" ORDER BY rowid')] for t in tables}
                trigger=c.execute("SELECT sql FROM sqlite_master WHERE name='medical_response_open'").fetchone()[0]
                with self.assertRaises(RuntimeError):migrate(c)
                backup=backup_before_upgrade(c,old.root)
                with self.assertRaises(sqlite3.Error):
                    migrate(c,migrations=MIGRATIONS[:25]+((26,dict(MIGRATIONS)[26]+('INVALID SQL',)),),allow_existing_upgrade=True)
                self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0],25)
                self.assertEqual(c.execute("SELECT sql FROM sqlite_master WHERE name='medical_response_open'").fetchone()[0],trigger)
                self.assertEqual(migrate(c,MIGRATIONS[:26],allow_existing_upgrade=True),26)
                for t,rows in before.items():self.assertEqual(rows,[tuple(r) for r in c.execute(f'SELECT * FROM "{t}" ORDER BY rowid')],t)
                self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok');self.assertIsNone(c.execute('PRAGMA foreign_key_check').fetchone())
                prior=sqlite3.connect(backup/'app.sqlite3')
                try:
                    self.assertEqual(prior.execute('PRAGMA user_version').fetchone()[0],25)
                    self.assertEqual(prior.execute("SELECT sql FROM sqlite_master WHERE name='medical_response_open'").fetchone()[0],trigger)
                    for t,rows in before.items():self.assertEqual(rows,prior.execute(f'SELECT * FROM "{t}" ORDER BY rowid').fetchall(),t)
                finally:prior.close()
            finally:c.close()
            page=old.page();self.assertFalse(page['can_create_consultation']);self.assertEqual(page['items'][0]['id'],identity)
            replay=old.client.post(old.url(),headers=old.headers(),json=request)
            self.assertEqual(replay.status_code,201,replay.text);self.assertTrue(replay.json()['replayed'])
            self.assertEqual(replay.json()['id'],identity);self.assertEqual(old.page()['dataset_version'],page['dataset_version'])
            self.assertEqual(old.client.post(old.url(),headers=old.headers(),json={**request,'question':'FICTICIO otro contenido.'}).status_code,409)
            self.assertEqual(old.client.post(old.url(),headers=old.headers(),json=old.body(question='FICTICIO consulta nueva prohibida.')).status_code,422)
            body=old.answer_body();body['responded_at']='2020-01-01T00:00:00+00:00'
            saved=old.answer(identity,body);self.assertEqual(saved.status_code,201,saved.text)
            c=connect(old.root)
            try:
                record=dict(c.execute('SELECT * FROM medical_responses WHERE id=?',(saved.json()['id'],)).fetchone())
                record.update(id=str(uuid4()),request_id=str(uuid4()),responded_at='2999-01-01T00:00:00+00:00')
                with self.assertRaises(sqlite3.IntegrityError):c.execute('INSERT INTO medical_responses VALUES('+','.join('?'*len(record))+')',tuple(record.values()))
                with self.assertRaises(sqlite3.IntegrityError):c.execute("UPDATE medical_responses SET responded_at='changed'")
            finally:c.close()
            old.batch=closed_batch;self.assertEqual(old.client.get(old.base()+'/export-closed').content,frozen)
        finally:old.tearDown()

    def test_invalid_content_dates_and_extra_fields(self):
        identity,_=self.ask();valid=self.answer_body()
        for changes in ({'author_name':'  '},{'response':' '*20},{'provenance':' '*10},{'channel':'fax'},
                        {'responded_at':'2999-01-01T00:00:00Z'},
                        {'responded_at':'2026-10-30T12:00:00'},{'responded_at':'invalid'}, {'response':'x'*4001}, {'amount_ars':'1.00'}):
            with self.subTest(changes=changes):self.assertEqual(self.answer(identity,{**valid,**changes}).status_code,422)
        self.assertEqual(self.page()['items'][0]['responses'],[])
        r=self.client.post(self.url(),headers=self.headers(),json=self.body(question=' '*20))
        self.assertEqual(r.status_code,422)

    def test_wrong_row_revision_and_dataset_never_link(self):
        identity,_=self.ask();body=self.answer_body()
        self.assertEqual(self.client.post(self.url(3)+f'/{identity}/responses',headers=self.headers(),json=body).status_code,404)
        self.assertEqual(self.client.post(self.url(999),headers=self.headers(),json=self.body(question='FICTICIO fila ausente.')).status_code,404)
        self.assertEqual(self.answer(identity,{**body,'revision_id':'other'}).status_code,409)
        other=self.client.post('/api/datasets',headers=self.headers(),json={'label':'FICTICIO otro conjunto'}).json()
        target=self.url().replace(self.dataset['id'],other['id'])
        self.assertEqual(self.client.get(target).status_code,404)
        self.assertEqual(self.client.post(target,headers=self.headers(),json=self.body(question='FICTICIO otro conjunto.')).status_code,404)

    def test_csrf_viewer_revoked_permissions_and_replay(self):
        identity,body=self.ask()
        self.assertEqual(self.client.post(self.url(),json=body).status_code,403)
        c=connect(self.root)
        try:
            c.execute("UPDATE users SET role='reviewer' WHERE username='owner'")
            user=c.execute("SELECT id FROM users WHERE username='owner'").fetchone()[0]
            c.execute('INSERT OR REPLACE INTO dataset_access VALUES(?,?,?)',(self.dataset['id'],user,'viewer'))
            self.assertEqual(self.client.get(self.url()).status_code,403)
            self.assertEqual(self.client.post(self.url(),headers=self.headers(),json=body).status_code,403)
            c.execute("UPDATE dataset_access SET role='reviewer' WHERE user_id=?",(user,))
            self.assertEqual(self.client.get(self.url()).status_code,200)
            self.assertEqual(self.answer(identity).status_code,201)
            c.execute('DELETE FROM dataset_access WHERE user_id=?',(user,))
            self.assertEqual(self.client.get(self.url()).status_code,403)
            self.assertEqual(self.client.post(self.url(),headers=self.headers(),json=body).status_code,403)
        finally:c.close()

    def test_concurrent_writers_one_wins_no_partial_events(self):
        b=self.body(question='FICTICIO consulta concurrente de prueba.');barrier=Barrier(2)
        def writer(key):
            c=connect(self.root)
            try:
                barrier.wait()
                try:return save(c,self.digest,self.dataset['id'],self.batch,2,**{**b,'request_id':key})
                except Problem as e:return e.status
            finally:c.close()
        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(writer,[str(uuid4()),str(uuid4())]))
        self.assertEqual(sum(isinstance(r,dict) for r in results),1);self.assertIn(409,results)
        self.assertEqual(len(self.page()['items']),1)

    def test_concurrent_identical_retries_only_one_record(self):
        b=self.body(question='FICTICIO consulta con entrega repetida.');barrier=Barrier(2)
        def writer(_):
            c=connect(self.root)
            try:barrier.wait();return save(c,self.digest,self.dataset['id'],self.batch,2,**b)
            finally:c.close()
        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(writer,range(2)))
        self.assertEqual(results[0]['id'],results[1]['id']);self.assertEqual(sum(r['replayed'] for r in results),1)

    def test_audit_failure_rolls_back_and_retry_completes(self):
        body=self.body(question='FICTICIO consulta interrumpida antes del commit.');before=self.page();c=connect(self.root)
        try:
            with patch('app.medical_consultations.event',side_effect=RuntimeError('synthetic interruption')):
                with self.assertRaises(RuntimeError):save(c,self.digest,self.dataset['id'],self.batch,2,**body)
            self.assertFalse(c.in_transaction);self.assertEqual(self.page(),before)
            result=save(c,self.digest,self.dataset['id'],self.batch,2,**body);self.assertFalse(result['replayed'])
        finally:c.close()

    def test_response_failure_is_atomic(self):
        identity,_=self.ask();body=self.answer_body();before=self.page();c=connect(self.root)
        try:
            with patch('app.medical_consultations.event',side_effect=RuntimeError('synthetic interruption')):
                with self.assertRaises(RuntimeError):save(c,self.digest,self.dataset['id'],self.batch,2,consultation_id=identity,**body)
            self.assertEqual(self.page(),before)
            save(c,self.digest,self.dataset['id'],self.batch,2,consultation_id=identity,**body)
            self.assertEqual(len(self.page()['items'][0]['responses']),1)
        finally:c.close()

    def test_consistent_read_rechecks_versions_and_revocation(self):
        self.ask();c=connect(self.root)
        def change():
            other=connect(self.root)
            try:other.execute('UPDATE datasets SET version=version+1 WHERE id=?',(self.dataset['id'],))
            finally:other.close()
        def revoke():
            other=connect(self.root)
            try:other.execute('DELETE FROM sessions WHERE token_hash=?',(self.digest,))
            finally:other.close()
        try:
            for callback,status in ((change,409),(revoke,401)):
                with self.assertRaises(Problem) as e:history(c,self.digest,self.dataset['id'],self.batch,2,after_read=callback)
                self.assertEqual(e.exception.status,status);self.assertFalse(c.in_transaction)
        finally:c.close()

    def test_export_close_pending_and_successor_preserve_frozen_bytes(self):
        identity,_=self.ask();self.assertEqual(self.answer(identity).status_code,201)
        self.dataset['version']=self.page()['dataset_version'];pending,_=self.ask()
        provisional=self.client.get(self.base()+'/export-provisional');self.assertEqual(provisional.status_code,200,provisional.text[:100])
        with ZipFile(BytesIO(provisional.content)) as z:
            records=z.read('medical_consultations.jsonl');manifest=json.loads(z.read('manifest.json'))
            self.assertEqual(manifest['medical_consultations']['awaiting_response'],1)
            self.assertEqual(len(manifest['medical_consultations']['response_ids']),1)
        closed,frozen=self.freeze()
        with ZipFile(BytesIO(frozen)) as z:self.assertEqual(z.read('medical_consultations.jsonl'),records)
        self.assertEqual(self.preview()['medical_consultations']['awaiting_response'],1)
        self.assertEqual(self.answer(pending).status_code,409)
        new=self.start();self.assertEqual(new.status_code,201,new.text)
        self.assertEqual(self.answer(pending).status_code,404)
        new_id,_=self.ask();self.assertEqual(self.answer(new_id).status_code,201)
        items=self.page()['items'];self.assertEqual(len(items),3)
        self.assertEqual(items[0]['revision_id'],closed['revision_id'])
        self.assertEqual(self.client.get(self.base()+'/export-closed?revision_id='+closed['revision_id']).content,frozen)

    def test_new_correspondence_invalidates_closure_preview_not_control_results(self):
        self.resolve_alerts();page=self.justify();self.ask()
        self.assertEqual(self.close(page).status_code,409)
        fresh=self.preview();self.assertTrue(fresh['can_close']);self.assertNotEqual(page['preview_sha256'],fresh['preview_sha256'])
        self.assertEqual(self.close(fresh).status_code,201)

    def test_database_history_cannot_be_edited_deleted_or_appended_after_close(self):
        identity,_=self.ask();r=self.answer(identity);self.assertEqual(r.status_code,201,r.text)
        self.dataset['version']=self.page()['dataset_version'];self.freeze();c=connect(self.root)
        try:
            for table in ('medical_consultations','medical_responses'):
                for operation in (f"UPDATE {table} SET created_at='changed'",f'DELETE FROM {table}'):
                    with self.assertRaises(sqlite3.IntegrityError):c.execute(operation)
                row=dict(c.execute(f'SELECT * FROM {table} LIMIT 1').fetchone());row.update(id=str(uuid4()),request_id=str(uuid4()))
                with self.assertRaises(sqlite3.IntegrityError):c.execute(f'INSERT INTO {table} VALUES('+','.join('?'*len(row))+')',tuple(row.values()))
            self.assertIsNone(c.execute('PRAGMA foreign_key_check').fetchone())
        finally:c.close()

    def test_v24_upgrade_requires_backup_preserves_closure_and_rollback(self):
        # Build a true v24 database with the old code path; no operational sources.
        with TemporaryDirectory(dir='.tmp') as temp:
            root=Path(temp);c=connect(root)
            try:
                migrate(c,MIGRATIONS[:24]);c.execute("INSERT INTO users(id,username,password_hash,role,active,created_at) VALUES('old','old','unused','admin',1,?)",(now_utc(),))
                before=c.execute('SELECT * FROM users').fetchall()
                with self.assertRaises(RuntimeError):migrate(c)
                backup=backup_before_upgrade(c,root)
                with self.assertRaises(sqlite3.Error):
                    migrate(c,migrations=MIGRATIONS[:24]+((25,dict(MIGRATIONS)[25]+('INVALID SQL',)),),allow_existing_upgrade=True)
                self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0],24)
                self.assertIsNone(c.execute("SELECT name FROM sqlite_master WHERE name='medical_consultations'").fetchone())
                self.assertEqual(migrate(c,migrations=MIGRATIONS[:25],allow_existing_upgrade=True),25)
                self.assertEqual(c.execute('SELECT * FROM users').fetchall(),before)
                self.assertEqual(c.execute('SELECT count(*) FROM medical_consultations').fetchone()[0],0)
                self.assertIsNone(c.execute('PRAGMA foreign_key_check').fetchone());self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok')
                old=sqlite3.connect(backup/'app.sqlite3')
                try:self.assertEqual(old.execute('PRAGMA user_version').fetchone()[0],24);self.assertEqual(old.execute('SELECT id FROM users').fetchone()[0],'old')
                finally:old.close()
            finally:c.close()

    def test_upgrade_keeps_preexisting_v24_closed_archive_exact(self):
        old=fixture.NewRevisionTests()
        with patch('tests.test_p05.migrate',side_effect=lambda c:migrate(c,MIGRATIONS[:24])), patch('app.api.migrate',side_effect=lambda c:migrate(c,MIGRATIONS[:24])):
            old.setUp()
        try:
            closed,frozen=old.freeze()
            with ZipFile(BytesIO(frozen)) as z:self.assertNotIn('medical_consultations.jsonl',z.namelist())
            old.client.__exit__(None,None,None)
            c=connect(old.root)
            try:
                backup=backup_before_upgrade(c,old.root)
                migrate(c,allow_existing_upgrade=True)
            finally:c.close()
            old.client=TestClient(create_app(old.root,public_origin=ORIGIN),base_url=ORIGIN)
            old.client.__enter__()
            login=old.client.post('/api/session',headers={'Origin':ORIGIN},json={'username':'owner','password':PASSWORD})
            old.csrf=login.json()['csrf_token']
            self.assertEqual(old.client.get(old.base()+'/export-closed').content,frozen)
            self.assertIsNone(old.preview()['medical_consultations'])
            c=sqlite3.connect(backup/'app.sqlite3')
            try:self.assertEqual(c.execute('SELECT archive_sha256 FROM revision_closures').fetchone()[0],closed['archive_sha256'])
            finally:c.close()
        finally:old.tearDown()

    def test_backup_restore_preserves_correspondence_and_closed_archive(self):
        from scripts.release_snapshot import build_release
        from scripts.recovery_data import make_backup,bundle_backup,restore_archive,fingerprint
        from app.storage import read_verified
        identity,_=self.ask();body=self.answer_body();body['responded_at']='2020-01-01T00:00:00+00:00'
        self.assertEqual(self.answer(identity,body).status_code,201)
        self.dataset['version']=self.page()['dataset_version'];closed,frozen=self.freeze()
        release=self.root/'consultation-source.zip';build_release(Path.cwd(),release,synthetic=True)
        backup=self.root/'backups'/'consultations';manifest,digest=make_backup(self.root,backup,release,data_kind='synthetic')
        for table in ('medical_consultations','medical_responses'):
            self.assertEqual(manifest['logical_state']['tables'][table]['count'],1)
        bundle=self.root/'consultations-backup.zip';bundle_backup(backup,bundle)
        restored=self.root/'restored';restore_archive(bundle,restored,digest,self.root)
        self.assertEqual(fingerprint(restored),manifest['logical_state'])
        self.assertEqual(read_verified(restored,closed['archive_sha256']),frozen)

    def test_exact_replay_after_closed_revision_has_no_second_event_or_version(self):
        identity,question=self.ask();body=self.answer_body();answer=self.answer(identity,body)
        self.assertEqual(answer.status_code,201,answer.text)
        self.dataset['version']=self.page()['dataset_version'];closed,frozen=self.freeze()
        c=connect(self.root)
        try:
            before={t:[tuple(r) for r in c.execute(f'SELECT * FROM {t} ORDER BY 1')] for t in
                    ('medical_responses','medical_consultations','audit_events','datasets','revisions')}
            replay=self.answer(identity,body);self.assertEqual(replay.status_code,201,replay.text)
            self.assertTrue(replay.json()['replayed']);self.assertEqual(replay.json()['id'],answer.json()['id'])
            for table,rows in before.items():self.assertEqual(rows,[tuple(r) for r in c.execute(f'SELECT * FROM {table} ORDER BY 1')])
            self.assertEqual(self.client.get(self.base()+'/export-closed').content,frozen)
        finally:c.close()

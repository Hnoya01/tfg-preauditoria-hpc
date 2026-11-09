"""C1 closes only justified reviews and downloads their immutable capture."""
from io import BytesIO
import json
import sqlite3
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from app.db import connect
from tests import test_p06 as fixture


class ClosureTests(unittest.TestCase):
    setUp = fixture.P06Tests.setUp
    tearDown = fixture.P06Tests.tearDown
    headers = fixture.P06Tests.headers
    import_book = fixture.P06Tests.import_book
    run_url = fixture.P06Tests.run_url
    alerts = fixture.P06Tests.alerts
    decide = fixture.P06Tests.decide

    def base(self):
        return f'/api/datasets/{self.dataset["id"]}/batches/{self.batch}'

    def preview(self):
        r = self.client.post(self.base() + '/closure-preview', headers=self.headers())
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def resolve_alerts(self):
        selected = [{'id': a['id'], 'expected_version': a['version']} for a in self.alerts()['items']]
        r = self.decide(selected, state='no_concluyente', foundation='FICTICIO: no existe evidencia suficiente para concluir.')
        self.assertEqual(r.status_code, 200, r.text)
        self.dataset['version'] = r.json()['dataset_version']

    def justify(self):
        page = self.preview()
        for group in page['limitations']:
            if group['justification']:
                continue
            r = self.client.post(self.base() + '/closure-limitations', headers=self.headers(), json={
                'expected_dataset_version': page['dataset_version'], 'expected_revision_version': page['revision_version'],
                'group_key': group['group_key'], 'scope_sha256': group['scope_sha256'],
                'foundation': 'FICTICIO: fuente o control sin verificar; se conserva la limitación, sin aprobación.'})
            self.assertEqual(r.status_code, 201, r.text)
            page = self.preview()
        return page

    def close(self, page):
        return self.client.post(self.base() + '/closure', headers=self.headers(), json={
            'expected_dataset_version': page['dataset_version'], 'expected_revision_version': page['revision_version'],
            'preview_sha256': page['preview_sha256'],
            'confirmed_limitation_ids': [g['justification']['id'] for g in page['limitations'] if g['justification']]})

    def test_pending_alerts_and_unjustified_controls_block_close(self):
        page = self.preview()
        self.assertGreater(page['pending_alert_count'], 0)
        self.assertFalse(page['can_close'])
        self.assertEqual(self.close(page).status_code, 409)
        self.resolve_alerts()
        page = self.preview()
        self.assertEqual(page['pending_alert_count'], 0)
        self.assertFalse(page['can_close'])
        self.assertTrue(any(g['reason_code'] == 'control_not_implemented' for g in page['limitations']))
        self.assertEqual(self.close(page).status_code, 409)

    def test_frozen_export_survives_source_changes_and_blocks_writes(self):
        self.resolve_alerts()
        page = self.justify()
        self.assertTrue(page['can_close'])
        r = self.close(page)
        self.assertEqual(r.status_code, 201, r.text)
        first = self.client.get(self.base() + '/export-closed')
        self.assertEqual(first.status_code, 200, first.text[:80])
        c = connect(self.root)
        try:
            c.execute('UPDATE datasets SET version=version+1 WHERE id=?', (self.dataset['id'],))
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute("UPDATE revision_closures SET manifest_json='{}'")
        finally:
            c.close()
        # Register a real domain source made only of fictional catalog rows.
        # Closed export must keep its old sources/results, not recompute them.
        c = connect(self.root)
        self.dataset['version'] = c.execute('SELECT version FROM datasets WHERE id=?', (self.dataset['id'],)).fetchone()[0]
        c.close()
        from tests import test_hpc_comparison as values_fixture
        values_fixture.HpcComparisonTests.register_fictional_hpc(self)
        closed = self.preview()
        changed = self.client.post(self.base()+'/rows/2/work-fields', headers=self.headers(), json={
            'expected_dataset_version': closed['dataset_version'], 'expected_revision_version': closed['revision_version'],
            'field': 'G', 'value': '4', 'reason': 'FICTICIO intento sobre revisión cerrada.'})
        self.assertEqual(changed.status_code, 409)
        second = self.client.get(self.base() + '/export-closed')
        self.assertEqual(first.content, second.content)
        self.assertEqual(first.headers['x-content-sha256'], second.headers['x-content-sha256'])
        with ZipFile(BytesIO(first.content)) as z:
            m = json.loads(z.read('manifest.json'))
            self.assertEqual(m['kind'], 'closed_review_export')
            self.assertEqual(m['batch']['state'], 'cerrada')
            self.assertTrue(m['closure']['limitations'])
            controls = [json.loads(line) for line in z.read('closure_controls.jsonl').splitlines()]
            self.assertTrue(any(e['result'] == 'no_evaluado' and e['rule_code'] == 'RN20' for e in controls))
        self.assertEqual(self.client.post(self.run_url(), headers=self.headers(), json={'expected_version': page['dataset_version']+2}).status_code, 409)
        self.assertEqual(self.client.get(self.base()+'/export-provisional').status_code, 409)

    def test_controls_without_any_analysis_require_explicit_limitations(self):
        from tests.test_p02 import book
        self.batch = self.import_book(book([('20/08/2026',10,20,30)]), 'SIN_ANALISIS_FICTICIO.xlsx')
        page = self.preview()
        self.assertIsNone(page['latest_run_id'])
        self.assertFalse(page['can_close'])
        self.assertTrue(any(g['reason_code']=='control_not_recorded' for g in page['limitations']))
        self.assertEqual(len(page['limitations']), 2)  # One cause, many controls, one justification.
        documents=next(g for g in page['limitations'] if g['reason_code']=='control_not_implemented')
        self.assertEqual(documents['rule_codes'], ['RN20','RN21','RN22'])
        page = self.justify()
        self.assertTrue(page['can_close'])
        self.assertEqual(self.close(page).status_code,201)
        frozen = self.client.get(self.base()+'/export-closed')
        self.assertEqual(frozen.status_code,200)
        with ZipFile(BytesIO(frozen.content)) as z:
            m=json.loads(z.read('manifest.json'))
            self.assertIsNone(m['control_run']['id'])
            self.assertEqual(m['control_run']['technical_state'],'not_executed')
            self.assertEqual(z.read('control_results.jsonl'), b'')
            self.assertIsNone(m['current_proposal_total_ars'])

    def test_prepare_conflict_leaves_no_partial_closure(self):
        from app.closure import close
        from app.service import Problem
        self.resolve_alerts()
        page=self.justify()
        def concurrent_change():
            other=connect(self.root)
            other.execute('UPDATE datasets SET version=version+1 WHERE id=?',(self.dataset['id'],))
            other.close()
        c=connect(self.root)
        try:
            with self.assertRaises(Problem) as error:
                close(c,self.root,self.digest,self.dataset['id'],self.batch,page['dataset_version'],page['revision_version'],page['preview_sha256'],
                      [g['justification']['id'] for g in page['limitations']],after_prepare=concurrent_change)
            self.assertEqual(error.exception.status,409)
            self.assertEqual(c.execute('SELECT count(*) FROM revision_closures').fetchone()[0],0)
            self.assertNotEqual(c.execute('SELECT state FROM revisions WHERE id=?',(page['revision_id'],)).fetchone()[0],'cerrada')
            self.assertEqual(c.execute("SELECT count(*) FROM audit_events WHERE action='revision_closed'").fetchone()[0],0)
        finally:c.close()

    def test_permissions_csrf_and_revocation_protect_capture(self):
        from fastapi.testclient import TestClient
        from app.api import create_app
        from tests.test_p02 import ORIGIN,PASSWORD
        self.assertEqual(self.client.post(self.base()+'/closure-preview').status_code,403)
        with TestClient(create_app(self.root,public_origin=ORIGIN,processing_enabled=False),base_url=ORIGIN) as viewer:
            login=viewer.post('/api/session',json={'username':'viewer','password':PASSWORD},headers={'Origin':ORIGIN})
            headers={'Origin':ORIGIN,'X-CSRF-Token':login.json()['csrf_token']}
            self.assertEqual(viewer.post(self.base()+'/closure-preview',headers=headers).status_code,403)
            self.assertEqual(viewer.get(self.base()+'/export-closed').status_code,403)
        self.resolve_alerts();page=self.justify();self.assertEqual(self.close(page).status_code,201)
        c=connect(self.root);c.execute('DELETE FROM sessions WHERE token_hash=?',(self.digest,));c.close()
        self.assertEqual(self.client.get(self.base()+'/export-closed').status_code,401)

    def test_confirmation_is_explicit_reused_and_invalidated_by_scope_changes(self):
        self.resolve_alerts();page=self.justify()
        original_ids=[g['justification']['id'] for g in page['limitations']]
        self.assertEqual(original_ids,[g['justification']['id'] for g in self.preview()['limitations']])
        response=self.client.post(self.base()+'/closure',headers=self.headers(),json={
            'expected_dataset_version':page['dataset_version'],'expected_revision_version':page['revision_version'],
            'preview_sha256':page['preview_sha256'],'confirmed_limitation_ids':[]})
        self.assertEqual(response.status_code,409)
        r=self.client.post(self.base()+'/rows/2/work-fields',headers=self.headers(),json={
            'expected_dataset_version':page['dataset_version'],'expected_revision_version':page['revision_version'],
            'field':'G','value':'3','reason':'Cambio ficticio de alcance tras justificar.'})
        self.assertEqual(r.status_code,200,r.text)
        changed=self.preview()
        self.assertTrue(any(g['justification'] is None for g in changed['limitations']))
        self.assertFalse(changed['can_close'])

    def test_transaction_failure_rolls_back_state_and_download_does_not_recalculate(self):
        self.resolve_alerts();page=self.justify()
        from app import closure
        with patch('app.closure.event',side_effect=RuntimeError('FICTICIO: rollback')):
            c=connect(self.root)
            try:
                with self.assertRaises(RuntimeError):
                    closure.close(c,self.root,self.digest,self.dataset['id'],self.batch,page['dataset_version'],page['revision_version'],page['preview_sha256'],[g['justification']['id'] for g in page['limitations']])
                self.assertEqual(c.execute('SELECT count(*) FROM revision_closures').fetchone()[0],0)
                self.assertNotEqual(c.execute('SELECT state FROM revisions WHERE id=?',(page['revision_id'],)).fetchone()[0],'cerrada')
            finally:c.close()
        self.assertEqual(self.close(page).status_code,201)
        with patch('app.provisional._run_summary',side_effect=RuntimeError('Do not recalculate')):
            self.assertEqual(self.client.get(self.base()+'/export-closed').status_code,200)

    def test_active_processing_blocks_closure(self):
        self.resolve_alerts();page=self.justify()
        self.client.app.state.processing_manager.close()
        queued=self.client.post(self.base()+'/processing-attempts',headers=self.headers(),json={
            'expected_dataset_version':page['dataset_version'],'expected_revision_version':page['revision_version'],
            'request_key':'closure-fictional-active-job'})
        self.assertEqual(queued.status_code,202,queued.text)
        self.assertTrue(self.preview()['processing_active'])
        self.assertEqual(self.close(page).status_code,409)


class ClosureMigrationTests(unittest.TestCase):
    def test_v19_upgrade_is_backed_up_and_failure_rolls_back(self):
        from pathlib import Path
        from app.db import MIGRATIONS, migrate, backup_before_upgrade
        from app.security import create_user
        from tests.temp_support import TemporaryDirectory
        from tests.test_p02 import PASSWORD
        with TemporaryDirectory(dir='.tmp') as directory:
            root=Path(directory);c=connect(root)
            try:
                old=tuple(m for m in MIGRATIONS if m[0]<=19)
                migrate(c,migrations=old)
                identity=create_user(c,'closure-migration',PASSWORD,'admin')
                backup=backup_before_upgrade(c,root)
                broken=old+((20,dict(MIGRATIONS)[20]+('INVALID SQL',)),)
                with self.assertRaises(sqlite3.OperationalError):migrate(c,migrations=broken,allow_existing_upgrade=True)
                self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0],19)
                self.assertIsNone(c.execute("SELECT name FROM sqlite_master WHERE name='revision_closures'").fetchone())
                self.assertEqual(migrate(c,allow_existing_upgrade=True),MIGRATIONS[-1][0])
                self.assertEqual(c.execute('SELECT id FROM users').fetchone()[0],identity)
                self.assertIsNone(c.execute('PRAGMA foreign_key_check').fetchone())
                self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok')
                saved=sqlite3.connect(backup/'app.sqlite3')
                try:
                    self.assertEqual(saved.execute('PRAGMA user_version').fetchone()[0],19)
                    self.assertEqual(saved.execute('SELECT id FROM users').fetchone()[0],identity)
                finally:saved.close()
            finally:c.close()

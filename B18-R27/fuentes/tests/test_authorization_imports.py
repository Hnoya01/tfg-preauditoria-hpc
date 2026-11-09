"""Canonical intake: invented authorizations only, no real coverage validation."""

from copy import deepcopy
import hashlib
from io import BytesIO
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from fastapi.testclient import TestClient

from app.api import create_app
from app.authorization_imports import confirm_authorization
from app.authorization_json import AuthorizationFormatError, parse_authorization
from app.controls import _run_summary
from app.db import connect
from app.security import create_user
from app.service import Problem
from tests import test_p05 as fixture
from tests.test_p02 import ORIGIN, PASSWORD


FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures' / 'autorizaciones'


def content(name='01_parcial.json'):
    return (FIXTURES / name).read_bytes()


def encode(value):
    return json.dumps(value, ensure_ascii=False).encode('utf-8')


class AuthorizationContractTests(unittest.TestCase):
    def test_representative_fictions_never_conclude_or_quantify(self):
        expected = [('01_parcial.json', 2, 0, 0), ('02_contradictoria.json', 1, 1, 0),
                    ('03_asociacion_ambigua.json', 2, 0, 1)]
        for name, items, conflict, ambiguous in expected:
            with self.subTest(name=name):
                parsed = parse_authorization(content(name))
                self.assertEqual(parsed.summary['orders'], 1)
                self.assertEqual(parsed.summary['items'], items)
                self.assertEqual(parsed.summary['orders_with_apparent_conflict'], conflict)
                self.assertEqual(parsed.summary['potentially_ambiguous_orders'], ambiguous)
                self.assertFalse(parsed.summary['controls_evaluated'])
                self.assertFalse(parsed.summary['analysis_started'])
                self.assertEqual(parsed.summary['coverage_verification'], 'not_verified')
                self.assertIsNone(parsed.summary['proposal_amount_ars'])
                self.assertEqual(parsed.canonical['orders'][0]['items'][0]['full_code'], '0000123456')
        partial = parse_authorization(content()).canonical['orders'][0]
        self.assertEqual(partial['global_status'], 'authorized')
        self.assertEqual([r['status'] for r in partial['resolutions']], ['authorized', 'rejected'])
        self.assertEqual(partial['resolutions'][0]['authorized_quantity'], '1')

    def test_incomplete_unknown_or_temporally_imprecise_is_not_format_error(self):
        raw = json.loads(content())
        raw['orders'] = [{'items': [{}], 'resolutions': [{'status': 'OTRO', 'authorized_quantity': 'desconocida'}]}]
        raw['source']['captured_at'] = '2026-08-20'
        raw['coverage']['declared'] = 'complete'
        parsed = parse_authorization(encode(raw))
        codes = {o['code'] for o in parsed.observations}
        self.assertTrue({'missing_order_id', 'quantity_unknown', 'quantity_uninterpretable',
                         'resolution_status_uninterpreted', 'resolution_scope_unresolved'} <= codes)
        self.assertEqual(parsed.summary['temporal_precision'][0]['precision'], 'day')
        self.assertEqual(parsed.canonical['source']['captured_at'], '2026-08-20')
        self.assertEqual(parsed.summary['coverage_verification'], 'not_verified')
        self.assertIsNone(parsed.canonical['orders'][0]['items'][0]['requested_quantity'])

    def test_bad_structure_numbers_and_client_attestations_are_format_errors(self):
        raw = json.loads(content())
        invalid = []
        for path, value in [('schema_version', 'other'), ('data_origin', 'verified')]:
            changed = deepcopy(raw); changed[path] = value; invalid.append(encode(changed))
        for field, value in [('full_code', 123456), ('requested_quantity', 2)]:
            changed = deepcopy(raw); changed['orders'][0]['items'][0][field] = value; invalid.append(encode(changed))
        changed = deepcopy(raw); changed['coverage']['verified'] = True; invalid.append(encode(changed))
        invalid += [b'{"orders":[],"orders":[]}', b'{"number":NaN}', b'\xff', b'[]',
                    b'{' + b'"huge":' + b'1' * 5000 + b'}', b'[' * 70 + b']' * 70,
                    b'{"source":"\\ud800"}', b'{"\\ud800":"text"}']
        for data in invalid:
            with self.subTest(data=data[:30]):
                with self.assertRaises(AuthorizationFormatError) as exc:
                    parse_authorization(data)
                self.assertTrue(exc.exception.errors)
                self.assertTrue(all(set(e) == {'path', 'code'} for e in exc.exception.errors))


class AuthorizationImportTests(unittest.TestCase):
    setUp = fixture.P05Tests.setUp
    tearDown = fixture.P05Tests.tearDown
    headers = fixture.P05Tests.headers
    import_book = fixture.P05Tests.import_book
    run_url = fixture.P05Tests.run_url
    alerts = fixture.P05Tests.alerts
    decide = fixture.P05Tests.decide

    def url(self, suffix=''):
        return f'/api/datasets/{self.dataset["id"]}/authorization-{suffix}'

    def stage(self, data=None, name='ficticio.json', expected=None):
        response = self.client.post(self.url('uploads'), content=content() if data is None else data,
            headers=self.headers(**{'X-Source-Filename': name, 'X-Expected-Version': str(
                self.dataset['version'] if expected is None else expected), 'Content-Type': 'application/octet-stream'}))
        if response.status_code in (200, 201):
            self.dataset['version'] = response.json()['dataset_version']
        return response

    def preview(self, upload):
        response = self.client.get(self.url(f'uploads/{upload["id"]}/preview'))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def confirm(self, upload, preview=None, **overrides):
        p = preview or self.preview(upload)
        body = {'expected_version': p['dataset_version'], 'preview_sha256': p['preview_sha256'],
                'provenance_note': 'Fixture ficticio conservado para prueba local.', **overrides}
        response = self.client.post(self.url(f'uploads/{upload["id"]}/import'), json=body, headers=self.headers())
        if response.status_code in (200, 201):
            self.dataset['version'] = response.json()['dataset_version']
        return response

    def test_original_provenance_preview_and_atomic_capture_without_analysis(self):
        original = content()
        staged = self.stage(original)
        self.assertEqual(staged.status_code, 201, staged.text)
        upload = staged.json()
        p = self.preview(upload)
        self.assertTrue(p['can_import'])
        self.assertEqual(p['technical_state'], 'interpreted')
        response = self.confirm(upload, p)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertFalse(response.json()['analysis_started'])
        download = self.client.get(self.url(f'uploads/{upload["id"]}/file'))
        self.assertEqual(download.content, original)
        self.assertEqual(download.headers['x-content-sha256'], hashlib.sha256(original).hexdigest())
        history = self.client.get(self.url('captures')).json()
        self.assertEqual(history['captures'][0]['actor_username'], 'owner')
        self.assertIn('ficticio', history['captures'][0]['provenance_note'])
        self.assertEqual(history['captures'][0]['data_origin'], 'synthetic')
        conn = connect(self.root)
        try:
            self.assertEqual(conn.execute('SELECT count(*) FROM control_runs').fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT count(*) FROM review_decisions').fetchone()[0], 0)
            self.assertEqual(conn.execute('SELECT count(*) FROM economic_verifications').fetchone()[0], 0)
            self.assertEqual(conn.execute('SELECT count(*) FROM proposal_versions').fetchone()[0], 0)
            summary = _run_summary(conn, self.dataset['id'], self.run['id'])
            self.assertEqual(set(summary['affected_rules']), {'RN09', 'RN10', 'RN11', 'RN18'})
            source = conn.execute('SELECT * FROM source_registry WHERE kind = "authorizations"').fetchone()
            self.assertEqual(json.loads(source['coverage_json'])['verification'], 'not_verified')
            self.assertTrue(json.loads(source['metadata_json'])['import_only'])
        finally:
            conn.close()

    def test_bad_format_retains_original_and_does_not_become_functional_failure(self):
        upload = self.stage(b'{bad JSON').json()
        p = self.preview(upload)
        self.assertFalse(p['can_import'])
        self.assertEqual(p['technical_state'], 'format_error')
        self.assertEqual(p['authorization_control'], 'not_evaluated')
        self.assertEqual(p['observations'], [])
        response = self.confirm(upload, p, preview_sha256='0' * 64)
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.client.get(self.url(f'uploads/{upload["id"]}/file')).content, b'{bad JSON')
        self.assertEqual(self.client.get(self.url('captures')).json()['captures'], [])

    def test_duplicate_renamed_original_and_history_do_not_reactivate_old_capture(self):
        first_upload = self.stage().json()
        first = self.confirm(first_upload).json()
        version = self.dataset['version']
        again = self.stage(name='otro-nombre.json')
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json()['id'], first_upload['id'])
        self.assertEqual(self.dataset['version'], version)
        second_upload = self.stage(content('04_parcial_v2.json')).json()
        second = self.confirm(second_upload).json()
        self.assertEqual(second['ordinal'], 2)
        self.assertEqual(second['previous_id'], first['id'])
        version = self.dataset['version']
        repeated = self.confirm(first_upload)
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertEqual(repeated.json()['id'], first['id'])
        self.assertEqual(self.dataset['version'], version)
        history = self.client.get(self.url('captures')).json()['captures']
        self.assertEqual([c['is_latest_import'] for c in history], [False, True])
        self.assertEqual(self.preview(first_upload)['canonical']['source']['capture_id'], 'FICT-CAP-001')

    def test_unknown_information_and_apparent_conflict_are_importable(self):
        for name in ('02_contradictoria.json', '03_asociacion_ambigua.json'):
            upload = self.stage(content(name)).json()
            p = self.preview(upload)
            self.assertTrue(p['can_import'])
            self.assertTrue(p['observations'])
            self.assertEqual(self.confirm(upload, p).status_code, 201)
        raw = json.loads(content()); raw['orders'] = [{}]
        upload = self.stage(encode(raw)).json()
        self.assertTrue(self.preview(upload)['can_import'])
        self.assertEqual(self.confirm(upload).status_code, 201)

    def test_independent_human_decision_remains_current_after_authorization_import(self):
        alert = self.alerts()['items'][0]
        decided = self.decide([{'id': alert['id'], 'expected_version': alert['version']}])
        self.assertEqual(decided.status_code, 200, decided.text)
        self.dataset['version'] = decided.json()['dataset_version']
        upload = self.stage().json()
        self.assertEqual(self.confirm(upload).status_code, 201)
        after = next(a for a in self.alerts()['items'] if a['id'] == alert['id'])
        self.assertEqual(after['rule_code'], 'RN17')
        self.assertEqual(after['decision'], 'descartada')
        self.assertEqual(after['freshness'], 'current')
        conn = connect(self.root)
        try:
            self.assertEqual(conn.execute('SELECT count(*) FROM review_decisions').fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT count(*) FROM control_runs').fetchone()[0], 1)
        finally:
            conn.close()

    def test_stream_origin_isolation_and_reused_external_id(self):
        first = self.stage().json(); self.assertEqual(self.confirm(first).status_code, 201)
        raw = json.loads(content()); raw['coverage']['limitations'].append('Otra recepción ficticia.')
        changed = self.stage(encode(raw)).json()
        self.assertIn('external_capture_id_reused', {o['code'] for o in self.preview(changed)['observations']})
        self.assertEqual(self.confirm(changed).status_code, 201)
        raw['data_origin'] = 'real_unvalidated'
        mixed = self.stage(encode(raw)).json()
        p = self.preview(mixed)
        self.assertEqual(p['technical_state'], 'interpreted')
        self.assertFalse(p['can_import'])
        self.assertEqual(p['context_errors'][0]['code'], 'stream_origin_conflict')
        self.assertEqual(self.confirm(mixed, p).status_code, 409)

    def test_stale_versions_preview_token_csrf_and_extra_claims_rejected(self):
        stale = self.dataset['version']
        upload = self.stage().json(); p = self.preview(upload)
        self.assertEqual(self.stage(content('02_contradictoria.json'), expected=stale).status_code, 409)
        self.assertEqual(self.confirm(upload, p, preview_sha256='f' * 64).status_code, 409)
        self.assertEqual(self.confirm(upload, p, economic_verified=True).status_code, 422)
        denied = self.client.post(self.url(f'uploads/{upload["id"]}/import'), json={
            'expected_version': p['dataset_version'], 'preview_sha256': p['preview_sha256'],
            'provenance_note': 'Prueba ficticia sin token CSRF.'}, headers={'Origin': ORIGIN})
        self.assertEqual(denied.status_code, 403)
        self.stage(content('02_contradictoria.json'))
        self.assertEqual(self.confirm(upload, p).status_code, 409)
        self.assertEqual(self.confirm(upload).status_code, 201)

    def test_permissions_and_cross_dataset_ids_for_all_authorization_routes(self):
        upload = self.stage().json(); p = self.preview(upload)
        conn = connect(self.root)
        create_user(conn, 'reviewer', PASSWORD, 'reviewer'); conn.close()
        for username in ('viewer', 'reviewer'):
            with TestClient(create_app(self.root, public_origin=ORIGIN), base_url=ORIGIN) as outsider:
                login = outsider.post('/api/session', json={'username': username, 'password': PASSWORD}, headers={'Origin': ORIGIN}).json()
                h = {'Origin': ORIGIN, 'X-CSRF-Token': login['csrf_token']}
                for tail in ('captures', f'uploads/{upload["id"]}/preview', f'uploads/{upload["id"]}/file'):
                    self.assertEqual(outsider.get(self.url(tail)).status_code, 403)
                self.assertEqual(outsider.post(self.url('uploads'), content=content(), headers={**h,
                    'X-Expected-Version': str(self.dataset['version']), 'X-Source-Filename': 'test.json'}).status_code, 403)
                self.assertEqual(outsider.post(self.url(f'uploads/{upload["id"]}/import'), json={
                    'expected_version': p['dataset_version'], 'preview_sha256': p['preview_sha256'],
                    'provenance_note': 'Prueba ficticia de permisos.'}, headers=h).status_code, 403)
        other = self.client.post('/api/datasets', json={'label': 'Otro conjunto ficticio'}, headers=self.headers()).json()
        for tail in ('preview', 'file'):
            self.assertEqual(self.client.get(f'/api/datasets/{other["id"]}/authorization-uploads/{upload["id"]}/{tail}').status_code, 404)
        self.assertEqual(self.client.post(f'/api/datasets/{other["id"]}/authorization-uploads/{upload["id"]}/import',
            json={'expected_version': other['version'], 'preview_sha256': p['preview_sha256'],
                  'provenance_note': 'Prueba ficticia entre conjuntos.'}, headers=self.headers()).status_code, 404)

    def test_authorized_reviewer_can_import(self):
        conn = connect(self.root); create_user(conn, 'reviewer', PASSWORD, 'reviewer'); conn.close()
        granted = self.client.post(f'/api/datasets/{self.dataset["id"]}/access',
            json={'username': 'reviewer', 'role': 'reviewer', 'expected_version': self.dataset['version']}, headers=self.headers())
        self.dataset['version'] = granted.json()['version']
        upload = self.stage().json(); p = self.preview(upload)
        with TestClient(create_app(self.root, public_origin=ORIGIN), base_url=ORIGIN) as reviewer:
            login = reviewer.post('/api/session', json={'username': 'reviewer', 'password': PASSWORD}, headers={'Origin': ORIGIN}).json()
            result = reviewer.post(self.url(f'uploads/{upload["id"]}/import'), json={
                'expected_version': p['dataset_version'], 'preview_sha256': p['preview_sha256'],
                'provenance_note': 'Revisor autorizado, fuente ficticia.'},
                headers={'Origin': ORIGIN, 'X-CSRF-Token': login['csrf_token']})
            self.assertEqual(result.status_code, 201, result.text)

    def test_permission_and_version_checked_again_at_publication(self):
        upload = self.stage().json(); p = self.preview(upload)
        conn = connect(self.root)
        def change_version():
            other = connect(self.root)
            other.execute('UPDATE datasets SET version = version + 1 WHERE id = ?', (self.dataset['id'],)); other.close()
        try:
            with self.assertRaises(Problem) as exc:
                confirm_authorization(conn, self.root, self.digest, self.dataset['id'], upload['id'],
                    p['dataset_version'], p['preview_sha256'], 'Prueba de cambio concurrente.', after_prepare=change_version)
            self.assertEqual(exc.exception.status, 409)
            self.assertEqual(conn.execute('SELECT count(*) FROM authorization_captures').fetchone()[0], 0)
            p = self.preview(upload)
            def revoke():
                other = connect(self.root)
                other.execute('DELETE FROM sessions WHERE token_hash = ?', (self.digest,)); other.close()
            with self.assertRaises(Problem) as exc:
                confirm_authorization(conn, self.root, self.digest, self.dataset['id'], upload['id'],
                    p['dataset_version'], p['preview_sha256'], 'Prueba de revocación durante lectura.', after_prepare=revoke)
            self.assertEqual(exc.exception.status, 401)
            self.assertEqual(conn.execute('SELECT count(*) FROM authorization_captures').fetchone()[0], 0)
        finally:
            conn.close()

    def test_preview_rechecks_session_after_interpretation(self):
        upload = self.stage().json()
        def parse_then_revoke(data):
            parsed = parse_authorization(data)
            conn = connect(self.root); conn.execute('DELETE FROM sessions WHERE token_hash = ?', (self.digest,)); conn.close()
            return parsed
        with patch('app.authorization_imports.parse_authorization', side_effect=parse_then_revoke):
            response = self.client.get(self.url(f'uploads/{upload["id"]}/preview'))
        self.assertEqual(response.status_code, 401)
        self.assertNotIn('canonical', response.json())

    def test_corrupted_original_is_not_interpreted_or_confirmed(self):
        upload = self.stage().json()
        path = self.root / 'objects' / upload['source_sha256'][:2] / upload['source_sha256']
        path.write_bytes(b'alterado')
        self.assertEqual(self.client.get(self.url(f'uploads/{upload["id"]}/preview')).status_code, 409)
        self.assertEqual(self.client.get(self.url(f'uploads/{upload["id"]}/file')).status_code, 409)

    def test_restart_and_provisional_export_preserve_versions_and_uncertainty(self):
        for name in ('01_parcial.json', '04_parcial_v2.json'):
            upload = self.stage(content(name)).json(); self.assertEqual(self.confirm(upload).status_code, 201)
        with TestClient(create_app(self.root, public_origin=ORIGIN), base_url=ORIGIN) as restarted:
            restarted.cookies.update(self.client.cookies)
            history = restarted.get(self.url('captures'))
            self.assertEqual(history.status_code, 200)
            self.assertEqual(len(history.json()['captures']), 2)
        response = self.client.get(f'/api/datasets/{self.dataset["id"]}/batches/{self.batch}/export-provisional')
        self.assertEqual(response.status_code, 200, response.text)
        with ZipFile(BytesIO(response.content)) as archive:
            records = [json.loads(line) for line in archive.read('authorization_captures.jsonl').splitlines()]
            manifest = json.loads(archive.read('manifest.json'))
        self.assertEqual([r['is_latest_import'] for r in records], [False, True])
        self.assertTrue(all(r['coverage_verification'] == 'not_verified' and r['proposal_amount_ars'] is None for r in records))
        self.assertIsNone(manifest['current_proposal_total_ars'])
        self.assertEqual(manifest['control_run']['freshness'], 'requires_update')


if __name__ == '__main__':
    unittest.main()

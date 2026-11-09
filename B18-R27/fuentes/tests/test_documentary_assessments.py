"""Individual documentary history with invented catalogs and observations only."""

from io import BytesIO
import hashlib
import json
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from fastapi.testclient import TestClient

from app import documentary_assessments as domain
from app import provisional
from app.db import connect
from app.security import create_user
from app.storage import object_path
from tests import test_hpc_comparison as fixture
from tests.test_economic_evidence import PDF
from tests.test_p02 import ORIGIN, PASSWORD


class DocumentaryAssessmentTests(unittest.TestCase):
    tearDown = fixture.HpcComparisonTests.tearDown
    headers = fixture.HpcComparisonTests.headers
    import_book = fixture.HpcComparisonTests.import_book
    run_url = fixture.HpcComparisonTests.run_url
    register_fictional_hpc = fixture.HpcComparisonTests.register_fictional_hpc

    def setUp(self):
        fixture.HpcComparisonTests.setUp(self)
        self.source_id = self.register_fictional_hpc({'catalogueSource': 'anexo-ficticio.pdf', 'cataloguePage': 2})
        response = self.client.post(f'/api/datasets/{self.dataset["id"]}/evidence-pdfs', content=PDF,
            headers=self.headers(**{'X-Expected-Version': str(self.dataset['version']), 'X-Source-Id': self.source_id,
                'X-Source-Filename': 'anexo-ficticio.pdf', 'X-Evidence-Category': 'nomenclator',
                'X-Provenance-Note': 'Documento inventado para el ensayo documental.',
                'X-Expected-SHA256': hashlib.sha256(PDF).hexdigest()}))
        self.assertEqual(response.status_code, 201, response.text)
        self.document_id = response.json()['id']
        self.dataset['version'] = response.json()['dataset_version']

    def url(self, dataset=None, source=None):
        return f'/api/datasets/{dataset or self.dataset["id"]}/sources/{source or self.source_id}/documentary-assessments'

    def body(self, **changes):
        return {'expected_dataset_version': self.dataset['version'], 'provider': 'HPC', 'code_complete': '123456',
                'tariff_seq': 1, 'document_id': self.document_id, 'edition': 'Edición ficticia 2026',
                'page_number': 2, 'fragment': 'Código ficticio 123456, columna U.B. en la tabla de prueba.',
                'observed_factor': '1', 'conclusion': 'matches', 'note': 'Cotejo humano ficticio de código y unidades.', **changes}

    def save(self, **changes):
        response = self.client.post(self.url(), json=self.body(**changes), headers=self.headers())
        self.assertEqual(response.status_code, 201, response.text)
        self.dataset['version'] = response.json()['dataset_version']
        return response.json()

    def history(self, **changes):
        response = self.client.get(self.url(), params={'provider': 'HPC', 'code': '123456', 'tariff_seq': 1, **changes})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def readiness(self):
        response = self.client.get(f'/api/datasets/{self.dataset["id"]}/batches/{self.batch}/reference-readiness',
                                   params={'source_id': self.source_id, 'source_row': 3})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['items'][0]

    def test_history_factor_precision_and_readiness_without_economic_approval(self):
        self.assertIn('factor_page_cotejo_not_recorded_per_code', self.readiness()['blocked_dimensions'])
        saved = self.save()
        history = self.history()
        record = history['latest']
        self.assertEqual(record['id'], saved['id'])
        self.assertEqual(record['observed_factor'], '1.000')
        self.assertEqual(record['basis_at_save']['source']['cut_label'], 'BASE_2026-10-09')
        self.assertEqual(record['basis_at_save']['document']['sha256'], hashlib.sha256(PDF).hexdigest())
        self.assertEqual(record['page_number'], 2)
        self.assertTrue(record['usable_match'])
        self.assertFalse(record['economic_approval'])
        self.assertTrue(record['actor_id'])
        self.assertTrue(record['created_at'])
        item = self.readiness()
        self.assertNotIn('factor_page_cotejo_not_recorded_per_code', item['blocked_dimensions'])
        self.assertIn('conditions_not_verified_for_row', item['blocked_dimensions'])
        self.assertFalse(item['ready_for_amount'])
        self.assertIsNone(item['proposal_amount_ars'])
        conn = connect(self.root)
        self.assertEqual(conn.execute('SELECT count(*) FROM economic_verifications').fetchone()[0], 0)
        self.assertEqual(conn.execute('SELECT count(*) FROM proposal_versions').fetchone()[0], 0)
        conn.close()

    def test_new_conclusion_keeps_original_and_never_falls_back(self):
        first = self.save()
        original = self.history()['history'][0]
        second = self.save(conclusion='differs', observed_factor='2.125', note='Nueva observación ficticia corrige la lectura anterior.')
        history = self.history()
        self.assertEqual(history['history'][0], original)
        self.assertEqual(history['history'][1]['previous_id'], first['id'])
        self.assertEqual(history['latest']['id'], second['id'])
        self.assertFalse(history['latest']['usable_match'])
        self.assertIn('factor_page_discrepancy', self.readiness()['blocked_dimensions'])
        self.save(conclusion='inconclusive', observed_factor=None, note='La ubicación ficticia no permite confirmar el factor.')
        self.assertIsNone(self.history()['latest']['observed_factor'])
        self.assertIn('factor_page_inconclusive', self.readiness()['blocked_dimensions'])

    def test_invalid_precision_conclusions_and_documents_are_atomic(self):
        for changes in ({'observed_factor': 'NaN'}, {'observed_factor': '1.0001'}, {'observed_factor': '-1'},
                        {'observed_factor': '2'}, {'observed_factor': None}, {'conclusion': 'differs'},
                        {'observed_factor': 1}, {'page_number': True}, {'page_number': 0}, {'edition': ' '},
                        {'document_id': 'unrelated'}, {'code_complete': '000123456'}, {'economic_approval': True}):
            response = self.client.post(self.url(), json=self.body(**changes), headers=self.headers())
            self.assertIn(response.status_code, (404, 422), response.text)
        self.assertEqual(self.history()['history'], [])
        self.save()

    def test_stale_save_and_csrf_reject_without_overwriting(self):
        stale = self.body()
        self.save()
        response = self.client.post(self.url(), json=stale, headers=self.headers())
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.client.post(self.url(), json=self.body(), headers={'Origin': ORIGIN}).status_code, 403)
        self.assertEqual(len(self.history()['history']), 1)

    def test_own_document_change_affects_observation(self):
        self.save()
        conn = connect(self.root)
        conn.execute("UPDATE evidence_documents SET provenance_note = 'Cambio ficticio de procedencia' WHERE id = ?", (self.document_id,))
        conn.close()
        latest = self.history()['latest']
        self.assertEqual(latest['freshness'], 'requires_update')
        self.assertFalse(latest['usable_match'])
        self.assertIn('factor_page_assessment_affected', self.readiness()['blocked_dimensions'])
        self.save(note='Nuevo cotejo sobre la procedencia documental corregida.')
        self.assertTrue(self.history()['latest']['usable_match'])

    def register_other_pdf(self, name='otro-ficticio.pdf'):
        content = PDF.replace(b'%%EOF', b'% Second fictional original\n%%EOF')
        response = self.client.post(f'/api/datasets/{self.dataset["id"]}/evidence-pdfs', content=content,
            headers=self.headers(**{'X-Expected-Version': str(self.dataset['version']), 'X-Source-Id': self.source_id,
                'X-Source-Filename': name, 'X-Evidence-Category': 'nomenclator',
                'X-Provenance-Note': 'Segundo documento inventado independiente.',
                'X-Expected-SHA256': hashlib.sha256(content).hexdigest()}))
        self.assertEqual(response.status_code, 201, response.text)
        self.dataset['version'] = response.json()['dataset_version']

    def test_unrelated_document_keeps_observation_current(self):
        self.save()
        before = self.history()['history'][0]
        self.register_other_pdf()
        self.assertEqual(self.history()['history'][0], before)
        self.assertTrue(self.history()['latest']['usable_match'])

    def test_ambiguous_filename_never_selects_an_arbitrary_pdf(self):
        self.save()
        self.register_other_pdf(name='anexo-ficticio.pdf')
        self.assertEqual(self.history()['latest']['freshness'], 'requires_update')
        self.assertEqual(self.client.post(self.url(), json=self.body(), headers=self.headers()).status_code, 409)

    def test_source_metadata_change_affects_history_with_original_basis_retained(self):
        self.save()
        before = self.history()['history'][0]
        conn = connect(self.root)
        conn.execute("UPDATE source_registry SET cut_label = 'OTRO_CORTE_FICTICIO' WHERE id = ?", (self.source_id,))
        conn.close()
        history = self.history()
        self.assertEqual(history['history'][0], before)
        self.assertEqual(history['latest']['freshness'], 'requires_update')

    def test_missing_pdf_affects_history_and_prevents_new_record(self):
        self.save()
        object_path(self.root, hashlib.sha256(PDF).hexdigest()).unlink()
        self.assertEqual(self.history()['latest']['freshness'], 'requires_update')
        self.assertEqual(self.client.post(self.url(), json=self.body(), headers=self.headers()).status_code, 409)
        self.assertEqual(len(self.history()['history']), 1)

    def test_permissions_are_per_dataset_and_sources_cannot_be_crossed(self):
        self.save()
        conn = connect(self.root)
        reviewer = create_user(conn, 'reviewer', PASSWORD, 'reviewer')
        conn.execute('INSERT INTO dataset_access VALUES (?, ?, ?)', (self.dataset['id'], reviewer, 'reviewer'))
        conn.close()
        with TestClient(self.client.app, base_url=ORIGIN) as client:
            login = client.post('/api/session', json={'username': 'viewer', 'password': PASSWORD}, headers={'Origin': ORIGIN})
            self.assertEqual(client.get(self.url(), params={'provider': 'HPC', 'code': '123456', 'tariff_seq': 1}).status_code, 403)
            self.assertEqual(client.post(self.url(), json=self.body(), headers={'Origin': ORIGIN, 'X-CSRF-Token': login.json()['csrf_token']}).status_code, 403)
            login = client.post('/api/session', json={'username': 'reviewer', 'password': PASSWORD}, headers={'Origin': ORIGIN})
            self.assertEqual(client.get(self.url(), params={'provider': 'HPC', 'code': '123456', 'tariff_seq': 1}).status_code, 200)
            response = client.post(self.url(), json=self.body(), headers={'Origin': ORIGIN, 'X-CSRF-Token': login.json()['csrf_token']})
            self.assertEqual(response.status_code, 201, response.text)
        other = self.client.post('/api/datasets', json={'label': 'Otro conjunto ficticio'}, headers=self.headers()).json()
        response = self.client.get(self.url(dataset=other['id']), params={'provider': 'HPC', 'code': '123456', 'tariff_seq': 1})
        self.assertEqual(response.status_code, 404)
        body = self.body(expected_dataset_version=other['version'])
        self.assertEqual(self.client.post(self.url(dataset=other['id']), json=body, headers=self.headers()).status_code, 404)

    def test_export_preserves_documentary_versions_without_money(self):
        self.save()
        self.save(conclusion='inconclusive', observed_factor=None)
        response = self.client.get(f'/api/datasets/{self.dataset["id"]}/batches/{self.batch}/export-provisional')
        self.assertEqual(response.status_code, 200, response.text)
        with ZipFile(BytesIO(response.content)) as archive:
            records = [json.loads(line) for line in archive.read('documentary_assessments.jsonl').splitlines()]
            manifest = json.loads(archive.read('manifest.json'))
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]['freshness'], 'historical')
        self.assertTrue(records[1]['is_latest'])
        self.assertFalse(records[1]['usable_match'])
        self.assertIsNone(manifest['current_proposal_total_ars'])

    def test_observation_during_export_rejects_outdated_zip(self):
        original = provisional._write_lines
        done = False
        def interleave(archive, name, records):
            nonlocal done
            original(archive, name, records)
            if not done:
                done = True
                self.save()
        with patch.object(provisional, '_write_lines', side_effect=interleave):
            response = self.client.get(f'/api/datasets/{self.dataset["id"]}/batches/{self.batch}/export-provisional')
        self.assertEqual(response.status_code, 409, response.text)

    def test_permission_revocation_during_read_rejects_history(self):
        self.save()
        original = domain.DocumentaryEvaluator.evaluate
        def revoke(evaluator, record):
            result = original(evaluator, record)
            conn = connect(self.root)
            try:
                conn.execute('DELETE FROM sessions')
            finally:
                conn.close()
            return result
        with patch.object(domain.DocumentaryEvaluator, 'evaluate', revoke):
            response = self.client.get(self.url(), params={'provider': 'HPC', 'code': '123456', 'tariff_seq': 1})
        self.assertEqual(response.status_code, 401)

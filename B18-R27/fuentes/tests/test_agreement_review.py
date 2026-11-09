"""General references from documentary facts, using fictional sources only."""

import copy
import hashlib
import json
import unittest
from io import BytesIO
from zipfile import ZipFile

from app.agreement_review import register_agreement_review
from app.db import connect
from app.security import create_user, issue_session, token_digest
from app.service import Problem
from app.storage import object_path
from scripts.prepare_agreement_review import observe_factor
from tests import test_documentary_assessments as fixture


class AgreementReviewTests(unittest.TestCase):
    setUp = fixture.DocumentaryAssessmentTests.setUp
    tearDown = fixture.DocumentaryAssessmentTests.tearDown
    headers = fixture.DocumentaryAssessmentTests.headers
    import_book = fixture.DocumentaryAssessmentTests.import_book
    run_url = fixture.DocumentaryAssessmentTests.run_url
    register_fictional_hpc = fixture.DocumentaryAssessmentTests.register_fictional_hpc
    readiness = fixture.DocumentaryAssessmentTests.readiness
    url = fixture.DocumentaryAssessmentTests.url
    body = fixture.DocumentaryAssessmentTests.body
    save = fixture.DocumentaryAssessmentTests.save
    register_other_pdf = fixture.DocumentaryAssessmentTests.register_other_pdf

    def report(self, specific_norm=False):
        conn = connect(self.root)
        source = conn.execute('SELECT source_sha256 FROM source_registry WHERE id = ?', (self.source_id,)).fetchone()[0]
        sha = conn.execute('SELECT sha256 FROM evidence_documents WHERE id = ?', (self.document_id,)).fetchone()[0]
        conn.close()
        return {'version': 'P06-general-agreement-v1', 'producer': 'automated_pdf_text_crosscheck', 'economic_approval': False,
                'source_sha256': source, 'cut_label': 'BASE_2026-10-09', 'document_sha256s': [sha],
                'agreement': {'sha256': sha, 'page': 1, 'valid_from': '2026-06-01', 'ub_rate_cents': 1500,
                              'currency_basis': 'ARS_fictional_documentary_context', 'practice_unit_basis': {'sha256': sha, 'page': 1}},
                'references': [{'tariff_seq': 1, 'code_complete': '123456', 'amount_cents': 1500,
                                'document_sha256': sha, 'page': 2, 'ub_milliunits': 1000, 'observed_factor_ub': '1.0',
                                'code_fragment': '123456 DETERMINACION FICTICIA 1,0', 'specific_norm': specific_norm}], 'unresolved': []}

    def register(self, report=None):
        conn = connect(self.root)
        try:
            result = register_agreement_review(conn, self.root, self.digest, self.dataset['id'], self.source_id,
                                                self.dataset['version'], self.report() if report is None else report)
            self.dataset['version'] = result['dataset_version']
            return result
        finally:
            conn.close()

    def test_supported_reference_resolves_only_documented_dimensions(self):
        self.register()
        item = self.readiness()
        general = item['general_reference']
        self.assertEqual(general['status'], 'supported_base_reference')
        self.assertEqual(general['rate_per_practice_ars'], '15.00')
        self.assertEqual(general['general_row_value_ars'], '30.00')
        self.assertTrue(general['no_end_date_is_not_expiry'])
        for code in ('end_or_supersession_not_verified', 'specific_agreement_not_checked', 'currency_not_verified_per_reference',
                     'billing_unit_not_verified_for_row', 'factor_page_cotejo_not_recorded_per_code'):
            self.assertNotIn(code, item['blocked_dimensions'])
        self.assertIn('confirmed_current_finding_missing', item['blocked_dimensions'])
        self.assertFalse(item['ready_for_amount'])
        self.assertFalse(general['case_applicability_confirmed'])
        self.assertIsNone(item['proposal_amount_ars'])
        conn = connect(self.root)
        self.assertEqual(conn.execute('SELECT count(*) FROM economic_verifications').fetchone()[0], 0)
        self.assertEqual(conn.execute('SELECT count(*) FROM documentary_assessments').fetchone()[0], 0)
        conn.close()

    def test_specific_norm_is_a_concrete_remaining_question(self):
        self.register(self.report(specific_norm=True))
        item = self.readiness()
        self.assertEqual(item['general_reference']['status'], 'requires_case_interpretation')
        self.assertIn('specific_nbu_norm_requires_case_interpretation', item['blocked_dimensions'])

    def test_missing_factor_does_not_reopen_documented_shared_clauses(self):
        report = self.report()
        report['references'] = []
        report['unresolved'] = [{'tariff_seq': 1, 'code_complete': '123456', 'reason': 'factor_not_crosschecked'}]
        self.register(report)
        item = self.readiness()
        self.assertEqual(item['general_reference']['status'], 'not_documented')
        self.assertIn('factor_page_cotejo_not_recorded_per_code', item['blocked_dimensions'])
        for code in ('end_or_supersession_not_verified', 'currency_not_verified_per_reference',
                     'billing_unit_not_verified_for_row', 'specific_agreement_not_checked'):
            self.assertNotIn(code, item['blocked_dimensions'])

    def test_conflicting_individual_observation_is_not_overridden(self):
        self.register()
        self.save(conclusion='differs', observed_factor='2')
        self.assertEqual(self.readiness()['general_reference']['status'], 'requires_update')
        self.assertIn('factor_page_discrepancy', self.readiness()['blocked_dimensions'])

    def test_source_and_document_changes_remove_supported_reference(self):
        self.register()
        conn = connect(self.root)
        conn.execute("UPDATE evidence_documents SET provenance_note = 'Cambio ficticio documentado' WHERE id = ?", (self.document_id,))
        conn.close()
        self.assertEqual(self.readiness()['general_reference']['status'], 'requires_update')
        conn = connect(self.root)
        conn.execute("UPDATE source_registry SET metadata_json = '{}' WHERE id = ?", (self.source_id,))
        conn.close()
        self.assertEqual(self.readiness()['general_reference']['status'], 'requires_update')

    def test_idempotence_keeps_one_snapshot_and_new_review_keeps_history(self):
        first = self.register()
        version = self.dataset['version']
        second = self.register()
        self.assertFalse(second['created'])
        self.assertEqual(second['id'], first['id'])
        self.assertEqual(self.dataset['version'], version)
        third = self.register(self.report(specific_norm=True))
        self.assertEqual(third['ordinal'], 2)
        conn = connect(self.root)
        self.assertEqual(conn.execute('SELECT count(*) FROM agreement_document_reviews').fetchone()[0], 2)
        conn.close()

    def test_permissions_versions_and_wrong_source_are_rejected(self):
        conn = connect(self.root)
        try:
            uid = create_user(conn, 'outsider', 'Fictional-test-password-2026!', 'reviewer')
            token, _ = issue_session(conn, uid)
            for digest, source, version, status in ((token_digest(token), self.source_id, self.dataset['version'], 403),
                    (self.digest, self.source_id, self.dataset['version'] - 1, 409), (self.digest, 'unknown', self.dataset['version'], 404)):
                with self.assertRaises(Problem) as failed:
                    register_agreement_review(conn, self.root, digest, self.dataset['id'], source, version, self.report())
                self.assertEqual(failed.exception.status, status)
        finally:
            conn.close()

    def test_unsupported_factor_cannot_be_installed_as_documented(self):
        report = self.report()
        report['references'][0]['observed_factor_ub'] = '2'
        with self.assertRaises(Problem):
            self.register(report)
        self.assertEqual(self.readiness()['general_reference']['status'], 'not_documented')

    def test_export_identifies_automatic_review_and_keeps_money_unknown(self):
        self.register()
        response = self.client.get(f'/api/datasets/{self.dataset["id"]}/batches/{self.batch}/export-provisional')
        self.assertEqual(response.status_code, 200, response.text)
        with ZipFile(BytesIO(response.content)) as archive:
            records = [json.loads(line) for line in archive.read('agreement_document_reviews.jsonl').splitlines()]
            manifest = json.loads(archive.read('manifest.json'))
        self.assertEqual(records[0]['report']['producer'], 'automated_pdf_text_crosscheck')
        self.assertFalse(records[0]['economic_approval'])
        self.assertIsNone(manifest['current_proposal_total_ars'])

    def test_parser_preserves_exact_code_decimal_and_ambiguity(self):
        text = '123456 PRACTICA FICTICIA U N 1,5\n123457 OTRA 2,0\n'
        observed = observe_factor(text, '123456', 1500)
        self.assertTrue(observed['specific_norm'])
        self.assertEqual(observed['observed_factor_ub'], '1.5')
        self.assertIsNone(observe_factor(text, '12345', 1500))
        self.assertIsNone(observe_factor(text, '123456', 2000))
        self.assertIsNone(observe_factor(text + text, '123456', 1500))
        final_row = '123456 PRACTICA FICTICIA N 1,5\nREFERENCIAS\nN: norma explicativa\n'
        self.assertEqual(observe_factor(final_row, '123456', 1500)['observed_factor_ub'], '1.5')

    def test_unrelated_pdf_change_or_loss_keeps_independent_reference(self):
        self.register_other_pdf()
        conn = connect(self.root)
        other = dict(conn.execute('SELECT * FROM evidence_documents WHERE id != ?', (self.document_id,)).fetchone())
        conn.close()
        report = self.report()
        report['document_sha256s'].append(other['sha256'])
        self.register(report)
        conn = connect(self.root)
        conn.execute("UPDATE evidence_documents SET provenance_note = 'Otra procedencia ficticia' WHERE id = ?", (other['id'],))
        conn.close()
        self.assertEqual(self.readiness()['general_reference']['status'], 'supported_base_reference')
        object_path(self.root, other['sha256']).unlink()
        self.assertEqual(self.readiness()['general_reference']['status'], 'supported_base_reference')

    def test_dependent_pdf_loss_marks_reference_without_erasing_history(self):
        saved = self.register()
        object_path(self.root, self.report()['document_sha256s'][0]).unlink()
        item = self.readiness()
        self.assertEqual(item['general_reference']['status'], 'requires_update')
        self.assertIn('factor_document_original_unavailable', item['blocked_dimensions'])
        conn = connect(self.root)
        self.assertEqual(conn.execute('SELECT id FROM agreement_document_reviews').fetchone()[0], saved['id'])
        conn.close()

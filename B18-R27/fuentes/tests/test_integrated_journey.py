"""One synthetic X1/A1/HPC journey through decisions, invalidation and export."""
from io import BytesIO
import json
import unittest
from zipfile import ZipFile

from tests import test_authorization_controls as fixture
from tests import test_hpc_comparison as values_fixture
from tests.test_p02 import book


class IntegratedJourneyTests(unittest.TestCase):
    def test_sources_review_change_reanalysis_and_provisional_export(self):
        case = fixture.IntegratedAuthorizationTests()
        case.setUp()
        try:
            case.batch = case.import_book(book([
                ('15/08/2026', 10, 20, 30, 'A'), ('16/08/2026', 10, 20, 30, 'C'),
                ('15/08/2026', 10, 20, 30, 'I'), ('15/09/2026', 10, 20, 30, 'A'),
                ('15/08/2026', 10, 20, 30, 'X'),
            ]), 'JORNADA_FICTICIA.xlsx')
            case.ready()
            self.assertEqual(case.declare().status_code, 200)
            self.assertEqual(case.declare(kind='incorporation', value='2026-08-15T17:00:00-03:00').status_code, 200)
            values_fixture.HpcComparisonTests.register_fictional_hpc(case)
            first = case.analyze()
            selected = [{'id': a['id'], 'expected_version': a['version']}
                        for a in case.alerts()['items'] if a['rule_code'] == 'RN11']
            decision = case.decide(selected, state='confirmada', evidence_note='Cotejo enteramente ficticio de jornada.')
            self.assertEqual(decision.status_code, 200)
            case.dataset['version'] = decision.json()['dataset_version']
            case.change(2, 'G', '1')
            self.assertEqual(case.results(first)['RN11']['freshness'], 'requires_update')
            second = case.analyze()
            self.assertNotEqual(first['id'], second['id'])
            response = case.client.post(case.base() + '/practice-search', json={'family': 'all'}, headers=case.headers())
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['scope_counts'], {'included': 2, 'excluded': 2, 'indeterminate': 1})
            output = case.client.get(case.base() + '/export-provisional')
            self.assertEqual(output.status_code, 200)
            with ZipFile(BytesIO(output.content)) as archive:
                manifest = json.loads(archive.read('manifest.json'))
                self.assertEqual(manifest['kind'], 'provisional_review_export')
                self.assertIsNone(manifest['current_proposal_total_ars'])
                self.assertEqual(manifest['control_run']['id'], second['id'])
                self.assertTrue(archive.read('authorization_captures.jsonl'))
            history = case.client.get(case.base() + '/analysis-history').json()
            self.assertEqual(history['total'], 2)
            self.assertFalse(history['operational'])
        finally:
            case.tearDown()

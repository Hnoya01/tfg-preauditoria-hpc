"""Documentary evidence changes only dependent monetary components; fictional data."""

import hashlib
import unittest

from app.db import connect
from app.service import Problem
from tests import test_proposal_freshness as fixture
from tests.test_economic_evidence import PDF


class DocumentaryProposalTests(unittest.TestCase):
    INVOICE_TOTAL = 400
    SOURCE_DIFFERENCE = 1
    VALUES_CALCULATION = {'kind': 'nbu', 'ubMilliunits': 1000, 'catalogueSource': 'factor-ficticio.pdf', 'cataloguePage': 1}
    tearDown = fixture.ComponentFreshnessTests.tearDown
    headers = fixture.ComponentFreshnessTests.headers
    import_book = fixture.ComponentFreshnessTests.import_book
    spec = fixture.ComponentFreshnessTests.spec
    base = fixture.ComponentFreshnessTests.base
    parts = fixture.ComponentFreshnessTests.parts
    save_parts = fixture.ComponentFreshnessTests.save_parts
    history = fixture.ComponentFreshnessTests.history
    export = fixture.ComponentFreshnessTests.export

    def setUp(self):
        fixture.ComponentFreshnessTests.setUp(self)
        conn = connect(self.root)
        # The second unit uses another genuine tariff in the fictional original.
        conn.execute("UPDATE economic_verifications SET tariff_locator = 'hpc_catalog_tariffs.seq=2', rate_ars = '234.56' WHERE id = ?",
                      (self.second_verification_id,))
        conn.close()
        pdf = PDF.replace(b'%%EOF', b'% Fictional factor source\n%%EOF')
        response = self.client.post(f'/api/datasets/{self.dataset["id"]}/evidence-pdfs', content=pdf,
            headers=self.headers(**{'X-Expected-Version': str(self.dataset['version']), 'X-Source-Id': self.source['id'],
                'X-Source-Filename': 'factor-ficticio.pdf', 'X-Evidence-Category': 'nomenclator',
                'X-Provenance-Note': 'Anexo inventado para probar dependencias monetarias.',
                'X-Expected-SHA256': hashlib.sha256(pdf).hexdigest()}))
        self.assertEqual(response.status_code, 201, response.text)
        self.document_id = response.json()['id']
        self.dataset['version'] = response.json()['dataset_version']

    def cotejo(self, conclusion='matches', observed='1'):
        response = self.client.post(f'/api/datasets/{self.dataset["id"]}/sources/{self.source["id"]}/documentary-assessments',
            json={'expected_dataset_version': self.dataset['version'], 'provider': 'P1', 'code_complete': '123456', 'tariff_seq': 1,
                  'document_id': self.document_id, 'edition': 'Edición ficticia', 'page_number': 1,
                  'fragment': 'Código inventado 123456 en tabla ficticia de unidades.', 'observed_factor': observed,
                  'conclusion': conclusion, 'note': 'Observación ficticia del factor para ensayar dependencias.'}, headers=self.headers())
        self.assertEqual(response.status_code, 201, response.text)
        self.dataset['version'] = response.json()['dataset_version']
        return response.json()['id']

    def test_new_observation_affects_only_dependent_component_without_new_proposal(self):
        saved = self.save_parts()
        before = self.history()['versions'][0]
        self.cotejo()
        latest = self.history()
        current = latest['current_proposal']
        self.assertEqual(current['proposal_id'], saved['id'])
        self.assertEqual(current['amount_ars'], '0.00')  # second component is a known zero
        self.assertEqual(current['current_component_count'], 1)
        self.assertEqual(current['affected_component_count'], 1)
        self.assertIn('documentary_assessment_changed', current['components'][0]['invalid_reasons'])
        self.assertEqual(latest['versions'][0], before)
        self.assertEqual(len(latest['versions']), 1)
        self.assertEqual(self.export()[0]['current_proposal_total_ars'], '0.00')

    def test_saved_match_is_traced_and_later_difference_blocks_save(self):
        cotejo_id = self.cotejo()
        self.save_parts()
        history = self.history()
        self.assertEqual(history['current_proposal']['components'][0]['documentary_assessment_id_at_save'], cotejo_id)
        self.assertEqual(history['current_proposal']['state'], 'current')
        self.cotejo(conclusion='differs', observed='2')
        self.assertEqual(self.history()['current_proposal']['state'], 'partially_current')
        with self.assertRaises(Problem) as blocked:
            self.save_parts()
        self.assertEqual(blocked.exception.status, 409)
        self.assertEqual(len(self.history()['versions']), 1)

"""Fictional page comparisons are read-only and separate from RN14 decisions."""
import unittest
from unittest.mock import patch
from tests import test_economic_applicability as fixture
from app.db import connect
from app.hpc_values import save_value_version
from app.board_values import page_comparisons

class BoardValueTests(unittest.TestCase):
    def setUp(self):self.f=fixture.EconomicApplicabilityTests();self.f.setUp()
    def tearDown(self):self.f.tearDown()
    def search(self):
        r=self.f.client.post(self.f.base()+'/practice-search',json={},headers=self.f.headers())
        self.assertEqual(r.status_code,200,r.text);return r.json()
    def test_original_conditional_columns_match_comparison_without_domain_writes(self):
        c=connect(self.f.root)
        tables=('control_runs','row_economic_references','proposal_versions','review_decisions')
        before={t:c.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in tables}
        with patch('app.board_values.source_db',wraps=__import__('app.values_v1',fromlist=['source_db']).source_db) as load:
            page=self.search();self.assertEqual(load.call_count,1)
        row=next(r for r in page['items'] if r['source_row']==3)
        ref=row['reference_comparison']
        self.assertEqual(ref['recorded_amount'],'15.00');self.assertIsNone(ref['declared_currency']);self.assertIsNone(ref['declared_unit'])
        self.assertEqual(ref['candidate_total_if_ars_and_same_unit'],'30.00');self.assertEqual(ref['difference_ars_if_comparable'],'2.00')
        self.assertFalse(page['analysis_started']);self.assertEqual({t:c.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in tables},before)
        self.assertIsNone(row.get('proposed_debit'));c.close()
    def test_documented_version_is_same_candidate_and_missing_scope_never_guesses(self):
        f=self.f;c=connect(f.root)
        result=save_value_version(c,f.root,f.digest,f.dataset['id'],f.source_id,
            expected_dataset_version=f.dataset['version'],tariff_seq=1,code='123456',amount_ars='14.00',
            unit_label='por práctica',effective_from='2026-08-16',document_id=f.agreement_id,page_number=1,
            excerpt='Valor ficticio de catorce ARS por práctica',reason='Cambio ficticio para comprobar columnas de bandeja')
        f.dataset['version']=result['dataset_version'];c.close()
        row=next(r for r in self.search()['items'] if r['source_row']==3)
        self.assertEqual(row['reference_comparison']['difference_ars_if_comparable'],'4.00')
        self.assertEqual(row['reference_comparison']['declared_currency'],'ARS')
        self.assertEqual(row['reference_comparison']['declared_unit'],'por práctica')
        with patch('app.board_values.provider_basis',return_value=None):
            ref=self.search()['items'][0]['reference_comparison'];self.assertEqual(ref['status'],'hpc_provider_scope_missing');self.assertIsNone(ref['recorded_amount'])
    def test_closed_and_unknown_references_have_no_numeric_fallback(self):
        f=self.f;c=connect(f.root)
        rows=[{'source_row':2,'code':'NO-EXISTE','quantity':1,'disposition':'included','practice_date':'2026-08-15','total_ars':'30.00'}]
        c.execute('BEGIN')
        result=page_comparisons(c,f.root,f.dataset['id'],f.batch,rows,'Hoja1')
        self.assertTrue(c.in_transaction);self.assertEqual(result[2]['status'],'no_exact_hpc_tariff');self.assertIsNone(result[2]['recorded_amount'])
        self.assertEqual(page_comparisons(c,f.root,f.dataset['id'],f.batch,rows,'Hoja1',closed=True)[2]['status'],'closed_revision_not_compared')
        c.rollback();c.close()
    def test_exploratory_filter_precedes_pagination_and_keeps_control_state_independent(self):
        f=self.f
        with patch('app.board_values.source_db',wraps=__import__('app.values_v1',fromlist=['source_db']).source_db) as load:
            response=f.client.post(f.base()+'/practice-search',json={'reference_comparison_state':'differences','limit':1},headers=f.headers())
            self.assertEqual(response.status_code,200,response.text);data=response.json()
            self.assertEqual(load.call_count,1)
        self.assertEqual(data['filtered_total'],1);self.assertEqual(data['items'][0]['source_row'],3)
        self.assertEqual(data['items'][0]['reference_comparison']['status'],'numeric_above_candidate')
        self.assertEqual(data['items'][0]['patient_group_total'],1)
        next_page=f.client.post(f.base()+'/practice-search',json={'reference_comparison_state':'differences','offset':1,'limit':1},headers=f.headers()).json()
        self.assertEqual(next_page['filtered_total'],1);self.assertEqual(next_page['items'],[])
        equal=f.client.post(f.base()+'/practice-search',json={'reference_comparison_state':'equal'},headers=f.headers()).json()
        self.assertEqual([r['source_row'] for r in equal['items']],[2])
        invalid=f.client.post(f.base()+'/practice-search',json={'reference_comparison_state':'debitar'},headers=f.headers())
        self.assertEqual(invalid.status_code,422)
    def test_declared_links_stay_separate_from_numeric_comparison(self):
        from app.hpc_catalog_links import CatalogLinks
        f=self.f;c=connect(f.root)
        rows=[{'source_row':99,'code':'180104','quantity':20,'disposition':'included','practice_date':'2026-08-15','total_ars':'999.00'}]
        declared={'status':'declared_hpc_link_pending_verification','equivalence_verified':False,'applied':False,'candidates':[{'recorded_amount':'15.00'}]}
        with patch.object(CatalogLinks,'suggestions',return_value=declared), patch.object(CatalogLinks,'comparison',return_value={'status':'related_dimensions_or_document_unverified','difference_ars_if_comparable':None}):
            result=page_comparisons(c,f.root,f.dataset['id'],f.batch,rows,'Hoja1')[99]
        self.assertEqual(result['related_hpc_references'],declared)
        self.assertEqual(result['status'],'no_exact_hpc_tariff');self.assertIsNone(result['recorded_amount'])
        self.assertIsNone(result['difference_ars_if_comparable']);self.assertIsNone(result['candidate_total_if_ars_and_same_unit'])
        c.close()

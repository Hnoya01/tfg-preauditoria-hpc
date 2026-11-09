"""Focused HPC delivery checks, retaining the original synthetic runner barriers."""
import json
import unittest
from . import run_synthetic_tests as runner

MODULES = ['tests.test_csv_validity', 'tests.test_authorization_signals', 'tests.test_sheet_correspondence', 'tests.test_hpc_csv_intake', 'tests.test_authorization_catalog_candidates', 'tests.test_sync_intake', 'tests.test_hpc_sync_adapter', 'tests.test_authorization_imports', 'tests.test_authorization_matching', 'tests.test_authorization_assessment', 'tests.test_authorization_controls', 'tests.test_verified_display_nomenclature', 'tests.test_calculated_nomenclature', 'tests.test_agreement_declarations', 'tests.test_hpc_catalog_links', 'tests.test_board_values', 'tests.test_hpc_percentage_local', 'tests.test_local_hpc', 'tests.test_document_filters', 'tests.test_row_documents', 'tests.test_hpc_value_status', 'tests.test_hpc_percentage', 'tests.test_effective_hpc_values', 'tests.test_p03', 'tests.test_hpc_comparison', 'tests.test_economic_applicability',
           'tests.test_hpc_values', 'tests.test_economic_evidence', 'tests.test_sheet_review',
           'tests.test_observation_workflow', 'tests.test_integrated_journey',
           'tests.test_practice_families', 'tests.test_practice_board']
EXCLUDED = {'tests.test_economic_applicability.EconomicApplicabilityTests.'
            'test_closed_zip_is_unchanged_and_successor_does_not_inherit_applicability':
            'Requires repository Git metadata absent from the 717c81a source ZIP.'}


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def main():
    original = unittest.defaultTestLoader.discover
    def selection(*args, **kwargs):
        cases = list(flatten(unittest.defaultTestLoader.loadTestsFromNames(MODULES)))
        chosen = [case for case in cases if case.id() not in EXCLUDED]
        (runner.ROOT / '.test-results' / 'hpc-delivery-selection.json').write_text(
            json.dumps({'selected': [case.id() for case in chosen], 'excluded': EXCLUDED}, indent=2),
            encoding='utf-8')
        return unittest.TestSuite(chosen)
    unittest.defaultTestLoader.discover = selection
    try:
        return runner.main()
    finally:
        unittest.defaultTestLoader.discover = original

if __name__ == '__main__':
    raise SystemExit(main())

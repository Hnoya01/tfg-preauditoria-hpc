"""Run the R22 synthetic board checks with writes confined to this copy."""
from pathlib import Path
import os, sys, tempfile, unittest
ROOT=Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0,str(ROOT))
from scripts import run_synthetic_tests
# The application virtual environment can live outside this isolated source copy.
# Extend only read access to that interpreter; keep all writes inside ROOT.
source=Path(run_synthetic_tests.__file__).read_text(encoding='utf-8').replace(
    'allowed_reads = (ROOT, Path(sys.base_prefix).resolve())',
    'allowed_reads = (ROOT, Path(sys.base_prefix).resolve(), Path(sys.prefix).resolve())')
modules=['tests.test_csv_budget','tests.test_practice_board','tests.test_board_values','tests.test_column_board','tests.test_row_decisions','tests.test_invoice_handoff','tests.test_invoice_audit','tests.test_csv_validity','tests.test_csv_reviews','tests.test_csv_shortfall','tests.test_csv_order_units','tests.test_hpc_csv_intake','tests.test_authorization_reinterpretation']
modules.extend(['tests.test_r22','tests.test_revisions','tests.test_authorization_controls'])
focused='--unidades' in sys.argv
if focused:
    modules=['tests.test_csv_order_units','tests.test_authorization_reinterpretation.ReinterpretationTests.test_preexisting_v3_with_two_units_requires_explicit_reinterpretation',
             'tests.test_csv_validity','tests.test_csv_budget','tests.test_csv_shortfall']
if '--cierres' in sys.argv:
    modules=['tests.test_invoice_audit','tests.test_r22','tests.test_processing.ProcessingTests.test_progress_publication_and_idempotent_receipt_and_result_reuse','tests.test_processing.ProcessingTests.test_version_or_permission_change_prevents_publication']
loader=unittest.TestLoader()
unittest.defaultTestLoader.discover=lambda *a,**k:loader.loadTestsFromNames(modules)
# Preload test dependencies before the audit hook to avoid threading module-loader
# work through Windows path resolution for every import.
for name in modules:__import__('.'.join(name.split('.')[:2]))
target=ROOT/'.tmp';target.mkdir(exist_ok=True)
os.environ['TMP']=os.environ['TEMP']=os.environ['TMPDIR']=str(target)
tempfile.tempdir=str(target)
folder='.test-results-r22-unidades' if focused else '.test-results-r22'
if '--cierres' in sys.argv:folder='.test-results-r22-cierres'
source=source.replace("output = ROOT / '.test-results'", f'output = ROOT / {folder!r}')
exec(compile(source,run_synthetic_tests.__file__,'exec'),run_synthetic_tests.__dict__)
raise SystemExit(run_synthetic_tests.main())

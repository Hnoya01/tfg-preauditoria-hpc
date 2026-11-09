"""Run the R19 synthetic board checks with writes confined to this copy."""
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
modules=['tests.test_csv_budget','tests.test_practice_board','tests.test_board_values','tests.test_column_board','tests.test_row_decisions','tests.test_invoice_handoff','tests.test_invoice_audit']
loader=unittest.TestLoader()
unittest.defaultTestLoader.discover=lambda *a,**k:loader.loadTestsFromNames(modules)
# Preload test dependencies before the audit hook to avoid threading module-loader
# work through Windows path resolution for every import.
for name in modules:__import__(name)
target=ROOT/'.tmp';target.mkdir(exist_ok=True)
os.environ['TMP']=os.environ['TEMP']=os.environ['TMPDIR']=str(target)
tempfile.tempdir=str(target)
source=source.replace("output = ROOT / '.test-results'", "output = ROOT / '.test-results-r19'")
exec(compile(source,run_synthetic_tests.__file__,'exec'),run_synthetic_tests.__dict__)
raise SystemExit(run_synthetic_tests.main())

"""Run synthetic unittest suite with write isolation and machine-readable results."""
import json
import mimetypes
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]

def main():
    if Path(sys.prefix).resolve() == Path(sys.base_prefix).resolve():
        raise SystemExit("Use a dedicated virtual environment.")
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    for key in list(os.environ):
        if key.startswith('TFG_'):
            del os.environ[key]
    temp = ROOT / '.tmp'
    temp.mkdir(exist_ok=True)
    output = ROOT / '.test-results'
    output.mkdir(exist_ok=True)
    os.environ['TMP'] = os.environ['TEMP'] = os.environ['TMPDIR'] = str(temp)
    os.environ['TFG_DATA_DIR'] = str(temp / 'synthetic-default-data')
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    os.environ.pop('PYTHONPATH', None)
    # Fail on Python file reads outside the copy and interpreter installation.
    # Native subprocesses are not sandboxed by this hook; recovery helpers were reviewed.
    allowed_reads = (ROOT, Path(sys.base_prefix).resolve())
    def inside(value, roots):
        if isinstance(value, (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(value)).resolve()
            return any(path.is_relative_to(base) for base in roots)
        return True
    def audit(event, args):
        if event == 'open':
            path, mode, flags = args
            writing = (isinstance(mode, str) and any(c in mode for c in 'wax+')) or bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            if not inside(path, (ROOT,) if writing else allowed_reads):
                raise PermissionError('Synthetic suite attempted external file access')
        elif event in ('os.remove','os.rmdir','os.mkdir','os.chmod'):
            if not inside(args[0], (ROOT,)):
                raise PermissionError('Synthetic suite attempted external mutation')
        elif event in ('os.rename','os.replace'):
            if not all(inside(p, (ROOT,)) for p in args[:2]):
                raise PermissionError('Synthetic suite attempted external move')
    sys.addaudithook(audit)
    if sys.platform == 'linux':
        # Use Python's built-in MIME table, not host-specific /etc files.
        # init([]) alone still reads knownfiles on first initialization.
        # init() also rebuilds a table initialized earlier in this process.
        mimetypes.knownfiles = []
        mimetypes.init()
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'), top_level_dir=str(ROOT))
    with (output / 'python.log').open('w', encoding='utf-8') as log:
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    record = {'platform':sys.platform, 'python':sys.version.split()[0], 'run':result.testsRun,
              'passed':result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped)-len(result.expectedFailures)-len(result.unexpectedSuccesses),
              'failed':[t.id() for t,_ in result.failures], 'errors':[t.id() for t,_ in result.errors],
              'skipped':[{'test':t.id(),'reason':reason} for t,reason in result.skipped],
              'expected_failures':[t.id() for t,_ in result.expectedFailures],
              'unexpected_successes':[t.id() for t in result.unexpectedSuccesses]}
    (output / 'python-summary.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    print(json.dumps(record))
    return 0 if result.wasSuccessful() else 1

if __name__ == '__main__':
    raise SystemExit(main())

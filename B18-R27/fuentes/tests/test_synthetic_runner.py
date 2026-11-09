"""Exercise the real runner in fresh processes without recursively discovering tests."""
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SyntheticRunnerTests(unittest.TestCase):
    def run_probe(self, preinitialized):
        program = textwrap.dedent(r'''
            import io
            import mimetypes
            from pathlib import Path
            import sys
            import unittest
            from unittest.mock import patch
            from scripts import run_synthetic_tests as runner

            if sys.argv[1] == 'warm' and sys.platform == 'linux':
                mimetypes.knownfiles = []
                mimetypes.init()
                mimetypes.add_type('application/x-wrong', '.html')
                # A prior caller's host paths must not survive initialization.
                mimetypes.knownfiles = ['/etc/mime.types']

            class Probe(unittest.TestCase):
                def test_mime_consumers_and_isolation(self):
                    from openpyxl import Workbook, load_workbook
                    from starlette.applications import Starlette
                    from starlette.routing import Mount
                    from starlette.staticfiles import StaticFiles
                    from starlette.testclient import TestClient

                    book = Workbook()
                    book.active['A1'] = 'FICTICIO'
                    stream = io.BytesIO()
                    book.save(stream)
                    stream.seek(0)
                    loaded = load_workbook(stream)
                    self.assertEqual(loaded.active['A1'].value, 'FICTICIO')
                    loaded.close()
                    app = Starlette(routes=[Mount('/', StaticFiles(directory=runner.ROOT / 'web'))])
                    with TestClient(app) as client:
                        for filename, allowed in (
                            ('index.html', ('text/html',)),
                            ('style.css', ('text/css',)),
                            ('app.js', ('text/javascript', 'application/javascript')),
                        ):
                            response = client.get('/' + filename)
                            self.assertEqual(response.status_code, 200)
                            self.assertIn(response.headers['content-type'].split(';')[0], allowed)
                    self.assertEqual(mimetypes.guess_type('fictional.pdf')[0], 'application/pdf')
                    self.assertEqual(mimetypes.guess_type('fictional.json')[0], 'application/json')
                    zip_type = mimetypes.guess_type('fictional.zip')[0]
                    if sys.platform == 'win32':
                        # Windows registry mapping: https://bugs.python.org/issue41738
                        self.assertIn(zip_type, ('application/zip', 'application/x-zip-compressed'))
                    else:
                        self.assertEqual(zip_type, 'application/zip')
                    # Nonexistent synthetic paths: no private file is read even if
                    # the hook regresses. Require the hook's error, not an OS error.
                    outside = runner.ROOT.parent / 'tfg-synthetic-forbidden' / 'probe'
                    for mode in ('rb', 'wb'):
                        with self.assertRaisesRegex(PermissionError, 'Synthetic suite attempted external file access'):
                            with outside.open(mode):
                                pass
                    with self.assertRaisesRegex(PermissionError, 'Synthetic suite attempted external mutation'):
                        outside.unlink()
                    # The interpreter is readable but must not become writable.
                    with self.assertRaisesRegex(PermissionError, 'Synthetic suite attempted external file access'):
                        with (Path(sys.base_prefix) / 'tfg-synthetic-forbidden' / 'probe').open('wb'):
                            pass

            suite = unittest.defaultTestLoader.loadTestsFromTestCase(Probe)
            # Only discovery and result destination are replaced; main installs
            # its actual isolation hook and MIME setup before running the probe.
            original_open = Path.open
            def result_open(path, *args, **kwargs):
                if path.parent == runner.ROOT / '.test-results':
                    path = Path(sys.argv[2]) / path.name
                return original_open(path, *args, **kwargs)
            with patch.object(Path, 'open', result_open), patch.object(
                runner.unittest.defaultTestLoader, 'discover', return_value=suite
            ):
                raise SystemExit(runner.main())
        ''')
        # Keep the real ROOT/allowlist; redirect only the child result files
        # into an allowed temporary directory so the parent log stays intact.
        from tests.temp_support import TemporaryDirectory
        with TemporaryDirectory(dir=ROOT / '.tmp') as temp:
            result = subprocess.run(
                [sys.executable, '-B', '-c', program, 'warm' if preinitialized else 'cold', temp],
                cwd=ROOT, env={k: v for k, v in os.environ.items() if k != 'PYTHONPATH'},
                capture_output=True, text=True, timeout=60,
            )
            log = Path(temp) / 'python.log'
            self.assertEqual(result.returncode, 0,
                             result.stdout + result.stderr + (log.read_text() if log.exists() else ''))

    def test_fresh_process_mime_consumers_and_file_isolation(self):
        self.run_probe(False)

    def test_preinitialized_process_mime_consumers_and_file_isolation(self):
        self.run_probe(True)

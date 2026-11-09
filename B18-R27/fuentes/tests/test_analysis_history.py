"""MD07: rejected calculations remain historical, never operational results."""
import unittest

from app.controls import run_controls
from app.db import connect
from app.review import _latest_run
from app.service import Problem
from tests import test_p05 as fixture


class AnalysisHistoryTests(unittest.TestCase):
    setUp = fixture.P05Tests.setUp
    tearDown = fixture.P05Tests.tearDown
    headers = fixture.P05Tests.headers
    import_book = fixture.P05Tests.import_book
    run_url = fixture.P05Tests.run_url

    def history_url(self):
        return f'/api/datasets/{self.dataset["id"]}/batches/{self.batch}/analysis-history'

    def test_capture_precedes_calculation_and_rejected_result_survives_restart(self):
        c = connect(self.root)
        c.execute('UPDATE datasets SET version=version+1 WHERE id=?', (self.dataset['id'],))
        version = self.dataset['version'] + 1
        # Change a dependency so this is a fresh computation, not reuse.
        c.execute("UPDATE invoice_imports SET period='2026-07' WHERE batch_id=?", (self.batch,))
        captured = []
        def inspect(stage, done, total):
            if stage == 'preparing' and done == 0 and not captured:
                other = connect(self.root)
                try:
                    captured.extend(other.execute("SELECT id FROM analysis_history WHERE state='captured'").fetchall())
                finally:
                    other.close()
        def change():
            other = connect(self.root)
            other.execute('UPDATE datasets SET version=version+1 WHERE id=?', (self.dataset['id'],))
            other.close()
        try:
            with self.assertRaises(Problem) as err:
                run_controls(c, self.digest, self.dataset['id'], self.batch, version, progress=inspect, after_prepare=change)
            self.assertEqual(err.exception.status, 409)
            self.assertEqual(len(captured), 1)
            self.assertEqual(_latest_run(c, self.run['snapshot']['revision_id'])['id'], self.run['id'])
            self.assertEqual(c.execute('SELECT count(*) FROM control_runs').fetchone()[0], 1)
        finally:
            c.close()
        response = self.client.get(self.history_url())
        self.assertEqual(response.status_code, 200, response.text)
        rejected = next(x for x in response.json()['items'] if x['state'] == 'historical')
        detail_url = f'/api/datasets/{self.dataset["id"]}/analysis-history/{rejected["id"]}'
        detail = self.client.get(detail_url).json()
        self.assertFalse(detail['operational'])
        self.assertEqual(detail['snapshot']['period'], '2026-07')
        self.assertGreater(len(detail['results']), 0)
        self.assertEqual(self.client.get(detail_url.replace(self.dataset['id'], 'other')).status_code, 404)
        c = connect(self.root)
        c.execute('DELETE FROM sessions WHERE token_hash=?', (self.digest,))
        c.close()
        self.assertEqual(self.client.get(detail_url).status_code, 401)

    def test_successful_publication_links_capture_and_reuse_does_not_duplicate(self):
        page = self.client.get(self.history_url()).json()
        self.assertEqual(page['total'], 1)
        self.assertEqual(page['items'][0]['state'], 'published')
        self.assertEqual(page['items'][0]['published_run_id'], self.run['id'])
        c = connect(self.root)
        try:
            _, created = run_controls(c, self.digest, self.dataset['id'], self.batch, self.dataset['version'])
            self.assertFalse(created)
            self.assertEqual(c.execute('SELECT count(*) FROM analysis_history').fetchone()[0], 1)
        finally:
            c.close()

    def test_historical_result_pagination_reaches_full_supported_import_size(self):
        page = self.client.get(self.history_url()).json()
        identity = page['items'][0]['id']
        url = f'/api/datasets/{self.dataset["id"]}/analysis-history/{identity}'
        response = self.client.get(url, params={'offset': 1_000_100, 'limit': 100})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['results'], [])
        for offset in (-1, 2**63):
            self.assertEqual(self.client.get(url, params={'offset': offset}).status_code, 422)


class HistoryLeaseTests(unittest.TestCase):
    def test_prepared_persistence_uses_publication_lease(self):
        import time
        from unittest.mock import patch
        from app import analysis_history
        from app.processing import execute
        from tests import test_processing as fixture_processing
        case = fixture_processing.ProcessingTests()
        case.setUp()
        try:
            queued = case.enqueue()
            job = case.claim()
            clock = [time.time()]
            original = analysis_history.save_prepared
            def slow_persistence(conn, identity, staged):
                clock[0] += 16  # More than evaluating lease, less than publishing lease.
                original(conn, identity, staged)
            with patch('app.processing.time.time', side_effect=lambda: clock[0]), patch(
                    'app.analysis_history.save_prepared', side_effect=slow_persistence):
                execute(case.root, job, heartbeat_interval=60)
            self.assertEqual(case.status(queued['id'])['state'], 'completed')
        finally:
            case.tearDown()


class HistoryMigrationTests(unittest.TestCase):
    def test_v18_upgrade_keeps_verified_backup_and_existing_rows(self):
        import sqlite3
        from pathlib import Path
        from app.db import MIGRATIONS, backup_before_upgrade, migrate
        from tests.temp_support import TemporaryDirectory
        with TemporaryDirectory(dir='.tmp') as directory:
            root = Path(directory)
            c = connect(root)
            try:
                migrate(c, migrations=tuple(m for m in MIGRATIONS if m[0] <= 18))
                self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0], 18)
                from app.security import create_user
                from tests.test_p02 import PASSWORD
                user = create_user(c, 'migration-fixture', PASSWORD, 'admin')
                c.execute('INSERT INTO datasets VALUES(?,?,?,?,?)',
                          ('migration-ds', 'FICTICIO migration', 7, user, '2026-10-27'))
                with self.assertRaises(RuntimeError):
                    migrate(c)
                backup = backup_before_upgrade(c, root)
                self.assertEqual(migrate(c, allow_existing_upgrade=True), MIGRATIONS[-1][0])
                self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                self.assertEqual(c.execute("SELECT version FROM datasets WHERE id='migration-ds'").fetchone()[0], 7)
                self.assertIsNone(c.execute('PRAGMA foreign_key_check').fetchone())
                saved = sqlite3.connect(backup / 'app.sqlite3')
                try:
                    self.assertEqual(saved.execute('PRAGMA user_version').fetchone()[0], 18)
                    self.assertEqual(saved.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                    self.assertEqual(saved.execute("SELECT version FROM datasets WHERE id='migration-ds'").fetchone()[0], 7)
                    self.assertIsNone(saved.execute("SELECT name FROM sqlite_master WHERE name='analysis_history'").fetchone())
                finally:
                    saved.close()
            finally:
                c.close()

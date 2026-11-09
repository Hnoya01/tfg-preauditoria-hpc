"""RNF07/08: authenticated WAL reads while a separate process owns the writer."""

from __future__ import annotations

from datetime import timedelta
import multiprocessing
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from app.db import connect
from app.security import now
from tests import test_p05 as fixture
from tests.sqlite_writer import hold_writer


class ReadContentionTests(unittest.TestCase):
    setUp = fixture.P05Tests.setUp
    tearDown = fixture.P05Tests.tearDown
    headers = fixture.P05Tests.headers
    import_book = fixture.P05Tests.import_book
    run_url = fixture.P05Tests.run_url

    def test_reads_survive_writer_and_mutation_reports_contention(self):
        old_activity = (now() - timedelta(minutes=2)).isoformat(timespec="seconds")
        conn = connect(self.root)
        conn.execute("UPDATE sessions SET last_active_at = ? WHERE token_hash = ?",
                     (old_activity, self.digest))
        conn.close()
        ctx = multiprocessing.get_context("spawn")
        ready, release = ctx.Event(), ctx.Event()
        worker = ctx.Process(target=hold_writer, args=(str(self.root.resolve()), ready, release))
        worker.start()
        try:
            self.assertTrue(ready.wait(10), "Separate writer did not acquire the transaction")
            started = time.monotonic()
            base = f'/api/datasets/{self.dataset["id"]}/batches'
            for url in ("/api/me", base, f'{base}/{self.batch}/control-runs',
                        f'{base}/{self.batch}/alerts'):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200, response.text)
            response = self.client.post(f'{base}/{self.batch}/practice-search', json={}, headers=self.headers())
            self.assertEqual(response.status_code, 200, response.text)
            page=response.json()
            selected=[{'id':a['id'],'expected_version':a['version']} for row in page['items'] for a in row['alerts'] if a['current']]
            preview=self.client.post(f'{base}/{self.batch}/decision-preview',headers=self.headers(),json={
                'expected_dataset_version':page['dataset_version'],'expected_revision_version':page['batch']['revision_version'],
                'items':selected})
            self.assertEqual(preview.status_code,200,preview.text)
            self.assertEqual(self.client.get(f'{base}/{self.batch}/rows/2/practice-detail').status_code, 200)
            self.assertLess(time.monotonic() - started, 3.0)
            # Use no-wait mutation connections in this test to inspect the busy
            # response without waiting the production contention timeout.
            with patch("app.api.connect", side_effect=lambda root: connect(root, timeout=0)):
                blocked = self.client.patch(f'/api/datasets/{self.dataset["id"]}',
                    json={"label": "Cambio ficticio bajo contención", "expected_version": self.dataset["version"]},
                    headers=self.headers())
            self.assertEqual(blocked.status_code, 503, blocked.text)
            self.assertEqual(blocked.headers["Retry-After"], "1")
            conn = connect(self.root)
            try:
                self.assertEqual(conn.execute("SELECT last_active_at FROM sessions WHERE token_hash = ?",
                                               (self.digest,)).fetchone()[0], old_activity)
            finally:
                conn.close()
        finally:
            release.set()
            worker.join(10)
            if worker.is_alive():
                worker.terminate()
                worker.join(5)
        self.assertEqual(worker.exitcode, 0)
        self.assertEqual(self.client.get("/api/me").status_code, 200)
        conn = connect(self.root)
        try:
            self.assertGreater(conn.execute("SELECT last_active_at FROM sessions WHERE token_hash = ?",
                                             (self.digest,)).fetchone()[0], old_activity)
            self.assertEqual(conn.execute("SELECT version FROM datasets WHERE id = ?",
                                           (self.dataset["id"],)).fetchone()[0], self.dataset["version"])
        finally:
            conn.close()

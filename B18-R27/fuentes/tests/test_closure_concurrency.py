"""Deterministic synchronization/fault coverage for the isolated closure assay."""
import json
from pathlib import Path
import queue
import sqlite3
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

from tests.closure_concurrency import concurrent_probe, supervise, ProbeFailure


class ClosureProbeTests(unittest.TestCase):
    def evidence(self):
        path = Path('.test-results') / ('closure-probe-' + uuid4().hex)
        path.mkdir(parents=True)
        return path

    def test_backup_work_has_no_worker_deadline_or_early_commit(self):
        # Logical workload varies without timing-dependent sleeps. Inspect the
        # actual release wait, not a longer wall-clock tolerance.
        for steps in (0, 25_000):
            with self.subTest(steps=steps):
                release_waits = []; committed = []; events = []; result = []
                real_event = threading.Event
                class ReleaseEvent:
                    def __init__(self): self.event = real_event()
                    def set(self): return self.event.set()
                    def is_set(self): return self.event.is_set()
                    def wait(self, timeout=None):
                        release_waits.append(timeout)
                        return self.event.wait(timeout)
                def close_one(identity, prepared):
                    prepared(); committed.append(identity)
                    return 'closed' if identity == 'a' else 409
                def backup():
                    for _ in range(steps):
                        self.assertEqual(committed, [])
                    self.assertEqual(committed, [])
                    return {'snapshot': 'FICTICIO'}
                # Patching the module's Event would also affect Thread internals;
                # construct workers before patching via a saved Thread factory.
                threads = queue.Queue()
                original_thread = threading.Thread
                def thread_factory(*args, **kwargs):
                    with patch('threading.Event', real_event):
                        t = original_thread(*args, **kwargs)
                    threads.put(t); return t
                with patch('tests.closure_concurrency.threading.Event', ReleaseEvent), patch('tests.closure_concurrency.threading.Thread', thread_factory):
                    result = concurrent_probe(['a', 'b'], close_one, backup,
                        lambda stage, **fields: events.append(stage))
                self.assertEqual(release_waits, [None, None])
                self.assertEqual(sorted(committed), ['a', 'b'])
                self.assertEqual(sorted(str(s) for _, s in result['results']), ['409', 'closed'])
                self.assertLess(events.index('backup_finished'), events.index('release'))
                self.assertLess(events.index('release'), events.index('closed'))
                while not threads.empty(): self.assertFalse(threads.get().is_alive())

    def test_missing_signal_and_blocked_backup_are_bounded_with_diagnostics(self):
        for mode, stage in [('missing_signal', 'blocked_worker'), ('blocked_backup', 'blocked_backup')]:
            with self.subTest(mode=mode):
                directory = self.evidence()
                # Expiration is injected ONLY after the real blocked checkpoint;
                # the independent real 60s cap remains active if startup fails.
                def expire(trace):
                    return f'"stage": "{stage}"' in trace.read_text(encoding='utf-8')
                with self.assertRaises(ProbeFailure) as raised:
                    supervise({'mode':mode, 'held':str((directory/'held').resolve())}, directory, expired=expire)
                text = str(raised.exception)
                self.assertIn(stage, text); self.assertIn('global concurrency probe budget exhausted', text)
                self.assertIn('cleanup: None', text)
                self.assertNotIn('"stage": "closed"', text)
                # A Windows descendant's open handle prevents this replacement
                # until tree termination; on all platforms no publication occurs.
                held = directory/'held'
                if held.exists():
                    c = sqlite3.connect(held, timeout=1)
                    try:
                        c.execute('BEGIN EXCLUSIVE'); c.rollback()
                    finally:
                        c.close()
                    held.rename(directory/'released')

    def test_real_global_deadline_is_independent_of_checkpoint_injection(self):
        directory = self.evidence()
        with self.assertRaisesRegex(ProbeFailure, 'global concurrency probe budget exhausted') as raised:
            supervise({'mode':'missing_signal'}, directory, budget=0)
        self.assertIn('cleanup: None', str(raised.exception))

    def test_first_exception_is_preserved_and_workers_cancelled(self):
        for mode, first in [('worker_error','worker'), ('backup_error','backup'),
                            ('backup_error_blocked_cleanup','backup')]:
            with self.subTest(mode=mode):
                directory = self.evidence()
                with self.assertRaises(ProbeFailure) as raised:
                    supervise({'mode':mode, 'held':str((directory/'held').resolve())}, directory,
                        expired=lambda trace: '"stage": "cleanup_blocked"' in trace.read_text(encoding='utf-8'))
                records = [json.loads(line) for line in (directory/'trace.jsonl').read_text().splitlines()]
                errors = [r for r in records if r['stage']=='first_error']
                self.assertEqual(len(errors),1)
                self.assertIn(f'FICTICIO original {first} failure', errors[0]['detail'])
                self.assertTrue(next(r for r in records if r['stage']=='release')['cancelled'])
                self.assertFalse(any(r['stage']=='closed' for r in records))
                self.assertIn('cleanup: None',str(raised.exception))
                if mode.endswith('blocked_cleanup'):
                    self.assertIn('global concurrency probe budget exhausted',str(raised.exception))
                held=directory/'held'
                if held.exists():
                    c = sqlite3.connect(held, timeout=1)
                    try:
                        c.execute('BEGIN EXCLUSIVE'); c.rollback()
                    finally:
                        c.close()
                    held.rename(directory/'released')

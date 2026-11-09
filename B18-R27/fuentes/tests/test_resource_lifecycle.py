"""Deterministic resource failures; no permissive cleanup or timing workaround."""
from pathlib import Path
import sqlite3
import threading
import unittest
from unittest.mock import patch

from app.db import connect
from app.processing import ProcessingManager
from tests.temp_support import TemporaryDirectory


class ResourceLifecycleTests(unittest.TestCase):
    def test_configuration_failure_explicitly_closes_the_created_connection(self):
        original=sqlite3.connect;created=[]
        class FailingConnection(sqlite3.Connection):
            closed=False
            def execute(self,sql,*args,**kwargs):
                if sql=='PRAGMA journal_mode = WAL':raise sqlite3.OperationalError('FICTICIO configuration failure')
                return super().execute(sql,*args,**kwargs)
            def close(self):
                super().close();self.closed=True
        def factory(*args,**kwargs):
            connection=original(*args,**kwargs,factory=FailingConnection);created.append(connection);return connection
        with TemporaryDirectory(dir='.tmp') as directory:
            try:
                with patch('app.db.sqlite3.connect',side_effect=factory):
                    with self.assertRaisesRegex(sqlite3.OperationalError,'FICTICIO'):connect(Path(directory))
                self.assertEqual(len(created),1);self.assertTrue(created[0].closed)
                with self.assertRaises(sqlite3.ProgrammingError):created[0].execute('SELECT 1')
            finally:
                for connection in created:connection.close()

    def held_thread(self,worker):
        ready,release=threading.Event(),threading.Event()
        def held():
            ready.set();release.wait()
        with TemporaryDirectory(dir='.tmp') as directory:
            manager=ProcessingManager(Path(directory))
            target=threading.Thread(target=held)
            if worker:
                manager.worker=target;manager.start();target.start()
            else:manager.thread=target;manager.start()
            real_join=target.join
            try:
                self.assertTrue(ready.wait(5))
                # Inject an exhausted join without spending five seconds or
                # changing production timeouts. The actual thread remains live.
                with patch.object(target,'join',side_effect=lambda timeout:real_join(0)):
                    with self.assertRaisesRegex(RuntimeError,'shutdown incomplete'):manager.close()
                self.assertTrue(manager.stop.is_set());self.assertTrue(target.is_alive())
            finally:
                release.set();real_join(5)
                if worker:manager.thread.join(5)
                self.assertFalse(target.is_alive());self.assertFalse(manager.thread.is_alive())
                manager.close()

    def test_shutdown_does_not_report_completion_with_a_live_coordinator(self):self.held_thread(False)

    def test_shutdown_does_not_report_completion_with_a_live_worker(self):self.held_thread(True)

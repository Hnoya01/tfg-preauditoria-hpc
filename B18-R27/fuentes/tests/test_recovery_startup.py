"""Restored synthetic databases stay quarantined until explicit activation."""
import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import create_app
from app.db import connect
from app.security import current_session
from scripts.recovery_data import activate_quarantined, digest, restore_archive
from tests import test_recovery as fixture


class RecoveryStartupTests(unittest.TestCase):
    setUp = fixture.RecoveryTests.setUp
    tearDown = fixture.RecoveryTests.tearDown
    backup = fixture.RecoveryTests.backup

    def restored(self):
        _, sha, archive = self.backup()
        target = self.root / 'restored'
        restore_archive(archive, target, sha, self.source)
        return target

    def test_pending_startup_cannot_touch_database_or_start_workers(self):
        target = self.restored()
        before = digest(target / 'app.sqlite3')
        with patch('app.api.ProcessingManager') as manager:
            with self.assertRaisesRegex(RuntimeError, 'recuperaci'):
                with TestClient(create_app(target)):
                    pass
            manager.assert_not_called()
        self.assertEqual(digest(target / 'app.sqlite3'), before)
        with self.assertRaises(RuntimeError):
            connect(target)

    def test_activation_receipt_retries_after_commit_and_disables_workers(self):
        target = self.restored()
        with patch('scripts.recovery_data.os.replace', side_effect=OSError('FICTICIO: interrupted receipt write')):
            with self.assertRaises(OSError):
                activate_quarantined(target)
        with self.assertRaises(RuntimeError):
            connect(target)
        result = activate_quarantined(target)
        self.assertEqual(result['sessions_revoked'], 1)
        self.assertEqual(activate_quarantined(target), result)
        with patch('app.api.ProcessingManager') as manager:
            with TestClient(create_app(target)) as client:
                self.assertEqual(client.get('/api/health').status_code, 200)
            manager.assert_not_called()
        c = connect(target)
        try:
            self.assertIsNone(current_session(c, self.token))
            self.assertEqual(c.execute("SELECT count(*) FROM audit_events WHERE action='recovery_sessions_revoked'").fetchone()[0], 1)
        finally:
            c.close()

    def test_incomplete_restore_and_forged_receipt_stay_blocked(self):
        target = self.restored()
        ready = target / 'RECOVERY_READY.json'
        body = json.loads(ready.read_text())
        (target / 'RECOVERY_ACTIVATED.json').write_text(json.dumps({
            'manifest_sha256': body['manifest_sha256'], 'workers_enabled': False,
            'sessions_revoked': 1, 'activated_at': 'FICTICIO'}))
        with self.assertRaises(RuntimeError):
            connect(target)
        ready.unlink()
        with self.assertRaises(RuntimeError):
            connect(target)

    def test_unrestored_database_still_starts_normally(self):
        with patch('app.api.ProcessingManager') as manager:
            with TestClient(create_app(self.source)) as client:
                self.assertEqual(client.get('/api/health').status_code, 200)
            manager.return_value.start.assert_called_once()

    def test_interrupted_extraction_stays_quarantined(self):
        _, sha, archive = self.backup()
        target = self.root / 'incomplete'
        with patch('scripts.recovery_data.shutil.copyfileobj', side_effect=OSError('FICTICIO: interrupted extraction')):
            with self.assertRaises(OSError):
                restore_archive(archive, target, sha, self.source)
        self.assertTrue((target / 'RECOVERY_PENDING.json').exists())
        self.assertFalse((target / 'RECOVERY_READY.json').exists())
        with self.assertRaises(RuntimeError):
            connect(target)
        self.assertFalse((target / 'app.sqlite3').exists())

    def test_repeated_backup_restore_requires_a_new_activation(self):
        from scripts.recovery_data import make_backup, bundle_backup
        target = self.restored()
        first = activate_quarantined(target)
        _, sha = make_backup(target, self.root / 'second-backup', self.release, data_kind='synthetic')
        archive = self.root / 'second.zip'
        bundle_backup(self.root / 'second-backup', archive)
        second = self.root / 'second-restore'
        restore_archive(archive, second, sha, target)
        with self.assertRaises(RuntimeError):
            connect(second)
        activation = activate_quarantined(second)
        self.assertNotEqual(first['manifest_sha256'], activation['manifest_sha256'])
        self.assertEqual(activation['sessions_revoked'], 0)
        c = connect(second)
        c.close()


"""Concurrent commits must not produce mixed alert detail or leak revoked data."""
import unittest
from unittest.mock import patch

from app import review
from app.db import connect
from app.service import Problem
from tests import test_p05 as fixture


class AlertConsistencyTests(unittest.TestCase):
    setUp = fixture.P05Tests.setUp
    tearDown = fixture.P05Tests.tearDown
    headers = fixture.P05Tests.headers
    import_book = fixture.P05Tests.import_book
    run_url = fixture.P05Tests.run_url
    alerts = fixture.P05Tests.alerts

    def test_concurrent_change_rejects_detail_without_mixed_versions(self):
        alert_id = self.alerts()['items'][0]['id']
        c = connect(self.root)
        original = review._result
        def changed(*args):
            other = connect(self.root)
            try:
                other.execute('UPDATE datasets SET version=version+1 WHERE id=?', (self.dataset['id'],))
            finally:
                other.close()
            return original(*args)
        try:
            with patch('app.review._result', side_effect=changed):
                with self.assertRaises(Problem) as error:
                    review.alert_detail(c, self.digest, self.dataset['id'], alert_id)
            self.assertEqual(error.exception.status, 409)
            self.assertFalse(c.in_transaction)
        finally:
            c.close()

    def test_revocation_after_summary_blocks_detail(self):
        alert_id = self.alerts()['items'][0]['id']
        original = review._decision_status
        def revoked(*args):
            other = connect(self.root)
            try:
                other.execute('DELETE FROM sessions WHERE token_hash=?', (self.digest,))
            finally:
                other.close()
            return original(*args)
        with patch('app.review._decision_status', side_effect=revoked):
            r = self.client.get(f'/api/datasets/{self.dataset["id"]}/alerts/{alert_id}')
        self.assertEqual(r.status_code, 401)
        self.assertNotIn('invoice', r.json())

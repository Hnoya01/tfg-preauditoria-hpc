"""Compact page summaries must agree with the existing B02 evidence and writes."""

import unittest
from app.db import connect
from tests import test_authorization_matching as matching
from tests.test_p02 import book


class SheetCorrespondenceTests(unittest.TestCase):
    setUp=matching.MatchingTests.setUp
    tearDown=matching.MatchingTests.tearDown
    headers=matching.MatchingTests.headers
    import_book=matching.MatchingTests.import_book
    run_url=matching.MatchingTests.run_url
    alerts=matching.MatchingTests.alerts
    decide=matching.MatchingTests.decide
    url=matching.MatchingTests.url
    stage=matching.MatchingTests.stage
    preview=matching.MatchingTests.preview
    confirm=matching.MatchingTests.confirm
    base=matching.MatchingTests.base
    add_capture=matching.MatchingTests.add_capture
    select=matching.MatchingTests.select
    evidence=matching.MatchingTests.evidence
    link=matching.MatchingTests.link

    def page(self):
        response=self.client.post(self.base()+'/practice-search',json={},headers=self.headers())
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def test_pending_sources_partial_conflict_and_manual_link_remain_separate(self):
        self.assertTrue(all(i['authorization']['state']=='scope_missing' for i in self.page()['items']))
        identity=self.add_capture();self.assertEqual(self.select([identity]).status_code,200)
        before=self.page()
        self.assertIn('declared_authorized',before['items'][0]['authorization']['resolution_states'])
        self.assertEqual(before['items'][0]['authorization']['panel_signal']['item_authorization'], 'authorized')
        self.assertEqual(before['items'][1]['authorization']['panel_signal']['item_authorization'], 'not_determinable')
        self.assertIn('apparent_conflict',before['items'][1]['authorization']['resolution_states'])
        data=self.evidence(2);saved=self.link(data);self.assertEqual(saved.status_code,200,saved.text)
        after=self.page()['items'][0]['authorization']
        self.assertEqual(after['link_state'],'selected');self.assertEqual(after['link_freshness'],'current')
        self.assertEqual(after['authorization_result'],'no_concluyente')
        self.assertIsNone(after['units_assigned']);self.assertIsNone(after['proposal_amount_ars'])
        self.assertEqual(len(self.evidence(2)['human_link']['history']),1)

    def test_ambiguous_and_excluded_rows_never_approve_or_assign(self):
        self.batch=self.import_book(book([('17/08/2026',10,20,30,'A'),('18/08/2026',10,20,30,'I')]),'AMBIGUO_FICTICIO.xlsx')
        self.select([self.add_capture()])
        data=self.page()['items'][0]['authorization']
        self.assertEqual(data['state'],'ambiguous');self.assertEqual(data['compatible_count'],2)
        self.assertIsNone(data['link_state'])
        excluded=self.client.post(self.base()+'/practice-search',json={'scope':'excluded'},headers=self.headers()).json()['items'][0]
        self.assertEqual(excluded['authorization']['state'],'outside_scope')
        conn=connect(self.root)
        self.assertEqual(conn.execute('SELECT count(*) FROM authorization_link_versions').fetchone()[0],0);conn.close()

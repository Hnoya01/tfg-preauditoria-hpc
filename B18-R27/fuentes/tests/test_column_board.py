import unittest
from uuid import uuid4
from app.db import connect
from tests import test_proposal_freshness as proposals
from tests import test_csv_reviews as csv


class ColumnProposalTests(unittest.TestCase):
    def test_debit_column_reuses_proposal_evaluation_and_never_a_difference(self):
        fixture=proposals.ComponentFreshnessTests()
        fixture.setUp()
        try:
            def search():
                r=fixture.client.post(fixture.base()+'/practice-search',headers=fixture.headers(),json={'view':'all'})
                self.assertEqual(r.status_code,200,r.text)
                return r.json()['items'][0]
            self.assertIsNone(search()['debit_proposal'])
            fixture.save_parts()
            shown=search()['debit_proposal']
            expected=fixture.history()['latest_evaluation']
            self.assertEqual(shown,expected)
            self.assertGreater(shown['current_component_count'],0)
            c=connect(fixture.root)
            try:
                c.execute('UPDATE datasets SET version=version+1 WHERE id=?',(fixture.dataset['id'],))
                from app.proposals import withdraw_economic_verification
                version=c.execute('SELECT version FROM datasets WHERE id=?',(fixture.dataset['id'],)).fetchone()[0]
                withdraw_economic_verification(c,fixture.digest,fixture.dataset['id'],fixture.verification_id,version,'Referencia ficticia retirada para comprobar vigencia.')
            finally:c.close()
            self.assertEqual(search()['debit_proposal'],fixture.history()['latest_evaluation'])
        finally:fixture.tearDown()


class ColumnCsvFilterTests(unittest.TestCase):
    def test_filter_precedes_pagination_and_preserves_decisions(self):
        fixture=csv.CsvReviewTests()
        fixture.setUp()
        try:
            def page(bid,state,offset=0):
                r=fixture.f.client.post(f'/api/datasets/{fixture.ds}/batches/{bid}/practice-search',
                    headers=fixture.f.headers(),json={'view':'all','csv_review_state':state,'limit':1,'offset':offset})
                self.assertEqual(r.status_code,200,r.text)
                return r.json()
            self.assertEqual(page(fixture.a,'review')['filtered_total'],1)
            self.assertEqual(page(fixture.a,'review',1)['items'],[])
            self.assertEqual(page(fixture.a,'supported')['filtered_total'],0)
            self.assertEqual(page(fixture.b,'supported')['filtered_total'],1)
            self.assertEqual(page(fixture.b,'review')['filtered_total'],0)
            self.assertEqual(page(fixture.a,'undetermined')['filtered_total'],0)
            bad=fixture.f.client.post(fixture.url+'/practice-search',headers=fixture.f.headers(),json={'csv_review_state':'approved'})
            self.assertEqual(bad.status_code,422)
            self.assertEqual(fixture.conn.execute('SELECT count(*) FROM review_decisions').fetchone()[0],0)
        finally:fixture.doCleanups()

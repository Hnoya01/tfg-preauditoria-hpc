"""Read-only workbench: invented X1 data, server filters and independent statuses."""

import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import create_app
from app.db import connect
from app.practice_board import practice_search, practice_detail
from app.service import Problem
from app.security import create_user
from tests import test_p05 as fixture
from tests.test_p02 import book, ORIGIN, PASSWORD


class PracticeBoardTests(unittest.TestCase):
    setUp=fixture.P05Tests.setUp
    tearDown=fixture.P05Tests.tearDown
    headers=fixture.P05Tests.headers
    import_book=fixture.P05Tests.import_book
    run_url=fixture.P05Tests.run_url
    alerts=fixture.P05Tests.alerts
    decide=fixture.P05Tests.decide

    def base(self):
        return f'/api/datasets/{self.dataset["id"]}/batches/{self.batch}'

    def search(self,**filters):
        response=self.client.post(self.base()+'/practice-search',json=filters,headers=self.headers())
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def detail(self,number=2):
        return self.client.get(self.base()+f'/rows/{number}/practice-detail')

    def test_workflow_hydrates_only_visible_page_and_reuses_freshness(self):
        from app import practice_board, observation_workflow
        expected=self.search()
        with patch.object(practice_board, '_run_summary', wraps=practice_board._run_summary) as summary, \
             patch.object(observation_workflow, '_run_summary', wraps=observation_workflow._run_summary) as extra, \
             patch.object(observation_workflow, 'observations', wraps=observation_workflow.observations) as observations:
            page=self.search(limit=1,offset=1)
            self.assertEqual(page['items'],expected['items'][1:2])
            self.assertEqual(summary.call_count,1)
            self.assertEqual(extra.call_count,0)
            self.assertEqual(observations.call_count,1)
            self.assertEqual(observations.call_args.args[3],page['items'][0]['source_row'])
        with patch.object(observation_workflow, 'observations', wraps=observation_workflow.observations) as observations:
            self.assertEqual(self.search(code='not-present')['items'],[])
            self.assertEqual(observations.call_count,0)

    def test_exception_queue_navigation_preserves_sort_page_and_filters(self):
        listing=self.search(view='exceptions')
        self.assertEqual([r['source_row'] for r in listing['items']],[2,3])
        self.assertEqual(listing['batch'],self.search(view='all')['batch'])
        self.assertEqual(len(listing['source_notices']),2)
        for reason,count in listing['exception_counts'].items():
            filtered=self.search(view='exceptions',exception_reason=reason,limit=1)
            self.assertEqual(count,filtered['filtered_total'])
            self.assertEqual(filtered['exception_counts'],listing['exception_counts'])
            self.assertIn(reason,filtered['items'][0]['exception_reasons'])
        subset=self.search(view='exceptions',code='sin-filas')
        self.assertEqual(subset['source_notices'],listing['source_notices'])
        for row in listing['items']:
            self.assertTrue(row['exception_details'])
            self.assertNotIn('source_notices',row)
        self.assertTrue(all(r['exception_reasons'] for r in listing['items']))
        for direction, first, second in [('asc',2,3),('desc',3,2)]:
            following=self.search(view='exceptions',limit=1,sort='source_row',direction=direction,after_source_row=first)
            self.assertEqual((following['next_source_row'],following['offset']),(second,1))
            self.assertEqual(following['items'][0]['source_row'],second)
            detail=self.client.get(self.base()+f'/rows/{second}/observations').json()
            self.assertEqual(following['next_review'],detail)
            self.assertIsNone(self.search(view='exceptions',direction=direction,after_source_row=second)['next_source_row'])
        self.assertEqual(self.search(view='referred')['filtered_total'],0)
        self.assertEqual(self.search(family='image_candidates')['filtered_total'],0)
        self.assertEqual(self.search(view='all')['dataset_version'],listing['dataset_version'])

    def assert_paginated_observations_equal_detail(self):
        from app.observation_workflow import observations
        from app.review import _batch
        whole=self.search()
        conn=connect(self.root)
        try:
            batch=_batch(conn,self.dataset['id'],self.batch)
            for offset,item in enumerate(whole['items']):
                paged=self.search(limit=1,offset=offset)['items'][0]
                self.assertEqual(paged,item)
                expected=[{k:v for k,v in observation.items()
                           if k not in ('history','decision_history','evidence')}
                          for observation in observations(conn,self.dataset['id'],batch,item['source_row'])]
                self.assertEqual(paged['observations'],expected)
        finally:
            conn.close()
        return whole

    def test_paginated_workflow_matches_independent_freshness_after_invalidation(self):
        page=self.search()
        changed=self.client.post(self.base()+'/rows/2/work-fields',headers=self.headers(),json={
            'expected_dataset_version':page['dataset_version'],'expected_revision_version':page['batch']['revision_version'],
            'field':'K','value':'Descripción ficticia corregida','reason':'Corrección ficticia con evidencia de origen.'})
        self.assertEqual(changed.status_code,200,changed.text)
        page=self.assert_paginated_observations_equal_detail()
        stale=next(row for row in page['items'] if row['source_row']==2)
        self.assertTrue(any(o['state']=='requires_update' and not o['fresh'] for o in stale['observations']))

    def test_paginated_workflow_matches_closed_revision(self):
        from tests.test_closure import ClosureTests
        # Existing public close workflow, including explicit human limitations.
        self.preview=lambda: ClosureTests.preview(self)
        ClosureTests.resolve_alerts(self)
        page=ClosureTests.justify(self)
        result=ClosureTests.close(self,page)
        self.assertEqual(result.status_code,201,result.text)
        page=self.assert_paginated_observations_equal_detail()
        self.assertEqual(page['batch']['revision_state'],'cerrada')
        self.assertFalse(page['analysis_started'])
        self.assertFalse(page['decision_written'])

    def test_multiple_controls_any_all_are_read_only_and_intersect_per_row(self):
        initial = self.search()
        chosen = ['RN13', 'RN17']
        before = self.detail().json()
        for mode in ('any', 'all'):
            for state in ('con_indicios', 'sin_indicios', 'no_concluyente', 'no_evaluado'):
                expected = []
                for item in initial['items']:
                    matches = [any(c['rule'] == rule and c['state'] == state for c in item['checks']) for rule in chosen]
                    if (any(matches) if mode == 'any' else all(matches)):
                        expected.append(item['source_row'])
                result = self.search(rules=chosen, rules_match=mode, state=state)
                self.assertEqual([item['source_row'] for item in result['items']], expected)
                self.assertFalse(result['analysis_started'])
                self.assertFalse(result['decision_written'])
                self.assertEqual(result['filters']['rules_match'], mode)
        self.assertEqual(self.detail().json(), before)
        for state in ('con_indicios', 'no_evaluado'):
            self.assertEqual(self.search(rule='RN13',state=state)['items'],
                             self.search(rules=['RN13'],state=state)['items'])

    def test_multiple_controls_unknown_and_ambiguous_inputs_rejected(self):
        for filters in ({'rules':['RN99']}, {'rules':['RN13'],'rules_match':'xor'},
                        {'rules':['RN13'],'rule':'RN17'}, {'rules':None}, {'rules':'RN13'}):
            response = self.client.post(self.base()+'/practice-search', json=filters, headers=self.headers())
            self.assertEqual(response.status_code,422,response.text)
        self.assertEqual(self.search(rules=[],rules_match='all')['items'],self.search()['items'])
        self.assertEqual(self.search(rules=['RN13','RN13'])['items'],self.search(rule='RN13')['items'])

    def test_multiple_controls_pagination_modes_and_unevaluated_keep_original_filters(self):
        self.batch=self.import_book(book([('17/08/2026',10,20,30,'A') for _ in range(105)]),'FICTICIO_modes.xlsx')
        filters = dict(rules=['RN13','RN17'],rules_match='all',state='no_evaluado',
                       view='information',code='123456',date_from='2026-08-17',sort='affiliate_id')
        first=self.search(**filters,limit=50)
        second=self.search(**filters,limit=50,offset=50)
        self.assertEqual(first['filtered_total'],105)
        self.assertEqual(second['filtered_total'],105)
        self.assertEqual(len(first['items']),50)
        self.assertEqual(len(second['items']),50)
        self.assertFalse({r['source_row'] for r in first['items']} & {r['source_row'] for r in second['items']})
        self.assertTrue(all(r['state']=='no_evaluado' for r in second['items']))
        self.assertEqual(self.search(**{**filters,'view':'reviewed'})['filtered_total'],0)
        self.assertEqual(self.search(**{**filters,'code':'not-present'})['filtered_total'],0)

    def test_all_rows_include_multiple_independent_states_and_read_only_evidence(self):
        conn=connect(self.root)
        before={table:conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for table in
                ('control_runs','review_decisions','work_changes','authorization_link_versions','proposal_versions')}
        conn.close()
        page=self.search()
        self.assertEqual(page['physical_total'],2)
        self.assertEqual(page['scope_counts'],{'included':2,'excluded':0,'indeterminate':0})
        self.assertEqual(page['filtered_total'],2)
        item=page['items'][0]
        self.assertEqual(item['state'],'con_indicios')
        self.assertGreater(item['control_counts']['sin_indicios'],0)
        self.assertGreater(item['control_counts']['no_concluyente'],0)
        self.assertGreater(item['control_counts']['no_evaluado'],0)
        self.assertEqual(item['decision'],'pendiente')
        self.assertFalse(page['analysis_started']);self.assertFalse(page['decision_written'])
        data=self.detail().json()
        self.assertEqual(data['locator'],'Hoja1!2')
        self.assertEqual(len(data['controls']),11)
        rn13=next(c for c in data['controls'] if c['rule_code']=='RN13')
        self.assertEqual(rn13['result'],'sin_observaciones')
        self.assertEqual(rn13['evidence']['cells'],['O2','P2','Q2'])
        self.assertEqual(data['amounts_original_ars']['total_ars'],'30.00')
        self.assertEqual(data['decision_history'],[])
        self.assertNotIn('V',data['original_fields']);self.assertNotIn('Y',data['original_fields'])
        conn=connect(self.root)
        try:
            self.assertEqual(before,{t:conn.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in before})
        finally:
            conn.close()

    def test_more_than_thousand_rows_pagination_filters_totals_and_scopes(self):
        rows=[('17/08/2026',10,20,99 if i in (3,1198) else 30,'A') for i in range(1200)]
        rows += [('17/08/2026',10,20,30,'C'),('17/08/2026',10,20,30,'I'),('17/08/2026',10,20,30,'I'),
                 ('01/09/2026',10,20,30,'A'),('17/08/2026',10,20,30,'X')]
        self.batch=self.import_book(book(rows),'FICTICIO_1205.xlsx')
        pending=self.search(limit=100,offset=1100)
        self.assertEqual(pending['physical_total'],1205)
        self.assertEqual(pending['scope_counts'],{'included':1201,'excluded':3,'indeterminate':1})
        self.assertEqual(len(pending['items']),100)
        self.assertEqual(pending['items'][0]['source_row'],1102)
        self.assertEqual(pending['items'][0]['state'],'no_evaluado')
        self.assertTrue(all(not x['alerts'] for x in pending['items']))
        analyzed=self.client.post(self.run_url(),json={'expected_version':self.dataset['version']},headers=self.headers())
        self.assertEqual(analyzed.status_code,201,analyzed.text);self.dataset['version']+=1
        differences=self.search(rule='RN13',state='con_indicios')
        self.assertEqual(differences['filtered_total'],2)
        self.assertEqual([x['source_row'] for x in differences['items']],[5,1200])
        self.assertEqual(self.search(rule='RN13',state='no_concluyente')['filtered_total'],0)
        self.assertEqual(self.search(rule='RN13',state='sin_indicios')['filtered_total'],1199)
        self.assertEqual(self.search(code='123456',text='FICTICIA',date_from='2026-08-17',date_to='2026-08-17')['filtered_total'],1201)
        self.assertEqual(self.search(code='12345')['filtered_total'],0)
        self.assertEqual(self.search(scope='excluded')['filtered_total'],3)
        self.assertTrue(all(i['disposition']=='excluded' for i in self.search(scope='excluded')['items']))
        self.assertEqual(self.search(scope='indeterminate')['filtered_total'],1)
        whole=self.search(scope='all',offset=1200)
        self.assertEqual((whole['physical_total'],whole['filtered_total'],whole['scope_total']),(1205,1205,1205))
        self.assertEqual([r['source_row'] for r in whole['items']],[1202,1203,1204,1205,1206])
        last=self.search(offset=1200)
        self.assertEqual([x['source_row'] for x in last['items']],[1202])
        self.assertEqual(last['items'][0]['scope_type'],'C')
        detail=self.detail(1202).json()
        self.assertEqual(detail['disposition'],'included')
        self.assertEqual(detail['decision_history'],[])

    def test_numeric_order_and_zero_remain_original_known_amounts(self):
        self.batch=self.import_book(book([('20/08/2026',0,0,2),('21/08/2026',0,0,10),('22/08/2026',0,0,0)]),'FICTICIO_importes.xlsx')
        data=self.search(sort='total_ars',direction='asc')
        self.assertEqual([x['total_ars'] for x in data['items']],['0.00','2.00','10.00'])
        self.assertEqual([x['source_row'] for x in self.search(sort='total_ars',direction='desc')['items']],[3,2,4])
        self.assertEqual(self.detail(4).json()['amounts_original_ars']['total_ars'],'0.00')
        self.assertEqual(self.search(date_from='2026-08-21',date_to='2026-08-21')['filtered_total'],1)

    def test_decision_filters_and_history_do_not_turn_absent_alerts_into_approval(self):
        page=self.alerts();selected=[{'id':page['items'][0]['id'],'expected_version':page['items'][0]['version']}]
        result=self.decide(selected,state='descartada')
        self.dataset['version']=result.json()['dataset_version']
        reviewed=self.search(view='reviewed',decision='descartada')
        self.assertEqual(reviewed['filtered_total'],1)
        self.assertEqual(reviewed['items'][0]['source_row'],2)
        self.assertEqual(self.search(decision='pendiente')['filtered_total'],1)
        self.assertEqual(self.detail().json()['decision_history'][0]['state'],'descartada')
        self.assertEqual(self.search(reason='coincidencia_estricta_candidata',rule='RN17')['filtered_total'],2)
        self.assertEqual(self.search(reason='suma_concilia',rule='RN17')['filtered_total'],0)

    def test_selective_staleness_detail_and_interpretation_history(self):
        page=self.search()
        changed=self.client.post(self.base()+'/rows/2/work-fields',headers=self.headers(),json={
            'expected_dataset_version':page['dataset_version'],'expected_revision_version':page['batch']['revision_version'],
            'field':'K','value':'Descripción ficticia corregida','reason':'Corrección ficticia con evidencia de origen.'})
        self.assertEqual(changed.status_code,200,changed.text)
        self.dataset['version']=changed.json()['dataset_version']
        stale=self.search(state='requires_update')
        self.assertEqual(stale['filtered_total'],1)
        self.assertEqual(stale['items'][0]['source_row'],2)
        self.assertEqual(self.search(text='corregida')['filtered_total'],1)
        self.assertEqual(self.search(search='corregida')['items'][0]['corrected_fields'],['K'])
        data=self.detail().json()
        self.assertEqual(data['original_fields']['K'],'Práctica ficticia')
        self.assertEqual(data['effective_fields']['K'],'Descripción ficticia corregida')
        self.assertEqual(len(data['interpretation_history']),1)
        self.assertEqual(next(c for c in data['controls'] if c['rule_code']=='RN13')['freshness'],'current')
        self.assertEqual(next(c for c in data['controls'] if c['rule_code']=='RN14')['freshness'],'requires_update')

    def test_filters_validate_and_post_search_requires_csrf(self):
        for filters in ({'limit':101},{'offset':-1},{'rule':'RN999'},{'state':'aprobada'},{'sort':'DROP TABLE'},
                        {'date_from':'2026-02-30'},{'date_from':'2026-09-01','date_to':'2026-08-01'},
                        {'scope':'desconocido'},{'text':'x'*101},{'include_private':True}):
            result=self.client.post(self.base()+'/practice-search',json=filters,headers=self.headers())
            self.assertEqual(result.status_code,422,result.text)
        self.assertEqual(self.client.post(self.base()+'/practice-search',json={},headers={'Origin':ORIGIN}).status_code,403)

    def test_object_permissions_and_missing_detail(self):
        with TestClient(create_app(self.root,public_origin=ORIGIN),base_url=ORIGIN) as outsider:
            login=outsider.post('/api/session',json={'username':'viewer','password':PASSWORD},headers={'Origin':ORIGIN}).json()
            self.assertEqual(outsider.get(self.base()+'/rows/2/practice-detail').status_code,403)
            self.assertEqual(outsider.post(self.base()+'/practice-search',json={},headers={'Origin':ORIGIN,'X-CSRF-Token':login['csrf_token']}).status_code,403)
        other=self.client.post('/api/datasets',json={'label':'Otro conjunto ficticio'},headers=self.headers()).json()
        url=f'/api/datasets/{other["id"]}/batches/{self.batch}'
        self.assertEqual(self.client.post(url+'/practice-search',json={},headers=self.headers()).status_code,404)
        self.assertEqual(self.client.get(url+'/rows/2/practice-detail').status_code,404)
        self.assertEqual(self.detail(999).status_code,404)

    def test_version_and_revocation_rechecked_before_delivering_data(self):
        conn=connect(self.root)
        def change():
            other=connect(self.root);other.execute('UPDATE datasets SET version=version+1 WHERE id=?',(self.dataset['id'],));other.close()
        try:
            with self.assertRaises(Problem) as exc:
                practice_search(conn,self.digest,self.dataset['id'],self.batch,{},after_read=change)
            self.assertEqual(exc.exception.status,409)
            def revoke():
                other=connect(self.root);other.execute('DELETE FROM sessions WHERE token_hash=?',(self.digest,));other.close()
            with self.assertRaises(Problem) as exc:
                practice_detail(conn,self.digest,self.dataset['id'],self.batch,2,after_read=revoke)
            self.assertEqual(exc.exception.status,401)
            self.assertFalse(conn.in_transaction)
        finally:
            conn.close()

    def test_two_assigned_reviewers_read_shared_changes_and_cannot_overwrite_stale_selection(self):
        conn=connect(self.root)
        for username in ('board_a','board_b'):
            create_user(conn,username,PASSWORD,'reviewer')
        conn.close()
        for username in ('board_a','board_b'):
            granted=self.client.post(f'/api/datasets/{self.dataset["id"]}/access',json={
                'username':username,'role':'reviewer','expected_version':self.dataset['version']},headers=self.headers())
            self.assertEqual(granted.status_code,200,granted.text)
            self.dataset['version']=granted.json()['version']
        with TestClient(create_app(self.root,public_origin=ORIGIN),base_url=ORIGIN) as a, TestClient(create_app(self.root,public_origin=ORIGIN),base_url=ORIGIN) as b:
            clients=[]
            for client,username in ((a,'board_a'),(b,'board_b')):
                login=client.post('/api/session',json={'username':username,'password':PASSWORD},headers={'Origin':ORIGIN}).json()
                headers={'Origin':ORIGIN,'X-CSRF-Token':login['csrf_token']}
                response=client.post(self.base()+'/practice-search',json={},headers=headers)
                self.assertEqual(response.status_code,200,response.text)
                clients.append((headers,response.json()))
            headers_a,page_a=clients[0];headers_b,page_b=clients[1]
            alert=next(x for x in page_a['items'][0]['alerts'] if x['current'])
            body={'expected_dataset_version':page_a['dataset_version'],'expected_revision_version':page_a['batch']['revision_version'],
                  'items':[{'id':alert['id'],'expected_version':alert['version']}],'state':'descartada',
                  'foundation':'Cotejo ficticio compartido; unidades independientes.'}
            saved=a.post(self.base()+'/decisions',json=body,headers=headers_a)
            self.assertEqual(saved.status_code,200,saved.text)
            stale=b.post(self.base()+'/decisions',json=body,headers=headers_b)
            self.assertEqual(stale.status_code,409,stale.text)
            refreshed=b.post(self.base()+'/practice-search',json={'decision':'descartada'},headers=headers_b)
            self.assertEqual(refreshed.status_code,200,refreshed.text)
            self.assertEqual(refreshed.json()['filtered_total'],1)
            history=b.get(self.base()+'/rows/2/practice-detail').json()['decision_history']
            self.assertEqual(len(history),1)
            self.assertEqual(history[0]['actor_username'],'board_a')


if __name__=='__main__':
    unittest.main()

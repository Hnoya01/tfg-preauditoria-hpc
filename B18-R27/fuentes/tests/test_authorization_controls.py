"""B04 full review path, using entirely invented invoices and authorizations."""
from copy import deepcopy
from io import BytesIO
import json
from time import monotonic,sleep
import unittest
from uuid import uuid4
from zipfile import ZipFile

from fastapi.testclient import TestClient
from app.api import create_app
from app.controls import _run_summary,run_controls
from app.db import connect
from app.proposals import save_verified_proposal
from app.security import create_user
from app.service import Problem
from scripts.create_b02_demo import capture
from tests import test_authorization_assessment as previous
from tests.test_p02 import book,ORIGIN,PASSWORD


class IntegratedAuthorizationTests(unittest.TestCase):
    setUp=previous.AssessmentTests.setUp
    tearDown=previous.AssessmentTests.tearDown
    headers=previous.AssessmentTests.headers
    import_book=previous.AssessmentTests.import_book
    run_url=previous.AssessmentTests.run_url
    alerts=previous.AssessmentTests.alerts
    decide=previous.AssessmentTests.decide
    url=previous.AssessmentTests.url
    stage=previous.AssessmentTests.stage
    confirm=previous.AssessmentTests.confirm
    base=previous.AssessmentTests.base
    add_capture=previous.AssessmentTests.add_capture
    select=previous.AssessmentTests.select
    evidence=previous.AssessmentTests.evidence
    link=previous.AssessmentTests.link
    preview=previous.AssessmentTests.preview
    declare=previous.AssessmentTests.declare
    ready=previous.AssessmentTests.ready

    def analyze(self):
        r=self.client.post(self.run_url(),headers=self.headers(),json={'expected_version':self.dataset['version']})
        self.assertIn(r.status_code,(200,201),r.text)
        self.dataset['version']=self.evidence()['dataset_version']
        return r.json()

    def results(self,run,number=2):
        r=self.client.get(f'/api/datasets/{self.dataset["id"]}/control-runs/{run["id"]}/rows/{number}')
        self.assertEqual(r.status_code,200,r.text)
        return {x['rule_code']:x for x in r.json()}

    def change(self,number,field,value):
        e=self.evidence(number)
        r=self.client.post(self.base()+f'/rows/{number}/work-fields',headers=self.headers(),json={
            'expected_dataset_version':e['dataset_version'],'expected_revision_version':e['revision_version'],
            'field':field,'value':value,'reason':'Corrección totalmente ficticia para ensayo integrado.'})
        self.assertEqual(r.status_code,200,r.text);self.dataset['version']=r.json()['dataset_version']

    def test_explicit_analysis_creates_fictional_alerts_and_frozen_export(self):
        self.ready();self.declare();self.declare(kind='incorporation',value='2026-08-15T17:00:00-03:00')
        conn=connect(self.root)
        try:self.assertEqual(conn.execute('SELECT count(*) FROM control_runs WHERE dataset_id=?',(self.dataset['id'],)).fetchone()[0],0)
        finally:conn.close()
        run=self.analyze();r=self.results(run)
        self.assertEqual([r[x]['result'] for x in ('RN09','RN10','RN11')],['sin_observaciones','con_indicios','con_indicios'])
        for rule in ('RN09','RN10','RN11'):
            self.assertEqual(r[rule]['rule_version'],'B04-authorizations-v1')
            self.assertEqual(r[rule]['evidence']['data_origin'],'synthetic')
            self.assertFalse(r[rule]['evidence']['monetary_eligible']);self.assertIsNone(r[rule]['difference_ars'])
        self.assertEqual({a['rule_code'] for a in self.alerts()['items']},{'RN10','RN11'})
        selected=[{'id':a['id'],'expected_version':a['version']} for a in self.alerts()['items'] if a['rule_code']=='RN11']
        d=self.decide(selected,state='confirmada',evidence_note='Cotejo ficticio de cantidades, sin valor económico real.')
        self.assertEqual(d.status_code,200,d.text);self.dataset['version']=d.json()['dataset_version']
        z=self.client.get(self.base()+'/export-provisional');self.assertEqual(z.status_code,200,z.text[:80])
        with ZipFile(BytesIO(z.content)) as archive:
            manifest=json.loads(archive.read('manifest.json'));snapshot=json.loads(archive.read('analysis_snapshot.json'))
            self.assertEqual(snapshot,run['snapshot'])
            self.assertEqual(manifest['authorization_analysis']['captured_mode'],'synthetic_demo')
            self.assertIsNone(manifest['current_proposal_total_ars'])
            refs=next(iter(snapshot['authorization_engine']['cohorts'].values()))
            self.assertTrue(refs[0]['link_id']);self.assertTrue(refs[0]['unit_input_id'])
        # Even an internal caller cannot turn a confirmed demo alert into real money.
        conn=connect(self.root)
        try:
            e=self.evidence()
            with self.assertRaises(Problem) as ex:
                save_verified_proposal(conn,self.root,self.digest,self.dataset['id'],self.batch,2,e['dataset_version'],e['revision_version'],({'decision_id':d.json()['decision_ids'][0]},))
            self.assertEqual(ex.exception.status,409)
            self.assertIn('ficticio',ex.exception.message)
        finally:conn.close()
        real=deepcopy(capture());real['source']['stream_id']='real-declarado-en-ensayo-ficticio';real['data_origin']='real_unvalidated'
        self.assertEqual(self.select([self.add_capture(real)],mode='real_unvalidated').status_code,422)

    def test_real_unvalidated_sources_preserve_raw_comparison_without_conclusive_alert(self):
        self.batch=self.import_book(book([('15/08/2026',10,20,30,'A')]),'ORIGEN_DECLARADO_FICTICIO_EN_EL_ENSAYO.xlsx')
        data=capture();data['data_origin']='real_unvalidated'
        self.select([self.add_capture(data)],mode='real_unvalidated');self.link(self.evidence());self.declare()
        self.declare(kind='incorporation',value='2026-08-15T17:00:00-03:00')
        r=self.results(self.analyze())
        self.assertTrue(all(r[x]['result']=='no_concluyente' for x in ('RN09','RN10','RN11')))
        self.assertEqual(r['RN11']['evidence']['quantity']['state'],'con_indicios')
        self.assertEqual(r['RN10']['evidence']['temporal']['state'],'con_indicios')
        self.assertEqual(self.alerts()['total'],0)

    def test_joint_changes_preserve_independent_decision_and_do_not_reuse_changed_one(self):
        self.batch=self.import_book(book([('15/08/2026',10,20,30,'A'),('15/08/2026',10,20,30,'A'),('16/08/2026',10,20,31,'A')]),'CONJUNTO_FICTICIO.xlsx')
        self.select([self.add_capture()])
        for n in (2,3):self.link(self.evidence(n));self.declare(n)
        run=self.analyze()
        self.assertEqual(self.results(run)['RN11']['evidence']['quantity']['billed_joint'],'4')
        alerts=[a for a in self.alerts()['items'] if (a['source_row'],a['rule_code']) in ((2,'RN11'),(4,'RN13'))]
        # Different rules remain separate atomic decisions.
        for a in alerts:
            d=self.decide([{'id':a['id'],'expected_version':a['version']}]);self.assertEqual(d.status_code,200,d.text)
            self.dataset['version']=d.json()['dataset_version']
        self.change(3,'G','1')
        r=self.results(run)
        self.assertEqual(r['RN11']['freshness'],'requires_update')
        self.assertTrue(all(r[x]['freshness']=='current' for x in ('RN09','RN10','RN13','RN17')))
        self.assertEqual(self.results(run,4)['RN11']['freshness'],'current')
        updated=self.analyze()
        self.assertEqual(self.results(updated)['RN11']['evidence']['quantity']['billed_joint'],'3')
        by={(a['source_row'],a['rule_code']):a for a in self.alerts()['items']}
        self.assertEqual(by[(2,'RN11')]['decision'],'pendiente')
        self.assertEqual(by[(4,'RN13')]['decision'],'descartada')
        conn=connect(self.root)
        try:self.assertEqual(conn.execute('SELECT count(*) FROM review_decisions d JOIN alerts a ON a.id=d.alert_id WHERE a.import_id=?',(run['snapshot']['import_id'],)).fetchone()[0],2)
        finally:conn.close()

    def test_warm_board_rechecks_source_integrity_and_row_edits(self):
        from app.storage import object_path
        from app.authorization_controls import Facts
        from unittest.mock import patch
        self.ready();self.declare()
        analyzed=self.analyze()
        def board():
            response=self.client.post(self.base()+'/practice-search',headers=self.headers(),
                                      json={'view':'exceptions'})
            self.assertEqual(response.status_code,200,response.text)
            return response.json()
        initial=board()
        with patch.object(Facts,'snapshot',side_effect=AssertionError('Repeated unchanged reconstruction')):
            self.assertEqual(board(),initial)
        basis=analyzed['snapshot']['authorization_engine']['scope']['captures'][0]
        original=object_path(self.root,basis['source_sha256'])
        contents=original.read_bytes()
        try:
            original.write_bytes(contents+b'FICTICIO')
            damaged=board()
            self.assertEqual(damaged['dataset_version'],initial['dataset_version'])
            self.assertEqual(damaged['batch']['run_freshness'],'requires_update')
            self.assertTrue(any(row['control_counts'].get('requires_update') for row in damaged['items']))
        finally:
            original.write_bytes(contents)
        self.assertEqual(board(),initial)
        self.change(2,'G','7')
        changed=board()
        self.assertGreater(changed['dataset_version'],initial['dataset_version'])
        self.assertTrue(any(c['rule']=='RN11' and c['state']=='requires_update'
                            for row in changed['items'] if row['source_row']==2 for c in row['checks']))

    def test_cross_batch_quantity_and_unit_dependencies_exclude_incorporation(self):
        cap=self.ready();self.declare();first=self.batch
        self.batch=self.import_book(book([('15/08/2026',10,20,31,'A')]),'OTRO_FICTICIO.xlsx')
        self.select([cap]);self.link(self.evidence());self.declare();second=self.batch
        self.batch=first;run=self.analyze()
        self.assertEqual(self.results(run)['RN11']['evidence']['quantity']['billed_joint'],'4')
        self.batch=second;self.declare(kind='incorporation',value='2026-08-16')
        self.assertEqual(self.results(run)['RN11']['freshness'],'current')
        self.declare(value='sesion')
        self.assertEqual(self.results(run)['RN11']['freshness'],'requires_update')
        self.assertEqual(self.results(run)['RN13']['freshness'],'current')
        self.batch=first;updated=self.analyze()
        self.assertEqual(self.results(updated)['RN11']['result'],'no_concluyente')
        self.assertIn('billed_quantity_or_unit_unverified',self.results(updated)['RN11']['evidence']['quantity']['limitations'])
        self.batch=second
        other=deepcopy(capture());other['source']['stream_id']='segunda-extraccion-no-verificada'
        self.select([self.add_capture(other)]);self.link(self.evidence());self.declare()
        self.batch=first;again=self.analyze()
        self.assertIn('coverage_identity_between_captures_unverified',self.results(again)['RN11']['evidence']['quantity']['limitations'])
        self.assertEqual(self.results(again)['RN09']['result'],'sin_observaciones')

    def test_unselected_stream_does_not_invalidate_selected_controls_but_replacement_does(self):
        self.ready();self.declare();run=self.analyze()
        other=deepcopy(capture());other['source']['stream_id']='otro-flujo-sin-seleccionar';self.add_capture(other)
        r=self.results(run);self.assertTrue(all(r[x]['freshness']=='current' for x in ('RN09','RN10','RN11','RN18')))
        replace=capture();replace['source']['capture_id']='FICT-NUEVA';replace['orders'][0]['resolutions'][0]['authorized_quantity']='3';self.add_capture(replace)
        r=self.results(run);self.assertTrue(all(r[x]['freshness']=='requires_update' for x in ('RN09','RN10','RN11','RN18')))
        self.assertEqual(r['RN13']['freshness'],'current');self.assertEqual(r['RN17']['freshness'],'current')

    def test_contradiction_ambiguity_inpatient_and_same_day_preserve_limits(self):
        self.batch=self.import_book(book([(f'{d}/08/2026',10,20,30,'I' if d==18 else 'A') for d in (16,17,18,19)]),'LIMITES_FICTICIOS.xlsx')
        self.select([self.add_capture()]);self.link(self.evidence(2))
        r=self.analyze()
        self.assertEqual(self.results(r,2)['RN09']['result'],'no_concluyente')
        self.assertEqual(self.results(r,3)['RN11']['result'],'no_concluyente')
        self.assertTrue(all(x['result']=='no_aplicable' for x in self.results(r,4).values()))
        self.assertEqual(self.results(r,5)['RN09']['result'],'no_concluyente')
        self.assertEqual(self.alerts()['total'],0)
        data=capture();data['source']['capture_id']='FICT-RECHAZO-EXPLICITO'
        data['orders'][1]['resolutions']=data['orders'][1]['resolutions'][1:]
        self.select([self.add_capture(data)]);self.link(self.evidence(2))
        rejected=self.results(self.analyze(),2)
        self.assertEqual(rejected['RN09']['result'],'con_indicios')
        self.assertEqual(rejected['RN11']['result'],'no_concluyente')  # Rejection is not an inferred zero quantity.

    def test_atomic_publication_rejects_changed_peer_and_preserves_prior_capture(self):
        self.ready();self.declare();run=self.analyze();self.change(2,'G','1')
        from app.dependencies import dependency_changes
        legacy=deepcopy(run['snapshot']);legacy.pop('rule_versions');legacy.pop('authorization_engine')
        conn=connect(self.root)
        try:
            compatible=dependency_changes(conn,legacy,run['snapshot'])
            # A capture without rule versions also predates the 45-day billing window.
            self.assertEqual(compatible['global_affected_rules'],['RN09','RN10','RN11','RN14','RN15','RN19'])
            self.assertNotIn('RN13',compatible['affected_rules']);self.assertNotIn('RN17',compatible['affected_rules'])
        finally:conn.close()
        conn=connect(self.root)
        def concurrent():
            other=connect(self.root);other.execute('UPDATE datasets SET version=version+1 WHERE id=?',(self.dataset['id'],));other.close()
        try:
            before=conn.execute('SELECT count(*) FROM control_runs').fetchone()[0]
            with self.assertRaises(Problem) as ex:run_controls(conn,self.digest,self.dataset['id'],self.batch,self.dataset['version'],after_prepare=concurrent)
            self.assertEqual(ex.exception.status,409)
            self.assertEqual(conn.execute('SELECT count(*) FROM control_runs').fetchone()[0],before)
            self.assertTrue(conn.execute('SELECT 1 FROM control_runs WHERE id=?',(run['id'],)).fetchone())
        finally:conn.close()

    def test_background_processing_publishes_complete_authorization_results_once(self):
        self.ready();self.declare();e=self.evidence();body={'expected_dataset_version':e['dataset_version'],'expected_revision_version':e['revision_version'],'request_key':uuid4().hex}
        url=self.base()+'/processing-attempts'
        first=self.client.post(url,headers=self.headers(),json=body);self.assertEqual(first.status_code,202,first.text)
        again=self.client.post(url,headers=self.headers(),json=body);self.assertIn(again.status_code,(200,202));self.assertEqual(again.json()['id'],first.json()['id'])
        end=monotonic()+10;job=first.json()
        while monotonic()<end and job['state'] in ('queued','running'):
            sleep(.03);job=self.client.get(url+'/'+job['id']).json()
        self.assertEqual(job['state'],'completed',job)
        self.assertEqual(self.results({'id':job['result_run_id']})['RN11']['result'],'con_indicios')
        conn=connect(self.root)
        try:self.assertEqual(conn.execute('SELECT count(*) FROM control_runs WHERE dataset_id=?',(self.dataset['id'],)).fetchone()[0],1)
        finally:conn.close()

    def test_processing_beyond_preview_limit_captures_all_members_without_assigning_units(self):
        self.batch=self.import_book(book([('15/08/2026',10,20,30,'A')]*1001),'1001_B04_FICTICIO.xlsx')
        self.select([self.add_capture()]);self.link(self.evidence());self.declare()
        run=self.analyze();r=self.results(run)
        cohorts=run['snapshot']['authorization_engine']['cohorts']
        self.assertEqual(len(next(iter(cohorts.values()))),1001)
        self.assertEqual(r['RN11']['result'],'no_concluyente')
        self.assertIn('pending_or_ambiguous_association',r['RN11']['evidence']['quantity']['limitations'])
        self.assertNotIn('candidate_limit_1000',r['RN11']['evidence']['quantity']['limitations'])

    def test_two_reviewers_see_shared_alert_and_stale_decision_is_rejected(self):
        self.ready();self.declare();self.analyze()
        conn=connect(self.root)
        try:create_user(conn,'colega_ficticio',PASSWORD,'reviewer')
        finally:conn.close()
        grant=self.client.post(f'/api/datasets/{self.dataset["id"]}/access',headers=self.headers(),json={'username':'colega_ficticio','role':'reviewer','expected_version':self.dataset['version']})
        self.assertEqual(grant.status_code,200,grant.text);self.dataset['version']=grant.json()['version']
        with TestClient(create_app(self.root,public_origin=ORIGIN,processing_enabled=False),base_url=ORIGIN) as colleague:
            login=colleague.post('/api/session',headers={'Origin':ORIGIN},json={'username':'colega_ficticio','password':PASSWORD}).json()
            page=colleague.get(self.base()+'/alerts').json();alert=page['items'][0]
            body={'expected_dataset_version':self.dataset['version'],'expected_revision_version':page['revision_version'],
                  'items':[{'id':alert['id'],'expected_version':alert['version']}],'state':'no_concluyente','foundation':'Ensayo compartido ficticio con evidencia pendiente.'}
            d=self.decide(body['items']);self.assertEqual(d.status_code,200,d.text);self.dataset['version']=d.json()['dataset_version']
            stale=colleague.post(self.base()+'/decisions',headers={'Origin':ORIGIN,'X-CSRF-Token':login['csrf_token']},json=body)
            self.assertEqual(stale.status_code,409)
            self.assertEqual(colleague.get(self.base()+'/alerts').json()['items'][0]['decision'],'descartada')


if __name__=='__main__':unittest.main()

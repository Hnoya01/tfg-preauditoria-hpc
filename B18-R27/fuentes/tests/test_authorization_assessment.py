"""B03 complete invented sources only; previews never approve real coverage."""
from copy import deepcopy
import unittest
from io import BytesIO
from time import monotonic
from zipfile import ZipFile
from fastapi.testclient import TestClient

from app.api import create_app
from app.authorization_assessment import applicable_resolution, compare_time, preview, save_input
from app.controls import _run_summary
from app.db import connect
from app.service import Problem
from scripts.create_b02_demo import capture
from tests import test_authorization_matching as matching
from tests.test_p02 import book, ORIGIN, PASSWORD


class SemanticsTests(unittest.TestCase):
    def test_temporal_precision_and_zones_not_realization(self):
        for a,b,state in [
            ('2026-08-15','2026-08-16','sin_observaciones'),
            ('2026-08-16','2026-08-15','con_indicios'),
            ('2026-08-15','2026-08-15','no_concluyente'),
            ('2026-08-15T18:00:00-03:00','2026-08-15T21:01:00Z','sin_observaciones'),
            ('2026-08-15T18:00:00-03:00','2026-08-15T20:59:00Z','con_indicios'),
            ('2026-08-15T18:00:00-03:00','2026-08-15T18:00:00-03:00','no_concluyente'),
            ('2026-08-15T18:00-03:00','2026-08-15T18:00:30-03:00','no_concluyente'),
            ('2026-08-15T18:00','2026-08-15T19:00','no_concluyente'),
            ('2026-08-15','2026-08-16T00:01:00-03:00','no_concluyente'),
            ('2026-08-15T18','2026-08-16','no_concluyente'),
            (None,'2026-08-16','no_concluyente')]:
            with self.subTest(a=a,b=b): self.assertEqual(compare_time(a,b)['state'],state)

    def test_explicit_general_individual_and_conflicting_replacements(self):
        order=capture()['orders'][0];item=order['items'][0]
        r=applicable_resolution(order,item)
        self.assertEqual((r['state'],r['quantity']),('declared_authorized','1'))
        order['resolutions'][0].update(scope='explicit_general',authorized_quantity=None,unit=None)
        self.assertEqual(applicable_resolution(order,item)['quantity'],'2')
        order['resolutions'][0]['authorized_quantity']='2'
        self.assertEqual(applicable_resolution(order,item)['state'],'no_concluyente')
        order['resolutions'][0].update(authorized_quantity=None,unit=None)
        second={**item,'item_id':'FICT-SEGUNDO','full_code':'654321','requested_quantity':'3'}
        order['items'].append(second);order['resolutions'][0]['item_ids'].append(second['item_id'])
        self.assertEqual(applicable_resolution(order,item)['quantity'],'2')
        self.assertEqual(applicable_resolution(order,second)['quantity'],'3')
        order=capture()['orders'][1]
        self.assertEqual(applicable_resolution(order,order['items'][0])['state'],'no_concluyente')
        order['resolutions'][1]['supersedes_resolution_id']=order['resolutions'][0]['resolution_id']
        self.assertEqual(applicable_resolution(order,order['items'][0])['state'],'no_concluyente')
        order['resolutions']=order['resolutions'][1:]
        self.assertEqual(applicable_resolution(order,order['items'][0])['state'],'no_concluyente')
        order['resolutions'][0]['scope']=None
        self.assertEqual(applicable_resolution(order,order['items'][0])['state'],'no_concluyente')


class AssessmentTests(unittest.TestCase):
    # Reuse setup/helpers, not the inherited B02 test methods.
    def setUp(self):
        matching.MatchingTests.setUp(self)
        # A new empty dataset preserves all setup history without letting its
        # intentionally unselected second invoice masquerade as known coverage.
        self.dataset=self.client.post('/api/datasets',headers=self.headers(),json={'label':'B03 FICTICIO aislado'}).json()
        self.batch=None
    tearDown=matching.MatchingTests.tearDown
    headers=matching.MatchingTests.headers
    import_book=matching.MatchingTests.import_book
    run_url=matching.MatchingTests.run_url
    alerts=matching.MatchingTests.alerts
    decide=matching.MatchingTests.decide
    url=matching.MatchingTests.url
    stage=matching.MatchingTests.stage
    confirm=matching.MatchingTests.confirm
    base=matching.MatchingTests.base
    add_capture=matching.MatchingTests.add_capture
    select=matching.MatchingTests.select
    evidence=matching.MatchingTests.evidence
    link=matching.MatchingTests.link
    # B01 helper preview is used by confirm; B03 helper has another name.
    preview=matching.MatchingTests.preview

    def check(self,number=2):
        r=self.client.get(self.base()+f'/rows/{number}/authorization-check-preview')
        self.assertEqual(r.status_code,200,r.text)
        return r.json()

    def declare(self,number=2,kind='quantity_unit',value='practica',state='declared',**overrides):
        e=self.evidence(number)
        r=self.client.post(self.base()+f'/rows/{number}/authorization-input',headers=self.headers(),json={
            'expected_version':e['dataset_version'],'expected_revision_version':e['revision_version'],
            'kind':kind,'state':state,'value':value,'provenance':'Declaración totalmente ficticia para ensayo B03.',
            'locator':f'FICTICIO!fila{number}',**overrides})
        if r.status_code==200:self.dataset['version']=r.json()['dataset_version']
        return r

    def ready(self):
        if not self.batch:self.batch=self.import_book(book([('15/08/2026',10,20,30,'A')]),'B03_FICTICIO.xlsx')
        cap=self.add_capture();self.select([cap]);self.link(self.evidence());return cap

    def test_partial_quantity_and_missing_temporal_evidence_never_money(self):
        self.ready()
        self.assertEqual(self.check()['quantity']['state'],'no_concluyente')
        self.assertEqual(self.declare().status_code,200)
        c=self.check()
        self.assertEqual((c['quantity']['state'],c['quantity']['billed_joint'],c['quantity']['authorized']),('con_indicios','2','1'))
        self.assertEqual(c['temporal']['state'],'no_concluyente')
        self.assertIsNone(c['units_assigned']);self.assertIsNone(c['proposal_amount_ars'])
        self.assertFalse(c['analysis_started']);self.assertTrue(c['preview_only'])
        conn=connect(self.root)
        try:
            self.assertEqual(conn.execute('SELECT count(*) FROM control_runs').fetchone()[0],1)
            self.assertEqual(conn.execute('SELECT count(*) FROM proposal_versions').fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT count(*) FROM review_decisions').fetchone()[0],0)
        finally:conn.close()

    def test_temporal_history_withdrawal_and_selective_freshness(self):
        self.ready();self.declare()
        run=self.client.post(self.run_url(),headers=self.headers(),json={'expected_version':self.dataset['version']})
        self.assertIn(run.status_code,(200,201),run.text);run=run.json()
        self.dataset['version']=self.evidence()['dataset_version']
        self.declare(kind='incorporation',value='2026-08-15T19:00:00-03:00')
        self.assertEqual(self.check()['temporal']['state'],'sin_observaciones')
        conn=connect(self.root)
        try:
            summary=_run_summary(conn,self.dataset['id'],run['id'])
            self.assertEqual(summary['affected_rules'],['RN10'])
        finally:conn.close()
        self.declare(kind='incorporation',value='2026-08-15T17:00:00-03:00')
        self.assertEqual(self.check()['temporal']['state'],'con_indicios')
        self.declare(kind='incorporation',value=None,state='withdrawn')
        c=self.check();self.assertEqual(c['temporal']['state'],'no_concluyente')
        self.assertEqual(len(c['inputs']['incorporation']['history']),3)
        self.assertIsNone(c['inputs']['incorporation']['current']['value'])
        self.assertEqual(len(c['inputs']['incorporation']['current']['record_sha256']),64)

    def test_ambiguous_conflicting_inpatient_and_unmatched_stay_open(self):
        self.batch=self.import_book(book([(f'{d}/08/2026',10,20,30,'I' if d==18 else 'A') for d in (16,17,18,19)]),'B03_FICTICIO.xlsx')
        self.select([self.add_capture()]);self.link(self.evidence())
        for number in (2,3,4,5):
            c=self.check(number)
            self.assertEqual(c['quantity']['state'],'no_concluyente')
            self.assertIsNone(c['units_assigned'])
        self.assertEqual(self.declare(4).status_code,409)

    def test_multiple_rows_same_coverage_no_arrival_allocation(self):
        self.batch=self.import_book(book([('15/08/2026',10,20,30,'A')]*2),'DOS_FILAS_FICTICIAS.xlsx')
        self.select([self.add_capture()]);self.link(self.evidence(2));self.declare(2)
        c=self.check(2)
        self.assertIn('pending_or_ambiguous_association',c['quantity']['limitations'])
        self.link(self.evidence(3));self.declare(3)
        c=self.check(2)
        self.assertEqual((c['quantity']['billed_joint'],len(c['quantity']['members'])),('4',2))
        self.assertEqual(c['quantity']['state'],'con_indicios')
        self.assertIsNone(c['units_assigned'])
        self.declare(3,value='sesion')
        self.assertEqual(self.check(2)['quantity']['state'],'no_concluyente')
        e=self.evidence(3)
        r=self.client.post(self.base()+'/rows/3/work-fields',headers=self.headers(),json={
            'expected_dataset_version':e['dataset_version'],'expected_revision_version':e['revision_version'],
            'field':'C','value':'IDENTIDAD-FICTICIA-PENDIENTE','reason':'Identidad sin resolver para ensayo de cobertura pendiente.'})
        self.assertEqual(r.status_code,200,r.text);self.dataset['version']=r.json()['dataset_version']
        self.assertIn('related_identity_unresolved',self.check(2)['quantity']['limitations'])

    def test_joint_coverage_across_batches_and_unverified_other_capture(self):
        cap=self.ready();self.declare();first=self.batch
        second=self.import_book(book([('15/08/2026',10,20,31,'A')]),'OTRO_LOTE_FICTICIO.xlsx')
        self.batch=second;self.select([cap]);self.link(self.evidence());self.declare()
        c=self.check();self.assertEqual(c['quantity']['billed_joint'],'4')
        self.assertEqual({m['batch_id'] for m in c['quantity']['members']},{first,second})
        another=deepcopy(capture());another['source']['stream_id']='otra-extraccion'
        cap2=self.add_capture(another);self.select([cap2]);self.link(self.evidence());self.declare()
        self.batch=first
        c=self.check()
        self.assertIn('coverage_identity_between_captures_unverified',c['quantity']['limitations'])
        self.assertIsNone(c['quantity']['billed_joint'])

    def test_capacity_limit_never_presents_a_partial_total_as_complete(self):
        self.batch=self.import_book(book([('15/08/2026',10,20,30,'A')]*1001),'1001_FILAS_FICTICIAS.xlsx')
        self.select([self.add_capture()]);self.link(self.evidence());self.declare()
        c=self.check()
        self.assertIn('candidate_limit_1000',c['quantity']['limitations'])
        self.assertEqual(c['quantity']['state'],'no_concluyente')
        self.assertIsNone(c['quantity']['billed_joint']);self.assertIsNone(c['units_assigned'])

    def test_versions_resource_permissions_csrf_and_revocation(self):
        self.ready();e=self.evidence()
        self.assertEqual(self.declare(expected_version=e['dataset_version']-1).status_code,409)
        self.assertEqual(self.declare(expected_revision_version=e['revision_version']+1).status_code,409)
        target=self.base()+'/rows/2/authorization-input'
        self.assertEqual(self.client.post(target,json={}).status_code,403)
        writer=connect(self.root)
        try:
            writer.execute('BEGIN IMMEDIATE')
            writer.execute('UPDATE datasets SET version=version WHERE id=?',(self.dataset['id'],))
            start=monotonic()
            self.assertEqual(self.client.get(self.base()+'/rows/2/authorization-check-preview').status_code,200)
            self.assertLess(monotonic()-start,3)
        finally:writer.rollback();writer.close()
        other=self.client.post('/api/datasets',headers=self.headers(),json={'label':'Otro conjunto ficticio'}).json()
        self.assertEqual(self.client.get(f'/api/datasets/{other["id"]}/batches/{self.batch}/rows/2/authorization-check-preview').status_code,404)
        with TestClient(create_app(self.root,public_origin=ORIGIN,processing_enabled=False),base_url=ORIGIN) as viewer:
            login=viewer.post('/api/session',headers={'Origin':ORIGIN},json={'username':'viewer','password':PASSWORD}).json()
            self.assertEqual(viewer.get(self.base()+'/rows/2/authorization-check-preview').status_code,403)
            body={'expected_version':e['dataset_version'],'expected_revision_version':e['revision_version'],'kind':'quantity_unit','state':'declared','value':'practica','provenance':'Declaración ficticia sin permiso.','locator':'FICT!2'}
            self.assertEqual(viewer.post(target,headers={'Origin':ORIGIN,'X-CSRF-Token':login['csrf_token']},json=body).status_code,403)
        conn=connect(self.root)
        try:
            session=conn.execute("SELECT token_hash FROM sessions s JOIN users u ON u.id=s.user_id WHERE u.username='owner' ORDER BY s.created_at DESC LIMIT 1").fetchone()[0]
            def change():conn.execute('UPDATE datasets SET version=version+1 WHERE id=?',(self.dataset['id'],))
            with self.assertRaises(Problem) as ctx:preview(conn,self.root,session,self.dataset['id'],self.batch,2,after_read=change)
            self.assertEqual(ctx.exception.status,409)
            self.dataset['version']+=1;e=self.evidence()
            def revoke():conn.execute("UPDATE users SET active=0 WHERE username='owner'")
            with self.assertRaises(Problem):save_input(conn,self.root,session,self.dataset['id'],self.batch,2,e['dataset_version'],e['revision_version'],'quantity_unit','declared','practica','Procedencia ficticia de prueba.','FICT!2',after_prepare=revoke)
            self.assertEqual(conn.execute('SELECT count(*) FROM authorization_input_versions').fetchone()[0],0)
        finally:conn.close()

    def test_quantity_changes_apply_without_relink_and_old_link_blocks(self):
        self.ready();self.declare()
        for field,value in [('G','1'),('K','Otra práctica ficticia')]:
            e=self.evidence()
            r=self.client.post(self.base()+'/rows/2/work-fields',headers=self.headers(),json={
                'expected_dataset_version':e['dataset_version'],'expected_revision_version':e['revision_version'],
                'field':field,'value':value,'reason':'Corrección ficticia con historia para probar dependencias.'})
            self.assertEqual(r.status_code,200,r.text);self.dataset['version']=r.json()['dataset_version']
            c=self.check()
            self.assertEqual(c['quantity']['state'],'sin_observaciones' if field=='G' else 'no_concluyente')
            self.assertIsNone(c['units_assigned'])

    def test_unknown_text_is_preserved_and_fixtures_are_deterministic(self):
        from scripts.create_b03_demo import sources
        from app.authorization_json import parse_authorization
        self.assertEqual(sources(),sources())
        self.assertEqual(len(parse_authorization(sources()['B03_FICTICIO.json']).canonical['orders']),7)
        self.ready();self.declare(kind='incorporation',value='Fecha pendiente de precisar')
        c=self.check();self.assertEqual(c['temporal']['state'],'no_concluyente')
        self.assertEqual(c['inputs']['incorporation']['current']['value'],'Fecha pendiente de precisar')
        self.assertEqual(self.declare(kind='incorporation',value='x'*81).status_code,422)

    def test_real_declarations_never_validate_sources_and_export_history(self):
        self.batch=self.import_book(book([('15/08/2026',10,20,30,'A')]),'B03_FICTICIO.xlsx')
        data=capture();data['data_origin']='real_unvalidated'
        cap=self.add_capture(data);self.select([cap],mode='real_unvalidated');self.link(self.evidence());self.declare()
        c=self.check();self.assertEqual(c['mode'],'real_unvalidated')
        self.assertEqual(c['source_validation'],'not_verified')
        self.assertIsNone(c['proposal_amount_ars'])
        self.assertEqual(c['inputs']['quantity_unit']['current']['data_origin'],'real_unvalidated')
        # An export must preserve declarations; it must not call the preview engine.
        r=self.client.post(self.run_url(),headers=self.headers(),json={'expected_version':self.dataset['version']})
        self.assertEqual(r.status_code,201,r.text)
        r=self.client.get(self.base()+'/export-provisional')
        self.assertEqual(r.status_code,200,r.text[:100])
        with ZipFile(BytesIO(r.content)) as z:
            self.assertIn('authorization_inputs.jsonl',z.namelist())
            self.assertIn(b'real_unvalidated',z.read('authorization_inputs.jsonl'))


if __name__=='__main__':unittest.main()

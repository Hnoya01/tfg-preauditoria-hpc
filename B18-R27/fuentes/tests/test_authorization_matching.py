"""B02 uses only invented invoices and authorization captures."""

from io import BytesIO
import json
import unittest
from zipfile import ZipFile

from fastapi.testclient import TestClient

from app.api import create_app
from app.authorization_matching import dni, save_link, save_scope
from app.controls import _run_summary
from app.db import connect
from app.service import Problem
from scripts.create_b02_demo import capture
from tests import test_authorization_imports as intake
from tests.test_p02 import book, PASSWORD, ORIGIN


class MatchingTests(unittest.TestCase):
    setUp = intake.AuthorizationImportTests.setUp
    tearDown = intake.AuthorizationImportTests.tearDown
    headers = intake.AuthorizationImportTests.headers
    import_book = intake.AuthorizationImportTests.import_book
    run_url = intake.AuthorizationImportTests.run_url
    alerts = intake.AuthorizationImportTests.alerts
    decide = intake.AuthorizationImportTests.decide
    url = intake.AuthorizationImportTests.url
    stage = intake.AuthorizationImportTests.stage
    preview = intake.AuthorizationImportTests.preview
    confirm = intake.AuthorizationImportTests.confirm

    def base(self):
        return f'/api/datasets/{self.dataset["id"]}/batches/{self.batch}'

    def add_capture(self, data=None):
        upload = self.stage(intake.encode(data or capture())).json()
        result = self.confirm(upload)
        self.assertEqual(result.status_code, 201, result.text)
        return result.json()['id']

    def select(self, ids, **overrides):
        result = self.client.post(self.base() + '/authorization-scope', headers=self.headers(), json={
            'expected_version': self.dataset['version'], 'capture_ids': ids, 'mode': 'synthetic_demo',
            'synthetic_invoice_confirmed': True, 'note': 'Fuentes y Excel inventados para el ensayo B02.', **overrides})
        if result.status_code == 200:
            self.dataset['version'] = result.json()['dataset_version']
        return result

    def evidence(self, number=2):
        result = self.client.get(self.base() + f'/rows/{number}/authorization-correspondence')
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def link(self, data, state='selected', key=None, **overrides):
        key = key or next((c['key'] for c in data['candidates'] if c['compatibility'] == 'compatible'), None)
        result = self.client.post(self.base() + f'/rows/{data["source_row"]}/authorization-link', headers=self.headers(), json={
            'expected_version': data['dataset_version'], 'expected_revision_version': data['revision_version'],
            'basis_sha256': data['basis_sha256'], 'state': state, 'candidate_key': key if state == 'selected' else None,
            'note': 'Cotejo humano ficticio con identificación explícita del ítem.', **overrides})
        if result.status_code == 200:
            self.dataset['version'] = result.json()['dataset_version']
        return result

    def test_recognized_identity_and_no_scope_do_not_imply_rejection(self):
        self.assertEqual(dni('000123/4'), '1234')
        self.assertEqual(dni('1234'), '1234')
        for value in (None, 'FICT-1234', '000/0', '001234', '12.34', '1234 ', 1234):
            self.assertIsNone(dni(value))
        data = self.evidence()
        self.assertEqual(data['state'], 'scope_missing')
        self.assertEqual(data['authorization_result'], 'no_concluyente')
        self.assertIsNone(data['units_assigned'])

    def test_explicit_scope_partial_and_contradiction_are_not_approvals(self):
        identity = self.add_capture()
        self.assertEqual(self.select([identity], synthetic_invoice_confirmed=False).status_code, 422)
        self.assertEqual(self.select([identity], mode='real_unvalidated').status_code, 422)
        self.assertEqual(self.select([identity]).status_code, 200)
        data = self.evidence()
        self.assertEqual(data['state'], 'unambiguous_candidate')
        candidate = next(c for c in data['candidates'] if c['compatibility'] == 'compatible')
        self.assertEqual(candidate['resolution']['state'], 'declared_authorized')
        self.assertEqual(candidate['item']['requested_quantity'], '2')
        self.assertEqual(candidate['resolution']['records'][0]['authorized_quantity'], '1')
        self.assertFalse(candidate['resolution']['applicable_resolution_confirmed'])
        conflict = next(c for c in self.evidence(3)['candidates'] if c['compatibility'] == 'compatible')
        self.assertEqual(conflict['resolution']['state'], 'apparent_conflict')
        self.assertEqual(self.link(self.evidence(3)).status_code, 200)
        self.assertEqual(self.evidence(3)['authorization_result'], 'no_concluyente')
        conn = connect(self.root)
        try:
            self.assertEqual(conn.execute('SELECT count(*) FROM control_runs').fetchone()[0], 1)
            for table in ('review_decisions', 'economic_verifications', 'proposal_versions'):
                self.assertEqual(conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0], 0)
        finally:
            conn.close()

    def test_ambiguous_inpatient_and_absence_with_unknown_coverage(self):
        self.batch = self.import_book(book([(f'{d}/08/2026', 10, 20, 30, 'I' if d == 18 else 'A') for d in (17,18,19)]), 'FICTICIO.xlsx')
        identity = self.add_capture()
        self.assertEqual(self.select([identity]).status_code, 200)
        data = self.evidence()
        self.assertEqual(data['state'], 'ambiguous')
        self.assertIsNone(data['units_assigned'])
        self.assertEqual(sum(c['compatibility'] == 'compatible' for c in data['candidates']), 2)
        self.assertEqual(self.evidence(3)['state'], 'outside_scope')
        self.assertEqual(self.link(self.evidence(3), state='unresolved').status_code, 409)
        absent = self.evidence(4)
        self.assertEqual(absent['state'], 'incompatible_candidates')
        self.assertEqual(absent['authorization_result'], 'no_concluyente')
        self.assertEqual(self.link(data, key='inventado').status_code, 422)

    def test_codes_provider_description_and_dates_never_use_name_or_order_number(self):
        raw = capture()
        raw['orders'] = [raw['orders'][0]]
        raw['orders'][0]['items'][0]['full_code'] = '12345600'
        identity = self.add_capture(raw); self.select([identity])
        self.assertEqual(self.evidence()['state'], 'no_authorization_located')
        raw['source']['capture_id'] = 'FICT-2'
        raw['orders'][0]['items'][0]['full_code'] = '123456'
        raw['orders'][0]['provider'] = 'OTRO'
        identity = self.add_capture(raw); self.select([identity])
        self.assertEqual(self.evidence()['state'], 'incompatible_candidates')
        raw['source']['capture_id'] = 'FICT-3'; raw['orders'][0]['provider'] = 'HPC'
        raw['orders'][0]['items'][0]['service_date'] = None
        identity = self.add_capture(raw); self.select([identity])
        self.assertEqual(self.evidence()['state'], 'needs_review')
        self.assertEqual(self.link(self.evidence()).status_code, 422)
        raw['source']['capture_id'] = 'FICT-4'; raw['orders'][0]['items'][0]['service_date'] = '2026-08-15'
        raw['orders'][0]['items'][0]['description'] = 'Otra descripción'
        identity = self.add_capture(raw); self.select([identity])
        self.assertEqual(self.evidence()['state'], 'needs_review')
        raw['source']['capture_id'] = 'FICT-BADDATE'
        raw['orders'][0]['items'][0]['description'] = 'Práctica ficticia'
        raw['orders'][0]['items'][0]['service_date'] = '2026-08-15T12'
        identity = self.add_capture(raw); self.select([identity])
        self.assertEqual(self.evidence()['state'], 'needs_review')

    def test_human_versions_stale_writes_and_independent_results(self):
        alert = self.alerts()['items'][0]
        decision = self.decide([{'id':alert['id'], 'expected_version':alert['version']}])
        self.dataset['version'] = decision.json()['dataset_version']
        identity = self.add_capture(); self.select([identity])
        old = self.evidence()
        self.assertEqual(self.link(old).status_code, 200)
        self.assertEqual(self.link(old).status_code, 409)
        current = self.evidence()
        self.assertEqual(current['human_link']['current']['freshness'], 'current')
        self.assertEqual(self.link(current, state='unresolved').status_code, 200)
        current = self.evidence()
        self.assertEqual(current['human_link']['current']['state'], 'unresolved')
        self.assertEqual(len(current['human_link']['history']), 2)
        self.assertEqual(next(a for a in self.alerts()['items'] if a['id'] == alert['id'])['decision'], 'descartada')
        conn = connect(self.root)
        try:
            summary = _run_summary(conn, self.dataset['id'], self.run['id'])
            self.assertEqual(set(summary['affected_rules']), {'RN09','RN10','RN11','RN18'})
        finally:
            conn.close()

    def test_new_capture_affects_selected_scope_and_old_link_without_fallback(self):
        first = self.add_capture(); self.select([first]); self.link(self.evidence())
        raw = capture(); raw['source']['capture_id'] = 'FICT-new'
        raw['coverage']['limitations'].append('Otra captura ficticia.')
        second = self.add_capture(raw)
        self.assertEqual(self.evidence()['state'], 'requires_update')
        self.assertEqual(self.evidence()['human_link']['current']['freshness'], 'requires_update')
        self.assertEqual(self.select([first]).status_code, 409)
        self.assertEqual(self.select([first,second]).status_code, 422)
        self.assertEqual(self.select([second]).status_code, 200)
        self.assertEqual(self.evidence()['human_link']['current']['freshness'], 'requires_update')
        scope = self.client.get(self.base() + '/authorization-scope').json()
        self.assertEqual(len(scope['history']), 2)

    def test_missing_original_and_changed_fields_affect_only_correspondence_dependencies(self):
        identity = self.add_capture(); self.select([identity]); self.link(self.evidence())
        for field, value, freshness in [('G', '9', 'current'), ('K', 'Otra descripción ficticia', 'requires_update')]:
            detail = self.evidence()
            result = self.client.post(self.base() + '/rows/2/work-fields', json={
                'expected_dataset_version': detail['dataset_version'], 'expected_revision_version':detail['revision_version'],
                'field':field, 'value':value, 'reason':'Corrección ficticia para comprobar dependencia selectiva.'}, headers=self.headers())
            self.assertEqual(result.status_code,200,result.text)
            self.dataset['version']=result.json()['dataset_version']
            self.assertEqual(self.evidence()['human_link']['current']['freshness'], freshness)
        conn = connect(self.root)
        try:
            sha = conn.execute('SELECT source_sha256 FROM authorization_uploads').fetchone()[0]
        finally:
            conn.close()
        (self.root / 'objects' / sha[:2] / sha).write_bytes(b'alterado')
        self.assertEqual(self.evidence()['state'], 'requires_update')
        self.assertEqual(self.evidence()['human_link']['current']['freshness'], 'requires_update')

    def test_recheck_permissions_and_versions_at_publication(self):
        identity = self.add_capture(); self.select([identity]); data = self.evidence()
        conn = connect(self.root)
        def change():
            other=connect(self.root); other.execute('UPDATE datasets SET version=version+1 WHERE id=?',(self.dataset['id'],)); other.close()
        try:
            with self.assertRaises(Problem) as exc:
                save_link(conn,self.root,self.digest,self.dataset['id'],self.batch,2,data['dataset_version'],data['revision_version'],
                          data['basis_sha256'],'unresolved',None,'Prueba ficticia concurrente.',after_prepare=change)
            self.assertEqual(exc.exception.status,409)
            self.assertEqual(conn.execute('SELECT count(*) FROM authorization_link_versions').fetchone()[0],0)
        finally:
            conn.close()
        self.dataset['version'] += 1
        data = self.evidence()
        with TestClient(create_app(self.root,public_origin=ORIGIN),base_url=ORIGIN) as outsider:
            login=outsider.post('/api/session',json={'username':'viewer','password':PASSWORD},headers={'Origin':ORIGIN}).json()
            self.assertEqual(outsider.get(self.base()+'/authorization-scope').status_code,403)
            self.assertEqual(outsider.get(self.base()+'/rows/2/authorization-correspondence').status_code,403)
            self.assertEqual(outsider.post(self.base()+'/authorization-scope',headers={'Origin':ORIGIN,'X-CSRF-Token':login['csrf_token']},json={
                'expected_version':self.dataset['version'],'capture_ids':[identity],'mode':'synthetic_demo',
                'synthetic_invoice_confirmed':True,'note':'Acceso ficticio sin permisos.'}).status_code,403)
        other=self.client.post('/api/datasets',json={'label':'Otro conjunto ficticio'},headers=self.headers()).json()
        url=f'/api/datasets/{other["id"]}/batches/{self.batch}'
        self.assertEqual(self.client.get(url+'/authorization-scope').status_code,404)
        self.assertEqual(self.client.get(url+'/rows/2/authorization-correspondence').status_code,404)
        data=self.evidence()
        conn=connect(self.root)
        def revoke():
            other=connect(self.root); other.execute('DELETE FROM sessions WHERE token_hash=?',(self.digest,)); other.close()
        try:
            with self.assertRaises(Problem) as exc:
                save_link(conn,self.root,self.digest,self.dataset['id'],self.batch,2,data['dataset_version'],data['revision_version'],
                          data['basis_sha256'],'unresolved',None,'Sesión revocada durante prueba ficticia.',after_prepare=revoke)
            self.assertEqual(exc.exception.status,401)
        finally:
            conn.close()

    def test_scope_publication_rechecks_version_and_repeated_ids_cannot_be_selected(self):
        raw=capture()
        raw['orders'][0]['items'].append(dict(raw['orders'][0]['items'][0]))
        identity=self.add_capture(raw)
        conn=connect(self.root)
        def change():
            other=connect(self.root); other.execute('UPDATE datasets SET version=version+1 WHERE id=?',(self.dataset['id'],)); other.close()
        try:
            with self.assertRaises(Problem) as exc:
                save_scope(conn,self.root,self.digest,self.dataset['id'],self.batch,self.dataset['version'],[identity],
                           'synthetic_demo','Selección ficticia con cambio concurrente.',True,after_prepare=change)
            self.assertEqual(exc.exception.status,409)
            self.assertEqual(conn.execute('SELECT count(*) FROM authorization_match_scopes').fetchone()[0],0)
        finally:
            conn.close()
        self.dataset['version']+=1
        self.select([identity])
        data=self.evidence()
        self.assertEqual(data['state'],'ambiguous')
        candidate=next(c for c in data['candidates'] if c['checks']['date'])
        self.assertFalse(candidate['checks']['unique_ids'])
        self.assertEqual(self.link(data,key=candidate['key']).status_code,422)

    def test_link_change_invalidates_only_its_row_after_explicit_analysis(self):
        identity=self.add_capture(); self.select([identity])
        analyzed=self.client.post(self.run_url(),json={'expected_version':self.dataset['version']},headers=self.headers())
        self.assertEqual(analyzed.status_code,201,analyzed.text)
        self.dataset['version']+=1
        self.link(self.evidence())
        conn=connect(self.root)
        try:
            summary=_run_summary(conn,self.dataset['id'],analyzed.json()['id'])
            self.assertEqual(summary['global_affected_rules'],[])
            self.assertEqual(set(summary['affected_rows']['2']),{'RN09','RN10','RN11','RN18'})
            self.assertNotIn('3',summary['affected_rows'])
        finally:
            conn.close()

    def test_provisional_export_keeps_human_history_and_no_money(self):
        identity=self.add_capture(); self.select([identity]); self.link(self.evidence())
        response=self.client.get(self.base()+'/export-provisional')
        self.assertEqual(response.status_code,200,response.text)
        with ZipFile(BytesIO(response.content)) as archive:
            links=[json.loads(r) for r in archive.read('authorization_links.jsonl').splitlines()]
            scopes=[json.loads(r) for r in archive.read('authorization_scopes.jsonl').splitlines()]
            manifest=json.loads(archive.read('manifest.json'))
        self.assertEqual(len(links),1); self.assertEqual(len(scopes),1)
        self.assertIsNone(links[0]['units_assigned']); self.assertIsNone(manifest['current_proposal_total_ars'])
        self.assertEqual(links[0]['human_link']['current']['freshness'],'current')

    def test_large_ambiguous_source_is_explicitly_limited_and_cannot_assign(self):
        raw=capture(); raw['orders']=raw['orders'][:1]
        order=raw['orders'][0]
        template=order['items'][0]
        order['items']=[{**template,'item_id':f'FICT-LARGE-{i}'} for i in range(201)]
        resolution=order['resolutions'][0]
        order['resolutions']=[{**resolution,'resolution_id':f'FICT-R-{i}',
                              'item_ids':[item['item_id'] for item in order['items']],
                              'reason':'Texto completamente ficticio. '*50} for i in range(21)]
        identity=self.add_capture(raw); self.select([identity])
        data=self.evidence()
        self.assertEqual(data['state'],'candidate_limit')
        self.assertEqual(data['candidate_count_total'],201)
        self.assertEqual(len(data['candidates']),200)
        self.assertEqual(self.link(data,key=data['candidates'][0]['key']).status_code,409)
        resolution=data['candidates'][0]['resolution']
        self.assertTrue(resolution['records_truncated'])
        self.assertEqual(resolution['records_total'],21)
        self.assertEqual(len(resolution['records']),20)
        self.assertTrue(resolution['records'][0]['reason_truncated'])
        self.assertTrue(resolution['records'][0]['item_ids_truncated'])


if __name__ == '__main__':
    unittest.main()

"""C2 uses only synthetic invoices, isolated sources and temporary databases."""
from io import BytesIO
import json
import sqlite3
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from app.db import connect
from tests import test_closure as fixture


class NewRevisionTests(unittest.TestCase):
    setUp=fixture.ClosureTests.setUp
    tearDown=fixture.ClosureTests.tearDown
    headers=fixture.ClosureTests.headers
    import_book=fixture.ClosureTests.import_book
    run_url=fixture.ClosureTests.run_url
    alerts=fixture.ClosureTests.alerts
    decide=fixture.ClosureTests.decide
    base=fixture.ClosureTests.base
    preview=fixture.ClosureTests.preview
    resolve_alerts=fixture.ClosureTests.resolve_alerts
    justify=fixture.ClosureTests.justify
    close=fixture.ClosureTests.close

    def history(self):
        r=self.client.get(self.base()+'/revisions');self.assertEqual(r.status_code,200,r.text);return r.json()

    def freeze(self):
        self.resolve_alerts();p=self.justify();r=self.close(p);self.assertEqual(r.status_code,201,r.text)
        return r.json(),self.client.get(self.base()+'/export-closed').content

    def start(self,page=None,**overrides):
        p=page or self.history()
        body={'previous_revision_id':p['revision_id'],'expected_dataset_version':p['dataset_version'],
              'expected_revision_version':p['revision_version'],'reason':'FICTICIO nueva evidencia para una revisión explícita.',**overrides}
        return self.client.post(self.base()+'/revisions',headers=self.headers(),json=body)

    def test_successor_shares_rows_preserves_history_and_requires_explicit_analysis(self):
        closed,frozen=self.freeze();old=self.history()
        c=connect(self.root)
        before={t:[tuple(x) for x in c.execute(f'SELECT * FROM {t} ORDER BY 1,2')] for t in
                ('invoice_imports','invoice_rows','control_runs','review_decisions','revision_closures','review_limitations')}
        c.close()
        r=self.start(old);self.assertEqual(r.status_code,201,r.text);new=r.json()
        self.assertNotEqual(new['revision_id'],closed['revision_id']);self.assertFalse(new['analysis_started'])
        self.assertEqual(new['opening_basis']['historical_decision_ids'],json.loads(ZipFile(BytesIO(frozen)).read('manifest.json'))['closure']['decision_ids'])
        c=connect(self.root)
        try:
            for t,data in before.items():self.assertEqual([tuple(x) for x in c.execute(f'SELECT * FROM {t} ORDER BY 1,2')],data,t)
            self.assertEqual(c.execute('SELECT count(*) FROM current_invoice_imports WHERE batch_id=?',(self.batch,)).fetchone()[0],1)
            self.assertEqual(c.execute('SELECT revision_id FROM invoice_imports WHERE batch_id=?',(self.batch,)).fetchone()[0],closed['revision_id'])
            self.assertIsNone(c.execute('PRAGMA foreign_key_check').fetchone())
        finally:c.close()
        self.assertEqual(self.preview()['latest_run_id'],None)
        self.assertEqual(self.alerts()['items'],[])
        self.assertEqual(self.client.get(self.base()+'/control-runs').json(),[])
        self.assertEqual(self.client.get(self.base()+'/export-provisional').status_code,409)
        self.dataset['version']=new['dataset_version']
        analyzed=self.client.post(self.run_url(),headers=self.headers(),json={'expected_version':self.dataset['version']})
        self.assertEqual(analyzed.status_code,201,analyzed.text)
        self.assertEqual(analyzed.json()['revision_id'],new['revision_id'])
        comparisons=analyzed.json()['snapshot']['comparison_imports']
        self.assertEqual(len(comparisons),len({x['import_id'] for x in comparisons}))
        self.assertTrue(all(a['decision']=='pendiente' for a in self.alerts()['items']))
        provisional=self.client.get(self.base()+'/export-provisional');self.assertEqual(provisional.status_code,200,provisional.text[:80])
        with ZipFile(BytesIO(provisional.content)) as z:
            self.assertEqual(z.read('decisions.jsonl'),b'')
            self.assertEqual(json.loads(z.read('manifest.json'))['revision_origin']['previous_revision_id'],closed['revision_id'])
        self.assertEqual(self.client.get(self.base()+'/export-closed?revision_id='+closed['revision_id']).content,frozen)

    def test_two_closures_are_addressable_and_original_work_is_preserved(self):
        page=self.preview()
        r=self.client.post(self.base()+'/rows/2/work-fields',headers=self.headers(),json={
            'expected_dataset_version':page['dataset_version'],'expected_revision_version':page['revision_version'],
            'field':'G','value':'4','reason':'FICTICIO corrección anterior al primer cierre.'})
        self.assertEqual(r.status_code,200,r.text)
        self.dataset['version']=r.json()['dataset_version']
        first,bytes1=self.freeze();opened=self.start();self.assertEqual(opened.status_code,201,opened.text)
        c=connect(self.root)
        try:
            self.assertEqual(c.execute('SELECT count(*) FROM work_fields WHERE import_id=?',(self.history()['import_id'],)).fetchone()[0],0)
            self.assertEqual(c.execute('SELECT count(*) FROM revision_work_fields WHERE revision_id=?',(first['revision_id'],)).fetchone()[0],1)
        finally:c.close()
        page=self.justify();second=self.close(page);self.assertEqual(second.status_code,201,second.text)
        bytes2=self.client.get(self.base()+'/export-closed').content
        self.assertNotEqual(bytes1,bytes2)
        self.assertEqual(self.client.get(self.base()+'/export-closed?revision_id='+first['revision_id']).content,bytes1)
        self.assertEqual(self.client.get(self.base()+'/export-closed?revision_id='+second.json()['revision_id']).content,bytes2)
        self.assertEqual(self.client.get(self.base()+'/export-closed?revision_id=not-a-revision').status_code,404)
        self.assertEqual(len(self.history()['items']),2)
        third=self.start();self.assertEqual(third.status_code,201,third.text);self.assertEqual(third.json()['ordinal'],3)

    def test_duplicate_stale_and_wrong_predecessor_do_not_create_partial_revision(self):
        self.assertEqual(self.start().status_code,409)
        closed,_=self.freeze();p=self.history()
        self.assertEqual(self.start(p,previous_revision_id='other').status_code,409)
        self.assertEqual(self.start(p,expected_revision_version=p['revision_version']-1).status_code,409)
        self.assertEqual(self.start(p,reason='').status_code,422)
        self.assertEqual(self.start(p).status_code,201)
        self.assertEqual(self.start(p).status_code,409)
        self.assertEqual(len(self.history()['items']),2)
        self.assertEqual(self.history()['items'][0]['state'],'cerrada')

    def test_transaction_rollback_and_revocation_at_commit(self):
        from app.revisions import start
        from app.service import Problem
        self.freeze();p=self.history();args=(self.digest,self.dataset['id'],self.batch,p['revision_id'],p['dataset_version'],p['revision_version'],'FICTICIO ensayo atómico de nueva revisión.')
        c=connect(self.root)
        try:
            with patch('app.revisions.event',side_effect=RuntimeError('FICTICIO rollback')):
                with self.assertRaises(RuntimeError):start(c,*args)
            self.assertEqual(c.execute('SELECT count(*) FROM revision_openings').fetchone()[0],0)
            self.assertEqual(self.history()['revision_id'],p['revision_id'])
            def revoke():
                other=connect(self.root);other.execute('DELETE FROM sessions WHERE token_hash=?',(self.digest,));other.close()
            with self.assertRaises(Problem) as e:start(c,*args,before_commit=revoke)
            self.assertEqual(e.exception.status,401)
            self.assertEqual(c.execute('SELECT count(*) FROM revision_openings').fetchone()[0],0)
        finally:c.close()

    def test_csrf_viewer_and_foreign_dataset_are_rejected(self):
        from app.api import create_app
        from fastapi.testclient import TestClient
        from tests.test_p02 import ORIGIN,PASSWORD
        self.freeze();p=self.history()
        self.assertEqual(self.client.post(self.base()+'/revisions',json={}).status_code,403)
        with TestClient(create_app(self.root,public_origin=ORIGIN,processing_enabled=False),base_url=ORIGIN) as viewer:
            login=viewer.post('/api/session',headers={'Origin':ORIGIN},json={'username':'viewer','password':PASSWORD})
            h={'Origin':ORIGIN,'X-CSRF-Token':login.json()['csrf_token']}
            self.assertEqual(viewer.get(self.base()+'/revisions').status_code,403)
            self.assertEqual(viewer.post(self.base()+'/revisions',headers=h,json={
                'previous_revision_id':p['revision_id'],'expected_dataset_version':p['dataset_version'],
                'expected_revision_version':p['revision_version'],'reason':'FICTICIO sin permiso de revisión.'}).status_code,403)
        other=self.client.post('/api/datasets',headers=self.headers(),json={'label':'OTRO FICTICIO'}).json()
        foreign=f'/api/datasets/{other["id"]}/batches/{self.batch}'
        self.assertEqual(self.client.get(foreign+'/revisions').status_code,404)
        self.assertEqual(self.client.get(foreign+'/export-closed?revision_id='+p['revision_id']).status_code,404)

    def test_sources_registered_after_close_are_visible_without_changing_frozen_capture(self):
        from tests import test_hpc_comparison as values_fixture
        old,frozen=self.freeze()
        self.dataset['version']=self.history()['dataset_version']
        source=values_fixture.HpcComparisonTests.register_fictional_hpc(self)
        opened=self.start();self.assertEqual(opened.status_code,201,opened.text)
        basis=opened.json()['opening_basis']
        self.assertIn(source,basis['available_source_ids']);self.assertNotIn(source,basis['previous_source_ids'])
        self.assertEqual(self.client.get(self.base()+'/export-closed?revision_id='+old['revision_id']).content,frozen)
        self.assertIsNone(self.preview()['latest_run_id'])

    def test_provider_scope_is_historical_until_confirmed_for_the_new_revision(self):
        from tests import test_hpc_comparison as values_fixture
        source=values_fixture.HpcComparisonTests.register_fictional_hpc(self)
        p=self.preview()
        body={'expected_dataset_version':p['dataset_version'],'expected_revision_version':p['revision_version'],
              'source_id':source,'provider':'HPC','billing_unit':'unverified',
              'confirmation_note':'FICTICIO prestador declarado sin verificación económica.'}
        r=self.client.post(self.base()+'/provider-scope',headers=self.headers(),json=body)
        self.assertEqual(r.status_code,200,r.text);self.dataset['version']=r.json()['dataset_version']
        old,_=self.freeze();r=self.start();self.assertEqual(r.status_code,201,r.text)
        h=self.client.get(self.base()+'/provider-scope').json();self.assertIsNone(h['current'])
        self.dataset['version']=r.json()['dataset_version']
        analysis=self.client.post(self.run_url(),headers=self.headers(),json={'expected_version':self.dataset['version']})
        self.assertEqual(analysis.status_code,201,analysis.text);self.assertIsNone(analysis.json()['snapshot']['provider_scope'])
        p=self.preview();body.update(expected_dataset_version=p['dataset_version'],expected_revision_version=p['revision_version'])
        r=self.client.post(self.base()+'/provider-scope',headers=self.headers(),json=body)
        self.assertEqual(r.status_code,200,r.text)
        c=connect(self.root)
        try:
            self.assertEqual(c.execute('SELECT count(*) FROM batch_provider_scope_history WHERE batch_id=?',(self.batch,)).fetchone()[0],2)
            self.assertEqual(c.execute("SELECT count(*) FROM revision_input_owners WHERE kind='batch_provider_scope_history' AND revision_id=?",(old['revision_id'],)).fetchone()[0],1)
        finally:c.close()

    def test_authorization_inputs_require_reconfirmation_and_do_not_double_count(self):
        from tests import test_authorization_controls as authorization_fixture
        x=authorization_fixture.IntegratedAuthorizationTests();x.setUp()
        try:
            cap=x.ready();x.declare();x.declare(kind='incorporation',value='2026-08-16')
            run=x.analyze()
            page=x.client.post(x.base()+'/closure-preview',headers=x.headers()).json()
            # All alerts in this single fictional row can share a nonconclusive decision.
            selected=[{'id':a['id'],'expected_version':a['version']} for a in x.alerts()['items']]
            if selected:
                d=x.decide(selected,state='no_concluyente',foundation='FICTICIO conservar limitaciones para cierre.')
                self.assertEqual(d.status_code,200,d.text)
            page=x.client.post(x.base()+'/closure-preview',headers=x.headers()).json()
            for group in page['limitations']:
                r=x.client.post(x.base()+'/closure-limitations',headers=x.headers(),json={
                    'expected_dataset_version':page['dataset_version'],'expected_revision_version':page['revision_version'],
                    'group_key':group['group_key'],'scope_sha256':group['scope_sha256'],
                    'foundation':'FICTICIO evidencia administrativa sin verificar.'})
                self.assertEqual(r.status_code,201,r.text)
                page=x.client.post(x.base()+'/closure-preview',headers=x.headers()).json()
            r=x.client.post(x.base()+'/closure',headers=x.headers(),json={
                'expected_dataset_version':page['dataset_version'],'expected_revision_version':page['revision_version'],
                'preview_sha256':page['preview_sha256'],'confirmed_limitation_ids':[g['justification']['id'] for g in page['limitations']]})
            self.assertEqual(r.status_code,201,r.text)
            old=r.json()['revision_id'];frozen=x.client.get(x.base()+'/export-closed').content
            h=x.client.get(x.base()+'/revisions').json()
            r=x.client.post(x.base()+'/revisions',headers=x.headers(),json={
                'previous_revision_id':old,'expected_dataset_version':h['dataset_version'],
                'expected_revision_version':h['revision_version'],'reason':'FICTICIO nueva revisión con fuentes actualizadas.'})
            self.assertEqual(r.status_code,201,r.text);x.dataset['version']=r.json()['dataset_version']
            c=connect(x.root)
            try:
                for table in ('authorization_match_scopes','authorization_link_versions','authorization_input_versions'):
                    self.assertGreater(c.execute(f'SELECT count(*) FROM {table} WHERE batch_id=?',(x.batch,)).fetchone()[0],0)
                    self.assertEqual(c.execute(f'SELECT count(*) FROM current_{table} WHERE batch_id=?',(x.batch,)).fetchone()[0],0)
                self.assertEqual(c.execute('SELECT count(*) FROM invoice_rows WHERE import_id=?',(h['import_id'],)).fetchone()[0],1)
            finally:c.close()
            x.select([cap]);x.link(x.evidence());x.declare();x.declare(kind='incorporation',value='2026-08-16')
            fresh=x.analyze()
            cohort=next(iter(fresh['snapshot']['authorization_engine']['cohorts'].values()))
            self.assertEqual(len(cohort),1)
            self.assertEqual(x.results(fresh)['RN11']['evidence']['quantity']['billed_joint'],'2')
            self.assertEqual(x.client.get(x.base()+'/export-closed?revision_id='+old).content,frozen)
            historical=x.client.get(f'/api/datasets/{x.dataset["id"]}/control-runs/{run["id"]}')
            self.assertEqual(historical.status_code,200,historical.text)
            self.assertTrue(historical.json()['closed_revision'])
            with ZipFile(BytesIO(frozen)) as archive:
                captured=json.loads(archive.read('manifest.json'))['control_run']
            for key in ('affected_rules','affected_rows','global_affected_rules'):
                self.assertEqual(historical.json()[key],captured[key])
        finally:x.tearDown()


class RevisionMigrationTests(unittest.TestCase):
    def test_v20_backup_migration_preserves_inputs_and_failed_migration_rolls_back(self):
        from pathlib import Path
        from app.db import MIGRATIONS,migrate,backup_before_upgrade
        from app.security import create_user,issue_session,token_digest
        from app.service import create_dataset,create_batch,confirm_invoice
        from app.review import change_work_field
        from tests.temp_support import TemporaryDirectory
        from tests.test_p02 import PASSWORD,book
        with TemporaryDirectory(dir='.tmp') as directory:
            root=Path(directory);c=connect(root)
            try:
                old=tuple(m for m in MIGRATIONS if m[0]<=20);migrate(c,migrations=old)
                user=create_user(c,'c2-migration',PASSWORD,'admin');token,_=issue_session(c,user);digest=token_digest(token)
                d=create_dataset(c,digest,'FICTICIO migración C2')
                b,_=create_batch(c,root,digest,d['id'],d['version'],'MIGRACION_FICTICIA.xlsx',book([('15/08/2026',10,20,30)]))
                i,_=confirm_invoice(c,root,digest,d['id'],b['id'],'2026-08',b['dataset_version'])
                change_work_field(c,digest,d['id'],b['id'],2,'G','3','FICTICIO cambio previo a migración.',i['dataset_version'],1)
                before=[tuple(r) for r in c.execute('SELECT * FROM work_fields')]
                backup=backup_before_upgrade(c,root)
                broken=old+((21,dict(MIGRATIONS)[21]+('INVALID SQL',)),)
                with self.assertRaises(sqlite3.OperationalError):migrate(c,migrations=broken,allow_existing_upgrade=True)
                self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0],20)
                self.assertEqual([tuple(r) for r in c.execute('SELECT * FROM work_fields')],before)
                self.assertEqual(migrate(c,allow_existing_upgrade=True),MIGRATIONS[-1][0])
                self.assertEqual([tuple(r) for r in c.execute('SELECT * FROM work_fields')],before)
                self.assertIsNone(c.execute('PRAGMA foreign_key_check').fetchone())
                self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok')
                saved=sqlite3.connect(backup/'app.sqlite3')
                try:
                    self.assertEqual(saved.execute('PRAGMA user_version').fetchone()[0],20)
                    self.assertEqual(saved.execute('PRAGMA integrity_check').fetchone()[0],'ok')
                finally:saved.close()
            finally:c.close()

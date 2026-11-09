"""Synthetic UUID practice additions, exact identity, temporal versions and safety."""
from contextlib import closing
import hashlib,io,json,sqlite3,unittest,zipfile
from fastapi.testclient import TestClient
from tests import test_hpc_values as fixture
from tests.test_p02 import ORIGIN,PASSWORD,book
from app.api import create_app
from app.db import MIGRATIONS,connect,migrate,backup_before_upgrade
from app.local_hpc import save,listing,tariffs
from app.effective_hpc_values import EffectiveHpcValues
from app.values_v1 import candidate_values
from app.practice_families import catalog_families,classify_family
from app.service import Problem
from tests.temp_support import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch
from tests.test_p03 import fictional_values

class LocalHpcTests(unittest.TestCase):
    def setUp(self):
        def catalog(folder):
            _,manifest,_=fictional_values(folder);path=folder/'catalogo_ficticio.sqlite'
            with closing(sqlite3.connect(path)) as c, c:
                c.execute('ALTER TABLE hpc_catalog_practices ADD COLUMN seq INTEGER')
                c.execute('ALTER TABLE hpc_catalog_practices ADD COLUMN name TEXT')
                c.execute('ALTER TABLE hpc_catalog_practices ADD COLUMN area TEXT')
                c.execute('ALTER TABLE hpc_catalog_components ADD COLUMN component TEXT')
                c.execute('ALTER TABLE hpc_catalog_components ADD COLUMN part INTEGER')
                c.execute('ALTER TABLE hpc_catalog_components ADD COLUMN text_data TEXT')
            data=path.read_bytes();m=json.loads(manifest);sha=hashlib.sha256(data).hexdigest()
            m['files']['valores_convenios_base_2026-10-09.sqlite']={'sha256':sha,'bytes':len(data)}
            return data,json.dumps(m).encode(),sha
        self.f=fixture.HpcValueTests()
        with patch('tests.test_hpc_values.fictional_values',side_effect=catalog):self.f.setUp()
    def tearDown(self):self.f.tearDown()
    def payload(self,**changes):
        f=self.f
        return dict(expected_dataset_version=f.dataset['version'],code='987654321',description='Imagen propia ficticia',family='images',
            amount_ars='14.00',currency='ARS',unit_label='por práctica',active=True,effective_from='2026-08-16',
            document_id=f.document,page_number=1,excerpt='Tarifa ficticia documentada ARS14 por práctica completa.',reason='Alta exclusivamente ficticia para prueba de integración',**changes)
    def save(self,**changes):
        data=self.payload();data.update(changes);f=self.f
        r=save(f.conn,f.root,f.digest,f.dataset['id'],f.source,**data);f.dataset['version']=r['dataset_version'];return r
    def resolve(self,pid,day):
        f=self.f;t=next(t for t in tariffs(f.conn,f.dataset['id'],f.source) if t['local_id']==pid)
        return EffectiveHpcValues(f.conn,f.root,f.dataset['id'],f.source).resolve(t,day)
    def test_history_versions_baja_reactivate_no_original_mutation(self):
        f=self.f;before=f.conn.execute('SELECT source_sha256 FROM source_registry WHERE id=?',(f.source,)).fetchone()[0]
        first=self.save();self.assertIsNone(tariffs(f.conn,f.dataset['id'],f.source)[0]['seq'])
        self.assertEqual(self.resolve(first['id'],'2026-08-15')['selected'],False)
        self.assertEqual(self.resolve(first['id'],'2026-08-16')['recorded_amount'],'14.00')
        self.save(practice_id=first['id'],active=False,effective_from='2026-09-01')
        self.assertEqual(self.resolve(first['id'],'2026-09-01')['status'],'withdrawn_reference')
        self.save(practice_id=first['id'],amount_ars='16.00',effective_from='2026-10-01')
        self.assertEqual(self.resolve(first['id'],'2026-10-01')['recorded_amount'],'16.00')
        self.assertEqual(self.resolve(first['id'],'2026-08-16')['recorded_amount'],'14.00')
        self.assertEqual(len(listing(f.conn,f.digest,f.dataset['id'],f.source,'Imagen propia ficticia')[0]['versions']),3)
        self.assertEqual(f.conn.execute('SELECT source_sha256 FROM source_registry WHERE id=?',(f.source,)).fetchone()[0],before)
        for stmt in ('DELETE FROM local_hpc_versions','UPDATE local_hpc_practices SET code=\'x\''):
            with self.assertRaises(sqlite3.IntegrityError):f.conn.execute(stmt)
    def test_validation_duplicates_immutable_identity_and_stale(self):
        for change in ({'currency':'USD'},{'unit_label':''},{'amount_ars':'NaN'},{'active':False},{'document_id':'other'}):
            with self.assertRaises(Problem):self.save(**change)
        version=self.f.dataset['version'];p=self.save()
        for change in ({},{'practice_id':p['id'],'code':'different'},{'practice_id':p['id'],'expected_dataset_version':version},{'practice_id':p['id'],'effective_from':'2026-07-01'}):
            with self.assertRaises(Problem):self.save(**change)
        self.assertEqual(self.f.conn.execute('SELECT count(*) FROM local_hpc_versions').fetchone()[0],1)
    def test_classification_and_exact_code_no_prefix(self):
        f=self.f;self.save()
        codes,names,_=catalog_families(f.conn,f.root,f.dataset['id'])
        self.assertEqual(classify_family('987654321',codes,'Imagen propia ficticia',names),('images','exact_local_hpc_code'))
        for code in ('987654','9876543210'):
            self.assertEqual(candidate_values(f.conn,f.root,f.digest,f.dataset['id'],f.source,code,'2026-08-16','HPC')['tariff_total'],0)
    def test_api_and_end_to_end_exact_local_reference(self):
        f=self.f
        with TestClient(create_app(f.root,public_origin=ORIGIN),base_url=ORIGIN) as client:
            route=f'/api/datasets/{f.dataset["id"]}/sources/{f.source}/local-hpc'
            self.assertEqual(client.get(route).status_code,401)
            login=client.post('/api/session',headers={'Origin':ORIGIN},json={'username':'owner','password':PASSWORD}).json();headers={'Origin':ORIGIN,'X-CSRF-Token':login['csrf_token']}
            self.assertEqual(client.post(route,json=self.payload(),headers={'Origin':ORIGIN}).status_code,403)
            added=client.post(route,json=self.payload(),headers=headers);self.assertEqual(added.status_code,201,added.text);local=added.json();f.dataset['version']=local['dataset_version']
            content=book([('16/08/2026',11,21,32)]);out=io.BytesIO()
            with zipfile.ZipFile(io.BytesIO(content)) as inp,zipfile.ZipFile(out,'w') as z:
                for n in inp.namelist():
                    data=inp.read(n)
                    if n.endswith('sheet1.xml'):data=data.replace(b'<v>123456</v>',b'<v>987654321</v>').replace('Práctica ficticia'.encode(),'Imagen propia ficticia'.encode())
                    z.writestr(n,data)
            base=f'/api/datasets/{f.dataset["id"]}'
            r=client.post(base+'/batches',content=out.getvalue(),headers={**headers,'X-Expected-Version':str(f.dataset['version']),'X-Source-Filename':'factura-ficticia.xlsx','Content-Type':'application/octet-stream'});self.assertEqual(r.status_code,201,r.text);batch=r.json()['id']
            r=client.post(base+f'/batches/{batch}/invoice-import',headers=headers,json={'period':'2026-08','period_confirmed':True,'expected_version':r.json()['dataset_version']});self.assertEqual(r.status_code,201,r.text)
            scope_url=base+f'/batches/{batch}/provider-scope';scope=client.get(scope_url).json()
            r=client.post(scope_url,headers=headers,json={'source_id':f.source,'provider':'HPC','billing_unit':'unverified','confirmation_note':'Factura ficticia HPC de práctica propia','expected_dataset_version':scope['dataset_version'],'expected_revision_version':scope['revision_version']});self.assertEqual(r.status_code,200,r.text)
            search=client.get(base+f'/sources/{f.source}/value-candidates',params={'code':'987654321','provider':'HPC','performed_on':'2026-08-16'}).json()
            self.assertEqual(search['tariff_candidates'][0]['effective_reference']['recorded_amount'],'14.00')
            comparison=client.get(base+f'/batches/{batch}/hpc-comparison',params={'source_id':f.source}).json()['items'][0]
            self.assertEqual(comparison['candidate_total_if_ars_and_same_unit'],'28.00')
            self.assertEqual(comparison['difference_ars_if_comparable'],'4.00')
            board=client.post(base+f'/batches/{batch}/practice-search',headers=headers,
                json={'family':'images','reference_comparison_state':'differences'}).json()
            self.assertEqual(board['filtered_total'],1,board)
            board_ref=board['items'][0]['reference_comparison']
            self.assertEqual(board_ref['effective_reference']['value_version']['id'],local['version_id'])
            self.assertEqual(board_ref['recorded_amount'],'14.00')
            self.assertEqual(board_ref['candidate_total_if_ars_and_same_unit'],'28.00')
            self.assertEqual(board_ref['difference_ars_if_comparable'],'4.00')
            self.assertEqual(board_ref['declared_currency'],'ARS')
            economic=client.get(base+f'/batches/{batch}/rows/2/economic-applicability',params={'source_id':f.source}).json()
            self.assertEqual(economic['basis']['status'],'ready_for_applicability',economic)
            self.assertEqual(economic['basis']['identity_method'],'local_exact_code')
            self.assertEqual(economic['basis']['candidate']['rate_ars'],'14.00')
            self.assertEqual(economic['basis']['candidate']['value_version']['id'],local['version_id'])
            self.assertIn(local['id'],economic['reference_display']['source_locator'])
        for table in ('control_runs','row_economic_references','proposal_versions'):
            self.assertEqual(f.conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0],0)
    def test_migration_backup_rollback(self):
        with TemporaryDirectory(dir='.tmp') as t:
            root=Path(t);c=connect(root)
            try:
                migrate(c,MIGRATIONS[:28]);backup=backup_before_upgrade(c,root)
                with self.assertRaises(RuntimeError):migrate(c)
                with self.assertRaises(sqlite3.Error):migrate(c,MIGRATIONS[:28]+((29,dict(MIGRATIONS)[29]+('INVALID SQL',)),),allow_existing_upgrade=True)
                self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0],28)
                self.assertIsNone(c.execute("SELECT name FROM sqlite_master WHERE name='local_hpc_practices'").fetchone())
                self.assertEqual(migrate(c,allow_existing_upgrade=True),MIGRATIONS[-1][0])
                old=sqlite3.connect(backup/'app.sqlite3');self.assertEqual(old.execute('PRAGMA user_version').fetchone()[0],28);old.close()
            finally:c.close()
    def test_economic_dependencies_update_and_collision_is_not_silently_resolved(self):
        from tests import test_economic_applicability as economic_fixture
        from app.hpc_value_status import save_status
        e=economic_fixture.EconomicApplicabilityTests();e.setUp()
        try:
            page=e.reference()
            r=e.client.post(e.base()+'/rows/3/work-fields',headers=e.headers(),json={
                'expected_dataset_version':page['dataset_version'],'expected_revision_version':page['revision_version'],
                'field':'E','value':'123456ABC','reason':'Código propio ficticio completo, no equivalencia por prefijo.'})
            self.assertEqual(r.status_code,200,r.text);e.dataset['version']=r.json()['dataset_version']
            conn=connect(e.root)
            try:
                data=self.payload();data.update(expected_dataset_version=e.dataset['version'],document_id=e.agreement_id,code='123456ABC')
                created=save(conn,e.root,e.digest,e.dataset['id'],e.source_id,**data)
            finally:conn.close()
            e.dataset['version']=created['dataset_version'];e.confirm();e.analyze();run=e.run['id']
            self.assertEqual(e.results(run)['RN14']['difference_ars'],'4.00')
            exported=e.client.get(e.base()+'/export-provisional')
            self.assertEqual(exported.status_code,200,exported.text[:100])
            with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
                history=[json.loads(line) for line in archive.read('local_hpc_history.jsonl').splitlines()]
                self.assertEqual(history[0]['id'],created['id'])
                manifest=json.loads(archive.read('manifest.json'));obj=manifest['local_hpc']['objects'][0]
                self.assertEqual(hashlib.sha256(archive.read(obj['path'])).hexdigest(),obj['sha256'])
            conn=connect(e.root)
            try:
                data.update(expected_dataset_version=e.dataset['version'],practice_id=created['id'],amount_ars='16.00')
                updated=save(conn,e.root,e.digest,e.dataset['id'],e.source_id,**data)
            finally:conn.close()
            e.dataset['version']=updated['dataset_version']
            self.assertFalse(e.reference()['latest']['current'])
            self.assertEqual(e.results(run)['RN14']['freshness'],'requires_update')
            self.assertEqual(e.results(run)['RN13']['freshness'],'current')
            self.assertEqual(e.reference()['basis']['candidate']['rate_ars'],'16.00')
            # A local code also present in original source is explicitly ambiguous.
            conn=connect(e.root)
            try:
                data.update(expected_dataset_version=e.dataset['version'],practice_id=None,code='123456',effective_from='2026-07-01')
                duplicate=save(conn,e.root,e.digest,e.dataset['id'],e.source_id,**data)
            finally:conn.close()
            e.dataset['version']=duplicate['dataset_version']
            self.assertEqual(e.reference(2)['basis']['status'],'ambiguous_reference')
            self.assertTrue(any(duplicate['id'] in str(locator) for locator in e.reference(2)['basis']['candidate_locators']))
            compare=e.client.get(e.base()+'/hpc-comparison',params={'source_id':e.source_id,'source_row':2}).json()['items'][0]
            self.assertEqual(compare['status'],'ambiguous_hpc_tariff')
        finally:e.tearDown()
    def test_nonadmin_and_other_dataset_cannot_write_or_read_identity(self):
        from app.security import create_user,issue_session,token_digest
        from app.service import create_dataset
        f=self.f;self.save()
        uid=create_user(f.conn,'local-reader',PASSWORD,'reviewer');raw,_=issue_session(f.conn,uid);digest=token_digest(raw)
        f.conn.execute('INSERT INTO dataset_access VALUES (?,?,?)',(f.dataset['id'],uid,'reviewer'))
        with self.assertRaises(Problem) as denied:save(f.conn,f.root,digest,f.dataset['id'],f.source,**{**self.payload(),'code':'new'})
        self.assertEqual(denied.exception.status,403)
        stranger=create_user(f.conn,'local-stranger',PASSWORD,'reviewer');raw,_=issue_session(f.conn,stranger);other=token_digest(raw)
        with self.assertRaises(Problem):listing(f.conn,other,f.dataset['id'],f.source)
    def test_corrupt_local_document_blocks_without_fallback(self):
        from app.storage import object_path
        p=self.save();f=self.f
        sha=f.conn.execute('SELECT sha256 FROM evidence_documents WHERE id=?',(f.document,)).fetchone()[0]
        object_path(f.root,sha).write_bytes(b'corrupt fictitious document')
        resolved=self.resolve(p['id'],'2026-08-16')
        self.assertTrue(resolved['selected']);self.assertEqual(resolved['status'],'version_evidence_unverifiable');self.assertIsNone(resolved['recorded_amount'])
    def test_future_local_identity_does_not_change_legacy_basis_or_confirmation(self):
        from tests import test_economic_applicability as economic_fixture
        e=economic_fixture.EconomicApplicabilityTests();e.setUp()
        try:
            e.confirm();before=e.reference();c=connect(e.root)
            try:
                payload=self.payload();payload.update(expected_dataset_version=e.dataset['version'],code='123456',effective_from='2026-09-01',document_id=e.agreement_id)
                saved=save(c,e.root,e.digest,e.dataset['id'],e.source_id,**payload)
            finally:c.close()
            e.dataset['version']=saved['dataset_version'];after=e.reference()
            self.assertEqual(before['basis'],after['basis']);self.assertEqual(before['basis_sha256'],after['basis_sha256'])
            self.assertTrue(after['latest']['current'])
        finally:e.tearDown()

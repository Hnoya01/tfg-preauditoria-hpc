"""Mixed native UUID and catalog percentage changes, fictional data only."""
from unittest import TestCase,mock
from app import hpc_percentage
from app.local_hpc import save as save_local
from app.service import Problem
from tests import test_hpc_percentage as percentage_fixture


class LocalPercentageTests(TestCase):
    def setUp(self):
        percentage_fixture.PercentageTests.setUp(self)
        self.local_payload=dict(expected_dataset_version=self.dataset['version'],code='987654321',
            description='Imagen propia ficticia',family='images',amount_ars='2.05',currency='ARS',
            unit_label='por práctica',active=True,effective_from='2026-11-01',document_id=self.document,
            page_number=1,excerpt='Cláusula ficticia de alta propia',reason='Alta ficticia para porcentaje mixto')
        saved=self.save_local();self.pid=saved['id']
    tearDown=percentage_fixture.PercentageTests.tearDown
    def save_local(self,**changes):
        payload={**self.local_payload,'expected_dataset_version':self.dataset['version'],**changes}
        result=save_local(self.conn,self.root,self.digest,self.dataset['id'],self.source,**payload)
        self.dataset['version']=result['dataset_version'];return result
    def payload(self,**changes):
        return percentage_fixture.PercentageTests.payload(self,**{'tariff_seqs':[1],'local_ids':[self.pid],**changes})
    preview=percentage_fixture.PercentageTests.preview
    apply=percentage_fixture.PercentageTests.apply
    def test_mixed_update_identity_history_one_version_no_debits(self):
        p=self.preview()
        self.assertEqual(p['items'][0]['tariff_seq'],1)
        local=p['items'][1];self.assertNotIn('tariff_seq',local)
        self.assertEqual(local['local_id'],self.pid);self.assertEqual(local['after_ars'],'2.26')
        result=self.apply(p)
        self.assertEqual(result['dataset_version'],self.dataset['version']+1)
        self.assertEqual(result['versions'][1]['local_id'],self.pid)
        self.assertNotIn('tariff_seq',result['versions'][1])
        for table in ('hpc_value_versions','local_hpc_versions'):
            reason=self.conn.execute(f'SELECT reason FROM {table} WHERE ordinal=2').fetchone()[0]
            self.assertIn(result['operation_id'],reason)
        for table in ('control_runs','economic_verifications'):
            self.assertEqual(self.conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0],0)
        with self.assertRaises(Problem) as stale:self.apply(p)
        self.assertEqual(stale.exception.status,409)
    def test_native_only_and_bad_ids(self):
        p=self.preview(tariff_seqs=[]);self.assertEqual(len(p['items']),1)
        self.apply(p,tariff_seqs=[])
        self.dataset['version']+=1
        for ids in [[self.pid,self.pid],['123'],[123],['00000000-0000-0000-0000-000000000000']]:
            with self.subTest(ids=ids):
                with self.assertRaises(Problem):self.preview(local_ids=ids)
        with self.assertRaises(Problem):self.preview(tariff_seqs=[],local_ids=[])
        with self.assertRaises(Problem):self.preview(tariff_seqs=list(range(1,1001)))
    def test_mixed_failure_rolls_back_first_legacy_write_and_retry(self):
        p=self.preview()
        with mock.patch.object(hpc_percentage,'_insert_local_version',side_effect=RuntimeError('synthetic second write failure')):
            with self.assertRaises(RuntimeError):self.apply(p)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM hpc_value_versions').fetchone()[0],2)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM local_hpc_versions').fetchone()[0],1)
        self.assertEqual(self.conn.execute('SELECT version FROM datasets WHERE id=?',(self.dataset['id'],)).fetchone()[0],self.dataset['version'])
        self.apply(p)
    def test_exact_code_collisions_between_classes_both_directions(self):
        other=self.save_local(code='123456',description='Código coincidente ficticio')
        with self.assertRaises(Problem) as legacy:self.preview(local_ids=[])
        self.assertIn('simultáneas',str(legacy.exception))
        with self.assertRaises(Problem):self.preview(tariff_seqs=[],local_ids=[other['id']])
        # A prefix alone is not a collision.
        shorter=self.save_local(code='987654',description='Prefijo sin equivalencia ficticia')
        self.preview(tariff_seqs=[],local_ids=[shorter['id']])
    def test_withdrawn_and_future_native_reference_rejected(self):
        self.save_local(practice_id=self.pid,active=False,effective_from='2026-11-02')
        with self.assertRaises(Problem):self.preview()
        self.save_local(practice_id=self.pid,active=True,effective_from='2026-12-01')
        with self.assertRaises(Problem):self.preview(effective_from='2026-11-01')

    def test_native_api_only_defaults_and_preview_identity_tamper(self):
        from fastapi.testclient import TestClient
        from app.api import create_app
        route=f'/api/datasets/{self.dataset["id"]}/sources/{self.source}/hpc-percentage'
        payload=self.payload(tariff_seqs=[]);del payload['tariff_seqs']
        with TestClient(create_app(self.root,public_origin='https://testserver'),base_url='https://testserver') as client:
            client.cookies.set('tfg_session',self.raw_token)
            headers={'Origin':'https://testserver','X-CSRF-Token':self.csrf}
            p=client.post(route+'/preview',json=payload,headers=headers)
            self.assertEqual(p.status_code,200,p.text)
            changed={**payload,'local_ids':[],'tariff_seqs':[1],'preview_sha256':p.json()['preview_sha256']}
            self.assertEqual(client.post(route+'/apply',json=changed,headers=headers).status_code,409)
            applied=client.post(route+'/apply',json={**payload,'preview_sha256':p.json()['preview_sha256']},headers=headers)
            self.assertEqual(applied.status_code,201,applied.text)
            self.assertEqual(applied.json()['versions'][0]['local_id'],self.pid)

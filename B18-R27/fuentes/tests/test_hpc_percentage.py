"""Fictional percentage update, atomicity and preview binding."""
import sqlite3
from unittest import TestCase, mock
from fastapi.testclient import TestClient
from app.api import create_app
from app.hpc_percentage import preview_percentage, apply_percentage
from app.hpc_values import save_value_version
from app.service import Problem
from app.security import create_user, issue_session, token_digest
from tests import test_hpc_values as fixtures


class PercentageTests(TestCase):
    def setUp(self):
        original=fixtures.fictional_values
        def catalog(root):
            result=original(root)
            c=sqlite3.connect(root/'catalogo_ficticio.sqlite')
            c.execute("UPDATE hpc_catalog_tariffs SET code='654321' WHERE seq=2")
            c.commit();c.close()
            return result
        with mock.patch.object(fixtures,'fictional_values',catalog):fixtures.HpcValueTests.setUp(self)
        for seq,code in ([(1,'123456'),(2,'654321')] if getattr(self,'seed_versions',True) else []):
            saved=save_value_version(self.conn,self.root,self.digest,self.dataset['id'],self.source,
                **fixtures.HpcValueTests.payload(self,tariff_seq=seq,code=code,amount_ars='1.05'))
            self.dataset['version']=saved['dataset_version']
    tearDown=fixtures.HpcValueTests.tearDown
    def payload(self,**changes):
        data=dict(expected_dataset_version=self.dataset['version'],tariff_seqs=[1,2],percentage='10',
                  effective_from='2026-11-02',document_id=self.document,page_number=2,
                  excerpt='Cláusula ficticia: aumento diez por ciento.',reason='Ensayo ficticio porcentaje documentado')
        data.update(changes);return data
    def preview(self,**changes):
        return preview_percentage(self.conn,self.root,self.digest,self.dataset['id'],self.source,**self.payload(**changes))
    def apply(self,p,**changes):
        return apply_percentage(self.conn,self.root,self.digest,self.dataset['id'],self.source,
                                preview_sha256=p['preview_sha256'],**self.payload(**changes))
    def test_rounding_single_version_increment_and_history(self):
        before=self.conn.execute('SELECT source_sha256 FROM source_registry WHERE id=?',(self.source,)).fetchone()[0]
        p=self.preview()
        self.assertEqual([i['after_ars'] for i in p['items']],['1.16','1.16'])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM hpc_value_versions').fetchone()[0],2)
        result=self.apply(p)
        self.assertEqual(result['dataset_version'],self.dataset['version']+1)
        rows=self.conn.execute('SELECT reason FROM hpc_value_versions WHERE ordinal=2').fetchall()
        self.assertEqual(len(rows),2)
        self.assertTrue(all(result['operation_id'] in r[0] for r in rows))
        self.assertEqual(before,self.conn.execute('SELECT source_sha256 FROM source_registry WHERE id=?',(self.source,)).fetchone()[0])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM control_runs').fetchone()[0],0)
        with self.assertRaises(Problem) as stale:self.apply(p)
        self.assertEqual(stale.exception.status,409)
    def test_rollback_after_first_insert(self):
        from app import hpc_percentage
        insert=hpc_percentage._insert_value_version
        count=0
        def fail(*args,**kwargs):
            nonlocal count
            count+=1
            if count==2:raise RuntimeError('synthetic interruption')
            return insert(*args,**kwargs)
        p=self.preview()
        with mock.patch.object(hpc_percentage,'_insert_value_version',fail):
            with self.assertRaises(RuntimeError):self.apply(p)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM hpc_value_versions').fetchone()[0],2)
        self.assertEqual(self.conn.execute('SELECT version FROM datasets WHERE id=?',(self.dataset['id'],)).fetchone()[0],self.dataset['version'])
        self.apply(p)
    def test_changed_preview_invalid_selections_and_dates(self):
        p=self.preview()
        with self.assertRaises(Problem):self.apply(p,percentage='11')
        for args in [dict(tariff_seqs=[3]),dict(tariff_seqs=[1,1]),dict(tariff_seqs=[True]),
                     dict(tariff_seqs=list(range(1,1002))),dict(percentage='NaN'),dict(percentage='-100'),
                     dict(percentage='0'),dict(effective_from='2026-10-01')]:
            with self.subTest(args=args):
                with self.assertRaises(Problem):self.preview(**args)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM hpc_value_versions').fetchone()[0],2)
    def test_base_future_and_corrupted_document_blocked(self):
        with self.assertRaises(Problem):self.preview(effective_from='2026-10-30')
        # Hash-backed evidence remains immutable; simulate unavailable storage at read boundary.
        with mock.patch('app.hpc_percentage.read_verified',side_effect=OSError('synthetic missing')):
            with self.assertRaises(Problem):self.preview()
        saved=save_value_version(self.conn,self.root,self.digest,self.dataset['id'],self.source,
            **fixtures.HpcValueTests.payload(self,effective_from='2026-12-01'))
        self.dataset['version']=saved['dataset_version']
        with self.assertRaises(Problem) as retro:self.preview()
        self.assertEqual(retro.exception.status,409)
    def test_reduction_partial_selection_and_tiny_result(self):
        p=self.preview(tariff_seqs=[2],percentage='-10')
        self.assertEqual([i['after_ars'] for i in p['items']],['0.95'])
        self.apply(p,tariff_seqs=[2],percentage='-10')
        self.assertEqual(self.conn.execute('SELECT count(*) FROM hpc_value_versions WHERE tariff_seq=1').fetchone()[0],1)
        self.dataset['version']+=1
        with self.assertRaises(Problem):self.preview(percentage='-99.9999')

    def test_api_csrf_admin_and_tampered_hash(self):
        app=create_app(self.root,public_origin='https://testserver')
        route=f'/api/datasets/{self.dataset["id"]}/sources/{self.source}/hpc-percentage'
        with TestClient(app,base_url='https://testserver') as client:
            self.assertEqual(client.post(route+'/preview',json=self.payload()).status_code,403)
            client.cookies.set('tfg_session',self.raw_token)
            self.assertEqual(client.post(route+'/apply',json={**self.payload(),'preview_sha256':'a'*64}).status_code,403)
            headers={'Origin':'https://testserver','X-CSRF-Token':self.csrf}
            p=client.post(route+'/preview',json=self.payload(),headers=headers)
            self.assertEqual(p.status_code,200,p.text)
            self.assertEqual(client.post(route+'/apply',json={**self.payload(),'preview_sha256':'a'*64},headers=headers).status_code,409)
            self.assertEqual(client.post(route+'/preview',json=self.payload(tariff_seqs=[True]),headers=headers).status_code,422)
            self.assertEqual(client.post(route+'/apply',json={**self.payload(),'preview_sha256':p.json()['preview_sha256']},headers=headers).status_code,201)
        owner=self.conn.execute("SELECT id FROM users WHERE username='owner'").fetchone()[0]
        self.conn.execute("UPDATE dataset_access SET role='reviewer' WHERE user_id=?",(owner,))
        self.conn.execute("UPDATE users SET role='reviewer' WHERE id=?",(owner,))
        with self.assertRaises(Problem) as denied:self.preview()
        self.assertEqual(denied.exception.status,403)


class AmbiguousPercentageTests(TestCase):
    setUp=fixtures.HpcValueTests.setUp
    tearDown=fixtures.HpcValueTests.tearDown
    def test_same_code_two_current_records_is_rejected(self):
        result=save_value_version(self.conn,self.root,self.digest,self.dataset['id'],self.source,
                                  **fixtures.HpcValueTests.payload(self))
        with self.assertRaises(Problem) as ambiguous:
            preview_percentage(self.conn,self.root,self.digest,self.dataset['id'],self.source,
                expected_dataset_version=result['dataset_version'],tariff_seqs=[1],percentage='10',
                effective_from='2026-11-02',document_id=self.document,page_number=2,
                excerpt='Cláusula de prueba ficticia',reason='Cambio porcentual ficticio')
        self.assertIn('simultáneas',str(ambiguous.exception))


class OriginalPercentageTests(TestCase):
    seed_versions=False
    setUp=PercentageTests.setUp
    tearDown=PercentageTests.tearDown
    preview=PercentageTests.preview
    apply=PercentageTests.apply
    def payload(self, **changes):
        return PercentageTests.payload(self,base_currency='ARS',base_unit_label='por práctica',
                                       base_declaration=True,**changes)
    def test_original_requires_all_explicit_declarations(self):
        for changes in [dict(base_currency=None),dict(base_currency='USD'),dict(base_unit_label=''),
                        dict(base_unit_label=' '),dict(base_declaration=False),dict(base_declaration=None)]:
            payload=self.payload();payload.update(changes)
            with self.subTest(changes=changes):
                with self.assertRaises(Problem):
                    preview_percentage(self.conn,self.root,self.digest,self.dataset['id'],self.source,**payload)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM hpc_value_versions').fetchone()[0],0)
    def test_original_preview_apply_trace_and_no_monetary_effect(self):
        p=self.preview()
        self.assertEqual([i['after_ars'] for i in p['items']],['135.80','258.02'])
        for item in p['items']:
            self.assertIsNone(item['base_version_id'])
            self.assertEqual(item['base_origin'],'catalogue_original')
            self.assertEqual(item['base_source_sha256'],p['source_sha256'])
            self.assertEqual(item['base_declaration_state'],'operator_declared_not_automatically_verified')
        self.apply(p)
        rows=self.conn.execute('SELECT reason FROM hpc_value_versions').fetchall()
        self.assertEqual(len(rows),2)
        self.assertTrue(all('no verificada automáticamente' in r[0] and p['source_sha256'] in r[0] for r in rows))
        self.assertEqual(self.conn.execute('SELECT count(*) FROM economic_verifications').fetchone()[0],0)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM control_runs').fetchone()[0],0)
    def test_original_transaction_failure_rolls_back_all(self):
        from app import hpc_percentage
        original=hpc_percentage._insert_value_version
        count=0
        def fail(*args,**kwargs):
            nonlocal count
            count+=1
            if count==2:raise RuntimeError('synthetic interruption original')
            return original(*args,**kwargs)
        p=self.preview()
        with mock.patch.object(hpc_percentage,'_insert_value_version',fail):
            with self.assertRaises(RuntimeError):self.apply(p)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM hpc_value_versions').fetchone()[0],0)
        self.assertEqual(self.conn.execute('SELECT version FROM datasets WHERE id=?',(self.dataset['id'],)).fetchone()[0],self.dataset['version'])

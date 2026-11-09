"""Fictional dated withdrawal; original catalog and earlier dates remain unchanged."""
import unittest
from unittest.mock import patch
from tests import test_hpc_values as fixtures
from app.hpc_value_status import migration_statements, save_status
from app.hpc_values import _source, _tariff
from app.effective_hpc_values import EffectiveHpcValues
from app.service import Problem

class StatusTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.HpcValueTests();self.f.setUp()
        if not self.f.conn.execute("SELECT 1 FROM sqlite_master WHERE name='hpc_value_status_versions'").fetchone():
            for stmt in migration_statements():self.f.conn.execute(stmt)
    def tearDown(self):self.f.tearDown()
    def save(self,**changes):
        f=self.f
        data=dict(expected_dataset_version=f.dataset['version'],tariff_seq=1,active=False,
            effective_from='2026-11-01',document_id=f.document,page_number=1,
            excerpt='Retiro ficticio de la práctica del convenio',reason='Cambio ficticio respaldado para probar historia')
        data.update(changes)
        result=save_status(f.conn,f.root,f.digest,f.dataset['id'],f.source,**data)
        f.dataset['version']=result['dataset_version'];return result
    def resolve(self,day):
        f=self.f;source=_source(f.conn,f.dataset['id'],f.source)
        return EffectiveHpcValues(f.conn,f.root,f.dataset['id'],f.source).resolve(_tariff(f.root,source,1),day)
    def test_dated_withdrawal_reinstatement_and_same_day_correction(self):
        before=self.resolve('2026-10-01')
        self.save()
        self.assertEqual(self.resolve('2026-10-01'),before)
        self.assertEqual(self.resolve('2026-11-01')['status'],'withdrawn_reference')
        self.save(active=True,effective_from='2026-11-01')
        self.assertEqual(self.resolve('2026-11-01')['status'],'catalogue_candidate')
        self.assertEqual(self.resolve('2026-11-01')['status_version']['ordinal'],2)
        self.assertEqual(self.f.conn.execute('SELECT count(*) FROM control_runs').fetchone()[0],0)
    def test_reject_repeat_stale_retroactive_and_other_provider(self):
        old=self.f.dataset['version'];self.save()
        for data in ({}, {'active':True,'effective_from':'2026-10-01'},
                     {'active':True,'expected_dataset_version':old}, {'tariff_seq':3}):
            with self.assertRaises(Problem):self.save(**data)
        self.assertEqual(self.f.conn.execute('SELECT count(*) FROM hpc_value_status_versions').fetchone()[0],1)
    def test_corrupt_withdrawal_document_blocks_not_fallback(self):
        self.save()
        with patch('app.effective_hpc_values.read_verified',side_effect=RuntimeError('corrupt')):
            self.assertEqual(self.resolve('2026-11-01')['status'],'status_evidence_unverifiable')
    def test_api_csrf_access_and_stale(self):
        from fastapi.testclient import TestClient
        from app.api import create_app
        f=self.f
        body=dict(expected_dataset_version=f.dataset['version'],tariff_seq=1,active=False,
            effective_from='2026-11-01',document_id=f.document,page_number=1,
            excerpt='Retiro ficticio documentado de arancel',reason='Prueba ficticia de estado administrativo')
        route=f'/api/datasets/{f.dataset["id"]}/sources/{f.source}/hpc-status'
        with TestClient(create_app(f.root,public_origin='https://testserver'),base_url='https://testserver') as client:
            self.assertEqual(client.post(route,json=body).status_code,403)
            client.cookies.set('tfg_session',f.raw_token)
            self.assertEqual(client.post(route,json=body,headers={'Origin':'https://testserver'}).status_code,403)
            headers={'Origin':'https://testserver','X-CSRF-Token':f.csrf}
            response=client.post(route,json=body,headers=headers)
            self.assertEqual(response.status_code,201,response.text)
            self.assertEqual(client.post(route,json=body,headers=headers).status_code,409)
            history=client.get(route.replace('hpc-status','hpc-values/1')).json()
            self.assertEqual(history['status_history'][0]['active'],0)
    def test_withdrawn_candidate_does_not_make_active_tariff_ambiguous(self):
        from app.hpc_comparison import _compare
        f=self.f;self.save()
        source=_source(f.conn,f.dataset['id'],f.source)
        tariff=_tariff(f.root,source,1)
        tariff.update(source_locator='tariff=1',amount_cents=1000,valid_from='2026-06-01',valid_until=None,
            calculation={'kind':'nbu','ubMilliunits':1000,'rateCents':1000})
        second={**tariff,'seq':900,'source_locator':'tariff=900'}
        resolver=EffectiveHpcValues(f.conn,f.root,f.dataset['id'],f.source)
        row={'source_row':2,'disposition':'included','practice_date':'2026-11-01','total_ars':'10.00'}
        def compare(items):return _compare(row,{'E':tariff['code'],'G':1},{},{tariff['code']:items},source,'Hoja1',resolver)
        self.assertEqual(compare([tariff,second])['status'],'numeric_equal')
        self.assertEqual(compare([tariff])['status'],'withdrawn_reference')
        with patch('app.effective_hpc_values.read_verified',side_effect=RuntimeError('corrupt')):
            resolver=EffectiveHpcValues(f.conn,f.root,f.dataset['id'],f.source)
            self.assertEqual(compare([tariff,second])['status'],'ambiguous_hpc_tariff')
    def test_status_history_is_append_only(self):
        import sqlite3
        self.save()
        for statement in ('DELETE FROM hpc_value_status_versions','UPDATE hpc_value_status_versions SET active=1'):
            with self.assertRaises(sqlite3.IntegrityError):self.f.conn.execute(statement)

"""Shared effective-value resolver: invented catalog, PDF, invoice and accounts only."""
from contextlib import closing
import hashlib
import json
import sqlite3
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient

from app.api import create_app
from app.effective_hpc_values import EffectiveHpcValues
from app.hpc_values import save_value_version
from app.values_v1 import candidate_values, source_db
from app.storage import object_path
from tests import test_hpc_values as value_fixture
from tests.test_p03 import fictional_values as original_fixture
from tests.test_p02 import ORIGIN, PASSWORD, book


def single_expired_catalog(folder):
    _,manifest,_=original_fixture(folder)
    path=folder/'catalogo_ficticio.sqlite'
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute('DELETE FROM hpc_catalog_tariffs WHERE seq=2')
        conn.execute("UPDATE hpc_catalog_tariffs SET valid_until='2026-07-31' WHERE seq=1")
        counts={r[0]:conn.execute(f'SELECT count(*) FROM "{r[0]}"').fetchone()[0]
                for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    content=path.read_bytes();sha=hashlib.sha256(content).hexdigest();data=json.loads(manifest)
    data['counts']=counts;data['files']['valores_convenios_base_2026-10-09.sqlite']={'sha256':sha,'bytes':len(content)}
    return content,json.dumps(data).encode(),sha


class EffectiveValueTests(unittest.TestCase):
    payload=value_fixture.HpcValueTests.payload
    tearDown=value_fixture.HpcValueTests.tearDown
    def setUp(self):
        with patch('tests.test_hpc_values.fictional_values',side_effect=single_expired_catalog):
            value_fixture.HpcValueTests.setUp(self)
    def save(self,**changes):
        result=save_value_version(self.conn,self.root,self.digest,self.dataset['id'],self.source,**self.payload(**changes))
        self.dataset['version']=result['dataset_version'];return result
    def tariff(self):
        source=self.conn.execute('SELECT * FROM source_registry WHERE id=?',(self.source,)).fetchone()
        catalog=source_db(object_path(self.root,source['source_sha256']).read_bytes())
        try:return dict(catalog.execute('SELECT * FROM hpc_catalog_tariffs WHERE seq=1').fetchone())
        finally:catalog.close()
    def test_version_has_own_start_and_corrects_same_day_without_old_expiry_cap(self):
        first=self.save(effective_from='2026-08-16',amount_ars='14.00')
        second=self.save(effective_from='2026-09-01',amount_ars='18.00')
        corrected=self.save(effective_from='2026-09-01',amount_ars='19.00')
        resolver=EffectiveHpcValues(self.conn,self.root,self.dataset['id'],self.source);tariff=self.tariff()
        self.assertEqual(resolver.resolve(tariff,'2026-07-15')['recorded_amount'],'123.45')
        self.assertFalse(resolver.resolve(tariff,'2026-08-15')['selected'])
        august=resolver.resolve(tariff,'2026-08-16');self.assertEqual(august['value_version']['id'],first['id'])
        self.assertEqual(august['next_version_from'],'2026-09-01')
        self.assertEqual(resolver.resolve(tariff,'2026-09-01')['value_version']['id'],corrected['id'])
        self.assertFalse(resolver.resolve(tariff,None)['selected'])
        self.assertFalse(resolver.resolve({**tariff,'provider':'OTRO'},'2026-09-01')['selected'])
    def test_invalid_version_document_never_falls_back_to_catalog(self):
        self.save(effective_from='2026-07-15',amount_ars='14.00')
        version=self.conn.execute('SELECT * FROM hpc_value_versions').fetchone()
        object_path(self.root,version['document_sha256']).write_bytes(b'fictitious corruption')
        resolved=EffectiveHpcValues(self.conn,self.root,self.dataset['id'],self.source).resolve(self.tariff(),'2026-07-16')
        self.assertEqual(resolved['status'],'version_evidence_unverifiable')
        self.assertEqual(resolved['recorded_amount'],'14.00')
        self.assertIsNotNone(resolved['value_version'])
    def test_hourly_version_is_found_but_not_compared_as_practices(self):
        from app.hpc_comparison import _compare
        self.save(effective_from='2026-07-15',amount_ars='14.00',unit_label='por hora')
        tariff=self.tariff();tariff['source_locator']='hpc_catalog_tariffs.seq=1';tariff['calculation']={}
        resolver=EffectiveHpcValues(self.conn,self.root,self.dataset['id'],self.source)
        source={'id':self.source,'source_sha256':'fictional','cut_label':'BASE_2026-10-09'}
        row={'source_row':2,'disposition':'included','practice_date':'2026-08-16','total_ars':'32.00'}
        result=_compare(row,{'E':'123456','G':2},{},{'123456':[tariff]},source,'Hoja1',resolver=resolver)
        self.assertEqual(result['status'],'value_version_unit_incompatible')
        self.assertIsNone(result['difference_ars_if_comparable'])
        self.assertEqual(result['effective_reference']['recorded_amount'],'14.00')
        self.assertEqual(result['effective_reference']['declared_unit'],'por hora')

    def test_two_active_tariff_records_remain_ambiguous_despite_documented_version(self):
        from app.hpc_comparison import _compare
        self.save(effective_from='2026-07-15',amount_ars='14.00')
        tariff=self.tariff();tariff['source_locator']='hpc_catalog_tariffs.seq=1';tariff['calculation']={}
        other={**tariff,'seq':99,'source_locator':'hpc_catalog_tariffs.seq=99','valid_until':None}
        resolver=EffectiveHpcValues(self.conn,self.root,self.dataset['id'],self.source)
        row={'source_row':2,'disposition':'included','practice_date':'2026-08-16','total_ars':'32.00'}
        source={'id':self.source,'source_sha256':'fictional','cut_label':'BASE_2026-10-09'}
        result=_compare(row,{'E':'123456','G':2},{},{'123456':[tariff,other]},source,'Hoja1',resolver=resolver)
        self.assertEqual(result['status'],'ambiguous_hpc_tariff')
        self.assertIsNone(result['difference_ars_if_comparable'])

    def test_non_nbu_version_agrees_across_search_comparison_and_row_candidate(self):
        saved=self.save(effective_from='2026-08-16',amount_ars='14.00')
        with TestClient(create_app(self.root,public_origin=ORIGIN),base_url=ORIGIN) as client:
            login=client.post('/api/session',headers={'Origin':ORIGIN},json={'username':'owner','password':PASSWORD}).json()
            headers={'Origin':ORIGIN,'X-CSRF-Token':login['csrf_token']};base=f'/api/datasets/{self.dataset["id"]}'
            staged=client.post(base+'/batches',content=book([('15/08/2026',10,20,30),('16/08/2026',11,21,32)]),
                               headers={**headers,'X-Expected-Version':str(self.dataset['version']),'X-Source-Filename':'factura-ficticia.xlsx','Content-Type':'application/octet-stream'})
            self.assertEqual(staged.status_code,201,staged.text);batch=staged.json()['id'];version=staged.json()['dataset_version']
            imported=client.post(base+f'/batches/{batch}/invoice-import',headers=headers,json={'period':'2026-08','period_confirmed':True,'expected_version':version})
            self.assertEqual(imported.status_code,201,imported.text)
            scope_url=base+f'/batches/{batch}/provider-scope';scope=client.get(scope_url).json()
            response=client.post(scope_url,headers=headers,json={'source_id':self.source,'provider':'HPC','billing_unit':'unverified',
                'confirmation_note':'Factura y convenio ficticios exclusivamente HPC.', 'expected_dataset_version':scope['dataset_version'],'expected_revision_version':scope['revision_version']})
            self.assertEqual(response.status_code,200,response.text)
            search=client.get(base+f'/sources/{self.source}/value-candidates',params={'code':'123456','provider':'HPC','performed_on':'2026-08-16'}).json()
            effective=search['tariff_candidates'][0]['effective_reference'];self.assertEqual(effective['recorded_amount'],'14.00')
            comparison=client.get(base+f'/batches/{batch}/hpc-comparison',params={'source_id':self.source,'source_row':3})
            self.assertEqual(comparison.status_code,200,comparison.text);item=comparison.json()['items'][0]
            self.assertEqual(item['candidate_total_if_ars_and_same_unit'],'28.00')
            self.assertEqual(item['difference_ars_if_comparable'],'4.00')
            preview=client.get(base+f'/batches/{batch}/rows/3/economic-applicability',params={'source_id':self.source})
            self.assertEqual(preview.status_code,200,preview.text);basis=preview.json()['basis']
            self.assertEqual(basis['status'],'ready_for_applicability')
            self.assertIsNone(preview.json()['reference_display']['valid_until'])
            self.assertEqual(basis['candidate']['rate_ars'],'14.00')
            self.assertEqual(basis['candidate']['value_version']['id'],saved['id'])
            self.assertEqual(item['effective_reference']['value_version']['id'],saved['id'])
            self.assertEqual(effective['value_version']['id'],saved['id'])
            self.assertIsNone(preview.json()['latest'])
        for table in ('control_runs','row_economic_references','proposal_versions'):
            self.assertEqual(self.conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0],0)

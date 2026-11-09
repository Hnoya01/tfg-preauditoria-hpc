"""Synthetic documented display categories, independent of authorizations and prices."""
from io import BytesIO
from openpyxl import Workbook,load_workbook
import unittest
from urllib.parse import quote
from app.db import connect
from app.storage import object_path
from tests import test_hpc_comparison as fixture
from tests.test_p02 import book


def price_free_hpc_catalog(folder):
    import hashlib,json,sqlite3
    from tests.test_practice_families import fictional_family_values
    _,manifest,_=fictional_family_values(folder)
    path=folder/'catalogo_ficticio.sqlite'
    c=sqlite3.connect(path)
    c.execute("UPDATE hpc_catalog_providers SET id='HPC' WHERE id='P1'")
    c.execute('DELETE FROM hpc_catalog_tariffs')
    c.commit();c.close()
    data=path.read_bytes();sha=hashlib.sha256(data).hexdigest();info=json.loads(manifest)
    info['counts']['hpc_catalog_tariffs']=0
    info['files']['valores_convenios_base_2026-10-09.sqlite']={'sha256':sha,'bytes':len(data)}
    return data,json.dumps(info).encode(),sha


def nomenclature(code,area='Imágenes'):
    out=BytesIO();wb=Workbook();ws=wb.active;ws.title='Prácticas'
    ws.append(['Código','Descripción','Área'])
    ws.append([code,'Eco de prueba',area])
    wb.save(out);wb.close();return out.getvalue()


class DisplayCategoryTests(unittest.TestCase):
    code='0098765432'
    def setUp(self):
        self.f=fixture.HpcComparisonTests();self.f.setUp()
        self.addCleanup(self.f.tearDown)
        from app.values_v1 import register_values
        c=connect(self.f.root)
        try:
            registered,_=register_values(c,self.f.root,self.f.digest,self.f.dataset['id'],self.f.dataset['version'],
                                         *price_free_hpc_catalog(self.f.root))
            self.source=registered['id'];self.f.dataset['version']=registered['dataset_version']
        finally:c.close()
        self.first=self.invoice(self.code,'Eco ficticia');self.scope(self.first)

    def invoice(self,code,name):
        wb=load_workbook(BytesIO(book([('04/08/2026',10,20,30)])))
        ws=wb.active;ws.cell(2,5).value=code;ws.cell(2,11).value=name
        out=BytesIO();wb.save(out);wb.close()
        return self.f.import_book(out.getvalue(),'ficticia.xlsx')

    def base(self,batch):return f'/api/datasets/{self.f.dataset["id"]}/batches/{batch}'

    def page(self,batch):
        res=self.f.client.post(self.base(batch)+'/practice-search',json={},headers=self.f.headers())
        self.assertEqual(res.status_code,200,res.text);return res.json()

    def scope(self,batch):
        page=self.page(batch)
        r=self.f.client.post(self.base(batch)+'/provider-scope',json={
            'expected_dataset_version':page['dataset_version'],'expected_revision_version':page['batch']['revision_version'],
            'source_id':self.source,'provider':'HPC','billing_unit':'unverified',
            'confirmation_note':'Alcance HPC confirmado para la prueba de clasificación.'},headers=self.f.headers())
        self.assertEqual(r.status_code,200,r.text);self.f.dataset['version']=r.json()['dataset_version']

    def save(self,batch,**headers):
        page=self.page(batch)
        return self.f.client.post(self.base(batch)+'/rows/2/display-category',content=nomenclature(self.code),
            headers=self.f.headers(**{'X-Dataset-Version':str(page['dataset_version']),
                        'X-Revision-Version':str(page['batch']['revision_version']),'X-Practice-Code':self.code,
                        'X-Family':'images','X-Sheet':quote('Prácticas'),'X-Evidence-Row':'2',
                        'X-Evidence-Column':'1','X-Source-Filename':'Nomenclador.xlsx',**headers}))

    def test_saved_code_recognized_in_future_confirmed_invoice_without_price(self):
        self.assertEqual(self.page(self.first)['items'][0]['family'],'unclassified')
        saved=self.save(self.first);self.assertEqual(saved.status_code,201,saved.text)
        self.f.dataset['version']=saved.json()['dataset_version']
        second=self.invoice(self.code,'Descripción diferente')
        self.assertEqual(self.page(second)['items'][0]['family'],'unclassified')
        self.scope(second)
        row=self.page(second)['items'][0]
        self.assertEqual((row['family'],row['family_basis']),('images','registered_hpc_category'))
        origin=row['family_evidence']['code'][0]
        self.assertEqual((origin['sheet'],origin['source_row'],origin['source_column']),('Prácticas',2,1))
        self.assertIsNone(row['reference_comparison']['recorded_amount'])
        other=self.invoice(self.code[:-1],'Eco ficticia');self.scope(other)
        self.assertEqual(self.page(other)['items'][0]['family'],'unclassified')
        path=object_path(self.f.root,saved.json()['source_sha256'])
        path.write_bytes(b'FICTICIO: respaldo alterado')
        self.assertEqual(self.page(second)['items'][0]['family_basis'],'category_evidence_unavailable')

    def test_conflicting_name_and_unconfirmed_batch_remain_unclassified(self):
        outside=self.invoice(self.code,'Descripción sin alcance')
        self.assertEqual(self.save(outside).status_code,409)
        saved=self.save(self.first);self.assertEqual(saved.status_code,201,saved.text)
        self.f.dataset['version']=saved.json()['dataset_version']
        conflict=self.invoice(self.code,'Laboratorio ficticio')
        self.scope(conflict)
        row=self.page(conflict)['items'][0]
        self.assertEqual((row['family'],row['family_basis']),('unclassified','conflicting_catalog_evidence'))

    def test_invalid_locator_stale_request_and_duplicate_do_not_create_other_records(self):
        self.assertEqual(self.save(self.first,**{'X-Evidence-Column':'2'}).status_code,422)
        self.assertEqual(self.save(self.first,**{'X-Dataset-Version':'0'}).status_code,409)
        saved=self.save(self.first)
        self.assertEqual(saved.status_code,201,saved.text)
        self.assertEqual(self.save(self.first).status_code,409)
        conn=connect(self.f.root)
        try:
            self.assertEqual(conn.execute('SELECT count(*) FROM hpc_display_categories').fetchone()[0],1)
            for table in ['local_hpc_practices','row_economic_references','proposal_versions','authorization_captures']:
                self.assertEqual(conn.execute('SELECT count(*) FROM '+table).fetchone()[0],0)
        finally:conn.close()

"""Independent synthetic category versions and internal registration requests."""
from io import BytesIO
import unittest
from urllib.parse import quote
from openpyxl import Workbook
from app.db import connect
from tests import test_display_categories as fixture
from tests.test_p02 import ORIGIN,PASSWORD


def correction_book(code):
    wb=Workbook();ws=wb.active;ws.title='Revisión'
    ws.append(['Código','Categoría']);ws.append([code,'Otras prácticas'])
    buf=BytesIO();wb.save(buf);wb.close();return buf.getvalue()


class CategoryWorkflowTests(unittest.TestCase):
    code=fixture.DisplayCategoryTests.code
    setUp=fixture.DisplayCategoryTests.setUp
    invoice=fixture.DisplayCategoryTests.invoice
    base=fixture.DisplayCategoryTests.base
    page=fixture.DisplayCategoryTests.page
    scope=fixture.DisplayCategoryTests.scope
    save=fixture.DisplayCategoryTests.save

    def correction(self,batch,previous=1,reason='Corrección según la hoja revisada del nomenclador.'):
        page=self.page(batch)
        return self.f.client.post(self.base(batch)+'/rows/2/display-category',content=correction_book(self.code),
            headers=self.f.headers(**{'X-Dataset-Version':str(page['dataset_version']),'X-Revision-Version':str(page['batch']['revision_version']),
              'X-Practice-Code':self.code,'X-Family':'other','X-Sheet':quote('Revisión'),'X-Evidence-Row':'2','X-Evidence-Column':'1',
              'X-Source-Filename':'Revisado.xlsx','X-Category-Version':str(previous),'X-Correction-Reason':quote(reason)}))

    def test_future_invoice_correction_history_and_both_originals(self):
        initial=self.save(self.first);self.assertEqual(initial.status_code,201,initial.text)
        self.assertEqual(self.correction(self.first,reason='').status_code,422)
        self.assertEqual(self.correction(self.first,previous=3).status_code,409)
        corrected=self.correction(self.first);self.assertEqual(corrected.status_code,201,corrected.text)
        self.f.dataset['version']=corrected.json()['dataset_version']
        future=self.invoice(self.code,'Texto ficticio nuevo');self.scope(future)
        row=self.page(future)['items'][0]
        self.assertEqual(row['family'],'other');self.assertIsNone(row['reference_comparison']['recorded_amount'])
        url=self.base(future)+'/rows/2/category-history'
        history=self.f.client.get(url).json()
        self.assertEqual([(r['ordinal'],r['family']) for r in history],[(1,'images'),(2,'other')])
        self.assertEqual(history[1]['source_sha256'],corrected.json()['source_sha256'])
        self.assertEqual(history[0]['source_sha256'],initial.json()['source_sha256'])
        self.assertNotEqual(history[1]['source_sha256'],history[0]['source_sha256'])
        self.assertEqual(history[1]['reason'],'Corrección según la hoja revisada del nomenclador.')
        import hashlib
        for r in history:
            response=self.f.client.get(url+'/'+str(r['ordinal'])+'/file')
            self.assertEqual(hashlib.sha256(response.content).hexdigest(),r['source_sha256'])

    def test_documented_agreement_registration_can_be_linked_by_admin(self):
        from app.economic_evidence import register_evidence_pdf
        from app.local_hpc import save
        import hashlib
        page=self.page(self.first)
        body=dict(version=page['dataset_version'],revision=page['batch']['revision_version'],
                  code=self.code,kind='agreement',reason='Alta de práctica ficticia según convenio.')
        response=self.f.client.post(self.base(self.first)+'/rows/2/practice-requests',json=body,headers=self.f.headers())
        self.assertEqual(response.status_code,201,response.text)
        self.assertEqual(self.page(self.first)['pending_requests'],1)
        req=response.json();data=b'%PDF-1.4\n% respaldo de prueba: importe ficticio\n%%EOF'
        conn=connect(self.f.root)
        try:
            doc,_=register_evidence_pdf(conn,self.f.root,self.f.digest,self.f.dataset['id'],self.source,req['dataset_version'],
                'acuerdo-ficticio.pdf','agreement','Respaldo del alta ficticia para esta prueba.',hashlib.sha256(data).hexdigest(),data)
            entry=save(conn,self.f.root,self.f.digest,self.f.dataset['id'],self.source,expected_dataset_version=doc['dataset_version'],
                code=self.code,description='Estudio ficticio',family='other',amount_ars='14.00',currency='ARS',unit_label='por práctica',
                active=True,effective_from='2026-08-01',document_id=doc['id'],page_number=1,excerpt='Arancel ficticio documentado.',
                reason='Alta documentada para responder la solicitud.')
        finally:conn.close()
        url=f'/api/datasets/{self.f.dataset["id"]}/practice-requests'
        answer=self.f.client.post(url+'/'+req['id']+'/answer',json={'version':entry['dataset_version'],'state':'registered','reason':'Alta ficticia registrada en la fuente seleccionada.'},headers=self.f.headers())
        self.assertEqual(answer.status_code,200,answer.text)
        self.assertEqual(self.f.client.get(url).json()['items'][0]['target'],entry['id'])
        self.assertEqual(self.page(self.first)['pending_requests'],0)

    def test_internal_request_is_separate_from_registration(self):
        page=self.page(self.first);path=self.base(self.first)+'/rows/2/practice-requests'
        listing=f'/api/datasets/{self.f.dataset["id"]}/practice-requests'
        body=dict(version=page['dataset_version'],revision=page['batch']['revision_version'],code=self.code,kind='category',reason='Registrar el código documentado en el nomenclador ficticio.')
        send=self.f.client.post(path,json=body,headers=self.f.headers())
        self.assertEqual(send.status_code,201,send.text);v=send.json()['dataset_version']
        self.assertEqual(self.f.client.post(path,json={**body,'version':v},headers=self.f.headers()).status_code,409)
        self.assertEqual(self.page(self.first)['items'][0]['family'],'unclassified')
        identity=send.json()['id'];answer=listing+'/'+identity+'/answer'
        response=dict(version=v,state='registered',reason='Alta registrada con el documento respaldatorio.')
        self.assertEqual(self.f.client.post(answer,json=response,headers=self.f.headers()).status_code,409)
        self.assertEqual(self.save(self.first).status_code,201)
        self.assertEqual(self.f.client.post(answer,json=response,headers=self.f.headers()).status_code,409)
        v=self.page(self.first)['dataset_version']
        self.assertEqual(self.f.client.post(answer,json={**response,'version':v},headers=self.f.headers()).status_code,200)
        history=self.f.client.get(listing).json()
        self.assertEqual(history['items'][0]['state'],'registered')
        req=self.f.client.post(path,json={**body,'version':history['dataset_version'],'kind':'agreement'},headers=self.f.headers())
        self.assertEqual(req.status_code,201,req.text)
        url=listing+'/'+req.json()['id']+'/answer'
        ans={**response,'version':req.json()['dataset_version']}
        self.assertEqual(self.f.client.post(url,json=ans,headers=self.f.headers()).status_code,409)
        self.assertEqual(self.f.client.post(url,json={**ans,'state':'declined'},headers=self.f.headers()).status_code,200)
        c=connect(self.f.root)
        try:
            for t in ('local_hpc_practices','proposal_versions','authorization_captures'):
                self.assertEqual(c.execute('SELECT count(*) FROM '+t).fetchone()[0],0)
        finally:c.close()

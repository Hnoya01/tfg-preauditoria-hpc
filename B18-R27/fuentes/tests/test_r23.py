"""Synthetic source, correspondence and quantity regressions for R23."""
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import unittest
from openpyxl import load_workbook
from tests.temp_support import TemporaryDirectory
from tests.test_p02 import book
from tests.test_p03 import fictional_values
from tests.test_hpc_csv_intake import row, encode
from app.db import connect,migrate
from app.security import create_user,issue_session,token_digest
from app.service import create_dataset,create_batch,confirm_invoice,Problem,grant_access
from app.values_v1 import register_values
from app.authorization_imports import stage_authorization,preview_authorization,confirm_authorization
from app.authorization_matching import page_correspondence,save_scope
from app.economic_evidence import confirm_provider_scope
from app.review import _batch
from app.code_correspondences import save,listing
from app.authorization_source import parse_authorization_source
from app.authorization_assessment import applicable_resolution

INVOICE='654321'
CSV='6543210100'


def declared(movement, practices=None):
    raw=encode([row(practicas=practices or f'{CSV} -- TAC ficticia,',movimientos=movement)])
    parsed=parse_authorization_source(raw)
    order=parsed.canonical['orders'][0]
    return [applicable_resolution(order,i)['state'] for i in order['items']],parsed


def catalog(folder):
    _,manifest,_=fictional_values(folder)
    p=folder/'catalogo_ficticio.sqlite'
    c=sqlite3.connect(p)
    c.execute('DROP TABLE hpc_catalog_components')
    c.execute('CREATE TABLE hpc_catalog_components(component TEXT,part INTEGER,text_data TEXT)')
    c.execute('DROP TABLE hpc_catalog_practices')
    c.execute('CREATE TABLE hpc_catalog_practices(seq INTEGER,id TEXT,area TEXT,name TEXT)')
    c.executemany('INSERT INTO hpc_catalog_practices VALUES (?,?,?,?)',[(20,'test-tac','Imágenes','TAC ficticia'),(21,'test-eco','Imágenes','Eco ficticia')])
    c.execute("INSERT INTO hpc_catalog_providers VALUES (3,'HPC','HPC ficticio')")
    c.executemany('INSERT INTO hpc_catalog_codes VALUES (?,?,?,?,?,?,?,?)',[
        (20,20,'test-tac',1,'NOMENCLADOR',INVOICE,'nomenclador','TAC de abdomen ficticia'),
        (21,20,'test-tac',2,'HPC',CSV,'orden','TAC ficticia'),
        (22,20,'test-tac',3,'NOMENCLADOR','678901','nomenclador','Imágenes diversas'),
        (23,21,'test-eco',1,'NOMENCLADOR','678901','nomenclador','Imágenes diversas'),
        (24,21,'test-eco',2,'HPC','6789010100','orden','Eco ficticia')])
    c.commit()
    info=json.loads(manifest)
    for table in info['counts']:
        info['counts'][table]=c.execute('SELECT count(*) FROM "'+table+'"').fetchone()[0]
    c.close()
    raw=p.read_bytes();sha=hashlib.sha256(raw).hexdigest()
    info['files']['valores_convenios_base_2026-10-09.sqlite']={'sha256':sha,'bytes':len(raw)}
    return raw,json.dumps(info).encode(),sha


class ListedDecisions(unittest.TestCase):
    event='02/07/2026 12:00 | Operador ficticio | '
    def test_approved_listed_item_and_requested_two_units(self):
        for practices in (None,f'{CSV} -- TAC ficticia x2,'):
            states,p=declared(self.event+'AUTORIZADO | Autorizado por profesional ficticio.',practices)
            self.assertEqual(states,['declared_authorized'])
            self.assertEqual(p.summary['adapter_provenance']['adapter'],'hpc-platform-csv-v6')
            r=p.canonical['orders'][0]['resolutions'][0]
            self.assertEqual(r['authorized_quantity'],'2' if practices else '1')
    def test_generic_order_approval_covers_list_without_distributing_budget(self):
        practices=f'{CSV} -- TAC ficticia,6789010100 -- Eco ficticia,'
        states,_=declared(self.event+'AUTORIZADO | ',practices)
        self.assertEqual(states,['declared_authorized']*2)
        states,_=declared(self.event+'AUTORIZADO | Se autoriza a valor ARS 200.000',practices)
        # R25 recognizes the approved list. The order-level price remains unassigned.
        self.assertEqual(states,['declared_authorized']*2)
        from app.csv_budget import source_budgets
        raw=encode([row(practicas=practices,movimientos=self.event+'AUTORIZADO | Se autoriza a valor ARS 200.000')])
        parsed=parse_authorization_source(raw)
        amounts=source_budgets(raw,parsed.canonical['orders'])
        self.assertTrue(amounts)
        self.assertTrue(all(b['status']=='por_verificar' and 'amount_ars' not in b for b in amounts.values()))
    def test_rejection_and_referral_are_different(self):
        self.assertEqual(declared(self.event+'RECHAZADO | ')[0],['declared_rejected'])
        self.assertEqual(declared(self.event+'RECHAZADO | Se deriva a otro prestador.')[0],['declared_referred'])
    def test_conditions_conflicts_invalid_dates_and_unnamed_items_remain_open(self):
        for movement in (self.event+'AUTORIZADO | Solo si presenta informe',
                         self.event+'AUTORIZADO | Se autoriza parcialmente',
                         self.event+'AUTORIZADO | '+CSV,
                         self.event+'AUTORIZADO | \n'+self.event+'RECHAZADO | ',
                         '32/07/2026 12:00 | Ficticio | AUTORIZADO | '):
            self.assertEqual(declared(movement)[0],['no_concluyente'])
    def test_explicit_single_item_decision_keeps_other_item_open(self):
        practices=f'{CSV} -- TAC ficticia,6789010100 -- Eco ficticia,'
        states,_=declared(self.event+'AUTORIZADO | Resolución por ítems - AUTORIZAR: '+CSV,practices)
        self.assertEqual(states,['declared_authorized','no_concluyente'])


class CorrespondenceFlow(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory(dir='.tmp');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.c=connect(self.root);self.addCleanup(self.c.close)
        migrate(self.c)
        u=create_user(self.c,'admin-ficticio','Frase ficticia de prueba R23','admin')
        self.token=token_digest(issue_session(self.c,u)[0])
        self.ds=create_dataset(self.c,self.token,'DEMO FICTICIO R23')['id']
        self.source,_=register_values(self.c,self.root,self.token,self.ds,self.version(),*catalog(self.root))
        raw=encode([row(afiliado='000111/1',fecha_orden='2026-07-02',fecha_orden_original='02/07/2026',
                       practicas=f'{CSV} -- TAC ficticia,',
                       movimientos='02/07/2026 12:00 | Operador ficticio | AUTORIZADO | Autorizado por profesional ficticio.')])
        up,_=stage_authorization(self.c,self.root,self.token,self.ds,self.version(),'ficticio.csv',raw)
        pre=preview_authorization(self.c,self.root,self.token,self.ds,up['id'])
        self.cap,_=confirm_authorization(self.c,self.root,self.token,self.ds,up['id'],self.version(),pre['preview_sha256'],'CSV completamente ficticio R23.')
        self.bid=self.invoice([('02/08/2026',INVOICE),('04/08/2026',CSV)])
    def version(self):
        return self.c.execute('SELECT version FROM datasets WHERE id=?',(self.ds,)).fetchone()[0]
    def invoice(self,rows):
        wb=load_workbook(BytesIO(book([(d,10,20,30) for d,code in rows])))
        for n,(_,code) in enumerate(rows,2):
            for col,value in [(3,'000111/1'),(5,code),(7,1),(11,'TAC de abdomen ficticia')]:
                wb.active.cell(n,col).value=value
        stream=BytesIO();wb.save(stream);wb.close()
        b,_=create_batch(self.c,self.root,self.token,self.ds,self.version(),'FICTICIO.xlsx',stream.getvalue())
        confirm_invoice(self.c,self.root,self.token,self.ds,b['id'],'2026-08',self.version())
        confirm_provider_scope(self.c,self.root,self.token,self.ds,b['id'],self.source['id'],'HPC','unverified',
                               'Factura completamente ficticia HPC.',self.version(),_batch(self.c,self.ds,b['id'])['revision_version'])
        save_scope(self.c,self.root,self.token,self.ds,b['id'],self.version(),[self.cap['id']],'real_unvalidated',
                   'CSV ficticio exhaustivo para esta prueba.',csv_complete_from='2026-06-01',csv_complete_until='2026-08-31')
        return b['id']
    def confirm(self,active=True,token=None,version=None,pairs=None):
        return save(self.c,self.root,token or self.token,self.ds,self.source['id'],
                    expected_version=self.version() if version is None else version,pairs=pairs or [[INVOICE,CSV]],
                    active=active,reason='Cotejo ficticio de los dos códigos en la identidad específica del catálogo.')
    def signals(self,bid=None,numbers=(2,3)):
        return {n:r['panel_signal'].get('csv_coverage') for n,r in page_correspondence(self.c,self.root,self.ds,bid or self.bid,list(numbers)).items()}
    def test_list_does_not_activate_until_confirmation_and_reuses_one_aval(self):
        before=self.signals()
        self.assertNotEqual((before[2] or {}).get('status'),'one_unit_supported')
        self.confirm()
        after=self.signals()
        self.assertEqual(page_correspondence(self.c,self.root,self.ds,self.bid,[2])[2]['panel_signal']['presence'],'found')
        self.assertEqual(after[2]['status'],'one_unit_supported')
        self.assertEqual(after[3]['status'],'already_used')
        self.assertEqual(len(after[2]['code_correspondence_ids']),1)
        from app.row_decisions import authorization_shortfall
        self.assertEqual(authorization_shortfall(__import__('decimal').Decimal('30.00'),after[3])['amount_ars'],'30.00')
    def test_alias_applies_to_another_invoice_without_reusing_order(self):
        self.confirm();another=self.invoice([('05/08/2026',INVOICE)])
        self.assertEqual(self.signals(another,(2,))[2]['status'],'already_used')
    def test_history_withdrawal_and_concurrent_version(self):
        version=self.version();self.confirm()
        with self.assertRaises(Problem) as caught:self.confirm(version=version)
        self.assertEqual(caught.exception.status,409)
        self.confirm(False)
        self.assertEqual(len(listing(self.c,self.root,self.token,self.ds,self.source['id'])['history']),2)
        self.assertNotEqual((self.signals()[2] or {}).get('status'),'one_unit_supported')
    def test_broad_category_is_not_accepted_as_specific_equivalence(self):
        with self.assertRaises(Problem) as caught:self.confirm(pairs=[['678901','6789010100']])
        self.assertEqual(caught.exception.status,422)
    def test_http_registry_and_identity_survive_restart(self):
        from fastapi.testclient import TestClient
        from app.api import create_app
        from tests.test_p02 import ORIGIN
        with TestClient(create_app(self.root,public_origin=ORIGIN),base_url=ORIGIN) as client:
            login=client.post('/api/session',json={'username':'admin-ficticio','password':'Frase ficticia de prueba R23'},headers={'Origin':ORIGIN})
            self.assertEqual(login.status_code,200)
            headers={'Origin':ORIGIN,'X-CSRF-Token':login.json()['csrf_token']}
            url=f'/api/datasets/{self.ds}/sources/{self.source["id"]}/code-correspondences'
            page=client.get(url)
            self.assertEqual(page.status_code,200)
            body={'expected_version':page.json()['dataset_version'],'pairs':[[INVOICE,CSV]],'active':True,
                  'reason':'Cotejo ficticio de ambos códigos en el catálogo.'}
            self.assertEqual(client.post(url,json=body,headers=headers).status_code,201)
            self.assertEqual(client.post(url,json=body,headers=headers).status_code,409)
            self.assertTrue(next(r for r in client.get(url).json()['items'] if r['invoice_code']==INVOICE)['active'])
        from app.code_correspondences import Correspondences
        c=connect(self.root)
        try:
            self.assertEqual(Correspondences(c,self.root,self.ds,self.bid).identity(CSV),INVOICE)
        finally:c.close()

    def test_reviewer_cannot_register_correspondence(self):
        u=create_user(self.c,'reviewer-ficticio','Frase ficticia de prueba R23','reviewer')
        grant_access(self.c,self.token,self.ds,self.version(),'reviewer-ficticio','reviewer','administrative')
        token=token_digest(issue_session(self.c,u)[0])
        with self.assertRaises(Problem) as caught:self.confirm(token=token)
        self.assertEqual(caught.exception.status,403)


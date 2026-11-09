"""Fictitious R24 tests for families, billed units and same-order components."""
from io import BytesIO
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
import hashlib,json,sqlite3,unittest
from openpyxl import load_workbook
from tests import test_r23 as base
from tests.test_hpc_csv_intake import row,encode
from tests.test_p02 import book
from app.code_correspondences import listing,save
from app.service import create_batch,confirm_invoice,Problem
from app.economic_evidence import confirm_provider_scope
from app.review import _batch
from app.authorization_imports import stage_authorization,preview_authorization,confirm_authorization
from app.authorization_matching import save_scope,page_correspondence
from app.row_decisions import authorization_shortfall

BASE_CATALOG=base.catalog

def catalogue(folder):
    _,manifest,_=BASE_CATALOG(folder)
    p=folder/'catalogo_ficticio.sqlite'
    with closing(sqlite3.connect(p)) as c:
        c.executemany('INSERT INTO hpc_catalog_practices VALUES (?,?,?,?)',[
            (30,'f-rx','Imágenes','RX tórax ficticia'),(31,'f-tac-contraste','Imágenes','TAC con contraste ficticia'),
            (32,'f-mamo','Imágenes','Mamografía ficticia'),(33,'f-gamma','Imágenes','Gammagrafía ficticia')])
        entries=[
          (30,30,'f-rx',0,'NOMENCLADOR','340301','nomenclador','Radiografía de tórax, primera exposición'),
          (31,30,'f-rx',1,'HPC','3403010500','orden','RX tórax ficticia'),
          (32,30,'f-rx',2,'NOMENCLADOR','340302','nomenclador','Por exposición subsiguiente'),
          (33,31,'f-tac-contraste',0,'NOMENCLADOR',base.INVOICE,'nomenclador','TAC de abdomen con o sin contraste ficticia'),
          (34,31,'f-tac-contraste',1,'HPC','6543210200','orden','TAC con contraste ficticia'),
          (35,32,'f-mamo',0,'NOMENCLADOR','340601','nomenclador','Mamografía por lado'),
          (36,32,'f-mamo',1,'HPC','3406010200','orden','Mamografía bilateral ficticia'),
          (37,33,'f-gamma',0,'NOMENCLADOR','260508','nomenclador','Centellograma óseo de un área'),
          (38,33,'f-gamma',1,'NOMENCLADOR','260509','nomenclador','Áreas subsiguientes'),
          (39,33,'f-gamma',2,'HPC','2605090000','orden','Gammagrafía ósea corporal total ficticia'),
        ]
        c.executemany('INSERT INTO hpc_catalog_codes VALUES (?,?,?,?,?,?,?,?)',entries)
        c.commit()
        info=json.loads(manifest)
        for table in info['counts']:info['counts'][table]=c.execute('SELECT count(*) FROM "'+table+'"').fetchone()[0]
    content=p.read_bytes();sha=hashlib.sha256(content).hexdigest()
    info['files']['valores_convenios_base_2026-10-09.sqlite']={'sha256':sha,'bytes':len(content)}
    return content,json.dumps(info).encode(),sha


class R24(unittest.TestCase):
    def setUp(self):
        mocked=patch('tests.test_r23.catalog',catalogue);mocked.start();self.addCleanup(mocked.stop)
        self.f=base.CorrespondenceFlow();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.c,self.root,self.ds,self.token,self.source=self.f.c,self.f.root,self.f.ds,self.f.token,self.f.source['id']
    def register(self,pairs,kind=None):
        page=listing(self.c,self.root,self.token,self.ds,self.source)
        proposals={(p['invoice_code'],p['authorization_code']):p for p in page['items']}
        changes=[]
        for pair in pairs:
            p=proposals[tuple(pair)]
            changes.append({k:p[k] for k in ('invoice_code','authorization_code','relation_kind','factor','billing_unit')})
            changes[-1]['active']=True
            if kind:changes[-1]['relation_kind']=kind
        return save(self.c,self.root,self.token,self.ds,self.source,expected_version=self.f.version(),
                    changes=changes,reason='Verificación enteramente ficticia de códigos, componentes y unidades en las fuentes.')
    def source_csv(self,practices,affiliate='000222/1',quantity_text='',movement=None):
        raw=encode([row(orden_hpc='FICTICIO-R24',afiliado=affiliate,practicas=practices,
                       fecha_orden='2026-07-02',fecha_orden_original='02/07/2026',
                       movimientos=movement or '02/07/2026 12:00 | Operador ficticio | AUTORIZADO | ')])
        up,_=stage_authorization(self.c,self.root,self.token,self.ds,self.f.version(),'FICTICIO.csv',raw)
        p=preview_authorization(self.c,self.root,self.token,self.ds,up['id'])
        cap,_=confirm_authorization(self.c,self.root,self.token,self.ds,up['id'],self.f.version(),p['preview_sha256'],'Fuente enteramente ficticia R24.')
        self.cap=cap['id']
    def invoice(self,entries):
        wb=load_workbook(BytesIO(book([(r.get('date','02/08/2026'),50000,50000,100000) for r in entries])))
        for n,r in enumerate(entries,2):
            for col,value in [(2,r.get('order','R24-ORDEN')),(3,r.get('affiliate','000222/1')),(5,r['code']),
                              (7,r.get('qty',1)),(11,r.get('description','Práctica ficticia'))]:
                wb.active.cell(n,col).value=value
        out=BytesIO();wb.save(out);wb.close()
        lot,_=create_batch(self.c,self.root,self.token,self.ds,self.f.version(),'FICTICIO.xlsx',out.getvalue());bid=lot['id']
        confirm_invoice(self.c,self.root,self.token,self.ds,bid,'2026-08',self.f.version())
        confirm_provider_scope(self.c,self.root,self.token,self.ds,bid,self.source,'HPC','unverified',
            'Factura enteramente ficticia HPC.',self.f.version(),_batch(self.c,self.ds,bid)['revision_version'])
        save_scope(self.c,self.root,self.token,self.ds,bid,self.f.version(),[self.cap],'real_unvalidated','CSV ficticio completo.',
                   csv_complete_from='2026-06-01',csv_complete_until='2026-08-31')
        self.bid=bid
        return bid
    def signals(self,numbers=None):
        numbers=numbers or [r[0] for r in self.c.execute('SELECT source_row FROM invoice_rows WHERE import_id=(SELECT id FROM current_invoice_imports WHERE batch_id=?)',(self.bid,))]
        return {n:r['panel_signal'].get('csv_coverage',{}) for n,r in page_correspondence(self.c,self.root,self.ds,self.bid,numbers).items()}
    def test_bilateral_one_study_covers_two_sides_and_cannot_be_reused(self):
        self.source_csv('3406010200 -- Mamografía bilateral ficticia,')
        self.invoice([dict(code='340601',qty=2),dict(code='340601',qty=2,date='04/08/2026')])
        self.register([['340601','3406010200']])
        signals=self.signals()
        self.assertEqual(signals[2]['status'],'units_supported')
        self.assertEqual((signals[2]['covered_units'],signals[2]['normalized_studies']),(2,'1'))
        self.assertEqual(signals[3]['status'],'already_used')
        self.assertIsNone(authorization_shortfall(__import__('decimal').Decimal(100000),signals[2]))
    def test_family_does_not_make_two_different_complete_codes_equivalent(self):
        self.source_csv('6543210200 -- TAC con contraste ficticia,')
        self.invoice([dict(code='6543210100',description='TAC ficticia')])
        self.register([[base.INVOICE,base.CSV],[base.INVOICE,'6543210200']])
        self.assertNotEqual(self.signals()[2].get('status'),'one_unit_supported')
    def test_two_side_lines_same_order_use_one_bilateral_study(self):
        self.source_csv('3406010200 -- Mamografía bilateral ficticia,')
        self.invoice([dict(code='340601',qty=1),dict(code='340601',qty=1)])
        self.register([['340601','3406010200']])
        sig=self.signals()
        self.assertEqual([sig[n]['status'] for n in (2,3)],['units_supported','units_supported'])
        self.assertEqual(sum(__import__('decimal').Decimal(sig[n]['assigned_studies']) for n in (2,3)),1)
    def exposure(self,qty=1,modifier=True,other_patient=False):
        self.source_csv('3403010500 -- RX tórax ficticia,'+('3402130020 -- FRENTE Y PERFIL,' if modifier else ''))
        self.invoice([dict(code='340301'),dict(code='340302',qty=qty,affiliate='000333/1' if other_patient else '000222/1')])
        pairs=[['340301','3403010500'],['340302','340301']]
        if modifier:pairs.append(['3402130020','3402130020'])
        self.register(pairs)
        return self.signals()
    def test_exposure_component_uses_principal_and_documented_views(self):
        sig=self.exposure()
        self.assertEqual(sig[2]['status'],'one_unit_supported')
        self.assertEqual(sig[3]['status'],'component_supported')
        self.assertEqual((sig[3]['parent_row'],sig[3]['documented_projections']),(2,2))
        self.assertEqual(sig[2]['locator'],sig[3]['locator'])
    def test_excess_exposures_and_unknown_counts_stay_pending_without_partial_debit(self):
        for modifier,qty in [(True,3),(False,1)]:
            with self.subTest(modifier=modifier):
                sig=self.exposure(qty,modifier)
                self.assertEqual(sig[3]['status'],'component_pending')
                self.assertIsNone(authorization_shortfall(__import__('decimal').Decimal(100000),sig[3]))
    def test_projection_before_unique_principal_is_attached_without_position_guess(self):
        self.source_csv('3402130020 -- FRENTE Y PERFIL,3403010500 -- RX tórax ficticia,')
        self.invoice([dict(code='340301'),dict(code='340302')])
        self.register([['340301','3403010500'],['340302','340301'],['3402130020','3402130020']])
        self.assertEqual(self.signals()[3]['status'],'component_supported')
    def test_projection_with_multiple_principals_does_not_choose_an_attachment(self):
        self.source_csv('3402130020 -- FRENTE Y PERFIL,3403010500 -- RX tórax ficticia,6543210200 -- TAC con contraste ficticia,')
        self.invoice([dict(code='340301'),dict(code='340302')])
        self.register([['340301','3403010500'],['340302','340301'],['3402130020','3402130020']])
        self.assertEqual(self.signals()[3]['status'],'component_pending')
    def test_component_never_crosses_patient(self):
        sig=self.exposure(other_patient=True)
        self.assertEqual(sig[3]['status'],'component_pending')
        self.assertNotIn('parent_row',sig[3])
    def test_parent_is_found_outside_current_page(self):
        self.exposure()
        sig=self.signals([3])[3]
        self.assertEqual(sig['status'],'component_supported')
        self.assertEqual(sig['parent_row'],2)
    def test_projection_codes_are_not_separate_study_equivalences(self):
        self.exposure()
        with self.assertRaises(Problem):
            save(self.c,self.root,self.token,self.ds,self.source,expected_version=self.f.version(),
                 pairs=[['340301','3402130020']],active=True,reason='Prueba ficticia de rechazo de atributo.')
    def test_areas_are_components_and_not_partial_whole_body_studies(self):
        self.source_csv('2605090000 -- Gammagrafía ósea corporal total ficticia,')
        self.invoice([dict(code='260508'),dict(code='260509',qty=6)])
        self.register([['260509','260508']])
        self.assertEqual(self.signals()[3]['status'],'component_pending')
        with self.assertRaises(Problem):
            save(self.c,self.root,self.token,self.ds,self.source,expected_version=self.f.version(),
                 pairs=[['260509','2605090000']],active=True,reason='El adicional no es un estudio corporal entero.')
    def test_mixed_bulk_change_is_atomic_and_preserves_history(self):
        self.exposure()
        before=self.c.execute('SELECT count(*) FROM hpc_code_correspondences').fetchone()[0]
        page=listing(self.c,self.root,self.token,self.ds,self.source)
        good=next(p for p in page['items'] if p['invoice_code']=='340301')
        changes=[dict(invoice_code=good['invoice_code'],authorization_code=good['authorization_code'],
                      active=False),dict(invoice_code='999999',authorization_code='9999999999',active=True)]
        with self.assertRaises(Problem):
            save(self.c,self.root,self.token,self.ds,self.source,expected_version=self.f.version(),changes=changes,
                 reason='Prueba ficticia de operación indivisible.')
        self.assertEqual(self.c.execute('SELECT count(*) FROM hpc_code_correspondences').fetchone()[0],before)

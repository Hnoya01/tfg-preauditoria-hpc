"""Fictional catalog families: display filters never infer prefixes or coverage."""

import hashlib
import json
import sqlite3
import unittest
from io import BytesIO
from zipfile import ZipFile

from app.db import connect
from app.practice_families import family_for, classify_family, normalized_name
from app.values_v1 import register_values
from app.storage import object_path
from tests import test_practice_board as board
from tests.test_p03 import fictional_values
from tests.test_p02 import book


def fictional_family_values(folder, neutral=False):
    _, manifest, _ = fictional_values(folder)
    path = folder/'catalogo_ficticio.sqlite'
    c = sqlite3.connect(path)
    c.execute('DROP TABLE hpc_catalog_components')
    c.execute('CREATE TABLE hpc_catalog_components(component TEXT,part INTEGER,text_data TEXT)')
    c.execute('DROP TABLE hpc_catalog_practices')
    c.execute('CREATE TABLE hpc_catalog_practices(seq INTEGER,name TEXT,area TEXT)')
    c.executemany('INSERT INTO hpc_catalog_practices VALUES (?,?,?)',
                  [(11,'Ecografía ficticia','Imágenes'),(12,'Laboratorio ficticio','Laboratorio')])
    c.execute('DELETE FROM hpc_catalog_codes')
    c.executemany('INSERT INTO hpc_catalog_codes VALUES (?,?,?,?,?,?,?,?)',
                  [(1,11,'fiction-img',1,'HPC','123456','orden','Ecografía ficticia'),
                   (2,12,'fiction-lab',1,'HPC','654321','orden','Laboratorio ficticio'),
                   (3,11,'fiction-conflict-a',1,'HPC','888888','orden','Conflicto ficticio'),
                   (4,12,'fiction-conflict-b',1,'HPC','888888','orden','Conflicto ficticio'),
                   (5,11,'fiction-suffix',1,'HPC','1801010000','orden','Código largo ficticio'),
                   (6,11,'fiction-other-provider',1,'OTRO','999999','orden','Otro prestador ficticio'),
                   (7,11,'fiction-tariff',1,'HPC','777777','convenio','Arancel ficticio')])
    if neutral:
        c.execute("UPDATE hpc_catalog_codes SET provider='NOMENCLADOR',kind='nomenclador' WHERE seq=1")
        component={'area':'Imágenes','sourceFile':'FICTICIO.xlsx','rows':[
            {'nomencladorCode':'123456','description':'Ecografía ficticia','sourceRow':42,
             'equivalence':{'kind':'sin_equivalente'},'amount':999999}]}
        c.execute('INSERT INTO hpc_catalog_components VALUES (?,?,?)',
                  ('seed.nomencladorImagenes',0,json.dumps(component)))
    c.commit()
    counts={r[0]:c.execute(f'SELECT count(*) FROM "{r[0]}"').fetchone()[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    c.close()
    content=path.read_bytes();sha=hashlib.sha256(content).hexdigest();data=json.loads(manifest)
    data['counts']=counts;data['files']['valores_convenios_base_2026-10-09.sqlite']={'sha256':sha,'bytes':len(content)}
    return content,json.dumps(data).encode(),sha


class PracticeFamilyTests(unittest.TestCase):
    setUp=board.PracticeBoardTests.setUp
    tearDown=board.PracticeBoardTests.tearDown
    headers=board.PracticeBoardTests.headers
    import_book=board.PracticeBoardTests.import_book
    run_url=board.PracticeBoardTests.run_url
    base=board.PracticeBoardTests.base
    search=board.PracticeBoardTests.search

    def test_image_review_view_includes_shortlist_without_reclassification(self):
        source=book([('17/08/2026',10,20,30)]*5)
        output=BytesIO()
        with ZipFile(BytesIO(source)) as original, ZipFile(output,'w') as target:
            for name in original.namelist():
                data=original.read(name)
                if name=='xl/worksheets/sheet1.xml':
                    text=data.decode()
                    for row,code in enumerate(('123456','183004','654321','999999','888888'),start=2):
                        text=text.replace(f'<c r="E{row}"><v>123456</v></c>',f'<c r="E{row}"><v>{code}</v></c>')
                    data=text.encode()
                target.writestr(name,data)
        self.batch=self.import_book(output.getvalue(),'REVISION_IMAGENES_FICTICIA.xlsx')
        self.assertEqual(self.search(family='images_and_candidates')['filtered_total'],0)
        content,manifest,sha=fictional_family_values(self.root)
        c=connect(self.root)
        result,_=register_values(c,self.root,self.digest,self.dataset['id'],self.dataset['version'],content,manifest,sha)
        self.dataset['version']=result['dataset_version']
        before=[tuple(r) for r in c.execute('SELECT id,version FROM datasets')]
        c.close()
        strict=self.search(family='images')
        self.assertEqual(strict['filtered_total'],1)
        self.assertEqual(strict['image_candidate_count'],1)
        both=self.search(family='images_and_candidates')
        self.assertEqual([r['source_row'] for r in both['items']],[2,3])
        self.assertEqual(both['family_counts'],{'images':1,'other':1,'unclassified':3})
        candidate=both['items'][1]
        self.assertEqual(candidate['family'],'unclassified')
        self.assertEqual(candidate['family_suggestion']['status'],'requires_manual_review')
        self.assertFalse(candidate['family_suggestion']['economic_equivalence_established'])
        self.assertEqual(self.search(family='unclassified')['filtered_total'],3)
        for offset,item in enumerate(both['items']):
            page=self.search(family='images_and_candidates',limit=1,offset=offset)
            self.assertEqual(page['items'],[item])
            self.assertEqual(page['filtered_total'],2)
        self.assertEqual(self.search(family='images_and_candidates',code='654321')['filtered_total'],0)
        filtered=self.search(family='images_and_candidates',code='183004')['items']
        self.assertEqual(len(filtered),1)
        self.assertEqual(filtered[0]['source_row'],candidate['source_row'])
        self.assertEqual(filtered[0]['family_suggestion'],candidate['family_suggestion'])
        self.assertEqual(filtered[0]['checks'],candidate['checks'])
        self.assertEqual(self.search(family='images')['items'],strict['items'])
        self.assertFalse(both['analysis_started']);self.assertFalse(both['decision_written'])
        c=connect(self.root)
        self.assertEqual([tuple(r) for r in c.execute('SELECT id,version FROM datasets')],before)
        c.close()
        object_path(self.root,sha).write_bytes(content+b'alteracion ficticia')
        unavailable=self.search(family='images_and_candidates')
        self.assertEqual(unavailable['filtered_total'],0)
        self.assertEqual(unavailable['image_candidate_count'],0)
        self.assertFalse(unavailable['classification']['available'])

    def test_only_exact_hpc_order_codes_classify_and_history_controls_remain_unchanged(self):
        source=book([('17/08/2026',10,20,30)]*6)
        output=BytesIO()
        with ZipFile(BytesIO(source)) as original, ZipFile(output,'w') as target:
            for name in original.namelist():
                data=original.read(name)
                if name=='xl/worksheets/sheet1.xml':
                    text=data.decode()
                    for row,code in enumerate(('123456','654321','888888','180101','999999','777777'),start=2):
                        text=text.replace(f'<c r="E{row}"><v>123456</v></c>',f'<c r="E{row}"><v>{code}</v></c>')
                    data=text.encode()
                target.writestr(name,data)
        self.batch=self.import_book(output.getvalue(),'FAMILIAS_FICTICIAS.xlsx')
        content,manifest,sha=fictional_family_values(self.root)
        c=connect(self.root)
        result,_=register_values(c,self.root,self.digest,self.dataset['id'],self.dataset['version'],content,manifest,sha)
        self.dataset['version']=result['dataset_version']
        before=[tuple(r) for r in c.execute('SELECT id,version FROM datasets')]
        runs=c.execute('SELECT count(*) FROM control_runs').fetchone()[0]
        c.close()
        page=self.search(family='images')
        self.assertEqual([r['source_row'] for r in page['items']],[2])
        self.assertEqual(page['family_counts'],{'images':1,'other':1,'unclassified':4})
        self.assertEqual(page['classification']['sources'][0]['source_sha256'],sha)
        self.assertEqual(page['classification']['sources'][0]['cut_label'],'BASE_2026-10-09')
        self.assertEqual(self.search(family='other')['filtered_total'],1)
        self.assertEqual(self.search(family='unclassified')['filtered_total'],4)
        self.assertEqual(self.search()['filtered_total'],6)
        c=connect(self.root)
        self.assertEqual([tuple(r) for r in c.execute('SELECT id,version FROM datasets')],before)
        self.assertEqual(c.execute('SELECT count(*) FROM control_runs').fetchone()[0],runs)
        c.close()
        object_path(self.root,sha).write_bytes(content+b'alteracion ficticia')
        unavailable=self.search(family='images')
        self.assertFalse(unavailable['classification']['available'])
        self.assertTrue(unavailable['classification']['source_unavailable'])
        self.assertEqual(unavailable['filtered_total'],0)
        self.assertEqual(self.search(family='unclassified')['filtered_total'],6)

    def test_no_catalog_is_unknown_and_search_is_full_lot_private_prepared_data_only(self):
        self.assertEqual(self.search(family='images')['filtered_total'],0)
        self.assertFalse(self.search()['classification']['available'])
        for text in ('000123/4','PACIENTE FICTICIO','123456','Práctica ficticia'):
            self.assertEqual(self.search(search=text)['filtered_total'],2)
        self.assertEqual(self.search(search='etiqueta histórica')['filtered_total'],0)
        for filters in ({'family':'assume_all_images'},{'search':'x'*101}):
            self.assertEqual(self.client.post(self.base()+'/practice-search',json=filters,headers=self.headers()).status_code,422)

    def test_conflicts_and_unmatched_never_become_other_or_images_by_guess(self):
        self.assertEqual(family_for('180101',{'1801010000':{'Imágenes'}}),'unclassified')
        self.assertEqual(family_for('012345',{'12345':{'Imágenes'}}),'unclassified')
        self.assertEqual(family_for('1',{'1':{'Imágenes','Laboratorio'}}),'unclassified')


    def test_exact_name_fallback_is_display_only_and_conflicts_remain_unknown(self):
        names={normalized_name('Ecografía ficticia'):{'Imágenes'}, normalized_name('Laboratorio ficticio'):{'Laboratorio'}}
        self.assertEqual(classify_family('unknown', {}, ' ECOGRAFIA   FICTICIA ', names),
                         ('images','exact_normalized_catalog_name'))
        self.assertEqual(classify_family('unknown', {}, 'Ecografía ficticia adicional', names)[0], 'unclassified')
        self.assertEqual(classify_family('654321', {'654321':{'Laboratorio'}}, 'Ecografía ficticia', names)[0], 'unclassified')
        self.assertEqual(classify_family('123456', {'123456':{'Imágenes'}}, 'Sin nombre catalogado', names)[0], 'images')
        self.assertEqual(classify_family('123456', {'123456':{'Imágenes','Laboratorio'}}, 'Ecografía ficticia', names)[0], 'unclassified')
        names[normalized_name('Ecografía ficticia')].add('Laboratorio')
        self.assertEqual(classify_family('unknown', {}, 'Ecografía ficticia', names)[0], 'unclassified')

    def test_patient_counts_span_pages_without_changing_invoice(self):
        self.batch=self.import_book(book([('17/08/2026',10,20,30)]*60),'PAGINAS_FICTICIAS.xlsx')
        first=self.search(sort='affiliate_id',offset=0,limit=50)
        second=self.search(sort='affiliate_id',offset=50,limit=50)
        self.assertEqual(first['filtered_total'],60)
        self.assertEqual(first['items'][0]['patient_group_total'],60)
        self.assertEqual(first['items'][0]['patient_group_position'],1)
        self.assertEqual(second['items'][0]['patient_group_total'],60)
        self.assertEqual(second['items'][0]['patient_group_position'],51)
        self.assertFalse(second['analysis_started'])
        self.assertFalse(second['decision_written'])

    def test_registered_catalog_name_matches_without_linking_or_pricing(self):
        source=book([('17/08/2026',10,20,30)])
        output=BytesIO()
        with ZipFile(BytesIO(source)) as original, ZipFile(output,'w') as target:
            for name in original.namelist():
                data=original.read(name)
                if name=='xl/worksheets/sheet1.xml':
                    text=data.decode().replace('<c r="E2"><v>123456</v></c>','<c r="E2"><v>999998</v></c>')
                    text=text.replace('Práctica ficticia','ECOGRAFIA FICTICIA')
                    data=text.encode()
                target.writestr(name,data)
        self.batch=self.import_book(output.getvalue(),'NOMBRE_FICTICIO.xlsx')
        content,manifest,sha=fictional_family_values(self.root)
        conn=connect(self.root)
        result,_=register_values(conn,self.root,self.digest,self.dataset['id'],self.dataset['version'],content,manifest,sha)
        self.dataset['version']=result['dataset_version']
        before={table:conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
                for table in ('control_runs','row_economic_references','proposal_versions')}
        conn.close()
        page=self.search(family='images')
        self.assertEqual(page['filtered_total'],1)
        self.assertEqual(page['items'][0]['code'],'999998')
        self.assertEqual(page['items'][0]['family_basis'],'exact_normalized_catalog_name')
        conn=connect(self.root)
        for table,count in before.items():
            self.assertEqual(conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0],count)
        conn.close()


    def test_neutral_board_returns_source_locators_without_economic_writes(self):
        content,manifest,sha=fictional_family_values(self.root, neutral=True)
        conn=connect(self.root)
        result,_=register_values(conn,self.root,self.digest,self.dataset['id'],self.dataset['version'],content,manifest,sha)
        self.dataset['version']=result['dataset_version']
        tables=('control_runs','row_economic_references','proposal_versions')
        before={table:conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for table in tables}
        conn.close()
        page=self.search(family='images')
        self.assertEqual(page['filtered_total'],2)
        for row in page['items']:
            self.assertEqual(row['code'],'123456')
            self.assertEqual(row['family_basis'],'exact_nomenclature_code')
            self.assertTrue(row['family_evidence']['display_only'])
            self.assertEqual(len(row['family_evidence']['code']),2)
            self.assertEqual(row['family_evidence']['code'][1]['source_row'],42)
            self.assertEqual(row['family_evidence']['code'][0]['source_sha256'],sha)
        conn=connect(self.root)
        for table,count in before.items():
            self.assertEqual(conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0],count)
        conn.close()

    def test_signs_and_multiple_non_image_areas_are_not_collapsed(self):
        names={normalized_name('MARCADOR +'):{'Imágenes'},normalized_name('MARCADOR -'):{'Laboratorio'}}
        self.assertNotEqual(normalized_name('MARCADOR +'),normalized_name('MARCADOR -'))
        self.assertEqual(classify_family('unknown', {}, 'MARCADOR -', names)[0],'other')
        self.assertEqual(classify_family('unknown', {}, 'MARCADOR', names)[0],'unclassified')
        ambiguous={normalized_name('Práctica ambigua'):{'Laboratorio','Consultas'}}
        self.assertEqual(classify_family('unknown', {}, 'Práctica ambigua', ambiguous),
                         ('unclassified','conflicting_catalog_evidence'))
        self.assertEqual(family_for('111111', {'111111':{'Laboratorio','Consultas'}}),'unclassified')


class NeutralNomenclatureTests(unittest.TestCase):
    def load(self, entries=(), component=None, malformed=False):
        from unittest.mock import patch
        from app.practice_families import catalog_families
        conn=sqlite3.connect(':memory:');conn.row_factory=sqlite3.Row
        conn.executescript("CREATE TABLE source_registry(id,source_sha256,cut_label,dataset_id,kind,status);INSERT INTO source_registry VALUES(7,'fictional-sha','fictional-cut',1,'values','registered');")
        source=sqlite3.connect(':memory:')
        source.executescript('CREATE TABLE hpc_catalog_practices(seq,name,area);CREATE TABLE hpc_catalog_codes(seq,code,practice_seq,description,provider,kind);')
        for seq,code,name,area,provider,kind in entries:
            source.execute('INSERT INTO hpc_catalog_practices VALUES(?,?,?)',(seq,name,area))
            source.execute('INSERT INTO hpc_catalog_codes VALUES(?,?,?,?,?,?)',(seq,code,seq,name,provider,kind))
        if component is not None or malformed:
            source.execute('CREATE TABLE hpc_catalog_components(component,part,text_data)')
            content='{broken' if malformed else json.dumps(component)
            for part,text in [(1,content[10:]),(0,content[:10])]:
                source.execute('INSERT INTO hpc_catalog_components VALUES(?,?,?)',('seed.nomencladorImagenes',part,text))
        with patch('app.practice_families.read_verified',return_value=b'fictional'),patch('app.practice_families.source_db',return_value=source):
            result=catalog_families(conn,object(),1)
        conn.close();return result

    def component(self):
        return {'area':'Imágenes','sourceFile':'FICTICIO.xlsx','rows':[{'nomencladorCode':'001234','description':'Imagen neutra +','sourceRow':42,'amount':999999,'practiceIds':['not-an-economic-link'],'equivalence':{'kind':'sin_equivalente'}}]}

    def test_neutral_links_exact_codes_and_provenance(self):
        from app.practice_families import classification_evidence
        areas,names,meta=self.load([(1,'001234','Imagen neutra','Imágenes','NOMENCLADOR','nomenclador')])
        self.assertEqual(classify_family('001234',areas,None,names),('images','exact_nomenclature_code'))
        for code in ('1234','00123400','0012','00.12.34'):
            self.assertEqual(classify_family(code,areas,None,names)[0],'unclassified')
        evidence=classification_evidence('001234',areas,None,names)
        self.assertEqual(evidence['code'][0]['seq'],1)
        self.assertEqual(evidence['code'][0]['source_sha256'],'fictional-sha')
        self.assertTrue(evidence['display_only']);self.assertFalse(meta['economic_equivalence_established'])

    def test_structured_component_not_economic_equivalence(self):
        from app.practice_families import classification_evidence
        areas,names,_=self.load(component=self.component())
        self.assertEqual(classify_family('001234',areas,None,names),('images','exact_nomenclature_code'))
        evidence=classification_evidence('001234',areas,None,names)['code'][0]
        self.assertEqual(evidence['source_row'],42);self.assertEqual(evidence['source_file'],'FICTICIO.xlsx')
        self.assertNotIn('amount',evidence);self.assertNotIn('practiceIds',evidence)
        self.assertEqual(classify_family('unknown',areas,' IMAGEN  NEUTRA + ',names)[0],'images')
        self.assertEqual(classify_family('unknown',areas,'Imagen neutra -',names)[0],'unclassified')

    def test_hpc_neutral_collision_and_agreement(self):
        areas,names,_=self.load([(1,'001234','Laboratorio local','Laboratorio','HPC','orden')],self.component())
        self.assertEqual(classify_family('001234',areas,None,names),('unclassified','conflicting_catalog_evidence'))
        areas,names,_=self.load([(1,'001234','Imagen local','Imágenes','HPC','orden')],self.component())
        self.assertEqual(classify_family('001234',areas,None,names),('images','exact_hpc_order_code'))

    def test_name_collisions_remain_unknown(self):
        areas,names,_=self.load([(1,'999999','Imagen neutra +','Laboratorio','HPC','orden')],self.component())
        self.assertEqual(classify_family('unknown',areas,'Imagen neutra +',names)[0],'unclassified')
        self.assertEqual(classify_family('001234',areas,'Imagen neutra +',names)[0],'unclassified')

    def test_foreign_and_wrong_kind_excluded(self):
        areas,names,_=self.load([(1,'123456','Ajena','Imágenes','OTRO','orden'),(2,'234567','Precio HPC','Imágenes','HPC','convenio'),(3,'345678','Precio neutral','Imágenes','NOMENCLADOR','convenio')])
        self.assertFalse(areas);self.assertFalse(names)

    def test_malformed_fails_closed(self):
        areas,names,meta=self.load([(1,'001234','Imagen HPC','Imágenes','HPC','orden')],malformed=True)
        self.assertFalse(meta['available']);self.assertTrue(meta['source_unavailable'])
        self.assertFalse(areas);self.assertFalse(areas.origins);self.assertFalse(names.origins)

    def test_same_area_repeated_links_not_ambiguous(self):
        entries=[(1,'001234','Imagen A','Imágenes','NOMENCLADOR','nomenclador'),(2,'001234','Imagen B','Imágenes','NOMENCLADOR','nomenclador')]
        areas,names,_=self.load(entries,self.component())
        self.assertEqual(classify_family('001234',areas,None,names)[0],'images')
        self.assertEqual(len(areas.origins['001234']),3)

import unittest
from app.practice_families import FamilyIndex, _add, classify_family, classification_evidence
from app.verified_display_nomenclature import ENTRIES, SOURCE, suggestion

class ReviewedDisplayTests(unittest.TestCase):
    def setUp(self):
        self.areas,self.names=FamilyIndex(),FamilyIndex()
        for code,area,row,description in ENTRIES:
            _add(self.areas,self.names,code,area,(),dict(SOURCE,source_row=row))
    def classify(self,code,name=''):
        return classify_family(code,self.areas,name,self.names)
    def test_consultations_exact_and_nonmonetary(self):
        for code in ('420101','420103'):
            self.assertEqual(self.classify(code)[0],'other')
            self.assertEqual(self.classify(code+'00')[0],'unclassified')
        self.assertEqual(self.classify('missing','Consulta médica.')[0],'unclassified')
        self.assertTrue(classification_evidence('420101',self.areas)['display_only'])
        self.assertNotIn('amount',SOURCE)
    def test_documented_overlap_preserves_specialty_and_origins(self):
        _add(self.areas,self.names,'180109','Oftalmología',(),{'kind':'hpc_order'})
        self.assertEqual(self.classify('180109'),('images','documented_modality_specialty_overlap'))
        ev=classification_evidence('180109',self.areas)
        self.assertEqual(ev['specialty'],'Oftalmología');self.assertEqual(len(ev['code']),2)
    def test_genuine_conflicts_remain_unclassified(self):
        _add(self.areas,self.names,'180109','Laboratorio',(),{'kind':'hpc_order'})
        self.assertEqual(self.classify('180109')[0],'unclassified')
        _add(self.areas,self.names,'123456','Laboratorio',('Descripción conflictiva',),{'kind':'hpc_order'})
        self.assertEqual(self.classify('420101','Descripción conflictiva')[0],'unclassified')
    def test_no_overlap_exception_without_reviewed_source(self):
        a,n=FamilyIndex(),FamilyIndex()
        for area in ('Imágenes','Oftalmología'):_add(a,n,'180109',area,(),{'kind':'hpc_order'})
        self.assertEqual(classify_family('180109',a)[0],'unclassified')
    def test_suggestions_never_classify_or_equate(self):
        for code in ('183004','183007','182002','187010','341053'):
            self.assertEqual(self.classify(code)[0],'unclassified')
            self.assertEqual(suggestion(code,'unclassified')['status'],'requires_manual_review')
            self.assertFalse(suggestion(code,'unclassified')['economic_equivalence_established'])
            self.assertIsNone(suggestion(code,'images'))
        self.assertIsNone(suggestion('18300400','unclassified'))

class ReviewedDisplayIntegrationTests(unittest.TestCase):
    from tests import test_practice_board as _board
    setUp=_board.PracticeBoardTests.setUp
    tearDown=_board.PracticeBoardTests.tearDown
    headers=_board.PracticeBoardTests.headers
    import_book=_board.PracticeBoardTests.import_book
    base=_board.PracticeBoardTests.base
    run_url=_board.PracticeBoardTests.run_url
    search=_board.PracticeBoardTests.search

    def test_board_reviewed_classification_and_hint_do_not_write_or_reprice(self):
        from io import BytesIO
        from zipfile import ZipFile
        from app.db import connect
        from app.values_v1 import register_values
        from app.storage import object_path
        from tests.test_p02 import book
        from tests.test_practice_families import fictional_family_values
        original=book([('17/08/2026',10,20,30)]*3);output=BytesIO()
        with ZipFile(BytesIO(original)) as source, ZipFile(output,'w') as target:
            for name in source.namelist():
                data=source.read(name)
                if name=='xl/worksheets/sheet1.xml':
                    text=data.decode()
                    for row,code in enumerate(('420101','180109','183004'),2):
                        text=text.replace(f'<c r="E{row}"><v>123456</v></c>',f'<c r="E{row}"><v>{code}</v></c>')
                    data=text.encode()
                target.writestr(name,data)
        self.batch=self.import_book(output.getvalue(),'CLASIFICACION_FICTICIA.xlsx')
        content,manifest,sha=fictional_family_values(self.root)
        conn=connect(self.root)
        result,_=register_values(conn,self.root,self.digest,self.dataset['id'],self.dataset['version'],content,manifest,sha)
        self.dataset['version']=result['dataset_version']
        tables=('control_runs','row_economic_references','proposal_versions','evidence_documents')
        before={t:conn.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in tables}
        version=conn.execute('SELECT version FROM datasets WHERE id=?',(self.dataset['id'],)).fetchone()[0];conn.close()
        page=self.search();items={r['code']:r for r in page['items']}
        self.assertEqual(page['family_counts'],{'images':1,'other':1,'unclassified':1})
        self.assertEqual(items['420101']['family_basis'],'exact_reviewed_nomenclature_code')
        self.assertEqual(items['180109']['family_evidence']['specialty'],'Oftalmología')
        self.assertEqual(items['183004']['family_suggestion']['status'],'requires_manual_review')
        self.assertEqual(self.search(family='images')['filtered_total'],1)
        self.assertEqual(items['420101']['total_ars'],'30.00')
        self.assertTrue(any(o['source_sha256']==SOURCE['source_sha256'] for o in items['420101']['family_evidence']['code']))
        conn=connect(self.root)
        self.assertEqual(before,{t:conn.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in tables})
        self.assertEqual(version,conn.execute('SELECT version FROM datasets WHERE id=?',(self.dataset['id'],)).fetchone()[0]);conn.close()
        self.assertEqual(object_path(self.root,sha).read_bytes(),content)
        object_path(self.root,sha).write_bytes(content+b'CORRUPCION_FICTICIA')
        unavailable=self.search()
        self.assertFalse(unavailable['classification']['available'])
        self.assertEqual(unavailable['family_counts'],{'images':0,'other':0,'unclassified':3})
        self.assertTrue(all(r['family_suggestion'] is None for r in unavailable['items']))

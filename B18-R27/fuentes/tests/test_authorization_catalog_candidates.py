"""All identities and codes invented; catalog links never authorize an item."""
import sqlite3
import unittest
from app.authorization_catalog_candidates import CodeRelations, suggest

class CatalogCandidateTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
        self.db.executescript('CREATE TABLE hpc_catalog_practices(seq,id); CREATE TABLE hpc_catalog_codes(seq,practice_seq,practice_id,provider,code,kind); INSERT INTO hpc_catalog_practices VALUES(1,"P1"),(2,"P2");')
        self.add(1,1,'P1','123456');self.add(2,1,'P1','1234560100');self.add(3,2,'P2','1234560200')
    def tearDown(self):self.db.close()
    def add(self,seq,pseq,pid,code,provider='HPC'):
        self.db.execute('INSERT INTO hpc_catalog_codes VALUES(?,?,?,?,?,?)',(seq,pseq,pid,provider,code,'orden'))
    def relations(self):return CodeRelations(self.db,'SRC','a'*64)
    def test_only_explicit_same_identity_never_prefix(self):
        result=self.relations().aliases('123456')
        self.assertEqual([r['authorization_code'] for r in result],['1234560100'])
        self.assertEqual(result[0]['invoice_code_seqs'],[1])
        self.assertFalse(result[0]['equivalence_verified'])
        self.assertEqual(self.relations().aliases('1234'),[])
    def test_conflicting_source_and_target_identity_block(self):
        self.add(4,2,'P2','1234560100')
        self.assertEqual(self.relations().aliases('123456'),[])
        self.add(5,2,'P2','123456')
        self.assertEqual(self.relations().aliases('123456'),[])
    def test_incoherent_and_other_provider_do_not_match(self):
        self.add(4,2,'P1','9999990000');self.add(5,1,'P1','8888880000','OTHER')
        self.assertEqual([x['authorization_code'] for x in self.relations().aliases('123456')],['1234560100'])
    def test_duplicate_practice_identity_blocks(self):
        self.db.execute('INSERT INTO hpc_catalog_practices VALUES(3,"P1")')
        self.assertEqual(self.relations().aliases('123456'),[])
    def evidence(self):return {'disposition':'included','issues':[],'invoice_fields':{'C':'12345','E':'123456'},'practice_date':'2026-08-10'}
    def entry(self,day=None,provider='HPC'):
        item={'item_id':'I','full_code':'1234560100','service_date':day}
        order={'order_id':'O','provider':provider,'items':[item],'resolutions':[],'global_status':None}
        return ({'id':'CAP','source_sha256':'b'*64},0,order,0,item,True)
    def test_repetitions_and_unknown_date_preserved_without_approval(self):
        e=self.entry();r=suggest(self.evidence(),{('12345','1234560100'):[e,e]},self.relations())
        self.assertEqual(r['candidate_count_total'],2)
        for c in r['candidates']:
            self.assertEqual(c['compatibility'],'needs_review');self.assertIsNone(c['checks']['date']);self.assertFalse(c['selectable'])
            self.assertEqual(c['resolution']['state'],'unresolved')
        self.assertEqual(r['authorization_result'],'no_concluyente')
    def test_identity_date_provider_and_scope_are_not_relaxed(self):
        index={('12345','1234560100'):[self.entry('2026-07-10'),self.entry(provider='OTHER')]}
        r=suggest(self.evidence(),index,self.relations());self.assertTrue(all(c['compatibility']=='incompatible' for c in r['candidates']))
        ev=self.evidence();ev['invoice_fields']['C']='9999';self.assertEqual(suggest(ev,index,self.relations())['candidate_count_total'],0)
        ev=self.evidence();ev['disposition']='excluded';self.assertEqual(suggest(ev,index,self.relations())['candidate_count_total'],0)
    def test_limit_is_visible_and_no_deduplication(self):
        r=suggest(self.evidence(),{('12345','1234560100'):[self.entry()]*201},self.relations())
        self.assertEqual(r['candidate_count_total'],201);self.assertEqual(len(r['candidates']),200);self.assertEqual(r['status'],'catalog_candidate_limit')

    def test_neutral_category_preserves_separate_practices(self):
        self.db.executemany('INSERT INTO hpc_catalog_codes VALUES(?,?,?,?,?,?)',[(4,1,'P1','NOMENCLADOR','340000','nomenclador'),(5,2,'P2','NOMENCLADOR','340000','nomenclador')])
        aliases=self.relations().aliases('340000')
        self.assertEqual({r['authorization_code'] for r in aliases},{'123456','1234560100','1234560200'})
        self.assertTrue(all(r['category_is_broad'] and not r['equivalence_verified'] for r in aliases))
        self.assertEqual(len({r['practice_id'] for r in aliases}),2)

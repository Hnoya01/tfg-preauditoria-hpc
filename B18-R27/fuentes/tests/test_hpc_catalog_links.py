from contextlib import closing
import sqlite3,unittest
from app.hpc_catalog_links import CatalogLinks
class LinkTests(unittest.TestCase):
 def setUp(self):
  self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row
  self.c.executescript('''CREATE TABLE hpc_catalog_practices(seq INTEGER,id TEXT);
  CREATE TABLE hpc_catalog_codes(seq INTEGER,practice_seq INTEGER,practice_id TEXT,provider TEXT,code TEXT,kind TEXT,description TEXT);
  CREATE TABLE hpc_catalog_tariffs(seq INTEGER,provider TEXT,code TEXT,practice_id TEXT,amount_cents,valid_from TEXT,valid_until TEXT,source_id TEXT,page INTEGER);
  CREATE TABLE hpc_catalog_documents(id TEXT,provider TEXT,filename TEXT,sha256 TEXT);
  INSERT INTO hpc_catalog_practices VALUES(1,'p');
  INSERT INTO hpc_catalog_codes VALUES(1,1,'p','HPC','180104','orden','Ficticia'),(2,1,'p','HPC','18010400','convenio','Ficticia');
  INSERT INTO hpc_catalog_tariffs VALUES(1,'HPC','18010400','p',3178661,'2026-06-01',NULL,'doc',5);
  INSERT INTO hpc_catalog_documents VALUES('doc','HPC','ficticio.pdf','abc');''')
 def tearDown(self):self.c.close()
 def result(self,code='180104',day='2026-08-01'):return CatalogLinks(self.c,'source','hash').suggestions(code,day)
 def test_declared_link_is_traced_but_never_applied(self):
  before=self.c.total_changes;r=self.result();x=r['candidates'][0]
  self.assertEqual(x['recorded_amount'],'31786.61');self.assertEqual(x['tariff_code'],'18010400')
  self.assertEqual(x['order_code_seqs'],[1]);self.assertEqual(x['convention_code_seqs'],[2])
  self.assertEqual(x['document_page'],5);self.assertEqual(x['declared_document']['sha256'],'abc')
  self.assertFalse(x['applied']);self.assertFalse(x['equivalence_verified']);self.assertFalse(x['document_bytes_verified'])
  self.assertIsNone(x['declared_currency']);self.assertIsNone(x['declared_unit']);self.assertNotIn('difference_ars',x)
  self.assertEqual(before,self.c.total_changes)
 def test_no_prefix_padding_name_or_neutral_provider_matching(self):
  for code in ['18010','1801040','18.01.04','Ficticia']:self.assertEqual(self.result(code)['candidates'],[])
  self.c.execute("UPDATE hpc_catalog_codes SET provider='NOMENCLADOR' WHERE seq=1")
  self.assertEqual(self.result()['candidates'],[])
 def test_never_use_another_provider_or_nonconvention_target(self):
  self.c.execute("UPDATE hpc_catalog_tariffs SET provider='OTHER'");self.assertEqual(self.result()['candidates'],[])
  self.c.execute("UPDATE hpc_catalog_tariffs SET provider='HPC'")
  self.c.execute("UPDATE hpc_catalog_codes SET kind='orden' WHERE seq=2");self.assertEqual(self.result()['candidates'],[])
 def test_inconsistent_or_ambiguous_identity_blocks_suggestion(self):
  self.c.execute("UPDATE hpc_catalog_codes SET practice_seq=99 WHERE seq=1")
  self.assertEqual(self.result()['status'],'inconsistent_declared_hpc_link')
  self.c.execute("UPDATE hpc_catalog_codes SET practice_seq=1 WHERE seq=1")
  self.c.executescript("INSERT INTO hpc_catalog_practices VALUES(2,'p2'); INSERT INTO hpc_catalog_codes VALUES(3,2,'p2','HPC','180104','orden','Ficticia');")
  self.assertEqual(self.result()['status'],'ambiguous_declared_hpc_link')
 def test_ambiguous_target_code_blocks_suggestion(self):
  self.c.executescript("INSERT INTO hpc_catalog_practices VALUES(2,'p2'); INSERT INTO hpc_catalog_codes VALUES(3,2,'p2','HPC','18010400','convenio','Ficticia');")
  self.assertEqual(self.result()['status'],'ambiguous_declared_hpc_link')
 def test_dates_visible_not_automatic_filter_and_unknown_amount_not_zero(self):
  self.assertEqual(self.result(day='2026-05-01')['candidates'][0]['temporal_relation'],'outside_declared_dates')
  self.assertEqual(self.result(day=None)['candidates'][0]['temporal_relation'],'undetermined_declared_dates')
  for value in ('S/D',None,b'S/D'):
   self.c.execute('UPDATE hpc_catalog_tariffs SET amount_cents=?',(value,));x=self.result()['candidates'][0]
   self.assertIsNone(x['recorded_amount']);self.assertEqual(x['amount_status'],'not_interpretable')
 def test_multiple_tariffs_remain_multiple_not_silently_chosen(self):
  self.c.execute("INSERT INTO hpc_catalog_tariffs VALUES(2,'HPC','18010400','p',99,'2026-06-01',NULL,'doc',6)")
  self.assertEqual(len(self.result()['candidates']),2)
 def test_exact_tariff_does_not_generate_related_identity(self):
  self.assertEqual(self.result('18010400')['candidates'],[])
 def test_same_order_code_also_used_for_other_convention_is_ambiguous(self):
  self.c.executescript("INSERT INTO hpc_catalog_practices VALUES(2,'p2'); INSERT INTO hpc_catalog_codes VALUES(3,2,'p2','HPC','180104','convenio','Ficticia');")
  self.assertEqual(self.result()['status'],'ambiguous_declared_hpc_link')
 def test_related_math_requires_documented_version_and_explicit_batch_unit(self):
  links=CatalogLinks(self.c,'source','hash');related=links.suggestions('180104','2026-08-01')
  class Resolver:
   status='documented_version_candidate'
   def resolve(self,tariff,day):return {'selected':True,'status':self.status,'recorded_amount':'14.00','declared_currency':'ARS','declared_unit':'por práctica','value_version':{'id':'version'}}
  resolver=Resolver()
  def compare(unit='practice'):return links.comparison(related,resolver,'2026-08-01',2,'32.00',unit)
  result=compare();self.assertEqual(result['candidate_total_if_ars_and_same_unit'],'28.00');self.assertEqual(result['difference_ars_if_comparable'],'4.00')
  self.assertFalse(result['applied']);self.assertFalse(result['equivalence_verified'])
  self.assertEqual(compare('unverified')['status'],'related_economic_unit_unverified_or_incompatible')
  self.assertIsNone(compare('unverified')['difference_ars_if_comparable'])
  resolver.status='catalogue_candidate';self.assertIsNone(compare()['difference_ars_if_comparable'])
  resolver.status='version_evidence_unverifiable';self.assertIsNone(compare()['difference_ars_if_comparable'])
  resolver.status='documented_version_candidate'
  links.tariffs['p'][0]['data_json']='{"calculation":{"reviewRequired":true}}'
  self.assertEqual(compare()['status'],'related_special_conditions_require_review')
 def test_related_math_does_not_choose_between_two_active_references(self):
  self.c.execute("INSERT INTO hpc_catalog_tariffs VALUES(2,'HPC','18010400','p',99,'2026-06-01',NULL,'doc',6)")
  links=CatalogLinks(self.c,'source','hash');related=links.suggestions('180104','2026-08-01')
  class Resolver:
   def resolve(self,tariff,day):return {'selected':True,'status':'documented_version_candidate'}
  result=links.comparison(related,Resolver(),'2026-08-01',2,'32.00','practice')
  self.assertEqual(result['status'],'ambiguous_related_reference');self.assertIsNone(result['difference_ars_if_comparable'])

class RegisteredLinkTests(unittest.TestCase):
 def test_registered_catalog_version_and_lookup_remain_readonly(self):
  import json,hashlib
  from unittest.mock import patch
  from tests import test_hpc_values as fixtures
  from tests.test_p03 import fictional_values
  from app.hpc_values import save_value_version
  from app.values_v1 import candidate_values,source_db
  from app.storage import read_verified
  from app.effective_hpc_values import EffectiveHpcValues
  def catalog(folder):
   _,rawmanifest,_=fictional_values(folder);path=folder/'catalogo_ficticio.sqlite'
   with closing(sqlite3.connect(path)) as c, c:
    c.execute('ALTER TABLE hpc_catalog_practices ADD COLUMN seq INTEGER')
    c.execute("INSERT INTO hpc_catalog_practices VALUES('p',1)")
    c.execute('DELETE FROM hpc_catalog_codes')
    c.executemany('INSERT INTO hpc_catalog_codes VALUES(?,?,?,?,?,?,?,?)',[(1,1,'p',1,'P1','180104','orden','Ficticia'),(2,1,'p',2,'P1','123456','convenio','Ficticia')])
    c.execute('DELETE FROM hpc_catalog_tariffs WHERE seq!=1');c.execute("UPDATE hpc_catalog_tariffs SET practice_id='p'")
    for name in ('provider','filename','sha256'):c.execute('ALTER TABLE hpc_catalog_documents ADD COLUMN '+name+' TEXT')
    c.execute("INSERT INTO hpc_catalog_documents VALUES('documento-ficticio','HPC','ficticio.pdf','declarado')")
    m=json.loads(rawmanifest);m['counts']={t:c.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in m['counts']}
   data=path.read_bytes();sha=hashlib.sha256(data).hexdigest();m['files']['valores_convenios_base_2026-10-09.sqlite']={'sha256':sha,'bytes':len(data)}
   return data,json.dumps(m).encode(),sha
  f=fixtures.HpcValueTests()
  with patch('tests.test_hpc_values.fictional_values',side_effect=catalog):f.setUp()
  try:
   version=save_value_version(f.conn,f.root,f.digest,f.dataset['id'],f.source,**f.payload(amount_ars='14.00',effective_from='2026-08-01'))
   f.dataset['version']=version['dataset_version'];before=f.conn.total_changes
   lookup=candidate_values(f.conn,f.root,f.digest,f.dataset['id'],f.source,'180104','2026-08-16','HPC')
   self.assertEqual(lookup['tariff_candidates'],[])
   related=lookup['related_hpc_references'];self.assertEqual(related['candidates'][0]['effective_reference']['value_version']['id'],version['id'])
   sha=f.conn.execute('SELECT source_sha256 FROM source_registry WHERE id=?',(f.source,)).fetchone()[0]
   c=source_db(read_verified(f.root,sha))
   try:links=CatalogLinks(c,f.source,sha)
   finally:c.close()
   resolver=EffectiveHpcValues(f.conn,f.root,f.dataset['id'],f.source)
   result=links.comparison(related,resolver,'2026-08-16',2,'32.00','practice')
   self.assertEqual(result['difference_ars_if_comparable'],'4.00');self.assertEqual(result['candidate_total_if_ars_and_same_unit'],'28.00')
   self.assertIsNone(links.comparison(related,resolver,'2026-08-16',2,'32.00','unverified')['difference_ars_if_comparable'])
   self.assertEqual(f.conn.total_changes,before)
   self.assertEqual(f.conn.execute('SELECT count(*) FROM row_economic_references').fetchone()[0],0)
  finally:f.tearDown()

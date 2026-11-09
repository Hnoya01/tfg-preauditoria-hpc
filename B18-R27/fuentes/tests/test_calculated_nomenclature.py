import copy,json,sqlite3,unittest
from app.calculated_nomenclature import CalculatedNomenclature,COMPONENT,FORMULA

class CalculationTests(unittest.TestCase):
 def setUp(self):
  self.c=sqlite3.connect(':memory:');self.c.execute('CREATE TABLE hpc_catalog_components(component TEXT,part INTEGER,text_data TEXT)')
  self.row={'nomencladorCode':'340301','description':'Práctica ficticia','qGal':6.75,'gto':25,'galenoRadiologico':477.65,'unidadRadiologica':388.4,'amount':1293414,'formula':FORMULA,'sourceRow':5,'norma':'En el caso de facturaci','unidadArancelaria':'D','formaFacturacion':'NO FACTURABLE CON OTROS CODIGOS','status':'pendiente_equivalencia','equivalence':{'kind':'sin_equivalente'}}
  self.data={'provider':'HPC','sourceFile':'ficticio.xlsx','validFrom':'2026-06-01','unitValues':{'galenoRadiologico':477.65,'unidadRadiologica':388.4},'rows':[self.row]}
 def tearDown(self):self.c.close()
 def result(self,code='340301',day='2026-08-01'):
  self.c.execute('DELETE FROM hpc_catalog_components');text=json.dumps(self.data,ensure_ascii=False)
  self.c.executemany('INSERT INTO hpc_catalog_components VALUES(?,?,?)',[(COMPONENT,0,text[:50]),(COMPONENT,1,text[50:])])
  before=self.c.total_changes;r=CalculatedNomenclature(self.c,'source','sha').references(code,day);self.assertEqual(before,self.c.total_changes);return r
 def candidate(self):return self.result()['candidates'][0]
 def test_exact_decimal_technical_rounding_and_no_authoritative_fields(self):
  c=self.candidate();self.assertEqual(c['calculated_amount_exact'],'12934.1375');self.assertEqual(c['calculated_amount_rounded'],'12934.14');self.assertEqual(c['recorded_amount'],'12934.14');self.assertEqual(c['arithmetic_status'],'corroborated_technical_rounding')
  self.assertIsNone(c['declared_currency']);self.assertIsNone(c['declared_unit']);self.assertFalse(c['applied']);self.assertFalse(c['equivalence_verified']);self.assertFalse(c['document_factor_verified'])
  self.assertNotIn('tariff_seq',c);self.assertNotIn('difference_ars_if_comparable',c);self.assertEqual(c['source_sha256'],'sha');self.assertEqual(c['norma'],self.row['norma'])
 def test_no_prefix_padding_name_or_equivalence_matching(self):
  for code in ('34030','0340301','34030100','34.03.01','Práctica ficticia'):
   self.assertEqual(self.result(code)['status'],'no_exact_nomenclature_code')
 def test_mismatch_invalid_missing_not_zero(self):
  self.row['amount']=123;self.assertEqual(self.candidate()['arithmetic_status'],'recorded_amount_mismatch')
  for amount in ('S/D',None,True,-1):
   self.row['amount']=amount;c=self.candidate();self.assertIsNone(c['recorded_amount']);self.assertEqual(c['arithmetic_status'],'recorded_amount_invalid')
  self.row['qGal']='S/D';self.assertIsNone(self.candidate()['calculated_amount_exact'])
 def test_duplicate_codes_never_silently_select(self):
  self.data['rows'].append(copy.deepcopy(self.row));r=self.result();self.assertEqual(r['status'],'duplicate_exact_nomenclature_code');self.assertEqual(len(r['candidates']),2)
 def test_coefficients_conflict_formula_and_provider(self):
  self.row['galenoRadiologico']=10;self.assertEqual(self.candidate()['arithmetic_status'],'coefficient_conflict')
  self.row['formula']='other';self.assertEqual(self.candidate()['arithmetic_status'],'unsupported_formula')
  self.data['provider']='OTHER';self.assertEqual(self.result()['status'],'outside_hpc_provider')
 def test_dates_missing_future_and_invalid_without_inferred_validity(self):
  self.assertEqual(self.result(day='2026-05-01')['candidates'][0]['temporal_relation'],'outside_declared_dates')
  for value in (None,'invalid','2026-99-01'):
   self.data['validFrom']=value;self.assertEqual(self.candidate()['temporal_relation'],'undetermined_declared_dates')
 def test_missing_malformed_parts_and_numbers_never_crash(self):
  self.assertEqual(CalculatedNomenclature(self.c,'s','h').references('x')['status'],'component_unavailable')
  self.c.execute('INSERT INTO hpc_catalog_components VALUES(?,?,?)',(COMPONENT,1,'{}'))
  self.assertEqual(CalculatedNomenclature(self.c,'s','h').status,'component_parts_invalid')
  self.c.execute('UPDATE hpc_catalog_components SET part=0,text_data=?',('{"x":NaN}',));self.assertEqual(CalculatedNomenclature(self.c,'s','h').status,'component_invalid')
  for value in (None,True,-1,1e50,'1.0'):
   self.row['qGal']=value;c=self.candidate();self.assertEqual(c['arithmetic_status'],'not_interpretable');self.assertIsNone(c['calculated_amount_exact'])

class IntegrationPriorityTests(unittest.TestCase):
 def test_lookup_empty_link_only_and_exact_priority(self):
  from tests import test_hpc_values as fixture
  from app.values_v1 import candidate_values
  from unittest.mock import patch
  f=fixture.HpcValueTests();f.setUp()
  try:
   payload={'status':'calculated_reference_pending_verification','candidates':[{'recorded_amount':'12.00'}]}
   with patch('app.calculated_nomenclature.CalculatedNomenclature.references',return_value=payload) as calc:
    exact=candidate_values(f.conn,f.root,f.digest,f.dataset['id'],f.source,'123456','2026-08-01','HPC');self.assertIsNone(exact['calculated_nomenclature_references']);calc.assert_not_called()
    for status in ('ambiguous_declared_hpc_link','inconsistent_declared_hpc_link','catalogue_link_structure_unavailable','declared_hpc_link_pending_verification'):
     with patch('app.hpc_catalog_links.CatalogLinks.suggestions',return_value={'status':status,'candidates':[]}):
      result=candidate_values(f.conn,f.root,f.digest,f.dataset['id'],f.source,'340301','2026-08-01','HPC');self.assertIsNone(result['calculated_nomenclature_references'])
    calc.assert_not_called()
    with patch('app.hpc_catalog_links.CatalogLinks.suggestions',return_value={'status':'no_linked_hpc_tariff','candidates':[]}):
     result=candidate_values(f.conn,f.root,f.digest,f.dataset['id'],f.source,'340301','2026-08-01','HPC');self.assertEqual(result['calculated_nomenclature_references'],payload)
   self.assertEqual(f.conn.execute('SELECT count(*) FROM row_economic_references').fetchone()[0],0)
  finally:f.tearDown()
 def test_board_separate_namespace_no_fallback_for_existing_reference(self):
  from tests import test_board_values as fixture
  from app.board_values import page_comparisons
  from app.db import connect
  from unittest.mock import patch
  f=fixture.BoardValueTests();f.setUp();c=connect(f.f.root)
  row={'source_row':99,'code':'340301','quantity':20,'disposition':'included','practice_date':'2026-08-15','total_ars':'999.00'}
  try:
   with patch('app.calculated_nomenclature.CalculatedNomenclature.references',return_value={'status':'calculated_reference_pending_verification','candidates':[{'recorded_amount':'12.00'}]}) as calc:
    with patch('app.hpc_catalog_links.CatalogLinks.suggestions',return_value={'status':'no_linked_hpc_tariff','candidates':[]}):
     result=page_comparisons(c,f.f.root,f.f.dataset['id'],f.f.batch,[row],'Hoja1')[99]
     self.assertIsNotNone(result['calculated_nomenclature_references']);self.assertIsNone(result['difference_ars_if_comparable']);self.assertIsNone(result['recorded_amount'])
    calc.reset_mock()
    for status in ('withdrawn_reference','version_evidence_unverifiable','ambiguous_hpc_tariff'):
     with patch('app.board_values._compare',return_value={'status':status}):page_comparisons(c,f.f.root,f.f.dataset['id'],f.f.batch,[row],'Hoja1')
    calc.assert_not_called()
  finally:c.close();f.tearDown()

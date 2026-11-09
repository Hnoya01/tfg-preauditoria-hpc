import hashlib,json,unittest,copy
from app.hpc_sync_adapter import adapt_sync_day,SyncFormatError

def seal(d):
 for row,item in zip(d['rows'],d['items']): row['payload_digest']=hashlib.sha256(json.dumps(item['payload'],sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
 return d

def fixture():
 p={'hpc_id':'SYNTH-1','internal_type':'orden.imagen','ready_for_ingest':True,'problems':[],'source':{'orderType':'orden.imagen','id':'SYNTH-1','affiliate':'SYNTH-A'},'displayed':{'id':'SYNTH-1','affiliate':'SYNTH-A','orderDate':'01/08/2026'},'practices':{'items':[{'position':0,'codeText':'010101','descriptionAndAmountText':'IMAGEN FICTICIA $ 100'}]},'movements':[{'statusText':'Autorizada','dateText':'01/08/2026 10:30','reasonText':'FICTICIO'}]}
 return seal({'queried_date':'2026-08-01','extractor_version':'historico-0.4','attempt_id':'synthetic-attempt','captured_at':1794052800,'source_outcome':'recognized','rows':[{'hpc_id':'SYNTH-1','operation_id':'op1','extraction_issue':None}],'items':[{'operation_id':'op1','payload':p}]})

def run(d,**kw): return adapt_sync_day(json.dumps(d).encode(),**kw)

class Tests(unittest.TestCase):
 def test_no_authority_inference(self):
  a,r=run(fixture(),synthetic=True); a=json.loads(a); o=a['orders'][0]
  self.assertEqual(a['data_origin'],'synthetic'); self.assertEqual(a['coverage']['declared'],'partial')
  self.assertEqual(o['resolutions'][0]['scope'],'unknown'); self.assertEqual(o['resolutions'][0]['item_ids'],[])
  self.assertNotIn('authorized_quantity',o['resolutions'][0]); self.assertNotIn('requested_quantity',o['items'][0]); self.assertTrue(r['requires_raw_source'])
 def test_real_default(self): self.assertEqual(json.loads(run(fixture())[0])['data_origin'],'real_unvalidated')
 def test_modified_payload(self):
  d=fixture(); d['items'][0]['payload']['hpc_id']='changed'
  with self.assertRaises(SyncFormatError): run(d)
 def test_missing_payload(self):
  d=fixture(); d['items']=[]
  with self.assertRaises(SyncFormatError): run(d)
 def test_duplicate_operation(self):
  d=fixture(); d['items'].append(copy.deepcopy(d['items'][0]))
  with self.assertRaises(SyncFormatError): run(d)
 def test_affiliate_conflict(self):
  d=fixture(); d['items'][0]['payload']['displayed']['affiliate']='OTHER'
  with self.assertRaises(SyncFormatError): run(seal(d))
 def test_partial_gap(self):
  d=fixture(); d['rows'].append({'operation_id':None,'extraction_issue':'unparsed'}); self.assertEqual(run(d)[1]['unrepresented_rows'],1)
 def test_digital_missing_practices(self):
  d=fixture(); p=d['items'][0]['payload']; p['internal_type']='orden.imagen.digital'; p['source']['orderType']='orden.imagen.digital'; p['practices']['items']=[]
  self.assertEqual(json.loads(run(seal(d))[0])['orders'][0]['items'],[])
 def test_dates_preserved(self): self.assertEqual(json.loads(run(fixture())[0])['orders'][0]['ordered_at'],'01/08/2026')
 def test_unknown_version(self):
  d=fixture(); d['extractor_version']='future'
  with self.assertRaises(SyncFormatError): run(d)
 def test_summary_not_supported(self):
  with self.assertRaises(SyncFormatError): run({'orders':[]})
 def test_duplicate_keys(self):
  with self.assertRaises(SyncFormatError): adapt_sync_day(b'{"x":1,"x":2}')
 def test_empty_unsupported(self):
  d=fixture(); d['items']=[];d['rows']=[]
  with self.assertRaises(SyncFormatError): run(d)

 def test_producer_whitespace_accepted(self):
  d=fixture();p=d['items'][0]['payload'];p['displayed']['id']='  synth-1\t';p['displayed']['affiliate']='\ufeff synth-a  '
  self.assertEqual(json.loads(run(seal(d))[0])['orders'][0]['affiliate_id'],'SYNTH-A')
 def test_source_type_conflict(self):
  d=fixture();d['items'][0]['payload']['source']['orderType']='orden.laboratorio'
  with self.assertRaises(SyncFormatError): run(seal(d))
 def test_invalid_query_dates(self):
  for value in ('2026-02-30','20260801','2026-13-01',None):
   d=fixture();d['queried_date']=value
   with self.subTest(value=value),self.assertRaises(SyncFormatError): run(d)
 def test_missing_query_date(self):
  d=fixture();del d['queried_date']
  with self.assertRaises(SyncFormatError): run(d)

 def test_explicit_blocking_problems_rejected(self):
  from app.hpc_sync_adapter import BLOCKING_CODES
  for code in BLOCKING_CODES:
   d=fixture();d['items'][0]['payload']['problems']=[{'code':code}]
   with self.subTest(code=code),self.assertRaises(SyncFormatError): run(seal(d))
 def test_quality_warning_preserved_in_raw_not_rejected(self):
  d=fixture();d['items'][0]['payload']['problems']=[{'code':'invalid_movement_date'}]
  self.assertEqual(run(seal(d))[1]['orders'],1)
 def test_problems_required(self):
  d=fixture();del d['items'][0]['payload']['problems']
  with self.assertRaises(SyncFormatError): run(seal(d))
 def test_producer_order_byte_limit(self):
  d=fixture();d['items'][0]['payload']['source']['log']='x'*81000
  with self.assertRaisesRegex(SyncFormatError,'order_too_large'): run(seal(d))

 def test_real_js_producer_to_adapter(self):
  import subprocess
  from pathlib import Path
  script=Path(__file__).parent/'fixtures'/'produce_synthetic_sync.cjs'
  generated=subprocess.run(['node',str(script)],check=True,capture_output=True,timeout=10).stdout
  a,r=adapt_sync_day(generated,synthetic=True)
  self.assertEqual(r['orders'],1)
  self.assertEqual(json.loads(a)['orders'][0]['items'][0]['full_code'],'010101')

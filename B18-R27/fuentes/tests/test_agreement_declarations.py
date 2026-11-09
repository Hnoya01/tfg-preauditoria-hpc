import unittest
from app import agreement_declarations as a
from app.effective_hpc_values import EffectiveHpcValues
from app.values_v1 import source_db
from app.storage import read_verified
from app.service import Problem
from tests import test_hpc_values as fixtures

class AgreementTests(unittest.TestCase):
 def setUp(self):
  self.f=fixtures.HpcValueTests();self.f.setUp();self.f.conn.row_factory=__import__('sqlite3').Row
  self.sha=self.f.conn.execute('SELECT source_sha256 FROM source_registry WHERE id=?',(self.f.source,)).fetchone()[0]
  c=source_db(read_verified(self.f.root,self.sha))
  self.tariff=dict(c.execute('SELECT * FROM hpc_catalog_tariffs WHERE seq=1').fetchone());c.close()
 def tearDown(self):self.f.tearDown()
 def body(self,**changes):
  p=dict(expected_dataset_version=self.f.dataset['version'],tariff_seqs=[1],document_id=self.f.document,currency='ARS',unit_label='por práctica',valid_from='2026-01-01',valid_until=None,page_number=1,excerpt='Documento ficticio declara ARS por práctica para las tarifas seleccionadas.',conditions_note='Tarifa base sin adicionales; no acredita cobertura ni autorización.',reason='Declaración documental ficticia para comparación exploratoria.');p.update(changes);return p
 def call(self,fn,**body):return fn(self.f.conn,self.f.root,self.f.digest,self.f.dataset['id'],self.f.source,**body)
 def save(self,**changes):
  body=self.body(**changes);p=self.call(a.preview,**body);r=self.call(a.save,preview_sha256=p['preview_sha256'],**body);self.f.dataset['version']=r['dataset_version'];return r
 def resolve(self,day='2026-08-01'):
  return a.ExploratoryResolver(EffectiveHpcValues(self.f.conn,self.f.root,self.f.dataset['id'],self.f.source),self.sha).resolve(self.tariff,day)
 def test_exact_fixed_price_in_board_requires_document_and_billing_unit(self):
  from app.service import create_batch, confirm_invoice
  from app.review import _batch
  from app.economic_evidence import confirm_provider_scope
  from app.practice_board import practice_search
  from tests.test_p02 import book
  import json, hashlib, sqlite3
  f=self.f
  # New isolated source with a single eligible exact tariff and explicit identity.
  db=sqlite3.connect(':memory:')
  try:
   db.deserialize(read_verified(f.root,self.sha))
   db.execute('DELETE FROM hpc_catalog_tariffs WHERE seq=2')
   db.execute("UPDATE hpc_catalog_tariffs SET practice_id='practice-1',data_json=? WHERE seq=1",
              (json.dumps({'calculation':{'kind':'fixed'}}),))
   db.commit(); blob=db.serialize()
   counts={r[0]:db.execute('SELECT count(*) FROM '+r[0]).fetchone()[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
  finally:db.close()
  manifest_hash=f.conn.execute('SELECT manifest_sha256 FROM source_registry WHERE id=?',(f.source,)).fetchone()[0]
  manifest=json.loads(read_verified(f.root,manifest_hash)); self.sha=hashlib.sha256(blob).hexdigest()
  manifest['counts']=counts;manifest['files']['valores_convenios_base_2026-10-09.sqlite']={'bytes':len(blob),'sha256':self.sha}
  from app.values_v1 import register_values
  from app.economic_evidence import register_evidence_pdf
  def version():return f.conn.execute('SELECT version FROM datasets WHERE id=?',(f.dataset['id'],)).fetchone()[0]
  source,_=register_values(f.conn,f.root,f.digest,f.dataset['id'],version(),blob,json.dumps(manifest).encode(),self.sha);f.source=source['id']
  pdf=b'%PDF-1.4\\n% Ficticio tarifa fija\\n%%EOF'
  doc,_=register_evidence_pdf(f.conn,f.root,f.digest,f.dataset['id'],f.source,version(),'ficticio.pdf','agreement','Convenio ficticio por practica.',hashlib.sha256(pdf).hexdigest(),pdf);f.document=doc['id']
  batch,_=create_batch(f.conn,f.root,f.digest,f.dataset['id'],version(),'ficticia.xlsx',book([('15/08/2026',10,20,30)]));bid=batch['id']
  confirm_invoice(f.conn,f.root,f.digest,f.dataset['id'],bid,'2026-08',version())
  def scope(unit):
   confirm_provider_scope(f.conn,f.root,f.digest,f.dataset['id'],bid,f.source,'HPC',unit,'Alcance ficticio para prueba.',version(),_batch(f.conn,f.dataset['id'],bid)['revision_version'],billing_unit_note='El documento ficticio acredita unidades por práctica.' if unit=='practice' else None)
  def comparison():
   return practice_search(f.conn,f.digest,f.dataset['id'],bid,{'family':'all'},root=f.root)['items'][0]['reference_comparison']
  scope('unverified');f.dataset['version']=version();record=self.save()
  self.assertIsNone(comparison()['difference_ars_if_comparable'])
  scope('practice');self.assertEqual(comparison()['difference_ars_if_comparable'],'-216.90')
  a.withdraw(f.conn,f.digest,f.dataset['id'],f.source,record['id'],version(),'Retiro ficticio de respaldo.')
  self.assertIsNone(comparison()['difference_ars_if_comparable'])
  self.assertEqual(f.conn.execute('SELECT count(*) FROM proposal_versions').fetchone()[0],0)

 def test_source_declaration_no_versions_or_economic_records(self):
  before=self.resolve();self.assertEqual(before['status'],'catalogue_candidate')
  self.save();r=self.resolve();self.assertEqual(r['status'],'documented_agreement_candidate');self.assertEqual(r['declared_currency'],'ARS')
  self.assertEqual(self.f.conn.execute('SELECT count(*) FROM hpc_value_versions').fetchone()[0],0)
  self.assertEqual(self.f.conn.execute('SELECT count(*) FROM row_economic_references').fetchone()[0],0)
  authoritative=EffectiveHpcValues(self.f.conn,self.f.root,self.f.dataset['id'],self.f.source).resolve(self.tariff,'2026-08-01')
  self.assertIsNone(authoritative['declared_currency'])
 def test_explicit_dimensions_and_preview_hash(self):
  for field in ('currency','unit_label'):
   with self.assertRaises(Problem):self.call(a.preview,**self.body(**{field:''}))
  with self.assertRaises(Problem):self.call(a.save,preview_sha256='incorrect',**self.body())
 def test_dates_identity_and_overlap(self):
  self.save(valid_from='2026-08-01',valid_until='2026-08-31')
  self.assertEqual(self.resolve('2026-07-31')['status'],'catalogue_candidate')
  self.assertEqual(self.resolve('2026-08-31')['status'],'documented_agreement_candidate')
  self.tariff['code']='different';self.assertEqual(self.resolve()['status'],'agreement_declaration_identity_mismatch')
  with self.assertRaises(Problem):self.save()
 def test_withdrawal_and_replacement(self):
  first=self.save();second=self.save(replaces_id=first['id'])
  self.assertEqual(self.resolve()['agreement_declaration']['id'],second['id'])
  result=a.withdraw(self.f.conn,self.f.digest,self.f.dataset['id'],self.f.source,second['id'],self.f.dataset['version'],'Retiro explícito de respaldo ficticio')
  self.f.dataset['version']=result['dataset_version'];self.assertEqual(self.resolve()['status'],'agreement_declaration_withdrawn')
 def test_corrupt_document_blocks_and_history_immutable(self):
  from unittest.mock import patch
  self.save()
  with patch('app.agreement_declarations.read_verified',side_effect=RuntimeError('corrupt')):self.assertEqual(self.resolve()['status'],'agreement_declaration_evidence_unverifiable')
  with self.assertRaises(__import__('sqlite3').IntegrityError):self.f.conn.execute("DELETE FROM agreement_declarations")
 def test_replacement_cannot_omit_selected_rows(self):
  first=self.save()
  with self.assertRaises(Problem):self.save(tariff_seqs=[1,2],replaces_id=first['id'])

 def test_linked_difference_uses_source_evidence_without_versions(self):
  from app.hpc_catalog_links import CatalogLinks
  self.save()
  resolver=a.ExploratoryResolver(EffectiveHpcValues(self.f.conn,self.f.root,self.f.dataset['id'],self.f.source),self.sha)
  class Links:
   tariff_by_seq={1:self.tariff}
   source_sha256=self.sha
  related={'status':'declared_hpc_link_pending_verification','candidates':[{'tariff_seq':1,'order_code':'ORDER','tariff_code':self.tariff['code']}]}
  from decimal import Decimal
  expected=Decimal(self.tariff['amount_cents'])/100*2
  result=CatalogLinks.comparison(Links(),related,resolver,'2026-08-01',2,str(expected+4),'practice')
  self.assertEqual(result['difference_ars_if_comparable'],'4.00');self.assertFalse(result['applied'])
  blocked=CatalogLinks.comparison(Links(),related,resolver,'2026-08-01',2,str(expected+4),'unverified')
  self.assertIsNone(blocked['difference_ars_if_comparable'])
 def test_api_preview_save_history_and_csrf(self):
  from fastapi.testclient import TestClient
  from app.api import create_app
  with TestClient(create_app(self.f.root),base_url='https://testserver') as client:
   client.cookies.set('tfg_session',self.f.raw_token)
   path=f'/api/datasets/{self.f.dataset["id"]}/sources/{self.f.source}/agreement-declarations'
   # Use the actual session cookie name used by the application.
   headers={'Origin':'https://testserver','X-CSRF-Token':self.f.csrf}
   denied=client.post(path+'/preview',json=self.body());self.assertEqual(denied.status_code,403)
   preview=client.post(path+'/preview',json=self.body(),headers=headers)
   self.assertEqual(preview.status_code,200,preview.text)
   saved=client.post(path,json={**self.body(),'preview_sha256':preview.json()['preview_sha256']},headers=headers)
   self.assertEqual(saved.status_code,201,saved.text)
   self.assertEqual(len(client.get(path).json()['history']),1)

 def test_idempotent_retry_and_migration30_backup(self):
  from pathlib import Path
  from tests.temp_support import TemporaryDirectory
  from app.db import connect,migrate,MIGRATIONS,backup_before_upgrade
  import sqlite3
  body=self.body();preview=self.call(a.preview,**body)
  first=self.call(a.save,preview_sha256=preview['preview_sha256'],**body)
  retry=self.call(a.save,preview_sha256=preview['preview_sha256'],**body)
  self.assertEqual(first['id'],retry['id']);self.assertFalse(retry['created'])
  with TemporaryDirectory(dir='.tmp') as t:
   root=Path(t);conn=connect(root)
   try:
    migrate(conn,MIGRATIONS[:29]);backup=backup_before_upgrade(conn,root)
    with self.assertRaises(RuntimeError):migrate(conn)
    with self.assertRaises(sqlite3.Error):migrate(conn,MIGRATIONS[:29]+((30,dict(MIGRATIONS)[30]+('INVALID SQL',)),),allow_existing_upgrade=True)
    self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0],29)
    self.assertIsNone(conn.execute("SELECT name FROM sqlite_master WHERE name='agreement_declarations'").fetchone())
    self.assertEqual(migrate(conn,MIGRATIONS[:30],allow_existing_upgrade=True),30)
    old=sqlite3.connect(backup/'app.sqlite3');self.assertEqual(old.execute('PRAGMA user_version').fetchone()[0],29);old.close()
   finally:conn.close()
 def test_closure_capture_preserves_declaration_and_legacy_absence(self):
  from app.service import create_batch,confirm_invoice
  from app.closure import _context
  from tests.test_p02 import book
  f=self.f
  batch,_=create_batch(f.conn,f.root,f.digest,f.dataset['id'],f.dataset['version'],'ficticia.xlsx',book([('15/08/2026',10,20,30)]))
  imported,_=confirm_invoice(f.conn,f.root,f.digest,f.dataset['id'],batch['id'],'2026-08',batch['dataset_version'])
  f.dataset['version']=imported['dataset_version']
  before={};_context(f.conn,f.digest,f.dataset['id'],batch['id'],capture_out=before)
  self.assertNotIn('agreement_declarations',before)
  created=self.save()
  after={};_context(f.conn,f.digest,f.dataset['id'],batch['id'],capture_out=after)
  self.assertEqual(after['agreement_declarations'][0]['id'],created['id'])
  document=next(d for d in after['documents'] if d['id']==f.document)
  self.assertEqual(document['sha256'],after['agreement_declarations'][0]['document_sha256'])
  self.assertEqual(before['snapshot'],after['snapshot'])

 def test_explicit_subset_of_withdrawn_and_omitted_tariff_stays_blocked(self):
  first=self.save(tariff_seqs=[1,2])
  with self.assertRaises(Problem):self.save(tariff_seqs=[1],replaces_id=first['id'])
  withdrawn=a.withdraw(self.f.conn,self.f.digest,self.f.dataset['id'],self.f.source,first['id'],self.f.dataset['version'],'Retiro explícito antes de reducir alcance')
  self.f.dataset['version']=withdrawn['dataset_version']
  with self.assertRaises(Problem):self.save(tariff_seqs=[1])
  second=self.save(tariff_seqs=[1],replaces_id=first['id'])
  self.assertEqual(self.resolve()['agreement_declaration']['id'],second['id'])
  self.assertEqual(self.resolve()['status'],'documented_agreement_candidate')
  c=source_db(read_verified(self.f.root,self.sha))
  try:other=dict(c.execute('SELECT * FROM hpc_catalog_tariffs WHERE seq=2').fetchone())
  finally:c.close()
  resolver=a.ExploratoryResolver(EffectiveHpcValues(self.f.conn,self.f.root,self.f.dataset['id'],self.f.source),self.sha)
  self.assertEqual(resolver.resolve(other,'2026-08-01')['status'],'agreement_declaration_withdrawn')
  third=self.save(tariff_seqs=[1],replaces_id=second['id'])
  self.assertEqual(self.resolve()['agreement_declaration']['id'],third['id'])
  self.assertEqual(self.resolve()['status'],'documented_agreement_candidate')

 def test_replacement_ancestors_with_nonmatching_intermediate_date(self):
  first=self.save(valid_from='2026-07-01')
  second=self.save(valid_from='2026-09-01',replaces_id=first['id'])
  third=self.save(valid_from='2026-08-01',replaces_id=second['id'])
  result=self.resolve('2026-08-15')
  self.assertEqual(result['status'],'documented_agreement_candidate')
  self.assertEqual(result['agreement_declaration']['id'],third['id'])
  self.assertEqual(self.resolve('2026-07-15')['status'],'agreement_declaration_withdrawn')

"""RN14 human review: invented data only; no operational or financial accounts."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile
import copy
import json
import sqlite3
import unittest

from fastapi.testclient import TestClient

from app.api import create_app
from app.db import MIGRATIONS,backup_before_upgrade,connect,migrate
from app.rn14_proposals import preview,save as save_amount
from app.service import Problem
from tests import test_economic_applicability as fixture
from tests.test_p02 import ORIGIN,PASSWORD
from tests.temp_support import TemporaryDirectory


class Rn14ProposalTests(unittest.TestCase):
    setUp=fixture.EconomicApplicabilityTests.setUp
    tearDown=fixture.EconomicApplicabilityTests.tearDown
    for _name in ('headers','import_book','run_url','register_fictional_hpc','url','body','save','set_scope',
                  'base','reference','reference_url','reference_body','confirm','analyze','results'):
        locals()[_name]=getattr(fixture.EconomicApplicabilityTests,_name)
    del _name

    def amount_url(self,row=3):return self.base()+f'/rows/{row}/rn14-proposal'

    def amount_preview(self,row=3):
        r=self.client.get(self.amount_url(row));self.assertEqual(r.status_code,200,r.text);return r.json()

    def alerts(self):
        r=self.client.get(self.base()+'/alerts');self.assertEqual(r.status_code,200,r.text);return r.json()

    def decide_rn14(self,state='confirmada',row=3,foundation='FICTICIO: revisión del importe y sus documentos vigentes.'):
        page=self.alerts();alert=next(a for a in page['items'] if a['rule_code']=='RN14' and a['source_row']==row)
        r=self.client.post(self.base()+'/decisions',headers=self.headers(),json={
            'expected_dataset_version':self.dataset['version'],'expected_revision_version':page['revision_version'],
            'items':[{'id':alert['id'],'expected_version':alert['version']}], 'state':state,'foundation':foundation,
            'evidence_note':'FICTICIO: cotejo documental para la diferencia de esta fila.' if state=='confirmada' else None})
        self.assertEqual(r.status_code,200,r.text);self.dataset['version']=r.json()['dataset_version'];return r.json()

    def demo(self):
        from scripts.create_b02_demo import capture
        prefix=f'/api/datasets/{self.dataset["id"]}/authorization-uploads'
        r=self.client.post(prefix,content=json.dumps(capture()).encode(),headers=self.headers(**{
            'X-Source-Filename':'ficcion.json','X-Expected-Version':str(self.dataset['version']),'Content-Type':'application/octet-stream'}))
        self.assertEqual(r.status_code,201,r.text);upload=r.json()
        p=self.client.get(prefix+'/'+upload['id']+'/preview').json()
        r=self.client.post(prefix+'/'+upload['id']+'/import',headers=self.headers(),json={
            'expected_version':p['dataset_version'],'preview_sha256':p['preview_sha256'],'provenance_note':'Captura enteramente ficticia para prueba de separación monetaria.'})
        self.assertEqual(r.status_code,201,r.text)
        r=self.client.post(self.base()+'/authorization-scope',headers=self.headers(),json={
            'expected_version':r.json()['dataset_version'],'capture_ids':[r.json()['id']], 'mode':'synthetic_demo',
            'synthetic_invoice_confirmed':True,'note':'Excel y JSON ficticios; no son evidencia de importes reales.'})
        self.assertEqual(r.status_code,200,r.text);self.dataset['version']=r.json()['dataset_version']

    def ready(self,simulation=False,row=3):
        if simulation:self.demo()
        self.confirm(row);self.analyze();self.decide_rn14(row=row)
        return self.amount_preview(row)

    def amount_body(self,p=None,row=3,**changes):
        p=p or self.amount_preview(row)
        return {'expected_dataset_version':p['dataset_version'],'expected_revision_version':p['revision_version'],
                'preview_sha256':p['preview_sha256'],'action':'confirm',**changes}

    def record_amount(self,p=None,row=3,**changes):
        r=self.client.post(self.amount_url(row),headers=self.headers(),json=self.amount_body(p,row,**changes))
        self.assertEqual(r.status_code,201,r.text);self.dataset['version']=r.json()['dataset_version'];return r.json()

    def export(self):
        r=self.client.get(self.base()+'/export-provisional');self.assertEqual(r.status_code,200,r.text[:100])
        with ZipFile(BytesIO(r.content)) as z:
            return json.loads(z.read('manifest.json')),[json.loads(l) for l in z.read('rows.jsonl').splitlines()],{n:z.read(n) for n in z.namelist()}

    def test_preview_requires_confirmed_finding_and_preserves_explicit_amount_review(self):
        self.confirm();self.analyze()
        p=self.amount_preview();self.assertEqual(p['automatic_amount_ars'],'2.00');self.assertFalse(p['can_save'])
        self.assertEqual(self.client.post(self.amount_url(),headers=self.headers(),json=self.amount_body(p)).status_code,409)
        self.decide_rn14();p=self.amount_preview();self.assertTrue(p['can_save']);self.assertFalse(p['simulation_only'])
        self.assertIn('FICTICIO',p['decision_record']['foundation']);self.assertIn('cotejo',p['decision_record']['evidence_note'])
        saved=self.record_amount(p);self.assertEqual(saved['amount_ars'],'2.00');self.assertIsNone(saved['simulated_amount_ars'])
        history=self.client.get(self.base()+'/rows/3/proposals').json()
        self.assertEqual(history['current_proposal']['amount_ars'],'2.00')
        self.assertEqual(history['versions'][0]['payload_at_save']['components'][0]['automatic_amount_ars'],'2.00')
        conn=connect(self.root)
        try:
            real=dict(conn.execute('SELECT * FROM proposal_versions').fetchone());payload=json.loads(real['payload_json'])
            payload['simulation_only']=True;real.update(id='false-simulation',payload_json=json.dumps(payload))
            with self.assertRaises(sqlite3.IntegrityError):conn.execute('INSERT INTO rn14_simulation_versions VALUES('+','.join('?'*14)+')',tuple(real.values()))
            self.assertEqual(conn.execute('SELECT count(*) FROM rn14_simulation_versions').fetchone()[0],0)
        finally:conn.close()
        m,rows,_=self.export();self.assertEqual(m['current_proposal_total_ars'],'2.00')
        self.assertIsNone(next(r for r in rows if r['source_row']==3)['rn14_simulation'])

    def test_adjustment_preserves_automatic_value_and_known_zero_is_not_unknown(self):
        self.ready();self.record_amount()
        self.record_amount(action='adjust',adjusted_ars='1.50',adjustment_calculation='2.00 - 0.50 = 1.50',
                           adjustment_reason='FICTICIO: ajuste respaldado y revisado expresamente.')
        p=self.amount_preview();self.assertEqual(len(p['proposal_history']),2)
        part=p['proposal_history'][-1]['payload_at_save']['components'][0]
        self.assertEqual((part['automatic_amount_ars'],part['amount_ars']),('2.00','1.50'))
        self.record_amount(action='adjust',adjusted_ars='0.00',adjustment_calculation='2.00 - 2.00 = 0.00',
                           adjustment_reason='FICTICIO: importe determinado cero con respaldo explícito.')
        self.assertEqual(self.amount_preview()['latest_evaluation']['amount_ars'],'0.00')
        self.decide_rn14('no_concluyente')
        p=self.amount_preview();self.assertIsNone(p['latest_evaluation']['amount_ars'])
        self.assertEqual(p['latest_evaluation']['state'],'not_current_by_decision')

    def test_demo_storage_api_and_export_never_add_to_real_totals(self):
        p=self.ready(simulation=True);self.assertTrue(p['simulation_only'])
        saved=self.record_amount();self.assertTrue(saved['simulation_only']);self.assertIsNone(saved['amount_ars'])
        self.assertEqual(saved['simulated_amount_ars'],'2.00')
        conn=connect(self.root)
        try:
            self.assertEqual(conn.execute('SELECT count(*) FROM proposal_versions').fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT count(*) FROM rn14_simulation_versions').fetchone()[0],1)
        finally:conn.close()
        p=self.amount_preview();self.assertEqual(p['latest_evaluation']['simulated_amount_ars'],'2.00')
        self.assertEqual(p['proposal_history'],[])
        self.assertIsNone(self.client.get(self.base()+'/rows/3/proposals').json()['current_proposal'])
        m,rows,files=self.export();self.assertIsNone(m['current_proposal_total_ars'])
        self.assertEqual(m['rn14_simulations']['current_simulated_total_ars'],'2.00')
        self.assertEqual(files['proposal_versions.jsonl'],b'')
        self.assertTrue(json.loads(files['rn14_simulation_versions.jsonl'].splitlines()[0])['simulation_only'])
        binding=json.loads(files['rn14_proposal_references.jsonl'].splitlines()[0]);self.assertEqual(binding['simulation_id'],saved['id']);self.assertIsNone(binding['proposal_id'])
        row=next(r for r in rows if r['source_row']==3);self.assertIsNone(row['proposed_amount_ars'])
        self.assertEqual(row['rn14_simulation']['simulated_amount_ars'],'2.00')

    def test_client_cannot_choose_origin_or_price_and_database_rejects_cross_storage(self):
        self.ready(simulation=True);saved=self.record_amount()
        for extra in ({'simulation_only':False},{'amount_ars':'999.00'},{'rate_ars':'1.00'},{'rubric':'honorarios'}):
            self.assertEqual(self.client.post(self.amount_url(),headers=self.headers(),json=self.amount_body(**extra)).status_code,422)
        conn=connect(self.root)
        try:
            r=dict(conn.execute('SELECT * FROM rn14_simulation_versions WHERE id=?',(saved['id'],)).fetchone())
            with self.assertRaises(sqlite3.IntegrityError):conn.execute('INSERT INTO proposal_versions VALUES('+','.join('?'*14)+')',tuple(r.values()))
            with self.assertRaises(sqlite3.IntegrityError):conn.execute("UPDATE rn14_simulation_versions SET amount_ars='999.00'")
            with self.assertRaises(sqlite3.IntegrityError):conn.execute('DELETE FROM rn14_simulation_versions')
            self.assertEqual(conn.execute('SELECT simulation_id FROM rn14_proposal_references').fetchone()[0],saved['id'])
            with self.assertRaises(sqlite3.IntegrityError):conn.execute('DELETE FROM rn14_proposal_references')
            from app.proposals import save_verified_proposal
            with self.assertRaises(Problem) as denied:
                save_verified_proposal(conn,self.root,self.digest,self.dataset['id'],self.batch,3,self.amount_preview()['dataset_version'],self.amount_preview()['revision_version'],({},))
            self.assertEqual(denied.exception.status,409)
        finally:conn.close()

    def test_discard_and_foundation_change_exclude_only_dependent_row(self):
        self.ready();self.record_amount()
        p=self.reference(2)
        changed=self.client.post(self.base()+'/rows/2/work-fields',headers=self.headers(),json={
            'expected_dataset_version':p['dataset_version'],'expected_revision_version':p['revision_version'],
            'field':'G','value':'1','reason':'FICTICIO: una práctica en la fila independiente.'})
        self.assertEqual(changed.status_code,200,changed.text);self.dataset['version']=changed.json()['dataset_version']
        self.confirm(2,covered_quantity='1');self.analyze();self.decide_rn14(row=2);self.record_amount(row=2)
        self.decide_rn14('descartada')
        p=self.amount_preview();self.assertIsNone(p['latest_evaluation']['amount_ars']);self.assertEqual(p['latest_evaluation']['state'],'not_current_by_decision')
        m,rows,_=self.export();self.assertEqual(m['current_proposal_total_ars'],'15.00')
        self.assertEqual(self.amount_preview(2)['latest_evaluation']['amount_ars'],'15.00')
        self.assertEqual(next(r for r in rows if r['source_row']==3)['proposal_state'],'not_current_by_decision')
        self.decide_rn14();self.record_amount()
        self.decide_rn14(foundation='FICTICIO: nuevo fundamento exige nueva revisión del mismo cálculo.')
        self.assertEqual(self.amount_preview()['latest_evaluation']['state'],'requires_update')
        self.record_amount();self.assertEqual(self.amount_preview()['latest_evaluation']['amount_ars'],'2.00')
        self.assertEqual(len(self.amount_preview()['proposal_history']),3)

    def test_complete_code_and_dated_value_version_use_the_captured_row_reference(self):
        p=self.reference()
        r=self.client.post(self.base()+'/rows/3/work-fields',headers=self.headers(),json={
            'expected_dataset_version':p['dataset_version'],'expected_revision_version':p['revision_version'],
            'field':'E','value':'123456789','reason':'FICTICIO: código completo con equivalencia económica.'})
        self.assertEqual(r.status_code,200,r.text);self.dataset['version']=r.json()['dataset_version']
        from app.hpc_values import save_value_version
        conn=connect(self.root)
        try:
            value=save_value_version(conn,self.root,self.digest,self.dataset['id'],self.source_id,
                expected_dataset_version=self.dataset['version'],tariff_seq=1,code='123456',amount_ars='14.00',
                unit_label='por práctica',effective_from='2026-08-16',document_id=self.agreement_id,page_number=1,
                excerpt='FICTICIO: precio documentado exacto ARS14 por práctica.',reason='FICTICIO: cambio de valor con versión y respaldo.')
        finally:conn.close()
        self.dataset['version']=value['dataset_version'];self.ready();self.record_amount()
        p=self.amount_preview();payload=p['proposal_history'][-1]['payload_at_save'];part=payload['components'][0]
        self.assertEqual(part['amount_ars'],'4.00');self.assertEqual(part['reference']['code_complete'],'123456789')
        self.assertEqual(payload['reference_dependency']['basis']['candidate']['tariff']['code'],'123456')
        self.assertEqual(payload['reference_dependency']['basis']['candidate']['value_version']['id'],value['id'])
        self.assertIn(value['id'],part['reference']['locator'])
        self.assertEqual(p['latest_evaluation']['amount_ars'],'4.00')

    def test_negative_difference_is_observation_without_a_zero_or_positive_proposal(self):
        p=self.reference()
        r=self.client.post(self.base()+'/rows/3/work-fields',headers=self.headers(),json={
            'expected_dataset_version':p['dataset_version'],'expected_revision_version':p['revision_version'],
            'field':'G','value':'3','reason':'FICTICIO: cantidad para comprobar diferencia negativa.'})
        self.assertEqual(r.status_code,200,r.text);self.dataset['version']=r.json()['dataset_version']
        self.confirm(covered_quantity='3');results=self.analyze();self.assertEqual(results['RN14']['difference_ars'],'-13.00')
        self.decide_rn14();p=self.amount_preview();self.assertFalse(p['can_save']);self.assertIsNone(p['automatic_amount_ars'])
        self.assertEqual(self.client.post(self.amount_url(),headers=self.headers(),json=self.amount_body(p)).status_code,409)
        self.assertEqual(p['proposal_history'],[])

    def test_simulated_adjustment_keeps_real_storage_and_totals_empty(self):
        self.ready(simulation=True);self.record_amount()
        self.record_amount(action='adjust',adjusted_ars='1.50',adjustment_calculation='2.00 - 0.50 = 1.50',
                           adjustment_reason='FICTICIO: ajuste revisado sólo dentro de simulación DEMO.')
        p=self.amount_preview();self.assertEqual(p['latest_evaluation']['simulated_amount_ars'],'1.50')
        self.assertEqual(p['simulation_history'][-1]['payload_at_save']['components'][0]['automatic_amount_ars'],'2.00')
        self.assertEqual(len(p['simulation_history']),2);self.assertEqual(p['proposal_history'],[])
        m,rows,_=self.export();self.assertIsNone(m['current_proposal_total_ars'])
        self.assertEqual(m['rn14_simulations']['current_simulated_total_ars'],'1.50')
        self.assertIsNone(next(r for r in rows if r['source_row']==3)['proposed_amount_ars'])

    def test_declaring_a_batch_fictitious_never_relabels_its_saved_real_proposal(self):
        self.ready();self.record_amount();self.ready(simulation=True);self.record_amount()
        history=self.client.get(self.base()+'/rows/3/proposals').json()
        self.assertIsNone(history['current_proposal']);self.assertEqual(len(history['versions']),1)
        self.assertFalse(history['versions'][0]['payload_at_save']['simulation_only'])
        self.assertEqual(self.amount_preview()['latest_evaluation']['simulated_amount_ars'],'2.00')
        m,_,files=self.export();self.assertIsNone(m['current_proposal_total_ars'])
        self.assertEqual(len(files['proposal_versions.jsonl'].splitlines()),1)
        self.assertEqual(len(files['rn14_simulation_versions.jsonl'].splitlines()),1)

    def test_adjustment_validation_and_obsolete_preview_leave_history_unchanged(self):
        p=self.ready()
        for extra in ({'action':'adjust','adjusted_ars':'1.50'},{'action':'adjust','adjusted_ars':'-1.00'},
                      {'action':'adjust','adjusted_ars':'1.501','adjustment_calculation':'x + y','adjustment_reason':'FICTICIO: cálculo con fracción de centavo.'},
                      {'action':'confirm','adjusted_ars':'1.50'}):
            self.assertEqual(self.client.post(self.amount_url(),headers=self.headers(),json=self.amount_body(p,**extra)).status_code,422)
        self.record_amount(p)
        self.assertEqual(self.client.post(self.amount_url(),headers=self.headers(),json=self.amount_body(p)).status_code,409)
        p=self.amount_preview()
        self.assertEqual(self.client.post(self.amount_url(),headers=self.headers(),json=self.amount_body(p,preview_sha256='0'*64)).status_code,409)
        self.assertEqual(len(self.amount_preview()['proposal_history']),1)

    def test_viewer_csrf_and_concurrent_reviewers_are_checked_at_commit(self):
        p=self.ready();body=self.amount_body(p)
        self.assertEqual(self.client.post(self.amount_url(),json=body,headers={'Origin':ORIGIN}).status_code,403)
        with TestClient(create_app(self.root,public_origin=ORIGIN),base_url=ORIGIN) as viewer:
            login=viewer.post('/api/session',json={'username':'viewer','password':PASSWORD},headers={'Origin':ORIGIN})
            self.assertEqual(viewer.get(self.amount_url()).status_code,403)
            self.assertEqual(viewer.post(self.amount_url(),json=body,headers={'Origin':ORIGIN,'X-CSRF-Token':login.json()['csrf_token']}).status_code,403)
        from app.security import create_user,token_digest
        from app.service import grant_access
        conn=connect(self.root)
        try:
            create_user(conn,'second-reviewer',PASSWORD,'reviewer')
            granted=grant_access(conn,self.digest,self.dataset['id'],self.dataset['version'],'second-reviewer','reviewer')
        finally:conn.close()
        self.dataset['version']=granted['version']
        with TestClient(create_app(self.root,public_origin=ORIGIN),base_url=ORIGIN) as reviewer:
            login=reviewer.post('/api/session',json={'username':'second-reviewer','password':PASSWORD},headers={'Origin':ORIGIN})
            self.assertEqual(login.status_code,200);other_digest=token_digest(reviewer.cookies.get('tfg_session'))
            self.assertTrue(reviewer.get(self.amount_url()).json()['can_save'])
        body=self.amount_body()
        barrier=Barrier(2)
        def write(digest):
            conn=connect(self.root)
            try:
                barrier.wait(timeout=10)
                try:save_amount(conn,self.root,digest,self.dataset['id'],self.batch,3,**body);return 201
                except Problem as exc:return exc.status
            finally:conn.close()
        with ThreadPoolExecutor(max_workers=2) as workers:
            futures=[workers.submit(write,self.digest),workers.submit(write,other_digest)];results=[f.result(timeout=15) for f in futures]
        self.assertEqual(sorted(results),[201,409]);self.assertEqual(len(self.amount_preview()['proposal_history']),1)

    def test_reference_change_requires_explicit_analysis_and_human_review(self):
        self.ready();self.record_amount();self.confirm(state='withdrawn')
        p=self.amount_preview();self.assertFalse(p['can_save']);self.assertIsNone(p['latest_evaluation']['amount_ars'])
        self.confirm();self.analyze();p=self.amount_preview();self.assertEqual(p['decision'],'pendiente')
        self.assertFalse(p['can_save']);self.decide_rn14();self.record_amount()
        self.assertEqual(len(self.amount_preview()['proposal_history']),2)

    def test_old_component_versions_are_not_silently_replaced(self):
        self.ready();saved=self.record_amount()
        conn=connect(self.root)
        try:
            r=dict(conn.execute('SELECT * FROM proposal_versions WHERE id=?',(saved['id'],)).fetchone())
            payload=json.loads(r['payload_json']);payload['format_version']=2;payload['components']*=2
            r.update(id='legacy-fixture',ordinal=2,previous_id=saved['id'],payload_json=json.dumps(payload))
            conn.execute('INSERT INTO proposal_versions VALUES('+','.join('?'*14)+')',tuple(r.values()))
        finally:conn.close()
        p=self.amount_preview();self.assertEqual(p['state'],'other_components_require_review');self.assertFalse(p['can_save'])
        self.assertEqual(self.client.post(self.amount_url(),headers=self.headers(),json=self.amount_body(p)).status_code,409)
        self.assertEqual(len(self.amount_preview()['proposal_history']),2)

    def test_changed_or_revoked_read_is_rejected_with_deterministic_barrier(self):
        p=self.ready();conn=connect(self.root)
        def revoke():
            other=connect(self.root)
            try:other.execute("UPDATE users SET active=0 WHERE username='owner'")
            finally:other.close()
        try:
            with self.assertRaises(Problem) as denied:preview(conn,self.root,self.digest,self.dataset['id'],self.batch,3,after_read=revoke)
            self.assertEqual(denied.exception.status,401)
            self.assertEqual(self.client.post(self.amount_url(),headers=self.headers(),json=self.amount_body(p)).status_code,401)
            self.assertEqual(conn.execute('SELECT count(*) FROM proposal_versions').fetchone()[0],0)
        finally:conn.close()

    def test_future_price_is_independent_but_changed_reference_foundation_requires_review(self):
        self.ready();self.record_amount()
        from app.hpc_values import save_value_version
        conn=connect(self.root)
        try:
            value=save_value_version(conn,self.root,self.digest,self.dataset['id'],self.source_id,
                expected_dataset_version=self.dataset['version'],tariff_seq=1,code='123456',amount_ars='18.00',
                unit_label='por práctica',effective_from='2026-11-01',document_id=self.agreement_id,page_number=1,
                excerpt='FICTICIO: importe futuro de noviembre sin aplicación a agosto.',reason='FICTICIO: versión futura independiente.')
        finally:conn.close()
        self.dataset['version']=value['dataset_version'];self.assertEqual(self.amount_preview()['latest_evaluation']['amount_ars'],'2.00')
        self.confirm(note='FICTICIO: nuevo fundamento de aplicación que exige revisar el cálculo.')
        self.assertIsNone(self.amount_preview()['latest_evaluation']['amount_ars'])
        self.analyze();self.assertFalse(self.amount_preview()['can_save']);self.decide_rn14();self.record_amount()
        self.assertEqual(self.amount_preview()['latest_evaluation']['amount_ars'],'2.00')

    def test_closed_simulation_is_frozen_and_successor_starts_without_it(self):
        from tests.test_closure import ClosureTests
        self.ready(simulation=True);self.record_amount()
        page=self.alerts();others=[{'id':a['id'],'expected_version':a['version']} for a in page['items'] if a['rule_code']!='RN14' or a['source_row']!=3]
        if others:
            r=self.client.post(self.base()+'/decisions',headers=self.headers(),json={'expected_dataset_version':self.dataset['version'],
                'expected_revision_version':page['revision_version'],'items':others,'state':'no_concluyente','foundation':'FICTICIO: casos fuera del ensayo económico conservados sin conclusión.'})
            self.assertEqual(r.status_code,200,r.text)
        self.preview=lambda:ClosureTests.preview(self)
        p=ClosureTests.justify(self);self.assertEqual(p['rn14_simulations']['current_simulated_total_ars'],'2.00');self.assertIsNone(p['current_proposal_total_ars'])
        closed=ClosureTests.close(self,p);self.assertEqual(closed.status_code,201,closed.text);closed=closed.json()
        frozen=self.client.get(self.base()+'/export-closed').content
        with ZipFile(BytesIO(frozen)) as z:
            m=json.loads(z.read('manifest.json'));self.assertEqual(m['rn14_simulations']['current_simulated_total_ars'],'2.00')
            self.assertIsNone(m['current_proposal_total_ars']);self.assertEqual(m['closure']['proposal_version_ids'],[])
            self.assertEqual(len(m['closure']['simulation_version_ids']),1)
        self.assertEqual(self.amount_preview()['state'],'closed_revision')
        r=self.client.post(self.base()+'/revisions',headers=self.headers(),json={'previous_revision_id':closed['revision_id'],
            'expected_dataset_version':closed['dataset_version'],'expected_revision_version':closed['revision_version'],
            'reason':'FICTICIO: nueva revisión conserva importes simulados sólo como historia.'})
        self.assertEqual(r.status_code,201,r.text);self.assertEqual(self.amount_preview()['simulation_history'],[])
        self.assertEqual(self.client.get(self.base()+'/export-closed').content,frozen)
        from scripts.release_snapshot import build_release
        from scripts.recovery_data import make_backup,bundle_backup,restore_archive,fingerprint
        from app.storage import read_verified
        release=self.root/'review-source.zip';build_release(Path.cwd(),release,synthetic=True)
        backup=self.root/'backups'/'review';manifest,digest=make_backup(self.root,backup,release,data_kind='synthetic')
        self.assertEqual(manifest['logical_state']['tables']['proposal_versions']['count'],0)
        self.assertEqual(manifest['logical_state']['tables']['rn14_simulation_versions']['count'],1)
        self.assertEqual(manifest['logical_state']['tables']['rn14_proposal_references']['count'],1)
        bundle=self.root/'review-backup.zip';bundle_backup(backup,bundle)
        restored=self.root/'review-restored';restore_archive(bundle,restored,digest,self.root)
        self.assertEqual(fingerprint(restored),manifest['logical_state'])
        self.assertEqual(read_verified(restored,closed['archive_sha256']),frozen)


class Rn14MigrationTests(unittest.TestCase):
    def test_additive_23_to_24_with_backup_and_atomic_rollback(self):
        with TemporaryDirectory(dir='.tmp') as directory:
            root=Path(directory);conn=connect(root)
            try:
                old=tuple(m for m in MIGRATIONS if m[0]<=23);migrate(conn,migrations=old)
                from app.security import create_user
                actor=create_user(conn,'fictional-migration',PASSWORD,'admin');backup=backup_before_upgrade(conn,root)
                with self.assertRaises(sqlite3.Error):migrate(conn,migrations=old+((24,dict(MIGRATIONS)[24]+('INVALID SQL',)),),allow_existing_upgrade=True)
                self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0],23)
                self.assertIsNone(conn.execute("SELECT name FROM sqlite_master WHERE name='rn14_simulation_versions'").fetchone())
                self.assertEqual(migrate(conn,migrations=MIGRATIONS[:24],allow_existing_upgrade=True),24)
                self.assertEqual(conn.execute('SELECT id FROM users').fetchone()[0],actor)
                self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone()[0],'ok');self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(),[])
                saved=sqlite3.connect(backup/'app.sqlite3')
                try:self.assertEqual(saved.execute('PRAGMA user_version').fetchone()[0],23)
                finally:saved.close()
            finally:conn.close()

"""One B12 operator journey, fictional inputs only, no server/listening socket."""
import hashlib
import json
import sqlite3
import unittest
from io import BytesIO
from zipfile import ZipFile
from uuid import uuid4
from app.db import connect
from app.values_v1 import register_values
from tests import test_p05 as p05
from tests.test_practice_families import fictional_family_values
from tests import test_closure as closure
from tests import test_revisions as revisions

class IntegralHpcOperatorTests(unittest.TestCase):
    setUp = p05.P05Tests.setUp
    tearDown = p05.P05Tests.tearDown
    headers = p05.P05Tests.headers
    import_book = p05.P05Tests.import_book
    run_url = p05.P05Tests.run_url
    alerts = p05.P05Tests.alerts
    decide = p05.P05Tests.decide
    base = closure.ClosureTests.base
    preview = closure.ClosureTests.preview
    justify = closure.ClosureTests.justify
    close = closure.ClosureTests.close
    history = revisions.NewRevisionTests.history
    start = revisions.NewRevisionTests.start

    def search(self, **params):
        r=self.client.post(self.base()+'/practice-search',headers=self.headers(),json=params)
        self.assertEqual(r.status_code,200,r.text)
        return r.json()

    def observation(self, action, duty='administrative', decision=None):
        url=self.base()+'/rows/2/observations'
        p=self.client.get(url).json()
        body=dict(expected_dataset_version=p['dataset_version'],expected_revision_version=p['revision_version'],
            revision_id=p['revision_id'],run_id=p['run_id'],request_id=str(uuid4()),rule_code='RN17',
            action=action,duty=duty,foundation='FICTICIO: cotejo de posible repetición entre facturas.',
            evidence_note='FICTICIO: se comprobaron las constancias para este ensayo.',decision=decision)
        r=self.client.post(url,headers=self.headers(),json=body)
        self.assertEqual(r.status_code,201,r.text)
        self.dataset['version']=r.json()['dataset_version']
        return body,r.json()

    def test_import_filter_compare_review_and_successor_preserve_originals(self):
        # P05 imports two invented invoices and performs an initial analysis.
        content,manifest,sha=fictional_family_values(self.root)
        path=self.root/'catalogo_ficticio.sqlite'
        cat=sqlite3.connect(path)
        cat.execute("UPDATE hpc_catalog_providers SET id='HPC' WHERE id='P1'")
        cat.execute("UPDATE hpc_catalog_tariffs SET provider='HPC',amount_cents=1500,valid_from='2026-06-01' WHERE seq=1")
        cat.execute('DELETE FROM hpc_catalog_tariffs WHERE seq<>1')
        cat.execute('UPDATE hpc_catalog_tariffs SET data_json=? WHERE seq=1',(json.dumps({'conditions':'Ficticio por práctica','calculation':{'kind':'nbu','ubMilliunits':1000,'rateCents':1500,'reviewRequired':False}}),))
        cat.commit(); counts={r[0]:cat.execute('SELECT count(*) FROM "'+r[0]+'"').fetchone()[0] for r in cat.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()};cat.close()
        content=path.read_bytes(); sha=hashlib.sha256(content).hexdigest();m=json.loads(manifest)
        m['counts']=counts;m['files']['valores_convenios_base_2026-10-09.sqlite']={'sha256':sha,'bytes':len(content)}
        c=connect(self.root)
        source,_=register_values(c,self.root,self.digest,self.dataset['id'],self.dataset['version'],content,json.dumps(m).encode(),sha)
        self.dataset['version']=source['dataset_version']; originals=[tuple(x) for x in c.execute('SELECT * FROM invoice_rows ORDER BY import_id,source_row')];c.close()
        p=self.alerts()
        r=self.client.post(self.base()+'/provider-scope',headers=self.headers(),json=dict(
            expected_dataset_version=self.dataset['version'],expected_revision_version=p['revision_version'],
            source_id=source['id'],provider='HPC',billing_unit='unverified',confirmation_note='HPC confirmado para ensayo ficticio integral.'))
        self.assertEqual(r.status_code,200,r.text);self.dataset['version']=r.json()['dataset_version']
        page=self.search(family='images')
        self.assertEqual(page['filtered_total'],2)
        self.assertEqual(page['family_counts'],{'images':2,'other':0,'unclassified':0})
        difference=self.search(family='images',reference_comparison_state='differences',limit=1)
        self.assertEqual(difference['filtered_total'],1)
        row=difference['items'][0];self.assertEqual(row['source_row'],3)
        self.assertEqual(row['reference_comparison']['difference_ars_if_comparable'],'2.00')
        self.assertIsNone(row['reference_comparison']['declared_currency'])
        r=self.client.post(self.run_url(),headers=self.headers(),json={'expected_version':self.dataset['version']})
        self.assertEqual(r.status_code,201,r.text);self.dataset['version']+=1
        page=self.search(family='images',rule='RN17',state='con_indicios')
        self.assertEqual(page['filtered_total'],2)
        combined=self.search(family='images',rules=['RN17','RN13'],rules_match='any',state='con_indicios',
            reference_comparison_state='differences',report_document_state='no_aportado',
            authorization_document_state='no_aportado',sort='affiliate_id')
        self.assertEqual([r['source_row'] for r in combined['items']],[3])
        self.assertEqual(self.search(family='images',report_document_state='revisado_manualmente')['filtered_total'],0)
        body,first=self.observation('refer')
        self.observation('request_info','auditor')
        self.observation('provide_info')
        self.observation('resolve','auditor','descartada')
        replay=self.client.post(self.base()+'/rows/2/observations',headers=self.headers(),json=body)
        self.assertEqual(replay.status_code,201,replay.text);self.assertTrue(replay.json()['replayed'])
        selected=[{'id':a['id'],'expected_version':a['version']} for a in self.alerts()['items'] if a['decision']=='pendiente']
        r=self.decide(selected,state='no_concluyente',foundation='FICTICIO: conservar incertidumbre sin débito.')
        self.assertEqual(r.status_code,200,r.text);self.dataset['version']=r.json()['dataset_version']
        provisional=self.client.get(self.base()+'/export-provisional')
        self.assertEqual(provisional.status_code,200,provisional.text[:100])
        with ZipFile(BytesIO(provisional.content)) as z:
            self.assertEqual(len(z.read('observation_events.jsonl').splitlines()),4)
            self.assertIsNone(json.loads(z.read('manifest.json'))['current_proposal_total_ars'])
        p=self.justify();self.assertTrue(p['can_close'])
        closed=self.close(p);self.assertEqual(closed.status_code,201,closed.text)
        frozen=self.client.get(self.base()+'/export-closed');self.assertEqual(frozen.status_code,200)
        old=self.history();new=self.start(old);self.assertEqual(new.status_code,201,new.text)
        self.assertFalse(new.json()['analysis_started'])
        self.assertEqual(self.alerts()['items'],[])
        # Opening is not reanalysis: operator must request it explicitly.
        self.dataset['version']=new.json()['dataset_version']
        rerun=self.client.post(self.run_url(),headers=self.headers(),json={'expected_version':self.dataset['version']})
        self.assertEqual(rerun.status_code,201,rerun.text)
        self.assertEqual(rerun.json()['revision_id'],new.json()['revision_id'])
        self.assertTrue(all(a['decision']=='pendiente' for a in self.alerts()['items']))
        # Documented revision policy: scopes are not silently inherited.
        page=self.search(family='images')
        self.assertTrue(all(r['reference_comparison']['status']=='hpc_provider_scope_missing' for r in page['items']))
        p=self.alerts()
        r=self.client.post(self.base()+'/provider-scope',headers=self.headers(),json=dict(
            expected_dataset_version=page['dataset_version'],expected_revision_version=p['revision_version'],
            source_id=source['id'],provider='HPC',billing_unit='unverified',confirmation_note='HPC reconfirmado en nueva revisión ficticia.'))
        self.assertEqual(r.status_code,200,r.text)
        page=self.search(family='images',reference_comparison_state='differences')
        self.assertEqual(page['filtered_total'],1)
        self.assertEqual(page['items'][0]['reference_comparison']['difference_ars_if_comparable'],'2.00')

        self.assertEqual(self.client.get(self.base()+'/export-closed?revision_id='+old['revision_id']).content,frozen.content)
        c=connect(self.root)
        self.assertEqual([tuple(x) for x in c.execute('SELECT * FROM invoice_rows ORDER BY import_id,source_row')],originals)
        self.assertEqual(c.execute('SELECT count(*) FROM proposal_versions').fetchone()[0],0)
        self.assertIsNone(c.execute('PRAGMA foreign_key_check').fetchone());c.close()

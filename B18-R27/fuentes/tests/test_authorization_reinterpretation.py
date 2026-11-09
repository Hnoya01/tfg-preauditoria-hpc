"""Explicit immutable reinterpretation; synthetic data only."""
import copy
import hashlib
import json
from unittest.mock import patch
from tests.test_sync_intake import SyncIntakeTests
from tests.test_hpc_csv_intake import encode, row
from app.authorization_source import parse_authorization_source
from app.authorization_matching import _captures
from app.db import connect, migrate, MIGRATIONS

class ReinterpretationTests(SyncIntakeTests):
    def legacy(self, raw):
        p=copy.deepcopy(parse_authorization_source(raw))
        p.summary['adapter_provenance']['adapter']='synthetic-legacy-v1'
        m=json.loads(p.manifest);m['summary']=p.summary
        p.manifest=json.dumps(m,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
        p.preview_sha256=hashlib.sha256(p.manifest).hexdigest()
        return p

    def old_capture(self):
        raw=encode([row()]);u=self.stage(raw,name='test.csv').json()
        with patch('app.authorization_imports.parse_authorization',return_value=self.legacy(raw)):
            p=self.preview(u);old=self.confirm(u,p).json()
        return u,old,raw

    def test_explicit_immutable_idempotent_and_selection(self):
        u,old,raw=self.old_capture();c=connect(self.root)
        before=dict(c.execute('select * from authorization_captures where id=?',(old['id'],)).fetchone())
        self.assertEqual(_captures(c,self.root,self.dataset['id'],[old['id']],'real_unvalidated')[1],[])
        p=self.preview(u);self.assertTrue(p['reinterpretation_required'])
        import subprocess
        from pathlib import Path
        subprocess.run(['node',str(Path(__file__).parent/'fixtures/render_sync_preview.cjs')],input=json.dumps(p).encode(),check=True,capture_output=True)
        untouched=dict(p);untouched['reinterpretation_required']=False
        subprocess.run(['node',str(Path(__file__).parent/'fixtures/render_sync_preview.cjs')],input=json.dumps(untouched).encode(),check=True,capture_output=True)
        self.assertEqual(self.confirm(u,p).status_code,409)
        self.assertEqual(self.confirm(u,p,reinterpret_capture_id='wrong').status_code,409)
        new=self.confirm(u,p,reinterpret_capture_id=old['id']);self.assertEqual(new.status_code,201,new.text)
        self.assertNotEqual(old['id'],new.json()['id']);self.assertFalse(new.json()['analysis_started'])
        self.assertEqual(before,dict(c.execute('select * from authorization_captures where id=?',(old['id'],)).fetchone()))
        self.assertEqual(_captures(c,self.root,self.dataset['id'],[old['id']],'real_unvalidated')[1],['capture_replaced'])
        self.assertEqual(_captures(c,self.root,self.dataset['id'],[new.json()['id']],'real_unvalidated')[1],[])
        self.assertEqual(self.confirm(u).status_code,200)
        inv=self.client.get(self.url('captures')).json();self.assertEqual(len(inv['uploads']),1);self.assertEqual(len(inv['captures']),2)
        self.assertEqual(self.client.get(self.url(f'uploads/{u["id"]}/file')).content,raw)
        self.assertEqual(c.execute('pragma foreign_key_check').fetchall(),[]);c.close()

    def test_preexisting_v3_with_two_units_requires_explicit_reinterpretation(self):
        code='1234567890'
        raw=encode([row(afiliado='000111/1',practicas=f'{code} -- TAC ficticia,',
                        movimientos=f'02/07/2026 10:00 | Operador ficticio | AUTORIZADO | Resolución por ítems - AUTORIZAR: {code} - TAC ficticia x2')])
        upload=self.stage(raw,name='cantidad-ficticia.csv').json()
        with patch('app.hpc_csv_resolutions.clause_units',return_value=(None,False)):
            old_preview=self.preview(upload)
            self.assertEqual(old_preview['summary']['adapter_provenance']['adapter'],'hpc-platform-csv-v3')
            old=self.confirm(upload,old_preview).json()
        from contextlib import closing
        with closing(connect(self.root)) as c:
            original=dict(c.execute('SELECT * FROM authorization_captures WHERE id=?',(old['id'],)).fetchone())
            self.assertEqual(_captures(c,self.root,self.dataset['id'],[old['id']],'real_unvalidated')[1],['csv_reinterpretation_required'])
            new_preview=self.preview(upload);self.assertTrue(new_preview['reinterpretation_required'])
            self.assertEqual(self.confirm(upload,new_preview).status_code,409)
            new=self.confirm(upload,new_preview,reinterpret_capture_id=old['id'])
            self.assertEqual(new.status_code,201,new.text)
            selected,issues=_captures(c,self.root,self.dataset['id'],[new.json()['id']],'real_unvalidated')
            self.assertEqual(issues,[])
            self.assertEqual(json.loads(selected[0]['canonical_json'])['orders'][0]['resolutions'][0]['authorized_quantity'],'2')
            self.assertEqual(dict(c.execute('SELECT * FROM authorization_captures WHERE id=?',(old['id'],)).fetchone()),original)

    def test_old_reception_cannot_displace_new_head(self):
        u,old,raw=self.old_capture()
        u2=self.stage(encode([row(orden_hpc='TEST-2')]),name='new.csv').json();self.assertEqual(self.confirm(u2).status_code,201)
        self.assertEqual(self.confirm(u,reinterpret_capture_id=old['id']).status_code,409)

    def test_schema_upgrade_requires_offline_and_preserves_capture(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        with TemporaryDirectory() as d:
            c=connect(Path(d));migrate(c,[m for m in MIGRATIONS if m[0]<=30]);self.assertEqual(c.execute('pragma user_version').fetchone()[0],30)
            with self.assertRaises(RuntimeError):migrate(c)
            migrate(c,[m for m in MIGRATIONS if m[0]<=31],allow_existing_upgrade=True)
            self.assertEqual(c.execute('pragma user_version').fetchone()[0],31)
            self.assertEqual(c.execute('pragma foreign_key_check').fetchall(),[]);c.close()

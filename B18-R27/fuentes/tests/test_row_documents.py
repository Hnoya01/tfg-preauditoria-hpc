import hashlib
from uuid import uuid4
import unittest
from unittest.mock import patch
from app.db import connect,migrate,MIGRATIONS
from app.storage import object_path
from tests import test_practice_board as fixture

PDF=b'%PDF-1.4\n% fictitious row report\n1 0 obj <<>> endobj\n%%EOF'
class RowDocumentTests(unittest.TestCase):
    setUp=fixture.PracticeBoardTests.setUp
    tearDown=fixture.PracticeBoardTests.tearDown
    headers=fixture.PracticeBoardTests.headers
    import_book=fixture.PracticeBoardTests.import_book
    run_url=fixture.PracticeBoardTests.run_url
    base=fixture.PracticeBoardTests.base
    search=fixture.PracticeBoardTests.search
    alerts=fixture.PracticeBoardTests.alerts
    decide=fixture.PracticeBoardTests.decide
    def url(self,row=2):return self.base()+f'/rows/{row}/documents'
    def upload(self,content=PDF,**changes):
        page=self.client.get(self.url()).json()
        headers={**self.headers(),'X-Expected-Version':str(page['dataset_version']),'X-Revision-Version':str(page['revision_version']),
          'X-Revision-Id':page['revision_id'],'X-Request-Id':str(uuid4()),'X-Document-Category':'informe','X-Source-Filename':'ficticio.pdf',
          'X-Provenance-Note':'Documento ficticio aportado por ensayo','X-Expected-SHA256':hashlib.sha256(content).hexdigest()}
        headers.update(changes);self.last_headers=headers
        return self.client.post(self.url(),content=content,headers=headers)
    def test_upload_review_hash_history_idempotent_no_control_changes(self):
        conn=connect(self.root);before=conn.execute('SELECT count(*) FROM control_runs').fetchone()[0];conn.close()
        response=self.upload();self.assertEqual(response.status_code,201,response.text);identifier=response.json()['id']
        repeat=self.client.post(self.url(),content=PDF,headers=self.last_headers);self.assertEqual(repeat.status_code,200,repeat.text)
        page=self.client.get(self.url()).json();self.assertEqual(len(page['items']),1);self.assertEqual(page['summary']['informe']['state'],'aportado_sin_revisar')
        file=self.client.get(f'/api/datasets/{self.dataset["id"]}/row-documents/{identifier}/file');self.assertEqual(file.content,PDF);self.assertEqual(file.headers['x-content-type-options'],'nosniff')
        body={k:page[k] for k in ('revision_id',)};body.update(expected_dataset_version=page['dataset_version'],expected_revision_version=page['revision_version'],request_id=str(uuid4()),note='Lectura manual ficticia, sin evaluación clínica')
        reviewed=self.client.post(self.url()+f'/{identifier}/reviews',json=body,headers=self.headers());self.assertEqual(reviewed.status_code,200,reviewed.text)
        self.assertEqual(self.client.post(self.url()+f'/{identifier}/reviews',json=body,headers=self.headers()).status_code,200)
        self.assertEqual(self.client.get(self.url()).json()['summary']['informe']['state'],'revisado_manualmente')
        self.assertEqual(self.search()['items'][0]['documents']['informe']['state'],'revisado_manualmente')
        conn=connect(self.root);self.assertEqual(conn.execute('SELECT count(*) FROM control_runs').fetchone()[0],before)
        self.assertEqual(conn.execute('SELECT count(*) FROM proposal_versions').fetchone()[0],0);conn.close()
    def test_validation_integrity_scope_and_csrf(self):
        self.assertEqual(self.upload(b'Not a PDF').status_code,422)
        self.assertEqual(self.upload(**{'X-Source-Filename':'../x.pdf'}).status_code,422)
        self.assertEqual(self.upload(**{'X-Expected-SHA256':'0'*64}).status_code,422)
        self.assertEqual(self.upload(**{'X-Expected-Version':'1'}).status_code,409)
        result=self.upload();self.assertEqual(result.status_code,201,result.text)
        missing_csrf={k:v for k,v in self.last_headers.items() if 'csrf' not in k.lower()}
        self.assertEqual(self.client.post(self.url(),content=PDF,headers=missing_csrf).status_code,403)
        self.assertEqual(self.client.get(self.url(99999)).status_code,404)
        sha=hashlib.sha256(PDF).hexdigest();object_path(self.root,sha).write_bytes(b'corrupt')
        self.assertEqual(self.client.get(f'/api/datasets/{self.dataset["id"]}/row-documents/{result.json()["id"]}/file').status_code,409)
    def test_closed_revision_blocks_writes_and_wrong_request_id_reuse(self):
        result=self.upload();self.assertEqual(result.status_code,201,result.text)
        bad={**self.last_headers,'X-Provenance-Note':'Otra procedencia distinta'}
        self.assertEqual(self.client.post(self.url(),content=PDF,headers=bad).status_code,409)
        conn=connect(self.root);conn.execute("UPDATE revisions SET state='cerrada' WHERE id=?",(self.last_headers['X-Revision-Id'],));conn.close()
        self.assertEqual(self.upload(content=PDF.replace(b'fictitious',b'different')).status_code,409)
        self.assertFalse(self.client.get(self.url()).json()['writable'])
    def test_readonly_role_and_different_dataset_deny_access(self):
        from app.security import create_user
        from tests.test_p02 import PASSWORD,ORIGIN
        conn=connect(self.root);create_user(conn,'other-doc-reader',PASSWORD,'viewer');conn.close()
        result=self.upload();self.assertEqual(result.status_code,201,result.text)
        self.client.delete('/api/session',headers=self.headers())
        login=self.client.post('/api/session',json={'username':'other-doc-reader','password':PASSWORD},headers={'Origin':ORIGIN})
        self.assertEqual(login.status_code,200,login.text)
        self.assertEqual(self.client.get(self.url()).status_code,403)
        self.assertEqual(self.client.get(f'/api/datasets/{self.dataset["id"]}/row-documents/{result.json()["id"]}/file').status_code,403)

class RowDocumentMigrationTests(unittest.TestCase):
    def test_offline_backup_upgrade_and_failure_rolls_back(self):
        import sqlite3
        from pathlib import Path
        from tests.temp_support import TemporaryDirectory
        from app.db import backup_before_upgrade
        with TemporaryDirectory(dir='.tmp') as name:
            root=Path(name);conn=connect(root);migrate(conn,MIGRATIONS[:27])
            self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0],27)
            with self.assertRaises(RuntimeError):migrate(conn)
            backup=backup_before_upgrade(conn,root)
            old=sqlite3.connect(backup/'app.sqlite3');self.assertEqual(old.execute('PRAGMA user_version').fetchone()[0],27);old.close()
            broken=(*MIGRATIONS[:27],(28,(*dict(MIGRATIONS)[28],'NOT VALID SQL')))
            with self.assertRaises(sqlite3.OperationalError):migrate(conn,broken,allow_existing_upgrade=True)
            self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0],27)
            self.assertIsNone(conn.execute("SELECT name FROM sqlite_master WHERE name='row_documents'").fetchone())
            self.assertEqual(migrate(conn,MIGRATIONS[:28],allow_existing_upgrade=True),28)
            self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(),[]);conn.close()

class RowDocumentAdditionalTests(unittest.TestCase):
    setUp=RowDocumentTests.setUp
    tearDown=RowDocumentTests.tearDown
    headers=RowDocumentTests.headers
    import_book=RowDocumentTests.import_book
    run_url=RowDocumentTests.run_url
    base=RowDocumentTests.base
    search=RowDocumentTests.search
    alerts=RowDocumentTests.alerts
    decide=RowDocumentTests.decide
    url=RowDocumentTests.url
    upload=RowDocumentTests.upload
    def test_oversized_pdf_and_failed_transaction_leave_no_registered_attachment(self):
        self.assertEqual(self.upload(PDF+b'x'*(10*1024*1024)).status_code,413)
        with patch('app.row_documents.event',side_effect=RuntimeError('injected failure')):
            with self.assertRaises(RuntimeError):self.upload()
        conn=connect(self.root)
        self.assertEqual(conn.execute('SELECT count(*) FROM row_documents').fetchone()[0],0)
        self.assertEqual(conn.execute('SELECT count(*) FROM row_document_reviews').fetchone()[0],0);conn.close()
    def test_append_only_history(self):
        import sqlite3
        self.assertEqual(self.upload().status_code,201)
        conn=connect(self.root)
        with self.assertRaises(sqlite3.IntegrityError):conn.execute("UPDATE row_documents SET provenance='changed'")
        with self.assertRaises(sqlite3.IntegrityError):conn.execute('DELETE FROM row_documents')
        conn.close()

from tests import test_closure as closure_fixture
class RowDocumentClosureTests(unittest.TestCase):
    setUp=closure_fixture.ClosureTests.setUp
    tearDown=closure_fixture.ClosureTests.tearDown
    headers=closure_fixture.ClosureTests.headers
    import_book=closure_fixture.ClosureTests.import_book
    run_url=closure_fixture.ClosureTests.run_url
    alerts=closure_fixture.ClosureTests.alerts
    decide=closure_fixture.ClosureTests.decide
    base=closure_fixture.ClosureTests.base
    preview=closure_fixture.ClosureTests.preview
    resolve_alerts=closure_fixture.ClosureTests.resolve_alerts
    justify=closure_fixture.ClosureTests.justify
    close=closure_fixture.ClosureTests.close
    url=RowDocumentTests.url
    upload=RowDocumentTests.upload
    def test_closed_zip_embeds_original_hash_and_history_stays_frozen(self):
        from io import BytesIO
        from zipfile import ZipFile
        import json
        uploaded=self.upload();self.assertEqual(uploaded.status_code,201,uploaded.text)
        note=('COTEJO DOCUMENTAL MANUAL · no ejecuta RN20–RN22 ni confirma vínculo.\n'
              'Identidad: Compatible según lectura manual · Página PDF 1 · Identidad ficticia cotejada\n'
              'Fecha: No evaluado\nEstudio: No evaluado\nRegión: No evaluado\nCantidad: No evaluado\n'
              'Mención de contraste: No concluyente · Página PDF 2 · Texto ficticio ilegible\n'
              'La mención de contraste no acredita cantidad ni importe.')
        current=self.client.get(self.url()).json()
        body=dict(expected_dataset_version=current['dataset_version'],expected_revision_version=current['revision_version'],
                  revision_id=current['revision_id'],request_id=str(uuid4()),note=note)
        reviewed=self.client.post(self.url()+f"/{uploaded.json()['id']}/reviews",json=body,headers=self.headers())
        self.assertEqual(reviewed.status_code,200,reviewed.text)
        self.assertEqual(self.client.get(self.url()).json()['items'][0]['reviews'][0]['note'],note)
        self.dataset['version']=reviewed.json()['dataset_version'];self.resolve_alerts();page=self.justify();closed=self.close(page)
        self.assertEqual(closed.status_code,201,closed.text)
        first=self.client.get(self.base()+'/export-closed');self.assertEqual(first.status_code,200)
        with ZipFile(BytesIO(first.content)) as archive:
            manifest=json.loads(archive.read('manifest.json'));entry=manifest['row_documents']['objects'][0]
            self.assertEqual(archive.read(entry['path']),PDF)
            self.assertEqual(entry['sha256'],hashlib.sha256(PDF).hexdigest())
            records=[json.loads(line) for line in archive.read('row_documents.jsonl').splitlines()]
            self.assertEqual(records[0]['id'],uploaded.json()['id']);self.assertEqual(records[0]['source_row'],2)
            self.assertEqual(records[0]['reviews'][0]['note'],note)
        object_path(self.root,hashlib.sha256(PDF).hexdigest()).write_bytes(b'changed after closure')
        self.assertEqual(self.client.get(self.base()+'/export-closed').content,first.content)
    def test_corrupt_attachment_cannot_freeze_a_successful_close(self):
        uploaded=self.upload();self.dataset['version']=uploaded.json()['dataset_version']
        self.resolve_alerts();page=self.justify()
        object_path(self.root,hashlib.sha256(PDF).hexdigest()).write_bytes(b'corrupt')
        result=self.close(page);self.assertEqual(result.status_code,409,result.text)
        conn=connect(self.root);self.assertEqual(conn.execute('SELECT count(*) FROM revision_closures').fetchone()[0],0);conn.close()

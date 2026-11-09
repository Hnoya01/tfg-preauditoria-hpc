"""Synthetic producer bytes exercise the real API and persisted derivation, never HPC."""
import hashlib
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
from app.db import connect
from app.storage import read_verified
from app.authorization_source import parse_authorization_source
from app.authorization_json import parse_authorization
from app.authorization_matching import _captures
from tests import test_authorization_imports as intake_tests
from tests.test_hpc_sync_adapter import fixture, seal


class SyncIntakeTests(unittest.TestCase):
    setUp = intake_tests.AuthorizationImportTests.setUp
    tearDown = intake_tests.AuthorizationImportTests.tearDown
    headers = intake_tests.AuthorizationImportTests.headers
    import_book = intake_tests.AuthorizationImportTests.import_book
    run_url = intake_tests.AuthorizationImportTests.run_url
    url = intake_tests.AuthorizationImportTests.url
    stage = intake_tests.AuthorizationImportTests.stage
    preview = intake_tests.AuthorizationImportTests.preview
    confirm = intake_tests.AuthorizationImportTests.confirm

    def package(self):
        return subprocess.run(['node',str(Path(__file__).parent/'fixtures/produce_synthetic_sync.cjs')],
                              capture_output=True,check=True,timeout=10).stdout

    def test_producer_api_persisted_a1_no_network_or_inference(self):
        raw=self.package()
        with patch('socket.socket.connect', side_effect=AssertionError('network forbidden')):
            upload=self.stage(raw).json(); p=self.preview(upload)
            self.assertTrue(p['can_import']); self.assertEqual(p['canonical']['data_origin'],'real_unvalidated')
            self.assertEqual(p['canonical']['coverage']['declared'],'partial')
            self.assertIn('2026-08-01',p['canonical']['source']['stream_id'])
            response=self.confirm(upload,p); self.assertEqual(response.status_code,201,response.text)
            self.assertFalse(response.json()['analysis_started'])
            downloaded=self.client.get(self.url(f'uploads/{upload["id"]}/file'))
            self.assertEqual(downloaded.content,raw)
        conn=connect(self.root)
        try:
            source=conn.execute("SELECT * FROM source_registry WHERE kind='authorizations'").fetchone()
            meta=json.loads(source['metadata_json'])
            derived=read_verified(self.root,meta['derived_a1_sha256'])
            self.assertEqual(parse_authorization(derived).canonical,p['canonical'])
            manifest=json.loads(read_verified(self.root,source['manifest_sha256']))
            self.assertEqual(manifest['source_sha256'],hashlib.sha256(raw).hexdigest())
            self.assertEqual(manifest['derived_a1_sha256'],hashlib.sha256(derived).hexdigest())
            captures,issues=_captures(conn,self.root,self.dataset['id'],[response.json()['id']],'real')
            self.assertEqual(issues,[])
        finally: conn.close()
        # Pass the real API preview to the actual renderer in a synthetic DOM.
        subprocess.run(['node',str(Path(__file__).parent/'fixtures/render_sync_preview.cjs')],
                       input=json.dumps(p).encode(),capture_output=True,check=True,timeout=10)

    def test_duplicate_renamed_and_stale_preview(self):
        raw=self.package(); upload=self.stage(raw).json(); p=self.preview(upload)
        again=self.stage(raw,name='renamed.json');self.assertEqual(again.status_code,200)
        self.assertEqual(again.json()['id'],upload['id'])
        bad=self.confirm(upload,p,preview_sha256='0'*64);self.assertEqual(bad.status_code,409)
        ok=self.confirm(upload,p);self.assertEqual(ok.status_code,201)
        self.assertEqual(self.confirm(upload).status_code,200)

    def test_invalid_digest_keeps_original_without_capture(self):
        d=fixture();d['items'][0]['payload']['source']['affiliate']='MODIFIED'
        raw=json.dumps(d).encode(); upload=self.stage(raw).json();p=self.preview(upload)
        self.assertFalse(p['can_import']);self.assertEqual(p['technical_state'],'format_error')
        self.assertEqual(self.client.get(self.url(f'uploads/{upload["id"]}/file')).content,raw)
        self.assertEqual(self.confirm(upload,p,preview_sha256='0'*64).status_code,422)
        conn=connect(self.root)
        self.assertEqual(conn.execute('SELECT count(*) FROM authorization_captures').fetchone()[0],0);conn.close()

    def test_derived_publication_failure_rolls_back_capture(self):
        u=self.stage(self.package()).json();p=self.preview(u)
        from app import authorization_imports as intake
        publish=intake.publish_bytes
        def fail_derived(root,data):
            if json.loads(data).get('schema_version')=='A1-canonical-v1': raise OSError('injected')
            return publish(root,data)
        with patch.object(intake,'publish_bytes',side_effect=fail_derived):
            with self.assertRaises(OSError):self.confirm(u,p)
        conn=connect(self.root)
        self.assertEqual(conn.execute('SELECT count(*) FROM authorization_captures').fetchone()[0],0)
        self.assertEqual(conn.execute('SELECT version FROM datasets WHERE id=?',(self.dataset['id'],)).fetchone()[0],p['dataset_version'])
        conn.close(); self.assertEqual(self.confirm(u,p).status_code,201)

    def test_unknown_scope_and_dates_not_inferred(self):
        d=fixture();u=self.stage(json.dumps(d).encode()).json();p=self.preview(u)
        res=p['canonical']['orders'][0]['resolutions'][0]
        self.assertEqual(res['scope'],'unknown');self.assertEqual(res['item_ids'],[])
        self.assertIsNone(res['authorized_quantity']);self.assertEqual(res['status'],'Autorizada')
        d2=fixture();d2['queried_date']='2026-08-02'
        self.assertNotEqual(parse_authorization_source(json.dumps(d).encode()).canonical['source']['stream_id'],
                            parse_authorization_source(json.dumps(d2).encode()).canonical['source']['stream_id'])

    test_permissions = intake_tests.AuthorizationImportTests.test_permissions_and_cross_dataset_ids_for_all_authorization_routes
    test_race = intake_tests.AuthorizationImportTests.test_permission_and_version_checked_again_at_publication

    def test_tampered_derived_a1_blocks_downstream(self):
        from app.storage import object_path
        u=self.stage(self.package()).json();p=self.preview(u);imported=self.confirm(u,p).json()
        object_path(self.root,p['summary']['adapter_provenance']['output_sha256']).write_bytes(b'{}')
        conn=connect(self.root)
        try:
            _,issues=_captures(conn,self.root,self.dataset['id'],[imported['id']],'real')
            self.assertIn('source_unverifiable',issues)
        finally:conn.close()

    def test_sync_limits_and_invalid_input_preserve_original_without_import(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":"\\ud800"}', b'['*70+b']'*70,
                    json.dumps({'extractor_version':'unknown'}).encode()):
            u=self.stage(raw).json();p=self.preview(u)
            self.assertFalse(p['can_import']);self.assertEqual(p['technical_state'],'format_error')
        from app.authorization_json import AuthorizationFormatError
        from app.storage import MAX_SOURCE_BYTES
        with self.assertRaises(AuthorizationFormatError):parse_authorization_source(b' '* (MAX_SOURCE_BYTES+1))
        d=fixture();d['rows']*=201
        with self.assertRaises(AuthorizationFormatError):parse_authorization_source(json.dumps(d).encode())

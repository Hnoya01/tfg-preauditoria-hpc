"""Source releases preserve Git blob bytes, regardless of checkout EOL policy."""
from io import BytesIO
import hashlib
import json
from pathlib import Path
import subprocess
import unittest
from zipfile import ZipFile

from scripts.release_snapshot import build_release
from scripts.recovery_data import source_archive
from tests.temp_support import TemporaryDirectory


class ReleasePortabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory(dir='.tmp');self.root=Path(self.temp.name).resolve()
        self.repo=self.root/'repo';self.repo.mkdir()
        self.git('init','--quiet')
        self.git('config','--local','core.autocrlf','false')
        attributes=self.root/'empty-attributes';attributes.write_bytes(b'')
        self.git('config','--local','core.attributesFile',str(attributes))
        self.contents={'app/db.py':b'MIGRATIONS: tuple = ((1, ()),)\n',
            'app/api.py':b'"""FICTICIO compatibility fixture."""\n','app/__init__.py':b'',
            'LF.txt':b'FICTICIO LF\nsecond line\n','CRLF.txt':b'FICTICIO CRLF\r\nsecond line\r\n',
            'binary.dat':b'\x00FICTICIO\n\r\n\xff', 'space name.txt':b'FICTICIO spaced name\n'}
        entries=[{'path':name,'bytes':len(value),'sha256':hashlib.sha256(value).hexdigest()} for name,value in sorted(self.contents.items())]
        entries.append({'path':'INVENTARIO.json','sha256':None})
        self.contents['INVENTARIO.json']=json.dumps({'file_count':len(entries),'files':entries}).encode()
        for name,value in self.contents.items():
            path=self.repo/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(value)
        self.git('add','--all')
        self.git('-c','user.name=Synthetic fixture','-c','user.email=synthetic@example.invalid','commit','--quiet','-m','FICTICIO source bytes')
        self.commit=self.git('rev-parse','HEAD').decode().strip()

    def tearDown(self):self.temp.cleanup()

    def git(self,*args):
        return subprocess.check_output(['git','-C',str(self.repo),*args],stderr=subprocess.PIPE)

    def test_clean_release_preserves_blobs_with_lf_and_crlf_checkouts(self):
        trees=[];evidence=[]
        for setting in ('false','true'):
            with self.subTest(autocrlf=setting):
                self.git('config','--local','core.autocrlf',setting)
                # An unchanged stat entry can avoid a checkout rewrite even
                # with --force. Recreate the files to exercise EOL conversion.
                for name in self.contents:(self.repo/name).unlink()
                self.git('checkout-index','--all','--force','--index')
                self.assertEqual(self.git('status','--porcelain'),b'')
                expected=self.contents['LF.txt'].replace(b'\n',b'\r\n') if setting=='true' else self.contents['LF.txt']
                self.assertEqual((self.repo/'LF.txt').read_bytes(),expected)
                # This is the observed old mechanism, not the release contract.
                with ZipFile(BytesIO(self.git('archive','--format=zip',self.commit))) as old:
                    exported=old.read('LF.txt');self.assertEqual(exported,expected)
                target=self.root/(setting+'.zip');manifest=build_release(self.repo,target)
                with ZipFile(target) as release:
                    for name,value in self.contents.items():self.assertEqual(release.read(name),value,name)
                self.assertEqual(source_archive(target)['schema_version'],1)
                self.assertEqual(manifest['provenance'],{'kind':'git_commit','git_commit':self.commit,'dirty':False})
                trees.append(manifest['source_tree_sha256'])
                evidence.append({'autocrlf':setting,'blob_sha256':hashlib.sha256(self.contents['LF.txt']).hexdigest(),
                    'archive_sha256':hashlib.sha256(exported).hexdigest(),'release_sha256':manifest['files']['LF.txt'],
                    'tree_sha256':manifest['source_tree_sha256'],'inventory_verified':True})
        self.assertEqual(len(set(trees)),1)
        output=Path('.test-results');output.mkdir(exist_ok=True)
        (output/'portable-eol.json').write_text(json.dumps(evidence,indent=2))

    def test_explicit_commit_does_not_depend_on_working_tree_files(self):
        (self.repo/'LF.txt').unlink()
        target=self.root/'historical.zip';build_release(self.repo,target,commit=self.commit)
        with ZipFile(target) as release:self.assertEqual(release.read('LF.txt'),self.contents['LF.txt'])
        self.assertEqual(source_archive(target)['provenance']['git_commit'],self.commit)

    def test_inventory_rejects_altered_missing_or_added_entries_after_rehash(self):
        original=self.root/'original.zip';build_release(self.repo,original)
        for change in ('altered','missing','extra'):
            with self.subTest(change=change):
                with ZipFile(original) as archive:files={name:archive.read(name) for name in archive.namelist()}
                manifest=json.loads(files.pop('SOURCE_MANIFEST.json'))
                if change=='altered':files['LF.txt']+=b'FICTICIO changed byte'
                elif change=='missing':files.pop('LF.txt')
                else:files['extra.txt']=b'FICTICIO unlisted source'
                manifest['files']={name:hashlib.sha256(value).hexdigest() for name,value in files.items()}
                manifest['source_tree_sha256']=hashlib.sha256(json.dumps(manifest['files'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
                target=self.root/(change+'.zip')
                with ZipFile(target,'w') as archive:
                    for name,value in files.items():archive.writestr(name,value)
                    archive.writestr('SOURCE_MANIFEST.json',json.dumps(manifest))
                with self.assertRaisesRegex(RuntimeError,'Inventario de release'):source_archive(target)

    def test_committed_symlinks_and_gitlinks_are_not_exported_as_regular_files(self):
        blob=self.git('rev-parse',self.commit+':LF.txt').decode().strip()
        for mode,oid in (('120000',blob),('160000',self.commit)):
            with self.subTest(mode=mode):
                self.git('update-index','--add','--cacheinfo',mode,oid,'unsupported-entry')
                self.git('-c','user.name=Synthetic fixture','-c','user.email=synthetic@example.invalid','commit','--quiet','-m','FICTICIO unsupported source mode')
                commit=self.git('rev-parse','HEAD').decode().strip()
                with self.assertRaisesRegex(RuntimeError,'source path or type'):
                    build_release(self.repo,self.root/(mode+'.zip'),commit=commit)
                self.git('update-index','--force-remove','unsupported-entry')

"""Recovery safety and authenticated-encryption checks use invented data only."""
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
from tests.temp_support import TemporaryDirectory
import unittest
from zipfile import ZipFile,ZIP_DEFLATED

from app.db import connect,migrate
from app.security import create_user,issue_session,token_digest
from app.service import create_dataset,create_batch,confirm_invoice
from scripts.recovery_data import (activate_quarantined,bundle_backup,digest,fingerprint,
    make_backup,powershell,restore_archive)
from tests.test_p02 import book,PASSWORD


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory(dir='.tmp');self.root=Path(self.temp.name).resolve()
        self.assertTrue(self.root.is_relative_to((Path.cwd()/'.tmp').resolve()))
        self.source=self.root/'source';self.source.mkdir()
        c=connect(self.source);migrate(c);user=create_user(c,'owner',PASSWORD,'admin')
        token,_=issue_session(c,user);self.token=token_digest(token)
        ds=create_dataset(c,self.token,'FICTICIO recuperación')
        batch,_=create_batch(c,self.source,self.token,ds['id'],ds['version'],'FICTICIO.xlsx',book([('15/08/2026',10,20,30)]))
        confirm_invoice(c,self.source,self.token,ds['id'],batch['id'],'2026-08',batch['dataset_version']);c.close()
        self.release=self.root/'application.zip'
        from scripts.release_snapshot import build_release
        build_release(Path.cwd(),self.release,synthetic=True)

    def tearDown(self):self.temp.cleanup()

    def backup(self):
        m,sha=make_backup(self.source,self.root/'backup',self.release,data_kind='synthetic')
        archive=self.root/'backup.zip';bundle_backup(self.root/'backup',archive)
        return m,sha,archive

    def test_complete_state_objects_permissions_and_revoked_sessions(self):
        before=fingerprint(self.source);m,sha,archive=self.backup()
        target=self.root/'restored';restore_archive(archive,target,sha,self.source)
        self.assertEqual(fingerprint(target),before)
        self.assertEqual(digest(target/'app.sqlite3'),m['database_sha256'])
        activation=activate_quarantined(target)
        self.assertEqual(activation['sessions_revoked'],1)
        self.assertFalse(activation['workers_enabled'])
        self.assertEqual(activate_quarantined(target),activation)
        self.assertEqual(fingerprint(self.source),before)

    def test_missing_original_and_changed_manifest_are_not_ready(self):
        m,sha,archive=self.backup()
        bad=self.root/'missing.zip'
        missing=m['logical_state']['objects'][0]['relative_path']
        with ZipFile(archive) as src,ZipFile(bad,'w') as dst:
            for name in src.namelist():
                if name!=missing:dst.writestr(name,src.read(name))
        with self.assertRaises(RuntimeError):restore_archive(bad,self.root/'missing',sha,self.source)
        self.assertFalse((self.root/'missing'/'RECOVERY_READY.json').exists())
        with self.assertRaises(RuntimeError):restore_archive(archive,self.root/'wrong-manifest','0'*64,self.source)

    def test_corrupt_object_and_existing_destination_do_not_overwrite_work(self):
        m,sha,archive=self.backup();bad=self.root/'corrupt.zip'
        altered=m['logical_state']['objects'][0]['relative_path']
        with ZipFile(archive) as src,ZipFile(bad,'w') as dst:
            for name in src.namelist():dst.writestr(name,b'alterado ficticio' if name==altered else src.read(name))
        target=self.root/'incomplete'
        with self.assertRaises(RuntimeError):restore_archive(bad,target,sha,self.source)
        self.assertFalse((target/'RECOVERY_READY.json').exists())
        occupied=self.root/'occupied';occupied.mkdir();(occupied/'keep.txt').write_text('Conservar')
        with self.assertRaises(FileExistsError):restore_archive(archive,occupied,sha,self.source)
        self.assertEqual((occupied/'keep.txt').read_text(),'Conservar')

    def test_unsafe_paths_and_nested_backup_are_rejected(self):
        from scripts.recovery_data import contained
        for name in ('../escape','C:/escape','/escape','objects/../../escape','objects\\escape'):
            with self.subTest(path=name),self.assertRaises(ValueError):contained(self.root,name)
        with self.assertRaises(ValueError):make_backup(self.source,self.source/'unintended',self.release,data_kind='synthetic')

    @unittest.skipUnless(os.name=='nt','El ensayo AES-GCM usa la implementación .NET Windows instalada')
    def test_authenticated_encrypted_copy_rejects_corruption_and_wrong_key(self):
        plain=self.root/'plain.zip';plain.write_bytes(b'FICTICIO: bytes del ensayo de cifrado')
        cipher=self.root/'copy.aesgcm';key=self.root/'key.bin';out=self.root/'decrypted.zip'
        powershell('recovery_crypto.ps1','-Mode','Encrypt','-InputFile',plain,'-OutputFile',cipher,'-KeyFile',key)
        powershell('recovery_crypto.ps1','-Mode','Decrypt','-InputFile',cipher,'-OutputFile',out,'-KeyFile',key)
        self.assertEqual(out.read_bytes(),plain.read_bytes())
        damaged=self.root/'damaged.aesgcm';content=bytearray(cipher.read_bytes());content[-1]^=1;damaged.write_bytes(content)
        wrong=self.root/'wrong.key';wrong.write_bytes(os.urandom(32))
        for n,encrypted,k in [('damaged',damaged,key),('wrong-key',cipher,wrong)]:
            target=self.root/(n+'.zip')
            with self.assertRaises(RuntimeError):powershell('recovery_crypto.ps1','-Mode','Decrypt','-InputFile',encrypted,'-OutputFile',target,'-KeyFile',k)
            self.assertFalse(target.exists())

    @unittest.skipUnless(os.name=='nt','Reglas de acceso NTFS del entorno Windows')
    def test_new_key_directory_has_only_operator_system_and_administrators(self):
        keys=self.root/'keys';keys.mkdir()
        powershell('recovery_access.ps1','-Mode','PrepareKey','-TargetRoot',keys)


if __name__=='__main__':unittest.main()

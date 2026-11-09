"""Offline recovery drill helpers. No overwrite, source writes or public routes."""
from datetime import datetime,timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path,PurePosixPath
import shutil
import sqlite3
import subprocess
import sys
from uuid import uuid4
from zipfile import ZipFile,ZIP_DEFLATED

from scripts.verify_v9_preservation import read_only,table_digest
from app.object_gate import recovery_snapshot,LOCK_NAME
from scripts.release_snapshot import declared_schema


FORMAT='TFG-recovery-v1'
EXCLUDED={'backups','tmp','app.sqlite3','app.sqlite3-wal','app.sqlite3-shm','initial_admin_password.txt',
          'RECOVERY_PENDING.json','RECOVERY_READY.json','RECOVERY_ACTIVATED.json',
          'manifest.json','access.json','application.zip','application'}
EXCLUDED.add(LOCK_NAME)


def digest(path):
    result=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(2*1024*1024),b''):result.update(chunk)
    return result.hexdigest()


def dump(path,value):
    with Path(path).open('x',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False,sort_keys=True,indent=2)


def stamp():return datetime.now(timezone.utc).isoformat()


def powershell(script,*args):
    executable=os.environ.get('TFG_RECOVERY_PWSH') or shutil.which('pwsh')
    if not executable:raise RuntimeError('Se requiere PowerShell 7 para ACL y AES-GCM')
    result=subprocess.run([executable,'-NoLogo','-NoProfile','-NonInteractive','-File',str(Path(__file__).with_name(script)),*map(str,args)],capture_output=True,text=True)
    if result.returncode:
        failure=RuntimeError(f'No se completó {script}')
        failure.diagnostic=result.stderr
        raise failure
    return result.stdout.strip()


def private_directory(path,acl_source):
    path=Path(path).resolve()
    path.mkdir(parents=True,exist_ok=False)
    if os.name=='nt':powershell('recovery_access.ps1','-Mode','Prepare','-SourceRoot',Path(acl_source).resolve(),'-TargetRoot',path)
    else:path.chmod(0o700)
    return path


def contained(root,relative):
    p=PurePosixPath(relative)
    if p.is_absolute() or '..' in p.parts or '\\' in relative or ':' in relative:raise ValueError('Ruta de recuperación inválida')
    path=Path(root).joinpath(*p.parts)
    if not path.resolve().is_relative_to(Path(root).resolve()):raise ValueError('Ruta fuera del destino')
    if any(parent.is_symlink() for parent in [path,*path.parents]):raise ValueError('No se admiten enlaces')
    return path


def fingerprint(root):
    root=Path(root).resolve();conn=read_only(root/'app.sqlite3')
    try:
        if conn.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or conn.execute('PRAGMA foreign_key_check').fetchone():raise RuntimeError('Integridad de base inválida')
        schema=[tuple(r) for r in conn.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")]
        tables={r['name']:table_digest(conn,r['name']) for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")}
        objects=[]
        for row in conn.execute('SELECT sha256,byte_count,relative_path FROM stored_files ORDER BY sha256'):
            if row['relative_path']!=f'objects/{row["sha256"][:2]}/{row["sha256"]}':raise RuntimeError('Localizador de objeto no canónico')
            p=contained(root,row['relative_path'])
            if not p.is_file() or p.stat().st_size!=row['byte_count'] or digest(p)!=row['sha256']:raise RuntimeError('Original ausente o alterado')
            objects.append(dict(row))
        registered={o['relative_path'] for o in objects}
        actual={p.relative_to(root).as_posix() for p in (root/'objects').rglob('*') if p.is_file()}
        extras=[]
        for relative in sorted(actual-registered):
            path=contained(root,relative)
            extras.append({'relative_path':relative,'sha256':digest(path),'byte_count':path.stat().st_size,
                           'classification':'unregistered_at_snapshot_may_await_commit'})
        result = {'schema':conn.execute('PRAGMA user_version').fetchone()[0],
            'schema_sha256':hashlib.sha256(json.dumps(schema,separators=(',',':')).encode()).hexdigest(),
            'tables':{k:{'count':v[0],'sha256':v[1]} for k,v in tables.items()},'objects':objects}
        if extras:result['unregistered_objects']=extras
        return result
    finally:conn.close()


def source_archive(path):
    with ZipFile(path) as z:
        m=json.loads(z.read('SOURCE_MANIFEST.json'))
        if m.get('kind')!='source_review_snapshot' or set(z.namelist())!=set(m['files'])|{'SOURCE_MANIFEST.json'}:raise RuntimeError('Paquete de aplicación inválido')
        if len(z.namelist())!=len(set(z.namelist())):raise RuntimeError('Entradas duplicadas')
        for name,sha in m['files'].items():
            contained(Path.cwd(),name)
            if hashlib.sha256(z.read(name)).hexdigest()!=sha:raise RuntimeError('Código de aplicación alterado')
        expected=hashlib.sha256(json.dumps(m['files'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if m['source_tree_sha256']!=expected:raise RuntimeError('Árbol de aplicación inválido')
        if not {'app/db.py','app/api.py','app/__init__.py'}<=set(m['files']):
            raise RuntimeError('Release sin contrato de compatibilidad verificable')
        if declared_schema(z.read('app/db.py'))!=m['schema_version']:raise RuntimeError('Esquema declarado no corresponde al código')
        if m.get('manifest_version') is None:
            # Existing archives remain readable when their real code/schema can
            # be verified. Missing historical commit provenance is not invented.
            m['provenance']={'kind':'legacy_hash_only','git_commit':None,'dirty':None}
            return m
        if m['manifest_version']!=2:raise RuntimeError('Versión de release no admitida')
        provenance=m.get('provenance',{})
        if provenance.get('kind') not in ('git_commit','synthetic_working_tree') or not isinstance(provenance.get('dirty'),bool):raise RuntimeError('Procedencia de release inválida')
        commit=provenance.get('git_commit','')
        if len(commit)!=40 or any(c not in '0123456789abcdef' for c in commit):raise RuntimeError('Commit de release inválido')
        if provenance['kind']=='git_commit' and provenance['dirty']:raise RuntimeError('Release atribuido a commit limpio con cambios')
        if provenance['kind']=='git_commit':
            inventory=json.loads(z.read('INVENTARIO.json'))
            if {i['path'] for i in inventory['files']}!=set(m['files']) or inventory['file_count']!=len(m['files']):
                raise RuntimeError('Inventario de release incompleto')
            for item in inventory['files']:
                if item['path']=='INVENTARIO.json':
                    if item['sha256'] is not None:raise RuntimeError('Autorreferencia de inventario inválida')
                    continue
                if m['files'][item['path']]!=item['sha256'] or len(z.read(item['path']))!=item['bytes']:
                    raise RuntimeError('Inventario de release no corresponde a sus bytes')
        return m


def effective_state(root):
    """Capture derived freshness/decisions as well as the immutable stored rows."""
    from app.controls import _run_summary
    from app.dependencies import result_affected
    from app.proposal_freshness import ProposalEvaluator
    from app.review import _batch,_decision_status,_latest_run,_result
    conn=read_only(Path(root)/'app.sqlite3')
    try:
        runs={r['id']:_run_summary(conn,r['dataset_id'],r['id']) for r in conn.execute('SELECT id,dataset_id FROM control_runs ORDER BY id')}
        summaries={k:{field:v[field] for field in ('freshness','stored_freshness','affected_rules','global_affected_rules','affected_rows')} for k,v in runs.items()}
        decisions={};proposals={}
        for item in conn.execute('SELECT i.batch_id,b.dataset_id FROM invoice_imports i JOIN batches b ON b.id=i.batch_id'):
            b=_batch(conn,item['dataset_id'],item['batch_id']);latest=_latest_run(conn,b['revision_id'])
            summary=runs.get(latest['id']) if latest else None
            for alert in conn.execute('SELECT * FROM alerts WHERE revision_id=?',(b['revision_id'],)):
                result=_result(conn,latest['id'],alert['source_row'],alert['rule_code']) if latest else None
                current=bool(result and result['result']=='con_indicios' and not result_affected(summary,alert['source_row'],alert['rule_code']))
                decisions[alert['id']]={'current':current,'decision':_decision_status(conn,alert['id'],latest['id']) if current else None}
            versions=conn.execute('SELECT * FROM proposal_versions WHERE import_id=? ORDER BY id',(b['import_id'],)).fetchall()
            if versions:
                evaluator=ProposalEvaluator(conn,Path(root),item['dataset_id'],item['batch_id'],b,summary)
                for version in versions:
                    value=evaluator.evaluate(version)
                    proposals[version['id']]={'state':value['state'],'current_component_count':value['current_component_count'],
                        'affected_component_count':value['affected_component_count'],'amount_ars':value.get('amount_ars')}
        return json.loads(json.dumps({'runs':summaries,'decisions':decisions,'proposals':proposals}))
    finally:conn.close()


def make_backup(source,target,release,*,data_kind):
    # No source objects are moved/deleted. The manifest quarantines unregistered
    # bytes logically; they remain unavailable to authenticated domain routes.
    with recovery_snapshot(source):
        return _make_backup(source,target,release,data_kind=data_kind)


def _make_backup(source,target,release,*,data_kind):
    source,target,release=Path(source).resolve(),Path(target).resolve(),Path(release).resolve()
    if target==source or source.is_relative_to(target):raise ValueError('Destino de respaldo inseguro')
    if target.is_relative_to(source) and target.relative_to(source).parts[0]!='backups':raise ValueError('No anidar el respaldo entre los datos operativos')
    if data_kind not in ('private_real','synthetic'):raise ValueError('Origen de ensayo no declarado')
    code=source_archive(release)
    if code.get('manifest_version')!=2:raise RuntimeError('Nuevo respaldo requiere release con procedencia explícita')
    baseline=fingerprint(source)
    if code['schema_version']!=baseline['schema']:raise RuntimeError('Aplicación y esquema del respaldo incompatibles')
    if code['provenance']['dirty'] and data_kind!='synthetic':raise RuntimeError('Código de trabajo sólo permitido para ensayo sintético')
    effective=effective_state(source)
    target=private_directory(target,source)
    src=read_only(source/'app.sqlite3');out=sqlite3.connect(target/'app.sqlite3')
    try:
        src.backup(out)
        out.execute('PRAGMA journal_mode=DELETE')
    finally:out.close();src.close()
    for obj in baseline['objects']+baseline.get('unregistered_objects',[]):
        destination=contained(target,obj['relative_path']);destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(contained(source,obj['relative_path']),destination)
    auxiliary={}
    for p in sorted(source.rglob('*')):
        relative=p.relative_to(source).as_posix()
        if relative.split('/')[0] in EXCLUDED:continue
        if p.is_symlink() or getattr(p,'is_junction',lambda:False)():raise RuntimeError('Enlace fuera del almacenamiento admitido')
        if p.is_file() and not relative.startswith('objects/'):
            destination=contained(target,relative);destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,destination)
            auxiliary[relative]={'sha256':digest(p),'byte_count':p.stat().st_size}
    shutil.copy2(release,target/'application.zip')
    if fingerprint(target)!=baseline or fingerprint(source)!=baseline:raise RuntimeError('El respaldo no representa un estado coherente; mantener origen detenido y revisar')
    acl_paths=sorted({p.relative_to(target).as_posix() for p in target.rglob('*') if p.name not in ('application.zip','app.sqlite3-wal','app.sqlite3-shm')})
    access=target/'access.json';dump(access,{'paths':acl_paths})
    if os.name=='nt':
        powershell('recovery_access.ps1','-Mode','Snapshot','-TargetRoot',source,'-Report',access)
        # The source has no application.zip/access.json/manifest. Only data ACLs
        # are replayed; application files inherit the private restore directory.
    else:access.write_text(json.dumps({'posix_private':True}),encoding='utf-8')
    manifest={'format':FORMAT,'snapshot_at':stamp(),'data_kind':data_kind,'source_root':str(source),'database_sha256':digest(target/'app.sqlite3'),
        'logical_state':baseline,'effective_state':effective,'auxiliary':auxiliary,'access_sha256':digest(access),
        'application':{'zip_sha256':digest(target/'application.zip'),'source_tree_sha256':code['source_tree_sha256'],
                       'files':len(code['files']),'schema':code['schema_version'],'provenance':code['provenance']},
        'runtime':{'python':sys.version,'packages':{d.metadata['Name']:d.version for d in importlib.metadata.distributions() if d.metadata['Name']}},
        'excluded':'Previous backups, temporary files, WAL/SHM and the initial plaintext password file. Password hashes/users/roles/history are in the database.'}
    dump(target/'manifest.json',manifest)
    return manifest,digest(target/'manifest.json')


def bundle_backup(backup,archive):
    backup,archive=Path(backup),Path(archive)
    if archive.exists():raise FileExistsError('No se reemplaza un archivo existente')
    with ZipFile(archive,'x',compression=ZIP_DEFLATED,compresslevel=6) as z:
        for path in sorted(backup.rglob('*')):
            if path.is_file() and path.name not in ('app.sqlite3-wal','app.sqlite3-shm'):z.write(path,path.relative_to(backup).as_posix())
    return digest(archive)


def restore_archive(archive,target,manifest_sha256,acl_source):
    archive,target=Path(archive),Path(target).resolve()
    if target.exists():raise FileExistsError('No se reemplaza un destino existente')
    with ZipFile(archive) as z:
        raw=z.read('manifest.json')
        if hashlib.sha256(raw).hexdigest()!=manifest_sha256:raise RuntimeError('Manifiesto de respaldo no coincide con la referencia')
        m=json.loads(raw)
        if m['format']!=FORMAT:raise RuntimeError('Formato de respaldo no admitido')
        objects={o['relative_path']:o for o in m['logical_state']['objects']+m['logical_state'].get('unregistered_objects',[])}
        expected={'app.sqlite3','manifest.json','access.json','application.zip'}|set(objects)|set(m['auxiliary'])
        if set(z.namelist())!=expected or len(z.namelist())!=len(expected):raise RuntimeError('Inventario de respaldo inconsistente')
        for name in expected:contained(target,name)
        target=private_directory(target,acl_source)
        dump(target/'RECOVERY_PENDING.json',{'format':FORMAT,'manifest_sha256':manifest_sha256})
        for name in sorted(expected):
            path=contained(target,name);path.parent.mkdir(parents=True,exist_ok=True)
            with z.open(name) as src,path.open('xb') as dst:shutil.copyfileobj(src,dst)
        if digest(target/'app.sqlite3')!=m['database_sha256'] or digest(target/'access.json')!=m['access_sha256'] or digest(target/'application.zip')!=m['application']['zip_sha256']:
            raise RuntimeError('Archivo de recuperación alterado; destino incompleto sin habilitar')
        for name,record in m['auxiliary'].items():
            if digest(contained(target,name))!=record['sha256']:raise RuntimeError('Archivo auxiliar alterado')
        if fingerprint(target)!=m['logical_state']:raise RuntimeError('No se recuperó el estado completo del respaldo')
        code=source_archive(target/'application.zip')
        if code['source_tree_sha256']!=m['application']['source_tree_sha256']:raise RuntimeError('Versión de aplicación diferente')
        if code['schema_version']!=m['logical_state']['schema'] or code['schema_version']!=m['application']['schema']:
            raise RuntimeError('Aplicación restaurada incompatible con la base')
        if code.get('manifest_version')==2:
            if code['provenance']!=m['application'].get('provenance'):raise RuntimeError('Procedencia de aplicación diferente')
        elif m['application'].get('provenance') is not None:raise RuntimeError('Procedencia legacy contradictoria')
        application=target/'application';application.mkdir()
        with ZipFile(target/'application.zip') as source:
            for name in source.namelist():
                p=contained(application,name);p.parent.mkdir(parents=True,exist_ok=True)
                with p.open('xb') as f:f.write(source.read(name))
        if os.name=='nt':powershell('recovery_access.ps1','-Mode','Apply','-TargetRoot',target,'-Report',target/'access.json')
        dump(target/'RECOVERY_READY.json',{'format':FORMAT,'manifest_sha256':manifest_sha256,'verified_at':stamp(),
            'workers_enabled':False,'sessions_require_revocation':True})
        return m


def activate_quarantined(root):
    root=Path(root)
    receipt=root/'RECOVERY_ACTIVATED.json'
    if receipt.exists():
        from app.recovery_guard import recovery_status
        recovery_status(root)
        return json.loads(receipt.read_text())
    ready=json.loads((root/'RECOVERY_READY.json').read_text())
    if digest(root/'manifest.json')!=ready['manifest_sha256']:raise RuntimeError('Recuperación sin referencia verificada')
    m=json.loads((root/'manifest.json').read_text())
    # A crash after the commit but before the receipt must be recoverable.
    conn=sqlite3.connect(root/'app.sqlite3')
    try:
        prior=conn.execute("SELECT occurred_at FROM audit_events WHERE action='recovery_sessions_revoked' AND entity_type='recovery' AND entity_id=? ORDER BY rowid DESC LIMIT 1",(ready['manifest_sha256'],)).fetchone()
        if prior:
            if conn.execute('SELECT count(*) FROM sessions').fetchone()[0]:
                raise RuntimeError('La activación interrumpida contiene sesiones inesperadas')
            count=m['logical_state']['tables']['sessions']['count'];activated_at=prior[0]
        else:
            if digest(root/'app.sqlite3')!=m['database_sha256']:raise RuntimeError('La copia dejó de ser prístina antes de activar')
            activated_at=stamp()
            conn.execute('BEGIN IMMEDIATE')
            count=conn.execute('SELECT count(*) FROM sessions').fetchone()[0]
            conn.execute('DELETE FROM sessions')
            conn.execute("INSERT INTO audit_events VALUES (?,NULL,'recovery_sessions_revoked','recovery',?,?)",(str(uuid4()),ready['manifest_sha256'],activated_at))
            conn.commit()
    finally:conn.close()
    result={'sessions_revoked':count,'workers_enabled':False,'activated_at':activated_at,'manifest_sha256':ready['manifest_sha256']}
    temporary=root/('.recovery-receipt-'+str(uuid4())+'.tmp')
    try:
        dump(temporary,result)
        os.replace(temporary,receipt)
    finally:
        temporary.unlink(missing_ok=True)
    return result

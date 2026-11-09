"""Build an explicit source release; never invent a clean commit for dirty bytes."""
import ast
import hashlib
import json
from pathlib import Path,PurePosixPath
import subprocess
from io import BytesIO
from zipfile import ZipFile,ZIP_DEFLATED


def declared_schema(content):
    tree=ast.parse(content)
    value=next(n.value for n in tree.body if isinstance(n,ast.AnnAssign) and getattr(n.target,'id',None)=='MIGRATIONS')
    versions=[n.elts[0].value for n in value.elts]
    if versions!=list(range(1,max(versions)+1)):raise ValueError('Invalid application migrations')
    return versions[-1]


def committed_contents(git,commit):
    entries=[]
    for record in git('ls-tree','-rz','--full-tree',commit).split(b'\0'):
        if not record:continue
        metadata,raw_name=record.split(b'\t',1)
        mode,kind,oid=metadata.split()
        name=raw_name.decode('utf-8');path=PurePosixPath(name)
        if (mode not in (b'100644',b'100755') or kind!=b'blob' or path.is_absolute()
                or '..' in path.parts or '\\' in name or ':' in name or name=='SOURCE_MANIFEST.json'):
            raise RuntimeError('Invalid committed release source path or type')
        entries.append((name,oid))
    # Read raw objects by OID. git archive applies checkout conversions (EOL,
    # filters, encoding and export attributes), even for an immutable commit.
    stream=BytesIO(git('cat-file','--batch',input=b''.join(oid+b'\n' for _,oid in entries)))
    contents={}
    for name,oid in entries:
        returned,kind,length=stream.readline().split();size=int(length)
        value=stream.read(size)
        if returned!=oid or kind!=b'blob' or len(value)!=size or stream.read(1)!=b'\n':
            raise RuntimeError('Invalid Git blob response')
        contents[name]=value
    if stream.read():raise RuntimeError('Unexpected Git blob data')
    return contents


def build_release(root,target,*,synthetic=False,commit=None):
    root,target=Path(root).resolve(),Path(target).resolve()
    def git(*args,input=None):return subprocess.check_output(['git','-C',str(root),*args],input=input)
    explicit=commit is not None
    if explicit and (len(commit)!=40 or any(c not in '0123456789abcdef' for c in commit)):raise ValueError('Expected an exact Git commit')
    commit=git('rev-parse',(commit if explicit else 'HEAD')+'^{commit}').decode().strip()
    dirty=False if explicit else bool(git('status','--porcelain','--untracked-files=normal'))
    if dirty and not synthetic:raise RuntimeError('Release requires a clean committed tree')
    if not dirty:
        contents=committed_contents(git,commit)
    else:
        names=set(git('ls-files','-z').decode().rstrip('\0').split('\0'))
        names.update(git('ls-files','--others','--exclude-standard','-z').decode().rstrip('\0').split('\0'));names.discard('')
        contents={}
        for name in sorted(names):
            path=root/name
            if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):raise RuntimeError('Invalid release source path')
            contents[name]=path.read_bytes()
    files={name:hashlib.sha256(value).hexdigest() for name,value in contents.items()}
    manifest={'kind':'source_review_snapshot','manifest_version':2,'files':files,
              'source_tree_sha256':hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
              'schema_version':declared_schema(contents['app/db.py']),
              'provenance':{'kind':'synthetic_working_tree' if dirty else 'git_commit',
                            'git_commit':commit,'dirty':dirty}}
    with ZipFile(target,'x',ZIP_DEFLATED) as archive:
        for name,value in contents.items():archive.writestr(name,value)
        archive.writestr('SOURCE_MANIFEST.json',json.dumps(manifest,sort_keys=True))
    return manifest

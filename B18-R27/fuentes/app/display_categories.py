"""Documentary classification of exact HPC invoice codes, independent of pricing."""
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile
import hashlib

from openpyxl import load_workbook

from .db import transaction
from .proposal_freshness import provider_basis
from .service import Problem, authorized_dataset, check_version, event, now_utc
from .storage import publish_bytes, read_verified


def _verify_cell(content,sheet,row,column,code):
    try:
        with ZipFile(BytesIO(content)) as archive:
            if sum(item.file_size for item in archive.infolist())>64*1024*1024:
                raise ValueError('Workbook too large')
            for item in archive.infolist():
                if item.filename.endswith(('.xml','.rels')):
                    xml=archive.read(item).upper()
                    if b'<!DOCTYPE' in xml or b'<!ENTITY' in xml:
                        raise ValueError('Unsupported XML')
        book=load_workbook(BytesIO(content),read_only=True,data_only=False,keep_links=False)
        try:
            cells=next(book[sheet].iter_rows(min_row=row,max_row=row,min_col=column,max_col=column),())
            if cells:
                cell=cells[0];value=cell.value
                if type(value) is int:
                    fmt=cell.number_format or 'General'
                    if fmt=='General':value=str(value)
                    elif set(fmt)=={'0'}:value=str(value).zfill(len(fmt))
                    else:value=None
                if isinstance(value,str) and cell.data_type!='f' and value==code:return
        finally:
            book.close()
    except Exception as exc:
        raise Problem(422,'No se pudo leer la hoja indicada del nomenclador XLSX.') from exc
    raise Problem(422,'La celda indicada no contiene el código completo de la prestación.')


def add_categories(conn,root,dataset_id,batch,areas):
    if conn.execute('PRAGMA user_version').fetchone()[0]<32:return
    basis=provider_basis(conn,batch['batch_id'])
    if not basis or basis['provider']!='HPC':return
    closed_version=None
    if batch['state']=='cerrada':
        closure=conn.execute('SELECT json_extract(manifest_json,?) AS version FROM revision_closures WHERE revision_id=?',('$.dataset.version',batch['revision_id'])).fetchone()
        if not closure:return
        closed_version=closure['version']
        if closed_version is None:return
    verified={}
    history='hpc_category_history' if conn.execute('PRAGMA user_version').fetchone()[0]>=33 else 'hpc_display_categories'
    cutoff=' AND dataset_version<=?' if closed_version is not None else ''
    params=(dataset_id,closed_version) if closed_version is not None else (dataset_id,)
    for row in conn.execute(f'SELECT h.*,u.username FROM {history} h JOIN users u ON u.id=h.actor_id '
                            f'JOIN (SELECT code,max(dataset_version) AS latest FROM {history} WHERE dataset_id=?{cutoff} GROUP BY code) g '
                            'ON h.code=g.code AND h.dataset_version=g.latest WHERE h.dataset_id=?',(*params,dataset_id)):
        sha=row['source_sha256']
        if sha not in verified:
            try:
                read_verified(root,sha)
                verified[sha]=True
            except (ValueError,RuntimeError,OSError):
                verified[sha]=False
        if not verified[sha]:
            areas.invalid_codes.add(row['code'])
        area='Imágenes' if row['family']=='images' else 'Otras prácticas'
        if verified[sha]:areas[row['code']].add(area)
        areas.origins[row['code']].append({'kind':'registered_hpc_category','area':area,'source_id':sha,
            'source_sha256':sha,'source_file':row['source_file'],'sheet':row['sheet'],'source_row':row['source_row'],
            'source_column':row['source_column'],'actor':row['username'],'created_at':row['created_at'],'ordinal':row['ordinal'] if 'ordinal' in row.keys() else 1})


def save_category(conn,root,token,dataset_id,batch_id,number,*,version,revision,code,family,sheet,evidence_row,evidence_column,filename,content,previous=None,reason=None):
    from .practice_families import catalog_families,classify_family
    _,dataset=authorized_dataset(conn,token,dataset_id,'reviewer')
    check_version(dataset,version)
    if (family not in ('images','other') or not code or len(code)>100 or not sheet or len(sheet)>31
            or not 1<=evidence_column<=16384 or not 1<=evidence_row<=1048576 or not filename.lower().endswith('.xlsx') or len(filename)>255
            or Path(filename).name!=filename or any(ord(c)<32 for c in filename+sheet+code)):
        raise Problem(422,'Revisá el código, la categoría y el localizador del XLSX.')
    if conn.execute('SELECT 1 FROM batches WHERE dataset_id=? AND source_sha256=?',
                    (dataset_id,hashlib.sha256(content).hexdigest())).fetchone():
        raise Problem(422,'Seleccioná el nomenclador de respaldo. Ese archivo es una factura del conjunto.')
    _verify_cell(content,sheet,evidence_row,evidence_column,code)
    with transaction(conn):
        user,dataset=authorized_dataset(conn,token,dataset_id,'reviewer')
        check_version(dataset,version)
        from .practice_requests import row_context
        batch,_,fields=row_context(conn,dataset_id,batch_id,number)
        if batch['state']=='cerrada' or batch['revision_version']!=revision:
            raise Problem(409,'Se requiere una revisión abierta y actual.')
        if fields.get('E')!=code:raise Problem(409,'Cambió el código de la fila. Actualizá la bandeja.')
        last=conn.execute('SELECT family,ordinal FROM hpc_category_history WHERE dataset_id=? AND code=? ORDER BY ordinal DESC LIMIT 1',(dataset_id,code)).fetchone()
        if previous is None and last:
            raise Problem(409,'Este código ya tiene una categoría registrada. Actualizá la bandeja.')
        if previous is not None:
            if not last or last['ordinal']!=previous:raise Problem(409,'Cambió la categoría. Consultá la historia.')
            if not reason or not 10<=len(reason.strip())<=2000:raise Problem(422,'Indicá el motivo del cambio (10 a 2000 caracteres).')
            if last['family']==family:raise Problem(422,'Elegí una categoría distinta para corregirla.')
        areas,names,meta=catalog_families(conn,root,dataset_id)
        _,why=classify_family(code,areas,fields.get('K'),names)
        if meta['source_unavailable'] or (previous is None and why!='not_found_in_catalog'):
            raise Problem(409,'Una fuente ya clasifica la práctica, presenta un conflicto o no se pudo verificar.')
        published=publish_bytes(root,content)
        conn.execute('INSERT OR IGNORE INTO stored_files VALUES (?,?,?,?)',(*published,now_utc()))
        registered=conn.execute('SELECT byte_count,relative_path FROM stored_files WHERE sha256=?',(published[0],)).fetchone()
        if tuple(registered)!=published[1:]:raise Problem(409,'El respaldo registrado tiene metadatos inconsistentes.')
        entry=(dataset_id,code,family,fields.get('K') or '',batch_id,batch['revision_id'],number,published[0],
               filename,sheet,evidence_row,evidence_column,user['id'],now_utc(),version+1)
        if previous is None:
            conn.execute('INSERT INTO hpc_display_categories VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',entry)
        else:
            conn.execute('INSERT INTO hpc_category_corrections VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                         (*entry,previous+1,reason.strip()))
        conn.execute('UPDATE datasets SET version=version+1 WHERE id=?',(dataset_id,))
        event(conn,user['id'],'hpc_display_category_corrected' if previous is not None else 'hpc_display_category_recorded','invoice_batch',batch_id)
    return {'code':code,'family':family,'source_sha256':published[0],'dataset_version':version+1}

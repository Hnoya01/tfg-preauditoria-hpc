"""Documented local HPC identities. No catalog mutation or inferred equivalence."""
from datetime import date
from decimal import Decimal
import json,re
from uuid import uuid4
from .db import transaction
from .consistent_reads import consistent_read
from .security import now_utc
from .service import Problem,authorized_dataset,check_version,event
from .storage import read_verified


def available(conn):
    return conn.execute('PRAGMA user_version').fetchone()[0]>=29


def practices(conn,dataset_id,source_id):
    if not available(conn):return []
    return [dict(r) for r in conn.execute('SELECT * FROM local_hpc_practices WHERE dataset_id=? AND source_id=? ORDER BY code,id',(dataset_id,source_id))]


def tariffs(conn,dataset_id,source_id):
    return [{'seq':None,'local_id':p['id'],'id':p['id'],'provider':'HPC','code':p['code'],
             'practice_id':p['id'],'description':p['description'],'family':p['family'],
             'amount_cents':None,'valid_from':None,'valid_until':None,'data_json':'{}',
             'source_locator':f"local_hpc_practices.id={p['id']}",'source_id':source_id,'page':None}
            for p in practices(conn,dataset_id,source_id)]


def save(conn,root,token,dataset_id,source_id,*,expected_dataset_version,code,description,family,
         amount_ars,currency,unit_label,active,effective_from,document_id,page_number,excerpt,reason,practice_id=None):
    if (not isinstance(code,str) or not code or code!=code.strip() or len(code)>64 or '\x00' in code
        or not isinstance(description,str) or not 3<=len(description.strip())<=300 or '\x00' in description
        or family not in ('images','other','unclassified') or currency!='ARS' or type(active) is not bool
        or not isinstance(unit_label,str) or not 2<=len(unit_label.strip())<=100 or '\x00' in unit_label
        or type(page_number) is not int or not 1<=page_number<=10000
        or any(not isinstance(v,str) or not 10<=len(v.strip())<=2000 or '\x00' in v for v in (excerpt,reason))):
        raise Problem(422,'Identidad, moneda, unidad o respaldo de la práctica inválidos')
    if not isinstance(amount_ars,str) or not re.fullmatch(r'(?:0|[1-9][0-9]{0,11})\.[0-9]{2}',amount_ars) or Decimal(amount_ars)<=0:
        raise Problem(422,'Importe ARS positivo con dos decimales requerido')
    try:
        if date.fromisoformat(effective_from).isoformat()!=effective_from:raise ValueError()
    except (TypeError,ValueError):raise Problem(422,'Fecha inválida') from None
    with transaction(conn):
        actor,dataset=authorized_dataset(conn,token,dataset_id,'admin');check_version(dataset,expected_dataset_version)
        source=conn.execute("SELECT source_sha256 FROM source_registry WHERE id=? AND dataset_id=? AND kind='values' AND status='registered'",(source_id,dataset_id)).fetchone()
        if source is None:raise Problem(404,'Fuente de valores inexistente')
        doc=conn.execute("SELECT sha256 FROM evidence_documents WHERE id=? AND dataset_id=? AND source_id=? AND category='agreement'",(document_id,dataset_id,source_id)).fetchone()
        if doc is None:raise Problem(422,'Seleccioná PDF de convenio para esta fuente')
        try:read_verified(root,source['source_sha256']);read_verified(root,doc['sha256'])
        except (OSError,RuntimeError) as exc:raise Problem(409,'No se pudo verificar el respaldo') from exc
        old=None
        if practice_id:
            p=conn.execute('SELECT * FROM local_hpc_practices WHERE id=? AND dataset_id=? AND source_id=?',(practice_id,dataset_id,source_id)).fetchone()
            if p is None:raise Problem(404,'Práctica propia inexistente')
            if (p['code'],p['description'],p['family'])!=(code,description.strip(),family):raise Problem(422,'La identidad es inmutable; no cambiar código, descripción ni familia')
            old=conn.execute('SELECT * FROM local_hpc_versions WHERE practice_id=? ORDER BY ordinal DESC LIMIT 1',(practice_id,)).fetchone()
            if old and effective_from<old['effective_from']:raise Problem(409,'La fecha antecede a la última versión')
        else:
            if not active:raise Problem(422,'El alta inicial debe estar activa')
            if conn.execute('SELECT 1 FROM local_hpc_practices WHERE dataset_id=? AND source_id=? AND code=?',(dataset_id,source_id,code)).fetchone():raise Problem(409,'El código propio ya existe; abrir su historia')
            practice_id=str(uuid4())
            conn.execute('INSERT INTO local_hpc_practices VALUES (?,?,?,?,?,?,?,?)',(practice_id,dataset_id,source_id,code,description.strip(),family,actor['id'],now_utc()))
        identifier,ordinal=_insert_version(conn,actor['id'],practice_id,amount_ars=amount_ars,
            unit_label=unit_label,active=active,effective_from=effective_from,document_id=document_id,
            document_sha256=doc['sha256'],page_number=page_number,excerpt=excerpt,reason=reason)
        conn.execute('UPDATE datasets SET version=version+1 WHERE id=?',(dataset_id,));event(conn,actor['id'],'local_hpc_version_recorded','local_hpc_practice',practice_id)
    return {'id':practice_id,'version_id':identifier,'ordinal':ordinal,'dataset_version':expected_dataset_version+1,'use_limit':'Referencia documentada por operador; no confirma aplicabilidad por fila ni ejecuta controles.'}


def listing(conn,token,dataset_id,source_id,query=None):
    return consistent_read(conn,token,dataset_id,lambda:_listing(conn,token,dataset_id,source_id,query))


def _listing(conn,token,dataset_id,source_id,query=None):
    authorized_dataset(conn,token,dataset_id,'reviewer')
    result=[]
    for p in practices(conn,dataset_id,source_id):
        if query is not None and query not in (p['code'],p['description']):continue
        p['versions']=[dict(r) for r in conn.execute('SELECT v.*,u.username AS actor_username FROM local_hpc_versions v JOIN users u ON u.id=v.actor_id WHERE practice_id=? ORDER BY ordinal',(p['id'],))]
        result.append(p)
    return result


def export_history(conn,dataset_id):
    if not available(conn):return []
    result=[]
    for source in conn.execute("SELECT id FROM source_registry WHERE dataset_id=? AND kind='values' ORDER BY id",(dataset_id,)):
        for p in practices(conn,dataset_id,source['id']):
            p['versions']=[dict(r) for r in conn.execute('SELECT * FROM local_hpc_versions WHERE practice_id=? ORDER BY ordinal',(p['id'],))]
            result.append(p)
    return result


def _insert_version(conn,actor_id,practice_id,*,amount_ars,unit_label,active,effective_from,
                    document_id,document_sha256,page_number,excerpt,reason):
    """Validated insertion shared by individual and atomic mixed batch writes."""
    if not conn.in_transaction:raise RuntimeError('Native insertion requires an owned transaction')
    old=conn.execute('SELECT id,ordinal,effective_from FROM local_hpc_versions WHERE practice_id=? ORDER BY ordinal DESC LIMIT 1',(practice_id,)).fetchone()
    if old and effective_from<old['effective_from']:raise Problem(409,'La fecha antecede a la última versión')
    identifier=str(uuid4());ordinal=old['ordinal']+1 if old else 1
    conn.execute('INSERT INTO local_hpc_versions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (identifier,practice_id,ordinal,old['id'] if old else None,amount_ars,unit_label.strip(),int(active),
         effective_from,document_id,document_sha256,page_number,excerpt.strip(),reason.strip(),actor_id,now_utc()))
    return identifier,ordinal

"""Source-level evidence; never creates row applicability or monetary decisions."""
import hashlib
import json
from datetime import date
from uuid import uuid4
from .db import transaction
from .economic_evidence import _registered_values
from .security import now_utc
from .service import Problem, authorized_dataset, check_version, event
from .storage import read_verified
from .values_v1 import source_db


def dump(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)


def sha(value):
    return hashlib.sha256(dump(value).encode()).hexdigest()


def history(conn, token, dataset_id, source_id):
    _,dataset=authorized_dataset(conn,token,dataset_id,'reviewer')
    _registered_values(conn,dataset_id,source_id)
    return {'dataset_version':dataset['version'],'history':export_history(conn,dataset_id,source_id)}


def export_history(conn,dataset_id,source_id=None):
    if conn.execute('PRAGMA user_version').fetchone()[0]<30:return []
    rows=conn.execute('SELECT d.*,w.reason AS withdrawal_reason,w.actor_id AS withdrawn_by,w.created_at AS withdrawn_at FROM agreement_declarations d LEFT JOIN agreement_declaration_withdrawals w ON w.declaration_id=d.id WHERE d.dataset_id=?'+(' AND d.source_id=?' if source_id else '')+' ORDER BY d.created_at,d.id',(dataset_id,source_id) if source_id else (dataset_id,))
    return [{**dict(r),'declaration':json.loads(r['payload_json'])} for r in rows]


def _prepare(conn,root,dataset_id,source_id,*,tariff_seqs,document_id,currency,unit_label,valid_from,valid_until,page_number,excerpt,conditions_note,reason,replaces_id=None,**unused):
    if currency!='ARS' or unit_label!='por práctica':raise Problem(422,'Declarar expresamente ARS y por práctica; no se infieren')
    try:
        if date.fromisoformat(valid_from).isoformat()!=valid_from:raise ValueError()
        if valid_until and (date.fromisoformat(valid_until).isoformat()!=valid_until or valid_until<valid_from):raise ValueError()
    except (ValueError,TypeError):raise Problem(422,'Vigencia inválida')
    if not tariff_seqs or len(tariff_seqs)>5000 or any(type(x) is not int for x in tariff_seqs) or len(set(tariff_seqs))!=len(tariff_seqs):raise Problem(422,'Seleccioná tarifas explícitas sin repeticiones')
    if type(page_number) is not int or not 1<=page_number<=100000 or not 20<=len(excerpt.strip())<=4000 or not 20<=len(conditions_note.strip())<=2000 or not 10<=len(reason.strip())<=2000:raise Problem(422,'Página, extracto, condiciones y fundamento obligatorios')
    source=_registered_values(conn,dataset_id,source_id)
    doc=conn.execute("SELECT * FROM evidence_documents WHERE id=? AND dataset_id=? AND source_id=? AND category='agreement'",(document_id,dataset_id,source_id)).fetchone()
    if not doc:raise Problem(422,'Convenio registrado de esta fuente requerido')
    try:
        read_verified(root,doc['sha256'])
        catalog=source_db(read_verified(root,source['source_sha256']))
        try:
            rows=[dict(r) for r in catalog.execute("SELECT * FROM hpc_catalog_tariffs WHERE provider='HPC'")]
            byseq={r['seq']:r for r in rows}
            if len(byseq)!=len(rows):raise Problem(422,'Identidad de tarifa duplicada en catálogo')
            selected=[]
            for seq in sorted(tariff_seqs):
                t=byseq.get(seq)
                if not t or type(t['amount_cents']) is not int or t['amount_cents']<0:raise Problem(422,'Tarifa inexistente o importe no interpretable')
                metadata=json.loads(t.get('data_json') or '{}')
                if not isinstance(metadata,dict):raise Problem(422,'Metadatos de tarifa no interpretables')
                calculation=metadata.get('calculation') or {}
                if not isinstance(calculation,dict) or calculation.get('kind') not in (None,'fixed','flat') or calculation.get('reviewRequired') is True or metadata.get('reviewRequired') is True or any(metadata.get(k) for k in ('specific_norm','specificNorm','special_norm','specialNorm')):
                    raise Problem(422,'Tarifa con cálculo o condiciones especiales: requiere respaldo específico; no se acredita globalmente')
                selected.append({k:t.get(k) for k in ('seq','code','practice_id','amount_cents','valid_from','valid_until','source_id','page')})
        finally:catalog.close()
    except (OSError,RuntimeError,ValueError) as exc:raise Problem(409,'Original o PDF no verificable') from exc
    records=export_history(conn,dataset_id,source_id)
    indexed={r['id']:r for r in records}
    replacing=set()
    if replaces_id:
        prior=indexed.get(replaces_id)
        if not prior:raise Problem(422,'Declaración reemplazada inexistente')
        previous_seqs={t['seq'] for t in prior['declaration']['tariffs']}
        chosen=set(tariff_seqs)
        if (not prior['withdrawn_at'] and chosen!=previous_seqs) or not chosen<=previous_seqs:
            raise Problem(422,'Activa: conservar conjunto exacto. Retirada: sólo subconjunto explícito, sin agregar tarifas')
        ancestor=replaces_id
        while ancestor and ancestor not in replacing:
            replacing.add(ancestor)
            ancestor=indexed.get(ancestor,{}).get('declaration',{}).get('replaces_id')
    for old in records:
        if old['id'] in replacing:continue
        if valid_from <= (old['valid_until'] or '9999-12-31') and old['valid_from'] <= (valid_until or '9999-12-31'):
            if set(tariff_seqs)&{t['seq'] for t in old['declaration']['tariffs']}:
                raise Problem(409,'Superposición: enlazá explícitamente la declaración anterior, incluso si fue retirada, mediante replaces_id')
    payload={'source_sha256':source['source_sha256'],'document_id':document_id,'document_sha256':doc['sha256'],'currency':currency,'unit_label':unit_label,'valid_from':valid_from,'valid_until':valid_until,'page_number':page_number,'excerpt':excerpt.strip(),'conditions_note':conditions_note.strip(),'reason':reason.strip(),'tariffs':selected,'replaces_id':replaces_id,'limit':'Respaldo declarado por administrador; sólo comparación exploratoria, no equivalencia clínica ni débito.'}
    return payload


def preview(conn,root,token,dataset_id,source_id,expected_dataset_version,**body):
    _,dataset=authorized_dataset(conn,token,dataset_id,'admin');check_version(dataset,expected_dataset_version)
    p=_prepare(conn,root,dataset_id,source_id,**body)
    return {'declaration':p,'preview_sha256':sha(p),'count':len(p['tariffs']),'dataset_version':dataset['version']}


def save(conn,root,token,dataset_id,source_id,expected_dataset_version,preview_sha256,**body):
    with transaction(conn):
        user,dataset=authorized_dataset(conn,token,dataset_id,'admin')
        for old in export_history(conn,dataset_id,source_id):
            prior=old['declaration']
            same=(old['payload_sha256']==preview_sha256 and not old['withdrawn_at']
                  and set(body.get('tariff_seqs',[]))=={t['seq'] for t in prior['tariffs']}
                  and all(body.get(k)==prior.get(k) for k in ('document_id','currency','unit_label','valid_from','valid_until','page_number','excerpt','conditions_note','reason','replaces_id')))
            if same:return {'id':old['id'],'dataset_version':dataset['version'],'count':len(prior['tariffs']),'created':False}
        check_version(dataset,expected_dataset_version)
        p=_prepare(conn,root,dataset_id,source_id,**body)
        if sha(p)!=preview_sha256:raise Problem(409,'La previsualización cambió')
        identity=str(uuid4());stamp=now_utc()
        if p['replaces_id'] and not conn.execute('SELECT 1 FROM agreement_declaration_withdrawals WHERE declaration_id=?',(p['replaces_id'],)).fetchone():
            conn.execute('INSERT INTO agreement_declaration_withdrawals VALUES(?,?,?,?)',(p['replaces_id'],'Reemplazada: '+p['reason'],user['id'],stamp))
        conn.execute('INSERT INTO agreement_declarations VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(identity,dataset_id,source_id,p['source_sha256'],p['document_id'],p['document_sha256'],p['valid_from'],p['valid_until'],dump(p),sha(p),user['id'],stamp))
        conn.execute('UPDATE datasets SET version=version+1 WHERE id=?',(dataset_id,));event(conn,user['id'],'agreement_declaration_saved','agreement_declaration',identity)
    return {'id':identity,'dataset_version':expected_dataset_version+1,'count':len(p['tariffs'])}


def withdraw(conn,token,dataset_id,source_id,declaration_id,expected_dataset_version,reason):
    if not 10<=len(reason.strip())<=2000:raise Problem(422,'Fundamento de retiro obligatorio')
    with transaction(conn):
        user,dataset=authorized_dataset(conn,token,dataset_id,'admin');check_version(dataset,expected_dataset_version)
        if not conn.execute('SELECT 1 FROM agreement_declarations WHERE id=? AND dataset_id=? AND source_id=?',(declaration_id,dataset_id,source_id)).fetchone():raise Problem(404,'Declaración inexistente')
        if conn.execute('SELECT 1 FROM agreement_declaration_withdrawals WHERE declaration_id=?',(declaration_id,)).fetchone():return {'dataset_version':dataset['version'],'created':False}
        conn.execute('INSERT INTO agreement_declaration_withdrawals VALUES(?,?,?,?)',(declaration_id,reason.strip(),user['id'],now_utc()))
        conn.execute('UPDATE datasets SET version=version+1 WHERE id=?',(dataset_id,));event(conn,user['id'],'agreement_declaration_withdrawn','agreement_declaration',declaration_id)
    return {'dataset_version':expected_dataset_version+1,'created':True}


class ExploratoryResolver:
    """Decorator used ONLY by exploratory UI; authoritative resolver stays unchanged."""
    def __init__(self,resolver,source_sha256):
        self.base=resolver;self.source_sha256=source_sha256
        self.records=export_history(resolver.conn,resolver.dataset_id,resolver.source_id)
        self.verified={}
    def resolve(self,tariff,performed_on):
        effective=self.base.resolve(tariff,performed_on)
        if effective['status']!='catalogue_candidate':return effective
        matched=[]
        for record in self.records:
            p=record['declaration']
            if p['source_sha256']!=self.source_sha256:continue
            if not (p['valid_from']<=performed_on and (not p['valid_until'] or performed_on<=p['valid_until'])):continue
            entries=[t for t in p['tariffs'] if t['seq']==tariff['seq']]
            if entries:matched.append((record,entries[0]))
        if not matched:return effective
        # Withdrawn declarations remain visible blockers, unless explicitly replaced.
        replaced=set()
        indexed={r['id']:r for r in self.records}
        for record,_ in matched:
            ancestor=record['declaration'].get('replaces_id')
            while ancestor and ancestor not in replaced:
                previous=indexed.get(ancestor)
                if not previous or not any(t['seq']==tariff['seq'] for t in previous['declaration']['tariffs']):break
                replaced.add(ancestor)
                ancestor=previous['declaration'].get('replaces_id')
        matched=[(r,t) for r,t in matched if r['id'] not in replaced]
        if len(matched)!=1:return {**effective,'status':'agreement_declaration_ambiguous'}
        r,t=matched[0];p=r['declaration']
        result={**effective,'agreement_declaration':{'id':r['id'],'payload_sha256':r['payload_sha256'],**p}}
        if r['withdrawn_at']:return {**result,'status':'agreement_declaration_withdrawn'}
        if sha(p)!=r['payload_sha256'] or any(t.get(k)!=tariff.get(k) for k in ('seq','code','practice_id','amount_cents','valid_from','valid_until')):
            return {**result,'status':'agreement_declaration_identity_mismatch'}
        if r['id'] not in self.verified:
            doc=self.base.conn.execute("SELECT sha256 FROM evidence_documents WHERE id=? AND dataset_id=? AND source_id=? AND category='agreement'",(r['document_id'],self.base.dataset_id,self.base.source_id)).fetchone()
            valid=bool(doc and doc['sha256']==r['document_sha256'])
            if valid:
                try:read_verified(self.base.root,r['document_sha256'])
                except (OSError,RuntimeError):valid=False
            self.verified[r['id']]=valid
        if not self.verified[r['id']]:return {**result,'status':'agreement_declaration_evidence_unverifiable'}
        return {**result,'status':'documented_agreement_candidate','declared_currency':p['currency'],'declared_unit':p['unit_label']}

"""B04 reproducible authorization controls; real unvalidated sources stay open."""
from .revision_scope import revision_table

from collections import defaultdict, deque
from threading import Lock
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from .authorization_assessment import applicable_resolution, compare_time, quantity
from .authorization_matching import _batch, _context, _hash, _index, _row_evidence, dni
from .eligibility import effective_row
from .storage import read_verified


VERSION = 'B04-authorizations-v1'
RULES = ('RN09', 'RN10', 'RN11', 'RN18')


def data_root(conn):
    return Path(next(r['file'] for r in conn.execute('PRAGMA database_list') if r['name']=='main')).parent


def synthetic_batch(conn, batch_id):
    if conn.execute('PRAGMA user_version').fetchone()[0]<15:return False
    return conn.execute("SELECT 1 FROM authorization_match_scopes WHERE batch_id=? AND mode='synthetic_demo' LIMIT 1",(batch_id,)).fetchone() is not None


def _latest(conn, table, import_id):
    kinds=',kind' if table=='authorization_input_versions' else ''
    extra=' AND x.kind=h.kind' if kinds else ''
    table = revision_table(conn, table)
    return [dict(r) for r in conn.execute(f'SELECT * FROM {table} h WHERE import_id=? AND ordinal='
        f'(SELECT max(ordinal) FROM {table} x WHERE x.import_id=h.import_id AND x.source_row=h.source_row{extra}) '
        f'ORDER BY source_row{kinds}', (import_id,))]


def _scope_basis(conn, batch_id, verified):
    row=conn.execute(f'SELECT * FROM {revision_table(conn, "authorization_match_scopes")} WHERE batch_id=? ORDER BY ordinal DESC LIMIT 1',(batch_id,)).fetchone()
    if not row:return None
    result={'id':row['id'],'mode':row['mode'],'captures':[]}
    root=data_root(conn)
    for identity in json.loads(row['capture_ids_json']):
        c=conn.execute('SELECT c.id,c.source_system,c.stream_id,c.data_origin,c.canonical_json,u.source_sha256,s.manifest_sha256,s.status '
            'FROM authorization_captures c JOIN authorization_uploads u ON u.id=c.upload_id '
            'JOIN source_registry s ON s.id=c.source_registry_id WHERE c.id=? AND c.dataset_id=?',(identity,row['dataset_id'])).fetchone()
        if not c:
            result['captures'].append({'id':identity,'missing':True});continue
        head=conn.execute('SELECT id FROM authorization_captures WHERE dataset_id=? AND source_system=? AND stream_id=? ORDER BY ordinal DESC LIMIT 1',
            (row['dataset_id'],c['source_system'],c['stream_id'])).fetchone()
        integrity=True
        for sha in (c['source_sha256'],c['manifest_sha256']):
            if sha not in verified:
                try:read_verified(root,sha);verified[sha]=True
                except (OSError,ValueError,RuntimeError):verified[sha]=False
            integrity=integrity and verified[sha]
        result['captures'].append({'id':identity,'head_id':head['id'] if head else None,'data_origin':c['data_origin'],
            'source_sha256':c['source_sha256'],'manifest_sha256':c['manifest_sha256'],'status':c['status'],
            'canonical_sha256':hashlib.sha256(c['canonical_json'].encode()).hexdigest(),'originals_verified':integrity})
    result['captures'].sort(key=lambda x:x['id'])
    return result


class Facts:
    """One coherent representation per current invoice import, with private keys in memory only."""
    def __init__(self,conn,dataset_id,target_batch,checkpoint=None,*,scopes=None):
        self.conn,self.dataset_id,self.root=conn,dataset_id,data_root(conn)
        self.target=_batch(conn,dataset_id,target_batch)
        self.batches={};self.rows={};self.groups=defaultdict(list);self.unknown=defaultdict(list)
        self.target_scope=(scopes[target_batch] if scopes is not None else
                           _scope_basis(conn,target_batch,{}) if conn.execute('PRAGMA user_version').fetchone()[0]>=18 else None)
        if not self.target_scope:return
        verified={}
        for item in conn.execute(f'SELECT i.batch_id,b.original_name FROM {revision_table(conn, "invoice_imports")} i JOIN batches b ON b.id=i.batch_id WHERE b.dataset_id=? ORDER BY i.id',(dataset_id,)):
            batch=_batch(conn,dataset_id,item['batch_id'])
            batch.update(batch_id=item['batch_id'],original_name=item['original_name'])
            scope=scopes[item['batch_id']] if scopes is not None else _scope_basis(conn,item['batch_id'],verified)
            links={r['source_row']:r for r in _latest(conn,'authorization_link_versions',batch['import_id'])}
            inputs={(r['source_row'],r['kind']):r for r in _latest(conn,'authorization_input_versions',batch['import_id'])}
            work=defaultdict(dict)
            for w in conn.execute('SELECT source_row,field,value_json,latest_change_id FROM work_fields WHERE import_id=?',(batch['import_id'],)):
                work[w['source_row']][w['field']]=(json.loads(w['value_json']),w['latest_change_id'])
            self.batches[batch['import_id']]={'batch':batch,'scope':scope}
            for pos,original in enumerate(conn.execute('SELECT * FROM invoice_rows WHERE import_id=? ORDER BY source_row',(batch['import_id'],)),1):
                if checkpoint and pos%250==0:checkpoint()
                fields=json.loads(original['permitted_json'])
                row=effective_row(original,batch['period'],fields=fields)
                if row['disposition']!='included':continue
                number=row['source_row']
                fields.update({k:v[0] for k,v in work[number].items()})
                affiliate,code=dni(fields.get('C')),fields.get('E')
                key=(affiliate,code,row['practice_date'])
                identity=(batch['import_id'],number)
                link=links.get(number)
                own={'import_id':batch['import_id'],'source_row':number,'invoice_sha256':batch['source_sha256'],
                     'period':batch['period'],'revision_id':batch['revision_id'],'practice_date':row['practice_date'],
                     'fields':{k:fields.get(k) for k in ('C','E','K')},'scope':scope,
                     'link_id':link['id'] if link else None}
                own_hash=_hash(own)
                bases={'RN09':own_hash,'RN18':own_hash}
                incorporation=inputs.get((number,'incorporation'));unit=inputs.get((number,'quantity_unit'))
                bases['RN10']=_hash([bases['RN09'],incorporation['id'] if incorporation else None])
                local=_hash([bases['RN09'],fields.get('G'),unit['id'] if unit else None])
                fact={'identity':identity,'row':row,'fields':fields,'key':key,'batch':batch,'scope':scope,'link':link,
                      'incorporation':incorporation,'quantity_unit':unit,'bases':bases,'quantity_local':local,
                      'work_change_ids':{k:v[1] for k,v in work[number].items() if k in ('C','E','K','G')}}
                self.rows[identity]=fact
                if affiliate and isinstance(code,str) and code:self.groups[key].append(fact)
                elif isinstance(code,str) and code:self.unknown[(code,row['practice_date'])].append(fact)

    def peers(self,fact):
        key=fact['key']
        return self.groups.get(key,[])+self.unknown.get((key[1],key[2]),[]) if key[0] and key[1] else [fact]

    def snapshot(self):
        rows={};cohorts={};participants={}
        cache={}
        for (import_id,number),fact in self.rows.items():
            if import_id!=self.target['import_id']:continue
            cohort=_hash(fact['key'])
            if cohort not in cache:
                members=sorted(self.peers(fact),key=lambda f:f['identity'])
                records=[{'import_id':f['identity'][0],'source_row':f['identity'][1],'basis_sha256':f['quantity_local'],
                    'link_id':f['link']['id'] if f['link'] else None,
                    'unit_input_id':f['quantity_unit']['id'] if f['quantity_unit'] else None,
                    'work_change_ids':f['work_change_ids'],'billed_quantity':f['fields'].get('G')} for f in members]
                cache[cohort]=_hash(records)
                cohorts[cohort]=records
                for f in members:
                    b=f['batch'];participants[b['import_id']]={'batch_id':b['batch_id'],'import_id':b['import_id'],
                        'revision_id':b['revision_id'],'revision_state':b['state'],'period':b['period'],
                        'source_sha256':b['source_sha256'],'scope':f['scope']}
            rows[str(number)]={**fact['bases'],'RN11':_hash([fact['quantity_local'],cache[cohort]])}
        return {'version':VERSION,'scope':self.target_scope,'rows':rows,'cohorts':cohorts,
                'participants':[participants[k] for k in sorted(participants)]}


# Keep only proofs of equality to a persisted analysis, never its rows or patient data.
_verified_bases = deque(maxlen=32)
_bases_lock = Lock()


def _inputs_digest(conn, dataset_id, batch_id):
    digest = hashlib.sha256()
    def add(value):
        encoded = json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=True).encode()
        digest.update(len(encoded).to_bytes(8, 'big'))
        digest.update(encoded)

    add([VERSION, dataset_id, batch_id])
    scopes = {}
    verified = {}
    imports = revision_table(conn, 'invoice_imports')
    for item in conn.execute(f'SELECT i.batch_id FROM {imports} i JOIN batches b ON b.id=i.batch_id '
                             'WHERE b.dataset_id=? ORDER BY i.id',(dataset_id,)):
        current_id = item['batch_id']
        batch = _batch(conn,dataset_id,current_id)
        # Human decisions can increment the revision version without changing Facts.
        add([current_id, batch['import_id'], batch['period'], batch['revision_id'], batch['state'], batch['source_sha256']])
        scopes[current_id] = _scope_basis(conn,current_id,verified)
        add(scopes[current_id])
        import_id = batch['import_id']
        for table in ('authorization_link_versions','authorization_input_versions'):
            add(_latest(conn,table,import_id))
        add([tuple(r) for r in conn.execute('SELECT source_row,field,value_json,latest_change_id FROM work_fields '
                                           'WHERE import_id=? ORDER BY source_row,field',(import_id,))])
        # Stream the actual originals too. A changed row, peer or noneligible row must miss.
        for n,day,fields in conn.execute('SELECT source_row,practice_date,permitted_json FROM invoice_rows '
                                       'WHERE import_id=? ORDER BY source_row',(import_id,)):
            raw=fields.encode()
            digest.update(n.to_bytes(8,'big'))
            date_bytes=(day or '').encode()
            digest.update(len(date_bytes).to_bytes(4,'big'))
            digest.update(date_bytes)
            digest.update(len(raw).to_bytes(8,'big'))
            digest.update(raw)
    return digest.digest(), scopes


def verified_dependency_snapshot(conn,dataset_id,batch_id,stored,stored_digest):
    if not conn.in_transaction or not stored or not stored.get('scope') or conn.execute('PRAGMA user_version').fetchone()[0]<18:
        return dependency_snapshot(conn,dataset_id,batch_id)
    inputs, scopes = _inputs_digest(conn,dataset_id,batch_id)
    signature=inputs.hex()
    if stored_digest and stored.get('input_proof_v1')==signature:
        return stored
    key = (stored_digest, inputs)
    with _bases_lock:
        if key in _verified_bases:
            return stored
    current = Facts(conn,dataset_id,batch_id,scopes=scopes).snapshot()
    if 'input_proof_v1' in stored:
        current['input_proof_v1']=signature
    if current == stored:
        with _bases_lock:
            _verified_bases.append(key)
    return current


def dependency_snapshot(conn,dataset_id,batch_id):
    if conn.execute('PRAGMA user_version').fetchone()[0]<39 or not conn.execute('SELECT 1 FROM current_authorization_match_scopes WHERE batch_id=?',(batch_id,)).fetchone():
        return Facts(conn,dataset_id,batch_id).snapshot()
    proof,scopes=_inputs_digest(conn,dataset_id,batch_id)
    result=Facts(conn,dataset_id,batch_id,scopes=scopes).snapshot()
    if result.get('scope'):result['input_proof_v1']=proof.hex()
    return result


class Evaluator:
    def __init__(self,conn,dataset_id,batch_id,checkpoint=None):
        self.facts=Facts(conn,dataset_id,batch_id,checkpoint)
        self.conn,self.checkpoint=conn,checkpoint
        self.contexts={};self.evidence={};self.quantities={}
        self.active=bool(self.facts.target_scope)

    def row_evidence(self,fact):
        identity=fact['identity']
        if identity not in self.evidence:
            b=fact['batch'];import_id=b['import_id']
            if import_id not in self.contexts:
                scope,captures,issues=_context(self.conn,self.facts.root,self.facts.dataset_id,b['batch_id'])
                if fact['scope'] and any(c.get('status')!='registered' for c in fact['scope']['captures']):issues=[*issues,'source_status_not_registered']
                self.contexts[import_id]=(scope,captures,issues,_index(captures) if not issues else {})
            scope,captures,issues,index=self.contexts[import_id]
            ev=_row_evidence(self.conn,b,fact['row'],scope,index,issues)
            link=fact['link']
            chosen=None
            if link and link['state']=='selected' and link['basis_sha256']==ev['basis_sha256'] and not ev['issues']:
                chosen=next((c for c in ev['candidates'] if c['key']==link['candidate_key'] and c['compatibility']=='compatible'),None)
            self.evidence[identity]=(ev,chosen)
        return self.evidence[identity]

    def joint(self,fact,chosen,resolution):
        key=(chosen['key'],fact['key'])
        if key in self.quantities:return self.quantities[key]
        q={'state':'no_concluyente','authorized':resolution['quantity'],'unit':resolution['unit'],
           'billed_joint':None,'members':[],'member_count':0,'limitations':[],'members_truncated':False}
        total=Decimal(0);issues=set();members=[]
        if quantity(q['authorized']) is None or not q['unit']:
            q['limitations']=['authorized_quantity_or_unit_unknown'];return q
        for pos,peer in enumerate(self.facts.peers(fact),1):
            if self.checkpoint and pos%100==0:self.checkpoint()
            if not peer['key'][0]:issues.add('related_identity_unresolved');continue
            ev,other=self.row_evidence(peer)
            if ev['issues']:issues.add('other_lot_scope_unresolved' if not peer['scope'] else 'association_candidates_incomplete');continue
            if other and other['key']!=chosen['key'] and other['capture_id']==chosen['capture_id']:continue
            possible=[c for c in ev['candidates'] if c['compatibility']!='incompatible']
            overlap=[c for c in possible if c['key']==chosen['key'] or c['capture_id']!=chosen['capture_id']]
            if not overlap:continue
            if (other and other['capture_id']!=chosen['capture_id']) or any(c['capture_id']!=chosen['capture_id'] for c in overlap):
                issues.add('coverage_identity_between_captures_unverified');continue
            if not other:issues.add('pending_or_ambiguous_association');continue
            unit=peer['quantity_unit'];amount=quantity(peer['fields'].get('G'))
            valid=unit and unit['state']=='declared' and unit['value']==q['unit'] and unit['data_origin']==chosen['data_origin']
            members.append({'import_id':peer['identity'][0],'batch_id':peer['batch']['batch_id'],'source_row':peer['identity'][1],
                'batch_name':peer['batch']['original_name'],
                'locator':f'Hoja1!{peer["identity"][1]}','billed':peer['fields'].get('G'),
                'unit_input_id':unit['id'] if unit else None,'link_id':peer['link']['id']})
            if not valid or amount is None:issues.add('billed_quantity_or_unit_unverified')
            else:total+=amount
        q.update(member_count=len(members),members=members[:20],members_truncated=len(members)>20,
                 members_sha256=_hash(members),limitations=sorted(issues))
        if not issues:q.update(state='con_indicios' if total>quantity(q['authorized']) else 'sin_observaciones',billed_joint=str(total))
        self.quantities[key]=q
        return q

    def evaluate(self,number,base):
        fact=self.facts.rows.get((self.facts.target['import_id'],number))
        if not fact or not self.active:return {}
        ev,chosen=self.row_evidence(fact)
        mode=fact['scope']['mode']
        common={**base,'authorization_engine_version':VERSION,'evaluation_mode':mode,
                'data_origin':'synthetic' if mode=='synthetic_demo' else 'real_unvalidated',
                'source_validation':'not_verified','coverage_verification':'not_verified','monetary_eligible':False,
                'link_id':fact['link']['id'] if fact['link'] else None,'correspondence_state':ev['state'],
                'basis_sha256':fact['bases']['RN09'],'source_issues':ev['issues']}
        resolution={'state':'no_concluyente','resolution':None,'reason':'Se necesita un vínculo humano actual e inequívoco.'}
        temporal=compare_time(None,None)
        q={'state':'no_concluyente','authorized':None,'billed_joint':None,'limitations':['applicable_resolution_unresolved']}
        if chosen:
            captures=self.contexts[fact['identity'][0]][1]
            c=next(c for c in captures if c['id']==chosen['capture_id'])
            oi,ii=(int(x) for x in chosen['key'].rsplit(':',2)[1:])
            order=json.loads(c['canonical_json'])['orders'][oi]
            resolution=applicable_resolution(order,order['items'][ii])
            common.update(capture_id=c['id'],authorization_source_sha256=chosen['source_sha256'],
                          authorization_locator=chosen['locator'],order_id=chosen['order_id'],item_id=chosen['item']['item_id'])
            if resolution['state']=='declared_authorized':
                time=fact['incorporation']
                temporal=compare_time(resolution['resolution']['decided_at'],time['value'] if time and time['state']=='declared' and time['data_origin']==chosen['data_origin'] else None)
                q=self.joint(fact,chosen,resolution)
        demo=mode=='synthetic_demo'
        state9=('sin_observaciones' if resolution['state']=='declared_authorized' else 'con_indicios' if resolution['state']=='declared_rejected' else 'no_concluyente') if demo else 'no_concluyente'
        state10=temporal['state'] if demo else 'no_concluyente'
        state11=q['state'] if demo else 'no_concluyente'
        reason9=('demo_autorizacion_declarada' if state9=='sin_observaciones' else 'demo_rechazo_declarado' if state9=='con_indicios' else 'demo_resolucion_sin_conclusion') if demo else 'autorizaciones_reales_sin_validar'
        reason10=('demo_autorizacion_previa_incorporacion' if state10=='sin_observaciones' else 'demo_autorizacion_posterior_incorporacion' if state10=='con_indicios' else 'demo_secuencia_temporal_incompleta') if demo else 'evidencia_temporal_real_sin_validar'
        reason11=('demo_cantidad_dentro_declarado' if state11=='sin_observaciones' else 'demo_cantidad_supera_declarado' if state11=='con_indicios' else 'demo_cantidad_sin_conclusion') if demo else 'cobertura_real_sin_validar'
        return {
            'RN09':('RN09',state9,reason9,{**common,'resolution':resolution},None,None),
            'RN10':('RN10',state10,reason10,{**common,'temporal':temporal,'incorporation':fact['incorporation']},None,None),
            'RN11':('RN11',state11,reason11,{**common,'quantity':q,'cohort_sha256':_hash(fact['key'])},None,None),
        }

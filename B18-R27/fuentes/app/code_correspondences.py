"""Versioned administrative correspondences, component rules and declared units."""
import json
from collections import defaultdict
from .db import transaction
from .security import now_utc
from .service import Problem, authorized_dataset, check_version, event
from .hpc_correspondence_catalog import catalogue_candidates,qualifier_candidates,text_key


def candidates(conn,root,dataset_id,source_id):
    return catalogue_candidates(conn,root,dataset_id,source_id)+qualifier_candidates(conn,root,dataset_id,source_id)


def history(conn,dataset_id,source_id):
    if conn.execute('PRAGMA user_version').fetchone()[0]<40:return []
    return [dict(r) for r in conn.execute(
        'SELECT c.*,u.username AS actor_username FROM hpc_code_correspondences c JOIN users u ON u.id=c.actor_id '
        'WHERE c.dataset_id=? AND c.source_id=? ORDER BY c.id',(dataset_id,source_id))]


def _valid_rule(row,proposal):
    kind=row.get('relation_kind','legacy')
    if kind=='legacy':
        return proposal['relation_kind']=='direct' and proposal['factor']=='1'
    if kind!=proposal['relation_kind'] or row['factor']!=proposal['factor'] or row['billing_unit']!=proposal['billing_unit']:
        return False
    if kind=='qualifier':
        saved=json.loads(row['basis_json'])
        return text_key(saved['authorization_description'])==text_key(proposal['authorization_description'])
    return row['source_sha256']==proposal['source_sha256']


def listing(conn,root,token,dataset_id,source_id):
    from .consistent_reads import consistent_read
    def read():
        user,ds=authorized_dataset(conn,token,dataset_id,'reviewer')
        rows=history(conn,dataset_id,source_id)
        current={(r['invoice_code'],r['authorization_code']):r for r in rows}
        items=candidates(conn,root,dataset_id,source_id)
        for item in items:
            previous=current.get((item['invoice_code'],item['authorization_code']))
            item['active']=bool(previous and previous['active'] and _valid_rule(previous,item))
            item['confirmation']=previous
        return {'items':items,'history':rows,'dataset_version':ds['version'],'can_edit':user['role']=='admin'}
    return consistent_read(conn,token,dataset_id,read)


def save(conn,root,token,dataset_id,source_id,*,expected_version,pairs=None,active=True,reason,
         relation_kind='direct',factor='1',billing_unit='practice',changes=None,locator=''):
    if not isinstance(reason,str) or not 10<=len(reason.strip())<=2000:
        raise Problem(422,'Indicá el respaldo y el motivo de la revisión.')
    if changes is None:
        if not isinstance(pairs,list) or not 1<=len(pairs)<=500 or any(
            not isinstance(p,list) or len(p)!=2 or any(not isinstance(v,str) for v in p) for p in pairs):
            raise Problem(422,'Seleccioná pares de códigos.')
        changes=[dict(invoice_code=p[0],authorization_code=p[1],active=active,relation_kind=relation_kind,
                      factor=factor,billing_unit=billing_unit,locator=locator) for p in pairs]
    if (not isinstance(changes,list) or not 1<=len(changes)<=500 or
            any(not isinstance(p,dict) or not isinstance(p.get('invoice_code'),str) or
                not isinstance(p.get('authorization_code'),str) or type(p.get('active')) is not bool for p in changes)):
        raise Problem(422,'Cambios de correspondencia inválidos.')
    if len({(p['invoice_code'],p['authorization_code']) for p in changes})!=len(changes):
        raise Problem(422,'No repetir el mismo par en una operación.')
    with transaction(conn):
        actor,ds=authorized_dataset(conn,token,dataset_id,'admin');check_version(ds,expected_version)
        allowed={(p['invoice_code'],p['authorization_code']):p for p in candidates(conn,root,dataset_id,source_id)}
        previous={(p['invoice_code'],p['authorization_code']):p for p in history(conn,dataset_id,source_id)}
        prepared=[]
        for change in changes:
            key=change['invoice_code'],change['authorization_code']
            proposal=allowed.get(key)
            if not proposal:
                if not change['active'] and key in previous:
                    proposal=json.loads(previous[key]['basis_json'])
                else:raise Problem(422,'La fuente no respalda esa relación de códigos.')
            if change['active'] and (change.get('relation_kind','direct') not in proposal.get('allowed_kinds',['direct']) or
                    str(change.get('factor','1'))!=proposal.get('factor','1') or
                    change.get('billing_unit','practice')!=proposal.get('billing_unit','practice')):
                raise Problem(422,'El tipo de relación o la unidad no coincide con la fuente. Revisá la propuesta.')
            location=change.get('locator') or proposal.get('locator') or 'Catálogo de códigos'
            if not isinstance(location,str) or not 3<=len(location)<=1000:
                raise Problem(422,'Indicá un localizador del respaldo.')
            prepared.append((change,proposal,location))
        for change,basis,location in prepared:
            conn.execute('INSERT INTO hpc_code_correspondences(dataset_id,source_id,source_sha256,invoice_code,authorization_code,active,basis_json,reason,actor_id,created_at,relation_kind,factor,billing_unit,parent_code,related_code,qualifier_kind,qualifier_value,locator) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (dataset_id,source_id,basis['source_sha256'],change['invoice_code'],change['authorization_code'],int(change['active']),
                 json.dumps(basis,sort_keys=True,ensure_ascii=False),reason.strip(),actor['id'],now_utc(),
                 basis.get('relation_kind','direct'),basis.get('factor','1'),basis.get('billing_unit','practice'),
                 basis.get('parent_code'),basis.get('related_code'),basis.get('qualifier_kind'),basis.get('qualifier_value'),location))
        conn.execute('UPDATE datasets SET version=version+1 WHERE id=?',(dataset_id,))
        event(conn,actor['id'],'hpc_code_correspondence_recorded','source',source_id)
    return {'dataset_version':expected_version+1,'recorded':len(prepared)}


class Correspondences:
    def __init__(self,conn,root,dataset_id,batch_id):
        from .proposal_freshness import provider_basis
        scope=provider_basis(conn,batch_id)
        self.codes,self.receipts,self.rules,self.components,self.qualifiers={},{},{},{},{}
        if not scope or scope['provider']!='HPC':return
        rows=history(conn,dataset_id,scope['source_id'])
        current={(r['invoice_code'],r['authorization_code']):r for r in rows}
        if not any(r['active'] for r in current.values()):return
        allowed={(r['invoice_code'],r['authorization_code']):r for r in candidates(conn,root,dataset_id,scope['source_id'])}
        groups=[];accepted=[];verified_sources=set()
        for row in current.values():
            proposal=allowed.get((row['invoice_code'],row['authorization_code']))
            if not row['active'] or not proposal or not _valid_rule(row,proposal):continue
            rule={**row,'relation_kind':proposal['relation_kind']}
            kind=rule['relation_kind']
            if row['source_sha256'] not in verified_sources:
                from .storage import read_verified
                try:read_verified(root,row['source_sha256'])
                except (OSError,RuntimeError,ValueError,TypeError):continue
                verified_sources.add(row['source_sha256'])
            if kind=='qualifier':self.qualifiers[rule['authorization_code']]=rule;continue
            if kind=='component':self.components[rule['invoice_code']]=rule;continue
            self.rules.setdefault(rule['invoice_code'],{})[rule['authorization_code']]=rule
            self.rules.setdefault(rule['authorization_code'],{}).setdefault(rule['authorization_code'],
                {**rule,'factor':'1','billing_unit':'practice'})
            component={rule['invoice_code'],rule['authorization_code']}
            other=[]
            for group in groups:
                if group&component:component.update(group)
                else:other.append(group)
            groups=other+[component];accepted.append(rule)
        for component in groups:
            key=min(component,key=lambda v:(len(v),v));self.codes.update((c,key) for c in component)
            self.receipts[key]=sorted(r['id'] for r in accepted if r['invoice_code'] in component and r['authorization_code'] in component)

    def key(self,affiliate,code):
        return affiliate,self.codes.get(code,code)

    def index(self,original):
        result=defaultdict(list)
        for (affiliate,code),entries in original.items():
            if code not in self.qualifiers:
                result[self.key(affiliate,code)].extend(entries)
        return result

    def identity(self,code):
        return self.codes.get(code)

    def modifiers(self,order,item_position):
        result=[]
        principals=[i for i in order['items'] if i['full_code'] not in self.qualifiers]
        if len(principals)!=1 or principals[0]['position']!=item_position:return []
        for item in order['items']:
            rule=self.qualifiers.get(item['full_code'])
            if rule:
                result.append({'code':item['full_code'],'kind':rule['qualifier_kind'],'value':rule['qualifier_value'],'rule_id':rule['id']})
        return result


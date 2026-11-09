"""Completitud declarada por el operador para una selección concreta de Imágenes HPC."""
from collections import defaultdict
from datetime import date, timedelta
from functools import cached_property, lru_cache
import json
import unicodedata

from .service import Problem

VALID_DAYS = 60


def export_range(conn,scope_id):
    row=conn.execute('SELECT complete_from,complete_until FROM csv_export_ranges WHERE scope_id=?',(scope_id,)).fetchone()
    return tuple(row) if row else None


def validate_declaration(start,end,captures):
    if start is None and end is None:
        return None
    try:
        if start!=date.fromisoformat(start).isoformat() or end!=date.fromisoformat(end).isoformat() or start>end:
            raise ValueError
    except (ValueError,TypeError):
        raise Problem(422,'Completá desde y hasta con el período exportado, en orden.') from None
    if not captures or any(c['source_system']!='HPC-CSV' for c in captures):
        raise Problem(422,'La declaración de cobertura corresponde al CSV de Imágenes HPC.')
    return start,end


def export_limitation(captures,issues):
    from .authorization_matching import dni
    if issues or not captures or any(c['source_system']!='HPC-CSV' for c in captures):
        return 'Falta una selección vigente y verificable de CSV de Imágenes HPC.'
    for c in captures:
        if any(o['code']=='csv_record_quarantined' for o in json.loads(c['observations_json'])):
            return 'Hay registros de la exportación que no se pudieron incorporar.'
        for order in json.loads(c['canonical_json'])['orders']:
            if not dni(order['affiliate_id']) or not order['items']:
                return 'Hay órdenes sin identificación de afiliado o de práctica.'
    return None


def description_key(text):
    return ''.join(c for c in unicodedata.normalize('NFKD',str(text or '')).casefold() if c.isalnum())


class ExportCoverage:
    def __init__(self,conn,scope,captures,index,load_relations):
        self.dates=export_range(conn,scope['id'])
        self.problem=export_limitation(captures,[]) if self.dates else 'Falta confirmar el período completo de la exportación.'
        self.scope=scope['id']
        self.load_relations=load_relations
        self.codes=defaultdict(dict)
        for (patient, code),matches in index.items():
            self.codes[patient][code]={description_key(m[4]['description']) for m in matches}
        self.aliases = lru_cache(maxsize=4096)(self._alias_codes)

    @cached_property
    def relations(self):
        return self.load_relations()

    def _alias_codes(self,code):
        return {r['authorization_code'] for r in self.relations.aliases(code)} if self.relations else set()

    def limitation(self,day):
        if self.problem:
            return self.problem
        start,end=self.dates
        if start>(day-timedelta(days=VALID_DAYS)).isoformat() or end<day.isoformat():
            return 'El período exportado no cubre los 60 días previos hasta la prestación.'
        return None

    def uncertain_identity(self,patient,code,description,linked):
        if not patient or not isinstance(code,str) or not code.strip() or not description_key(description) or linked:
            return True
        other=self.codes.get(patient,{})
        # A truncated code, a related catalog code or a similar description is a lead for review.
        # None establishes either an authorization or an absence.
        name=description_key(description)
        for candidate,names in other.items():
            if candidate==code:
                continue
            if (not code.isdigit() or len(code)!=10 or candidate[:6]==code[:6] or candidate in self.aliases(code)
                    or any(n and (n in name or name in n) for n in names)):
                return True
        return False

    def absence(self,patient,code,fields,row,linked):
        day=date.fromisoformat(row['practice_date'])
        if not patient:
            return {'status':'unidentified','reason':'Afiliado no identificable · débito total propuesto'}
        problem=self.limitation(day)
        if problem:
            return {'status':'coverage_pending','coverage_note':problem}
        if self.uncertain_identity(patient,code,fields.get('K'),linked):
            return {'status':'needs_review','coverage_note':'Falta aclarar la identidad del afiliado o de la práctica.'}
        return {'status':'no_aval','export_scope':self.scope,'complete_range':self.dates}

    def check_shortfall(self,signal,row,patient,code):
        if signal['status'] not in ('already_used','outside_window','one_unit_only','units_partial','declared_rejected','posterior_candidate','referred_elsewhere','prior_not_found'):
            return
        problem=self.limitation(row['day'])
        verified_pair=bool(row.get('directed_rules')) or code in self.codes.get(patient,{})
        if not problem and (row['uncertain'] or (not verified_pair and self.uncertain_identity(patient,code,row['description'],False))):
            problem='Hay otra correspondencia por cotejar.'
        if problem:
            signal['coverage_note']=problem
        else:
            signal['export_scope']=self.scope
            signal['complete_range']=self.dates


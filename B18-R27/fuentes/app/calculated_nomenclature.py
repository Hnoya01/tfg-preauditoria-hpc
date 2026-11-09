"""Read-only exact-code component references, never tariffs or equivalences."""
import json
import sqlite3
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext

COMPONENT='seed.nomencladorImagenes'
FORMULA='(Q GAL × Galeno Radiológico) + (Gto × Unidad Radiológica)'
LIMIT=('Referencia calculada declarada en componente de nomenclador; no acredita equivalencia clínica, '
       'moneda, unidad facturable, vigencia contractual ni factor documental. No aplica arancel ni débito.')
EMPTY_LINK_STATUSES={'no_declared_hpc_link','no_linked_hpc_tariff'}


def literal(value):
    if isinstance(value,dict):return {str(k):literal(v) for k,v in value.items()}
    if isinstance(value,list):return [literal(v) for v in value]
    if isinstance(value,Decimal):return str(value)
    return value


def number(value):
    if isinstance(value,bool) or not isinstance(value,(int,Decimal)) or len(str(value))>60:raise ValueError()
    result=Decimal(value)
    if not result.is_finite() or result<0 or result>Decimal('1000000000000') or result.as_tuple().exponent < -12:raise ValueError()
    return result


def valid_date(value):
    if not isinstance(value,str):return False
    try:return date.fromisoformat(value).isoformat()==value
    except ValueError:return False


class CalculatedNomenclature:
    def __init__(self,catalog,source_id,source_sha256):
        self.source_id,self.source_sha256=source_id,source_sha256
        self.data={};self.index={};self.status='component_unavailable'
        try:
            parts=list(catalog.execute('SELECT part,text_data FROM hpc_catalog_components WHERE component=? ORDER BY part',(COMPONENT,)))
            if not parts:return
            if [p[0] for p in parts]!=list(range(len(parts))):self.status='component_parts_invalid';return
            if sum(len(p[1]) for p in parts)>16*1024*1024:self.status='component_too_large';return
            self.data=json.loads(''.join(p[1] for p in parts),parse_float=Decimal,parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if not isinstance(self.data,dict) or not isinstance(self.data.get('rows'),list):self.status='component_structure_invalid';return
            if self.data.get('provider')!='HPC':self.status='outside_hpc_provider';return
            for index,row in enumerate(self.data['rows']):
                if isinstance(row,dict) and isinstance(row.get('nomencladorCode'),str):self.index.setdefault(row['nomencladorCode'],[]).append((index,row))
            self.status='available'
        except (sqlite3.Error,ValueError,TypeError,KeyError):self.status='component_invalid'

    def references(self,code,performed_on=None):
        result={'status':self.status,'candidates':[],'source_id':self.source_id,'source_sha256':self.source_sha256,
                'code_complete':code,'use_limit':LIMIT,'applied':False,'equivalence_verified':False}
        if self.status!='available':return result
        rows=self.index.get(code,[])
        if not rows:return {**result,'status':'no_exact_nomenclature_code'}
        items=[self._candidate(index,row,performed_on) for index,row in rows]
        return {**result,'status':'duplicate_exact_nomenclature_code' if len(items)>1 else 'calculated_reference_pending_verification','candidates':items}

    def _candidate(self,index,row,performed_on):
        start=row.get('validFrom',self.data.get('validFrom'));end=row.get('validUntil',self.data.get('validUntil'))
        temporal='undetermined_declared_dates'
        if valid_date(start) and (end is None or valid_date(end) and end>=start) and valid_date(performed_on):
            temporal='inside_declared_dates' if start<=performed_on and (end is None or performed_on<=end) else 'outside_declared_dates'
        amount=row.get('amount');good_amount=type(amount) is int and 0<=amount<=10**20
        candidate={'row_index':index,'source_locator':f'hpc_catalog_components[{COMPONENT}].rows[{index}]',
            'source_id':self.source_id,'source_sha256':self.source_sha256,
            'code':row.get('nomencladorCode'),'description':literal(row.get('description')),'provider':self.data.get('provider'),
            'source_file':literal(self.data.get('sourceFile')),'source_row':literal(row.get('sourceRow')),
            'valid_from':literal(start),'valid_until':literal(end),'temporal_relation':temporal,
            'formula':literal(row.get('formula')),'qGal':literal(row.get('qGal')),'gto':literal(row.get('gto')),
            'galenoRadiologico':literal(row.get('galenoRadiologico')),'unidadRadiologica':literal(row.get('unidadRadiologica')),
            'component_unit_values':literal(self.data.get('unitValues')),
            'calculated_amount_exact':None,'calculated_amount_rounded':None,
            'recorded_amount':format(Decimal(amount)/100,'.2f') if good_amount else None,
            'recorded_amount_cents':amount if good_amount else None,'amount_literal':literal(amount),
            'arithmetic_status':'not_interpretable','rounding_note':'Cotejo técnico Decimal ROUND_HALF_UP a 2 decimales; no acredita regla contractual de redondeo.',
            'component_status':literal(row.get('status')),'norma':literal(row.get('norma')),
            'unidadArancelaria':literal(row.get('unidadArancelaria')),'formaFacturacion':literal(row.get('formaFacturacion')),
            'equivalence_declared':literal(row.get('equivalence')),'practice_ids_declared':literal(row.get('practiceIds')),
            'declared_currency':None,'declared_unit':None,'document_factor_verified':False,
            'norms_limit':'Texto literal del componente, posiblemente incompleto; revisar original, no interpretar como norma íntegra.',
            'applied':False,'equivalence_verified':False}
        if row.get('provider','HPC')!='HPC':return {**candidate,'arithmetic_status':'provider_conflict'}
        if row.get('formula')!=FORMULA:return {**candidate,'arithmetic_status':'unsupported_formula'}
        try:
            q,g,gal,unit=(number(row.get(k)) for k in ('qGal','gto','galenoRadiologico','unidadRadiologica'))
            declared=self.data.get('unitValues')
            if not isinstance(declared,dict):raise ValueError()
            if gal!=number(declared.get('galenoRadiologico')) or unit!=number(declared.get('unidadRadiologica')):
                return {**candidate,'arithmetic_status':'coefficient_conflict'}
            with localcontext() as ctx:
                ctx.prec=80
                exact=q*gal+g*unit;rounded=exact.quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
            candidate.update(calculated_amount_exact=format(exact,'f'),calculated_amount_rounded=format(rounded,'.2f'))
            candidate['arithmetic_status']='recorded_amount_invalid' if not good_amount else 'corroborated_technical_rounding' if rounded*100==amount else 'recorded_amount_mismatch'
        except (ValueError,TypeError,InvalidOperation):pass
        return candidate

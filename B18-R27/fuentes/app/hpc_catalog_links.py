"""Read-only declared HPC order/convention links. Never a verified equivalence.

Exact identifiers only; source structure is evidence of a declared relationship,
not proof of clinical scope, currency, unit, date applicability or authorization.
"""
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
import json
import sqlite3

LIMIT = ('Enlace declarado por el catálogo, pendiente de verificación documental y de alcance. '
         'Por sí solo no acredita condiciones ni equivalencia clínica, ni aplica el arancel o un débito.')


class CatalogLinks:
    def __init__(self, catalog, source_id, source_sha256):
        self.source_id, self.source_sha256 = source_id, source_sha256
        self.available = True
        self.tariff_by_seq = {}
        self.codes, self.practices, self.tariffs, self.documents = defaultdict(list), {}, defaultdict(list), defaultdict(list)
        try:
            for row in catalog.execute('SELECT seq,id FROM hpc_catalog_practices'):
                self.practices[row['seq']] = row['id']
            self.practice_ids = defaultdict(list)
            for seq, pid in self.practices.items(): self.practice_ids[pid].append(seq)
            for row in catalog.execute("SELECT seq,practice_seq,practice_id,provider,code,kind,description FROM hpc_catalog_codes WHERE provider='HPC'"):
                self.codes[row['code']].append(dict(row))
            columns={r['name'] for r in catalog.execute('PRAGMA table_info(hpc_catalog_tariffs)')}
            extra=',data_json' if 'data_json' in columns else ''
            for row in catalog.execute("SELECT seq,provider,code,practice_id,amount_cents,valid_from,valid_until,source_id,page"+extra+" FROM hpc_catalog_tariffs WHERE provider='HPC'"):
                if row['seq'] in self.tariff_by_seq:
                    self.available=False
                tariff=dict(row)
                self.tariff_by_seq[row['seq']]=tariff
                self.tariffs[row['practice_id']].append(tariff)
            if catalog.execute("SELECT 1 FROM sqlite_master WHERE name='hpc_catalog_documents'").fetchone():
                for row in catalog.execute('SELECT id,provider,filename,sha256 FROM hpc_catalog_documents'):
                    self.documents[row['id']].append(dict(row))
        except (sqlite3.Error, TypeError, KeyError):
            self.available = False

    def coherent(self, entry):
        return (entry['practice_id'] and self.practices.get(entry['practice_seq']) == entry['practice_id']
                and self.practice_ids[entry['practice_id']] == [entry['practice_seq']])

    def suggestions(self, code, performed_on=None, resolver=None):
        base = {'status':'no_declared_hpc_link','candidates':[], 'source_id':self.source_id,
                'source_sha256':self.source_sha256,'code_complete':code,'use_limit':LIMIT,
                'equivalence_verified':False,'applied':False}
        if not self.available: return {**base,'status':'catalogue_link_structure_unavailable'}
        entries = [e for e in self.codes.get(code,[]) if e['kind']=='orden']
        if not entries: return base
        all_entries=self.codes.get(code,[])
        if any(not self.coherent(e) for e in all_entries): return {**base,'status':'inconsistent_declared_hpc_link'}
        identities = {(e['practice_seq'],e['practice_id']) for e in all_entries}
        if len(identities)!=1: return {**base,'status':'ambiguous_declared_hpc_link'}
        practice_seq, pid = next(iter(identities))
        from .values_v1 import json_safe_catalog_amount, catalog_amount_literal
        candidates=[]; ambiguous=False
        for tariff in self.tariffs.get(pid,[]):
            if tariff['code']==code: continue  # This module never changes the exact-code path.
            target = [e for e in self.codes.get(tariff['code'],[]) if e['kind']=='convenio']
            if not target: continue
            if any(not self.coherent(e) or (e['practice_seq'],e['practice_id'])!=(practice_seq,pid) for e in self.codes.get(tariff['code'],[])):
                ambiguous=True;continue
            relation='undetermined_declared_dates'
            try:
                day=date.fromisoformat(performed_on); start=date.fromisoformat(tariff['valid_from'])
                end=date.fromisoformat(tariff['valid_until']) if tariff['valid_until'] else None
                if day.isoformat()!=performed_on or (end and end<start):raise ValueError()
                relation='outside_declared_dates' if day<start or (end and day>end) else 'inside_declared_dates'
            except (ValueError,TypeError): pass
            documents=[d for d in self.documents.get(tariff['source_id'],[]) if d['provider']=='HPC']
            document=documents[0] if len(documents)==1 else None
            amount=tariff['amount_cents'];interpretable=type(amount) is int and amount>=0
            candidates.append({'order_code':code,'tariff_code':tariff['code'],'practice_id':pid,
                'practice_seq':practice_seq,'order_code_seqs':[e['seq'] for e in entries],
                'convention_code_seqs':[e['seq'] for e in target],'tariff_seq':tariff['seq'],
                'source_id':self.source_id,'source_sha256':self.source_sha256,
                'source_locator':f"hpc_catalog_tariffs.seq={tariff['seq']}",
                'document_source_id':tariff['source_id'],'document_page':tariff['page'],
                'declared_document':document,'document_bytes_verified':False,
                'valid_from':tariff['valid_from'],'valid_until':tariff['valid_until'],'temporal_relation':relation,
                'amount_cents':json_safe_catalog_amount(amount),'amount_literal':catalog_amount_literal(amount),
                'recorded_amount':format(Decimal(amount)/100,'.2f') if interpretable else None,
                'amount_status':'interpretable' if interpretable else 'not_interpretable',
                'declared_currency':None,'declared_unit':None,'equivalence_verified':False,'applied':False,
                **({'effective_reference':resolver.resolve(tariff,performed_on)} if resolver is not None else {})})
        if ambiguous: return {**base,'status':'ambiguous_declared_hpc_link'}
        return {**base,'status':'declared_hpc_link_pending_verification' if candidates else 'no_linked_hpc_tariff',
                'candidates':sorted(candidates,key=lambda x:x['tariff_seq'])}

    def comparison(self, related, resolver, performed_on, quantity, billed_total, billing_unit):
        base={'status':'related_link_not_comparable','candidate_total_if_ars_and_same_unit':None,
              'difference_ars_if_comparable':None,'equivalence_verified':False,'applied':False,
              'use_limit':'Comparación exploratoria de enlace sujeto a verificación; no confirma equivalencia ni genera débito.'}
        if related['status']!='declared_hpc_link_pending_verification':return base
        effective=[]
        for item in related['candidates']:
            raw=self.tariff_by_seq[item['tariff_seq']];resolved=resolver.resolve(raw,performed_on)
            if resolved['status']=='withdrawn_reference':continue
            if resolved['selected']:effective.append((item,raw,resolved))
        if len(effective)!=1:return {**base,'status':'ambiguous_related_reference' if effective else 'no_related_reference_for_date'}
        item,raw,resolved=effective[0]
        base.update(tariff_seq=item['tariff_seq'],order_code=item['order_code'],tariff_code=item['tariff_code'],
                    source_sha256=self.source_sha256,effective_reference=resolved)
        try:
            metadata=json.loads(raw.get('data_json') or '{}')
            if not isinstance(metadata,dict):raise ValueError()
            calculation=metadata.get('calculation') or {}
        except (TypeError,ValueError):return {**base,'status':'related_conditions_uninterpretable'}
        if (not isinstance(calculation,dict) or calculation.get('reviewRequired') is True
                or metadata.get('reviewRequired') is True
                or calculation.get('kind') not in (None,'nbu','fixed','flat')
                or any(metadata.get(k) for k in ('specific_norm','specificNorm','special_norm','specialNorm'))):
            return {**base,'status':'related_special_conditions_require_review'}
        if resolved['status'] not in ('documented_version_candidate','documented_agreement_candidate'):return {**base,'status':'related_dimensions_or_document_unverified'}
        if billing_unit!='practice' or resolved.get('declared_currency')!='ARS' or resolved.get('declared_unit')!='por práctica':
            return {**base,'status':'related_economic_unit_unverified_or_incompatible'}
        try:
            if len(str(quantity))>64 or len(str(billed_total))>64:raise ValueError()
            qty=Decimal(str(quantity));billed=Decimal(str(billed_total));rate=Decimal(resolved['recorded_amount'])
            if not qty.is_finite() or qty<=0 or qty>Decimal('1000000000') or qty.as_tuple().exponent < -6 or not billed.is_finite():raise ValueError()
            total=qty*rate
            if total*100!=(total*100).to_integral_value():return {**base,'status':'related_fractional_cent_needs_rounding_rule'}
            delta=billed-total
        except (ValueError,TypeError,InvalidOperation):return {**base,'status':'related_quantity_or_total_uninterpretable'}
        status='numeric_equal' if abs(delta)<=Decimal('0.01') else 'numeric_above_candidate' if delta>0 else 'numeric_below_candidate'
        return {**base,'status':status,'recorded_amount':format(rate,'.2f'),'declared_currency':'ARS',
                'declared_unit':'por práctica','candidate_total_if_ars_and_same_unit':format(total,'.2f'),
                'difference_ars_if_comparable':format(delta,'.2f')}

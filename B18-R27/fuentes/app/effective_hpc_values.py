"""One read-only temporal resolver for HPC catalog values and documented versions.

A selected candidate is not row applicability. No analysis, confirmation or debit
is created here. A version has its own declared start; unrelated tariff records
can still conflict and must not be silently overridden.
"""
from datetime import date
from decimal import Decimal, InvalidOperation

from .storage import read_verified


class EffectiveHpcValues:
    def __init__(self, conn, root, dataset_id, source_id):
        self.conn, self.root = conn, root
        self.dataset_id, self.source_id = dataset_id, source_id
        self.versions, self.documents, self.statuses, self.local_versions = {}, {}, {}, {}
        if conn.execute('PRAGMA user_version').fetchone()[0]>=29:
            for row in conn.execute('SELECT v.*,p.code FROM local_hpc_versions v JOIN local_hpc_practices p ON p.id=v.practice_id WHERE p.dataset_id=? AND p.source_id=? ORDER BY v.effective_from,v.ordinal',(dataset_id,source_id)):
                self.local_versions.setdefault(row['practice_id'],[]).append(dict(row))
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='hpc_value_status_versions'").fetchone():
            for row in conn.execute("SELECT * FROM hpc_value_status_versions WHERE dataset_id=? AND source_id=? ORDER BY effective_from,ordinal", (dataset_id,source_id)):
                self.statuses.setdefault(row['tariff_seq'],[]).append(dict(row))
        for row in conn.execute('SELECT * FROM hpc_value_versions WHERE dataset_id=? AND source_id=? '
                                'ORDER BY effective_from,ordinal', (dataset_id, source_id)):
            self.versions.setdefault(row['tariff_seq'], []).append(dict(row))

    def _document(self, version):
        key=(version['document_id'],version['document_sha256'])
        if key not in self.documents:
            row=self.conn.execute("SELECT * FROM evidence_documents WHERE id=? AND dataset_id=? "
                                  "AND source_id=? AND category='agreement'",
                                  (version['document_id'],self.dataset_id,self.source_id)).fetchone()
            doc=dict(row) if row else None
            usable=bool(doc and doc['sha256']==version['document_sha256'])
            if usable:
                try:read_verified(self.root,version['document_sha256'])
                except (OSError,RuntimeError):usable=False
            self.documents[key]=(doc,usable)
        return self.documents[key]

    def resolve(self, tariff, performed_on):
        base={'selected':False,'value_version':None,'recorded_amount':None,
              'declared_currency':None,'declared_unit':None,'effective_from':None,
              'declared_until':None,'next_version_from':None,'document':None,
              'status':'undetermined_declared_dates'}
        if tariff.get('provider','HPC')!='HPC':
            return {**base,'status':'outside_hpc_provider'}
        if not performed_on:
            return base
        try:
            if date.fromisoformat(performed_on).isoformat()!=performed_on:return base
        except (ValueError,TypeError):return base
        if tariff.get('local_id'):
            versions=self.local_versions.get(tariff['local_id'],[])
            eligible=[v for v in versions if v['effective_from']<=performed_on]
            if not eligible:return {**base,'status':'outside_declared_dates'}
            value=eligible[-1]
            base.update(selected=True,value_version=value,effective_from=value['effective_from'],declared_currency='ARS',declared_unit=value['unit_label'])
            doc,usable=self._document(value);base['document']=doc
            if not usable:return {**base,'status':'version_evidence_unverifiable'}
            if not value['active']:return {**base,'status':'withdrawn_reference','status_version':value}
            try:
                amount=Decimal(value['amount_ars'])
                if not amount.is_finite() or amount<=0 or amount*100!=(amount*100).to_integral_value():raise ValueError()
            except (ValueError,TypeError,InvalidOperation):return {**base,'status':'version_amount_not_interpretable'}
            return {**base,'recorded_amount':format(amount,'.2f'),'status':'documented_version_candidate'}
        states=[v for v in self.statuses.get(tariff['seq'],[]) if v['effective_from']<=performed_on]
        if states:
            state=states[-1]
            base['status_version']=state
            _,usable=self._document(state)
            if not usable:return {**base,'selected':True,'status':'status_evidence_unverifiable'}
            if not state['active']:return {**base,'selected':True,'status':'withdrawn_reference'}
        versions=self.versions.get(tariff['seq'],[])
        eligible=[v for v in versions if v['effective_from']<=performed_on]
        value=eligible[-1] if eligible else None
        if value:
            future=[v['effective_from'] for v in versions if v['effective_from']>performed_on]
            base.update(selected=True,value_version=value,effective_from=value['effective_from'],
                        next_version_from=min(future) if future else None,
                        declared_currency='ARS',declared_unit=value['unit_label'])
            if value['code']!=tariff['code']:
                return {**base,'status':'version_identity_mismatch'}
            try:
                amount=Decimal(value['amount_ars'])
                if not amount.is_finite() or amount<=0 or amount*100!=(amount*100).to_integral_value():
                    return {**base,'status':'version_amount_not_interpretable'}
            except (ValueError,TypeError,InvalidOperation):
                return {**base,'status':'version_amount_not_interpretable'}
            base['recorded_amount']=format(amount,'.2f')
            doc,usable=self._document(value);base['document']=doc
            return {**base,'status':'documented_version_candidate' if usable else 'version_evidence_unverifiable'}
        start,end=tariff.get('valid_from'),tariff.get('valid_until')
        if not start:return base
        if performed_on<start or (end is not None and performed_on>end):
            return {**base,'status':'outside_declared_dates'}
        base.update(selected=True,effective_from=start,declared_until=end)
        amount=tariff.get('amount_cents')
        if type(amount) is not int or amount<0:
            return {**base,'status':'catalogue_amount_not_interpretable'}
        return {**base,'recorded_amount':format(Decimal(amount)/100,'.2f'),'status':'catalogue_candidate'}

"""Page-local exploratory comparisons. Never analysis, applicability or a debit."""
from collections import defaultdict
from decimal import Decimal
import json
import sqlite3
from .effective_hpc_values import EffectiveHpcValues
from .hpc_comparison import _compare
from .proposal_freshness import provider_basis
from .storage import read_verified
from .values_v1 import CUT, source_db, json_safe_catalog_amount

LIMIT='Referencia exploratoria; diferencia para revisión, no débito ni confirmación de aplicabilidad.'


def page_comparisons(conn, root, dataset_id, batch_id, rows, sheet, *, closed=False):
    def unavailable(status):
        return {r['source_row']:{'status':status,'recorded_amount':None,'declared_currency':None,
                'declared_unit':None,'candidate_total_if_ars_and_same_unit':None,
                'difference_ars_if_comparable':None,'use_limit':LIMIT} for r in rows}
    if not rows:return {}
    if closed:return unavailable('closed_revision_not_compared')
    scope=provider_basis(conn,batch_id)
    if root is None or not scope or scope['provider']!='HPC':
        return unavailable('hpc_provider_scope_missing')
    source=conn.execute("SELECT id,source_sha256,cut_label,source_version FROM source_registry WHERE id=? "
        "AND dataset_id=? AND kind='values' AND status='registered'",(scope['source_id'],dataset_id)).fetchone()
    if source is None:return unavailable('source_unavailable')
    if source['cut_label']!=CUT:return unavailable('unsupported_value_cut')
    try:
        catalog=source_db(read_verified(root,source['source_sha256']))
        tariffs=defaultdict(list)
        from .hpc_catalog_links import CatalogLinks
        links=CatalogLinks(catalog,source['id'],source['source_sha256'])
        from .calculated_nomenclature import CalculatedNomenclature,EMPTY_LINK_STATUSES
        calculated=CalculatedNomenclature(catalog,source['id'],source['source_sha256'])
        try:
            for r in catalog.execute("SELECT * FROM hpc_catalog_tariffs WHERE provider='HPC' ORDER BY seq"):
                raw=json.loads(r['data_json'])
                tariffs[r['code']].append({'seq':r['seq'],'code':r['code'],'provider':'HPC','practice_id':r['practice_id'],
                    'source_locator':f"hpc_catalog_tariffs.seq={r['seq']}",
                    'amount_cents':json_safe_catalog_amount(r['amount_cents']),'valid_from':r['valid_from'],
                    'valid_until':r['valid_until'],'document_source_id':r['source_id'],'document_page':r['page'],
                    'conditions':raw.get('conditions'),'calculation':raw.get('calculation')})
        finally:catalog.close()
        if conn.execute('PRAGMA user_version').fetchone()[0]>=29:
            from .local_hpc import tariffs as local_tariffs
            for item in local_tariffs(conn,dataset_id,source['id']):tariffs[item['code']].append(item)
        resolver=EffectiveHpcValues(conn,root,dataset_id,source['id'])
        from .agreement_declarations import ExploratoryResolver
        exploratory=ExploratoryResolver(resolver,source['source_sha256'])
        result={}
        for row in rows:
            fields={'E':row['code'],'G':row['quantity']}
            compared=_compare(row,fields,{},tariffs,source,sheet,resolver=exploratory,billing_unit=scope.get('billing_unit'))
            if compared['status']=='no_exact_hpc_tariff':
                compared['related_hpc_references']=links.suggestions(str(row['code'] or ''),row['practice_date'],exploratory)
                compared['related_comparison']=links.comparison(compared['related_hpc_references'],exploratory,row['practice_date'],row['quantity'],row['total_ars'],scope.get('billing_unit'))
                if compared['related_hpc_references']['status'] in EMPTY_LINK_STATUSES:
                    compared['calculated_nomenclature_references']=calculated.references(str(row['code'] or ''),row['practice_date'])
            effective=compared.get('effective_reference') or {}
            tariff=compared.get('tariff') or {}
            amount=effective.get('recorded_amount')
            if amount is None and not effective.get('value_version') and type(tariff.get('amount_cents')) is int and tariff['amount_cents']>=0:
                amount=format(Decimal(tariff['amount_cents'])/100,'.2f')
            result[row['source_row']]={**compared,'recorded_amount':amount,
                'declared_currency':effective.get('declared_currency'),'declared_unit':effective.get('declared_unit'),
                'use_limit':LIMIT}
        return result
    except (OSError,RuntimeError,ValueError,sqlite3.Error):
        return unavailable('source_or_evidence_unverifiable')

"""Exploratory code relationships only; never an authorization or selectable link.

Uses explicit coherent HPC catalog code rows sharing a practice identity. Prefixes,
zero padding, names and prices do not establish relationships in this module.
"""
from collections import defaultdict
import sqlite3

LIMIT = ('Coincidencia por enlace explícito del catálogo HPC, pendiente de cotejo. '
         'No acredita equivalencia clínica, fecha, autorización individual, cantidad ni débito.')

class CodeRelations:
    def __init__(self, catalog, source_id, sha256):
        self.source_id, self.sha256 = source_id, sha256
        self.codes, self.by_practice, self.neutral = defaultdict(list), defaultdict(list), defaultdict(list)
        self.available = False
        try:
            practices = defaultdict(list)
            for r in catalog.execute('SELECT seq,id FROM hpc_catalog_practices'):
                practices[r['id']].append(r['seq'])
            for r in catalog.execute("SELECT seq,practice_seq,practice_id,provider,code,kind FROM hpc_catalog_codes WHERE provider IN ('HPC','NOMENCLADOR')"):
                e = dict(r)
                e['coherent'] = bool(e['practice_id']) and practices[e['practice_id']] == [e['practice_seq']]
                if e['provider'] == 'HPC':
                    self.codes[e['code']].append(e)
                    self.by_practice[e['practice_id']].append(e)
                elif e['kind'] == 'nomenclador':
                    self.neutral[e['code']].append(e)
            self.available = True
        except (sqlite3.Error, KeyError, TypeError):
            pass

    def identity(self, code):
        rows = self.codes.get(code, [])
        if not rows or any(not r['coherent'] for r in rows): return None
        identities = {(r['practice_seq'], r['practice_id']) for r in rows}
        return next(iter(identities)) if len(identities) == 1 else None

    def aliases(self, code):
        identity = self.identity(code)
        if not self.available: return []
        if not identity:
            # Explicit neutral category rows can denote several distinct practices.
            # Retain each relationship as a category candidate, never an equivalence.
            neutral = self.neutral.get(code, [])
            if self.codes.get(code) or not neutral or any(not r['coherent'] for r in neutral): return []
            result = []
            for pid in sorted({r['practice_id'] for r in neutral}):
                sources = [r for r in neutral if r['practice_id'] == pid]
                pseq = sources[0]['practice_seq']
                for target in sorted({r['code'] for r in self.by_practice[pid]}):
                    if target == code or self.identity(target) != (pseq,pid): continue
                    result.append({'invoice_code':code,'authorization_code':target,
                        'practice_seq':pseq,'practice_id':pid,
                        'invoice_code_seqs':sorted(r['seq'] for r in sources),
                        'authorization_code_seqs':sorted(r['seq'] for r in self.codes[target]),
                        'source_id':self.source_id,'source_sha256':self.sha256,
                        'basis':'explicit_neutral_category_to_hpc',
                        'category_is_broad':len({r['practice_id'] for r in neutral})>1,
                        'equivalence_verified':False})
            return result
        result = []
        for target in sorted({r['code'] for r in self.by_practice[identity[1]]}):
            if target == code or self.identity(target) != identity: continue
            result.append({'invoice_code': code, 'authorization_code': target,
                'practice_seq': identity[0], 'practice_id': identity[1],
                'invoice_code_seqs': sorted(r['seq'] for r in self.codes[code]),
                'authorization_code_seqs': sorted(r['seq'] for r in self.codes[target]),
                'source_id': self.source_id, 'source_sha256': self.sha256,
                'basis': 'explicit_hpc_catalog_relationship', 'equivalence_verified': False})
        return result


def load_relations(conn, root, dataset_id, batch_id):
    from .proposal_freshness import provider_basis
    from .storage import read_verified
    from .values_v1 import source_db, CUT
    scope = provider_basis(conn, batch_id)
    if root is None or not scope or scope['provider'] != 'HPC': return None
    source = conn.execute("SELECT * FROM source_registry WHERE id=? AND dataset_id=? AND kind='values' AND status='registered'",
                          (scope['source_id'], dataset_id)).fetchone()
    if source is None or source['cut_label'] != CUT: return None
    catalog = None
    try:
        catalog = source_db(read_verified(root, source['source_sha256']))
        return CodeRelations(catalog, source['id'], source['source_sha256'])
    except (OSError, ValueError, RuntimeError, sqlite3.Error):
        return None
    finally:
        if catalog is not None: catalog.close()


def suggest(evidence, index, relations):
    from .authorization_matching import dni, _day, _resolutions
    from .authorization_signals import csv_order_history
    result = {'status': 'no_declared_catalog_candidate', 'candidates': [], 'candidate_count_total': 0,
              'use_limit': LIMIT, 'authorization_result': 'no_concluyente', 'selectable': False}
    if evidence['disposition'] != 'included' or evidence['issues']:
        return {**result, 'status': 'scope_unavailable_or_outside'}
    if relations is None or not relations.available:
        return {**result, 'status': 'catalog_relationships_unavailable'}
    affiliate = dni(evidence['invoice_fields'].get('C'))
    code = evidence['invoice_fields'].get('E')
    if not affiliate or not isinstance(code, str): return {**result, 'status': 'identity_or_code_unresolved'}
    matches = []
    for relation in relations.aliases(code):
        for capture, oi, order, ii, item, unique_order in index.get((affiliate, relation['authorization_code']), []):
            # No deduplication: every source order and item retains its identity.
            day = _day(item['service_date'])
            checks = {'identity': True, 'provider': order['provider'] == 'HPC' if order['provider'] else None,
                      'date': day == evidence['practice_date'] if day else None,
                      'unique_order': unique_order, 'complete_code': False, 'catalog_relationship': True}
            incompatible = checks['provider'] is False or checks['date'] is False
            matches.append({'capture_id': capture['id'], 'source_sha256': capture['source_sha256'],
                'locator': f'$.orders[{oi}].items[{ii}]', 'order_id': order['order_id'], 'item': item,
                'relation': relation, 'checks': checks,
                'compatibility': 'incompatible' if incompatible else 'needs_review',
                'resolution': _resolutions(order, item['item_id'], f'$.orders[{oi}]'),
                'csv_order_history': csv_order_history(order, capture), 'selectable': False})
    result.update(candidate_count_total=len(matches), candidates=matches[:200])
    if matches: result['status'] = 'catalog_candidates_need_review' if len(matches) <= 200 else 'catalog_candidate_limit'
    return result

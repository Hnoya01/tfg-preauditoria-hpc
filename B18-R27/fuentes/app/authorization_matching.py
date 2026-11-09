"""B02 correspondence evidence; no authorization, quantity or economic conclusions."""

from .revision_scope import revision_table, next_ordinal

from collections import Counter, defaultdict
from datetime import date, datetime
import hashlib
import json
import re
from uuid import uuid4

from .authorization_json import AuthorizationFormatError
from .authorization_source import parse_authorization_source
from .db import transaction
from .eligibility import effective_row
from .security import now_utc
from .service import Problem, authorized_dataset, check_version, event
from .storage import read_verified
from .csv_export import export_limitation


MATCH_VERSION = 'A1-match-v1'
AUTH_RULES = ('RN09', 'RN10', 'RN11', 'RN18')


def _dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _hash(value):
    return hashlib.sha256(_dump(value).encode()).hexdigest()


def dni(value):
    """RN05 recognized digit/slash shapes only; not a registry validation."""
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,20}(?:/[0-9]{1,20})?', value):
        return None
    if '/' not in value and value.startswith('0'):
        return None  # RN05 documents padding removal for the slash shape only.
    result = value.replace('/', '').lstrip('0')
    return result or None


def _day(value):
    if not isinstance(value, str):
        return None
    try:
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            return date.fromisoformat(value).isoformat()
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})?', value):
            return datetime.fromisoformat(value.replace('Z', '+00:00')).date().isoformat()
    except ValueError:
        pass
    return None


def _description(value):
    return ' '.join(value.split()).casefold() if isinstance(value, str) else ''


def _batch(conn, dataset_id, batch_id):
    row = conn.execute('SELECT i.id AS import_id, i.period, i.revision_id, r.state, r.version AS revision_version, '
                       f'b.source_sha256 FROM batches b JOIN {revision_table(conn, "invoice_imports")} i ON i.batch_id=b.id '
                       'JOIN revisions r ON r.id=i.revision_id WHERE b.id=? AND b.dataset_id=?',
                       (batch_id, dataset_id)).fetchone()
    if not row:
        raise Problem(404, 'Lote importado inexistente')
    return dict(row)


def _scope(conn, batch_id):
    return conn.execute(f'SELECT * FROM {revision_table(conn, "authorization_match_scopes")} WHERE batch_id=? ORDER BY ordinal DESC LIMIT 1',
                        (batch_id,)).fetchone()


def _captures(conn, root, dataset_id, ids, mode, *, budgets=False):
    if not 1 <= len(ids) <= 8 or len(set(ids)) != len(ids):
        raise Problem(422, 'Seleccionar entre una y ocho capturas distintas de flujos diferentes')
    selected, streams, issues = [], set(), []
    for identity in sorted(ids):
        row = conn.execute('SELECT c.*, u.source_sha256, s.manifest_sha256 FROM authorization_captures c '
                           'JOIN authorization_uploads u ON u.id=c.upload_id '
                           'JOIN source_registry s ON s.id=c.source_registry_id WHERE c.id=? AND c.dataset_id=?',
                           (identity, dataset_id)).fetchone()
        if not row:
            raise Problem(404, 'Captura inexistente en el conjunto')
        stream = (row['source_system'], row['stream_id'])
        if stream in streams:
            raise Problem(422, 'No sumar dos versiones del mismo flujo')
        streams.add(stream)
        if row['data_origin'] != ('synthetic' if mode == 'synthetic_demo' else 'real_unvalidated'):
            raise Problem(422, 'El modo del lote y el origen de las capturas deben coincidir')
        latest = conn.execute('SELECT id FROM authorization_captures WHERE dataset_id=? AND source_system=? '
                              'AND stream_id=? ORDER BY ordinal DESC LIMIT 1', (dataset_id, *stream)).fetchone()
        if latest['id'] != row['id']:
            issues.append('capture_replaced')
        budget_orders = {}
        try:
            original = read_verified(root, row['source_sha256'])
            manifest_bytes = read_verified(root, row['manifest_sha256'])
            manifest = json.loads(manifest_bytes)
            summary = json.loads(row['summary_json'])
            if (row['preview_sha256'] != row['manifest_sha256'] or
                    manifest.get('source_sha256') != row['source_sha256'] or
                    manifest.get('summary') != summary or
                    manifest.get('observations') != json.loads(row['observations_json'])):
                raise ValueError('stored interpretation metadata changed')
            if 'adapter_provenance' in summary:
                # The immutable derived A1 belongs to this capture, not today's parser.
                provenance = summary['adapter_provenance']
                if provenance.get('adapter') == 'hpc-platform-csv-v2':
                    issues.append('csv_reinterpretation_required')
                sha = provenance['output_sha256']
                if manifest.get('derived_a1_sha256') != sha:
                    raise ValueError('derived identity changed')
                derived = json.loads(read_verified(root, sha))
                if derived != json.loads(row['canonical_json']):
                    raise ValueError('stored canonical changed')
                if provenance.get('adapter') in ('hpc-platform-csv-v3','hpc-platform-csv-v4'):
                    from .csv_item_quantity import MARKER,LEADING_HINT
                    original_text=original.decode('utf-8-sig')
                    if MARKER.search(original_text) or LEADING_HINT.search(original_text):
                        current_parser=parse_authorization_source(original)
                        if current_parser.summary['adapter_provenance']['adapter'] in ('hpc-platform-csv-v4','hpc-platform-csv-v5') and current_parser.summary['adapter_provenance']['adapter']!=provenance['adapter']:
                            issues.append('csv_reinterpretation_required')
                if provenance.get('adapter') in ('hpc-platform-csv-v3','hpc-platform-csv-v4','hpc-platform-csv-v5'):
                    if parse_authorization_source(original).summary['adapter_provenance']['adapter'] == 'hpc-platform-csv-v6':
                        issues.append('csv_reinterpretation_required')
                if provenance.get('adapter') in ('hpc-platform-csv-v3','hpc-platform-csv-v4','hpc-platform-csv-v5','hpc-platform-csv-v6'):
                    if parse_authorization_source(original).summary['adapter_provenance']['adapter']=='hpc-platform-csv-v7':
                        issues.append('csv_reinterpretation_required')
                if budgets and row['source_system']=='HPC-CSV' and provenance.get('adapter') in tuple(f'hpc-platform-csv-v{v}' for v in range(3,8)):
                    from .csv_budget import source_budgets
                    budget_orders = source_budgets(original, derived['orders'])
            else:
                parsed = parse_authorization_source(original)
                if parsed.canonical != json.loads(row['canonical_json']) or parsed.manifest != manifest_bytes:
                    raise ValueError('interpretation changed')
        except (OSError, ValueError, RuntimeError, KeyError, TypeError, AuthorizationFormatError):
            issues.append('source_unverifiable')
        selected.append({**dict(row), '_budget_orders': budget_orders})
    return selected, sorted(set(issues))


def _context(conn, root, dataset_id, batch_id, *, budgets=False):
    scope = _scope(conn, batch_id)
    if not scope:
        return None, [], ['scope_missing']
    captures, issues = _captures(conn, root, dataset_id, json.loads(scope['capture_ids_json']), scope['mode'], budgets=budgets)
    return dict(scope), captures, issues


def save_scope(conn, root, token_hash, dataset_id, batch_id, expected_version, capture_ids, mode, note,
               synthetic_invoice_confirmed=False, *, csv_complete_from=None, csv_complete_until=None, after_prepare=None):
    _, dataset = authorized_dataset(conn, token_hash, dataset_id, 'reviewer')
    check_version(dataset, expected_version)
    batch = _batch(conn, dataset_id, batch_id)
    if batch['state'] == 'cerrada':
        raise Problem(409, 'Revisión cerrada')
    if mode not in ('synthetic_demo', 'real_unvalidated') or not 10 <= len(note.strip()) <= 2000:
        raise Problem(422, 'Indicar modo y fundamento de alcance de 10 a 2000 caracteres')
    if mode == 'synthetic_demo' and not synthetic_invoice_confirmed:
        raise Problem(422, 'Confirmar expresamente que el Excel de este lote también es ficticio')
    if mode == 'real_unvalidated' and conn.execute("SELECT 1 FROM authorization_match_scopes WHERE batch_id=? AND mode='synthetic_demo' LIMIT 1",(batch_id,)).fetchone():
        raise Problem(422, 'El lote fue declarado ficticio; no puede reclasificarse como real mediante otra selección')
    from .csv_export import export_range, validate_declaration
    selected, issues = _captures(conn, root, dataset_id, capture_ids, mode)
    declaration = validate_declaration(csv_complete_from, csv_complete_until, selected)
    if issues:
        raise Problem(409, 'Captura reemplazada o fuente no verificable; revisar selección')
    if after_prepare:
        after_prepare()
    with transaction(conn):
        user, current = authorized_dataset(conn, token_hash, dataset_id, 'reviewer')
        check_version(current, expected_version)
        if _batch(conn, dataset_id, batch_id)['state'] == 'cerrada':
            raise Problem(409, 'Revisión cerrada')
        previous = _scope(conn, batch_id)
        serialized = _dump(sorted(capture_ids))
        if previous and (previous['capture_ids_json'], previous['mode'], previous['note']) == (serialized, mode, note.strip()) and export_range(conn,previous['id']) == declaration:
            return {'id': previous['id'], 'dataset_version': expected_version, 'created': False}
        identity = str(uuid4())
        conn.execute('INSERT INTO authorization_match_scopes VALUES (?,?,?,?,?,?,?,?,?,?)',
                     (identity, dataset_id, batch_id, next_ordinal(conn, 'authorization_match_scopes', 'batch_id=?', (batch_id,)),
                      previous['id'] if previous else None, serialized, mode, note.strip(), user['id'], now_utc()))
        conn.execute('UPDATE datasets SET version=version+1 WHERE id=?', (dataset_id,))
        if declaration:
            conn.execute('INSERT INTO csv_export_ranges VALUES (?,?,?)',(identity,*declaration))
        event(conn, user['id'], 'authorization_scope_selected', 'batch', batch_id)
    return {'id': identity, 'dataset_version': expected_version + 1, 'created': True, 'analysis_started': False}


def _index(captures):
    index = defaultdict(list)
    for capture in captures:
        data = json.loads(capture['canonical_json'])
        order_ids = Counter(o['order_id'] for o in data['orders'] if o['order_id'])
        for oi, order in enumerate(data['orders']):
            affiliate = dni(order['affiliate_id'])
            for ii, item in enumerate(order['items']):
                if affiliate and item['full_code']:
                    index[(affiliate, item['full_code'])].append((capture, oi, order, ii, item, order_ids[order['order_id']] == 1))
    return index


def _resolutions(order, item_id, path):
    item_ids = Counter(i['item_id'] for i in order['items'] if i['item_id'])
    resolution_ids = Counter(r['resolution_id'] for r in order['resolutions'] if r['resolution_id'])
    records, scoped, unresolved = [], [], False
    for ri, resolution in enumerate(order['resolutions']):
        explicit = (resolution['scope'] in ('item', 'explicit_general') and bool(resolution['item_ids']) and
                    all(item_ids[i] == 1 for i in resolution['item_ids']))
        targets = item_id in resolution['item_ids'] if explicit else None
        if ri < 20:
            records.append({**resolution, 'reason': resolution['reason'][:500] if resolution['reason'] else resolution['reason'],
                            'reason_truncated': bool(resolution['reason'] and len(resolution['reason']) > 500),
                            'item_ids': resolution['item_ids'][:20], 'item_ids_total': len(resolution['item_ids']),
                            'item_ids_truncated': len(resolution['item_ids']) > 20,
                            'locator': f'{path}.resolutions[{ri}]', 'targets_item': targets})
        if not explicit:
            unresolved = True
        elif targets:
            scoped.append(resolution)
    states = {(r['status'], r['authorized_quantity'], r['unit']) for r in scoped}
    if len(states) > 1:
        state = 'apparent_conflict'
    elif unresolved or not scoped:
        state = 'unresolved'
    elif len(scoped) != 1 or not scoped[0]['resolution_id'] or resolution_ids[scoped[0]['resolution_id']] != 1:
        state = 'multiple_or_unidentified_resolutions'
    elif scoped[0]['status'] not in ('authorized', 'rejected', 'referred', 'pending', 'unknown'):
        state = 'uninterpreted_status'
    else:
        state = 'declared_' + scoped[0]['status']
    return {'state': state, 'records': records, 'global_status_declared': order['global_status'],
            'records_total': len(order['resolutions']), 'records_truncated': len(order['resolutions']) > 20,
            'global_status_is_item_approval': False, 'applicable_resolution_confirmed': False}


def _row_evidence(conn, batch, row, scope, index, issues):
    fields = json.loads(row['permitted_json'])
    edits = [dict(r) for r in conn.execute('SELECT field, value_json, latest_change_id FROM work_fields '
                                          'WHERE import_id=? AND source_row=? ORDER BY field', (batch['import_id'], row['source_row']))]
    for edit in edits:
        fields[edit['field']] = json.loads(edit['value_json'])
    eligible = effective_row(row, batch['period'])
    # Only identity/correspondence fields enter B02. Quantity and money remain B03/P06.
    basis = {'version': MATCH_VERSION, 'scope_id': scope['id'] if scope else None,
             'invoice_sha256': batch['source_sha256'], 'source_row': row['source_row'],
             'eligibility': eligible['disposition'], 'practice_date': row['practice_date'],
             'fields': {k: fields.get(k) for k in ('C', 'E', 'K')},
             'issues': issues}
    result = {'source_row': row['source_row'], 'invoice_locator': f'Hoja1!{row["source_row"]}',
              'invoice_fields': basis['fields'], 'practice_date': row['practice_date'],
              'disposition': eligible['disposition'], 'eligibility_reasons': eligible['eligibility_reasons'],
              'mode': scope['mode'] if scope else None, 'basis_sha256': _hash(basis),
              'state': 'outside_scope', 'candidates': [], 'issues': issues,
              'authorization_result': 'no_concluyente', 'coverage_verification': 'not_verified',
              'units_assigned': None, 'proposal_amount_ars': None, 'analysis_started': False}
    if eligible['disposition'] != 'included':
        return result
    if issues:
        result['state'] = 'requires_update' if scope else 'scope_missing'
        return result
    affiliate = dni(fields.get('C'))
    code = fields.get('E')
    if not affiliate or not isinstance(code, str) or not code:
        result['state'] = 'identity_or_code_unresolved'
        return result
    matches = index.get((affiliate, code), [])
    result['candidate_count_total'] = len(matches)
    from .authorization_signals import csv_order_history
    from .authorization_assessment import applicable_resolution
    for capture, oi, order, ii, item, unique_order in matches[:200]:
        path = f'$.orders[{oi}]'
        ids = Counter(i['item_id'] for i in order['items'] if i['item_id'])
        checks = {'identity': True, 'complete_code': True,
                  'provider': True if order['provider'] == 'HPC' else False if order['provider'] else None,
                  'date': _day(item['service_date']) == row['practice_date'] if _day(item['service_date']) else None,
                  'description': _description(item['description']) == _description(fields.get('K'))
                      if _description(item['description']) and _description(fields.get('K')) else None,
                  'unique_ids': bool(unique_order and item['item_id'] and ids[item['item_id']] == 1)}
        # A different description needs review, never a clinical equivalence by name.
        incompatible = checks['provider'] is False or checks['date'] is False
        compatible = all(v is True for v in checks.values())
        key = f'{capture["id"]}:{oi}:{ii}'
        result['candidates'].append({'key': key, 'capture_id': capture['id'], 'capture_ordinal': capture['ordinal'],
            'data_origin': capture['data_origin'], 'source_sha256': capture['source_sha256'],
            'locator': f'{path}.items[{ii}]', 'order_id': order['order_id'], 'item': item,
            'affiliate_original': order['affiliate_id'], 'provider': order['provider'],
            'checks': checks, 'compatibility': 'incompatible' if incompatible else 'compatible' if compatible else 'needs_review',
            'resolution': _resolutions(order, item['item_id'], path),
            'source_system': capture.get('source_system'),
            'item_resolution_state': applicable_resolution(order, item)['state'],
            'csv_order_history': csv_order_history(order, capture)})
    viable = [c for c in result['candidates'] if c['compatibility'] != 'incompatible']
    result['state'] = ('ambiguous' if len(viable) > 1 else
                       'unambiguous_candidate' if len(viable) == 1 and viable[0]['compatibility'] == 'compatible' else
                       'needs_review' if viable else 'incompatible_candidates' if result['candidates'] else 'no_authorization_located')
    if len(matches) > 200:
        result['state'] = 'candidate_limit'
        result['issues'] = [*issues, 'candidate_limit_200']
    return result


def _human(conn, batch, row, evidence):
    history = []
    for r in conn.execute(f'SELECT l.*, u.username AS actor_username FROM {revision_table(conn, "authorization_link_versions")} l '
                          'JOIN users u ON u.id=l.actor_id WHERE l.import_id=? AND l.source_row=? ORDER BY l.ordinal',
                          (batch['import_id'], row['source_row'])):
        record = dict(r)
        record['evidence_at_save'] = json.loads(record.pop('evidence_json'))
        history.append(record)
    current = None
    if history:
        current = {**history[-1], 'freshness': 'requires_update' if history[-1]['basis_sha256'] != evidence['basis_sha256'] or
                   evidence['issues'] or evidence['disposition'] != 'included' else 'current'}
    return {'current': current, 'history': history}


def correspondence(conn, root, token_hash, dataset_id, batch_id, source_row):
    _, dataset = authorized_dataset(conn, token_hash, dataset_id, 'reviewer')
    batch = _batch(conn, dataset_id, batch_id)
    row = conn.execute('SELECT * FROM invoice_rows WHERE import_id=? AND source_row=?', (batch['import_id'], source_row)).fetchone()
    if not row:
        raise Problem(404, 'Fila inexistente')
    scope, captures, issues = _context(conn, root, dataset_id, batch_id, budgets=batch['state'] != 'cerrada')
    index = _index(captures) if not issues else {}
    evidence = _row_evidence(conn, batch, row, scope, index, issues)
    from .authorization_catalog_candidates import load_relations, suggest
    if not issues and scope and batch['state'] != 'cerrada':
        from .csv_coverage import coverage
        evidence['csv_coverage'] = coverage(conn, dataset_id, batch_id, {source_row}, index,captures=captures,root=root).get((batch['import_id'],source_row))
    evidence['catalog_relationships'] = suggest(evidence, index, load_relations(conn, root, dataset_id, batch_id))
    from .csv_reviews import history as csv_review_history
    evidence['csv_review_history'] = csv_review_history(conn,batch['revision_id'],source_row)
    evidence['revision_id'] = batch['revision_id']
    result = {**evidence, 'human_link': _human(conn, batch, row, evidence), 'dataset_version': dataset['version'],
              'revision_version': batch['revision_version']}
    _, current = authorized_dataset(conn, token_hash, dataset_id, 'reviewer')
    check_version(current, dataset['version'])
    return result


def csv_queue_coverage(conn, root, dataset_id, batch_id, rows, *, source_context=None):
    if not root or not rows:
        return {}
    batch = _batch(conn,dataset_id,batch_id)
    if batch['state'] == 'cerrada':
        return {}
    scope,captures,issues = source_context or _context(conn,root,dataset_id,batch_id,budgets=True)
    if not scope or issues or not any(c['source_system']=='HPC-CSV' for c in captures):
        # Only an HPC invoice in the imaging workflow acquires a missing-source exception.
        from .proposal_freshness import provider_basis
        if (provider_basis(conn,batch_id) or {}).get('provider')!='HPC':
            return {}
        results={}
        for r in rows:
            if r.get('family')!='images':
                continue
            key=(batch['import_id'],r['source_row'])
            results[key]={'status':'coverage_pending','coverage_note':'Falta un CSV de Imágenes HPC vigente y verificable.'}
            if 'affiliate_id' in r and not dni(r['affiliate_id']):
                results[key]={'status':'unidentified','reason':'Afiliado no identificable · débito total propuesto'}
        return results
    from .csv_coverage import coverage
    images={r['source_row'] for r in rows if r.get('family')=='images'} if all('family' in r for r in rows) else None
    return coverage(conn,dataset_id,batch_id,{r['source_row'] for r in rows},_index(captures),
                    captures=captures,root=root,image_numbers=images)


def page_correspondence(conn, root, dataset_id, batch_id, source_rows, *, indexed_coverage=None, source_context=None):
    """Compact B02 evidence for one page, using one verified capture/index snapshot."""
    batch = _batch(conn, dataset_id, batch_id)
    scope, captures, issues = source_context or _context(conn, root, dataset_id, batch_id, budgets=batch['state'] != 'cerrada')
    index = _index(captures) if not issues else {}
    from .authorization_catalog_candidates import load_relations, suggest
    relations = load_relations(conn, root, dataset_id, batch_id)
    from .csv_coverage import coverage
    if indexed_coverage is None:
        indexed_coverage = (coverage(conn, dataset_id, batch_id, set(source_rows), index,captures=captures,root=root)
                        if scope and not issues and batch['state'] != 'cerrada'
                        and any(c['source_system']=='HPC-CSV' for c in captures) else {})
    result = {}
    for number in source_rows:
        row = conn.execute('SELECT * FROM invoice_rows WHERE import_id=? AND source_row=?',
                           (batch['import_id'], number)).fetchone()
        evidence = _row_evidence(conn, batch, row, scope, index, issues)
        related = suggest(evidence, index, relations)
        # Only the latest link is needed here; full history stays in the per-row endpoint.
        link = conn.execute(f'SELECT state,basis_sha256,candidate_key FROM {revision_table(conn, "authorization_link_versions")} '
                            'WHERE import_id=? AND source_row=? ORDER BY ordinal DESC LIMIT 1',
                            (batch['import_id'], number)).fetchone()
        from .authorization_signals import panel_signal
        result[number] = {'panel_signal': panel_signal(evidence, related, dict(link) if link else None), 'state': evidence['state'], 'mode': evidence['mode'],
            'catalog_candidate_count': related['candidate_count_total'],
            'catalog_candidate_status': related['status'],
            'candidate_count': evidence.get('candidate_count_total', 0),
            'compatible_count': sum(c['compatibility'] == 'compatible' for c in evidence['candidates']),
            'resolution_states': sorted({c['resolution']['state'] for c in evidence['candidates'] if c['compatibility'] != 'incompatible'}),
            'link_state': link['state'] if link else None,
            'link_freshness': ('requires_update' if link['basis_sha256'] != evidence['basis_sha256'] or evidence['issues'] or evidence['disposition'] != 'included' else 'current') if link else None,
            'authorization_result': 'no_concluyente', 'units_assigned': None, 'proposal_amount_ars': None}
        comparison = indexed_coverage.get((batch['import_id'],number))
        if comparison and (not evidence['issues'] or comparison['status'] in ('coverage_pending','unidentified')):
            result[number]['panel_signal']['csv_coverage'] = comparison
            if comparison.get('code_correspondence_ids'):
                result[number]['panel_signal']['presence'] = 'found'
    return result


def scope_history(conn, root, token_hash, dataset_id, batch_id):
    _, dataset = authorized_dataset(conn, token_hash, dataset_id, 'reviewer')
    _batch(conn, dataset_id, batch_id)
    scope, captures, issues = _context(conn, root, dataset_id, batch_id)
    history = [dict(r) for r in conn.execute(f'SELECT s.*, u.username AS actor_username FROM {revision_table(conn, "authorization_match_scopes")} s '
                                            'JOIN users u ON u.id=s.actor_id WHERE s.batch_id=? ORDER BY ordinal', (batch_id,))]
    for record in history:
        record['capture_ids'] = json.loads(record.pop('capture_ids_json'))
        from .csv_export import export_range
        record['csv_complete_range'] = export_range(conn,record['id'])
    _, current = authorized_dataset(conn, token_hash, dataset_id, 'reviewer')
    check_version(current, dataset['version'])
    return {'current': history[-1] if history else None, 'history': history, 'issues': issues,
            'dataset_version': dataset['version'], 'coverage_verification': 'not_verified',
            'csv_export_limitation': export_limitation(captures,issues) if scope else None, 'analysis_started': False}


def save_link(conn, root, token_hash, dataset_id, batch_id, source_row, expected_version,
              expected_revision_version, basis_sha256, state, candidate_key, note, *, after_prepare=None):
    evidence = correspondence(conn, root, token_hash, dataset_id, batch_id, source_row)
    if evidence['dataset_version'] != expected_version or evidence['revision_version'] != expected_revision_version or evidence['basis_sha256'] != basis_sha256:
        raise Problem(409, 'La correspondencia cambió; actualizar antes de guardar')
    if evidence['disposition'] != 'included' or evidence['issues']:
        raise Problem(409, 'Fila excluida o fuentes afectadas; no se puede confirmar vínculo')
    if state not in ('selected', 'unresolved') or not 10 <= len(note.strip()) <= 2000:
        raise Problem(422, 'Indicar estado y evidencia del vínculo')
    candidate = next((c for c in evidence['candidates'] if c['key'] == candidate_key), None)
    if state == 'selected' and (not candidate or candidate['compatibility'] != 'compatible'):
        raise Problem(422, 'No confirmar identidad, prestador, descripción o fecha sin correspondencia suficiente')
    if state == 'unresolved' and candidate_key is not None:
        raise Problem(422, 'Un vínculo no resuelto no selecciona candidato')
    batch = _batch(conn, dataset_id, batch_id)
    if after_prepare:
        after_prepare()
    with transaction(conn):
        user, dataset = authorized_dataset(conn, token_hash, dataset_id, 'reviewer')
        check_version(dataset, expected_version)
        current_batch = _batch(conn, dataset_id, batch_id)
        if current_batch['state'] == 'cerrada' or current_batch['revision_version'] != expected_revision_version:
            raise Problem(409, 'La revisión cambió o está cerrada')
        previous = conn.execute(f'SELECT * FROM {revision_table(conn, "authorization_link_versions")} WHERE import_id=? AND source_row=? '
                                'ORDER BY ordinal DESC LIMIT 1', (batch['import_id'], source_row)).fetchone()
        identity = str(uuid4())
        saved_evidence = {k: v for k, v in evidence.items() if k != 'human_link'}
        conn.execute('INSERT INTO authorization_link_versions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (identity, dataset_id, batch_id, batch['import_id'], source_row, next_ordinal(conn, 'authorization_link_versions', 'import_id=? AND source_row=?', (batch['import_id'], source_row)),
             previous['id'] if previous else None, state, candidate_key, basis_sha256, _dump(saved_evidence),
             note.strip(), user['id'], now_utc()))
        conn.execute('UPDATE datasets SET version=version+1 WHERE id=?', (dataset_id,))
        conn.execute('UPDATE revisions SET version=version+1 WHERE id=?', (batch['revision_id'],))
        event(conn, user['id'], 'authorization_link_reviewed', 'authorization_link', identity)
    return {'id': identity, 'dataset_version': expected_version+1, 'revision_version': expected_revision_version+1,
            'analysis_started': False, 'units_assigned': None, 'proposal_amount_ars': None}


def dependency_snapshot(conn, batch_id, import_id):
    if conn.execute('PRAGMA user_version').fetchone()[0] < 15:
        return {}
    scope = _scope(conn, batch_id)
    links = [dict(r) for r in conn.execute(f'SELECT source_row, id FROM {revision_table(conn, "authorization_link_versions")} l WHERE import_id=? '
             f'AND ordinal=(SELECT max(ordinal) FROM {revision_table(conn, "authorization_link_versions")} x WHERE x.import_id=l.import_id AND x.source_row=l.source_row) '
             'ORDER BY source_row', (import_id,))]
    result = {'authorization_scope_id': scope['id'] if scope else None, 'authorization_links': links} if scope or links else {}
    if conn.execute('PRAGMA user_version').fetchone()[0] >= 18:
        inputs = [dict(r) for r in conn.execute(f'SELECT source_row,kind,id FROM {revision_table(conn, "authorization_input_versions")} h WHERE import_id=? '
            f'AND ordinal=(SELECT max(ordinal) FROM {revision_table(conn, "authorization_input_versions")} x WHERE x.import_id=h.import_id AND x.source_row=h.source_row AND x.kind=h.kind) '
            'ORDER BY source_row,kind', (import_id,))]
        if inputs:
            result['authorization_inputs'] = inputs
    if conn.execute('PRAGMA user_version').fetchone()[0] >= 40:
        # Histories enter the dependency digest even when the latest pair is withdrawn.
        from .proposal_freshness import provider_basis
        provider = provider_basis(conn,batch_id) or {}
        records = [dict(r) for r in conn.execute(
            "SELECT id,source_id,invoice_code,authorization_code,active FROM hpc_code_correspondences WHERE source_id=? "
            "AND (invoice_code IN (SELECT json_extract(permitted_json,'$.E') FROM invoice_rows WHERE import_id=?) "
            "OR authorization_code IN (SELECT json_extract(permitted_json,'$.E') FROM invoice_rows WHERE import_id=?) "
            + ("OR relation_kind='qualifier' " if conn.execute('PRAGMA user_version').fetchone()[0]>=41 else "") + ") ORDER BY id",
            (provider.get('source_id'),import_id,import_id))]
        if records:
            result['code_correspondences'] = records
    return result


def export_correspondence_history(conn, root, dataset_id, batch_id):
    """Saved human evidence only; exporting never starts a matching/control run."""
    batch = _batch(conn, dataset_id, batch_id)
    scope, captures, issues = _context(conn, root, dataset_id, batch_id)
    index = _index(captures) if not issues else {}
    for row in conn.execute('SELECT * FROM invoice_rows WHERE import_id=? AND source_row IN '
                            f'(SELECT source_row FROM {revision_table(conn, "authorization_link_versions")} WHERE import_id=?) ORDER BY source_row',
                            (batch['import_id'], batch['import_id'])):
        evidence = _row_evidence(conn, batch, row, scope, index, issues)
        human = _human(conn, batch, row, evidence)
        yield {'source_row': row['source_row'], 'mode': scope['mode'] if scope else None,
               'human_link': human, 'authorization_result': 'no_concluyente',
               'units_assigned': None, 'proposal_amount_ars': None}

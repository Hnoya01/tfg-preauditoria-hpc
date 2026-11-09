"""B03 explicit, nonmonetary previews. Declarations never validate real sources."""

from .revision_scope import revision_table, next_ordinal

from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
import re
from uuid import uuid4

from .authorization_matching import (_batch, _context, _hash, _index, _row_evidence,
                                     dni, _dump)
from .db import transaction
from .eligibility import effective_row
from .security import now_utc
from .service import Problem, authorized_dataset, check_version, event


VERSION = 'B03-preview-v1'
LIMIT = 1000


def quantity(value):
    if type(value) is int:  # X1 preserves integral numeric cells, unlike A1 strings.
        value = str(value)
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', value) or len(value) > 64:
        return None
    try:
        number = Decimal(value)
        return number if number.is_finite() and number >= 0 else None
    except InvalidOperation:
        return None


def temporal(value):
    """Bounds express declared precision, never an invented event at midnight."""
    result = {'original': value, 'precision': 'unknown', 'zone': None, 'basis': None}
    if not isinstance(value, str):
        return result, None
    try:
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            day = date.fromisoformat(value)
            result.update(precision='day', basis='calendar_day')
            return result, (day, day, 'day')
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})?', value):
            return result, None
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        seconds = bool(re.search(r'T\d{2}:\d{2}:\d{2}', value))
        fraction = re.search(r'\.(\d+)', value)
        precision = 'fraction' if fraction else 'second' if seconds else 'minute'
        step = timedelta(microseconds=10 ** (6 - len(fraction[1]))) if fraction else timedelta(seconds=1 if seconds else 60)
        result.update(precision=precision, zone=parsed.strftime('%z') if parsed.tzinfo else None,
                      basis='instant' if parsed.tzinfo else 'local_time_without_zone')
        if parsed.tzinfo:
            parsed = parsed.astimezone(timezone.utc)
        return result, (parsed, parsed + step, 'zoned' if parsed.tzinfo else 'naive')
    except (ValueError, OverflowError):
        return result, None


def compare_time(authorization, incorporation):
    a, ab = temporal(authorization)
    b, bb = temporal(incorporation)
    result = {'authorization': a, 'incorporation': b, 'state': 'no_concluyente',
              'reason': 'Falta evidencia temporal interpretable de ambos eventos.'}
    if not ab or not bb:
        return result
    # Calendar dates can establish different days only with the same declared
    # calendar basis. Mixing a day with a zoned instant needs source timezone.
    if ab[2] == bb[2] == 'day':
        order = -1 if ab[0] < bb[0] else 1 if ab[0] > bb[0] else 0
    elif ab[2] == bb[2] == 'zoned':
        order = -1 if ab[1] <= bb[0] else 1 if bb[1] <= ab[0] else 0
    else:
        result['reason'] = 'Zona o base temporal insuficiente para ordenar ambos eventos.'
        return result
    if order:
        result.update(state='sin_observaciones' if order < 0 else 'con_indicios',
                      reason='Autorización anterior a la incorporación.' if order < 0 else 'Autorización posterior a la incorporación: revisar.')
        if order<0 and (bb[0]-ab[0]).days>60:
            result.update(state='con_indicios',reason='La incorporación supera los 60 días desde la autorización.')
    else:
        result['reason'] = 'Mismo día o precisiones superpuestas: no se puede establecer precedencia.'
    return result


def applicable_resolution(order, item):
    """Interpret complete declarations only; conflicting replacements stay open."""
    base = {'state': 'no_concluyente', 'reason': 'Resolución por aclarar.',
            'resolution': None, 'quantity': None, 'unit': None, 'locator': None}
    ids = Counter(i.get('item_id') for i in order['items'] if i.get('item_id'))
    resolution_ids = Counter(r.get('resolution_id') for r in order['resolutions'] if r.get('resolution_id'))
    scoped = []
    for pos, r in enumerate(order['resolutions']):
        targets = r['item_ids']
        if r['scope'] not in ('item', 'explicit_general') or not targets or len(set(targets)) != len(targets) or any(ids[x] != 1 for x in targets):
            return {**base, 'reason': 'Hay resoluciones cuyo alcance no se puede delimitar.'}
        if r['scope'] == 'item' and len(targets) != 1:
            return {**base, 'reason': 'Una resolución por ítem identifica varios ítems: requiere aclaración.'}
        if item['item_id'] in targets:
            scoped.append((pos, r))
    if len(scoped) != 1:
        return {**base, 'reason': 'Hay varias resoluciones aplicables o ninguna; no se elige por fecha ni por reemplazo declarado.'}
    pos, r = scoped[0]
    if not r['resolution_id'] or resolution_ids[r['resolution_id']] != 1 or r.get('supersedes_resolution_id'):
        return {**base, 'reason': 'Identidad o reemplazo de resolución pendiente de verificación.'}
    if r['status'] not in ('authorized', 'rejected', 'referred', 'pending', 'unknown'):
        return {**base, 'reason': 'Estado no interpretado.'}
    amount, unit = r['authorized_quantity'], r['unit']
    if r['scope'] == 'explicit_general':
        # RN09: express approval of the identified requested items. A common
        # aggregate amount must not be copied to each practice.
        if r['authorized_quantity'] is not None or r['unit'] is not None:
            return {**base, 'reason': 'Cantidad general agregada sin reparto inequívoco por ítem.'}
        amount, unit = item['requested_quantity'], item['unit']
    return {**base, 'state': 'declared_' + r['status'], 'resolution': r,
            'quantity': amount if quantity(amount) is not None else None, 'unit': unit,
            'locator': f'resolutions[{pos}]',
            'reason': 'Declaración individual delimitada.' if r['scope'] == 'item' else 'Autorización general expresa de los ítems y cantidades solicitados identificados.'}


def input_history(conn, import_id, number):
    result = {}
    for kind in ('incorporation', 'quantity_unit'):
        rows = [dict(r) for r in conn.execute(f'SELECT h.*,u.username AS actor_username FROM {revision_table(conn, "authorization_input_versions")} h '
            'JOIN users u ON u.id=h.actor_id WHERE import_id=? AND source_row=? AND kind=? ORDER BY ordinal',
            (import_id, number, kind))]
        result[kind] = {'current': rows[-1] if rows else None, 'history': rows}
    return result


def save_input(conn, root, token_hash, dataset_id, batch_id, source_row, expected_version,
               expected_revision_version, kind, state, value, provenance, locator, *, after_prepare=None):
    _, ds = authorized_dataset(conn, token_hash, dataset_id, 'reviewer')
    check_version(ds, expected_version)
    batch = _batch(conn, dataset_id, batch_id)
    scope, _, issues = _context(conn, root, dataset_id, batch_id)
    row = conn.execute('SELECT * FROM invoice_rows WHERE import_id=? AND source_row=?', (batch['import_id'], source_row)).fetchone()
    if not row:
        raise Problem(404, 'Fila inexistente')
    if batch['state'] == 'cerrada' or batch['revision_version'] != expected_revision_version or issues or not scope or effective_row(row, batch['period'])['disposition'] != 'included':
        raise Problem(409, 'Revisión, ámbito o fuentes pendientes de actualizar')
    if kind not in ('incorporation', 'quantity_unit') or state not in ('declared', 'withdrawn'):
        raise Problem(422, 'Tipo o estado no admitido')
    if not 10 <= len(provenance.strip()) <= 2000 or not 3 <= len(locator.strip()) <= 300:
        raise Problem(422, 'Registrar procedencia y localizador de la declaración')
    if state == 'withdrawn':
        if value is not None:
            raise Problem(422, 'Retirar no conserva un valor operativo')
    elif not isinstance(value, str) or not value.strip() or len(value) > (80 if kind == 'incorporation' else 100):
        raise Problem(422, 'Indicar valor declarado')
    # Unknown temporal text is preservable information, not a format failure.
    origin = 'synthetic' if scope['mode'] == 'synthetic_demo' else 'real_unvalidated'
    if after_prepare:
        after_prepare()
    with transaction(conn):
        user, current = authorized_dataset(conn, token_hash, dataset_id, 'reviewer')
        check_version(current, expected_version)
        b = _batch(conn, dataset_id, batch_id)
        if b['state'] == 'cerrada' or b['revision_version'] != expected_revision_version:
            raise Problem(409, 'La revisión cambió o se cerró')
        _, _, current_issues = _context(conn, root, dataset_id, batch_id)
        if current_issues:
            raise Problem(409, 'La fuente dejó de ser verificable')
        previous = conn.execute(f'SELECT * FROM {revision_table(conn, "authorization_input_versions")} WHERE import_id=? AND source_row=? AND kind=? ORDER BY ordinal DESC LIMIT 1', (batch['import_id'], source_row, kind)).fetchone()
        identity, created = str(uuid4()), now_utc()
        content = {'id': identity, 'import_id': batch['import_id'], 'source_row': source_row, 'kind': kind,
                   'state': state, 'value': value, 'provenance': provenance.strip(), 'locator': locator.strip(),
                   'data_origin': origin, 'previous_id': previous['id'] if previous else None,
                   'actor_id': user['id'], 'created_at': created}
        conn.execute('INSERT INTO authorization_input_versions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (identity, dataset_id, batch_id, batch['import_id'], source_row, kind, next_ordinal(conn, 'authorization_input_versions', 'import_id=? AND source_row=? AND kind=?', (batch['import_id'], source_row, kind)),
             content['previous_id'], state, value, content['provenance'], content['locator'], origin,
             _hash(content), user['id'], created))
        conn.execute('UPDATE datasets SET version=version+1 WHERE id=?', (dataset_id,))
        conn.execute('UPDATE revisions SET version=version+1 WHERE id=?', (batch['revision_id'],))
        event(conn, user['id'], 'authorization_input_declared', 'authorization_input', identity)
    return {'id': identity, 'dataset_version': expected_version+1, 'revision_version': expected_revision_version+1,
            'analysis_started': False, 'source_validation': 'not_verified', 'proposal_amount_ars': None}


def _current_inputs(conn, import_id, number):
    return {kind: entry['current'] for kind, entry in input_history(conn, import_id, number).items()}


def _selected(conn, batch, row, evidence):
    link = conn.execute(f'SELECT * FROM {revision_table(conn, "authorization_link_versions")} WHERE import_id=? AND source_row=? ORDER BY ordinal DESC LIMIT 1', (batch['import_id'], row['source_row'])).fetchone()
    if not link or link['state'] != 'selected' or link['basis_sha256'] != evidence['basis_sha256'] or evidence['issues']:
        return None
    return next((c for c in evidence['candidates'] if c['key'] == link['candidate_key'] and c['compatibility'] == 'compatible'), None)


def _preview(conn, root, dataset_id, batch_id, number):
    batch = _batch(conn, dataset_id, batch_id)
    row = conn.execute('SELECT * FROM invoice_rows WHERE import_id=? AND source_row=?', (batch['import_id'], number)).fetchone()
    if not row:
        raise Problem(404, 'Fila inexistente')
    scope, captures, issues = _context(conn, root, dataset_id, batch_id)
    index = _index(captures) if not issues else {}
    evidence = _row_evidence(conn, batch, row, scope, index, issues)
    history = input_history(conn, batch['import_id'], number)
    result = {'version': VERSION, 'source_row': number, 'mode': scope['mode'] if scope else None,
              'source_validation': 'not_verified', 'coverage_verification': 'not_verified',
              'preview_only': True, 'analysis_started': False, 'units_assigned': None, 'proposal_amount_ars': None,
              'tp_control_results': {'RN09': 'no_concluyente', 'RN10': 'no_concluyente', 'RN11': 'no_concluyente'},
              'inputs': history, 'resolution': {'state': 'no_concluyente', 'reason': 'Se necesita un vínculo humano actual e inequívoco.'},
              'quantity': {'state': 'no_concluyente', 'reason': 'Cantidad no comprobada.', 'authorized': None, 'billed_joint': None, 'members': [], 'limitations': []},
              'temporal': compare_time(None, None)}
    if evidence['disposition'] != 'included':
        result['resolution']['reason'] = 'Fila excluida o con ámbito indeterminado.'
        return result
    if issues:
        result['resolution']['reason'] = 'Falta seleccionar fuentes vigentes o actualizar las que dejaron de ser verificables.'
        return result
    candidate = _selected(conn, batch, row, evidence)
    if not candidate:
        return result
    cap = next(c for c in captures if c['id'] == candidate['capture_id'])
    oi, ii = (int(x) for x in candidate['key'].rsplit(':', 2)[1:])
    order = json.loads(cap['canonical_json'])['orders'][oi]
    resolution = applicable_resolution(order, order['items'][ii])
    result['resolution'] = resolution
    current_time = history['incorporation']['current']
    result['temporal'] = compare_time(resolution['resolution']['decided_at'] if resolution['resolution'] and resolution['state'] == 'declared_authorized' else None,
        current_time['value'] if current_time and current_time['state'] == 'declared' and current_time['data_origin'] == cap['data_origin'] else None)
    if resolution['state'] != 'declared_authorized':
        result['quantity']['reason'] = 'La resolución no permite establecer cantidad autorizada.'
        return result
    q = result['quantity']
    q['authorized'], q['unit'] = resolution['quantity'], resolution['unit']
    if quantity(resolution['quantity']) is None or not resolution['unit']:
        q['reason'] = 'Cantidad o unidad autorizada desconocida; no se sustituye por cero.'
        return result
    target_dni, target_code = dni(evidence['invoice_fields']['C']), evidence['invoice_fields']['E']
    total, seen, unresolved = Decimal(0), 0, set()
    # One invoice import per original hash; histories/contrast are not new rows.
    for record in conn.execute(f'SELECT i.batch_id,b.original_name FROM {revision_table(conn, "invoice_imports")} i JOIN batches b ON b.id=i.batch_id WHERE b.dataset_id=? ORDER BY i.id', (dataset_id,)):
        b = _batch(conn, dataset_id, record['batch_id'])
        s, cs, errors = _context(conn, root, dataset_id, record['batch_id'])
        ix = _index(cs) if not errors else {}
        originals = conn.execute("SELECT r.* FROM invoice_rows r WHERE import_id=? AND COALESCE((SELECT json_extract(w.value_json,'$') FROM work_fields w WHERE w.import_id=r.import_id AND w.source_row=r.source_row AND w.field='E'),json_extract(r.permitted_json,'$.E'))=? ORDER BY source_row", (b['import_id'], target_code))
        for original in originals:
            if effective_row(original, b['period'])['disposition'] != 'included':
                continue
            f = json.loads(original['permitted_json'])
            f.update({w['field']: json.loads(w['value_json']) for w in conn.execute('SELECT field,value_json FROM work_fields WHERE import_id=? AND source_row=?', (b['import_id'], original['source_row']))})
            identity = dni(f.get('C'))
            if identity != target_dni and (identity is not None or original['practice_date'] != row['practice_date']):
                continue
            seen += 1
            if seen > LIMIT:
                unresolved.add('candidate_limit_1000')
                break
            if identity is None:
                unresolved.add('related_identity_unresolved')
                continue
            ev = _row_evidence(conn, b, original, s, ix, errors)
            if ev['issues'] and not errors:
                unresolved.add('association_candidates_incomplete')
                continue
            possible = [c for c in ev['candidates'] if c['compatibility'] != 'incompatible']
            # Different extractions with similar item IDs do not establish MD04
            # identity. Keep them separate and block allocation pending evidence.
            overlap = [c for c in possible if c['key'] == candidate['key'] or c['capture_id'] != candidate['capture_id']]
            if errors:
                if original['practice_date'] == row['practice_date']:
                    unresolved.add('other_lot_scope_unresolved')
                continue
            if not overlap:
                continue
            if any(c['key'] != candidate['key'] for c in overlap):
                unresolved.add('coverage_identity_between_captures_unverified')
                continue
            chosen = _selected(conn, b, original, ev)
            if chosen and chosen['key'] != candidate['key']:
                continue  # A current human choice of a different item is not an unresolved link.
            if not chosen:
                unresolved.add('pending_or_ambiguous_association')
                continue
            inputs = _current_inputs(conn, b['import_id'], original['source_row'])
            unit = inputs['quantity_unit']
            valid_unit = unit and unit['state'] == 'declared' and unit['value'] == resolution['unit'] and unit['data_origin'] == cap['data_origin']
            amount = quantity(f.get('G'))
            q['members'].append({'batch_id': record['batch_id'], 'batch_name': record['original_name'], 'import_id': b['import_id'], 'source_row': original['source_row'],
                                 'locator': f'Hoja1!{original["source_row"]}', 'billed': f.get('G'), 'unit': unit['value'] if unit and unit['state']=='declared' else None,
                                 'revision_version': b['revision_version'], 'revision_state': b['state']})
            if not valid_unit or amount is None:
                unresolved.add('billed_quantity_or_unit_unverified')
            else:
                total += amount
        if seen > LIMIT:
            break
    q['limitations'] = sorted(unresolved)
    if unresolved:
        q['reason'] = 'Hay asociaciones, identidades de cobertura o unidades pendientes. No se asignan ni liberan unidades.'
    else:
        q.update(state='con_indicios' if total > quantity(resolution['quantity']) else 'sin_observaciones',
                 billed_joint=str(total), reason='Cantidad conjunta mayor que la autorizada declarada.' if total > quantity(resolution['quantity']) else 'Cantidad conjunta dentro de lo autorizado declarado.')
    return result


def preview(conn, root, token_hash, dataset_id, batch_id, source_row, *, after_read=None):
    conn.execute('BEGIN')
    try:
        _, ds = authorized_dataset(conn, token_hash, dataset_id, 'reviewer')
        batch = _batch(conn, dataset_id, batch_id)
        result = _preview(conn, root, dataset_id, batch_id, source_row)
        result.update(dataset_version=ds['version'], revision_version=batch['revision_version'], revision_state=batch['state'])
        result['basis_sha256'] = _hash(result)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    if after_read:
        after_read()
    _, current = authorized_dataset(conn, token_hash, dataset_id, 'reviewer')
    check_version(current, ds['version'])
    if _batch(conn, dataset_id, batch_id)['revision_version'] != batch['revision_version']:
        raise Problem(409, 'La revisión cambió durante la consulta')
    return result

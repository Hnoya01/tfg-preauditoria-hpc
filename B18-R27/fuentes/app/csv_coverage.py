"""Read-only administrative comparison of selected HPC CSV items and billed dates."""
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import json
import hashlib

from .authorization_assessment import applicable_resolution, compare_time
from .eligibility import effective_row

from .csv_export import ExportCoverage, VALID_DAYS


def movement_actor(record):
    from .hpc_csv_resolutions import EVENT
    ident = str(record.get('resolution_id','')).split(':')
    if 'event' not in ident:
        return None
    try:
        line = record['reason'].splitlines()[int(ident[ident.index('event')+1])]
    except (IndexError,KeyError,ValueError):
        return None
    match = EVENT.fullmatch(line)
    return match[2].strip() if match else None


def dated_item(capture, order_pos, order, item_pos, item, unique_order):
    resolution = applicable_resolution(order, item)
    record = resolution.get('resolution') or {}
    try:
        day = date.fromisoformat(record['decided_at'][:10])
    except (KeyError, TypeError, ValueError):
        day = None
    from .csv_movements import rejection_kind
    from .hpc_csv_resolutions import EVENT
    import re
    comment = ''
    parts = str(record.get('resolution_id','')).split(':')
    if 'event' in parts:
        try:
            line = record['reason'].splitlines()[int(parts[parts.index('event')+1])]
            movement = EVENT.fullmatch(line)
            comment = movement[4] if movement else ''
        except (IndexError,ValueError,KeyError):
            pass
    prior_id = re.search(r'\b(?:orden|autorizaci[oó]n)\s+(?:n[°º.]?\s*|ID\s*)?(\d+)\b',comment,re.I)
    return {
        'outcome': ('referral' if re.search(r'\b(?:otro prestador|otra instituci[oó]n)\b',comment,re.I)
                    and not re.search(r'\bno (?:se )?deriva',comment,re.I) else 'check_referral') if resolution['state']=='declared_referred'
                    else rejection_kind(comment) if resolution['state']=='declared_rejected' else None,
        'prior_order_id': prior_id[1] if prior_id else None,
        'reference': (capture['id'], order_pos, item_pos), 'full_code':item['full_code'],
        'locator': f'$.orders[{order_pos}].items[{item_pos}]',
        'sha256': capture['source_sha256'], 'day': day, 'decided_at': record.get('decided_at'),
        'order_id': order['order_id'], 'origin': capture.get('data_origin'), 'movement_actor':movement_actor(record),
        'authorized_units': int(record['authorized_quantity']) if record.get('unit')=='práctica'
            and str(record.get('authorized_quantity','')).isascii() and str(record.get('authorized_quantity','')).isdigit()
            else (None if record.get('authorized_quantity') is not None or record.get('unit') is not None else 1),
        'authorized': resolution['state'] == 'declared_authorized' and record.get('scope') == 'item',
        'rejected': resolution['state'] == 'declared_rejected' and record.get('scope') == 'item',
        'unique': unique_order and bool(item['item_id']) and
                  sum(x['item_id'] == item['item_id'] for x in order['items']) == 1,
        'description': item.get('description'), 'provider': order.get('provider'),
        'budget': capture.get('_budget_orders', {}).get(order['order_id']), 'affiliate': order.get('affiliate_id'),
    }


def billed_quantity(row):
    try:
        qty=Decimal(str(row['quantity']))
        if qty.is_finite() and qty>=1 and qty==qty.to_integral_value():
            return int(qty)
    except InvalidOperation:
        pass
    return None


def covered_status(covered,billed,capacity):
    if covered==billed:
        return 'one_unit_supported' if capacity==1 else 'units_supported'
    return 'one_unit_only' if covered==1 else 'units_partial'


def csv_sequence(item, row):
    result = _sequence(item, row)
    inc = row.get('incorporation') or {}
    if result['state']=='sin_observaciones' and inc.get('value') and item.get('day'):
        elapsed = (date.fromisoformat(inc['value'][:10])-item['day']).days
        result['elapsed_days']=elapsed
        if elapsed>VALID_DAYS:
            result.update(state='con_indicios',reason='La incorporación supera los 60 días desde la autorización.')
    return result


def _sequence(item, row):
    raw = item.get('decided_at') or (item['day'] and item['day'].isoformat())
    inc = row.get('incorporation') or {}
    value = inc.get('value') if inc.get('origin') == item.get('origin') else None
    result = compare_time(raw, value)
    if result['state'] == 'no_concluyente' and raw and value:
        try:
            first, second = datetime.fromisoformat(raw), datetime.fromisoformat(value)
        except (TypeError,ValueError):
            return result
        if first.tzinfo is None and second.tzinfo is None:
            if first.date() != second.date():
                order = compare_time(first.date().isoformat(), second.date().isoformat())
            elif 'T' in raw and 'T' in value:
                from .authorization_assessment import temporal
                a, b = temporal(raw)[1], temporal(value)[1]
                if a[1] <= b[0]:
                    order = {'state':'sin_observaciones','reason':'Autorización anterior a la incorporación.'}
                elif b[1] <= a[0]:
                    order = {'state':'con_indicios','reason':'Autorización posterior a la incorporación.'}
                else:
                    return result
            else:
                return result
            result.update(state=order['state'],reason=order['reason'])
    return result


def practice_identity(value):
    from .authorization_matching import _description
    return value.get('match_identity') or _description(value['description'])


def assess_group(rows, items):
    if any(r.get('directed_rules') for r in rows):
        from .csv_allocation import assess
        return assess(rows,items)
    from .authorization_matching import _description
    by_day = defaultdict(list)
    for row in rows:
        by_day[row['day']].append(row)
    usage=defaultdict(list)
    spent=defaultdict(int)
    uncertain,results=set(),{}
    for day in sorted(by_day):
        group = by_day[day]
        if len(group)>1:
            quantities=[billed_quantity(r) for r in group]
            demand=sum(quantities) if None not in quantities and not any(r['uncertain'] or r.get('hpc') is False for r in group) else None
            descriptions={practice_identity(r) for r in group}
            same_occasion = (all('billed_order' not in r for r in group) or
                len({r.get('billed_order') for r in group})==1 and all(r.get('billed_order') for r in group))
            opening_spent=dict(spent)
        eligible = [i for i in items if i['day'] is None or (day - i['day']).days <= VALID_DAYS]
        for row in group:
            key = row['key']
            if not eligible:
                results[key] = {'status': 'outside_window', 'valid_days': VALID_DAYS}
                continue
            available = [i for i in eligible if not usage[i['reference']] or
                         (usage[i['reference']][0]['performed_on'] == day.isoformat() and
                          spent[i['reference']] < (i.get('authorized_units',1) or 0))]
            prior = [i for i in available if not i['day'] or i['day'] <= day]
            if prior:
                available = prior + [i for i in available if i not in prior and csv_sequence(i,row)['state']=='sin_observaciones']
            if not available:
                if (row['uncertain'] or not _description(row['description'])
                        or any(practice_identity(i) != practice_identity(row) for i in eligible)):
                    results[key] = {'status': 'needs_review'}
                    continue
                previous = [r for i in eligible for r in usage[i['reference']]]
                results[key] = {'status': 'already_used', 'previous_rows': previous}
                continue
            item = available[0]
            capacity=item.get('authorized_units',1)
            if len(group)>1:
                # Same-day rows can all be covered only if allocation order is irrelevant.
                # Include units already assigned on this day when checking the group's opening balance.
                same_day_certain=(capacity is not None and capacity>1 and item['authorized']
                    and same_occasion and demand is not None and descriptions=={practice_identity(item)}
                    and demand<=capacity-opening_spent.get(item['reference'],0))
            else:
                same_day_certain=True
            if (len(available) != 1 or not same_day_certain or row['uncertain']
                    or not item['unique'] or item['provider'] != 'HPC' or not item['day']
                    or not _description(item['description'])
                    or practice_identity(row) != practice_identity(item)
                    or (capacity and capacity>1 and row.get('hpc') is False) or item['reference'] in uncertain):
                uncertain.update(i['reference'] for i in available)
                results[key] = {'status': 'needs_review'}
                continue
            basis = {'authorization_date': item['day'].isoformat(), 'performed_on': day.isoformat(),
                     'elapsed_days': (day-item['day']).days, 'valid_days': VALID_DAYS,
                     'locator': item['locator'], 'source_sha256': item['sha256']}
            if item.get('order_id'):
                basis['order_id'] = item['order_id']
                if item.get('movement_actor'):basis['movement_actor']=item['movement_actor']
            if (item['day'] > day or row.get('incorporation')) and (item['authorized'] or item['rejected']):
                temporal = csv_sequence(item,row)
                basis['temporal'] = temporal
                if temporal['state'] != 'sin_observaciones':
                    if temporal['state']=='no_concluyente':
                        uncertain.add(item['reference'])
                    results[key] = {**basis, 'status': 'temporal_late' if temporal['state']=='con_indicios' else 'temporal_pending'}
                    continue
            if item['rejected']:
                results[key] = {**basis, 'status': 'declared_rejected'}
            elif not item['authorized']:
                results[key] = {'status': 'needs_review'}
            else:
                billed=billed_quantity(row)
                if billed is None or not capacity or capacity<1:
                    uncertain.add(item['reference'])
                    results[key] = {'status':'needs_review'}
                    continue
                covered=min(billed,capacity-spent[item['reference']])
                receipt={'batch_id':row['batch_id'],'source_row':key[1],'performed_on':day.isoformat(),
                         'authorization_date':item['day'].isoformat()}
                if capacity>1:
                    receipt['units']=covered
                usage[item['reference']].append(receipt)
                spent[item['reference']]+=covered
                results[key]={**basis,'status':covered_status(covered,billed,capacity)}
                if billed>1 or capacity>1:
                    results[key]['billed_units']=billed
                if capacity>1:
                    results[key].update(order_units=capacity,covered_units=covered)
    return results


def attach_review_evidence(group, results, scope, patient_code, reviewed):
    """Bind 'already used' to this practice, its predecessor and the selected capture."""
    rows = {(row['batch_id'], row['key'][1]):row for row in group}
    for row in group:
        signal = results[row['key']]
        if signal['status'] != 'already_used' or row['batch_id'] != scope['batch_id']:
            continue
        previous = [rows[(p['batch_id'], p['source_row'])] for p in signal['previous_rows']]
        basis = [scope['id'], patient_code, signal['previous_rows'],
                 [(r['key'], r['day'].isoformat(), r['quantity'], r['description'], r['scope_id'], r['edits'])
                  for r in [row, *previous]]]
        digest = hashlib.sha256(json.dumps(basis,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        signal['review_basis'] = digest
        signal['reviewed'] = (row['key'][1],digest) in reviewed


def coverage(conn, dataset_id, batch_id, numbers, index, *, captures, root, image_numbers=None):
    from .authorization_matching import dni, _scope
    from .code_correspondences import Correspondences
    correspondence = Correspondences(conn,root,dataset_id,batch_id)
    index = correspondence.index(index)
    # Look beyond the current page and period. Each lot contributes only its current revision.
    all_groups = defaultdict(list)
    overrides = defaultdict(dict)
    edit_ids = defaultdict(list)
    for edit in conn.execute('SELECT w.* FROM work_fields w JOIN current_invoice_imports i ON i.id=w.import_id '
                             'JOIN batches b ON b.id=i.batch_id WHERE b.dataset_id=?', (dataset_id,)):
        key = (edit['import_id'],edit['source_row'])
        overrides[key][edit['field']] = json.loads(edit['value_json'])
        if edit['field'] in ('C','E','G','K'):
            edit_ids[key].append((edit['field'],edit['latest_change_id']))
    incorporations = {}
    for record in conn.execute("""SELECT a.import_id,a.source_row,a.value,a.data_origin,a.state
          FROM current_authorization_input_versions a JOIN batches b ON b.id=a.batch_id
          WHERE b.dataset_id=? AND a.kind='incorporation' ORDER BY a.ordinal""",(dataset_id,)):
        incorporations[(record['import_id'],record['source_row'])] = (
            {'value':record['value'],'origin':record['data_origin']} if record['state']=='declared' else None)
    linked_rows = {(r['import_id'],r['source_row']) for r in conn.execute(
        'SELECT l.import_id,l.source_row FROM current_authorization_link_versions l '
        'JOIN batches b ON b.id=l.batch_id WHERE b.dataset_id=?', (dataset_id,))}
    wanted, uncertain_keys = set(), set()
    scope = _scope(conn, batch_id)
    if not scope:
        return {}
    scope_ids = set(json.loads(scope['capture_ids_json']))
    reviewed = {(r['source_row'], r['evidence_sha256']) for r in conn.execute(
        'SELECT r.source_row,r.evidence_sha256 FROM csv_coverage_reviews r JOIN current_invoice_imports i '
        'ON r.revision_id=i.revision_id WHERE i.batch_id=?',(batch_id,))}
    from .authorization_catalog_candidates import load_relations
    assessment=ExportCoverage(conn,scope,captures,index,lambda: load_relations(conn,root,dataset_id,batch_id))
    result = {}
    families=None
    def in_images(number,fields):
        nonlocal families
        if image_numbers is not None:
            return number in image_numbers
        from .practice_families import catalog_families,classify_family
        if families is None:
            from .display_categories import add_categories
            from .authorization_matching import _batch
            areas,names,classification=catalog_families(conn,root,dataset_id)
            if not classification['source_unavailable']:
                add_categories(conn,root,dataset_id,{**_batch(conn,dataset_id,batch_id),'batch_id':batch_id},areas)
            families=areas,names
        areas,names=families
        return classify_family(fields.get('E'),areas,fields.get('K'),names)[0]=='images'
    from .proposal_freshness import provider_basis
    target_hpc=(provider_basis(conn,batch_id) or {}).get('provider')=='HPC'
    component_rows=[];main_rows={};item_lookup={}
    for lot in conn.execute('SELECT i.* FROM current_invoice_imports i JOIN batches b ON b.id=i.batch_id WHERE b.dataset_id=?', (dataset_id,)):
        provider = provider_basis(conn,lot['batch_id'])
        if provider and provider['provider']!='HPC':
            continue
        lot_scope = _scope(conn,lot['batch_id'])
        same_scope = lot_scope and set(json.loads(lot_scope['capture_ids_json'])) == scope_ids
        changed=[n for (imp,n),edits in overrides.items() if imp==lot['id'] and 'E' in edits]
        requested=set(numbers) if lot['batch_id']==batch_id else set()
        codes={code for _,code in index}.union(correspondence.codes,correspondence.components)
        codes.update(r['parent_code'] for r in correspondence.components.values())
        plausible=conn.execute("""SELECT * FROM invoice_rows WHERE import_id=? AND
            (source_row IN (SELECT value FROM json_each(?)) OR
             json_extract(permitted_json,'$.E') IN (SELECT value FROM json_each(?)))""",
            (lot['id'],json.dumps(list(requested.union(changed))),json.dumps(list(codes))))
        from .csv_actions import active_links, row_basis
        pins=active_links(conn,lot['revision_id'],lot_scope['id']) if lot_scope else {}
        for raw in plausible:
            fields=json.loads(raw['permitted_json'])
            row = effective_row(raw, lot['period'],fields=fields)
            if row['disposition'] == 'excluded':
                continue
            fields.update(overrides.get((lot['id'],raw['source_row']),{}))
            k = correspondence.key(dni(fields.get('C')),fields.get('E'))
            if row['disposition'] != 'included' or not row['practice_date']:
                if k in index:uncertain_keys.add(k)
                continue
            entry=dict(key=(lot['id'],raw['source_row']),batch_id=lot['batch_id'],
                       day=date.fromisoformat(row['practice_date']),description=fields.get('K'),
                       match_identity=correspondence.identity(fields.get('E')),original_code=fields.get('E'),
                       directed_rules=correspondence.rules.get(fields.get('E'),{}),
                       incorporation=incorporations.get((lot['id'],raw['source_row'])),billed_order=fields.get('B'),
                       quantity=fields.get('G'),scope_id=lot_scope['id'] if lot_scope else None,
                       hpc=(provider or {}).get('provider')=='HPC',affiliate=fields.get('C'),affiliate_key=k[0],billed=raw['total_ars'],
                       edits=sorted(edit_ids.get((lot['id'],raw['source_row']),())),
                       uncertain=(not same_scope or (lot['id'],raw['source_row']) in linked_rows or
                                  (target_hpc and lot['batch_id']!=batch_id and
                                   (not provider or provider.get('source_id')!=(provider_basis(conn,batch_id) or {}).get('source_id')))))
            pin=pins.get(raw['source_row'])
            if pin and pin['row_basis']==row_basis(entry):
                entry['verified_link']=pin
            main_rows[entry['key']]=entry
            component_rule=correspondence.components.get(fields.get('E'))
            if component_rule:
                component_rows.append(entry)
                if lot['batch_id']==batch_id and raw['source_row'] in numbers:
                    wanted.add(correspondence.key(k[0],component_rule['parent_code']))
                continue
            if k not in index:
                if lot['batch_id']==batch_id and raw['source_row'] in numbers and entry['hpc'] and in_images(raw['source_row'],fields):
                    result[entry['key']]=assessment.absence(k[0],fields.get('E'),fields,row,entry['key'] in linked_rows)
                continue
            if lot['batch_id']==batch_id and raw['source_row'] in numbers:
                wanted.add(k)
            all_groups[k].append(entry)
    for k in wanted:
        if k not in index:continue
        matches = index[k]
        if not all(m[0]['source_system']=='HPC-CSV' for m in matches):
            continue
        group = all_groups[k]
        if k in uncertain_keys or len(matches)>200:
            budget_hint = any(m[2]['order_id'] in m[0].get('_budget_orders', {}) for m in matches)
            ambiguous = {'budget':{'status':'por_verificar','reason':'Hay coincidencias o fechas sin resolver.'}} if budget_hint else {}
            result.update({r['key']:{'status':'needs_review', **ambiguous} for r in group})
        else:
            from .csv_budget import assess_budgets
            items = [dict(dated_item(*m),match_identity=correspondence.identity(m[4]['full_code']),
                          qualifiers=correspondence.modifiers(m[2],m[3]),order=m[2]) for m in matches]
            item_lookup.update(((i['sha256'],i['locator']),i) for i in items)
            from .csv_rules import allocate
            signals = allocate(group,items) if target_hpc else assess_group(group,items)
            if any(r.get('match_identity') for r in group):
                for signal in signals.values():
                    signal.setdefault('code_correspondence_ids',correspondence.receipts.get(k[1],[]))
            for row in group:
                if (row['batch_id']!=batch_id or not row['hpc'] or row['key'][1] not in numbers
                        or not in_images(row['key'][1],{'E':k[1],'K':row['description']})):
                    continue
                signal=signals[row['key']]
                assessment.check_shortfall(signal,row,*k)
                if signal['status']=='outside_window' and not signal.get('coverage_note'):
                    from .authorization_matching import _description
                    if any(not i['unique'] or i['provider']!='HPC' or _description(i['description'])!=_description(row['description']) for i in items):
                        signal['coverage_note']='Falta cotejar la práctica de la orden fuera del período.'
            assess_budgets(group,items,signals)
            attach_review_evidence(group, signals, scope, k, reviewed)
            if conn.execute('PRAGMA user_version').fetchone()[0]>=39:
                from .image_budgets import apply_links
                apply_links(conn,dataset_id,group,signals)
            result.update(signals)
    if component_rows:
        from .csv_components import attach
        attach(component_rows,main_rows,result,item_lookup,correspondence.components)
    return result

"""Strict observed CSV item blocks. Source declarations, never audit decisions.

Offsets are Unicode character offsets in the decoded movimientos field, not byte
or physical CSV line offsets. The original CSV and its hash remain authoritative.
"""
from .csv_item_quantity import clause_units
from collections import Counter
from datetime import datetime
import re

HEADER = re.compile(r'^\s*Resoluci[oó]n por [ií]tems\s*[-:]\s*', re.I)
AUTH = re.compile(r'(?<!\w)(NO\s+AUTORIZAR|AUTORIZAR)\s*:', re.I)
REFERRAL = re.compile(r'(?<!\w)(NO\s+CORRESPONDE(?:N)?|CORRESPONDE(?:N)?)\s*:', re.I)
CODE = re.compile(r'(?<![\w./-])\d{10}(?![\w./-])')
EVENT = re.compile(r'^(\d{2}/\d{2}/\d{4} \d{2}:\d{2}) \| ([^|]+) \| ([^|]+) \| (.*)$')


def plain_item_tail(tail):
    # A subject may be followed by a dash-delimited description and the
    # delimiter of the next numbered clause. Free instructions are unresolved.
    tail = re.sub(r'(?:;\s*(?:\d+[).])?|\s+\d+[).])\s*$', '', tail).strip()
    if not tail:
        return True
    if not re.fullmatch(r'-\s+[^;:\n]+', tail):
        return False
    return not re.search(r'\b(si|pendiente|condicionad\w*|salvo|excepto|sujet\w*|'
                         r'anulad\w*|revocad\w*|autorizar|siempre que|a confirmar)\b', tail, re.I)


def listed_order_resolutions(text, items, csv_record, source_sha256):
    """A dated platform decision covers the listed items under the agreed HPC contract."""
    events = []
    for line in text.splitlines():
        event = EVENT.fullmatch(line)
        if not event:
            return [], []
        try:
            when = datetime.strptime(event[1], '%d/%m/%Y %H:%M').isoformat(timespec='minutes')
        except ValueError:
            return [], []
        state = event[3].strip().upper()
        if state in ('AUTORIZADO', 'RECHAZADO'):
            events.append((event, when))
        elif state not in ('SOLICITADO', 'PENDIENTE', 'INGRESADO', 'EN AUDITORIA'):
            return [], []
    if len(events) != 1 or not items or any(n != 1 for n in Counter(i['full_code'] for i in items).values()):
        return [], []
    event, when = events[0]
    comment = event[4].strip()
    # Item blocks and qualified prose keep their original interpretation.
    if (HEADER.search(comment) or CODE.search(comment)
            or re.search(r'resoluci[oó]n por|autorizar\s*:|no autoriza|no se autoriza|'
                         r'pendiente|condicion|sujeto|salvo|excepto|parcial|solamente|\bsolo\b|'
                         r'\bsi\b|revoc|anulad|rectific|\d+\s+de\s+\d+', comment, re.I)):
        return [], []
    referral = bool(re.search(r'\bderiva\w*|\bderivaci[oó]n', comment, re.I))
    if referral:
        state = 'referred'
    else:
        state = 'authorized' if event[3].strip().upper() == 'AUTORIZADO' else 'rejected'
    if len(items) > 1 and comment and not re.fullmatch(
            r'autorizad[oa](?:\s+por\s+[^;:]+)?\.?', comment, re.I):
        return [], []
    decisions, evidence = [], []
    for item in items:
        units = item.get('requested_quantity') or '1'
        if not re.fullmatch(r'[1-9]\d{0,5}', units):
            return [], []
        decisions.append({
            'resolution_id': f"csv:{csv_record}:event:{text.splitlines().index(event[0])}:item:{item['position']}",
            'scope': 'item', 'item_ids': [item['item_id']], 'status': state,
            'decided_at': when, 'reason': text,
            'authorized_quantity': units if state == 'authorized' else None,
            'unit': 'práctica' if state == 'authorized' else None})
        evidence.append({'kind': 'authorization', 'basis': 'platform_decision_for_listed_items',
                         'state': state, 'full_code': item['full_code'],
                         'item_position': item['position'], 'csv_record': csv_record,
                         'source_sha256': source_sha256, 'decided_at': when})
    return decisions, evidence


def extract_item_resolutions(text, items, csv_record, source_sha256):
    from .csv_movements import read
    return read(text, items, csv_record, source_sha256, extract_legacy, EVENT)


def extract_legacy(text, items, csv_record, source_sha256):
    counts = Counter(i['full_code'] for i in items)
    positions = {i['full_code']: i['position'] for i in items}
    evidence, warnings, declared = [], [], []
    offset = 0
    valid_events = True
    for event_index, line in enumerate(text.splitlines(keepends=True)):
        body = line.rstrip('\r\n')
        event = EVENT.fullmatch(body)
        try:
            if not event or not event[2].strip() or not event[3].strip():
                raise ValueError()
            when = datetime.strptime(event[1], '%d/%m/%Y %H:%M').isoformat(timespec='minutes')
        except ValueError:
            valid_events = False
            offset += len(line)
            continue
        reason, origin = event[4], offset + event.start(4)
        header = HEADER.search(reason)
        modes = []
        if header:
            modes.append(('authorization', AUTH, header.end()))
        if '[DER:' in reason:
            modes.append(('referral', REFERRAL, 0))
        for kind, pattern, start in modes:
            labels = list(pattern.finditer(reason, start))
            if kind == 'authorization' and not labels:
                warnings.append({'event': event_index, 'kind': kind, 'code': 'uninterpreted_item_block'})
            for n, label in enumerate(labels):
                end = labels[n + 1].start() if n + 1 < len(labels) else len(reason)
                section = reason[label.end():end]
                if kind == 'authorization':
                    prefix = reason[start:label.start()]
                    # A subheading starts the block, or follows a numbered or
                    # semicolon delimiter, never arbitrary prose/negation.
                    if (n == 0 and not re.fullmatch(r'\s*(?:\d+[).]\s*)?', prefix)) or (n > 0 and not re.search(r'(?:;\s*|\d+[).]\s*)$', prefix)):
                        warnings.append({'event': event_index, 'kind': kind, 'code': 'item_label_context_uninterpretable'})
                        continue
                codes = list(CODE.finditer(section))
                # Empty outer AUTORIZAR headings before numbered subheadings are
                # structural only. Do not treat an empty final clause as approval.
                if not codes:
                    if kind == 'authorization' and label[1].upper() == 'AUTORIZAR' and n + 1 < len(labels) and re.fullmatch(r'\s*(?:\d+[).]\s*)?', section):
                        continue
                    warnings.append({'event': event_index, 'kind': kind, 'code': 'item_clause_uninterpretable'})
                    continue
                subjects = codes if kind == 'referral' else codes[:1]
                for subject in subjects:
                    # Authorization subjects must start their own labeled clause.
                    # Referral lists are a separate non-authorizing declaration.
                    leading = re.fullmatch(r'\s*(?:\d+[).]\s*)?', section[:subject.start()])
                    code = subject[0]
                    unique = counts[code] == 1 and (kind == 'referral' or (len(codes) == 1 and bool(leading)))
                    tail=section[subject.end():]
                    item=items[positions[code]] if unique else {}
                    units,marked=clause_units(tail,item) if kind=='authorization' and unique else (None,False)
                    listed=item.get('requested_quantity')
                    list_tail=re.sub(r'(?:;\s*(?:\d+[).])?|\s+\d+[).])\s*$','',tail).strip()
                    compatible_list=not list_tail or list_tail.removeprefix('-').strip().casefold()==item.get('description','').casefold()
                    if kind=='authorization' and unique and (marked or listed) and label[1].upper()=='AUTORIZAR':
                        if event[3].strip().casefold()!='autorizado' or (marked and units is None) or (not marked and not compatible_list):
                            warnings.append({'event':event_index,'kind':kind,'code':'authorized_quantity_unresolved'})
                        elif not marked:
                            units=int(listed)
                    if kind == 'authorization' and units is None and not plain_item_tail(tail):
                        warnings.append({'event': event_index, 'kind': kind, 'code': 'uninterpreted_item_qualification'})
                    state = ('rejected' if label[1].upper().startswith('NO') else 'authorized') if kind == 'authorization' else ('excluded' if label[1].upper().startswith('NO') else 'included')
                    entry = {'kind': kind, 'state': state if unique else 'indeterminate',
                             'full_code': code, 'item_position': positions.get(code) if unique else None,
                             'event': event_index, 'decided_at': when, 'csv_record': csv_record,
                             'source_sha256': source_sha256, 'field': 'movimientos',
                             'offset_unit': 'unicode_character',
                             'start': origin + label.start(), 'end': origin + end,
                             'code_start': origin + label.end() + subject.start(),
                             'code_end': origin + label.end() + subject.end(),
                             'excerpt': reason[label.start():end]}
                    if marked:
                        entry['quantity_text']=tail.strip()
                    if units and state=='authorized':
                        entry['authorized_quantity']=str(units)
                    evidence.append(entry)
                    if not unique:
                        warnings.append({'event': event_index, 'kind': kind, 'code': 'item_subject_not_unique'})
                    elif kind == 'authorization':
                        declared.append(entry)
        offset += len(line)
    if not valid_events:
        warnings.append({'kind': 'authorization', 'code': 'event_layout_uninterpretable'})
    # Ambiguous clauses may refer to any item: do not publish a partial decision.
    blocked = any(w['kind'] == 'authorization' for w in warnings)
    frequencies = Counter(e['full_code'] for e in declared)
    resolutions = []
    for entry in declared:
        if blocked or frequencies[entry['full_code']] != 1:
            entry['state'] = 'indeterminate'
            continue
        resolutions.append({'resolution_id': f"csv:{csv_record}:event:{entry['event']}:item:{entry['item_position']}",
                            'scope': 'item', 'item_ids': [f"csv-item:{entry['item_position']}"],
                            'status': entry['state'], 'decided_at': entry['decided_at'],
                            'reason': text})
        if entry.get('authorized_quantity'):
            resolutions[-1].update(authorized_quantity=entry['authorized_quantity'],unit='práctica')
    referrals = Counter(e['full_code'] for e in evidence if e['kind'] == 'referral')
    for entry in evidence:
        if entry['kind'] == 'referral' and referrals[entry['full_code']] > 1:
            entry['state'] = 'indeterminate'
    if any(n > 1 for n in frequencies.values()):
        warnings.append({'kind': 'authorization', 'code': 'multiple_or_conflicting_item_declarations'})
    if not resolutions and not warnings and not evidence:
        resolutions, evidence = listed_order_resolutions(text, items, csv_record, source_sha256)
    return resolutions, {'csv_record': csv_record, 'evidence': evidence, 'warnings': warnings}

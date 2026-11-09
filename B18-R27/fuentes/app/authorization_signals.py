"""Read-only panel signals: presence, item decision and order history are distinct."""
import re
from datetime import datetime


def csv_order_history(order, capture):
    if capture.get('source_system') != 'HPC-CSV':
        return []
    # Observed contract: one event per line, date | actor | state | reason.
    # Split only the first three separators: arbitrary pipes in the reason are
    # never interpreted as another state. An unexpected layout is not guessed.
    states = set()
    for resolution in order['resolutions']:
        reason = resolution.get('reason')
        if not isinstance(reason, str) or not reason:
            return []
        for line in reason.splitlines():
            fields = line.split(' | ', 3)
            if len(fields) != 4 or not re.fullmatch(r'\d{2}/\d{2}/\d{4} \d{2}:\d{2}', fields[0]) or not fields[1].strip():
                return []
            try:
                datetime.strptime(fields[0], '%d/%m/%Y %H:%M')
            except ValueError:
                return []
            if fields[2] in ('AUTORIZADO', 'RECHAZADO'):
                states.add(fields[2].lower())
    return sorted(states)


def panel_signal(evidence, related, link=None):
    result = {'presence': 'not_evaluated', 'item_authorization': 'not_determinable',
              'order_history_states': [], 'decision_basis': None,
              'is_audit_decision': False}
    if evidence['disposition'] != 'included':
        return {**result, 'presence': 'outside_scope'}
    if evidence['issues'] or evidence['state'] in ('scope_missing', 'requires_update', 'identity_or_code_unresolved', 'candidate_limit'):
        return result
    exact = evidence['candidates']
    viable = [c for c in exact if c['compatibility'] != 'incompatible']
    relatives = [c for c in related['candidates'] if c['compatibility'] != 'incompatible']
    result['presence'] = ('found' if viable else 'candidate' if relatives else
                          'incompatible' if exact or related['candidates'] else 'not_located')
    result['order_history_states'] = sorted({s for c in viable + relatives for s in c.get('csv_order_history', [])})
    # A human-selected, still-current item can disambiguate candidates. Otherwise
    # only one complete correspondence can carry a source-declared item status.
    chosen = None
    if link:
        if link['state'] != 'selected' or link['basis_sha256'] != evidence['basis_sha256']:
            return result
        chosen = next((c for c in viable if c['key'] == link['candidate_key']), None)
    elif len(viable) == 1:
        chosen = viable[0]
    if chosen and chosen.get('source_system') == 'HPC-CSV':
        declared = chosen.get('item_resolution_state')
        if declared in ('declared_authorized', 'declared_rejected'):
            result['csv_item_declaration'] = declared.removeprefix('declared_')
    if chosen and chosen['compatibility'] == 'compatible':
        state = chosen.get('item_resolution_state', 'no_concluyente')
        if state in ('declared_authorized', 'declared_rejected', 'declared_pending', 'declared_referred'):
            result['item_authorization'] = state.removeprefix('declared_')
            result['decision_basis'] = {'capture_id': chosen['capture_id'], 'locator': chosen['locator'],
                                        'source_sha256': chosen['source_sha256']}
    return result

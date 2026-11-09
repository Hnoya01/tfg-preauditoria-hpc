"""Versioned, selective closure dependencies; complete captures are stored once."""
from .dependencies import FIELD_RULES

FORMAT = 'closure-input-v2'
AUTH_RULES = ('RN09', 'RN10', 'RN11', 'RN18')


def member_basis(snapshot, shared, source_row, rule, work):
    basis = {'format': FORMAT, 'invoice': snapshot['invoice_sha256'],
             'period': snapshot['period'], 'eligibility_policy': snapshot.get('eligibility_policy'),
             'work': {field: identity for field, identity in work.items()
                      if rule in FIELD_RULES.get(field, set())}}
    if rule in AUTH_RULES:
        engine = snapshot.get('authorization_engine', {})
        dependency = engine.get('rows', {}).get(str(source_row), {}).get(rule)
        basis['authorization'] = {'version': engine.get('version'), 'dependency': dependency}
        if dependency is None:
            basis['authorization']['scope'] = shared['authorization_scope']
            if not engine.get('scope'):
                basis['authorization']['sources'] = shared['authorization_sources']
    if rule in ('RN14','RN15','RN16'):
        engine = snapshot.get('economic_engine')
        if rule in ('RN14','RN15') and engine:
            from .economic_applicability import _sha
            basis['economic_reference'] = {'version': engine['version'],
                'simulation_only': engine.get('simulation_only') if engine['rows'].get(str(source_row)) else None,
                'dependency_sha256': _sha(engine['rows'].get(str(source_row)))}
        else:
            basis['values'] = shared['values']
            if rule in ('RN14','RN15'):basis['provider_scope'] = shared['provider_scope']
    if rule in ('RN20','RN21','RN22'):
        basis['documents'] = shared['documents']
    return basis

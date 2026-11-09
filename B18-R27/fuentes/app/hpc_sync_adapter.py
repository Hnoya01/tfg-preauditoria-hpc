"""Offline preview of Sync 0.5.1 prepareImageDay packages. Never contacts HPC."""
import hashlib
import json
import re
from datetime import date, datetime, timezone
from .authorization_json import parse_authorization, _unique_object, _reject_constant
from .storage import MAX_SOURCE_BYTES


BLOCKING_CODES = frozenset({
    'identity_mismatch', 'order_date_mismatch', 'duplicate_order_id',
    'empty_order_id', 'unexpected_internal_type', 'malformed_history_row',
    'attachment_order_mismatch',
})

JS_WHITESPACE = r"[\u0009-\u000d\u0020\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+"


def normalize_identity(value):
    """Same whitespace normalization and lowercasing used by the producer."""
    if not isinstance(value, str):
        raise SyncFormatError("identity_type")
    return re.sub(JS_WHITESPACE, " ", value).strip(" ").lower()


class SyncFormatError(ValueError):
    pass


def adapt_sync_day(content: bytes, *, synthetic=False):
    """Returns A1 bytes and non-identifying provenance. Caller retains raw bytes.

    This is NOT an adapter for query summaries or arbitrary Worker responses.
    Movement scope and item authorization are unknown; no inference is made.
    """
    def require(condition, code):
        if not condition:
            raise SyncFormatError(code)
    require(0 < len(content) <= MAX_SOURCE_BYTES, 'size')
    try:
        day = json.loads(content.decode('utf-8-sig'), object_pairs_hook=_unique_object,
                         parse_constant=_reject_constant)
        require(isinstance(day, dict), 'day_object')
        require(day.get('extractor_version') == 'historico-0.4', 'unsupported_extractor')
        require(isinstance(day.get('queried_date'), str) and bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}', day['queried_date'])), 'queried_date')
        date.fromisoformat(day['queried_date'])
        require(day.get('source_outcome') in ('recognized', 'partial'), 'source_outcome')
        require(isinstance(day.get('attempt_id'), str) and bool(day['attempt_id']), 'attempt_id')
        require(type(day.get('captured_at')) is int and day['captured_at'] > 0, 'capture_seconds')
        captured = datetime.fromtimestamp(day['captured_at'], timezone.utc).isoformat()
        require(isinstance(day.get('rows'), list) and isinstance(day.get('items'), list), 'rows_items')
        require(len(day['rows']) <= 200 and len(day['items']) <= 200, 'day_limit')
        require(bool(day['rows']), 'empty_day_not_supported')
        rows = {}
        for row in day['rows']:
            require(isinstance(row, dict), 'row_object')
            if row.get('extraction_issue'):
                require(row.get('operation_id') is None, 'rejected_operation')
                continue
            op = row.get('operation_id')
            require(isinstance(op, str) and bool(op) and op not in rows, 'duplicate_operation')
            rows[op] = row
        orders, seen, operations = [], set(), set()
        for item in day['items']:
            require(isinstance(item, dict), 'item_object')
            op, p = item.get('operation_id'), item.get('payload')
            require(isinstance(op, str) and op in rows and op not in operations, 'operation_mapping')
            operations.add(op)
            require(isinstance(p, dict) and p.get('ready_for_ingest') is True, 'payload_not_ready')
            require(isinstance(p.get('problems'), list), 'problems_required')
            require(all(isinstance(problem, dict) and isinstance(problem.get('code'), str)
                        for problem in p['problems']), 'problem_format')
            require(not any(problem['code'] in BLOCKING_CODES for problem in p['problems']),
                    'payload_blocking_problem')
            encoded = json.dumps(p, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
            # prepareImageDay excludes oversized orders rather than ingesting them.
            require(len(encoded) <= 80000, 'order_too_large')
            require(hashlib.sha256(encoded).hexdigest() == rows[op].get('payload_digest'), 'payload_digest')
            oid = p.get('hpc_id')
            require(isinstance(oid, str) and bool(oid) and oid not in seen and oid == rows[op].get('hpc_id'), 'order_identity')
            seen.add(oid)
            source, displayed = p['source'], p['displayed']
            require(normalize_identity(source['id']) == normalize_identity(oid) == normalize_identity(displayed['id']), 'identity_conflict')
            require(normalize_identity(source['affiliate']) == normalize_identity(displayed['affiliate']), 'affiliate_conflict')
            require(p['internal_type'] in ('orden.imagen', 'orden.imagen.digital'), 'not_images')
            require(source['orderType'] == p['internal_type'], 'internal_type_conflict')
            practices = p['practices']
            require(isinstance(practices['items'], list) and isinstance(p['movements'], list), 'collections')
            # Keep descriptions WITH amount text. Never parse money or quantities heuristically.
            items = [{'position': v['position'], 'full_code': v['codeText'],
                      'description': v['descriptionAndAmountText']} for v in practices['items']]
            resolutions = [{'scope': 'unknown', 'item_ids': [], 'status': v['statusText'],
                            'decided_at': v['dateText'], 'reason': v['reasonText']}
                           for v in p['movements']]
            orders.append({'order_id': oid, 'affiliate_id': source['affiliate'],
                           'provider': 'HPC', 'ordered_at': displayed['orderDate'],
                           'items': items, 'resolutions': resolutions})
        require(set(rows) == operations, 'missing_payload')
        limitations = ['Captura parcial no validada contra el intercambio real.',
                      'Movimientos sin atribución a ítems; no acreditan autorización individual.',
                      'No se infieren cantidades, unidades, importes ni vigencia.',
                      'Adjuntos, texto bruto y metadatos permanecen en el paquete original; no se descargan.',
                      'Fechas locales originales conservadas, sin asignar zona ni normalizar.']
        canonical = {'schema_version': 'A1-canonical-v1',
                     'data_origin': 'synthetic' if synthetic else 'real_unvalidated',
                     'source': {'system': 'HPC-Sync', 'stream_id': 'historico-0.4:' + day['queried_date'],
                                'capture_id': day['attempt_id'], 'captured_at': captured},
                     'coverage': {'declared': 'partial', 'description': 'Paquete diario de captura Sync; no exportación exhaustiva.',
                                  'limitations': limitations}, 'orders': orders}
        result = json.dumps(canonical, ensure_ascii=False).encode()
        parse_authorization(result)
        return result, {'adapter': 'sync-day-preview-v1', 'source_sha256': hashlib.sha256(content).hexdigest(),
                        'output_sha256': hashlib.sha256(result).hexdigest(), 'orders': len(orders),
                        'unrepresented_rows': len(day['rows']) - len(orders), 'requires_raw_source': True}
    except SyncFormatError:
        raise
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError, AttributeError):
        raise SyncFormatError('invalid_sync_day') from None

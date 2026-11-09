"""A1 canonical intake only: source observations are not control conclusions."""

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .storage import MAX_SOURCE_BYTES


SCHEMA = 'A1-canonical-v1'
PARSER_VERSION = 'A1-intake-v1'


class Canonical(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class CaptureSource(Canonical):
    system: str = Field(pattern=r'^[A-Za-z0-9_.:-]{1,80}$')
    stream_id: str = Field(pattern=r'^[A-Za-z0-9_.:-]{1,80}$')
    capture_id: str | None = Field(default=None, max_length=200)
    captured_at: str | None = Field(default=None, max_length=80)


class DeclaredCoverage(Canonical):
    declared: Literal['unknown', 'partial', 'complete']
    description: str = Field(max_length=4000)
    period: str | None = Field(default=None, pattern=r'^\d{4}-(0[1-9]|1[0-2])$')
    limitations: list[str] = Field(default_factory=list, max_length=100)


class Practice(Canonical):
    item_id: str | None = Field(default=None, max_length=200)
    position: int | None = Field(default=None, ge=0)
    full_code: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=4000)
    requested_quantity: str | None = Field(default=None, max_length=64)
    unit: str | None = Field(default=None, max_length=100)
    service_date: str | None = Field(default=None, max_length=80)


class Resolution(Canonical):
    resolution_id: str | None = Field(default=None, max_length=200)
    scope: str | None = Field(default=None, max_length=100)
    item_ids: list[str] = Field(default_factory=list, max_length=10000)
    status: str | None = Field(default=None, max_length=100)
    authorized_quantity: str | None = Field(default=None, max_length=64)
    unit: str | None = Field(default=None, max_length=100)
    decided_at: str | None = Field(default=None, max_length=80)
    supersedes_resolution_id: str | None = Field(default=None, max_length=200)
    reason: str | None = Field(default=None, max_length=8000)


class Order(Canonical):
    order_id: str | None = Field(default=None, max_length=200)
    affiliate_id: str | None = Field(default=None, max_length=200)
    provider: str | None = Field(default=None, max_length=200)
    ordered_at: str | None = Field(default=None, max_length=80)
    global_status: str | None = Field(default=None, max_length=100)
    items: list[Practice] = Field(default_factory=list, max_length=10000)
    resolutions: list[Resolution] = Field(default_factory=list, max_length=10000)


class Capture(Canonical):
    schema_version: Literal['A1-canonical-v1']
    data_origin: Literal['synthetic', 'real_unvalidated']
    source: CaptureSource
    coverage: DeclaredCoverage
    orders: list[Order] = Field(max_length=5000)


class AuthorizationFormatError(ValueError):
    def __init__(self, errors):
        self.errors = errors
        super().__init__('El archivo no cumple el contrato canónico A1')


@dataclass
class ParsedAuthorization:
    canonical: dict
    summary: dict
    observations: list[dict]
    manifest: bytes
    preview_sha256: str


def _reject_constant(_value):
    raise AuthorizationFormatError([{'path': '$', 'code': 'non_json_number'}])


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise AuthorizationFormatError([{'path': '$', 'code': 'duplicate_json_key'}])
        result[key] = value
    return result


def parse_authorization(content: bytes) -> ParsedAuthorization:
    if not 1 <= len(content) <= MAX_SOURCE_BYTES:
        raise AuthorizationFormatError([{'path': '$', 'code': 'file_size'}])
    try:
        raw = json.loads(content.decode('utf-8-sig'), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        stack, nodes = [(raw, 0)], 0
        while stack:
            value, depth = stack.pop()
            nodes += 1
            if depth > 60 or nodes > 250000:
                raise AuthorizationFormatError([{'path': '$', 'code': 'document_complexity'}])
            if isinstance(value, dict):
                for key in value:
                    key.encode('utf-8')
                stack.extend((v, depth + 1) for v in value.values())
            elif isinstance(value, list):
                stack.extend((v, depth + 1) for v in value)
            elif isinstance(value, str):
                value.encode('utf-8')
        canonical = Capture.model_validate(raw).model_dump(mode='json')
    except AuthorizationFormatError:
        raise
    except ValidationError as exc:
        errors = [{'path': '$.' + '.'.join(str(x) for x in e['loc']), 'code': e['type']}
                  for e in exc.errors(include_input=False, include_url=False)[:30]]
        raise AuthorizationFormatError(errors) from None
    except (UnicodeError, ValueError, RecursionError):
        raise AuthorizationFormatError([{'path': '$', 'code': 'invalid_utf8_or_json'}]) from None

    observations, temporal = [], []
    def observe(code, path, message, level='warning'):
        observations.append({'code': code, 'path': path, 'message': message, 'level': level})

    def timestamp(value, path):
        precision, zoned = 'unknown', False
        if value:
            try:
                if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
                    date.fromisoformat(value)
                    precision = 'day'
                elif re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})?', value):
                    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
                    precision = 'second' if re.match(r'.*T\d{2}:\d{2}:\d{2}', value) else 'minute'
                    zoned = parsed.tzinfo is not None
                    if not zoned:
                        observe('timezone_unknown', path, 'Hora sin zona informada; no se agrega una zona por suposición.')
                else:
                    raise ValueError('unsupported temporal form')
            except ValueError:
                observe('uninterpretable_date', path, 'Fecha conservada sin interpretación temporal suficiente.')
        else:
            observe('missing_date', path, 'Fecha no informada; no se completa por inferencia.')
        temporal.append({'path': path, 'precision': precision, 'timezone_provided': zoned})

    def quantity(value, unit, path):
        if value is None:
            observe('quantity_unknown', path, 'Cantidad no informada; no equivale a cero.')
            return
        try:
            number = Decimal(value)
            if not number.is_finite() or number < 0:
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            observe('quantity_uninterpretable', path, 'Cantidad conservada como texto; requiere interpretación.')
        if not unit:
            observe('unit_unknown', path, 'Unidad de cantidad no informada.')

    observe('synthetic_data' if canonical['data_origin'] == 'synthetic' else 'real_source_unvalidated', '$.data_origin',
            'DATOS FICTICIOS: no acreditan validación real.' if canonical['data_origin'] == 'synthetic' else
            'Origen declarado real, sin validación del intercambio ni cobertura.', 'information')
    observe('coverage_not_verified', '$.coverage', 'Cobertura declarada conservada; su exhaustividad no está comprobada.')
    if not canonical['orders']:
        observe('empty_capture', '$.orders', 'La captura no contiene órdenes; no prueba ausencia de autorizaciones.')
    timestamp(canonical['source']['captured_at'], '$.source.captured_at')
    totals = Counter()
    seen_orders = set()
    for i, order in enumerate(canonical['orders']):
        path = f'$.orders[{i}]'
        totals['orders'] += 1
        for field in ('order_id', 'affiliate_id', 'provider'):
            if not order[field]:
                observe('missing_' + field, path + '.' + field, 'Dato no informado; no se confirma una asociación.')
        if order['order_id'] and order['order_id'] in seen_orders:
            observe('duplicate_order_id', path + '.order_id', 'ID de orden repetida; conservar registros separados.')
        seen_orders.add(order['order_id'])
        timestamp(order['ordered_at'], path + '.ordered_at')
        if order['global_status']:
            observe('global_status_not_item_approval', path + '.global_status', 'El estado global no aprueba por sí solo todos los ítems.', 'information')
        ids = Counter(item['item_id'] for item in order['items'] if item['item_id'])
        codes = Counter(item['full_code'] for item in order['items'] if item['full_code'])
        if any(n > 1 for n in codes.values()):
            totals['potentially_ambiguous_orders'] += 1
            observe('repeated_full_code_candidates', path + '.items', 'Prácticas con el mismo código: posible ambigüedad para el futuro vínculo con Excel; aún no evaluado.')
        for j, item in enumerate(order['items']):
            item_path = f'{path}.items[{j}]'
            totals['items'] += 1
            for field in ('item_id', 'full_code'):
                if not item[field]:
                    observe('missing_' + field, item_path + '.' + field, 'Ítem incompleto; no se reconstruye identidad o código.')
            if item['item_id'] and ids[item['item_id']] > 1:
                observe('duplicate_item_id', item_path + '.item_id', 'ID de ítem repetida; las referencias requieren interpretación.')
            quantity(item['requested_quantity'], item['unit'], item_path + '.requested_quantity')
            timestamp(item['service_date'], item_path + '.service_date')
        states_by_item = {}
        distinct_states = set()
        if not order['resolutions']:
            observe('resolutions_missing', path + '.resolutions', 'No se informan resoluciones; no equivale a rechazo.')
        for j, resolution in enumerate(order['resolutions']):
            rpath = f'{path}.resolutions[{j}]'
            totals['resolutions'] += 1
            state = resolution['status']
            if state not in {'authorized', 'rejected', 'referred', 'pending', 'unknown'}:
                observe('resolution_status_uninterpreted', rpath + '.status', 'Estado ausente o no reconocido; se conserva sin traducirlo a autorización/rechazo.')
            distinct_states.add(state)
            if resolution['scope'] not in {'item', 'explicit_general'} or not resolution['item_ids']:
                observe('resolution_scope_unresolved', rpath, 'Alcance o ítems afectados no acreditados.')
            for item_id in resolution['item_ids']:
                if ids.get(item_id) != 1:
                    observe('resolution_item_reference_unresolved', rpath + '.item_ids', 'La referencia a un ítem falta o no es unívoca.')
                states_by_item.setdefault(item_id, set()).add(state)
            quantity(resolution['authorized_quantity'], resolution['unit'], rpath + '.authorized_quantity')
            timestamp(resolution['decided_at'], rpath + '.decided_at')
        if 'authorized' in distinct_states and 'rejected' in distinct_states:
            observe('mixed_item_resolution_states', path + '.resolutions', 'La orden contiene autorizaciones y rechazos; no se extienden entre prácticas.', 'information')
        if any('authorized' in states and 'rejected' in states for states in states_by_item.values()):
            totals['orders_with_apparent_conflict'] += 1
            observe('apparent_resolution_conflict', path + '.resolutions', 'Resoluciones aparentemente contradictorias sobre un mismo ítem; no se elige la aplicable en esta importación.')
    if totals['items'] > 25000 or totals['resolutions'] > 25000:
        raise AuthorizationFormatError([{'path': '$.orders', 'code': 'record_limit'}])
    summary = {key: totals[key] for key in ('orders', 'items', 'resolutions', 'potentially_ambiguous_orders', 'orders_with_apparent_conflict')}
    summary.update(schema_version=SCHEMA, parser_version=PARSER_VERSION, data_origin=canonical['data_origin'],
                   source=canonical['source'], declared_coverage=canonical['coverage'],
                   coverage_verification='not_verified', controls_evaluated=False, analysis_started=False,
                   economic_applicability='not_evaluated', proposal_amount_ars=None,
                   observation_count=len(observations), temporal_precision=temporal)
    manifest = json.dumps({'kind': 'authorization_intake_manifest', 'source_sha256': hashlib.sha256(content).hexdigest(),
                           'summary': summary, 'observations': observations}, ensure_ascii=False,
                          sort_keys=True, separators=(',', ':')).encode()
    if len(manifest) > MAX_SOURCE_BYTES:
        raise AuthorizationFormatError([{'path': '$', 'code': 'intake_manifest_size_limit'}])
    return ParsedAuthorization(canonical, summary, observations, manifest, hashlib.sha256(manifest).hexdigest())

"""Versioned A1 intake with immutable originals; never starts an analysis."""

import json
from pathlib import Path
from uuid import uuid4

from .authorization_json import AuthorizationFormatError, SCHEMA
from .authorization_source import parse_authorization_source as parse_authorization, canonical_bytes
from .db import transaction
from .security import now_utc
from .service import Problem, authorized_dataset, check_version, event, validate_filename
from .storage import publish_bytes, read_verified
from .values_v1 import _register_file


def _upload(conn, dataset_id, upload_id):
    row = conn.execute('SELECT u.*, c.id AS capture_id, c.ordinal AS imported_ordinal FROM authorization_uploads u '
                       'LEFT JOIN authorization_captures c ON c.id = (SELECT id FROM authorization_captures WHERE upload_id=u.id ORDER BY ordinal DESC LIMIT 1) WHERE u.dataset_id = ? AND u.id = ?',
                       (dataset_id, upload_id)).fetchone()
    if row is None:
        raise Problem(404, 'Original de autorizaciones inexistente en el conjunto')
    return dict(row)


def stage_authorization(conn, root: Path, token_hash: str, dataset_id: str, expected_version: int,
                        filename: str, content: bytes, *, after_publish=None) -> tuple[dict, bool]:
    filename = validate_filename(filename)
    if not filename.lower().endswith(('.json', '.csv')):
        raise Problem(422, 'Se requiere JSON A1/Sync o CSV de plataforma HPC')
    _, dataset = authorized_dataset(conn, token_hash, dataset_id, 'reviewer')
    check_version(dataset, expected_version)
    try:
        stored = publish_bytes(root, content)
    except ValueError as exc:
        raise Problem(422, str(exc)) from exc
    if after_publish:
        after_publish()
    with transaction(conn):
        user, current = authorized_dataset(conn, token_hash, dataset_id, 'reviewer')
        check_version(current, expected_version)
        previous = conn.execute('SELECT id FROM authorization_uploads WHERE dataset_id = ? AND source_sha256 = ?',
                                (dataset_id, stored[0])).fetchone()
        if previous:
            return {**_upload(conn, dataset_id, previous['id']), 'dataset_version': expected_version}, False
        _register_file(conn, *stored)
        identity = str(uuid4())
        conn.execute('INSERT INTO authorization_uploads VALUES (?, ?, ?, ?, ?, ?)',
                      (identity, dataset_id, stored[0], filename, user['id'], now_utc()))
        conn.execute('UPDATE datasets SET version = version + 1 WHERE id = ?', (dataset_id,))
        event(conn, user['id'], 'authorization_original_staged', 'authorization_upload', identity)
        result = _upload(conn, dataset_id, identity)
    return {**result, 'dataset_version': expected_version + 1}, True


def _read(root, sha):
    try:
        return read_verified(root, sha)
    except (ValueError, OSError, RuntimeError) as exc:
        raise Problem(409, 'El original falta o no coincide con su SHA-256') from exc


def _latest(conn, dataset_id, system, stream):
    return conn.execute('SELECT * FROM authorization_captures WHERE dataset_id = ? AND source_system = ? '
                        'AND stream_id = ? ORDER BY ordinal DESC LIMIT 1', (dataset_id, system, stream)).fetchone()


def _context(conn, dataset_id, parsed):
    source = parsed.canonical['source']
    latest = _latest(conn, dataset_id, source['system'], source['stream_id'])
    errors, notes = [], []
    if latest and latest['data_origin'] != parsed.canonical['data_origin']:
        errors.append({'code': 'stream_origin_conflict', 'path': '$.data_origin',
                       'message': 'Un mismo flujo no mezcla datos ficticios y origen real; usar otro flujo o conjunto.'})
    if latest and source['capture_id']:
        old = json.loads(latest['canonical_json'])['source']
        if old['capture_id'] == source['capture_id']:
            notes.append({'code': 'external_capture_id_reused', 'path': '$.source.capture_id', 'level': 'warning',
                          'message': 'ID externa ya recibida; los bytes y la versión interna distinguen las capturas.'})
    return latest, errors, notes


def preview_authorization(conn, root, token_hash, dataset_id, upload_id) -> dict:
    _, dataset = authorized_dataset(conn, token_hash, dataset_id, 'reviewer')
    upload = _upload(conn, dataset_id, upload_id)
    content = _read(root, upload['source_sha256'])
    try:
        parsed = parse_authorization(content)
        latest, errors, notes = _context(conn, dataset_id, parsed)
        result = {'technical_state': 'interpreted', 'can_import': not errors, 'format_errors': [],
                  'context_errors': errors, 'summary': parsed.summary, 'canonical': parsed.canonical,
                  'observations': parsed.observations + notes, 'preview_sha256': parsed.preview_sha256,
                  'latest_stream_import': {'id': latest['id'], 'ordinal': latest['ordinal']} if latest else None}
    except AuthorizationFormatError as exc:
        result = {'technical_state': 'format_error', 'can_import': False, 'format_errors': exc.errors,
                  'context_errors': [], 'summary': None, 'canonical': None, 'observations': [], 'preview_sha256': None}
    old = conn.execute('SELECT preview_sha256 FROM authorization_captures WHERE id=?', (upload['capture_id'],)).fetchone()
    result['reinterpretation_required'] = bool(old and result['preview_sha256'] and old['preview_sha256'] != result['preview_sha256'])
    result['previous_capture_id'] = upload['capture_id']
    _, current = authorized_dataset(conn, token_hash, dataset_id, 'reviewer')
    check_version(current, dataset['version'])
    return {**result, 'upload': upload, 'dataset_version': dataset['version'],
            'authorization_control': 'not_evaluated', 'analysis_started': False,
            'coverage_verification': 'not_verified', 'proposal_amount_ars': None}


def confirm_authorization(conn, root, token_hash, dataset_id, upload_id, expected_version: int,
                          preview_sha256: str, provenance_note: str, *, reinterpret_capture_id: str | None = None, after_prepare=None) -> tuple[dict, bool]:
    if not isinstance(provenance_note, str) or not 10 <= len(provenance_note.strip()) <= 2000:
        raise Problem(422, 'Registrar procedencia o contexto de recepción, entre 10 y 2000 caracteres')
    _, dataset = authorized_dataset(conn, token_hash, dataset_id, 'reviewer')
    check_version(dataset, expected_version)
    upload = _upload(conn, dataset_id, upload_id)
    content = _read(root, upload['source_sha256'])
    try:
        parsed = parse_authorization(content)
    except AuthorizationFormatError as exc:
        raise Problem(422, 'El formato impide incorporar la captura; revisar la vista previa del original conservado') from exc
    if parsed.preview_sha256 != preview_sha256:
        raise Problem(409, 'La interpretación cambió; volver a consultar la vista previa')
    if after_prepare:
        after_prepare()
    with transaction(conn):
        user, current = authorized_dataset(conn, token_hash, dataset_id, 'reviewer')
        check_version(current, expected_version)
        upload = _upload(conn, dataset_id, upload_id)
        existing = conn.execute('SELECT id, ordinal, preview_sha256 FROM authorization_captures WHERE upload_id = ? ORDER BY ordinal DESC LIMIT 1', (upload_id,)).fetchone()
        if existing and existing['preview_sha256'] != parsed.preview_sha256:
            if reinterpret_capture_id != existing['id']:
                raise Problem(409, 'La captura ya existe con otra interpretación. Confirmar explícitamente una nueva versión desde la vista previa.')
            duplicate = conn.execute('SELECT id FROM authorization_captures WHERE upload_id=? AND preview_sha256=?', (upload_id, parsed.preview_sha256)).fetchone()
            if duplicate:
                raise Problem(409, 'Esta interpretación ya existe en la historia; no se reactiva automáticamente')
        elif reinterpret_capture_id and not existing:
            raise Problem(409, 'La captura anterior no existe')
        if existing and existing['preview_sha256'] == parsed.preview_sha256:
            return {'id': existing['id'], 'ordinal': existing['ordinal'], 'dataset_version': expected_version,
                    'created': False, 'analysis_started': False, 'coverage_verification': 'not_verified',
                    'authorization_control': 'not_evaluated', 'proposal_amount_ars': None}, False
        previous, errors, _ = _context(conn, dataset_id, parsed)
        if errors:
            raise Problem(409, errors[0]['message'])
        if existing and previous and existing['id'] != previous['id']:
            raise Problem(409, 'No reinterpretar una recepción histórica reemplazada; usar la captura más reciente del flujo')
        manifest = publish_bytes(root, parsed.manifest)
        _register_file(conn, *manifest)
        identity, source_id = str(uuid4()), str(uuid4())
        ordinal = previous['ordinal'] + 1 if previous else 1
        source = parsed.canonical['source']
        coverage = {**parsed.canonical['coverage'], 'verification': 'not_verified'}
        metadata = {'data_origin': parsed.canonical['data_origin'], 'import_only': True, 'analysis_enabled': False,
                    'economic_applicability': 'not_evaluated', 'authorization_capture_id': identity,
                    'source_system': source['system'], 'stream_id': source['stream_id'], 'ordinal': ordinal,
                    'external_capture_id': source['capture_id']}
        if existing:
            metadata['reinterpretation_of'] = existing['id']
            metadata['previous_preview_sha256'] = existing['preview_sha256']
        if 'adapter_provenance' in parsed.summary:
            derived = publish_bytes(root, canonical_bytes(parsed))
            _register_file(conn, *derived)
            metadata['adapter_provenance'] = parsed.summary['adapter_provenance']
            metadata['derived_a1_sha256'] = derived[0]
        stamp = now_utc()
        conn.execute('INSERT INTO source_registry VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                      (source_id, dataset_id, 'authorizations', 'registered', upload['source_sha256'], manifest[0],
                       SCHEMA, None, str(ordinal), source['captured_at'], json.dumps(coverage, ensure_ascii=False),
                       json.dumps(metadata, ensure_ascii=False), user['id'], stamp))
        conn.execute('INSERT INTO authorization_captures VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                      (identity, dataset_id, upload_id, source_id, source['system'], source['stream_id'], ordinal,
                       previous['id'] if previous else None, parsed.canonical['data_origin'],
                       json.dumps(parsed.canonical, ensure_ascii=False, sort_keys=True),
                       json.dumps(parsed.summary, ensure_ascii=False, sort_keys=True),
                       json.dumps(parsed.observations, ensure_ascii=False, sort_keys=True), parsed.preview_sha256,
                       provenance_note.strip(), user['id'], stamp))
        conn.execute('UPDATE datasets SET version = version + 1 WHERE id = ?', (dataset_id,))
        event(conn, user['id'], 'authorization_capture_reinterpreted' if existing else 'authorization_capture_imported', 'authorization_capture', identity)
    return {'id': identity, 'ordinal': ordinal, 'previous_id': previous['id'] if previous else None,
            'dataset_version': expected_version + 1, 'created': True, 'analysis_started': False,
            'coverage_verification': 'not_verified', 'authorization_control': 'not_evaluated',
            'proposal_amount_ars': None}, True


def authorization_inventory(conn, token_hash, dataset_id):
    _, dataset = authorized_dataset(conn, token_hash, dataset_id, 'reviewer')
    uploads = [dict(row) for row in conn.execute(
        'SELECT u.id, u.source_sha256, u.original_name, u.created_at, c.id AS capture_id, c.ordinal AS imported_ordinal '
        'FROM authorization_uploads u LEFT JOIN authorization_captures c ON c.id = (SELECT id FROM authorization_captures WHERE upload_id=u.id ORDER BY ordinal DESC LIMIT 1) '
        'WHERE u.dataset_id = ? ORDER BY u.created_at DESC, u.rowid DESC', (dataset_id,))]
    captures = []
    for row in conn.execute('SELECT c.*, u.original_name, u.source_sha256, a.username AS actor_username '
                            'FROM authorization_captures c JOIN authorization_uploads u ON u.id = c.upload_id '
                            'JOIN users a ON a.id = c.actor_id WHERE c.dataset_id = ? ORDER BY c.source_system, c.stream_id, c.ordinal', (dataset_id,)):
        head = _latest(conn, dataset_id, row['source_system'], row['stream_id'])
        captures.append({key: row[key] for key in ('id', 'source_system', 'stream_id', 'ordinal', 'previous_id', 'data_origin',
                          'original_name', 'source_sha256', 'provenance_note', 'actor_username', 'created_at')})
        captures[-1].update(summary=json.loads(row['summary_json']), is_latest_import=head['id'] == row['id'])
    _, current = authorized_dataset(conn, token_hash, dataset_id, 'reviewer')
    check_version(current, dataset['version'])
    return {'uploads': uploads, 'captures': captures, 'dataset_version': dataset['version'],
            'coverage_verification': 'not_verified', 'analysis_started': False}


def authorization_original(conn, root, token_hash, dataset_id, upload_id):
    _, dataset = authorized_dataset(conn, token_hash, dataset_id, 'reviewer')
    upload = _upload(conn, dataset_id, upload_id)
    content = _read(root, upload['source_sha256'])
    _, current = authorized_dataset(conn, token_hash, dataset_id, 'reviewer')
    check_version(current, dataset['version'])
    return content, upload['source_sha256']


def capture_export_records(conn, dataset_id):
    for row in conn.execute('SELECT c.*, u.original_name, u.source_sha256 FROM authorization_captures c '
                            'JOIN authorization_uploads u ON u.id = c.upload_id WHERE c.dataset_id = ? '
                            'ORDER BY c.source_system, c.stream_id, c.ordinal', (dataset_id,)):
        record = dict(row)
        for key in ('canonical', 'summary', 'observations'):
            record[key] = json.loads(record.pop(key + '_json'))
        record.update(coverage_verification='not_verified', authorization_control='not_evaluated',
                      proposal_amount_ars=None, is_latest_import=_latest(conn, dataset_id, row['source_system'], row['stream_id'])['id'] == row['id'])
        yield record

"""RN26 external correspondence only. No clinical decisions or medical access."""
from datetime import datetime, timezone
import hashlib
import json
from uuid import uuid4

from .consistent_reads import consistent_read
from .eligibility import classify
from .db import transaction
from .review import _batch
from .security import now_utc
from .service import Problem, authorized_dataset, check_version, event


def _dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def records(conn, revision_id=None, import_id=None, source_row=None):
    """Explicit revision for exports; whole row ancestry for reviewer history."""
    if conn.execute('PRAGMA user_version').fetchone()[0] < 25:
        return []
    result = []
    for row in conn.execute('SELECT c.*,u.username AS actor_username,r.ordinal AS revision_ordinal '
            'FROM medical_consultations c JOIN users u ON u.id=c.actor_id JOIN revisions r ON r.id=c.revision_id '
            'WHERE (? IS NULL OR c.revision_id=?) AND (? IS NULL OR c.import_id=?) '
            'AND (? IS NULL OR c.source_row=?) ORDER BY r.ordinal,c.created_at,c.rowid',
            (revision_id, revision_id, import_id, import_id, source_row, source_row)):
        item = dict(row)
        item['context'] = json.loads(item.pop('context_json'))
        item.pop('request_sha256'); item.pop('request_id')
        item['responses'] = []
        for response in conn.execute('SELECT a.*,u.username AS registrar_username FROM medical_responses a '
                'JOIN users u ON u.id=a.actor_id WHERE consultation_id=? ORDER BY a.created_at,a.rowid', (row['id'],)):
            answer = dict(response); answer.pop('request_sha256'); answer.pop('request_id')
            item['responses'].append(answer)
        item['status'] = 'response_recorded' if item['responses'] else 'awaiting_response'
        result.append(item)
    return result


def summary(conn, revision_id):
    items = records(conn, revision_id=revision_id)
    return {'consultation_ids': [r['id'] for r in items],
            'response_ids': [a['id'] for r in items for a in r['responses']],
            'awaiting_response': sum(not r['responses'] for r in items),
            'note': 'Respuestas externas registradas; no resuelven alertas ni autorizan o modifican importes.'}


def history(conn, token, dataset_id, batch_id, source_row, *, after_read=None):
    def read():
        _, dataset = authorized_dataset(conn, token, dataset_id, 'reviewer')
        batch = _batch(conn, dataset_id, batch_id)
        row = _row(conn, batch, source_row)
        inpatient = _inpatient(row, batch)
        return {'dataset_version': dataset['version'], 'revision_version': batch['revision_version'],
                'revision_id': batch['revision_id'], 'revision_state': batch['state'],
                'can_create_consultation': not inpatient and batch['state'] != 'cerrada',
                'creation_block_reason': 'internacion_fuera_de_alcance' if inpatient else
                    'revision_cerrada' if batch['state'] == 'cerrada' else None,
                'items': records(conn, import_id=batch['import_id'], source_row=source_row)}
    return consistent_read(conn, token, dataset_id, read, after_read=after_read)


def _row(conn, batch, source_row):
    row = conn.execute('SELECT * FROM invoice_rows WHERE import_id=? AND source_row=?',
                       (batch['import_id'], source_row)).fetchone()
    if row is None:
        raise Problem(404, 'Prestación inexistente en este lote')
    return row


def _inpatient(row, batch):
    return classify(row['practice_date'], json.loads(row['permitted_json']).get('F'),
                    batch['period'])['scope_type'] == 'I'


def _text(value, minimum, maximum):
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum or '\x00' in value:
        raise Problem(422, 'Texto requerido ausente, demasiado largo o inválido')
    return value.strip()


def save(conn, token, dataset_id, batch_id, source_row, *, expected_dataset_version,
         expected_revision_version, revision_id, request_id, question=None, consultation_id=None,
         author_name=None, responded_at=None, channel=None, provenance=None, response=None):
    # Hash the exact submitted operation, including its optimistic versions, for safe retry.
    payload = {k: v for k, v in locals().copy().items() if k not in ('conn', 'token')}
    digest = hashlib.sha256(_dump(payload).encode()).hexdigest()
    request_id = _text(request_id, 16, 100)
    table = 'medical_responses' if consultation_id is not None else 'medical_consultations'
    with transaction(conn):
        user, dataset = authorized_dataset(conn, token, dataset_id, 'reviewer')
        batch = _batch(conn, dataset_id, batch_id)
        row = _row(conn, batch, source_row)
        old = conn.execute(f'SELECT id,request_sha256 FROM {table} WHERE actor_id=? AND request_id=?',
                           (user['id'], request_id)).fetchone()
        if old:
            if old['request_sha256'] != digest:
                raise Problem(409, 'La clave de operación ya identifica otro contenido')
            return {'id': old['id'], 'replayed': True, 'dataset_version': dataset['version'],
                    'revision_version': batch['revision_version']}
        check_version(dataset, expected_dataset_version)
        if batch['revision_id'] != revision_id or batch['revision_version'] != expected_revision_version or batch['state'] == 'cerrada':
            raise Problem(409, 'La revisión cambió o está cerrada; actualizá la vista')
        identity, created = str(uuid4()), now_utc()
        if consultation_id is None:
            if _inpatient(row, batch):
                raise Problem(422, 'Internación fuera de alcance: no se permiten consultas nuevas')
            question = _text(question, 10, 4000)
            context = {'original_fields': json.loads(row['permitted_json']),
                       'work_fields': [dict(r) for r in conn.execute('SELECT * FROM work_fields WHERE import_id=? AND source_row=?',
                                                                   (batch['import_id'], source_row))],
                       'dataset_version': dataset['version'], 'revision_version': batch['revision_version']}
            conn.execute('INSERT INTO medical_consultations VALUES(?,?,?,?,?,?,?,?,?,?)',
                         (identity, revision_id, batch['import_id'], source_row, question, _dump(context),
                          user['id'], created, request_id, digest))
        else:
            consultation = conn.execute('SELECT * FROM medical_consultations WHERE id=? AND revision_id=? '
                                        'AND import_id=? AND source_row=?',
                                        (consultation_id, revision_id, batch['import_id'], source_row)).fetchone()
            if consultation is None:
                raise Problem(404, 'Consulta inexistente en esta prestación y revisión')
            author_name, provenance, response = _text(author_name, 2, 200), _text(provenance, 10, 2000), _text(response, 10, 4000)
            if channel not in ('email', 'phone', 'document', 'other'):
                raise Problem(422, 'Medio externo inválido')
            try:
                dt = datetime.fromisoformat(responded_at)
                if dt.tzinfo is None:
                    raise ValueError()
                responded_at = dt.astimezone(timezone.utc).isoformat(timespec='seconds')
                if responded_at > created:
                    raise ValueError()
            except (TypeError, ValueError, OverflowError):
                raise Problem(422, 'Fecha de recepción con zona horaria requerida y no futura') from None
            conn.execute('INSERT INTO medical_responses VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                         (identity, consultation_id, author_name, responded_at, channel, provenance,
                          response, user['id'], created, request_id, digest))
        conn.execute('UPDATE datasets SET version=version+1 WHERE id=?', (dataset_id,))
        conn.execute('UPDATE revisions SET version=version+1 WHERE id=?', (revision_id,))
        event(conn, user['id'], 'external_response_recorded' if consultation_id else 'medical_consultation_recorded', table, identity)
    return {'id': identity, 'replayed': False, 'dataset_version': expected_dataset_version + 1,
            'revision_version': expected_revision_version + 1}

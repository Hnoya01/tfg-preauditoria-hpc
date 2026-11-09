"""RF16/RN30: explicit successor, shared originals and no inherited decisions."""
import json
from uuid import uuid4

from .closure import CLOSURE_RULES
from .db import transaction
from .provisional import _dump, _read_snapshot
from .review import _batch
from .security import now_utc
from .service import Problem, authorized_dataset, check_version, event


def history(conn, token, dataset_id, batch_id):
    with _read_snapshot(conn):
        user, dataset = authorized_dataset(conn, token, dataset_id, 'reviewer')
        current = dict(_batch(conn, dataset_id, batch_id))
        rows = conn.execute('''SELECT r.*,c.archive_sha256,c.manifest_sha256,c.created_at AS closed_at,
            o.previous_revision_id,o.reason,o.actor_id,o.basis_json
            FROM revisions r LEFT JOIN revision_closures c ON c.revision_id=r.id
            LEFT JOIN revision_openings o ON o.revision_id=r.id
            WHERE r.batch_id=? ORDER BY r.ordinal''', (batch_id,)).fetchall()
        items = []
        for row in rows:
            item = {k: row[k] for k in row.keys() if k != 'basis_json'}
            item['opening_basis'] = json.loads(row['basis_json']) if row['basis_json'] else None
            item['current'] = row['id'] == current['revision_id']
            items.append(item)
        from .invoice_handoff import assigned_duty
        result = {'invoice_duty':assigned_duty(conn,user,dataset_id),'items': items, 'dataset_version': dataset['version'], **current,
                  'new_review_policy': 'Original Excel only. Working corrections, scopes, links, declarations, decisions, proposals and limitations require explicit confirmation again; no analysis starts automatically.'}
    authorized_dataset(conn, token, dataset_id, 'reviewer')
    return result


def start(conn, token, dataset_id, batch_id, previous_revision_id,
          expected_dataset_version, expected_revision_version, reason, *, before_commit=None):
    if not 10 <= len(reason.strip()) <= 2000:
        raise Problem(422, 'Indicar motivo de nueva revisión de 10 a 2000 caracteres')
    if before_commit:
        before_commit()
    with transaction(conn):
        user, dataset = authorized_dataset(conn, token, dataset_id, 'reviewer')
        check_version(dataset, expected_dataset_version)
        current = _batch(conn, dataset_id, batch_id)
        if (current['revision_id'] != previous_revision_id or current['state'] != 'cerrada' or
                current['revision_version'] != expected_revision_version):
            raise Problem(409, 'La revisión cambió o existe una revisión abierta; actualizar historial')
        if conn.execute('PRAGMA user_version').fetchone()[0]>=39:
            from .invoice_handoff import assigned_duty
            if conn.execute('SELECT 1 FROM audit_invoice_closures WHERE revision_id=?',(previous_revision_id,)).fetchone():
                if assigned_duty(conn,user,dataset_id) not in ('admin','administrative'):
                    raise Problem(403,'Se requiere función administrativa para iniciar otra revisión de Imágenes.')
                if not conn.execute('SELECT 1 FROM revision_closures WHERE revision_id=?',(previous_revision_id,)).fetchone():
                    from .closure_views import root_path
                    from .image_reports import preserve_legacy_close
                    preserve_legacy_close(conn,root_path(conn),dataset_id,batch_id,previous_revision_id)
        closure = conn.execute('SELECT * FROM revision_closures WHERE revision_id=? AND dataset_id=?',
                               (previous_revision_id, dataset_id)).fetchone()
        if closure is None:
            raise Problem(409, 'La revisión anterior no tiene una captura de cierre verificable')
        manifest = json.loads(closure['manifest_json'])
        identity, stamp = str(uuid4()), now_utc()
        ordinal = conn.execute('SELECT ordinal+1 FROM revisions WHERE id=?', (previous_revision_id,)).fetchone()[0]
        source_ids = [r['id'] for r in conn.execute('SELECT id FROM source_registry WHERE dataset_id=? ORDER BY id', (dataset_id,))]
        basis = {'import_id': current['import_id'], 'previous_closure_id': closure['id'],
                 'previous_archive_sha256': closure['archive_sha256'],
                 'previous_manifest_sha256': closure['manifest_sha256'],
                 'previous_source_ids': manifest['closure']['source_ids'], 'available_source_ids': source_ids,
                 'invoice_sha256': manifest['batch']['source_sha256'], 'period': current['period'],
                 'affected_rules': list(CLOSURE_RULES),
                 'historical_decision_ids': manifest['closure']['decision_ids'],
                 'historical_proposal_version_ids': manifest['closure']['proposal_version_ids'],
                 'working_inputs_policy': 'original_rows_only_reconfirmation_required',
                 'inherited_decision_ids': [], 'inherited_result_ids': [], 'analysis_started': False}
        conn.execute("INSERT INTO revisions VALUES(?,?,?,'preparacion',1,?)", (identity, batch_id, ordinal, stamp))
        conn.execute('INSERT INTO revision_openings VALUES(?,?,?,?,?,?)',
                     (identity, previous_revision_id, user['id'], stamp, reason.strip(), _dump(basis)))
        conn.execute('UPDATE datasets SET version=version+1 WHERE id=?', (dataset_id,))
        event(conn, user['id'], 'new_revision_started', 'revision', identity)
    return {'revision_id': identity, 'previous_revision_id': previous_revision_id, 'ordinal': ordinal,
            'state': 'preparacion', 'revision_version': 1, 'dataset_version': expected_dataset_version+1,
            'analysis_started': False, 'opening_basis': basis}

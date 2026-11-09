"""Dated logical withdrawal/reinstatement of existing HPC references, never deletion."""
from datetime import date
from uuid import uuid4
from .db import transaction
from .hpc_values import _source, _tariff
from .security import now_utc
from .service import Problem, authorized_dataset, check_version, event
from .storage import read_verified


from .hpc_value_status_schema import migration_statements


def save_status(conn, root, token_hash, dataset_id, source_id, *, expected_dataset_version,
                tariff_seq, active, effective_from, document_id, page_number, excerpt, reason):
    if type(active) is not bool or type(tariff_seq) is not int or tariff_seq<1:
        raise Problem(422,'Estado o arancel inválido')
    try:
        if date.fromisoformat(effective_from).isoformat()!=effective_from:raise ValueError()
    except (ValueError,TypeError):raise Problem(422,'Fecha de inicio inválida') from None
    if type(page_number) is not int or not 1<=page_number<=10000 or any(
        not isinstance(s,str) or not 10<=len(s.strip())<=2000 for s in (excerpt,reason)):
        raise Problem(422,'Indicar página, extracto y motivo del cambio')
    with transaction(conn):
        actor,dataset=authorized_dataset(conn,token_hash,dataset_id,'admin')
        check_version(dataset,expected_dataset_version)
        source=_source(conn,dataset_id,source_id)
        if not _tariff(root,source,tariff_seq):raise Problem(422,'Arancel HPC inexistente')
        doc=conn.execute("SELECT sha256 FROM evidence_documents WHERE id=? AND dataset_id=? AND source_id=? AND category='agreement'",(document_id,dataset_id,source_id)).fetchone()
        if doc is None:raise Problem(422,'Seleccioná un PDF de convenio de esta fuente')
        try:read_verified(root,doc['sha256'])
        except (OSError,RuntimeError) as exc:raise Problem(409,'No se pudo verificar el respaldo') from exc
        previous=conn.execute('SELECT * FROM hpc_value_status_versions WHERE dataset_id=? AND source_id=? AND tariff_seq=? ORDER BY ordinal DESC LIMIT 1',(dataset_id,source_id,tariff_seq)).fetchone()
        if previous and effective_from<previous['effective_from']:
            raise Problem(409,'La fecha antecede al último cambio de estado')
        if previous and bool(previous['active'])==active:
            raise Problem(409,'El último estado ya coincide; no se creó una repetición')
        if not previous and active:raise Problem(409,'El arancel original ya está activo')
        identifier=str(uuid4());ordinal=previous['ordinal']+1 if previous else 1
        conn.execute('INSERT INTO hpc_value_status_versions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (identifier,dataset_id,source_id,tariff_seq,ordinal,previous['id'] if previous else None,
             int(active),effective_from,document_id,doc['sha256'],page_number,excerpt.strip(),reason.strip(),actor['id'],now_utc()))
        conn.execute('UPDATE datasets SET version=version+1 WHERE id=?',(dataset_id,))
        event(conn,actor['id'],'hpc_value_status_recorded','hpc_value_status',identifier)
    return {'id':identifier,'ordinal':ordinal,'active':active,'dataset_version':expected_dataset_version+1,
            'use_limit':'Baja o reactivación lógica con fecha; conserva originales e historia. No ejecuta controles ni decisiones.'}

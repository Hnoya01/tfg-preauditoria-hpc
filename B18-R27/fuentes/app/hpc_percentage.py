"""Atomic, preview-bound percentage changes of documented HPC value versions."""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import re
from uuid import uuid4, UUID

from .consistent_reads import consistent_read
from .db import transaction
from .effective_hpc_values import EffectiveHpcValues
from .hpc_values import _source, _insert_value_version
from .local_hpc import tariffs as local_tariffs, _insert_version as _insert_local_version
from .service import Problem, authorized_dataset, check_version, event
from .storage import read_verified
from .values_v1 import source_db


def _preview(conn, root, token, dataset_id, source_id, *, expected_dataset_version,
             tariff_seqs, percentage, effective_from, document_id, page_number, excerpt, reason,
             base_currency=None, base_unit_label=None, base_declaration=False, local_ids=None):
    _, dataset = authorized_dataset(conn, token, dataset_id, 'admin')
    check_version(dataset, expected_dataset_version)
    local_ids=[] if local_ids is None else local_ids
    if (not isinstance(tariff_seqs,list) or not isinstance(local_ids,list)
            or not 1 <= len(tariff_seqs)+len(local_ids) <= 1000
            or any(type(i) is not int or i<1 for i in tariff_seqs)
            or len(set(tariff_seqs))!=len(tariff_seqs)):
        raise Problem(422,'Seleccioná de 1 a 1000 referencias distintas, por secuencia o UUID propio')
    try:
        if any(not isinstance(i,str) or str(UUID(i))!=i for i in local_ids) or len(set(local_ids))!=len(local_ids):
            raise ValueError()
    except (ValueError,TypeError,AttributeError):
        raise Problem(422,'Los IDs propios deben ser UUID completos, canónicos y distintos') from None
    if not isinstance(percentage, str) or not re.fullmatch(r'-?(?:0|[1-9][0-9]{0,3})(?:\.[0-9]{1,4})?', percentage):
        raise Problem(422, 'Porcentaje decimal inválido (hasta cuatro decimales)')
    percent = Decimal(percentage)
    if percent <= -100 or percent == 0 or percent > 1000:
        raise Problem(422, 'El porcentaje debe ser mayor que -100, distinto de cero y hasta 1000')
    try:
        if date.fromisoformat(effective_from).isoformat() != effective_from: raise ValueError()
    except (TypeError, ValueError):
        raise Problem(422, 'Fecha de inicio inválida') from None
    if (type(page_number) is not int or not 1 <= page_number <= 10000
            or not 10 <= len(excerpt.strip()) <= 2000 or not 10 <= len(reason.strip()) <= 1400):
        raise Problem(422, 'Indicá página, cláusula y motivo del cambio')
    if type(base_declaration) is not bool:
        raise Problem(422, 'La declaración de base debe ser explícita')
    source = _source(conn, dataset_id, source_id)
    document = conn.execute("SELECT sha256 FROM evidence_documents WHERE id=? AND dataset_id=? "
                            "AND source_id=? AND category='agreement'", (document_id,dataset_id,source_id)).fetchone()
    if document is None: raise Problem(422, 'Seleccioná un PDF de convenio registrado para esta fuente')
    try:
        read_verified(root, document['sha256'])
        catalog = source_db(read_verified(root, source['source_sha256']))
    except (OSError, RuntimeError, ValueError) as exc:
        raise Problem(409, 'No se pudo verificar el respaldo original') from exc
    try:
        tariffs = [dict(r) for r in catalog.execute("SELECT * FROM hpc_catalog_tariffs WHERE provider='HPC'")]
    finally: catalog.close()
    by_seq = {t['seq']:t for t in tariffs}
    native=local_tariffs(conn,dataset_id,source_id)
    by_local={t['local_id']:t for t in native}
    tariffs+=native
    resolver = EffectiveHpcValues(conn, root, dataset_id, source_id)
    items=[]
    selections=[(False,seq) for seq in sorted(tariff_seqs)]+[(True,pid) for pid in sorted(local_ids)]
    for is_local, identifier in selections:
        seq=identifier
        tariff=(by_local if is_local else by_seq).get(identifier)
        if tariff is None: raise Problem(422, f'Referencia {identifier}: no corresponde a HPC en esta fuente')
        effective=resolver.resolve(tariff,effective_from)
        original = effective['status'] == 'catalogue_candidate'
        if original:
            if (base_declaration is not True or base_currency != 'ARS'
                    or not isinstance(base_unit_label, str) or not 2 <= len(base_unit_label.strip()) <= 100):
                raise Problem(422, f'Referencia {seq}: declará expresamente moneda ARS y unidad del importe base según el PDF')
            unit_label = base_unit_label.strip()
            base_id = None
        elif effective['status'] == 'documented_version_candidate':
            unit_label = effective['declared_unit']
            base_id = effective['value_version']['id']
            if not 2 <= len((unit_label or '').strip()) <= 100:
                raise Problem(422, f'Referencia {seq}: unidad documentada no interpretable')
        else:
            raise Problem(422, f'Referencia {seq}: no hay una base vigente interpretable con respaldo; revisá la referencia')
        if any(v['effective_from'] > effective_from for v in (resolver.local_versions if is_local else resolver.versions).get(identifier, [])):
            raise Problem(409, f'Referencia {seq}: hay una versión posterior; revisá la historia')
        competing=[t for t in tariffs if (t.get('local_id')!=identifier if is_local else (t.get('local_id') is not None or t['seq']!=identifier)) and t['code']==tariff['code']
                   and resolver.resolve(t,effective_from)['selected']
                   and resolver.resolve(t,effective_from)['status']!='withdrawn_reference']
        if competing: raise Problem(422, f'Referencia {seq}: existen referencias simultáneas del mismo código')
        before=Decimal(effective['recorded_amount'])
        after=(before * (1+percent/100)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        if after<=0 or after>=Decimal('1000000000000'):
            raise Problem(422, f'Referencia {seq}: el resultado está fuera del rango permitido')
        items.append({**({'local_id':identifier} if is_local else {'tariff_seq':seq}),
                      'code':tariff['code'],'base_version_id':base_id,
                      'base_origin':'local_documented_version' if is_local else ('catalogue_original' if original else 'documented_version'),
                      'base_source_sha256':source['source_sha256'],
                      'base_declaration_state':'operator_declared_not_automatically_verified' if original else 'documented_version',
                      'before_ars':format(before,'.2f'),'after_ars':format(after,'.2f'),
                      'unit_label':unit_label})
    result={'dataset_id':dataset_id,'source_id':source_id,'source_sha256':source['source_sha256'],
            'dataset_version':expected_dataset_version,'percentage':percentage,'effective_from':effective_from,
            'document_id':document_id,'document_sha256':document['sha256'],'page_number':page_number,
            'excerpt':excerpt.strip(),'reason':reason.strip(),
            'base_currency':base_currency,'base_unit_label':base_unit_label,'base_declaration':base_declaration,
            'rounding':'ROUND_HALF_UP a dos decimales',
            'items':items,'use_limit':'Cambio de referencias; no ejecuta controles ni crea débitos. Redondeo operativo, no regla contractual acreditada.'}
    if local_ids:result['local_ids']=sorted(local_ids)
    result['preview_sha256']=hashlib.sha256(json.dumps(result,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    return result


def preview_percentage(conn, root, token, dataset_id, source_id, **payload):
    return consistent_read(conn,token,dataset_id,lambda:_preview(conn,root,token,dataset_id,source_id,**payload))


def apply_percentage(conn, root, token, dataset_id, source_id, *, preview_sha256, **payload):
    with transaction(conn):
        preview=_preview(conn,root,token,dataset_id,source_id,**payload)
        if preview['preview_sha256'] != preview_sha256:
            raise Problem(409, 'La previsualización cambió; volvé a calcularla antes de aplicar')
        actor,_=authorized_dataset(conn,token,dataset_id,'admin')
        operation=str(uuid4()); versions=[]
        for item in preview['items']:
            base_note = (f"original SHA256 {item['base_source_sha256']} secuencia {item['tariff_seq']}; "
                         f"base ARS {item['before_ars']} unidad {item['unit_label']} declarada por operador según PDF; no verificada automáticamente"
                         if item['base_origin']=='catalogue_original' else item['base_version_id'])
            reason=(f"{preview['reason']} [operación {operation}; porcentaje {preview['percentage']}%; "
                    f"base {base_note}; ROUND_HALF_UP 2 decimales]")
            common=dict(amount_ars=item['after_ars'],unit_label=item['unit_label'],
                effective_from=preview['effective_from'],document_id=preview['document_id'],
                document_sha256=preview['document_sha256'],page_number=preview['page_number'],
                excerpt=preview['excerpt'],reason=reason)
            if item.get('local_id'):
                version_id,ordinal=_insert_local_version(conn,actor['id'],item['local_id'],active=True,**common)
                event(conn,actor['id'],'local_hpc_version_recorded','local_hpc_practice',item['local_id'])
                versions.append({'id':version_id,'ordinal':ordinal,'local_id':item['local_id']})
            else:
                version_id,ordinal=_insert_value_version(conn,actor['id'],dataset_id,source_id,
                    tariff_seq=item['tariff_seq'],code=item['code'],**common)
                versions.append({'id':version_id,'ordinal':ordinal,'tariff_seq':item['tariff_seq']})
        conn.execute('UPDATE datasets SET version=version+1 WHERE id=?',(dataset_id,))
        event(conn,actor['id'],'hpc_percentage_applied','hpc_percentage_operation',operation)
    return {'operation_id':operation,'versions':versions,'dataset_version':preview['dataset_version']+1,
            'preview_sha256':preview_sha256,'use_limit':preview['use_limit']}

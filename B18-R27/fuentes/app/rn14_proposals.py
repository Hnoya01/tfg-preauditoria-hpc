"""Explicit RN14 amount review; simulations never enter the real proposal table.

The arithmetic remains in monetary_gate. This adapter binds its inputs to the
published RN14 capture, the current human decision and the row reference, rather
than weakening the older catalogue/verification-based proposal contract.
"""
from datetime import date
from decimal import Decimal
import json
from uuid import uuid4

from .authorization_controls import synthetic_batch
from .consistent_reads import consistent_read
from .controls import _run_summary
from .db import transaction
from .dependencies import result_affected
from .economic_applicability import VERSION as REFERENCE_VERSION, _sha, _dump, control_results
from .monetary_gate import RowContext, EconomicReference, ProposedComponent, consolidate_current, GateBlocked
from .review import _batch, _latest_run, _result, _decision_status
from .security import now_utc
from .service import Problem, authorized_dataset, check_version, event
from .storage import read_verified

FORMAT = 'RN14-row-proposal-v1'
TABLES = ('proposal_versions', 'rn14_simulation_versions')


def _own_payload(payload):
    parts=payload.get('components',[])
    return (payload.get('format_version')==3 and payload.get('basis',{}).get('version')==FORMAT and
            payload.get('reference_kind')=='row_economic_reference' and len(parts)==1 and
            parts[0].get('rule_code')=='RN14' and parts[0].get('rubric')=='total')


def _signature(result):
    return {k: result[k] for k in ('rule_version','result','reason_code','evidence_json','difference_ars','currency')}


def _latest(conn, table, batch, source_row):
    if table not in TABLES:
        raise ValueError('Unknown amount history')
    return conn.execute(f'SELECT * FROM {table} WHERE revision_id=? AND import_id=? AND source_row=? ORDER BY ordinal DESC LIMIT 1',
                        (batch['revision_id'], batch['import_id'], source_row)).fetchone()


def _candidate(conn, root, dataset_id, batch_id, source_row, batch=None, summary=None):
    batch = batch if batch is not None else _batch(conn, dataset_id, batch_id)
    row = conn.execute('SELECT * FROM invoice_rows WHERE import_id=? AND source_row=?',
                        (batch['import_id'], source_row)).fetchone()
    if row is None:
        raise Problem(404, 'Fila inexistente en esta revisión')
    simulation = synthetic_batch(conn, batch_id)
    value = {'simulation_only': simulation, 'state': 'analysis_missing', 'can_save': False,
             'source_row': source_row, 'run_id': None, 'decision_id': None, 'decision': 'pendiente',
             'alert_id': None, 'automatic_amount_ars': None, 'evidence': None, 'decision_record': None}
    if batch['state'] == 'cerrada':
        return {**value, 'state': 'closed_revision'}
    latest = _latest_run(conn, batch['revision_id'])
    if latest is None:
        return value
    summary = summary if summary is not None else _run_summary(conn, dataset_id, latest['id'])
    result = _result(conn, latest['id'], source_row, 'RN14')
    value['run_id'] = latest['id']
    if result is None or result_affected(summary, source_row, 'RN14'):
        return {**value, 'state': 'analysis_requires_update'}
    evidence = json.loads(result['evidence_json'])
    value['evidence'] = evidence
    alert = conn.execute("SELECT id,version FROM alerts WHERE revision_id=? AND source_row=? AND rule_code='RN14'",
                         (batch['revision_id'], source_row)).fetchone()
    decision, identity = _decision_status(conn, alert['id'], latest['id']) if alert else ('pendiente', None)
    decision_record=conn.execute('SELECT d.id,d.alert_id,d.rule_code,d.state,d.foundation,d.evidence_note,d.actor_id,d.created_at,u.username AS actor_username '
                                 'FROM review_decisions d JOIN users u ON u.id=d.actor_id WHERE d.id=?',(identity,)).fetchone() if identity else None
    value.update(decision=decision,decision_id=identity,decision_record=dict(decision_record) if decision_record else None,
                 alert_id=alert['id'] if alert else None,alert_version=alert['version'] if alert else None)
    if result['result'] != 'con_indicios' or result['difference_ars'] is None or Decimal(result['difference_ars']) <= Decimal('0.01'):
        return {**value, 'state': 'no_positive_rn14_difference'}
    dep = summary['snapshot'].get('economic_engine', {}).get('rows', {}).get(str(source_row))
    if (result['rule_version'] != REFERENCE_VERSION or not dep or not dep['current'] or
            evidence.get('applicability_id') != dep['id'] or dep['state'] != 'confirmed'):
        return {**value, 'state': 'row_reference_missing'}
    expected = control_results(dep, {'source_sha256': evidence['source_sha256'], 'locator': evidence['locator']},
                               synthetic=simulation)['RN14']
    if (tuple(result[k] for k in ('rule_code','result','reason_code','evidence_json','difference_ars','currency')) !=
            (expected[0],expected[1],expected[2],_dump(expected[3]),expected[4],expected[5])):
        return {**value, 'state': 'captured_calculation_mismatch'}
    try:
        original_sha = conn.execute('SELECT source_sha256 FROM batches WHERE id=?', (batch_id,)).fetchone()[0]
        read_verified(root, original_sha)
    except (OSError, RuntimeError, ValueError):
        return {**value, 'state': 'invoice_original_unavailable'}
    value.update(state='ready' if decision == 'confirmada' else 'finding_not_confirmed', can_save=decision == 'confirmada',
                 alert_id=alert['id'] if alert else None, alert_version=alert['version'] if alert else None,
                 decision=decision, decision_id=identity, automatic_amount_ars=result['difference_ars'],
                 basis={'version': FORMAT, 'revision_id':batch['revision_id'], 'source_row':source_row,
                        'invoice_sha256':original_sha, 'run_id':latest['id'], 'run_sha256':summary['snapshot_sha256'],
                        'result':_signature(result), 'reference_dependency_sha256':_sha(dep),
                        'applicability_id':dep['id'], 'decision_id':identity,
                        'decision_snapshot':dict(decision_record) if decision_record else None},
                 reference_dependency=dep, row=dict(row))
    return value


def _calculation(candidate, *, adjusted_ars=None, adjustment_calculation=None, adjustment_reason=None):
    dep, row = candidate['reference_dependency'], candidate['row']
    basis, confirmation = dep['basis'], dep['confirmation']
    source = basis['source']
    # Billing code stays complete. The separately saved tariff/code/version proves
    # the six-digit equivalence; no source catalogue field is rewritten.
    locator=basis['candidate']['tariff'].get('source_locator') or f"hpc_catalog_tariffs.seq={basis['candidate']['tariff']['seq']}"
    if basis['candidate']['value_version']:
        locator+=(';local_hpc_versions.id=' if basis['candidate']['tariff'].get('local_id') else ';hpc_value_versions.id=')+basis['candidate']['value_version']['id']
    reference = EconomicReference(source['id'],source['source_sha256'],source['cut_label'],
        locator, 'HPC',basis['code_complete'],
        confirmation['currency'],confirmation['billing_unit'],Decimal(basis['candidate']['rate_ars']),
        date.fromisoformat(basis['candidate']['effective_from']),date.fromisoformat(confirmation['coverage_through']),
        True,confirmation['note'])
    context = RowContext(row['source_row'],'HPC',basis['code_complete'],date.fromisoformat(basis['practice_date']),
        Decimal(confirmation['covered_quantity']),Decimal(row['honorarios_ars']),Decimal(row['derechos_ars']),
        Decimal(row['total_ars']),confirmation['billing_unit'],basis['disposition']=='included',
        frozenset({(candidate['decision_id'],'RN14')}),frozenset({(source['id'],source['source_sha256'])}))
    part = ProposedComponent(row['source_row'],candidate['decision_id'],'RN14','total',Decimal('0'),
        Decimal(confirmation['covered_quantity']),Decimal(row['total_ars']),reference,
        Decimal(adjusted_ars) if adjusted_ars is not None else None,adjustment_calculation,adjustment_reason)
    return consolidate_current(context,(part,))


def _history(conn, table, batch, source_row):
    if table not in TABLES:
        raise ValueError('Unknown amount history')
    records = conn.execute(f'SELECT p.*,u.username AS actor_username FROM {table} p JOIN users u ON u.id=p.actor_id '
        'WHERE revision_id=? AND import_id=? AND source_row=? ORDER BY ordinal',
        (batch['revision_id'],batch['import_id'],source_row)).fetchall()
    return [{**{k:r[k] for k in ('id','ordinal','previous_id','run_id','actor_username','created_at')},
             'simulation_only':table=='rn14_simulation_versions', 'payload_at_save':json.loads(r['payload_json'])} for r in records]


def _preview(conn,root,token,dataset_id,batch_id,source_row):
    _,dataset=authorized_dataset(conn,token,dataset_id,'reviewer')
    batch=_batch(conn,dataset_id,batch_id)
    candidate=_candidate(conn,root,dataset_id,batch_id,source_row,batch)
    table=TABLES[int(candidate['simulation_only'])]
    previous=_latest(conn,table,batch,source_row)
    if previous:
        payload=json.loads(previous['payload_json'])
        binding=conn.execute('SELECT id FROM rn14_proposal_references WHERE id=?',(previous['id'],)).fetchone()
        if not _own_payload(payload) or binding is None:
            candidate.update(state='other_components_require_review',can_save=False)
    result={k:v for k,v in candidate.items() if k not in ('reference_dependency','row')}
    result.update(dataset_version=dataset['version'],revision_version=batch['revision_version'],revision_id=batch['revision_id'],
                  revision_state=batch['state'],previous_id=previous['id'] if previous else None,
                  proposal_history=_history(conn,'proposal_versions',batch,source_row),
                  simulation_history=_history(conn,'rn14_simulation_versions',batch,source_row))
    result['preview_sha256']=_sha({k:v for k,v in result.items() if k not in ('proposal_history','simulation_history')})
    if previous:
        if not candidate['simulation_only'] and json.loads(previous['payload_json']).get('format_version')!=3:
            from .proposal_freshness import ProposalEvaluator
            result['latest_evaluation']=ProposalEvaluator(conn,root,dataset_id,batch_id,batch).evaluate(previous)
        else:
            result['latest_evaluation']=evaluate_version(conn,root,dataset_id,batch_id,batch,previous,simulation=candidate['simulation_only'])
    else:
        result['latest_evaluation']=None
    return result


def preview(conn,root,token,dataset_id,batch_id,source_row,*,after_read=None):
    return consistent_read(conn,token,dataset_id,lambda:_preview(conn,root,token,dataset_id,batch_id,source_row),after_read=after_read)


def save(conn,root,token,dataset_id,batch_id,source_row,*,expected_dataset_version,expected_revision_version,
         preview_sha256,action,adjusted_ars=None,adjustment_calculation=None,adjustment_reason=None):
    if action not in ('confirm','adjust') or (action=='confirm' and any(v is not None for v in (adjusted_ars,adjustment_calculation,adjustment_reason))):
        raise Problem(422,'Acción o ajuste incompatible')
    if action=='adjust' and (adjusted_ars is None or not isinstance(adjusted_ars,str) or len(adjusted_ars)>32):
        raise Problem(422,'Se requiere un ajuste decimal exacto')
    with transaction(conn):
        user,dataset=authorized_dataset(conn,token,dataset_id,'reviewer')
        check_version(dataset,expected_dataset_version)
        batch=_batch(conn,dataset_id,batch_id)
        if batch['revision_version']!=expected_revision_version or batch['state']=='cerrada':
            raise Problem(409,'La revisión cambió o está cerrada')
        shown=_preview(conn,root,token,dataset_id,batch_id,source_row)
        if shown['preview_sha256']!=preview_sha256:
            raise Problem(409,'El cálculo o sus fundamentos cambiaron; volvé a revisar')
        if not shown['can_save']:
            raise Problem(409,'El cálculo no se puede confirmar: '+shown['state'])
        candidate=_candidate(conn,root,dataset_id,batch_id,source_row,batch)
        try:
            payload=_calculation(candidate,adjusted_ars=adjusted_ars,adjustment_calculation=adjustment_calculation,adjustment_reason=adjustment_reason)
        except (ValueError,TypeError,ArithmeticError,GateBlocked) as exc:
            raise Problem(422,'Ajuste o cálculo sin respaldo suficiente') from exc
        simulation=candidate['simulation_only'];table=TABLES[int(simulation)]
        previous=_latest(conn,table,batch,source_row)
        ordinal=conn.execute(f'SELECT coalesce(max(ordinal),0)+1 FROM {table} WHERE import_id=? AND source_row=?',
                             (batch['import_id'],source_row)).fetchone()[0]
        identity=str(uuid4())
        payload.update(format_version=3,simulation_only=simulation,basis=candidate['basis'],
                       reference_dependency=candidate['reference_dependency'],reference_kind='row_economic_reference',
                       state='simulation_only' if simulation else payload['state'])
        payload['components'][0]['component_id']=str(uuid4())
        from .proposals import _work_basis
        conn.execute(f'INSERT INTO {table} VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (identity,batch['revision_id'],batch['import_id'],source_row,ordinal,previous['id'] if previous else None,
             candidate['run_id'],'HPC',_dump(_work_basis(conn,batch['import_id'],source_row)),payload['amount_ars'],'ARS',
             _dump(payload),user['id'],now_utc()))
        conn.execute('INSERT INTO rn14_proposal_references VALUES(?,?,?,?,?)',
            (identity,None if simulation else identity,identity if simulation else None,
             candidate['decision_id'],candidate['basis']['applicability_id']))
        conn.execute('UPDATE datasets SET version=version+1 WHERE id=?',(dataset_id,))
        conn.execute('UPDATE revisions SET version=version+1 WHERE id=?',(batch['revision_id'],))
        event(conn,user['id'],'rn14_simulation_saved' if simulation else 'rn14_proposal_saved',
              'rn14_simulation' if simulation else 'proposal',identity)
    return {'id':identity,'simulation_only':simulation,'ordinal':ordinal,
            'simulated_amount_ars':payload['amount_ars'] if simulation else None,
            'amount_ars':None if simulation else payload['amount_ars'],
            'dataset_version':expected_dataset_version+1,'revision_version':expected_revision_version+1}


def evaluate_version(conn,root,dataset_id,batch_id,batch,version,*,simulation=False,summary=None,summary_reader=None):
    payload=json.loads(version['payload_json']);parts=payload.get('components',[]);basis=payload.get('basis',{})
    reasons=[];state='requires_update';current=None
    if not _own_payload(payload) or payload.get('simulation_only') is not simulation:
        reasons.append('saved_dependency_basis_missing')
    if _sha(payload.get('reference_dependency'))!=basis.get('reference_dependency_sha256'):
        reasons.append('saved_dependency_basis_missing')
    binding=conn.execute('SELECT * FROM rn14_proposal_references WHERE id=?',(version['id'],)).fetchone()
    if (binding is None or binding['decision_id']!=basis.get('decision_id') or binding['applicability_id']!=basis.get('applicability_id') or
            binding['simulation_id' if simulation else 'proposal_id']!=version['id']):
        reasons.append('saved_dependency_basis_missing')
    if simulation!=synthetic_batch(conn,batch_id):reasons.append('proposal_origin_mismatch')
    if version['revision_id']!=batch['revision_id'] or version['import_id']!=batch['import_id']:reasons.append('proposal_revision_mismatch')
    if batch['state']=='cerrada':reasons.append('closed_revision_snapshot_required')
    if not reasons:
        candidate=_candidate(conn,root,dataset_id,batch_id,version['source_row'],batch,summary)
        if candidate['state']=='finding_not_confirmed' and candidate['decision'] in ('descartada','no_concluyente'):
            reasons.append('decision_excludes_component');state='not_current_by_decision'
        elif not candidate['can_save']:reasons.append(candidate['state'])
        else:
            saved_summary=summary_reader(version['run_id']) if summary_reader else _run_summary(conn,dataset_id,version['run_id'])
            if (basis.get('run_id')!=version['run_id'] or basis.get('run_sha256')!=saved_summary['snapshot_sha256'] or
                    result_affected(saved_summary,version['source_row'],'RN14')):reasons.append('supporting_analysis_changed')
            for key in ('result','reference_dependency_sha256','applicability_id','decision_id','decision_snapshot','invoice_sha256'):
                if basis.get(key)!=candidate.get('basis',{}).get(key):reasons.append('decision_basis_changed' if key in ('decision_id','decision_snapshot') else 'finding_dependencies_changed')
            try:
                part=parts[0]
                adjusted=part.get('adjustment_calculation') is not None or part.get('adjustment_reason') is not None
                reproduced=_calculation(candidate,adjusted_ars=part.get('amount_ars') if adjusted else None,
                    adjustment_calculation=part.get('adjustment_calculation'),adjustment_reason=part.get('adjustment_reason'))
                if (any(part.get(k)!=v for k,v in reproduced['components'][0].items()) or
                        payload.get('amount_ars')!=reproduced['amount_ars'] or version['amount_ars']!=reproduced['amount_ars']):
                    reasons.append('saved_calculation_not_reproducible')
            except (ValueError,TypeError,KeyError,ArithmeticError):reasons.append('saved_calculation_not_reproducible')
            if not reasons:current=version['amount_ars'];state='current'
    components=[{**p,'amount_ars_at_save':p.get('amount_ars'),'current_amount_ars':current if not simulation else None,
                 'freshness':'current' if current is not None else 'requires_update','invalid_reasons':sorted(set(reasons))} for p in parts]
    if simulation:
        return {'simulation_id':version['id'],'simulation_only':True,'ordinal':version['ordinal'],'source_row':version['source_row'],
                'state':state,'simulated_amount_ars':current,'simulated_amount_ars_at_save':version['amount_ars'],
                'calculation_at_save':payload,'invalid_reasons':sorted(set(reasons))}
    return {'proposal_id':version['id'],'ordinal':version['ordinal'],'source_row':version['source_row'],'state':state,'currency':'ARS',
            'amount_ars':current,'amount_ars_at_save':version['amount_ars'],'affected_amount_ars_at_save':None if current is not None else version['amount_ars'],
            'current_component_count':int(current is not None),'affected_component_count':int(current is None),'components':components,
            'invalid_reasons':sorted(set(reasons))}


def simulation_summary(conn,root,dataset_id,batch_id,batch,summary=None):
    if conn.execute('PRAGMA user_version').fetchone()[0]<24:
        return {'simulation_only':True,'version_count':0,'current_count':0,'current_simulated_total_ars':None}
    latest=conn.execute('SELECT s.* FROM rn14_simulation_versions s WHERE revision_id=? AND NOT EXISTS '
        '(SELECT 1 FROM rn14_simulation_versions n WHERE n.revision_id=s.revision_id AND n.source_row=s.source_row AND n.ordinal>s.ordinal)',(batch['revision_id'],)).fetchall()
    evaluated=[evaluate_version(conn,root,dataset_id,batch_id,batch,r,simulation=True,summary=summary) for r in latest]
    amounts=[Decimal(r['simulated_amount_ars']) for r in evaluated if r['simulated_amount_ars'] is not None]
    return {'simulation_only':True,'version_count':conn.execute('SELECT count(*) FROM rn14_simulation_versions WHERE revision_id=?',(batch['revision_id'],)).fetchone()[0],
            'current_count':len(amounts),'current_simulated_total_ars':format(sum(amounts,Decimal('0.00')),'.2f') if amounts else None}

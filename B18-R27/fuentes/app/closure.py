"""C1: justified limitations, atomic review closure and immutable downloads."""
from .revision_scope import revision_table

from collections import defaultdict, Counter
from decimal import Decimal
import hashlib
from io import BytesIO
import json
from pathlib import Path
import time
from uuid import uuid4
from zipfile import ZipFile, ZIP_DEFLATED

from .controls import RULES, _snapshot, _run_summary
from .db import transaction
from .dependencies import result_affected
from .eligibility import effective_row
from .provisional import _dump, _read_snapshot, provisional_export
from .review import _batch, _latest_run, _decision_status
from .security import now_utc
from .service import Problem, authorized_dataset, check_version, event
from .storage import publish_artifact, read_verified
from .closure_basis import FORMAT as BASIS_FORMAT, member_basis

# Documentary rules are specified but not implemented in this prototype. Their
# applicability is not inferred: closure must explicitly preserve that limitation.
CLOSURE_RULES = tuple(sorted(set(RULES) | {'RN20','RN21','RN22'}))


def _sha(value):
    return hashlib.sha256(_dump(value).encode()).hexdigest()


def _context(conn, token, dataset_id, batch_id, *, capture_out=None):
    user, dataset = authorized_dataset(conn, token, dataset_id, 'reviewer')
    batch = _batch(conn, dataset_id, batch_id)
    latest = _latest_run(conn, batch['revision_id'])
    summary = _run_summary(conn, dataset_id, latest['id']) if latest else None
    invoice = conn.execute(f'SELECT i.*,b.source_sha256 FROM {revision_table(conn, "invoice_imports")} i JOIN batches b ON b.id=i.batch_id WHERE i.id=?', (batch['import_id'],)).fetchone()
    snapshot = _snapshot(conn, dataset_id, invoice)
    results = {(r['source_row'], r['rule_code']): dict(r) for r in conn.execute('SELECT * FROM control_results WHERE run_id=?', (latest['id'] if latest else None,))}
    alerts = {(r['source_row'], r['rule_code']): r for r in conn.execute('SELECT * FROM alerts WHERE revision_id=?', (batch['revision_id'],))}
    work = defaultdict(dict)
    for r in conn.execute('SELECT * FROM work_fields WHERE import_id=?', (batch['import_id'],)):
        work[r['source_row']][r['field']] = r['latest_change_id']
    documents = [dict(r) for r in conn.execute('SELECT id,sha256,source_id FROM evidence_documents WHERE dataset_id=? ORDER BY id', (dataset_id,))]
    from .row_documents import export_records as row_document_records
    row_documents=row_document_records(conn,batch['import_id'],batch['revision_id'])
    capture = {'format': BASIS_FORMAT, 'snapshot': snapshot, 'documents': documents}
    if conn.execute('PRAGMA user_version').fetchone()[0]>=34:
        from .csv_reviews import history as csv_history
        reviews = csv_history(conn,batch['revision_id'])
        if reviews:
            capture['csv_coverage_reviews'] = reviews
    if row_documents:
        capture['row_documents']=row_documents
        documents=documents+[{'id':d['id'],'sha256':d['sha256'],'source_row':d['source_row'],
                              'category':d['category'],'reviews':d['reviews']} for d in row_documents]
    from .local_hpc import export_history as local_history
    local=local_history(conn,dataset_id)
    if local:capture['local_hpc_history']=local
    from .agreement_declarations import export_history as agreement_history
    declarations=agreement_history(conn,dataset_id)
    if declarations:capture['agreement_declarations']=declarations
    if capture_out is not None:capture_out.update(capture)
    shared={'documents':_sha(documents),'authorization_scope':_sha(snapshot.get('authorization_engine',{}).get('scope')),
            'authorization_sources':_sha([s for s in snapshot['sources'] if s['kind']=='authorizations']),
            'values':_sha({'sources':[s for s in snapshot['sources'] if s['kind']=='values'],'local':local}) if local else _sha([s for s in snapshot['sources'] if s['kind']=='values']),
            'provider_scope':_sha(snapshot.get('provider_scope'))}
    groups, evaluations, pending = {}, [], []
    for original in conn.execute('SELECT * FROM invoice_rows WHERE import_id=? ORDER BY source_row', (batch['import_id'],)):
        row = effective_row(original, batch['period'])
        if row['disposition'] == 'excluded':
            continue
        for rule in CLOSURE_RULES:
            r = results.get((row['source_row'], rule))
            affected = bool(summary and result_affected(summary, row['source_row'], rule))
            reason = ('control_not_implemented' if rule not in RULES else 'control_not_recorded' if r is None else
                      'requires_update' if affected else r['reason_code'])
            limitation = r is None or affected or r['result'] in ('no_concluyente', 'no_evaluado')
            record = {'source_row': row['source_row'], 'rule_code': rule,
                      'run_id': latest['id'] if r else None, 'result': r['result'] if r else 'no_evaluado',
                      'rule_version': r['rule_version'] if r else None, 'reason_code': reason,
                      'freshness': 'requires_update' if affected else 'current' if r else 'not_evaluated',
                      'evidence_sha256': hashlib.sha256(r['evidence_json'].encode()).hexdigest() if r else None,
                      'applicability': 'unverified' if rule not in RULES or row['disposition']=='indeterminate' else 'in_scope'}
            evaluations.append(record)
            alert = alerts.get((row['source_row'], rule))
            if alert and r and r['result'] == 'con_indicios':
                decision, _ = _decision_status(conn, alert['id'], latest['id'])
                if decision == 'pendiente':
                    pending.append(alert['id'])
            if not limitation:
                continue
            key = _sha([reason])
            group = groups.setdefault(key, {'group_key': key, 'rule_codes': [], 'reason_code': reason, 'members': []})
            if rule not in group['rule_codes']:
                group['rule_codes'].append(rule)
            # Relevant current inputs, not dataset version, bind the justification.
            basis = member_basis(snapshot,shared,row['source_row'],rule,work[row['source_row']])
            group['members'].append({**record, 'input_basis': basis})
    legacy_members = {(r['source_row'], r['rule_code']) for r in conn.execute(
        'SELECT c.source_row,c.rule_code FROM limitation_controls c JOIN review_limitations l ON l.id=c.limitation_id '
        'LEFT JOIN limitation_formats f ON f.limitation_id=l.id WHERE l.revision_id=? AND f.limitation_id IS NULL',
        (batch['revision_id'],))}
    for group in groups.values():
        group['scope_sha256'] = _sha([{k:v for k,v in m.items() if k!='run_id'} for m in group['members']])
        saved = conn.execute('SELECT l.*,f.format_version,f.input_capture_sha256 FROM review_limitations l '
                             'JOIN limitation_formats f ON f.limitation_id=l.id WHERE revision_id=? AND group_key=? '
                             'AND scope_sha256=? AND f.format_version=? ORDER BY ordinal DESC LIMIT 1',
                             (batch['revision_id'], group['group_key'], group['scope_sha256'],BASIS_FORMAT)).fetchone()
        group['justification'] = dict(saved) if saved else None
        legacy=conn.execute('SELECT l.foundation FROM review_limitations l LEFT JOIN limitation_formats f ON f.limitation_id=l.id '
                            'WHERE l.revision_id=? AND l.group_key=? AND f.limitation_id IS NULL ORDER BY ordinal DESC LIMIT 1',
                            (batch['revision_id'],group['group_key'])).fetchone()
        # A new rule version can regroup old controls under requires_update.
        # Keep their legacy status without borrowing a foundation for a new scope.
        group['legacy_reconfirmation_required'] = bool(not saved and
            (legacy or any((m['source_row'], m['rule_code']) in legacy_members for m in group['members'])))
        group['legacy_foundation'] = legacy['foundation'] if legacy and not saved else None
    active = conn.execute("SELECT 1 FROM processing_attempts WHERE batch_id=? AND (state='queued' OR (state='running' AND lease_until>?)) LIMIT 1", (batch_id,time.time())).fetchone() is not None
    public = {'basis_format': BASIS_FORMAT,'input_capture_sha256':_sha(capture),
              'dataset_version': dataset['version'], 'revision_version': batch['revision_version'],
              'revision_id': batch['revision_id'], 'state': batch['state'], 'latest_run_id': latest['id'] if latest else None,
              'pending_alert_count': len(pending), 'pending_alert_ids': pending[:100], 'processing_active': active,
              'limitations': [{k:v for k,v in g.items() if k!='members'} | {'control_count':len(g['members'])} for g in groups.values()],
              'control_count':len(evaluations), 'coverage_note':'Incluye controles del prototipo y limitaciones documentales RN20–RN22 sin inferir aplicabilidad. El cierre no certifica toda la factura.'}
    public['coverage_counts']=dict(Counter(e['result'] for e in evaluations))
    public['decision_count']=conn.execute('SELECT count(*) FROM review_decisions d JOIN alerts a ON a.id=d.alert_id WHERE a.revision_id=?',(batch['revision_id'],)).fetchone()[0]
    records=conn.execute('SELECT p.* FROM proposal_versions p WHERE revision_id=? AND NOT EXISTS '
        '(SELECT 1 FROM proposal_versions x WHERE x.revision_id=p.revision_id AND x.source_row=p.source_row AND x.ordinal>p.ordinal)',(batch['revision_id'],)).fetchall()
    public['proposal_version_count']=conn.execute('SELECT count(*) FROM proposal_versions WHERE revision_id=?',(batch['revision_id'],)).fetchone()[0]
    total=Decimal('0.00');components=0
    if records:
        from .proposal_freshness import ProposalEvaluator
        from .closure_views import root_path
        evaluator=ProposalEvaluator(conn,root_path(conn),dataset_id,batch_id,batch,summary)
        for record in records:
            value=evaluator.evaluate(record);components+=value['current_component_count']
            if value['amount_ars'] is not None:total+=Decimal(value['amount_ars'])
    public['current_proposal_total_ars']=format(total,'.2f') if components else None
    from .rn14_proposals import simulation_summary
    from .closure_views import root_path
    public['rn14_simulations']=simulation_summary(conn,root_path(conn),dataset_id,batch_id,batch,summary)
    from .medical_consultations import summary as consultation_summary
    public['medical_consultations'] = consultation_summary(conn, batch['revision_id'])
    public['can_close'] = batch['state'] != 'cerrada' and not pending and not active and all(g['justification'] for g in groups.values())
    public['preview_sha256'] = _sha([public, _sha(snapshot), pending])
    return public, groups, evaluations, user


def preview(conn, token, dataset_id, batch_id):
    with _read_snapshot(conn):
        _,dataset=authorized_dataset(conn,token,dataset_id,'reviewer')
        version=dataset['version']
        if _batch(conn,dataset_id,batch_id)['state']=='cerrada':
            from .closure_views import frozen
            result=frozen(conn,dataset_id,batch_id)[0]
        else:result, _, _, _ = _context(conn, token, dataset_id, batch_id)
    _, current = authorized_dataset(conn, token, dataset_id, 'reviewer')
    check_version(current, version)
    return result


def save_limitation(conn, token, dataset_id, batch_id, expected_dataset_version, expected_revision_version,
                    group_key, scope_sha256, foundation):
    if not isinstance(foundation,str) or not 10 <= len(foundation.strip()) <= 4000:
        raise Problem(422,'Fundamento obligatorio de 10 a 4000 caracteres')
    with transaction(conn):
        capture={}
        page, groups, _, user = _context(conn, token, dataset_id, batch_id,capture_out=capture)
        _check_versions(page, expected_dataset_version, expected_revision_version)
        group = groups.get(group_key)
        if group is None or group['scope_sha256'] != scope_sha256:
            raise Problem(409,'La limitación o su alcance cambió; actualizar vista previa')
        prior = conn.execute('SELECT id,ordinal FROM review_limitations WHERE revision_id=? AND group_key=? ORDER BY ordinal DESC LIMIT 1', (page['revision_id'],group_key)).fetchone()
        identity = str(uuid4())
        conn.execute('INSERT INTO review_limitations VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                     (identity,page['revision_id'],group_key,scope_sha256,_dump(group['rule_codes']),group['reason_code'],foundation.strip(),(prior['ordinal']+1) if prior else 1,prior['id'] if prior else None,user['id'],now_utc()))
        import_id = _batch(conn,dataset_id,batch_id)['import_id']
        conn.execute('INSERT OR IGNORE INTO closure_input_captures VALUES(?,?)',(_sha(capture),_dump(capture)))
        conn.execute('INSERT INTO limitation_formats VALUES(?,?,?)',(identity,BASIS_FORMAT,_sha(capture)))
        conn.executemany('INSERT INTO limitation_controls VALUES(?,?,?,?,?)',
                         ((identity,import_id,m['source_row'],m['rule_code'],_dump(m)) for m in group['members']))
        conn.execute('UPDATE datasets SET version=version+1 WHERE id=?',(dataset_id,))
        conn.execute('UPDATE revisions SET version=version+1 WHERE id=?',(page['revision_id'],))
        event(conn,user['id'],'closure_limitation_recorded','review_limitation',identity)
    return {'id':identity,'dataset_version':expected_dataset_version+1,'revision_version':expected_revision_version+1}


def _check_versions(page, dataset_version, revision_version):
    if page['state']=='cerrada' or page['dataset_version']!=dataset_version or page['revision_version']!=revision_version:
        raise Problem(409,'La revisión cambió o está cerrada; actualizar vista previa')


def _confirm(page, dataset_version, revision_version, preview_sha256, ids):
    _check_versions(page,dataset_version,revision_version)
    expected = {g['justification']['id'] for g in page['limitations'] if g['justification']}
    if not page['can_close'] or page['preview_sha256']!=preview_sha256 or len(set(ids))!=len(ids) or set(ids)!=expected:
        raise Problem(409,'Hay pendientes o cambió el fundamento del cierre; actualizar y confirmar las limitaciones vigentes')


def close(conn, root, token, dataset_id, batch_id, expected_dataset_version, expected_revision_version,
          preview_sha256, confirmed_limitation_ids, *, after_prepare=None):
    with _read_snapshot(conn):
        capture={}
        page, groups, evaluations, user = _context(conn,token,dataset_id,batch_id,capture_out=capture)
        _confirm(page,expected_dataset_version,expected_revision_version,preview_sha256,confirmed_limitation_ids)
        content, _, manifest = provisional_export(conn,root,token,dataset_id,batch_id,_capture_only=True,_allow_unexecuted=True)
        identity, timestamp = str(uuid4()), now_utc()
        manifest['kind']='closed_review_export'
        manifest['dataset']['version']=expected_dataset_version+1
        manifest['batch'].update(state='cerrada',revision_version=expected_revision_version+1)
        limitations = [{**g['justification'], 'control_count':len(g['members'])} for g in groups.values()]
        with ZipFile(BytesIO(content)) as source:
            decisions = [json.loads(line)['id'] for line in source.read('decisions.jsonl').splitlines()]
            proposals = [json.loads(line)['id'] for line in source.read('proposal_versions.jsonl').splitlines()]
            simulations = ([json.loads(line)['id'] for line in source.read('rn14_simulation_versions.jsonl').splitlines()]
                           if 'rn14_simulation_versions.jsonl' in source.namelist() else [])
            manifest['closure']={'id':identity,'closed_at':timestamp,'actor_id':user['id'], 'preview_sha256':preview_sha256,
                                 'limitations':limitations,'decision_ids':decisions,'proposal_version_ids':proposals,
                                 'simulation_version_ids':simulations,
                                 'source_ids':[s['id'] for s in manifest['sources']], 'control_count':len(evaluations),
                                 'coverage_note':page['coverage_note'], 'economic_approval':False}
            captures={_sha(capture):capture}
            for g in groups.values():
                key=g['justification']['input_capture_sha256']
                stored=conn.execute('SELECT payload_json FROM closure_input_captures WHERE sha256=?',(key,)).fetchone()
                payload=json.loads(stored['payload_json'])
                if _sha(payload)!=key:raise RuntimeError('Closure input capture integrity failed')
                captures[key]=payload
            manifest['closure'].update(basis_format=BASIS_FORMAT,input_capture_sha256=_sha(capture))
            manifest['contents'] += ['closure_controls.jsonl','closure_limitations.jsonl','closure_input_captures.jsonl']
            output=BytesIO()
            with ZipFile(output,'w',ZIP_DEFLATED,compresslevel=6) as archive:
                for info in source.infolist():
                    if info.filename!='manifest.json':archive.writestr(info,source.read(info.filename))
                archive.writestr('closure_controls.jsonl',''.join(_dump(e)+'\n' for e in evaluations))
                archive.writestr('closure_limitations.jsonl',''.join(_dump({'limitation':g['justification'],'members':g['members']})+'\n' for g in groups.values()))
                archive.writestr('closure_input_captures.jsonl',''.join(_dump({'sha256':key,'payload':value})+'\n' for key,value in sorted(captures.items())))
                archive.writestr('manifest.json',_dump(manifest))
        frozen=output.getvalue()
    digest, size, relative = publish_artifact(root,frozen)
    if after_prepare:after_prepare()
    with transaction(conn):
        current, _, _, actor = _context(conn,token,dataset_id,batch_id)
        _confirm(current,expected_dataset_version,expected_revision_version,preview_sha256,confirmed_limitation_ids)
        conn.execute('INSERT OR IGNORE INTO stored_files VALUES(?,?,?,?)',(digest,size,relative,timestamp))
        conn.execute('INSERT INTO revision_closures VALUES(?,?,?,?,?,?,?,?)',
                     (identity,page['revision_id'],dataset_id,digest,_sha(manifest),_dump(manifest),actor['id'],timestamp))
        conn.execute("UPDATE revisions SET state='cerrada',version=version+1 WHERE id=?",(page['revision_id'],))
        conn.execute('UPDATE datasets SET version=version+1 WHERE id=?',(dataset_id,))
        event(conn,actor['id'],'revision_closed','revision',page['revision_id'])
    return {'id':identity,'revision_id':page['revision_id'],'archive_sha256':digest,'manifest_sha256':_sha(manifest),'state':'cerrada',
            'dataset_version':expected_dataset_version+1,'revision_version':expected_revision_version+1}


def download(conn, root, token, dataset_id, batch_id, revision_id=None, *, after_prepare=None):
    user,_=authorized_dataset(conn,token,dataset_id,'reviewer')
    row=conn.execute('SELECT c.* FROM revision_closures c JOIN revisions r ON r.id=c.revision_id '
                     'WHERE c.dataset_id=? AND r.batch_id=? AND (? IS NULL OR c.revision_id=?) '
                     'ORDER BY r.ordinal DESC LIMIT 1', (dataset_id,batch_id,revision_id,revision_id)).fetchone()
    if row is None:raise Problem(404,'Cierre inexistente')
    imaging=conn.execute('PRAGMA user_version').fetchone()[0]>=39 and conn.execute('SELECT 1 FROM audit_invoice_closures WHERE revision_id=?',(row['revision_id'],)).fetchone()
    if imaging:
        from .invoice_handoff import assigned_duty
        if assigned_duty(conn,user,dataset_id) not in ('admin','administrative','auditor'):
            raise Problem(403,'Esta salida requiere una función de revisión de Imágenes.')
    content=read_verified(root,row['archive_sha256'])
    with ZipFile(BytesIO(content)) as archive:
        if _sha(json.loads(archive.read('manifest.json')))!=row['manifest_sha256']:
            raise RuntimeError('Manifest integrity check failed')
    if after_prepare:after_prepare()
    with transaction(conn):
        actor,_=authorized_dataset(conn,token,dataset_id,'reviewer')
        if imaging and assigned_duty(conn,actor,dataset_id) not in ('admin','administrative','auditor'):
            raise Problem(403,'Permiso de revisión de Imágenes revocado.')
        event(conn,actor['id'],'closed_export_response_prepared','revision_closure',_dump({
            'revision_id':row['revision_id'],'closure_id':row['id'],'archive_sha256':row['archive_sha256'],
            'manifest_sha256':row['manifest_sha256'],'semantics':'verified_bytes_prepared_for_response_not_client_receipt'}))
    return content,row['archive_sha256'],row['revision_id']

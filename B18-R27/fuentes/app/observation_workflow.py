"""Internal administrative/auditor workflow, distinct from external correspondence.

Both internal duties use the existing dataset reviewer capability. No grants are
created by this module. Automatic results and monetary proposals remain unchanged.
"""
import hashlib
import json
from uuid import uuid4
from .db import transaction
from .consistent_reads import consistent_read
from .service import authorized_dataset, check_version, event, Problem
from .security import now_utc
from .review import _batch, _latest_run, _result, _decision_status, decide_alerts, _same_result, _dependencies_same
from .dependencies import result_affected
from .controls import _run_summary
from .eligibility import effective_row


def records(conn, revision_id, source_row=None):
    return [dict(r) for r in conn.execute('SELECT e.*,u.username AS actor FROM observation_events e JOIN users u ON u.id=e.actor_id WHERE revision_id=? '+
            ('AND source_row=? ' if source_row is not None else '')+'ORDER BY e.created_at,e.rowid',
            (revision_id,source_row) if source_row is not None else (revision_id,))]


def observation_context(conn,dataset_id,batch):
    latest=_latest_run(conn,batch['revision_id'])
    return (latest,_run_summary(conn,dataset_id,latest['id']) if latest else None,records(conn,batch['revision_id']))


def observations(conn, dataset_id, batch, source_row, *, context=None):
    latest,summary,all_history=context or observation_context(conn,dataset_id,batch)
    if not latest:return []
    history=[e for e in all_history if e['source_row']==source_row]
    items=[]
    for result in conn.execute('SELECT * FROM control_results WHERE run_id=? AND source_row=? ORDER BY rule_code',(latest['id'],source_row)):
        if result['result'] not in ('con_indicios','no_concluyente','no_evaluado'):continue
        rule=result['rule_code']
        entries=[e for e in history if e['rule_code']==rule]
        current=[e for e in entries if e['run_id']==latest['id']]
        reused=False
        if not current and entries:
            prior=entries[-1]
            old_result=_result(conn,prior['run_id'],source_row,rule)
            if old_result is not None and _same_result(old_result,result) and _dependencies_same(conn,prior['run_id'],latest['id'],rule,source_row,{}):
                current=[prior];reused=True
        state='pending'; decision=None
        if current:
            state={'refer':'referred','request_info':'waiting_information','provide_info':'referred','resolve':'resolved'}[current[-1]['action']]
            decision=current[-1]['decision']
        alert=conn.execute('SELECT id,version FROM alerts WHERE revision_id=? AND source_row=? AND rule_code=?',(batch['revision_id'],source_row,rule)).fetchone()
        if alert:
            decision,_=_decision_status(conn,alert['id'],latest['id'])
            if decision in ('confirmada','descartada'):state='resolved'
            elif state=='resolved':state='pending'
        fresh=not result_affected(summary,source_row,rule)
        if not fresh:state='requires_update'
        from .practice_board import reason_label
        items.append({'rule_code':rule,'reason':reason_label(result['reason_code']),
            'category':'inconsistency' if result['result']=='con_indicios' else 'insufficient_information',
            'difference_ars':result['difference_ars'],'state':state,'decision':decision,'reused':reused,'historical_resolution':bool(entries and not current),'fresh':fresh,'evidence':json.loads(result['evidence_json']),
            'history':entries,'decision_history':([dict(r) for r in conn.execute(
                'SELECT d.id,d.state,d.foundation,d.evidence_note,d.created_at,u.username AS actor FROM review_decisions d JOIN users u ON u.id=d.actor_id WHERE d.alert_id=? ORDER BY d.created_at,d.rowid',(alert['id'],))] if alert else []),
            'alert_id':alert['id'] if alert else None})
    return items


def review_page(conn, dataset, batch, row, batch_name, latest, items):
    fields=json.loads(row['permitted_json'])
    for edit in conn.execute('SELECT field,value_json FROM work_fields WHERE import_id=? AND source_row=?',(batch['import_id'],row['source_row'])):
        fields[edit['field']]=json.loads(edit['value_json'])
    return {'dataset_version':dataset['version'],'revision_version':batch['revision_version'],
        'revision_id':batch['revision_id'],'run_id':latest['id'] if latest else None,
        'can_write':batch['state']!='cerrada' and effective_row(row,batch['period'])['disposition']=='included',
        'batch_name':batch_name,'practice_date':row['practice_date'],'fields':fields,'total_ars':row['total_ars'],'items':items}


def page(conn,token,dataset_id,batch_id,source_row):
    def read():
        _,dataset=authorized_dataset(conn,token,dataset_id,'reviewer')
        batch=_batch(conn,dataset_id,batch_id)
        row=conn.execute('SELECT * FROM invoice_rows WHERE import_id=? AND source_row=?',(batch['import_id'],source_row)).fetchone()
        if row is None:raise Problem(404,'Prestación inexistente')
        original=conn.execute('SELECT original_name FROM batches WHERE id=?',(batch_id,)).fetchone()
        context=observation_context(conn,dataset_id,batch)
        items=observations(conn,dataset_id,batch,source_row,context=context)
        return review_page(conn,dataset,batch,row,original['original_name'],context[0],items)
    return consistent_read(conn,token,dataset_id,read)


def save(conn,token,dataset_id,batch_id,source_row,**body):
    digest=hashlib.sha256(json.dumps([dataset_id,batch_id,source_row,body],sort_keys=True,separators=(',',':')).encode()).hexdigest()
    request_id=body['request_id']
    if not 16<=len(request_id)<=100:raise Problem(422,'Clave de operación inválida')
    with transaction(conn):
        user,dataset=authorized_dataset(conn,token,dataset_id,'reviewer')
        batch=_batch(conn,dataset_id,batch_id)
        old=conn.execute('SELECT id,request_sha256 FROM observation_events WHERE actor_id=? AND request_id=?',(user['id'],request_id)).fetchone()
        if old:
            if old['request_sha256']!=digest:raise Problem(409,'La clave identifica otra operación')
            return {'id':old['id'],'replayed':True,'dataset_version':dataset['version'],'revision_version':batch['revision_version']}
        check_version(dataset,body['expected_dataset_version'])
        if batch['state']=='cerrada' or batch['revision_id']!=body['revision_id'] or batch['revision_version']!=body['expected_revision_version']:
            raise Problem(409,'La revisión cambió o está cerrada; actualizá la vista')
        latest=_latest_run(conn,batch['revision_id'])
        if not latest or latest['id']!=body['run_id']:raise Problem(409,'El análisis cambió')
        row=conn.execute('SELECT * FROM invoice_rows WHERE import_id=? AND source_row=?',(batch['import_id'],source_row)).fetchone()
        if row is None:raise Problem(404,'Prestación inexistente')
        if effective_row(row,batch['period'])['disposition']!='included':raise Problem(422,'Prestación fuera del alcance')
        context=(latest,_run_summary(conn,dataset_id,latest['id']),records(conn,batch['revision_id'],source_row))
        observation=next((i for i in observations(conn,dataset_id,batch,source_row,context=context) if i['rule_code']==body['rule_code']),None)
        if not observation or not observation['fresh']:raise Problem(409,'Observación ausente o evidencia por actualizar')
        if observation['state']=='resolved':raise Problem(409,'La observación ya fue resuelta; consultar su historia')
        action,duty=body['action'],body['duty']
        allowed={'refer':('administrative',('pending','referred')),
                 'request_info':('auditor',('referred',)),
                 'provide_info':('administrative',('waiting_information',))}
        if duty not in ('administrative','auditor'):raise Problem(422,'Función interna inválida')
        if action in allowed:
            required,states=allowed[action]
            if duty!=required or observation['state'] not in states:raise Problem(409,'La acción no corresponde al trabajo pendiente')
        elif action=='resolve':
            if duty=='auditor' and observation['state']!='referred':raise Problem(409,'El auditor resuelve la observación derivada')
            if duty=='administrative' and observation['state']!='pending':raise Problem(409,'La observación está en consulta; completá lo solicitado')
            if body.get('decision') not in ('confirmada','descartada'):raise Problem(422,'Elegí una resolución')
        else:raise Problem(422,'Acción inválida')
        for name in ('foundation','evidence_note'):
            if not isinstance(body.get(name),str) or not 10<=len(body[name].strip())<=4000 or '\x00' in body[name]:raise Problem(422,'Fundamento y respaldo explícitos requeridos')
        decision_id=None
        if action=='resolve' and observation['alert_id']:
            alert=conn.execute('SELECT version FROM alerts WHERE id=?',(observation['alert_id'],)).fetchone()
            result=decide_alerts(conn,token,dataset_id,batch_id,dataset['version'],batch['revision_version'],
                [{'id':observation['alert_id'],'expected_version':alert['version']}],body['decision'],body['foundation'],body['evidence_note'],_within_transaction=True,_transaction_summary=context[1])
            decision_id=result['decision_ids'][0]
        else:
            conn.execute('UPDATE datasets SET version=version+1 WHERE id=?',(dataset_id,))
            conn.execute('UPDATE revisions SET version=version+1 WHERE id=?',(batch['revision_id'],))
        identity=str(uuid4())
        conn.execute('INSERT INTO observation_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (identity,batch['revision_id'],latest['id'],source_row,body['rule_code'],action,duty,
             body['foundation'].strip(),body['evidence_note'].strip(),body.get('decision') if action=='resolve' else None,
             decision_id,user['id'],now_utc(),request_id,digest))
        event(conn,user['id'],'observation_'+action,'observation_event',identity)
    return {'id':identity,'replayed':False,'dataset_version':dataset['version']+1,'revision_version':batch['revision_version']+1}


def inbox(conn,token,dataset_id,all_cases=False):
    def read():
        authorized_dataset(conn,token,dataset_id,'reviewer')
        items=[]
        for b in conn.execute('SELECT b.id,b.original_name FROM batches b JOIN current_invoice_imports i ON i.batch_id=b.id WHERE b.dataset_id=?',(dataset_id,)).fetchall():
            batch=_batch(conn,dataset_id,b['id'])
            from .revision_scope import revision_table
            provider=conn.execute(f'SELECT provider FROM {revision_table(conn, "batch_provider_scope_history")} WHERE batch_id=? ORDER BY ordinal DESC LIMIT 1',(b['id'],)).fetchone()
            context=observation_context(conn,dataset_id,batch)
            for row in conn.execute('SELECT source_row,permitted_json,practice_date,total_ars FROM invoice_rows WHERE import_id=?',(batch['import_id'],)).fetchall():
                fields=json.loads(row['permitted_json'])
                for observation in observations(conn,dataset_id,batch,row['source_row'],context=context):
                    if not all_cases and observation['state'] not in ('referred','waiting_information'):continue
                    items.append({'batch_id':b['id'],'batch_name':b['original_name'],'provider':provider['provider'] if provider else 'Prestador por comprobar',
                        'source_row':row['source_row'],'affiliate':fields.get('H'),'date':row['practice_date'],
                        'practice':fields.get('K'),'amount':row['total_ars'],'observation':observation})
        return {'items':items}
    return consistent_read(conn,token,dataset_id,read)

"""Frozen evidence for the imaging workflow, shared with RF16 revision history."""
from io import BytesIO
import hashlib
import json
from uuid import uuid4
from zipfile import ZipFile, ZIP_DEFLATED

from . import invoice_audit
from .closure import _sha
from .provisional import _dump, _read_snapshot, provisional_export
from .report_pdf import make_pdf, ars
from .review import _batch
from .security import now_utc
from .service import authorized_dataset, Problem
from .storage import publish_artifact, read_verified


def report_scope(conn,root,token,ds,batch,closed):
    from .practice_board import practice_search
    query={'family':'images','scope':'included','view':'row_detail','_report':True,'sort':'priority','limit':100}
    first=practice_search(conn,token,ds,batch,query,root=root)
    rev=_batch(conn,ds,batch)['revision_id']
    info=conn.execute('SELECT b.original_name,i.period,i.sheet_name,r.ordinal FROM batches b JOIN invoice_imports i ON i.batch_id=b.id JOIN revisions r ON r.id=? WHERE b.id=?',(rev,batch)).fetchone()
    title='Observaciones de Imágenes HPC'
    lines=[('Cierre' if closed else 'Provisional')+f" | {info['original_name']} | {info['period']}",
           f"Revisión {info['ordinal']} | {rev}",f"Lote {batch}",'Alcance: prestaciones de Imágenes incluidas.',
           f"Factura completa: {first['physical_total']} filas. Excluidas: {first['scope_counts']['excluded']}.",
           f"Imágenes pendientes: {first['row_decision_counts']['pending']}. Revisadas: {first['row_decision_counts']['reviewed']}.",
           'Importes en ARS. Propuestas para validación humana.',*first.get('source_notices',[])]
    items=first['items'][:]
    for offset in range(100,first['filtered_total'],100):
        items.extend(practice_search(conn,token,ds,batch,{**query,'offset':offset},root=root)['items'])
    final_rows={r['source_row']:r for r in invoice_audit.rows(conn,rev)}
    if closed:
        scope=invoice_audit.frozen_scope(conn,rev)
        figures=invoice_audit.totals(scope,list(final_rows.values()))
        lines.append(f"Facturado en Imágenes {ars(figures['images_ars'])} | Débito confirmado {ars(figures['debit_ars'])} | Neto {ars(figures['net_ars'])}")
    lines.append('Informes médicos: el cotejo automático no está implementado.')
    for r in items:
        n=r['source_row']; d=r.get('administrative_decision') or {}
        csv=((r.get('authorization') or {}).get('panel_signal') or {}).get('csv_coverage') or {}
        lines.extend(['',f"{info['sheet_name']}!{n} | Orden {r['order_number']} | {r['practice_date']} | {r['description']}",
                      f"Facturado {ars(r['total_ars'])} | Propuesto {ars((d.get('proposal') or {}).get('amount_ars'))}",
                      'Observaciones: '+(' / '.join(r.get('exception_details',[])) or 'Sin observaciones pendientes.')])
        for k in ('order_id','locator','authorization_date'):
            if csv.get(k): lines.append(f"{ {'order_id':'Orden CSV','locator':'Origen CSV','authorization_date':'Resolución'}[k]}: {csv[k]}")
        ref=r.get('reference_comparison') or {}
        tariff=r.get('applicable_tariff')
        if tariff:lines.append('Convenio HPC: '+ars(tariff['total_ars'])+' | '+(tariff['from'] or 'inicio sin informar')+' a '+tariff['through']+' | '+tariff['locator'])
        if ref.get('source_locator'):lines.append('Convenio HPC: '+str(ref['source_locator']))
        budget=d.get('budget') or {}
        if budget.get('authorized_ars') is not None:
            lines.append('Presupuesto de la orden '+str(budget.get('order_id') or '')+' | '+ars(budget['authorized_ars'])+' | Resolución '+str(budget.get('authorized_on') or 'por verificar'))
        if budget.get('locator'):lines.append('Respaldo del presupuesto: '+budget['locator'])
        prev=d.get('previous')
        if prev and d.get('current'):lines.append('Administrativo: '+ars(prev['amount_ars'])+' | '+prev['reason'])
        elif prev:lines.append('Decisión anterior pendiente de reevaluación.')
        fr=final_rows.get(n)
        if fr:lines.append('Auditoría: '+ars(fr['final_ars'])+' | '+fr['final_reason'])
    return make_pdf(title,lines)


def freeze(conn,root,token,ds,batch,rev,user,excel):
    from .closure import _context
    package,_,manifest=provisional_export(conn,root,token,ds,batch,_capture_only=True,_allow_unexecuted=True)
    pdf=report_scope(conn,root,token,ds,batch,True)
    _,groups,evaluations,_=_context(conn,token,ds,batch)
    stamp,identity=now_utc(),str(uuid4())
    limitations=[]
    for group in groups.values():
        record=group['justification'] or {**{k:group[k] for k in ('group_key','scope_sha256','reason_code')},'rule_codes_json':_dump(group['rule_codes']),'foundation':'Limitación del control conservada al cierre de Imágenes.'}
        limitations.append({'limitation':record,'members':group['members']})
    rows=invoice_audit.rows(conn,rev)
    with ZipFile(BytesIO(package)) as src:
        def ids(name):return [json.loads(s)['id'] for s in src.read(name).splitlines()]
        manifest['closure']={'id':identity,'actor_id':user['id'],'closed_at':stamp,
            'decision_ids':ids('decisions.jsonl')+[f"imagen:{r['source_row']}" for r in rows],
            'proposal_version_ids':ids('proposal_versions.jsonl'),'source_ids':[s['id'] for s in manifest['sources']],
            'control_count':len(evaluations),'coverage_note':'Cierre administrativo y auditor de Imágenes HPC.',
            'economic_approval':False}
        manifest['dataset']['version']+=1
        manifest['kind']='closed_review_export'
        manifest['batch']['state']='cerrada'
        manifest['batch']['revision_version']+=1
        budget_history=[dict(r) for r in conn.execute('SELECT l.*,u.username actor FROM image_budget_links l JOIN users u ON u.id=l.actor_id WHERE l.revision_id=? ORDER BY l.id',(rev,))]
        extras={'vinculos_presupuesto.json':_dump(budget_history),'observaciones.pdf':pdf,'excel_sha256.txt':hashlib.sha256(excel).hexdigest(),'decisiones_imagenes.json':_dump(rows),
                'closure_controls.jsonl':'\n'.join(map(_dump,evaluations)),
                'closure_limitations.jsonl':'\n'.join(map(_dump,limitations))}
        manifest['contents'].extend(extras)
        out=BytesIO()
        with ZipFile(out,'w',ZIP_DEFLATED) as dest:
            for name in src.namelist():
                if name!='manifest.json':dest.writestr(name,src.read(name))
            for name,data in extras.items():dest.writestr(name,data)
            dest.writestr('manifest.json',_dump(manifest))
    digest,size,relative=publish_artifact(root,out.getvalue())
    conn.execute('INSERT OR IGNORE INTO stored_files VALUES(?,?,?,?)',(digest,size,relative,stamp))
    conn.execute('INSERT INTO revision_closures VALUES(?,?,?,?,?,?,?,?)',(identity,rev,ds,digest,_sha(manifest),_dump(manifest),user['id'],stamp))


def preserve_legacy_close(conn,root,ds,batch,rev):
    """Build RF16 provenance solely from the receipt and immutable R19 workbook."""
    old=conn.execute('SELECT c.*,b.original_name,b.source_sha256,i.period,r.version,r.ordinal FROM audit_invoice_closures c JOIN revisions r ON r.id=c.revision_id JOIN batches b ON r.batch_id=b.id JOIN invoice_imports i ON i.batch_id=b.id WHERE c.revision_id=? AND b.id=? AND b.dataset_id=?',(rev,batch,ds)).fetchone()
    if not old:return
    if hashlib.sha256(old['workbook']).hexdigest()!=old['sha256']:
        raise Problem(409,'El Excel histórico no pasó la comprobación de integridad.')
    items=invoice_audit.rows(conn,rev)
    note='Cierre anterior a R22. Solo se conservan las decisiones y evidencias disponibles en aquel cierre.'
    identity=str(uuid4())
    manifest={'kind':'historical_imaging_close','batch':{'source_sha256':old['source_sha256'],'revision_version':old['version'],'ordinal':old['ordinal']},
        'dataset':{'id':ds,'version':None},'closure':{'id':identity,'closed_at':old['closed_at'],'decision_ids':[f"imagen:{r['source_row']}" for r in items],
        'proposal_version_ids':[],'source_ids':[],'coverage_note':note,'control_count':0}}
    lines=[old['original_name']+' | '+old['period'],f"Cierre histórico | Revisión {old['ordinal']} | {rev}",note,
           f"Débito confirmado de Imágenes: {ars(old['debit_ars'])}"]
    for r in items:
        lines.extend([f"Fila {r['source_row']} | Orden {r['order_number']} | {r['description']} | {ars(r['final_ars'])}",r['final_reason']])
    out=BytesIO()
    with ZipFile(out,'w',ZIP_DEFLATED) as archive:
        archive.writestr('manifest.json',_dump(manifest))
        archive.writestr('closure_controls.jsonl','');archive.writestr('closure_limitations.jsonl','')
        archive.writestr('decisiones_imagenes.json',_dump(items))
        archive.writestr('observaciones.pdf',make_pdf('Observaciones de Imágenes HPC',lines))
        archive.writestr('excel_sha256.txt',old['sha256'])
    digest,size,path=publish_artifact(root,out.getvalue())
    conn.execute('INSERT OR IGNORE INTO stored_files VALUES(?,?,?,?)',(digest,size,path,old['closed_at']))
    conn.execute('INSERT INTO revision_closures VALUES(?,?,?,?,?,?,?,?)',(identity,rev,ds,digest,_sha(manifest),_dump(manifest),old['actor_id'],old['closed_at']))


def pdf_download(conn,root,token,ds,batch,revision):
    from .consistent_reads import consistent_read
    return consistent_read(conn,token,ds,lambda:_pdf_download(conn,root,token,ds,batch,revision))


def _pdf_download(conn,root,token,ds,batch,revision):
    with _read_snapshot(conn):
        user,_=authorized_dataset(conn,token,ds,'reviewer')
        if conn.execute('SELECT 1 FROM invoice_review_duties WHERE dataset_id=? LIMIT 1',(ds,)).fetchone():
            from .invoice_handoff import assigned_duty
            if assigned_duty(conn,user,ds) not in ('admin','administrative','auditor'):
                raise Problem(403,'Se requiere una función de revisión de Imágenes en este conjunto.')
        current=_batch(conn,ds,batch)
        rev=revision or current['revision_id']
        frozen=conn.execute('SELECT archive_sha256 FROM revision_closures c JOIN revisions r ON r.id=c.revision_id WHERE c.dataset_id=? AND r.batch_id=? AND r.id=?',(ds,batch,rev)).fetchone()
        if frozen:
            with ZipFile(BytesIO(read_verified(root,frozen[0]))) as archive:
                if 'observaciones.pdf' in archive.namelist():return archive.read('observaciones.pdf')
            raise Problem(409,'Este cierre anterior no contiene un reporte de Imágenes.')
        old=conn.execute("""SELECT b.original_name,i.period,c.debit_ars,c.sha256,c.workbook FROM audit_invoice_closures c
            JOIN revisions r ON r.id=c.revision_id JOIN batches b ON b.id=r.batch_id JOIN invoice_imports i ON i.batch_id=b.id
            WHERE c.revision_id=? AND b.id=? AND b.dataset_id=?""",(rev,batch,ds)).fetchone()
        if old:
            if hashlib.sha256(old['workbook']).hexdigest()!=old['sha256']:raise Problem(409,'Excel histórico no verificable.')
            lines=[old['original_name']+' | '+old['period'],'Cierre anterior a R22 | '+rev,
                   'Las limitaciones que no se conservaron entonces quedan sin determinar.',
                   'Débito confirmado de Imágenes: '+ars(old['debit_ars'])]
            for r in invoice_audit.rows(conn,rev):
                lines.extend([f"Fila {r['source_row']} | Orden {r['order_number']} | {r['description']} | {ars(r['final_ars'])}",r['final_reason']])
            return make_pdf('Observaciones de Imágenes HPC',lines)
        if rev!=current['revision_id'] or current['state']=='cerrada':
            raise Problem(409,'No existe un PDF conservado de esa revisión.')
        return report_scope(conn,root,token,ds,batch,False)

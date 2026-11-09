let invoiceList=[];
function showInvoices(batches){
  invoiceList=batches;
  const body=document.querySelector('#home-rows');body.replaceChildren();
  document.querySelector('#home-add').hidden=batches[0]?.invoice_duty==='auditor';
  for(const b of batches){
    const row=body.insertRow();
    const closed=Boolean(b.audit_closed_at), handed=Boolean(b.handoff_received_at),auditor=b.invoice_duty==='auditor';
    for(const label of [b.original_name,b.period || 'Sin período',closed?'Cerrada':handed?'En auditoría':!b.import_id?'Falta incorporar el Excel':!b.csv_selected?'Falta seleccionar el CSV':b.analyzed?'En revisión administrativa':'Lista para analizar'])row.insertCell().textContent=label;
    const action=(!handed && auditor)?'Aún no recibida':closed?'Ver cierre':handed?(auditor?'Revisar decisiones':'Ver pase'):b.import_id && b.csv_selected?'Abrir factura':'Completar carga';
    const button=document.createElement('button');button.textContent=action;button.disabled=auditor&&!handed;
    button.onclick=async()=>{
      const select=document.querySelector('#invoice-batch');select.value=b.id;
      button.disabled=true;
      try {
        clearPreview();practiceContextKey=null;practiceOffset=0;
        const ds=selectedDataset.id;
        let ready=false;
        if(b.import_id && !handed){
          const [scope,inventory]=await Promise.all([request('/api/datasets/'+ds+'/batches/'+b.id+'/authorization-scope'),
            request('/api/datasets/'+ds+'/authorization-captures')]);
          ready=!scope.issues.length && inventory.captures.some(c=>c.source_system==='HPC-CSV' && c.is_latest_import && scope.current?.capture_ids.includes(c.id));
          if(select.value!==b.id || selectedDataset.id!==ds)return;
          updateIntake(ready,Boolean(scope.current?.csv_complete_range));
        }
        await activateWorkspaceView(handed || ready?'revision':'facturacion');

      } catch(e){message.textContent=e.message;} finally{button.disabled=false;}
    };
    row.insertCell().append(button);
  }
  const inbox=document.querySelector('#home-requests');inbox.hidden=currentRole!=='admin';
  if(currentRole==='admin' && selectedDataset){
    const id=selectedDataset.id;
    request('/api/datasets/'+id+'/practice-requests').then(p=>{
      if(id===selectedDataset?.id)inbox.textContent='Solicitudes de alta ('+p.items.filter(r=>!r.state).length+')';
    }).catch(()=>{inbox.textContent='Solicitudes de alta';});
  }
}
let intakeReady=null;
function intakeIsReady(){
  return Boolean(intakeReady && intakeReady.dataset===selectedDataset?.id &&
    intakeReady.batch===document.querySelector('#invoice-batch').value && intakeReady.ok);
}
function updateIntake(csv=false,complete=false){
  const batch=document.querySelector('#invoice-batch').value;
  const excel=Boolean(invoiceList.find(b=>b.id===batch)?.import_id);
  intakeReady={dataset:selectedDataset?.id,batch,ok:csv && excel};
  document.querySelector('#intake-status').textContent=(excel?'Excel incorporado':'Falta incorporar el Excel')+' · '+
    (csv?(complete?'CSV seleccionado con período declarado':'CSV seleccionado. Cobertura sin confirmar.'):'Falta seleccionar un CSV incorporado para esta factura.');
  document.querySelector('#intake-open').disabled=!intakeReady.ok;
  const current=invoiceList.find(b=>b.id===batch);
  const nav=document.querySelector('[data-workspace-view=revision]');
  nav.disabled=Boolean(current?.audit_workflow && !current.handoff_received_at && !intakeReady.ok);
}
function initInvoiceHome(){
  document.querySelector('#intake-open').onclick=()=>{if(intakeIsReady())activateWorkspaceView('revision');};
  document.querySelector('#home-add').onclick=()=>activateWorkspaceView('facturacion');
  document.querySelector('#home-agreement').onclick=()=>activateWorkspaceView('valores');
  document.querySelector('#home-requests').onclick=()=>activateWorkspaceView('solicitudes');
}

const requestKinds={category:'Categoría sin arancel',agreement:'Alta en convenio HPC'};

async function refreshRequestInbox(ctx){
  if(!sheetCurrent(ctx))return;
  closeSheetReview();
  await loadPracticeBoard();
  if(selectedDataset?.id===ctx.datasetId && document.querySelector('#invoice-batch').value===ctx.batchId &&
     document.querySelector('#sheet-review-panel').hidden)await showPracticeRequests();
}

function showPracticeRequest(item){
  const panel=sheetPanel('Solicitar alta al administrador'),ctx=sheetContext();
  const version=practicePage.dataset_version,revision=practicePage.batch.revision_version;
  detailText(panel,'Práctica',item.code+' · '+item.description);
  const form=document.createElement('form'),kind=sheetField(form,'Qué necesitás','select');
  kind.append(new Option('Elegir',''),...Object.entries(requestKinds).map(([v,label])=>new Option(label,v)));kind.required=true;
  const reason=sheetField(form,'Motivo de la solicitud');
  const submit=document.createElement('button');submit.textContent='Enviar solicitud';
  const status=document.createElement('p');status.setAttribute('role','status');form.append(submit,status);panel.append(form);
  form.addEventListener('submit',async ev=>{
    ev.preventDefault();if(submit.disabled||!sheetCurrent(ctx))return;
    submit.disabled=true;
    try{
      await request(`/api/datasets/${ctx.datasetId}/batches/${ctx.batchId}/rows/${item.source_row}/practice-requests`,
        {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({version,revision,code:item.code,kind:kind.value,reason:reason.value})});
      if(!sheetCurrent(ctx))return;
      await refreshRequestInbox(ctx);
    }catch(e){if(sheetCurrent(ctx)){status.textContent=e.message;submit.disabled=false;}}
  });
}

async function showCategoryHistory(item){
  const panel=sheetPanel('Historia de categoría · '+item.code),ctx=sheetContext();
  try{
    const rows=await request(`/api/datasets/${ctx.datasetId}/batches/${ctx.batchId}/rows/${item.source_row}/category-history`);
    if(!sheetCurrent(ctx))return;
    for(const v of rows){
      const box=document.createElement('section');
      detailText(box,'Versión '+v.ordinal,(v.family==='images'?'Imágenes':'Otras prácticas')+' · '+v.username+' · '+new Date(v.created_at).toLocaleString('es-AR'));
      detailText(box,v.reason?'Motivo':'Registro',v.reason || 'Alta inicial');
      detailText(box,'Respaldo',v.source_file+' · '+v.sheet+' · fila '+v.source_row+', columna '+v.source_column);
      const file=document.createElement('a');file.textContent='Abrir respaldo de esta versión';
      file.href=`/api/datasets/${ctx.datasetId}/batches/${ctx.batchId}/rows/${item.source_row}/category-history/${v.ordinal}/file`;
      box.append(file);
      const trace=document.createElement('details'),title=document.createElement('summary');title.textContent='Huella del archivo';trace.append(title,document.createTextNode(v.source_sha256));box.append(trace);panel.append(box);
    }
  }catch(e){if(sheetCurrent(ctx))panel.textContent=e.message;}
}

async function showPracticeRequests(standalone=false){
  const home=standalone===true;
  const panel=home?document.querySelector('#requests-home-content'):sheetPanel('Solicitudes de alta');
  const ctx=home?{datasetId:selectedDataset?.id}:sheetContext();
  const active=()=>home?activeWorkspaceView==='solicitudes' && selectedDataset?.id===ctx.datasetId:sheetCurrent(ctx);
  panel.replaceChildren();
  try{
    const list=await request('/api/datasets/'+ctx.datasetId+'/practice-requests');
    if(!active())return;
    if(!list.items.length){panel.textContent='No hay solicitudes. Para enviar una, abrí Detalle en una prestación HPC.';return;}
    const history=document.createElement('details'),summary=document.createElement('summary');
    summary.textContent='Solicitudes respondidas ('+list.items.filter(r=>r.state).length+')';history.append(summary);
    for(const r of list.items){
      const box=document.createElement('section');
      detailText(box,r.state==='registered'?'Registrada':r.state==='declined'?'Rechazada':'Pendiente',
        requestKinds[r.kind]+' · '+r.code+' · '+r.description);
      detailText(box,'Solicitud',r.requester+' · '+r.original_name+' · fila '+r.invoice_row+' · '+r.reason);
      if(r.state)detailText(box,'Respuesta',r.answered_by+' · '+r.answer+(r.target?' · '+r.target:''));
      else if(currentRole==='admin'){
        box.append(sheetButton(r.kind==='category'?'Preparar categoría':'Preparar alta en convenio',async()=>{
          try{
            if(r.kind==='category'){
              const row=await request(`/api/datasets/${ctx.datasetId}/batches/${r.batch_id}/rows/${r.invoice_row}/practice-detail`);
              if(!active())return;
              if(row.effective_fields.E!==r.code)throw Error('El código de la fila cambió.');
              if(home){
                document.querySelector('#invoice-batch').value=r.batch_id;practiceContextKey=null;
                await activateWorkspaceView('revision');
              }
              showCategoryRegistration({source_row:r.invoice_row,code:r.code,description:r.description},
                {batchId:r.batch_id,version:row.dataset_version,revision:row.revision_version});
            }else{
              await activateWorkspaceView('valores');
              const source=document.querySelector('#value-source');
              if(!Array.from(source.options).some(o=>o.value===r.source_id))throw Error('La fuente de convenio ya no está disponible.');
              if(selectedDataset?.id!==ctx.datasetId)return;
              selectedDataset.version=list.dataset_version;source.value=r.source_id;source.dispatchEvent(new Event('change'));
              resetLocalHpc();localNode('code').value=r.code;localNode('description').value=r.description;
              localNode('form').scrollIntoView({block:'center'});localNode('amount').focus();
            }
          }catch(e){message.textContent=e.message;}
        }));
        const form=document.createElement('form'),state=sheetField(form,'Respuesta','select');
        state.append(new Option('Elegir',''),new Option('Vincular alta registrada','registered'),new Option('Rechazar solicitud','declined'));state.required=true;
        const reason=sheetField(form,'Motivo de la respuesta');
        const button=document.createElement('button');button.textContent='Guardar respuesta';form.append(button);
        const status=document.createElement('p');status.setAttribute('role','status');form.append(status);box.append(form);
        form.addEventListener('submit',async ev=>{
          ev.preventDefault();if(button.disabled || !active())return;
          button.disabled=true;
          try{
            await request(`/api/datasets/${ctx.datasetId}/practice-requests/${r.id}/answer`,
              {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({version:list.dataset_version,state:state.value,reason:reason.value})});
            if(home){await showPracticeRequests(true);showInvoices(invoiceList);}else await refreshRequestInbox(ctx);
          }catch(e){if(active()){status.textContent=e.message;button.disabled=false;}}
        });
      }
      (r.state?history:panel).append(box);
    }
    if(list.items.some(r=>r.state))panel.append(history);
  }catch(e){if(active())panel.textContent=e.message;}
}

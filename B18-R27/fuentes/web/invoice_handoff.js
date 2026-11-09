let handoffView=null, inspectInvoice=null, sendingHandoff=false, lastSend=null, receiptPage=0;

function resetHandoff(resetSession=false){
  if(resetSession){inspectInvoice=null;lastSend=null;}
  handoffView=null;
  document.querySelector('#handoff-panel').hidden=true;
  document.querySelector('#handoff-send').disabled=true;
  document.querySelector('#handoff-full').hidden=true;
  document.querySelector('#handoff-full').disabled=false;
  delete document.querySelector('#review-workbench').dataset.handoffView;
  document.querySelector('#handoff-inbox').replaceChildren();
  document.querySelector('#handoff-decisions').replaceChildren();
}

function initializeHandoff(){
  // A signed-in auditor can receive a new invoice while this screen stays open.
  document.querySelector('#audit-open-board').addEventListener('click',()=>activateWorkspaceView('revision'));
  document.addEventListener('visibilitychange',pollAuditorInbox);
  window.addEventListener('focus',pollAuditorInbox);
  window.setInterval(pollAuditorInbox,20000);
  document.querySelector('#handoff-send').addEventListener('click',sendHandoff);
  document.querySelector('#handoff-full').addEventListener('click',()=>{
    if(!handoffView)return;
    inspectInvoice=inspectInvoice===handoffView.key?null:handoffView.key;
    clearSheetSelection();closePracticeDetail();setQueuePreset(inspectInvoice?'all':'images');loadPracticeBoard();
  });
}

async function refreshHandoff(page,requestId){
  const dataset=selectedDataset?.id,batch=page.batch.id;
  const base='/api/datasets/'+dataset+'/batches/'+batch+'/handoff';
  const current=()=>requestId===practiceRequest && practicePage===page && selectedDataset?.id===dataset &&
    document.querySelector('#invoice-batch').value===batch;
  const panel=document.querySelector('#handoff-panel'),status=document.querySelector('#handoff-status');
  try{
    const data=page.handoff || await request(base);
    if(!current())return;
    if(data.dataset_version!==page.dataset_version || data.revision_version!==page.batch.revision_version){
      panel.hidden=false;document.querySelector('#handoff-title').textContent='Pase al auditor';
      status.textContent='La factura cambió. Actualizá la planilla.';return;
    }
    const state={data,base,current,key:[dataset,batch,data.revision_id].join('/')};
    handoffView=state;panel.hidden=false;
    const sent=['closed','auditor'].includes(data.state),send=document.querySelector('#handoff-send'),full=document.querySelector('#handoff-full');
    send.hidden=sent || !['administrative','admin'].includes(data.duty);
    send.disabled=sendingHandoff || !data.can_send;
    full.hidden=!sent;
    const title=document.querySelector('#handoff-title');
    if(sent){
      closeSheetReview();closePracticeDetail();
      const details=inspectInvoice!==state.key;
      panel.parentElement.dataset.handoffView=details?'receipt':'invoice';
      full.textContent=details?'Ver factura completa':'Volver a decisiones recibidas';
      title.textContent=data.state==='closed'?'Factura cerrada':'Factura en auditoría';
      status.textContent='Enviada por '+data.receipt.sender+' · '+data.receipt.receipt_count+' decisiones · débito administrativo '+rowAmount(data.receipt.debit_total_ars)+'.';
    }else{
      title.textContent=data.duty==='auditor'?'En revisión administrativa':'Cierre administrativo';
      status.textContent=data.reason || (data.can_send?'Imágenes sin pendientes. '+data.reviewed+' decisiones listas para el auditor.':
        'Esta factura todavía está en revisión administrativa.');
    }
    const jobs=[];
    if(sent && inspectInvoice!==state.key && ['admin','auditor','administrative'].includes(data.duty))jobs.push(showReceived(state,0));
    if(data.duty==='auditor' || data.duty==='admin')jobs.push(showAuditInbox(state,dataset,batch));
    await Promise.all(jobs);
  }catch(error){if(current()){
    panel.hidden=false;document.querySelector('#handoff-send').disabled=true;
    status.textContent='No se pudo consultar el pase. '+error.message;
  }}
}

async function sendHandoff(){
  const state=handoffView;
  if(sendingHandoff || !state?.current() || !state.data.can_send)return;
  const count=state.data.reviewed;
  const draft=document.querySelector('.row-decision-form[data-edited]')?'Hay un borrador sin guardar. Se enviarán los importes guardados. ':'';
  if(!window.confirm(draft+'¿Cerrar la revisión administrativa y pasar '+count+' '+(count===1?'decisión':'decisiones')+' al auditor? Después del pase, el administrativo solo podrá consultarlas.'))return;
  const key=[state.key,state.data.dataset_version,state.data.revision_version].join('/');
  if(lastSend?.key!==key)lastSend={key,id:crypto.randomUUID()};
  sendingHandoff=true;document.querySelector('#handoff-send').disabled=true;
  const status=document.querySelector('#handoff-status');
  status.textContent='Enviando al auditor…';
  try{
    await request(state.base,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
      revision_id:state.data.revision_id,expected_dataset_version:state.data.dataset_version,
      expected_revision_version:state.data.revision_version,request_id:lastSend.id})});
    if(state.current()){clearSheetSelection();closePracticeDetail();await loadPracticeBoard();}
  }catch(error){
    if(state.current()){
      if(error.status===409){await loadPracticeBoard();message.textContent=error.message;}
      else{status.textContent='Comprobá el pase o reintentá. '+error.message;document.querySelector('#handoff-send').disabled=false;}
    }
  }finally{sendingHandoff=false;if(handoffView?.data.can_send)document.querySelector('#handoff-send').disabled=false;}
}

let pollingInbox=false;
async function pollAuditorInbox(){
  const state=handoffView;
  if(pollingInbox || document.hidden || activeWorkspaceView!=='revision' ||
      !state?.current() || state.data.duty!=='auditor')return;
  pollingInbox=true;
  try{
    const dataset=selectedDataset.id,batch=practicePage.batch.id;
    const result=await request('/api/datasets/'+dataset+'/auditor-handoffs');
    if(!state.current())return;
    if(result.items.some(item=>item.batch_id===batch && state.data.state!==(item.closed_at?'closed':'auditor')) && !state.auditEditing){
      await loadPracticeBoard();
    }else if(JSON.stringify(result.items)!==state.inboxSignature){
      await showAuditInbox(state,dataset,batch,result);
    }
  }catch(error){
    if(state.current())document.querySelector('#handoff-status').textContent='No se pudo actualizar la bandeja del auditor. '+error.message;
  }finally{pollingInbox=false;}
}

async function showAuditInbox(state,dataset,batch,result=null){
  if(!result)result=await request('/api/datasets/'+dataset+'/auditor-handoffs');
  if(!state.current())return;
  state.inboxSignature=JSON.stringify(result.items);
  const inbox=document.querySelector('#handoff-inbox');inbox.replaceChildren();
  const title=document.createElement('strong');title.textContent='Facturas recibidas ('+result.items.length+')';inbox.append(title);
  for(const invoice of result.items){
    const b=sheetButton(invoice.original_name+(invoice.closed_at?" · Cerrada":""),()=>{
      const select=document.querySelector('#invoice-batch');select.value=invoice.batch_id;
      inspectInvoice=null;select.dispatchEvent(new Event('change'));
    });
    b.disabled=invoice.batch_id===batch;inbox.append(b);
  }
}

async function showReceived(state,offset){
  const epoch=++receiptPage,root=document.querySelector('#handoff-decisions');
  if(state.data.duty==='auditor' || state.data.state==='closed'){
    return showAuditorPage(state,offset,epoch,root);
  }
  const page=await request(state.base+'/decisions?offset='+offset+'&limit=50');
  if(!state.current() || epoch!==receiptPage)return;
  root.replaceChildren();
  if(!page.items.length){root.textContent='Factura recibida sin decisiones administrativas de Imágenes.';return;}
  const table=document.createElement('table'),head=table.createTHead().insertRow(),body=table.createTBody();
  for(const label of ['Fecha','Orden','Prestación','Decisión','Débito administrativo','Motivo']){
    const h=document.createElement('th');h.scope='col';h.textContent=label;head.append(h);
  }
  for(const row of page.items){
    const tr=body.insertRow();tr.dataset.sourceRow=String(row.source_row);
    for(const value of [row.practice_date?.split('-').reverse().join('/'),row.order_number,row.description,
      rowActionLabels[row.action],rowAmount(row.amount_ars),row.reason]){
      tr.insertCell().textContent=value ?? '—';
    }
    if(row.correction_note && row.correction_note!==row.reason){
      const note=document.createElement('small');note.textContent='Corrección: '+row.correction_note;
      tr.lastElementChild.append(document.createElement('br'),note);
    }
  }
  root.append(table);
  if(page.receipt_count>page.limit){
    const load=async next=>{
      try{await showReceived(state,next);}catch(error){if(state.current())document.querySelector('#handoff-status').textContent=error.message;}
    };
    const prev=sheetButton('Anterior',()=>load(offset-page.limit)),next=sheetButton('Siguiente',()=>load(offset+page.limit));
    prev.disabled=offset===0;next.disabled=offset+page.items.length>=page.receipt_count;
    const caption=document.createElement('span');caption.textContent=(offset+1)+'–'+(offset+page.items.length)+' de '+page.receipt_count;
    root.append(prev,caption,next);
  }
}


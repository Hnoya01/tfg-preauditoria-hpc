function auditText(tag,text,cls){
  const el=document.createElement(tag);el.textContent=text;if(cls)el.className=cls;return el;
}

async function showAuditorPage(state,offset,epoch,root){
  const url=state.base+'/audit',page=await request(url+'?offset='+offset+'&limit=50');
  if(!state.current() || epoch!==receiptPage)return;
  root.replaceChildren();state.auditEditing=false;
  const heading=auditText('h3',page.closed?'Cierre confirmado':'Revisión del auditor');
  const context=auditText('p','Factura completa: '+rowAmount(page.invoice_ars)+' · '+page.image_count+' prestaciones de Imágenes en alcance.');
  const summary=auditText('div','','audit-summary');
  for(const [label,key] of [['Facturado en Imágenes','images_ars'],[page.closed?'Débito confirmado':'Débito a confirmar','debit_ars'],['Neto de Imágenes','net_ars']]){
    const box=auditText('div','');box.append(auditText('span',label),auditText('strong',rowAmount(page[key])));box.dataset.total=key;summary.append(box);
  }
  const note=auditText('p',page.closed?'Confirmó '+page.closed.auditor+' · '+new Date(page.closed.closed_at).toLocaleString('es-AR')+'.':
    'Si coincidís con la decisión administrativa, no hace falta volver a guardarla.');
  const feedback=auditText('p','','audit-feedback');feedback.setAttribute('role','status');
  root.append(heading,context,summary,note,feedback);
  let busy=false,closeButton;const nav=[];
  const load=async n=>{try{await showReceived(state,n);}catch(error){if(state.current())feedback.textContent=error.message;}};
  function lock(value){
    state.auditEditing=value;
    if(closeButton)closeButton.disabled=value;
    for(const [button,disabled] of nav)button.disabled=value || disabled;
    for(const b of root.querySelectorAll('.audit-adjust'))b.disabled=value;
    document.querySelector('#handoff-full').disabled=value;
  }
  async function post(tail,body){
    return request(url+tail,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
      revision_id:page.revision_id,expected_dataset_version:page.dataset_version,...body})});
  }
  function editor(tr,r){
    if(busy || state.auditEditing)return;
    lock(true);
    const detail=tr.parentNode.insertRow(tr.sectionRowIndex+1),cell=detail.insertCell();cell.colSpan=tr.cells.length;
    const form=document.createElement('form');form.className='audit-edit';
    const amt=document.createElement('input');amt.name='amount';amt.type='text';amt.inputMode='decimal';amt.required=true;amt.value=r.final_ars.replace('.',',');
    const reason=document.createElement('textarea');reason.name='reason';reason.required=true;reason.maxLength=4000;reason.value=r.final_reason;
    for(const [label,input] of [['Débito final (ARS)',amt],['Motivo final',reason]]){
      const l=auditText('label',label);l.append(input);form.append(l);
    }
    const save=auditText('button','Guardar ajuste');save.type='submit';
    const cancel=sheetButton('Cancelar',()=>{detail.remove();lock(false);tr.querySelector('.audit-adjust').focus();});
    const msg=auditText('span','');msg.setAttribute('role','status');form.append(save,cancel,msg);cell.append(form);amt.focus();amt.select();
    form.addEventListener('submit',async e=>{
      e.preventDefault();if(busy || !state.current())return;
      const text=amt.value.trim().replace(',','.');
      if(!/^\d+(\.\d{1,2})?$/.test(text)){msg.textContent='Ingresá el importe sin separador de miles.';amt.focus();return;}
      busy=true;save.disabled=cancel.disabled=true;
      try{
        await post('/rows/'+r.source_row,{amount_ars:text,reason:reason.value});
        if(state.current()){await load(offset);if(state.current())root.querySelector('.audit-feedback').textContent='Ajuste guardado. Totales actualizados.';}
      }catch(error){
        if(state.current()){msg.textContent=error.message;if(error.status===409){save.disabled=true;cancel.textContent='Actualizar';cancel.onclick=()=>load(offset);}}
      }finally{busy=false;cancel.disabled=false;if(!msg.textContent || !cancel.onclick)save.disabled=false;}
    });
  }
  if(!page.items.length)root.append(auditText('p','No hay decisiones administrativas en esta factura.'));
  else{
    const table=document.createElement('table'),head=table.createTHead().insertRow(),body=table.createTBody();
    for(const label of ['Fecha','Orden','Prestación','Facturado','Débito final','Motivo final',...(page.can_adjust?['Acción']:[])]){
      const h=auditText('th',label);h.scope='col';head.append(h);
    }
    for(const r of page.items){
      const tr=body.insertRow();tr.dataset.sourceRow=String(r.source_row);
      for(const text of [r.practice_date?.split('-').reverse().join('/'),r.order_number,r.description,rowAmount(r.billed_ars),rowAmount(r.final_ars),r.final_reason]){
        tr.insertCell().textContent=text ?? 'Sin dato';
      }
      if(r.budget_note)tr.cells[5].append(auditText('small',r.budget_note));
      if(r.adjustments){
        tr.cells[4].append(auditText('small','Administrativo: '+rowAmount(r.amount_ars)));
        tr.cells[5].append(auditText('small','Motivo administrativo: '+r.reason));
      }
      if(page.can_adjust){
        const b=sheetButton('Ajustar',()=>editor(tr,r));b.classList.add('audit-adjust');tr.insertCell().append(b);
      }
    }
    root.append(table);
  }
  if(page.receipt_count>page.limit){
    const prev=sheetButton('Anterior',()=>load(offset-page.limit)),next=sheetButton('Siguiente',()=>load(offset+page.limit));
    nav.push([prev,offset===0],[next,offset+page.items.length>=page.receipt_count]);
    root.append(prev,auditText('span',(offset+1)+'–'+(offset+page.items.length)+' de '+page.receipt_count),next);
  }
  if(page.closed && state.data.duty==='auditor'){
    const a=auditText('a','Descargar Excel de débitos');a.href=url+'/excel';a.download='Debitos-Imagenes-HPC.xlsx';a.className='audit-download';root.append(a);
    const report=auditText('a','Descargar PDF de observaciones');report.className='audit-report-download';report.href=url.replace('/handoff/audit','/observations.pdf')+'?revision_id='+encodeURIComponent(page.revision_id);root.append(report);
  }else if(page.can_adjust){
    const requestId=crypto.randomUUID();
    closeButton=sheetButton('Cerrar factura y confirmar '+rowAmount(page.debit_ars),async()=>{
      if(busy || state.auditEditing || !state.current())return;
      if(!window.confirm('¿Confirmar el débito total de Imágenes de '+rowAmount(page.debit_ars)+' y cerrar la factura? Después solo se podrá consultar.'))return;
      busy=true;lock(true);
      try{
        await post('/close',{expected_debit_ars:page.debit_ars,request_id:requestId});
        if(state.current()){
          const select=document.querySelector('#invoice-batch'),opt=select.selectedOptions[0];
          if(opt)opt.textContent=opt.textContent.replace(/ · (En auditoría|Cerrada)$/,'')+' · Cerrada';
          await loadPracticeBoard();
        }
      }catch(error){
        if(state.current()){
          lock(false);feedback.textContent=error.message;
          if(error.status===409){closeButton.disabled=true;feedback.append(' ',sheetButton('Actualizar resumen',()=>loadPracticeBoard()));}
        }
      }finally{busy=false;}
    });closeButton.id='audit-confirm';root.append(closeButton);
  }
  lock(false);
}


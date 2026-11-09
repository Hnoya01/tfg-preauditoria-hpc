/* The server computes amounts, authorizes the user and versions each decision. */
const rowActionLabels={accept:'Aceptar débito propuesto',partial:'Débito parcial',total:'Débito total',none:'Sin débito'};

function openIncorporationGroup(){
  const ctx=sheetContext(), page=practicePage;
  if(!page || !ctx.batchId)return;
  const content=sheetPanel('Registrar incorporación al consolidado',null);
  const form=document.createElement('form');
  const fields={};
  for(const [name,label,type] of [['rows','Filas del Excel incluidas en el comprobante (ej. 2, 5, 8)','text'],
    ['incorporation','Fecha de incorporación','date'],['locator','Comprobante y ubicación','text']]){
    const l=document.createElement('label'),i=document.createElement('input');
    l.textContent=label;i.type=type;i.required=true;l.append(i);form.append(l);fields[name]=i;
  }
  const save=document.createElement('button'),notice=document.createElement('p');
  save.textContent='Guardar para estas filas';form.append(save,notice);content.replaceChildren(form);
  form.onsubmit=async e=>{
    e.preventDefault();
    const rows=fields.rows.value.trim().split(/[ ,]+/).map(Number);
    if(rows.some(n=>!Number.isInteger(n)||n<1)||new Set(rows).size!==rows.length){notice.textContent='Revisá los números de fila.';return;}
    save.disabled=true;
    try{
      await request('/api/datasets/'+ctx.datasetId+'/batches/'+ctx.batchId+'/incorporation-group',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({expected_version:page.dataset_version,expected_revision_version:page.batch.revision_version,
          rows,incorporation:fields.incorporation.value,locator:fields.locator.value.trim()})});
      await loadPracticeBoard();document.querySelector('#sheet-action-status').textContent='Incorporación registrada para '+rows.length+' prestaciones.';
    }catch(err){notice.textContent=err.message;save.disabled=false;}
  };
}

function rowAmount(value){
  return value==null?'—':'$'+boardMoney(value);
}

async function openRowDecision(item,loaded=null){
  const content=sheetPanel('Revisar prestación',item.source_row);
  const ctx=sheetContext(), number=item.source_row;
  const url='/api/datasets/'+ctx.datasetId+'/batches/'+ctx.batchId+'/rows/'+number+'/administrative-decision';
  const feedback=document.querySelector('#sheet-action-status');
  const isHere=()=>sheetCurrent(ctx);
  content.textContent='Cargando la prestación…';
  try{
    const info=loaded || await request(url);
    if(!isHere())return;
    if(info.dataset_version!==practicePage?.dataset_version || info.revision_version!==practicePage?.batch.revision_version){
      content.textContent='La factura cambió. Actualizá la planilla para decidir.';return;
    }
    const heading=document.querySelector('#sheet-review-heading');
    heading.textContent=item.description+' · '+(item.practice_date?.split('-').reverse().join('/') || 'Sin fecha')+' · '+rowAmount(info.billed_ars);
    content.replaceChildren();
    const p=document.createElement('p');p.className='budget-summary';
    p.textContent=info.budget?budgetParagraph(item,info.budget):
      ('Orden '+(item.order_number ?? 'sin informar')+' · '+(item.description || '')+'.');
    const coverage=item.authorization?.panel_signal?.csv_coverage;
    if(info.proposal && !item.late_billing_reason && ['no_aval','one_unit_only','units_partial'].includes(coverage?.status))p.textContent+=' '+info.proposal.reason;
    if(coverage?.allocations?.length>1)p.textContent+=' '+csvUnitsLabel(coverage)+' · órdenes '+[...new Set(coverage.allocations.map(a=>a.order_id))].join(', ')+'.';
    if(coverage?.unit_conversion || coverage?.component_rule_id || ['posterior_candidate','later_movement','unidentified','referred_elsewhere','prior_not_found'].includes(coverage?.status))p.textContent+=' '+csvCoverageText(coverage).join(' ');
    else if(coverage?.temporal)p.textContent+=' '+csvCoverageText(coverage).join(' ');
    else if(!info.budget && coverage?.order_id)p.textContent+=' Orden de autorización '+coverage.order_id+' · resolución '+coverage.authorization_date+(coverage.movement_actor?' · movimiento registrado por '+coverage.movement_actor:'')+'.';
    if(info.budget?.link_id)p.textContent+=' Verificado en '+info.budget.locator+'. '+info.budget.reason;
    if(info.quantity_advisory)p.textContent+=' '+info.quantity_advisory.reason;
    if(coverage?.previous_rows?.length){
      const uses=coverage.previous_rows.map(u=>(u.performed_on || '').split('-').reverse().join('/')+' (fila '+u.source_row+')');
      p.textContent+=' El aval ya respalda la prestación del '+[...new Set(uses)].join(', ')+'.';
    }
    if(item.applicable_tariff){
      const tariff=item.applicable_tariff;
      p.textContent+=' Convenio HPC: '+rowAmount(tariff.total_ars)+' '+tariff.unit+', vigente desde '+tariff.from+
        (tariff.through?' hasta '+tariff.through:'')+' ('+tariff.locator+').';
    }
    content.append(p);
    if(info.can_write && coverage?.status==='posterior_candidate'){
      for(const order of coverage.alternatives.filter(o=>!o.cross_batch)){
        content.append(sheetButton('Vincular orden '+order.order_id+' verificada',async()=>{
          const reason=window.prompt('¿Dónde verificaste que esta orden corresponde a la prestación? Si cubría otra fila, volverá a revisión.');
          if(!reason)return;
          try{
            await request(url.replace('/administrative-decision','/verified-assignment'),{method:'POST',headers:{'Content-Type':'application/json'},
              body:JSON.stringify({expected_version:info.dataset_version,expected_revision_version:info.revision_version,
                source_sha256:order.source_sha256,locator:order.locator,reason})});
            await loadPracticeBoard();
          }catch(err){feedback.textContent=err.message;}
        }));
      }
    }
    if(info.can_write && info.budget && ['one_unit_supported','units_supported'].includes(coverage?.status)
       && (['por_verificar','otro_item'].includes(info.budget.status) || info.budget.link_id)){
      content.append(sheetButton(info.budget.link_id || info.budget.assigned_link_id?'Corregir vínculo de presupuesto':'Vincular presupuesto a esta práctica',()=>{
        const form=document.createElement('form');
        const fields={};
        for(const [key,label] of [['amount_ars','Total autorizado para esta práctica (ARS)'],['locator','Dónde lo verificaste'],['reason','Motivo del vínculo']]){
          const input=document.createElement('input'),l=document.createElement('label');l.textContent=label;input.required=true;
          input.value=key==='amount_ars'?info.budget.authorized_ars || '':'';l.append(input);form.append(l);fields[key]=input;
        }
        const save=document.createElement('button');save.textContent='Guardar vínculo';form.append(save);
        const status=document.createElement('p');form.append(status);content.replaceChildren(p,form);
        form.onsubmit=async e=>{e.preventDefault();save.disabled=true;try{
          await request(url.replace('/administrative-decision','/budget-link'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
            revision_id:info.revision_id,expected_dataset_version:info.dataset_version,evidence_hash:info.evidence_hash,replace_link:info.budget.assigned_link_id || null,
            amount_ars:fields.amount_ars.value.trim().replace(',','.'),locator:fields.locator.value,reason:fields.reason.value})});
          if(!isHere())return;await loadPracticeBoard();const updated=practicePage.items.find(r=>r.source_row===number);
          if(updated)await openRowDecision(updated);
        }catch(err){status.textContent=err.message;save.disabled=false;}};
      }));
    }
    const reasons=info.reasons.filter(reason=>!p.textContent.includes(reason) &&
      !(info.budget?.status==='over' && reason.startsWith('Supera el presupuesto de la orden en ')));
    if(reasons.length)p.textContent+=' Revisar: '+reasons.map(r=>r.replace(/\.$/,'')).join(' · ')+'.';
    if(info.previous){
      const saved=document.createElement('p');saved.className='saved-receipt';
      saved.textContent=(info.current?'Decisión guardada':'Decisión anterior por actualizar')+' · '+rowActionLabels[info.previous.action]+' · '+rowAmount(info.previous.amount_ars)+' · '+info.previous.reason;
      content.append(saved);
      if(info.history.length>1){
        const history=document.createElement('details'),title=document.createElement('summary');title.textContent='Historial de decisiones ('+info.history.length+')';
        history.append(title);
        for(const h of info.history){
          const line=document.createElement('p');line.textContent=h.created_at+' · '+h.actor+' · '+rowActionLabels[h.action]+' · '+rowAmount(h.amount_ars)+' · '+h.reason+(h.correction_note && h.correction_note!==h.reason?' · Corrección: '+h.correction_note:'');
          history.append(line);
        }
        content.append(history);
      }
    }
    if(!info.can_write || info.blocked){
      const status=document.createElement('p');status.textContent=info.blocked?'Revisá el estado de la factura y actualizá los controles antes de decidir.':'Se requiere la función administrativa para guardar.';
      content.append(status);return;
    }
    renderRowForm(content,item,info,url,ctx,feedback);
    const first=content.querySelector('input[type=radio]:not(:disabled)');
    if(first){
      first.focus({preventScroll:true});
      const panel=heading.closest('#sheet-review-panel'), wrapper=panel?.closest('.board-table-wrapper');
      if(wrapper){
        const row=panel.closest('tr')?.previousElementSibling;
        if(row)wrapper.scrollTop+=row.getBoundingClientRect().top-wrapper.getBoundingClientRect().top-86;
      }
    }
  }catch(error){if(isHere())content.textContent='No se pudo abrir la prestación. '+error.message;}
}

function renderRowForm(content,item,info,url,ctx,feedback){
  const form=document.createElement('form');form.className='row-decision-form';
  const refs=document.createElement('select');
  if(info.conflict){
    const label=document.createElement('label');label.textContent='Elegir referencia';
    refs.append(new Option('Elegí cuál corresponde',''));
    for(const [key,quote] of Object.entries(info.choices)){
      refs.append(new Option((key==='budget'?'Presupuesto autorizado':'Convenio HPC aplicable')+' · '+rowAmount(quote.reference_ars),key));
    }
    label.append(refs);form.append(label);
    if(!info.choices.agreement){const note=document.createElement('small');note.textContent='El convenio visible requiere acreditar su aplicabilidad.';form.append(note);}
  }
  const group=document.createElement('fieldset'),legend=document.createElement('legend');
  legend.textContent='Decisión sobre la prestación';group.append(legend);form.append(group);
  const options={};let action=null;
  for(const [key,label] of Object.entries(rowActionLabels)){
    const container=document.createElement('label'),radio=document.createElement('input'),text=document.createElement('span');
    radio.type='radio';radio.name='decision';radio.value=key;
    container.append(radio,text);group.append(container);options[key]={radio,text,label};
    radio.addEventListener('change',()=>{action=key;update();});
  }
  const partial=document.createElement('input');partial.inputMode='decimal';partial.name='partial_ars';partial.placeholder='Ej. 125000,50';
  const partialLabel=document.createElement('label');partialLabel.textContent='Importe parcial en ARS';partialLabel.append(partial);
  const reason=document.createElement('textarea');reason.name='reason';reason.maxLength=2000;
  const reasonLabel=document.createElement('label');reasonLabel.textContent=info.previous?'Motivo de la corrección':'Motivo de la decisión';reasonLabel.append(reason);
  const status=document.createElement('p');status.setAttribute('role','status');
  const submit=document.createElement('button');submit.type='submit';submit.textContent='Guardar y seguir';
  const skip=sheetButton('Dejar pendiente y seguir',async()=>{
    if(busy || !sheetCurrent(ctx) || (form.dataset.edited && !window.confirm('¿Seguir sin guardar esta decisión?')))return;
    try{await advance(null);}catch(error){status.textContent=error.message;}
  });
  form.append(partialLabel,reasonLabel,status,submit);if(!info.current)form.append(skip);content.append(form);
  const pendingNotice=item.observations?.find(o=>o.state==='pending' && o.fresh);
  if(!info.current && pendingNotice){
    form.append(sheetButton('Consultar al auditor',async()=>{
      if(busy || !sheetCurrent(ctx) || (form.dataset.edited && !window.confirm('¿Abrir la consulta sin guardar este borrador?')))return;
      await showObservationReview(item.source_row,pendingNotice.rule_code);
      const refer=document.querySelector('.observation-form input[value="refer"]');
      if(refer)refer.click();
    }));
  }
  let busy=false,requestId=null,lastPayload=null,committed=false;
  function quote(){return info.conflict?info.choices[refs.value]:info.proposal;}
  function validPartial(){
    const v=partial.value.trim().replace(',','.');
    return /^\d+(?:\.\d{1,2})?$/.test(v) && Number(v)>0 && Number(v)<Number(info.billed_ars);
  }
  function update(){
    const proposal=quote(),available=proposal && Number(proposal.amount_ars)>0;
    options.accept.radio.disabled=!available;
    if(action==='accept' && !available){action=null;options.accept.radio.checked=false;}
    options.accept.text.textContent=rowActionLabels.accept+' · '+(available?rowAmount(proposal.amount_ars):'Sin propuesta');
    options.partial.text.textContent=rowActionLabels.partial+(validPartial()?' · '+rowAmount(partial.value.trim().replace(',','.')):'');
    options.total.text.textContent=rowActionLabels.total+' · '+rowAmount(info.billed_ars);
    options.none.text.textContent=rowActionLabels.none+' · '+rowAmount('0.00');
    partialLabel.hidden=action!=='partial';
    const needsReason=action && (action!=='accept' || info.previous || info.conflict);
    reasonLabel.hidden=!needsReason;reason.required=Boolean(needsReason);
    submit.disabled=busy || committed || !action || (info.conflict && !refs.value) || (needsReason && !reason.value.trim()) || (action==='partial' && !validPartial());
  }
  refs.addEventListener('change',update);form.addEventListener('input',()=>{form.dataset.edited='yes';update();});
  async function advance(saved){
    const fromReviewed=practicePage.filters.view==='row_reviewed';
    if(fromReviewed && saved)setQueuePreset('images');
    const first=await loadPracticeBoard({saved,afterRow:item.source_row});
    if(!first || !sheetCurrent(ctx))return;
    let next=first.next_source_row;
    if(next==null && saved && first.filtered_total){
      practiceOffset=0;const start=await loadPracticeBoard();if(!start || !sheetCurrent(ctx))return;
      next=start.items[0]?.source_row;
    }
    if(next==null){
      closeSheetReview();feedback.textContent+=(saved && !first.filtered_total?' No quedan pendientes en esta vista.':' Llegaste al último caso de esta vista.');return;
    }
    const nextItem=practicePage.items.find(r=>r.source_row===next);
    if(nextItem?.administrative_decision)await openRowDecision(nextItem,first.next_source_row===next && practicePage===first?first.next_decision:null);
    else if(nextItem)await showObservationReview(next);
  }
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(submit.disabled || !sheetCurrent(ctx))return;
    const body={expected_dataset_version:info.dataset_version,expected_revision_version:info.revision_version,
      revision_id:info.revision_id,evidence_hash:info.evidence_hash,action,reference:refs.value || null,
      partial_ars:action==='partial'?partial.value.trim().replace(',','.'):null,reason:reasonLabel.hidden?'':reason.value.trim()};
    const serialized=JSON.stringify(body);
    if(lastPayload!==serialized){requestId=crypto.randomUUID();lastPayload=serialized;}
    busy=true;form.inert=true;update();status.textContent='Guardando…';
    try{
      const saved=await request(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...body,request_id:requestId})});
      committed=true;
      if(!sheetCurrent(ctx))return;
      sheetReviewVersion=null;
      feedback.textContent='Guardada en Revisadas: '+item.description+' · '+rowActionLabels[action]+' · '+rowAmount(saved.amount_ars ?? (action==='accept'?quote().amount_ars:action==='total'?info.billed_ars:action==='none'?'0.00':body.partial_ars))+'.';
      status.textContent=feedback.textContent;await advance(saved);
    }catch(error){
      if(sheetCurrent(ctx))status.textContent=(committed?'Decisión guardada. Actualizá la bandeja. ':
        error.status===409?'Volvé a abrir la prestación. ':'Verificá el mensaje o reintentá el mismo guardado. ')+error.message;
    }finally{busy=false;form.inert=committed;update();}
  });
  update();
}


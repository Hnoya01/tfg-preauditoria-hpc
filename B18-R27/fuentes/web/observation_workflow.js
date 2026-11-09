/* Internal workflow: same observation and versioned evidence for both duties. */
const observationPending=new Map();
let observationOwner=null;
function observationSession(){
  const owner=typeof csrfToken==='undefined'?null:csrfToken;
  if(owner!==observationOwner){observationPending.clear();observationOwner=owner;}
  return owner;
}
function observationDuty(){return document.querySelector('#observation-duty')?.value || 'administrative';}
function observationState(state,duty=observationDuty()){
  return {pending:'Pendiente',referred:'Consulta al auditor',waiting_information:duty==='auditor'?'Esperando información':'Completar información solicitada',resolved:'Resuelta',requires_update:'Evidencia por actualizar'}[state] || state;
}
if(typeof window!=='undefined')window.addEventListener('beforeunload',e=>{if(observationPending.size){e.preventDefault();e.returnValue='';}});
function initializeObservationWorkflow(){
  document.querySelector('#observation-duty').addEventListener('change',()=>{
    closeSheetReview();if(practicePage)renderPracticeRows(practicePage.items);
    if(observationDuty()==='auditor')showObservationInbox();
  });
  document.querySelector('#observation-inbox').addEventListener('click',()=>showObservationInbox());
  document.querySelector('#observation-all').addEventListener('click',()=>showObservationInbox(true));
}
async function showObservationInbox(all=false){
  if(!selectedDataset)return;
  const content=sheetPanel(all?'Todos los casos del conjunto permitido':'Auditor · derivaciones prioritarias'),context=sheetContext();
  content.textContent='Consultando casos…';
  try{
    const page=await request(`/api/datasets/${context.datasetId}/observation-inbox?all_cases=${all}`);
    if(!sheetCurrent(context))return;content.replaceChildren();
    detailText(content,'Acceso','Casos del conjunto seleccionado que tu cuenta puede revisar. Cada consulta conserva la prestación, su evidencia e historia.');
    for(const item of page.items){
      const section=document.createElement('section');
      detailText(section,`${item.provider} · ${item.batch_name}`,`${item.affiliate || 'Afiliado sin nombre'} · ${item.date || 'Fecha pendiente'} · ${item.practice || 'Práctica pendiente'} · $ ${item.amount ?? 'Sin importe'}`);
      detailText(section,observationState(item.observation.state),item.observation.reason);
      section.append(sheetButton('Revisar e historia',()=>showObservationReview(item.source_row,item.observation.rule_code,item.batch_id)));content.append(section);
    }
    if(!page.items.length)detailText(content,'Bandeja','No hay casos en esta selección.');
  }catch(e){if(sheetCurrent(context))content.textContent=e.message;}
}
// Decimal strings remain exact even beyond JavaScript's safe integer range.
function observationDecimal(value){
  if(typeof value!=='string')return null;
  const match=/^([+-]?)(\d+)(?:\.(\d+))?$/.exec(value);if(!match)return null;
  const fraction=match[3] || '';return {units:BigInt((match[1]==='-'?'-':'')+match[2]+fraction),scale:fraction.length};
}
function observationMoney(value){
  if(!value)return 'Sin dato';
  const negative=value.units<0n,digits=(negative?-value.units:value.units).toString().padStart(value.scale+1,'0');
  return `${negative?'-':''}${value.scale?digits.slice(0,-value.scale):digits},${(value.scale?digits.slice(-value.scale):'').padEnd(2,'0')}`;
}
function observationSumSummary(item){
  const amounts=item.evidence?.amounts_ars || {};
  const o=observationDecimal(amounts.O),p=observationDecimal(amounts.P),q=observationDecimal(amounts.Q),difference=observationDecimal(item.difference_ars);
  if(!o || !p || !q || !difference)return {summary:'Datos insuficientes para explicar la diferencia de suma.',support:'Consultar el respaldo; no se supone que un importe faltante sea cero.'};
  const scale=Math.max(o.scale,p.scale),sum={units:o.units*10n**BigInt(scale-o.scale)+p.units*10n**BigInt(scale-p.scale),scale};
  const absolute={...difference,units:difference.units<0n?-difference.units:difference.units};
  const direction=difference.units<0n?`El total informado supera la suma en ARS ${observationMoney(absolute)}.`:difference.units>0n?`La suma supera el total informado en ARS ${observationMoney(absolute)}.`:'La suma coincide con el total informado.';
  return {billed:observationMoney(q),sum:observationMoney(sum),brief:direction,summary:`Total informado ${observationMoney(q)} · Suma de honorarios y derechos ${observationMoney(sum)} · Diferencia ${observationMoney(difference)} (suma menos informado).`,support:`${observationMoney(o)} + ${observationMoney(p)}. ${direction} No determina un débito.`};
}
function observationEvidence(parent,item,datasetId){
  const value=item.evidence || {};
  if(item.rule_code==='RN13'){
    const comparison=observationSumSummary(item);
    if(comparison.billed){
      const amounts=document.createElement('dl');amounts.className='review-amounts';
      for(const [label,value] of [['Total informado',comparison.billed],['Suma de componentes',comparison.sum]]){
        const box=document.createElement('div'),term=document.createElement('dt'),amount=document.createElement('dd');
        term.textContent=label;amount.textContent=value+' ARS';box.append(term,amount);amounts.append(box);
      }
      parent.append(amounts);
      const note=document.createElement('p');note.className='review-finding';note.textContent=comparison.brief;parent.append(note);
    }else detailText(parent,'Comprobación',comparison.summary);
  }else if(item.rule_code==='RN09')detailText(parent,'Comprobación','Consultá la declaración individual de esta práctica y su correspondencia con la fila.');
  if(item.rule_code==='RN14' && value.comparable_total_ars!==undefined){
    detailText(parent,'Comparación de convenio',`$ ${value.rate_ars} por unidad × ${value.covered_quantity} = $ ${value.comparable_total_ars}. Facturado $ ${value.billed_total_ars}; diferencia $ ${value.difference_ars}.`);
    detailText(parent,'Referencia',`HPC · código ${value.code_complete}, equivalencia ${value.value_code} · vigencia desde ${value.reference?.effective_from || 'por verificar'} hasta ${value.reference?.tariff?.valid_until || 'sin fin informado'}`);
    detailText(parent,'Fragmento pertinente',value.confirmation?.excerpt);
    if(value.agreement_document?.id){const link=document.createElement('a');link.href=`/api/datasets/${encodeURIComponent(datasetId)}/evidence-pdfs/${encodeURIComponent(value.agreement_document.id)}/file`;link.target='_blank';link.rel='noopener';link.textContent='Abrir convenio original';parent.append(link);}
  }
  const details=document.createElement('details'),title=document.createElement('summary');
  title.textContent='Respaldo técnico y trazabilidad';details.append(title);
  let rendered=false;
  details.addEventListener('toggle',()=>{
    if(details.open && !rendered){appendControlEvidence(details,value);rendered=true;}
  });
  parent.append(details);
}
function savedRowMessage(status,sourceRow,action=null){
  if(!status || status.source_row!==sourceRow)return 'Decisión guardada. Falta verificar el estado de la prestación.';
  const practice=(status.practice || 'Prestación')+' (fila '+sourceRow+')';
  let result='Decisión guardada. ';
  if(action?.action==='resolve'){
    result=action.rule_code==='RN13'?'Observación de suma resuelta. ':
      'Observación resuelta: '+(ruleNames[action.rule_code] || action.rule_code)+'. ';
  }
  const membership=status.in_exceptions?' sigue en Excepciones. Pendiente: '+status.pending.join(' · ')+'.':' salió de Excepciones.';
  const limits=[];
  if(status.inconclusive)limits.push(status.inconclusive===1?'1 control sin conclusión':status.inconclusive+' controles sin conclusión');
  if(status.unevaluated)limits.push(status.unevaluated===1?'1 sin evaluar':status.unevaluated+' sin evaluar');
  const coverage=limits.length?' En esta prestación: '+limits.join(' y ')+'.':'';
  return result+practice+membership+coverage;
}

async function showObservationReview(sourceRow,selectedRule=null,targetBatch=null,boardReview=null,receipt=null){
  if(!selectedDataset)return;
  const content=sheetPanel('Revisión de la prestación',!targetBatch || targetBatch===document.querySelector('#invoice-batch').value?sourceRow:null),context=sheetContext(),owner=observationSession();
  document.querySelector('#legacy-review').open=false;
  const batchId=targetBatch || context.batchId,duty=observationDuty();
  const current=()=>sheetCurrent(context) && observationSession()===owner && observationDuty()===duty;
  const url=`/api/datasets/${context.datasetId}/batches/${batchId}/rows/${sourceRow}/observations`;
  content.textContent='Consultando observaciones e historia…';
  try{
    const page=boardReview || await request(url);if(!current())return;content.replaceChildren();
    const f=page.fields;
    const panel=document.querySelector('#sheet-review-panel');panel.classList.add('observation-panel');
    const dateText=page.practice_date?.split('-').reverse().join('/') || 'Fecha pendiente';
    const amount=page.total_ars==null?'Importe pendiente':page.total_ars.replace('.',',')+' ARS';
    document.querySelector('#sheet-review-heading').textContent=[f.K || 'Práctica pendiente',dateText,amount].join(' · ');
    content.className='observation-layout';
    const contextBox=document.createElement('div');contextBox.className='observation-context';content.append(contextBox);
    if(receipt){
      const notice=document.createElement('p');notice.className='saved-receipt';notice.setAttribute('role','status');
      const status=receipt.list.dataset_version===page.dataset_version && receipt.list.batch.revision_version===page.revision_version
        ? receipt.list.saved_row_status : null;
      notice.textContent=savedRowMessage(status,receipt.sourceRow,receipt.action)+(receipt.atEnd?' Último caso de esta vista.':'');
      contextBox.append(notice);
    }
    detailText(contextBox,'Afiliado',`${f.H || 'Nombre pendiente'} · ${f.C || 'Identidad pendiente'}`);
    const origin=document.createElement('p');origin.className='review-origin';origin.textContent=`${page.batch_name} · fila ${sourceRow} · cantidad ${f.G ?? 'sin informar'}`;contextBox.append(origin);
    const additional=document.createElement('details'),additionalTitle=document.createElement('summary');additionalTitle.textContent='Otros controles y consultas';additional.append(additionalTitle);
    for(const row of document.querySelectorAll('#practice-rows tr[data-source-row]'))row.classList.toggle('review-selected',batchId===context.batchId && Number(row.dataset.sourceRow)===sourceRow);

    if(batchId===context.batchId && practicePage){
      const row=practicePage.items.find(item=>item.source_row===sourceRow);
      const coverage=row?.authorization?.panel_signal?.csv_coverage;
      if(coverage?.budget){const p=document.createElement('p');p.className='budget-summary';p.textContent=budgetParagraph(row,coverage.budget);contextBox.append(p);}
      if(coverage?.status==='already_used' && coverage.previous_rows?.length){
        const trace=document.createElement('div'),label=document.createElement('strong');
        label.textContent=coverage.previous_rows.length===1?'Ver las dos prestaciones':'Ver prestaciones relacionadas';trace.append(label);
        detailText(trace,'En revisión',dateText+' · '+page.batch_name+' · fila '+sourceRow);
        for(const prior of coverage.previous_rows){
          const batch=document.querySelector('#invoice-batch');
          const lot=Array.from(batch.options).find(option=>option.value===prior.batch_id)?.textContent || 'Factura relacionada';
          const day=prior.performed_on.split('-').reverse().join('/');
          detailText(trace,'Con aval CSV',day+' · '+lot+' · fila '+prior.source_row);
        }
        contextBox.append(trace);
      }
      if(row?.exception_reasons?.includes('Revisar aval CSV'))
        additional.append(sheetButton('Consultar aval CSV',()=>showSheetAuthorization(sourceRow)));
      if(row?.exception_reasons?.includes('Diferencia exploratoria a revisar'))
        additional.append(sheetButton('Consultar referencia HPC',()=>showEconomicApplicability(sourceRow,row.reference_comparison?.source_id)));
      const next=sheetButton('Siguiente caso',async()=>{
        if(!current() || next.disabled)return;
        if(observationPending.size){message.textContent='Comprobá el guardado pendiente antes de avanzar.';return;}
        if(content.querySelector('form[data-edited]') && !window.confirm('¿Descartar el borrador y pasar al siguiente caso?'))return;
        next.disabled=true;
        try{
          const list=await loadPracticeBoard({afterRow:sourceRow});
          if(!list || !current())return;
          if(list.next_source_row==null){message.textContent='Llegaste al último caso de esta vista.';return;}
          await showObservationReview(list.next_source_row,null,batchId,list.next_review);
          document.querySelector('#practice-rows .review-selected')?.scrollIntoView({block:'nearest'});
        }finally{if(current())next.disabled=false;}
      });
      next.classList.add('next-without-decision');additional.append(next);
    }
    if(!page.run_id){detailText(content,'Análisis pendiente','Todavía no hay resultados de controles para revisar. Ejecutá el análisis desde Procesamiento.');return;}
    const pending=page.items.filter(i=>i.state!=='resolved').sort((a,b)=>(a.category==='inconsistency'?-1:1)-(b.category==='inconsistency'?-1:1));
    for(const [pendingKey,pendingBody] of observationPending){
      const parts=JSON.parse(pendingKey);
      if(parts[0]!==owner || parts[1]!==context.datasetId || parts[2]!==batchId || parts[3]!==sourceRow)continue;
      const notice=document.createElement('p');notice.className='observation-status';notice.dataset.state='error';notice.setAttribute('role','status');notice.textContent='No pudimos confirmar el guardado.';
      const retry=sheetButton('Comprobar guardado',async()=>{
        retry.disabled=true;notice.dataset.state='working';notice.textContent='Comprobando guardado…';let confirmed=false;
        try{const saved=await request(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(pendingBody)});confirmed=true;observationPending.delete(pendingKey);if(!current())return;notice.dataset.state='saved';notice.textContent='Decisión guardada.';sheetReviewVersion=null;const list=await loadPracticeBoard({saved,savedRow:batchId===context.batchId?sourceRow:null});if(current() && list)await showObservationReview(sourceRow,selectedRule,batchId,null,batchId===context.batchId?{sourceRow,list,action:pendingBody}:null);}
        catch(e){notice.dataset.state='error';notice.textContent=confirmed?'Guardado confirmado; falta actualizar la pantalla.':`No se pudo confirmar: ${e.message}`;retry.disabled=false;}
      });content.append(notice,retry);return;
    }
    if(!page.items.length)return;
    const selector=document.createElement('select');selector.setAttribute('aria-label','Observación a revisar');
    for(const i of page.items)selector.append(new Option(`${ruleNames[i.rule_code]} · ${observationState(i.state,duty)}`,i.rule_code));
    selector.value=selectedRule || pending[0]?.rule_code || page.items[0].rule_code;
    const item=page.items.find(i=>i.rule_code===selector.value);if(!item)return;
    selector.addEventListener('change',()=>{
      if(content.querySelector('form[data-edited]') && !window.confirm('¿Cambiar de control y descartar el texto sin guardar?')){
        selector.value=item.rule_code;return;
      }
      showObservationReview(sourceRow,selector.value,batchId);
    });
    const others=pending.filter(i=>i.rule_code!==item.rule_code);
    additionalTitle.textContent=others.length?'Otros controles · '+others.length+' pendientes':'Otros controles y consultas';
    const choose=document.createElement('label');choose.textContent='Consultar otro control';choose.append(selector);additional.append(choose);
    const issue=document.createElement('h5');issue.className='review-issue';
    issue.textContent=item.rule_code==='RN13'?'Diferencia en la suma':ruleNames[item.rule_code] || item.rule_code;
    contextBox.append(issue);
    if(item.rule_code!=='RN13')detailText(contextBox,'Por revisar',item.reason);
    if(item.reused)detailText(contextBox,'Vigencia','Se conserva la gestión anterior porque el resultado y sus dependencias son equivalentes.');
    if(item.historical_resolution)detailText(contextBox,'Cambio de evidencia','La gestión anterior queda en la historia. El análisis actual requiere una revisión nueva.');

    const historyBox=document.createElement('details'),historyTitle=document.createElement('summary');historyTitle.textContent=`Historia compartida · ${item.history.length} registros`;historyBox.append(historyTitle);
    const referral=[...item.history].reverse().find(h=>h.action==='refer');
    if(referral && duty==='auditor'){
      const question=document.createElement('div');question.className='auditor-question';
      detailText(question,'Pregunta del administrativo',referral.foundation);if(referral.evidence_note!==referral.foundation)detailText(question,'Respaldo de la consulta',referral.evidence_note);contextBox.prepend(question);
    }
    const last=item.history.at(-1);
    if(last && ['provide_info','request_info'].includes(last.action)){detailText(contextBox,last.action==='request_info'?'Información solicitada':'Información incorporada',last.foundation);if(last.evidence_note!==last.foundation)detailText(contextBox,'Respaldo',last.evidence_note);}
    for(const h of item.history){
      const box=document.createElement('details'),title=document.createElement('summary');
      title.textContent=`${h.actor} · ${h.created_at} · ${{refer:'Consulta al auditor',request_info:'Solicitud de información',provide_info:'Información incorporada',resolve:'Resolución guardada'}[h.action]}`;
      box.open=false;box.append(title);detailText(box,'Motivo y respaldo',h.foundation);if(h.evidence_note!==h.foundation)detailText(box,'Respaldo adicional',h.evidence_note);historyBox.append(box);
    }
    const linked=new Set(item.history.map(h=>h.decision_id));
    for(const decision of item.decision_history || []){
      if(linked.has(decision.id))continue;
      detailText(historyBox,`${decision.actor} · ${decision.created_at} · ${decisionLabels[decision.state]}`,`${decision.foundation} · ${decision.evidence_note || 'Sin nota adicional'}`);
    }
    observationEvidence(contextBox,item,context.datasetId);
    if(item.history.length || item.decision_history?.length)contextBox.append(historyBox);
    contextBox.append(additional);
    if(item.state==='resolved'){
      const resolution=document.createElement('section');resolution.className='observation-resolution';
      detailText(resolution,'Resolución guardada',item.decision==='descartada'?'Observación descartada con respaldo.':'Observación confirmada con respaldo.');
      const lastResolution=[...item.history].reverse().find(h=>h.action==='resolve');
      if(lastResolution){detailText(resolution,'Fundamento',lastResolution.foundation);detailText(resolution,'Registró',`${lastResolution.actor} · ${lastResolution.created_at}`);}
      detailText(resolution,'Trabajo restante',pending.length?`${pending.length} observaciones pendientes. ${pending.filter(i=>i.category==='inconsistency').map(i=>ruleNames[i.rule_code]).join(' · ')}`:'No quedan observaciones pendientes en este análisis; no implica autorización.');
      content.append(resolution);
    }
    if(!page.can_write || !item.fresh || item.state==='resolved')return;
    const actions=[];
    if((duty==='administrative' && item.state==='pending') || (duty==='auditor' && item.state==='referred')){
      actions.push(['confirmada','Confirmar observación'],['descartada','Descartar observación']);
    }
    if(duty==='administrative' && item.state==='pending')actions.push(['refer','Consultar al auditor']);
    if(duty==='administrative' && item.state==='waiting_information')actions.push(['provide_info','Completar información']);
    if(duty==='auditor' && item.state==='referred')actions.push(['request_info','Pedir información']);
    if(!actions.length)return;
    const key=JSON.stringify([owner,context.datasetId,batchId,sourceRow,item.rule_code]);
    const form=document.createElement('form');form.className='sheet-action-form observation-form';
    form.addEventListener('input',()=>{form.dataset.edited='true';});
    const choices=document.createElement('fieldset'),legend=document.createElement('legend');
    legend.textContent='Decisión sobre esta observación';choices.append(legend);
    for(const [value,label] of actions){
      const wrapper=document.createElement('label'),radio=document.createElement('input');
      radio.type='radio';radio.name='review-action';radio.value=value;radio.required=true;
      radio.setAttribute('aria-label',label);
      const shortLabel={confirmada:'Confirmar',descartada:'Descartar',refer:'Consultar auditor'}[value] || label;
      wrapper.append(radio,document.createTextNode(shortLabel));choices.append(wrapper);
    }
    form.append(choices);
    const foundation=sheetField(form,'Motivo y respaldo');
    foundation.placeholder='Indicá qué comprobaste y en qué te basás, o qué necesitás consultar.';
    const submit=document.createElement('button');submit.type='submit';
    const canAdvance=batchId===context.batchId && Boolean(practicePage);
    submit.textContent=canAdvance?'Guardar y seguir':'Guardar decisión';
    const status=document.createElement('p');status.className='observation-status';status.setAttribute('role','status');
    form.append(submit,status);content.append(form);
    function feedback(text,state){status.textContent=text;status.dataset.state=state;}
    let busy=false;
    form.addEventListener('submit',async event=>{
      event.preventDefault();if(busy || !current())return;
      let body=observationPending.get(key);
      const retry=Boolean(body);
      if(!body){
        const selection=choices.querySelector('input:checked')?.value;
        if(!selection)return;
        const resolution=['confirmada','descartada'].includes(selection);
        body={expected_dataset_version:page.dataset_version,expected_revision_version:page.revision_version,
          revision_id:page.revision_id,run_id:page.run_id,request_id:crypto.randomUUID(),rule_code:item.rule_code,
          action:resolution?'resolve':selection,duty,foundation:foundation.value,evidence_note:foundation.value,
          decision:resolution?selection:null};
        observationPending.set(key,body);
      }
      busy=true;submit.disabled=true;choices.disabled=true;foundation.disabled=true;
      const goNext=canAdvance && !retry;
      feedback(retry?'Comprobando guardado…':'Guardando decisión…','working');
      let confirmed=false;
      try{
        const saved=await request(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});confirmed=true;observationPending.delete(key);
        if(!current())return;feedback(goNext?'Decisión guardada. Buscando el siguiente caso…':'Decisión guardada.','saved');
        // Read failures after this point never turn a confirmed write into a failure.
        // Keep the panel's version guard while refreshing the grid.
        sheetReviewVersion=null;
        const list=await loadPracticeBoard({saved,afterRow:goNext?sourceRow:null,savedRow:canAdvance?sourceRow:null});
        if(!current() || !list)return;
        if(goNext && list.next_source_row!=null){
          await showObservationReview(list.next_source_row,null,batchId,list.next_review,{sourceRow,list,action:body});
          document.querySelector('#practice-rows .review-selected')?.scrollIntoView({block:'nearest'});
        }else{
          await showObservationReview(sourceRow,item.rule_code,batchId,null,canAdvance?{sourceRow,list,atEnd:goNext,action:body}:null);
        }
      }catch(error){
        if(!current())return;
        if(confirmed){feedback('Decisión guardada. Falta actualizar la bandeja.','error');submit.disabled=true;}
        else if(error.status && error.status<500){observationPending.delete(key);feedback(`No se guardó. ${error.message}`,'error');submit.disabled=true;}
        else{feedback('No pudimos confirmar el guardado.','error');submit.textContent='Comprobar guardado';submit.disabled=false;}
      }finally{busy=false;}
    });
  }catch(error){if(current())content.textContent=error.message;}
}

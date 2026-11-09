/* B-UI2: explicit review actions, using versioned P05 and B02 writes. */
const sheetSelection = new Map();
let sheetSelectionVersion = null;
let sheetReviewEpoch = 0;
let sheetReviewVersion = null;
const declaredStateLabels={authorized:'Autorizada',rejected:'Rechazada',referred:'Derivada',pending:'Pendiente',unknown:'Sin precisar'};
function declaredState(value){return declaredStateLabels[value] || (value?`Sin interpretar (${value})`:'No informado');}

function initializeSheetActions() {
  document.querySelector('#sheet-review-close').addEventListener('click',closeSheetReview);
  document.querySelector('#sheet-review-panel').addEventListener('keydown',e=>{if(e.key==='Escape')closeSheetReview();});
  document.querySelector('#sheet-selection-clear').addEventListener('click',()=>{clearSheetSelection();if(practicePage)renderPracticeRows(practicePage.items);});
  document.querySelector('#sheet-preview-button').addEventListener('click',showSheetDecisionPreview);
}

function parkInlineReview(){
  const panel=document.querySelector('#sheet-review-panel'), host=panel.closest?.('tr.inline-review-row');
  if(!host)return null;
  document.querySelector('#sheet-review-home').after(panel);host.remove();
  return Number(host.dataset.forRow);
}
function mountInlineReview(number){
  const row=Array.from(document.querySelectorAll('#practice-rows tr[data-source-row]'))
    .find(r=>Number(r.dataset.sourceRow)===number);
  if(!row)return false;
  const host=document.createElement('tr'),td=document.createElement('td');
  host.className='inline-review-row';host.dataset.forRow=number;
  td.colSpan=document.querySelector('#board-show-amounts').checked?15:13;
  row.after(host);host.append(td);td.append(document.querySelector('#sheet-review-panel'));
  row.classList.add('review-selected');
  return true;
}
function closeSheetReview() {
  parkInlineReview();
  sheetReviewEpoch++;
  sheetReviewVersion=null;
  document.querySelector('#sheet-review-panel').hidden=true;
  document.querySelector('#sheet-review-panel').classList.remove('observation-panel','budget-panel');
  document.querySelector('#sheet-review-content').className='';
  for(const row of document.querySelectorAll('#practice-rows .review-selected'))row.classList.remove('review-selected');
  document.querySelector('#sheet-review-content').replaceChildren();
}

function clearSheetSelection() {
  sheetSelection.clear();sheetSelectionVersion=null;closeSheetReview();updateSheetSelectionCount();
  document.querySelector('#sheet-action-status').textContent='';
}

function updateSheetSelectionCount() {
  document.querySelector('#sheet-selection-bar').hidden=!sheetSelection.size;
  document.querySelector('#sheet-selection-count').textContent=`${sheetSelection.size} avisos elegidos expresamente (máximo 100)`;
}

function sheetVersion(page) {
  return `${selectedDataset?.id}:${document.querySelector('#invoice-batch').value}:${page.dataset_version}:${page.batch.revision_version}:${page.batch.latest_run_id}`;
}

function syncSheetSelection(page) {
  if((sheetSelectionVersion && sheetSelectionVersion!==sheetVersion(page)) || (sheetReviewVersion && sheetReviewVersion!==sheetVersion(page))) {
    clearSheetSelection();document.querySelector('#sheet-action-status').textContent='La revisión cambió. Se quitó la selección anterior; revisá nuevamente los avisos.';
  }
}

function selectSheetAlert(alert,checked) {
  if(!practicePage || practicePage.batch.revision_state==='cerrada')return;
  if(checked && !sheetSelection.has(alert.id) && sheetSelection.size>=100) {
    document.querySelector('#sheet-action-status').textContent='El límite es 100 avisos. Quitá alguno antes de agregar otro.';return;
  }
  closeSheetReview();
  if(checked){sheetSelection.set(alert.id,{id:alert.id,expected_version:alert.version});sheetSelectionVersion=sheetVersion(practicePage);}
  else {sheetSelection.delete(alert.id);if(!sheetSelection.size)sheetSelectionVersion=null;}
  updateSheetSelectionCount();
}

function renderSheetDecision(cell,item) {
  const alerts=item.alerts.filter(a=>a.current);
  if(!alerts.length || practicePage?.batch.revision_state==='cerrada')return;
  if(alerts.length===1) {
    const checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.checked=sheetSelection.has(alerts[0].id);
    checkbox.setAttribute('aria-label',`Elegir aviso ${alerts[0].rule_code} de ${item.locator}`);
    checkbox.title=`Elegir ${ruleNames[alerts[0].rule_code] || alerts[0].rule_code} de esta fila`;
    checkbox.addEventListener('change',()=>{selectSheetAlert(alerts[0],checkbox.checked);checkbox.checked=sheetSelection.has(alerts[0].id);});
    cell.prepend(checkbox);
  } else {
    cell.replaceChildren();const button=sheetButton(`Elegir ${alerts.length} avisos`,()=>showSheetAlertPicker(item));cell.append(button);
  }
}

function authorizationLabel(data) {
  if(!data)return 'Consultar';
  if(data.link_freshness==='requires_update')return 'Revisar vínculo';
  if(data.state==='outside_scope')return 'Fuera de alcance';
  if(data.state==='scope_missing')return 'Elegir fuentes';
  if(data.state==='requires_update')return 'Actualizar fuentes';
  if(data.resolution_states?.includes('apparent_conflict'))return 'Resoluciones diferentes';
  if(data.link_state==='selected')return 'Ítem elegido';
  if(data.link_state==='unresolved')return 'Sin resolver (revisado)';
  if(data.catalog_candidate_count>0 && !data.candidate_count)return `${data.catalog_candidate_count} candidatos por catálogo: revisar`;
  return {ambiguous:'Varias coincidencias',unambiguous_candidate:'Candidato a vincular',needs_review:'Datos por aclarar',
    incompatible_candidates:'Datos diferentes',no_authorization_located:'Sin coincidencia',identity_or_code_unresolved:'Identidad por aclarar',candidate_limit:'Demasiadas opciones'}[data.state] || 'Consultar';
}

function csvUnitsLabel(c) {
  if(c.unit_conversion?.billed_unit==='side')return c.covered_units+' de '+c.billed_units+' lados cubiertos';
  const covered=c.covered_units ?? 1;
  return covered+' de '+c.billed_units+(covered===1?' autorizada':' autorizadas');
}

function csvCoverageText(c) {
  const lines=[];
    const labels = {
      posterior_candidate:'Posible débito · verificar orden.',
      later_movement:'La orden registra un '+(c.movement || 'movimiento')+' posterior. Verificá si corresponde a esta prestación.',
      unidentified:'Afiliado no identificable · débito total propuesto.',
      referred_elsewhere:'Derivada a otro prestador.',
      referral_pending:'Verificar prestador de la derivación.',
      prior_not_found:'Débito total propuesto · aval anterior no localizado.',
      component_supported:'Adicional cubierto por el aval y la cantidad documentada del estudio principal.',
      component_pending:c.reason || 'Revisar las unidades del adicional y el aval de su estudio principal.',
      one_unit_supported:'Con aval CSV para una realización.',
      units_supported:csvUnitsLabel(c)+'.',
      units_partial:csvUnitsLabel(c)+'.',
      one_unit_only:csvUnitsLabel(c)+'.',
      no_aval:'Sin aval localizado en el CSV completo.',
      coverage_pending:'Pendiente de cotejo.',
      temporal_pending:'Pendiente de verificar la incorporación al consolidado.',
      temporal_late:'La autorización llegó después de la incorporación al consolidado.',
      already_used:'Sin otra unidad autorizada localizada. Revisar esta realización.',
      outside_window:'Sin resolución dentro de los 60 días previos. Revisar fechas.',
      declared_rejected:'El CSV declara rechazo individual para el ítem. Revisar la fila.',
      needs_review:'Correspondencia o cantidad ambigua. Revisar sin asignar aval.'
    };
    lines.push(c.reviewed?'Aval ya revisado. Sigue respaldando la prestación anterior.':labels[c.status] || 'Revisar aval de la realización.');
    if(c.order_id)lines.push('Orden '+c.order_id+'.');
    if(c.prior_order_id)lines.push('Orden anterior mencionada: '+c.prior_order_id+'.');
    if(c.candidate_budget_ars)lines.push('Monto autorizado de la orden: $'+boardMoney(c.candidate_budget_ars)+'.');
    if(c.coverage_note)lines.push(c.coverage_note);
    if(c.unit_conversion)lines.push(c.billed_units+' '+(c.unit_conversion.billed_unit==='side'?'lados':'unidades')+' facturados equivalen a '+c.normalized_studies+' estudio(s) según la correspondencia registrada.');
    if(c.parent_row)lines.push('Estudio principal en la fila '+c.parent_row+'.');
    if(c.authorization_date)lines.push('Resolución '+c.authorization_date+(c.performed_on?' · prestación '+c.performed_on:'')+(c.temporal?' · incorporación '+(c.temporal.incorporation?.value || c.temporal.incorporation?.original || 'sin fecha acreditada'):'')+'.');
    if(!c.temporal && Number.isInteger(c.elapsed_days) && c.elapsed_days>=0)lines.push('Vigencia: día '+c.elapsed_days+' de 60.');
    if(c.movement_actor)lines.push('Registrado por '+c.movement_actor+'.');
    for(const previous of c.previous_rows || [])lines.push('Aval localizado antes: '+previous.performed_on+' · fila '+previous.source_row+' · lote '+previous.batch_id);
  return lines;
}

function authorizationSignalText(signal) {
  if(!signal)return [];
  const presence={found:'✓ Práctica localizada (afiliado y código completo)',candidate:'? Posible práctica por catálogo: cotejar',not_located:'— Práctica no localizada en fuentes seleccionadas',incompatible:'! Coincidencia con fecha o prestador diferente',not_evaluated:'— Búsqueda sin determinar',outside_scope:'— Fuera de alcance'};
  const authorization={authorized:'✓ Autorizada según declaración individual de la fuente',rejected:'✗ Rechazada según declaración individual de la fuente',pending:'◷ Autorización pendiente según la fuente',referred:'↗ Derivada según la fuente',not_determinable:'? Autorización individual no determinable'};
  const lines=[presence[signal.presence] || presence.not_evaluated,authorization[signal.item_authorization] || authorization.not_determinable];
  if(signal.csv_item_declaration) {
    const declared = signal.csv_item_declaration === 'authorized' ? 'autorizada' : 'no autorizada';
    lines.splice(1, 0, 'Ítem en el CSV: ' + declared + ' según la fuente.');
    if(signal.item_authorization === 'not_determinable')lines[2]='Correspondencia con esta fila: pendiente de verificación.';
  }
  if(signal.csv_coverage) {
    const c=signal.csv_coverage;
    if(['one_unit_supported','units_supported','one_unit_only','units_partial'].includes(c.status)) {
      const pending=lines.findIndex(l=>l.startsWith('Correspondencia con esta fila:') || l.includes('Autorización individual no determinable'));
      if(pending>=0)lines.splice(pending,1);
    }
    lines.push(...csvCoverageText(c));
  }
  if(signal.order_history_states?.length)lines.push(`Historial de orden(es): ${signal.order_history_states.map(s=>({autorizado:'AUTORIZADO',rechazado:'RECHAZADO'}[s] || 'sin interpretar')).join(' / ')}. No determina la autorización de esta práctica.`);
  return lines;
}

function renderSheetAuthorization(cell,item) {
  for(const text of authorizationSignalText(item.authorization?.panel_signal)){const line=document.createElement('div');line.textContent=text;cell.append(line);}
  const button=sheetButton(`Ver CSV / A1: ${authorizationLabel(item.authorization)}`,()=>showSheetAuthorization(item.source_row));
  button.setAttribute('aria-label',`Consultar correspondencia A1 de ${item.locator}`);
  button.title='Fuente estructurada separada de los PDF. CSV / A1: práctica localizada y autorización individual son señales separadas. No localizada no significa rechazada. Sin decisiones ni débitos automáticos.';
  cell.append(button);
}

function sheetButton(text,handler) {
  const button=document.createElement('button');button.type='button';button.className='secondary';button.textContent=text;button.addEventListener('click',handler);return button;
}

function sheetPanel(title,number=null) {
  closePracticeDetail();closeSheetReview();
  sheetReviewVersion=practicePage?sheetVersion(practicePage):null;
  document.querySelector('#sheet-review-heading').textContent=title;
  if(number!=null)mountInlineReview(number);
  document.querySelector('#sheet-review-panel').hidden=false;
  return document.querySelector('#sheet-review-content');
}

function sheetContext() {
  return {datasetId:selectedDataset?.id,batchId:document.querySelector('#invoice-batch').value,epoch:sheetReviewEpoch};
}

function sheetCurrent(context) {
  return context.epoch===sheetReviewEpoch && selectedDataset?.id===context.datasetId && document.querySelector('#invoice-batch').value===context.batchId && currentRole!=='viewer';
}

function sheetField(form,label,kind='textarea') {
  const wrapper=document.createElement('label');wrapper.textContent=label;const input=document.createElement(kind);
  input.setAttribute('aria-label',label);
  if(kind==='textarea'){input.required=true;input.minLength=10;input.maxLength=4000;}
  wrapper.append(input);form.append(wrapper);return input;
}

function showSheetAlertPicker(item) {
  const content=sheetPanel(`Fila ${item.source_row} · elegir avisos`);
  detailText(content,'Selección','Cada aviso se elige por separado. Los controles o motivos distintos se deciden en grupos separados.');
  for(const alert of item.alerts.filter(a=>a.current)) {
    const label=document.createElement('label'),input=document.createElement('input');input.type='checkbox';input.checked=sheetSelection.has(alert.id);
    label.append(input,document.createTextNode(`${ruleNames[alert.rule_code]} · ${decisionLabels[alert.decision]}`));
    input.addEventListener('change',()=>{selectSheetAlert(alert,input.checked);showSheetAlertPicker(item);});content.append(label);
  }
}

async function refreshSheetAfterWrite(context,text) {
  if(!sheetCurrent(context))return;
  clearSheetSelection();
  document.querySelector('#sheet-action-status').textContent=text;
  try {await refreshAlerts();}
  catch(error){document.querySelector('#sheet-action-status').textContent=`${text} Falta actualizar la pantalla: ${error.message}`;}
}

async function showSheetDecisionPreview() {
  if(!sheetSelection.size || !practicePage || sheetSelectionVersion!==sheetVersion(practicePage))return;
  const content=sheetPanel('Revisar decisión · avisos seleccionados'),context=sheetContext();
  const versions={expected_dataset_version:practicePage.dataset_version,expected_revision_version:practicePage.batch.revision_version};
  const items=Array.from(sheetSelection.values()).map(i=>({...i}));
  content.textContent='Consultando los avisos y su evidencia…';
  try {
    const preview=await request(`/api/datasets/${context.datasetId}/batches/${context.batchId}/decision-preview`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...versions,items})});
    if(!sheetCurrent(context))return;
    content.replaceChildren();
    if(practicePage.batch.synthetic_data)detailText(content,'DATOS FICTICIOS','Estas decisiones forman parte de un ensayo. No validan autorizaciones ni habilitan importes reales.');
    detailText(content,'Casos',`${preview.count} avisos. Una decisión por aviso, con historia. No se calculan ni suman débitos.`);
    for(const item of preview.items) {
      const details=document.createElement('details'),summary=document.createElement('summary');
      summary.textContent=`${item.locator} · ${ruleNames[item.rule_code]} · ${item.reason_label} · actual: ${decisionLabels[item.decision]}`;
      details.append(summary);appendControlEvidence(details,item.evidence);content.append(details);
    }
    const form=document.createElement('form');form.className='sheet-action-form';
    const state=sheetField(form,'Decisión para estos avisos','select');state.required=true;
    for(const [value,label] of [['','Elegí una decisión'],['confirmada','Confirmar el aviso con evidencia'],['descartada','Descartar el aviso'],['no_concluyente','Dejar sin conclusión por falta de evidencia']])state.append(new Option(label,value));
    const foundation=sheetField(form,'Fundamento de la decisión');
    const evidence=sheetField(form,'Evidencia adicional para confirmar');evidence.required=false;
    state.addEventListener('change',()=>evidence.required=state.value==='confirmada');
    const acknowledge=document.createElement('label'),check=document.createElement('input');check.type='checkbox';check.required=true;
    acknowledge.append(check,document.createTextNode('Revisé estos casos y el fundamento corresponde a cada aviso seleccionado.'));form.append(acknowledge);
    const submit=document.createElement('button');submit.type='submit';submit.textContent=`Guardar ${preview.count} decisiones individuales`;
    const status=document.createElement('p');status.setAttribute('role','status');form.append(submit,status);content.append(form);
    let busy=false;
    form.addEventListener('submit',async event=>{
      event.preventDefault();if(busy || !sheetCurrent(context))return;busy=true;submit.disabled=true;
      try {
        await request(`/api/datasets/${context.datasetId}/batches/${context.batchId}/decisions`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...versions,items,preview_sha256:preview.preview_sha256,state:state.value,foundation:foundation.value,evidence_note:evidence.value || null})});
        await refreshSheetAfterWrite(context,`${preview.count} decisiones guardadas con historia. Importes sin modificar.`);
      } catch(error){if(sheetCurrent(context))status.textContent=`No se guardó esta acción: ${error.message}. Tu texto sigue aquí; actualizá la selección si cambió la revisión.`;}
      finally {busy=false;if(sheetCurrent(context))submit.disabled=false;}
    });
  } catch(error){if(sheetCurrent(context))content.textContent=`No se preparó la decisión: ${error.message}. No se guardó ningún cambio.`;}
}

function appendCsvReview(content,context,sourceRow,data){
  const signal=data.csv_coverage;
  const history=data.csv_review_history || [];
  if(history.length){
    const details=document.createElement('details'),label=document.createElement('summary');
    label.textContent='Historial de revisión del aval ('+history.length+')';details.append(label);
    for(const entry of history){
      detailText(details,entry.actor+' · '+entry.created_at,entry.note);
    }
    content.append(details);
  }
  if(signal?.status!=='already_used' || !signal.review_basis)return;
  if(signal.reviewed){
    detailText(content,'Aval revisado','La revisión quedó registrada para esta evidencia.');
    return;
  }
  const form=document.createElement('form');form.className='sheet-form';
  const reason=sheetField(form,'Motivo de la revisión del aval');reason.maxLength=2000;
  const save=document.createElement('button');save.type='submit';save.textContent='Marcar aval como revisado';
  const status=document.createElement('p');status.setAttribute('role','status');
  form.append(save,status);content.append(form);
  let body=null;
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(save.disabled || !sheetCurrent(context))return;
    body ??= {version:data.dataset_version,revision_id:data.revision_id,revision_version:data.revision_version,
      evidence_sha256:signal.review_basis,request_id:crypto.randomUUID(),note:reason.value};
    save.disabled=true;reason.disabled=true;status.textContent='Guardando revisión…';
    let confirmed=false;
    try{
      const saved=await request(`/api/datasets/${context.datasetId}/batches/${context.batchId}/rows/${sourceRow}/csv-coverage-review`,
        {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      confirmed=true;if(!sheetCurrent(context))return;
      status.textContent='Aval revisado. Actualizando la bandeja…';sheetReviewVersion=null;
      const list=await loadPracticeBoard({saved,savedRow:sourceRow});
      if(!sheetCurrent(context))return;
      const receipt=list?.saved_row_status;
      status.textContent='Aval revisado. '+(receipt?.source_row!==sourceRow?'Consultá la bandeja actualizada.':
        receipt.in_exceptions?'La prestación sigue en Excepciones: '+receipt.pending.join(' · ')+'.':'La prestación salió de Excepciones.');
    }catch(error){
      if(!sheetCurrent(context))return;
      if(confirmed){status.textContent='Aval revisado. Falta actualizar la bandeja.';return;}
      if(error.status && error.status<500){
        status.textContent=error.message;
        if(error.status===422){body=null;reason.disabled=false;save.disabled=false;}
      }else{
        status.textContent='Guardado sin confirmar. Podés comprobar el mismo envío.';
        save.textContent='Comprobar guardado';save.disabled=false;
      }
    }
  });
}

async function showSheetAuthorization(sourceRow) {
  if(!practicePage)return;
  const content=sheetPanel(`Fila ${sourceRow} · autorizaciones`),context=sheetContext();content.textContent='Buscando correspondencias en las fuentes seleccionadas…';
  try {
    const data=await request(`/api/datasets/${context.datasetId}/batches/${context.batchId}/rows/${sourceRow}/authorization-correspondence`);
    if(!sheetCurrent(context))return;
    if(data.dataset_version!==practicePage?.dataset_version || data.revision_version!==practicePage?.batch.revision_version){content.textContent='La revisión cambió. Actualizá la planilla y abrí nuevamente esta fila.';return;}
    content.replaceChildren();
    detailText(content,'Origen',data.mode==='synthetic_demo'?'DATOS FICTICIOS':data.mode?'Fuente real sin validar':'Sin fuente seleccionada');
    detailText(content,'Correspondencia',authorizationLabel({state:data.state}));
    detailText(content,'Límite','Vincular un ítem no aprueba su autorización. «Comprobar cantidades y fechas» consulta lo declarado sin guardar controles ni importes. Sin coincidencia no significa rechazo.');
    if(data.csv_coverage) {
      detailText(content,'Cotejo CSV a 60 días',csvCoverageText(data.csv_coverage).join(' '));
    }
    appendCsvReview(content,context,sourceRow,data);
    detailText(content,'Cobertura de la fuente','Sin verificar. Los casos no encontrados no prueban ausencia de autorización.');
    content.append(sheetButton('Administrar fuentes de autorizaciones',()=>{closeSheetReview();activateWorkspaceView('autorizaciones');}));
    const selector=document.createElement('select');selector.required=true;selector.setAttribute('aria-label','Ítem a vincular');selector.append(new Option('Elegí un candidato compatible',''));
    for(const candidate of data.candidates) {
      const details=document.createElement('details'),summary=document.createElement('summary');
      const resolution={apparent_conflict:'resoluciones diferentes: revisar',declared_authorized:'autorización declarada',declared_rejected:'rechazo declarado',declared_pending:'pendiente declarado',declared_referred:'derivación declarada'}[candidate.resolution.state] || 'resolución por aclarar';
      summary.textContent=`${candidate.order_id || 'Orden sin ID'} / ${candidate.item.item_id || 'Ítem sin ID'} · ${candidate.compatibility==='compatible'?'Datos compatibles':candidate.compatibility==='incompatible'?'Datos diferentes':'Datos por aclarar'} · ${resolution}`;
      details.append(summary);
      detailText(details,'Práctica',`${candidate.item.full_code} · ${candidate.item.description || 'Sin descripción'} · ${candidate.item.service_date || 'Sin fecha'}`);
      detailText(details,'Cantidad solicitada',`${candidate.item.requested_quantity ?? 'Desconocida'} ${candidate.item.unit || '(unidad sin informar)'}`);
      if(candidate.csv_order_history?.length)detailText(details,'Historial CSV de la orden',`${candidate.csv_order_history.join(' / ')}. No determina autorización individual ni estado actual.`);
      detailText(details,'Estado global declarado',`${declaredState(candidate.resolution.global_status_declared)}. No aprueba por sí solo todos los ítems.`);
      for(const [key,label] of Object.entries({identity:'Afiliado',complete_code:'Código completo',provider:'Prestador HPC',date:'Fecha',description:'Descripción',unique_ids:'IDs de orden e ítem'}))detailText(details,label,candidate.checks[key]===true?'Coincide':candidate.checks[key]===false?'Diferente o no unívoco':'No informado');
      detailText(details,'Original',`${candidate.locator} · SHA-256 ${candidate.source_sha256} · captura v${candidate.capture_ordinal}`);
      authorizationTable(details,`Resoluciones declaradas · ${candidate.resolution.records.length} de ${candidate.resolution.records_total}`, [['ID','resolution_id'],['Alcance','scope_display'],['Ítems','item_ids'],['Estado declarado','status_display'],['Cantidad declarada','authorized_quantity'],['Unidad','unit'],['Fecha','decided_at'],['Reemplaza','supersedes_resolution_id'],['Motivo','reason'],['Afecta este ítem','affects']],candidate.resolution.records.map(r=>({...r,status_display:declaredState(r.status),scope_display:{item:'Por ítem',explicit_general:'General explícita'}[r.scope] || 'Alcance por aclarar',affects:r.targets_item===true?'Sí':r.targets_item===false?'No':'Sin determinar'})));
      if(candidate.resolution.records_truncated || candidate.resolution.records.some(r=>r.reason_truncated || r.item_ids_truncated))detailText(details,'Vista parcial','Hay textos, ítems o resoluciones truncados: consultar el original completo antes de interpretar.');
      content.append(details);
      if(candidate.compatibility==='compatible')selector.append(new Option(`${candidate.order_id}/${candidate.item.item_id} · ${candidate.locator}`,candidate.key));
    }
    if(data.catalog_relationships) {
      const related=data.catalog_relationships;
      detailText(content,'Candidatos por catálogo',`${related.candidates.length} mostrados de ${related.candidate_count_total}. ${related.use_limit}`);
      for(const candidate of related.candidates) {
        const details=document.createElement('details'),summary=document.createElement('summary');
        summary.textContent=`${candidate.order_id || 'Orden sin ID'} · ${candidate.relation.invoice_code} → ${candidate.item.full_code} · ${candidate.compatibility==='incompatible'?'Fecha o prestador incompatible':'Revisar enlace declarado'}`;details.append(summary);
        if(candidate.csv_order_history?.length)detailText(details,'Historial CSV de la orden',`${candidate.csv_order_history.join(' / ')}. No determina autorización individual ni estado actual.`);
        detailText(details,'Tipo de enlace',candidate.relation.category_is_broad?'Categoría amplia del nomenclador: varias prácticas posibles; NO equivalencia.':candidate.relation.basis==='explicit_neutral_category_to_hpc'?'Enlace del nomenclador a HPC; equivalencia por verificar.':'Enlace entre códigos HPC; equivalencia por verificar.');
        detailText(details,'Práctica',`${candidate.item.full_code} · ${candidate.item.description || 'Sin descripción'} · ${candidate.item.service_date || 'Sin fecha de prestación'}`);
        detailText(details,'Evidencia',`${candidate.relation.practice_id} · filas de códigos ${candidate.relation.invoice_code_seqs.join(', ')} → ${candidate.relation.authorization_code_seqs.join(', ')} · SHA-256 catálogo ${candidate.relation.source_sha256}`);
        detailText(details,'Original',`${candidate.locator} · SHA-256 ${candidate.source_sha256}`);
        detailText(details,'Límite','No seleccionable como correspondencia exacta. No acredita autorización individual, cantidad ni débito.');content.append(details);
      }
    }
    detailText(content,'Candidatos',`${data.candidates.length} mostrados de ${data.candidate_count_total ?? 0}.`);
    content.append(sheetButton('Comprobar cantidades y fechas',()=>showAuthorizationChecks(sourceRow)));
    if(data.human_link.current)detailText(content,'Último vínculo',`${data.human_link.current.state==='selected'?'Ítem elegido':'Sin resolver'} · ${data.human_link.current.freshness==='current'?'sin cambios pendientes':'requiere revisar'} · v${data.human_link.current.ordinal}`);
    const history=document.createElement('details'),title=document.createElement('summary');title.textContent=`Historia del vínculo · ${data.human_link.history.length} versiones`;history.append(title);
    for(const entry of data.human_link.history)detailText(history,`v${entry.ordinal} · ${entry.actor_username} · ${entry.created_at}`,`${entry.state==='selected'?'Seleccionado':'Sin resolver'}: ${entry.note}`);content.append(history);
    if(data.disposition!=='included' || data.issues.length || practicePage.batch.revision_state==='cerrada') {detailText(content,'Guardado no disponible','Fila fuera de alcance, fuentes sin seleccionar/por actualizar o revisión cerrada.');return;}
    const form=document.createElement('form');form.className='sheet-action-form';
    const state=sheetField(form,'Qué registrar sobre el vínculo','select');state.required=true;
    state.append(new Option('Elegí una acción',''),new Option('Elegir un ítem compatible con evidencia','selected'),new Option('Dejar sin resolver / retirar la selección anterior','unresolved'));
    const wrapper=document.createElement('label');wrapper.textContent='Ítem a vincular';wrapper.append(selector);form.append(wrapper);
    state.addEventListener('change',()=>selector.required=state.value==='selected');
    const note=sheetField(form,'Evidencia y fundamento del vínculo');note.maxLength=2000;
    const submit=document.createElement('button');submit.type='submit';submit.textContent='Guardar versión del vínculo';const status=document.createElement('p');status.setAttribute('role','status');form.append(submit,status);content.append(form);
    let busy=false;
    form.addEventListener('submit',async event=>{
      event.preventDefault();if(busy || !sheetCurrent(context))return;busy=true;submit.disabled=true;
      try {
        await request(`/api/datasets/${context.datasetId}/batches/${context.batchId}/rows/${sourceRow}/authorization-link`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_version:data.dataset_version,expected_revision_version:data.revision_version,basis_sha256:data.basis_sha256,state:state.value,candidate_key:state.value==='selected'?selector.value:null,note:note.value})});
        await refreshSheetAfterWrite(context,'Vínculo guardado con historia. Autorización sin aprobar; no se ejecutó análisis.');
      } catch(error){if(sheetCurrent(context))status.textContent=`No se guardó el vínculo: ${error.message}. Tu fundamento sigue aquí.`;}
      finally {busy=false;if(sheetCurrent(context))submit.disabled=false;}
    });
  } catch(error){if(sheetCurrent(context))content.textContent=`No se pudo consultar: ${error.message}`;}
}

/* For writes without an idempotency contract, an unknown result is read back,
   never resubmitted by this form. A failed GET cannot undo a confirmed POST. */
async function settleSheetWrite({context,state,button,status,content,send,refreshView,readHistory}) {
  if(state.busy || state.locked || !sheetCurrent(context))return;
  const controls=[...content.querySelectorAll('input,select,textarea,button')];
  const disabled=controls.map(control=>control.disabled);
  state.busy=true;for(const control of controls)control.disabled=true;button.disabled=true;
  try {
    let saved;
    try {saved=await send();}
    catch(error) {
      if(error.status && error.status<500){
        if(sheetCurrent(context)){
          if(error.status===401 || error.status===403){state.locked=true;content.replaceChildren();content.textContent='Acceso revocado o sesión vencida.';}
          else status.textContent=`No se guardó: ${error.message}. El texto se conserva; actualizá la vista si cambió la revisión.`;
        }
        return;
      }
      state.locked=true;
      if(!sheetCurrent(context))return;
      status.textContent='Resultado incierto del guardado. Conservá el texto y comprobá el historial; no se reenviará esta operación.';
      const check=document.createElement('button');check.type='button';check.textContent='Comprobar historial sin reenviar';
      const evidence=document.createElement('div');content.append(check,evidence);
      check.addEventListener('click',async()=>{
        if(state.reading || !sheetCurrent(context))return;state.reading=true;check.disabled=true;
        try {
          const history=await readHistory();if(!sheetCurrent(context))return;
          evidence.replaceChildren();
          detailText(evidence,'Historial consultado','Compará IDs, autoría, fecha, cálculo y fundamento con tu borrador. La lectura no atribuye automáticamente un registro a esta petición ni crea otra operación.');
          for(const entry of history)detailText(evidence,`Registro ${entry.id}`,entry.description);
          if(!history.length)detailText(evidence,'Sin registros','No demuestra rechazo: la petición podría seguir en curso. Volvé a comprobar antes de iniciar otra acción.');
        } catch(error){
          if(!sheetCurrent(context))return;
          if(error.status===401 || error.status===403){content.replaceChildren();content.textContent='Acceso revocado o sesión vencida.';}
          else status.textContent=`Resultado incierto. No se pudo consultar el historial: ${error.message}. No se reenvió la operación.`;
        } finally {state.reading=false;if(sheetCurrent(context))check.disabled=false;}
      });
      return;
    }
    state.locked=true;
    if(!sheetCurrent(context))return;
    status.textContent=`Guardado confirmado${saved?.id?' · ID '+saved.id:''}. Actualizando la pantalla…`;
    try {await refreshView();}
    catch(error){if(sheetCurrent(context)){
      if(error.status===401 || error.status===403){content.replaceChildren();content.textContent='Guardado confirmado. Sesión vencida o acceso revocado; se retiró la evidencia de la pantalla.';}
      else status.textContent=`Guardado confirmado${saved?.id?' · ID '+saved.id:''}. Falta actualizar la pantalla: ${error.message}. No vuelvas a enviar este formulario.`;
    }}
  } finally {state.busy=false;if(sheetCurrent(context)){if(!state.locked)controls.forEach((control,i)=>control.disabled=disabled[i]);button.disabled=Boolean(state.locked);}}
}

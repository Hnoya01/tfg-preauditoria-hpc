/* B-UI1: navigation and read-only practice workbench. Writes remain in existing flows. */
let activeWorkspaceView = 'inicio';
let practicePage = null;
let practiceOffset = 0;
let practiceContextKey = null;
let sheetExpansionContext = null;
let practiceRequest = 0;
let practiceDetailRequest = 0;
let practiceFocusedRow = null;
const workspaceViews = {solicitudes:'#requests-home',inicio:'#invoice-home',facturacion:'#invoice-panel', autorizaciones:'#authorization-panel', valores:'#source-panel', procesamiento:'#controls-panel', revision:'#review-workbench', salida:'#export-panel'};
const controlLabels = {requires_update:'Requiere actualización', con_indicios:'Con indicios', no_concluyente:'No concluyente', no_evaluado:'No evaluado', sin_indicios:'Sin indicios', sin_observaciones:'Sin indicios', no_aplicable:'No aplicable', outside_scope:'Fuera de alcance', scope_indeterminate:'Ámbito indeterminado'};
const decisionLabels = {pendiente:'Pendiente', confirmada:'Confirmada', descartada:'Descartada', no_concluyente:'No concluyente', mixta:'Decisiones distintas', sin_indicios_vigentes:'Sin indicios vigentes para decidir'};
const ruleNames={RN09:'Autorización de la práctica',RN10:'Incorporación al consolidado',RN11:'Cantidad autorizada',RN12:'Importes de fila',RN13:'Honorarios + derechos = total',RN14:'Valor del convenio',RN15:'Referencia arancelaria',RN16:'Importes cero',RN17:'Posible facturación repetida',RN18:'Órdenes válidas',RN19:'Plazo de facturación'};
const simpleResults={con_indicios:'Revisar diferencia',sin_observaciones:'Sin diferencia detectada',sin_indicios:'Sin diferencia detectada',no_concluyente:'Falta información para comprobarlo',no_evaluado:'Control sin ejecutar',no_aplicable:'Este control no corresponde'};
const exclusionNames={internacion_fuera_de_alcance:'Internación',fuera_del_periodo:'Fecha fuera del período admitido',tipo_no_reconocido:'Tipo por aclarar',fecha_no_interpretable:'Fecha por aclarar'};

const queuePresets = {
  exceptions: ['exceptions','all'], images: ['exceptions','images'],
  row_reviewed: ['row_reviewed','images'], candidates: ['all','image_candidates'], referred: ['referred','images'], all: ['all','all']
};

function setQueuePreset(name) {
  const sort=document.querySelector('#board-sort'), direction=document.querySelector('#board-direction');
  const order=sort.value, dir=direction.value;
  document.querySelector('#board-filters').reset();
  sort.value=order;direction.value=dir;
  document.querySelector('#board-view').value=queuePresets[name][0];
  document.querySelector('#board-scope').value=name==='all'?'all':'included';
  document.querySelector('#board-family').value=queuePresets[name][1];
  practiceOffset=0;
}

function initializeWorkbench() {
  initInvoiceHome();
  if(typeof initializeHandoff==="function")initializeHandoff();
  document.querySelector('#practice-requests').addEventListener('click',showPracticeRequests);
  for(const button of document.querySelectorAll('[data-queue]'))button.addEventListener('click',()=>{
    clearSheetSelection();closePracticeDetail();setQueuePreset(button.dataset.queue);loadPracticeBoard();
  });
  if(typeof initializeObservationWorkflow==='function')initializeObservationWorkflow();
  if(typeof initializeSheetActions==='function')initializeSheetActions();
  const auth = document.querySelector('#authorization-panel');
  document.querySelector('#workspace-panel').insertBefore(auth, document.querySelector('#intake-ready'));
  for (let n=9;n<=19;n++) {
    const option=document.createElement('option'); option.value=`RN${String(n).padStart(2,'0')}`; option.textContent=`${ruleNames[option.value]} (${option.value})`;
    document.querySelector('#board-rule').append(option);
  }
  for (const button of document.querySelectorAll('[data-workspace-view]')) button.addEventListener('click',()=>activateWorkspaceView(button.dataset.workspaceView));
  document.querySelector('#board-filters').addEventListener('submit',event=>{event.preventDefault();document.querySelector('#board-more-filters').open=false; if(typeof clearSheetSelection==='function')clearSheetSelection();practiceOffset=0; closePracticeDetail(); loadPracticeBoard();});
  document.querySelector('#board-reset').addEventListener('click',()=>{setQueuePreset('images'); if(typeof clearSheetSelection==='function')clearSheetSelection();practiceOffset=0; closePracticeDetail(); loadPracticeBoard();});
  document.querySelector('#board-refresh').addEventListener('click',()=>loadPracticeBoard());
  const incor=sheetButton('Registrar incorporación',()=>openIncorporationGroup());
  incor.id='incorporation-group';
  document.querySelector('#board-source-info')?.append(incor);
  document.querySelector('#board-expand').addEventListener('click',()=>setSheetExpanded(document.querySelector('#board-expand').getAttribute('aria-pressed')!=='true'));
  document.querySelector('#board-family').addEventListener('change',()=>{if(typeof clearSheetSelection==='function')clearSheetSelection();practiceOffset=0;closePracticeDetail();loadPracticeBoard();});
  for(const id of ['board-report-document-state','board-authorization-document-state','board-reference-comparison-state','board-csv-review-state']) document.querySelector(`#${id}`).addEventListener('change',()=>{if(typeof clearSheetSelection==='function')clearSheetSelection();practiceOffset=0;closePracticeDetail();loadPracticeBoard();});
  document.querySelector('#board-show-amounts').addEventListener('change',event=>{
    document.querySelector('#practice-table').classList.toggle('show-amounts',event.target.checked);
    for(const cell of document.querySelectorAll('#practice-rows th[colspan], #practice-rows td[colspan]'))cell.colSpan=event.target.checked?15:13;
    document.querySelector('#amounts-group').colSpan=event.target.checked?7:5;
    configureBoardColumns(event.target.checked);
  });
  document.querySelector('#board-previous').addEventListener('click',()=>{practiceOffset=Math.max(0,practiceOffset-50);closeSheetReview();closePracticeDetail();loadPracticeBoard();});
  document.querySelector('#board-next').addEventListener('click',()=>{practiceOffset+=50;closeSheetReview();closePracticeDetail();loadPracticeBoard();});
  document.querySelector('#board-scope').addEventListener('change',()=>{
    if(typeof clearSheetSelection==='function')clearSheetSelection();
    for(const id of ['board-view','board-state','board-reason','board-decision']) document.querySelector(`#${id}`).selectedIndex=0;
    for(const option of document.querySelector('#board-rule').options)option.selected=false;
    document.querySelector('#board-rules-match').value='any';
    practiceOffset=0; closePracticeDetail(); loadPracticeBoard();
  });
  document.querySelector('#practice-detail-close').addEventListener('click',closePracticeDetail);
  document.querySelector('#practice-detail-panel').addEventListener('keydown',event=>{if(event.key==='Escape')closePracticeDetail();});
  for(const id of ['invoice-dataset','invoice-batch']) document.querySelector(`#${id}`).addEventListener('change',()=>{
    practiceRequest++;practicePage=null;practiceContextKey=null;practiceOffset=0;
    if(typeof clearSheetSelection==='function')clearSheetSelection();
    setBoardControlsDisabled(true);
    if(typeof parkInlineReview==='function')parkInlineReview();
    document.querySelector('#practice-rows').replaceChildren();closePracticeDetail();
    document.querySelector('#board-count').textContent='Actualizando contexto…';
    document.querySelector('#workspace-context-summary').textContent='Actualizando el lote seleccionado…';
  });
}

function setSheetExpanded(expanded){
  document.body.classList.toggle('sheet-expanded',expanded);
  const button=document.querySelector('#board-expand');
  button.textContent=expanded?'Mostrar menú':'Ampliar planilla';
  button.setAttribute('aria-pressed',String(expanded));
  const caption=document.querySelector('#sheet-focus-context');caption.hidden=!expanded;
  caption.textContent=(document.querySelector('#invoice-batch').selectedOptions?.[0]?.textContent || 'Factura seleccionada')+
    ' · '+(document.querySelector('#identity').textContent || 'Revisión');
}

function setBoardControlsDisabled(disabled) {
  document.querySelector('#practice-table').inert=disabled;
  document.querySelector('#practice-table').setAttribute('aria-busy',String(disabled));
  for(const control of document.querySelectorAll('#board-filters input, #board-filters select, #board-filters button'))control.disabled=disabled;
  document.querySelector('#board-refresh').disabled=disabled;
  if(disabled) {
    document.querySelector('#board-previous').disabled=true;
    document.querySelector('#board-next').disabled=true;
  }
}

function syncWorkspaceNavigation() {
  if(activeWorkspaceView!=='revision' && document.body.classList.contains('sheet-expanded'))setSheetExpanded(false);
  const operator=Boolean(selectedDataset && currentRole && currentRole!=='viewer');
  if((!operator || activeWorkspaceView!=='revision') && typeof clearSheetSelection==='function')clearSheetSelection();
  document.querySelector('#workspace-context').hidden=!operator;
  document.querySelector('#workspace-nav').hidden=!operator;
  document.querySelector('#dataset-management').hidden=currentRole!=='admin';
  const auditOutput=document.querySelector('#audit-output');
  if(auditOutput){
    const auditFlow=document.querySelector('#invoice-batch').selectedOptions?.[0]?.dataset?.auditWorkflow==='1';
    const pdf=document.querySelector('#image-pdf-download');
    if(pdf && selectedDataset && document.querySelector('#invoice-batch').value)pdf.href='/api/datasets/'+selectedDataset.id+'/batches/'+document.querySelector('#invoice-batch').value+'/observations.pdf';
    auditOutput.hidden=!auditFlow;document.querySelector('#traditional-output').hidden=auditFlow;
  }
  for(const [view,selector] of Object.entries(workspaceViews)) document.querySelector(selector).hidden=!operator || activeWorkspaceView!==view;
  document.querySelector('#intake-ready').hidden=!operator || activeWorkspaceView!=='facturacion';
  if(operator && activeWorkspaceView==='facturacion')document.querySelector('#authorization-panel').hidden=false;
  document.body.classList.toggle('combined-intake',operator && activeWorkspaceView==='facturacion');
  for(const button of document.querySelectorAll('[data-workspace-view]')) {
    button.setAttribute('aria-current',button.dataset.workspaceView===activeWorkspaceView?'page':'false');
  }
}

async function activateWorkspaceView(view) {
  if(!workspaceViews[view])return;
  activeWorkspaceView=view;syncWorkspaceNavigation();
  if(view==='revision')await refreshWorkbench();
  else if(view==='solicitudes')await showPracticeRequests(true);
  else if(view==='facturacion' || view==='autorizaciones' || view==='valores')await refreshSources();
  else if(view==='procesamiento')await refreshRuns();
}

async function refreshWorkbench() {
  syncWorkspaceNavigation();
  const batchId=document.querySelector('#invoice-batch').value;
  const key=`${selectedDataset?.id || ''}:${batchId}`;
  if(key!==practiceContextKey) {
    practiceContextKey=key;practiceOffset=0;practicePage=null;practiceRequest++;
    setQueuePreset('images');
    syncWorkspaceNavigation();
    document.querySelector('#board-reason').replaceChildren(new Option('Todos los motivos',''));
    if(typeof parkInlineReview==='function')parkInlineReview();
    document.querySelector('#practice-rows').replaceChildren();closePracticeDetail();
    if(typeof clearSheetSelection==='function')clearSheetSelection();
  }
  const batchLabel=document.querySelector('#invoice-batch').selectedOptions[0]?.textContent;
  document.querySelector('#workspace-context-summary').textContent=batchLabel?`${batchLabel} · ${selectedDataset.label}`:'Sin lote seleccionado. Importá el Excel desde Facturación.';
  if(activeWorkspaceView==='revision')await loadPracticeBoard();
}

function practiceFilters() {
  const result={offset:practiceOffset,limit:50};
  const selectedReason=document.querySelector('#board-exception-reason').value;
  if(selectedReason && document.querySelector('#board-view').value==='exceptions')result.exception_reason=selectedReason;
  const ids={scope:'scope',family:'family',report_document_state:'report-document-state',authorization_document_state:'authorization-document-state',reference_comparison_state:'reference-comparison-state',csv_review_state:'csv-review-state',search:'search',view:'view',state:'state',reason:'reason',decision:'decision',code:'code',text:'text',date_from:'date-from',date_to:'date-to',sort:'sort',direction:'direction'};
  for(const [key,id] of Object.entries(ids)) {
    const value=document.querySelector(`#board-${id}`).value;
    if(value!=='')result[key]=value;
  }
  result.rules=Array.from(document.querySelector('#board-rule').selectedOptions || []).map(option=>option.value).filter(Boolean);
  result.rules_match=document.querySelector('#board-rules-match').value || 'any';
  return result;
}

async function loadPracticeBoard({afterRow=null, saved=null, savedRow=null}={}) {
  const datasetId=selectedDataset?.id,batchId=document.querySelector('#invoice-batch').value;
  const status=document.querySelector('#board-count');
  document.querySelector('#category-feedback').hidden=true;
  const notices=document.querySelector('#invoice-source-notices');
  notices.hidden=true;
  const requestId=++practiceRequest;
  if(typeof resetHandoff==="function")resetHandoff();
  setBoardControlsDisabled(true);
  if(!datasetId || !batchId || currentRole==='viewer') {
    if(typeof parkInlineReview==='function')parkInlineReview();
    document.querySelector('#practice-rows').replaceChildren();
    status.textContent='Elegí un conjunto y un lote importado. La bandeja incluye todas sus prácticas elegibles.';
    document.querySelector('#board-previous').disabled=true;document.querySelector('#board-next').disabled=true;
    return;
  }
  status.textContent='Consultando el lote completo y sus filtros…';
  document.querySelector('#board-refresh').disabled=true;
  try {
    const page=await request(`/api/datasets/${datasetId}/batches/${batchId}/practice-search`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...practiceFilters(),...(afterRow===null?{}:{after_source_row:afterRow}),...(savedRow===null?{}:{saved_source_row:savedRow})})});
    if(requestId!==practiceRequest || selectedDataset?.id!==datasetId || document.querySelector('#invoice-batch').value!==batchId)return;
    const versionChanged=practicePage && (practicePage.dataset_version!==page.dataset_version || practicePage.batch.revision_version!==page.batch.revision_version);
    const ownSave=saved && practicePage && saved.dataset_version===page.dataset_version &&
      saved.revision_version===page.batch.revision_version && page.dataset_version===practicePage.dataset_version+1 &&
      page.batch.revision_version===practicePage.batch.revision_version+1;
    if(versionChanged && !ownSave) {
      closePracticeDetail();
      if(typeof clearSheetSelection==='function')clearSheetSelection();
      if(page.offset>0 || afterRow!==null) {
        practiceOffset=0;practicePage=page;
        message.textContent='La factura o su revisión cambió durante la paginación. Volvimos a la primera página para evitar saltar prestaciones; revisá nuevamente el recorrido del filtro.';
        await loadPracticeBoard();return;
      }
    }
    practiceOffset=page.offset;practicePage=page;selectedDataset.version=page.dataset_version;
    const expansionContext=datasetId+':'+batchId;
    if(sheetExpansionContext!==expansionContext){
      sheetExpansionContext=expansionContext;
      setSheetExpanded(page.scope_total>page.limit);
    }
    if(typeof syncSheetSelection==='function')syncSheetSelection(page);
    if(page.offset && page.offset>=page.filtered_total) {practiceOffset=page.filtered_total?Math.floor((page.filtered_total-1)/50)*50:0;return loadPracticeBoard({saved,savedRow,afterRow});}
    const compact=page.filters.view==='exceptions' || page.filters.view==='referred';
    document.querySelector('#practice-table').dataset.compact=String(compact);
    notices.textContent=(page.source_notices || []).join(' ');
    if(page.batch.run_freshness==='not_analyzed' && page.batch.revision_state!=='cerrada'){
      notices.append(document.createTextNode(' Falta analizar la factura. '),sheetButton('Ir a procesamiento',()=>activateWorkspaceView('procesamiento')));
    }
    notices.hidden=!notices.textContent;
    document.querySelector('#practice-requests').textContent=page.pending_requests?
      'Solicitudes de alta · '+page.pending_requests+' pendientes':'Solicitudes de alta';
    const chips=document.querySelector('#exception-reasons');chips.replaceChildren();
    chips.hidden=page.filters.view!=='exceptions';
    const reasonInput=document.querySelector('#board-exception-reason');
    const available={...(page.exception_counts || {})};
    if(reasonInput.value && !Object.hasOwn(available,reasonInput.value))available[reasonInput.value]=0;
    for(const [label,count] of Object.entries(available)){
      const button=document.createElement('button');button.type='button';button.className='secondary';
      button.textContent=label+' · '+count;button.setAttribute('aria-pressed',String(reasonInput.value===label));
      button.addEventListener('click',()=>{clearSheetSelection();closePracticeDetail();reasonInput.value=reasonInput.value===label?'':label;practiceOffset=0;loadPracticeBoard();});
      chips.append(button);
    }
    const counts=page.scope_counts;
    const familyName={image_candidates:'posibles imágenes por revisar',images_and_candidates:'imágenes y posibles imágenes por revisar (sin reclasificar)',images:'imágenes identificadas por código o nombre de catálogo',other:'otras áreas del catálogo',unclassified:'prácticas sin clasificar',all:'prácticas'}[page.filters.family || 'all'];
    status.textContent=`${page.filtered_total.toLocaleString('es-AR')} ${familyName} · filas ${page.items.length?page.offset+1:0}–${page.offset+page.items.length}`;
    if(page.filters.view==='exceptions'){
      status.textContent=page.filtered_total ? 'Excepciones · '+status.textContent :
        (page.batch.run_freshness==='not_analyzed'?'Sin excepciones detectadas todavía. Falta analizar el lote en Procesamiento.':'Sin excepciones en esta selección. Podés consultar todas las prácticas y su cobertura.');
      if(!page.filtered_total && page.filters.family==='images' && !page.family_counts?.images && page.family_counts?.unclassified){
        status.textContent='Todavía no se identificaron prestaciones de Imágenes. Revisá las categorías en Ver factura completa.';
      }
    }
    for(const b of document.querySelectorAll('[data-queue]')){
      const [view,family]=queuePresets[b.dataset.queue];
      if(page.row_decision_counts && page.filters.family==='images' && ['row_reviewed','exceptions'].includes(page.filters.view)){
        if(b.dataset.queue==='images')b.textContent='Pendientes · '+page.row_decision_counts.pending;
        if(b.dataset.queue==='row_reviewed')b.textContent='Revisadas · '+page.row_decision_counts.reviewed;
      }else if(b.dataset.queue==='images' || b.dataset.queue==='row_reviewed'){
        b.textContent=b.dataset.queue==='images'?'Pendientes · Imágenes':'Revisadas · Imágenes';
      }
      b.setAttribute('aria-pressed',String(view===(page.filters.view||'all') && family===(page.filters.family||'all')));
    }
    status.title=`${page.physical_total} filas originales; ${counts.included} para revisión administrativa; ${counts.excluded} excluidas; ${counts.indeterminate} con alcance por aclarar.`;
    const classification=page.classification;
    document.querySelector('#board-classification').textContent=classification?.available
      ?`${page.family_counts.unclassified.toLocaleString('es-AR')} filas sin clasificar · ${(page.image_candidate_count || 0).toLocaleString('es-AR')} posibles imágenes por revisar: disponibles en «Imágenes + posibles imágenes» · ${[...new Set(classification.sources.map(s=>s.cut_label || 'Corte no declarado'))].join(', ')}`
      :classification?.source_unavailable?'No se pudo verificar el catálogo HPC: clasificación pendiente':'Sin clasificación: falta un catálogo HPC utilizable';
    document.querySelector('#board-classification').title='Imágenes usa códigos completos de orden HPC, códigos exactos de nomencladores neutrales o nombres exactos del catálogo (normalizando acentos y espacios; conservando signos). No infiere por prefijos ni palabras sueltas. Conflictos y no encontrados quedan sin clasificar. La clasificación no acredita identidad, autorización ni valor.';
    document.querySelector('#workspace-context-summary').textContent=`${page.batch.synthetic_data?'FICTICIO · ':''}${page.batch.period} · ${{not_analyzed:'Sin analizar',current:'Controles sin cambios pendientes',requires_update:'Hay controles por repetir'}[page.batch.run_freshness] || 'Consultar Procesamiento'}`;
    document.querySelector('#board-page').textContent=page.filtered_total?`Página ${Math.floor(page.offset/50)+1} de ${Math.ceil(page.filtered_total/50)}`:'Sin resultados';
    document.querySelector('#board-previous').disabled=page.offset===0;
    document.querySelector('#board-next').disabled=page.offset+page.items.length>=page.filtered_total;
    const reasons=document.querySelector('#board-reason'),selected=reasons.value;
    reasons.replaceChildren(new Option('Todos los motivos',''));
    const seen=new Set();
    for(const facet of page.facets) if(!seen.has(facet.reason)) {seen.add(facet.reason);reasons.append(new Option(facet.label,facet.reason));}
    if(seen.has(selected))reasons.value=selected;
    renderPracticeRows(page.items);
    if(typeof refreshHandoff==="function")refreshHandoff(page,requestId);
    return page;
  } catch(error) {
    if(requestId!==practiceRequest)return;
    if(typeof clearSheetSelection==='function')clearSheetSelection();
    practicePage=null;closePracticeDetail();if(typeof parkInlineReview==='function')parkInlineReview();
    document.querySelector('#practice-rows').replaceChildren();
    status.textContent=`No se pudo consultar la bandeja: ${error.message}. Actualizá o elegí un lote importado.`;
    document.querySelector('#board-previous').disabled=true;document.querySelector('#board-next').disabled=true;
  } finally {if(requestId===practiceRequest){setBoardControlsDisabled(false);document.querySelector('#board-refresh').disabled=false;}}
}

function badge(label,state) {
  const span=document.createElement('span');span.className=`status-badge state-${state}`;span.textContent=label;return span;
}

function rowObservation(item) {
  if(item.disposition!=='included')return item.eligibility_reasons.map(r=>exclusionNames[r] || r.replaceAll('_',' ')).join(' · ');
  const counts=item.control_counts;
  if(counts.requires_update)return '↻ Datos cambiaron: repetir controles afectados';
  if(Object.keys(counts).length===1 && counts.no_evaluado)return 'Análisis pendiente';
  if(item.observations){
    const pending=item.observations.filter(i=>i.state!=='resolved').sort((a,b)=>(a.category==='inconsistency'?-1:1)-(b.category==='inconsistency'?-1:1));
    if(!pending.length)return 'Sin alertas detectadas pendientes; no implica autorización';
    const priority=pending.filter(i=>i.category==='inconsistency'),gaps=pending.filter(i=>i.category!=='inconsistency');
    const messages=[];
    if(priority.length)messages.push(`${({RN13:'Diferencia de suma',RN17:'Posible repetición',RN14:'Valor de convenio'})[priority[0].rule_code] || priority[0].reason}${priority.length>1?` (+${priority.length-1})`:''}`);
    if(gaps.length)messages.push(`Información insuficiente (${gaps.length})${gaps[0].rule_code?'':`: ${gaps[0].reason}`}`);
    return messages.join(' · ');
  }
  if(item.motives.length)return '⚑ '+item.motives.map(m=>m.label).join(' · ');
  if(Object.keys(counts).length===1 && counts.no_evaluado)return 'Análisis pendiente';
  const missing=(counts.no_concluyente || 0)+(counts.no_evaluado || 0);
  const pendingRules=new Set((item.checks || []).filter(c=>c.state==='no_concluyente' || c.state==='no_evaluado').map(c=>c.rule));
  if(pendingRules.has('RN09') && pendingRules.has('RN14'))return 'Autorización / valores pendientes';
  return missing?`${missing} controles pendientes`:'Sin avisos en controles ejecutados';
}

function columnStatus(cell,mark,label,state,onClick){
  cell.className='column-state state-'+state;
  const node=onClick?document.createElement('button'):document.createElement('span');
  if(onClick){node.type='button';node.addEventListener('click',onClick);}
  node.className='column-indicator';node.textContent=mark;
  node.title=label;node.setAttribute('aria-label',label);
  const text=document.createElement('small');text.textContent=label;
  if(onClick)node.append(text);else cell.append(text);
  cell.append(node);
}

function boardConsultOnly(){return practicePage?.filters?.scope==='all' || ['auditor','closed'].includes(practicePage?.handoff?.state);}

function renderDocumentColumn(cell,item,kind){
  const doc=item.documents?.[kind],label=kind==='informe'?'Informe':'Autorización PDF';
  const state=!doc?'unknown':doc.count===0?'missing':doc.state==='revisado_manualmente'?'read':'present';
  const words={unknown:'Duda',missing:'Sin PDF',present:'Por leer',read:'Leído'};
  const mark={unknown:'?',missing:'×',present:'✓',read:'✓'}[state];
  columnStatus(cell,mark,words[state],state==='read'?'ok':state==='present'?'warning':'muted',
    !boardConsultOnly() && typeof showRowDocuments==='function'?()=>showRowDocuments(item.source_row):null);
  cell.title=label+': '+words[state]+'. La marca indica si hay un PDF aportado y su lectura registrada.';
}

function renderCsvColumns(row,item){
  const signal=item.authorization?.panel_signal || {},coverage=signal.csv_coverage || {};
  const presence=document.createElement('td'),authorization=document.createElement('td');
  const found=signal.presence==='found',absent=signal.presence==='not_located';
  if(item.disposition && item.disposition!=='included'){
    const label=item.disposition==='excluded'?'Fuera de alcance':'Alcance pendiente';
    columnStatus(presence,'—',label,'muted',null);columnStatus(authorization,'—',label,'muted',null);
    presence.classList.add('column-presence');
  row.append(presence,authorization);return;
  }
  const open=!boardConsultOnly() && typeof showSheetAuthorization==='function'?()=>showSheetAuthorization(item.source_row):null;
  if(coverage.component_rule_id)columnStatus(presence,coverage.authorization_path?'✓':'?',coverage.parent_row?'Ver principal':'Duda',coverage.authorization_path?'ok':'muted',open);
  else columnStatus(presence,found?'✓':absent?'×':'?',found?'Hallada':absent?'Ausente':'Duda',found?'ok':'muted',open);
  let mark='?',label='Por verificar',state='warning';
  if(coverage.coverage_note && ['already_used','outside_window'].includes(coverage.status)){mark='?';label='Pendiente de verificar';}
  else if(coverage.status==='component_supported'){mark='✓';label='Aval principal';state='ok';}
  else if(coverage.status==='component_pending'){mark='?';label=coverage.reason==='Verificar segunda proyección'?coverage.reason:'Revisar adicional';}
  else if(coverage.status==='posterior_candidate'){mark='!';label='Posible débito · verificar orden';}
  else if(coverage.status==='later_movement'){mark='?';label='Orden posterior · verificar';}
  else if(coverage.status==='unidentified'){mark='!';label='Afiliado no identificable';}
  else if(coverage.status==='referred_elsewhere'){mark='!';label='Derivada a otro prestador';}
  else if(coverage.status==='referral_pending'){mark='?';label='Verificar prestador';}
  else if(coverage.status==='prior_not_found'){mark='!';label='Aval anterior no localizado';}
  else if(coverage.status==='one_unit_supported'){mark='✓';label='1 realización';state='ok';}
  else if(coverage.status==='declared_rejected' || (!coverage.status && signal.item_authorization==='rejected')){mark='×';label='Rechazo';state='bad';}
  else if(coverage.status==='already_used'){mark=coverage.reviewed?'✓':'!';label=coverage.reviewed?'Revisado':coverage.export_scope?'Sin aval':'Usado';state=coverage.reviewed?'muted':'warning';}
  else if(coverage.status==='units_supported'){mark='✓';label=csvUnitsLabel(coverage);state='ok';}
  else if(coverage.status==='one_unit_only' || coverage.status==='units_partial'){mark='!';label=csvUnitsLabel(coverage);}
  else if(coverage.status==='no_aval'){mark='!';label='Sin aval';}
  else if(coverage.status==='coverage_pending'){mark='?';label='Pendiente de cotejo';}
  else if(coverage.status==='outside_window'){mark='!';label='Fuera de plazo';}
  else if(['temporal_pending','temporal_late','needs_review'].includes(coverage.status)){mark='?';label=coverage.status==='temporal_late'?'Revisar fechas':'Pendiente de verificar';}
  else if(signal.item_authorization==='authorized'){mark='✓';label='Declarada';state='ok';}
  columnStatus(authorization,mark,label,state,open);
  authorization.title=(typeof csvCoverageText==='function' && coverage.status?csvCoverageText(coverage).join(' '):
    'Consultar la declaración individual y su correspondencia con la prestación.');
  presence.classList.add('column-presence');
  row.append(presence,authorization);
}

function boardMoney(value){
  if(value===null || value===undefined)return '—';
  const text=String(value);
  if(!/^-?\d+(\.\d{1,2})?$/.test(text))return '—';
  const negative=text.startsWith('-'),[whole,fraction='']=text.replace('-','').split('.');
  return (negative?'−':'')+whole.replace(/\B(?=(\d{3})+(?!\d))/g,'.')+','+fraction.padEnd(2,'0');
}

function appendCategoryActions(detail,item){
  if(item.family_basis==='not_found_in_catalog' && item.code && practicePage?.batch?.provider==='HPC' && !practicePage.classification?.source_unavailable &&
       practicePage.batch.revision_state!=='cerrada' && ['admin','reviewer'].includes(currentRole))
    detail.append(sheetButton('Registrar categoría',()=>showCategoryRegistration(item)));
  const registered=item.family_evidence?.code?.find(source=>source.kind==='registered_hpc_category');
  if(registered && practicePage?.batch?.revision_state!=='cerrada')
    detail.append(sheetButton('Corregir categoría',()=>showCategoryRegistration(item,{previous:registered})));
}

function configureBoardColumns(showAmounts){
  const widths=[78,180,62,82,60,60,...(showAmounts?[80,80]:[]),80,85,94,85,88,84,76];
  const group=document.querySelector('#board-columns');group.replaceChildren();
  for(const width of widths){
    const col=document.createElement('col');col.setAttribute('style','width:'+width+'px');group.append(col);
  }
}

function budgetMoney(value){
  return '$'+boardMoney(value).replace(/,00$/,'');
}

function budgetParagraph(item,budget){
  const date=value=>value?.split('-').reverse().join('/') || 'fecha sin precisar';
  const origin=[item.description || 'Prestación',item.code?'código '+item.code:null,budget.order_id?'orden '+budget.order_id:null].filter(Boolean).join(' · ');
  if(budget.status==='otro_item')return origin+'. El presupuesto pertenece a otra práctica de la orden. Revisá esta prestación por su convenio HPC.';
  if(budget.status==='por_verificar')return origin+'. Presupuesto por verificar: '+budget.reason+' No se calculó una diferencia.'+(budget.csv_row?' Consultá el registro '+budget.csv_row+' del CSV.':'');
  const check=budget.status==='over'?'La diferencia a revisar es '+budgetMoney(budget.excess_ars)+'.':'El total facturado no supera ese presupuesto.';
  return origin+'. '+(budget.movement_actor?'Movimiento registrado por '+budget.movement_actor+'. ':'')+'El '+date(budget.authorized_on)+' se autorizó un presupuesto total de '+budgetMoney(budget.authorized_ars)+' ARS para esta práctica. El '+date(budget.performed_on)+' se facturaron '+budgetMoney(budget.billed_ars)+' ARS. '+check+' Respaldo: movimiento del CSV, registro '+budget.csv_row+'.';
}

async function showBudgetDetail(item){
  const content=sheetPanel('Presupuesto de la prestación',item.source_row),ctx=sheetContext();
  document.querySelector('#sheet-review-panel').classList.add('budget-panel');
  for(const row of document.querySelectorAll('#practice-rows tr[data-source-row]'))row.classList.toggle('review-selected',Number(row.dataset.sourceRow)===item.source_row);
  content.textContent='Consultando el presupuesto…';
  try{
    const data=await request(`/api/datasets/${ctx.datasetId}/batches/${ctx.batchId}/rows/${item.source_row}/authorization-correspondence`);
    if(!sheetCurrent(ctx))return;
    if(data.dataset_version!==practicePage?.dataset_version || data.revision_version!==practicePage?.batch.revision_version || !data.csv_coverage?.budget){
      closeSheetReview();await loadPracticeBoard();message.textContent='La evidencia cambió. Volvé a abrir la prestación.';return;
    }
    const paragraph=document.createElement('p');paragraph.className='budget-summary';
    paragraph.textContent=budgetParagraph(item,data.csv_coverage.budget);
    content.replaceChildren(paragraph);
  }catch(error){if(sheetCurrent(ctx))content.textContent='No se pudo consultar el presupuesto: '+error.message;}
}

function moneyKey(value){
  const m=/^(\d+)(?:\.(\d+))?$/.exec(String(value));if(!m)return null;
  return m[1].replace(/^0+(?=\d)/,'')+'.'+(m[2] || '').replace(/0+$/,'');
}
function referenceChoiceNeeded(item){
  const ref=item.reference_comparison || {}, compare=ref.related_comparison || ref;
  const total=compare.candidate_total_if_ars_and_same_unit, b=item.authorization?.panel_signal?.csv_coverage?.budget;
  return total!=null && ['over','within'].includes(b?.status) && b.authorized_ars!=null &&
    moneyKey(total)!==null && moneyKey(b.authorized_ars)!==null && moneyKey(total)!==moneyKey(b.authorized_ars);
}

function renderReferenceCells(row, item, compact=false) {
  const ref=item.reference_comparison || {},price=document.createElement('td'),difference=document.createElement('td');
  price.className='numeric';difference.className='numeric';
  const missing={outside_scope:'Fuera del alcance de comparación',outside_declared_dates:'Sin referencia vigente para la fecha',undetermined_declared_dates:'Fecha de referencia indeterminada',catalogue_amount_not_interpretable:'Importe de referencia no interpretable',source_unavailable:'Fuente no disponible',unsupported_value_cut:'Corte de valores no compatible',hpc_provider_scope_missing:'Confirmá HPC y la fuente del lote',closed_revision_not_compared:'Revisión cerrada: consultar historia',
    withdrawn_reference:'Referencia dada de baja',status_evidence_unverifiable:'Respaldo del estado no verificable',
    ambiguous_hpc_tariff:'Referencias ambiguas',source_or_evidence_unverifiable:'Fuente o respaldo no verificable'};
  if(ref.recorded_amount!==null && ref.recorded_amount!==undefined) {
    price.textContent=`${ref.recorded_amount} · ${ref.declared_currency || 'moneda pendiente'} · ${ref.declared_unit || 'unidad pendiente'}`;
    if(!['numeric_equal','numeric_above_candidate','numeric_below_candidate'].includes(ref.status))price.textContent+=' · referencia pendiente de interpretación';
  } else price.textContent=Object.hasOwn(missing,ref.status)?missing[ref.status]:'Valor indeterminado; revisar presupuesto/autorización';
  if(compact && ['source_unavailable','hpc_provider_scope_missing'].includes(ref.status))price.textContent='Sin referencia';
  const related=ref.related_hpc_references;
  if(related?.candidates?.length) {
    price.textContent=related.candidates.map(c=>{
      const effective=c.effective_reference;
      let text;
      if(effective?.status==='withdrawn_reference')text=`BAJA para la fecha · original histórico ${c.recorded_amount ?? 'no interpretable'}, no aplicable`;
      else if(effective?.status==='status_evidence_unverifiable')text=`Estado no verificable · original histórico ${c.recorded_amount ?? 'no interpretable'}, no aplicable`;
      else if(effective?.value_version) {
        const literal=effective.recorded_amount ?? effective.value_version.amount_ars ?? 'no interpretable';
        text=effective.status==='documented_version_candidate'
          ? `${literal} · ARS · ${effective.declared_unit}`
          : `${literal} · versión ${effective.status}; no verificable o no interpretable, sin uso económico`;
      } else if(effective?.status==='documented_agreement_candidate')text=`${effective.recorded_amount} · ${effective.declared_currency} · ${effective.declared_unit} · convenio documentado ${effective.agreement_declaration.id}`;
      else if(effective?.agreement_declaration)text=`${c.recorded_amount ?? 'no interpretable'} · respaldo ${effective.status}; sin comparación económica`;
      else text=`${c.recorded_amount ?? 'importe no interpretable'} · moneda/unidad pendientes · importe original (${effective?.status || c.temporal_relation || 'vigencia no evaluada'})`;
      return `${text} · enlace ${c.order_code} → ${c.tariff_code} sin verificar`;
    }).join(' | ');
  }
  const calculated=ref.calculated_nomenclature_references;
  const arithmeticLabels={corroborated_technical_rounding:'cálculo y redondeo técnico coinciden',recorded_amount_invalid:'importe registrado no interpretable',recorded_amount_mismatch:'importe registrado distinto del cálculo',not_interpretable:'cálculo no interpretable',coefficient_conflict:'coeficientes contradictorios',unsupported_formula:'fórmula no admitida',provider_conflict:'prestador contradictorio'}, temporalLabels={inside_declared_dates:'dentro de fechas declaradas',outside_declared_dates:'fuera de fechas declaradas',undetermined_declared_dates:'fecha indeterminada'};
  if(calculated?.candidates?.length && !related?.candidates?.length && (ref.recorded_amount===null || ref.recorded_amount===undefined)) {
    price.textContent=(calculated.candidates.length>1?'Referencias múltiples; no seleccionar automáticamente · ':'')+calculated.candidates.map(c=>`${c.recorded_amount ?? 'importe registrado no interpretable'} · referencia calculada de nomenclador · moneda/unidad pendientes · ${arithmeticLabels[c.arithmetic_status] || c.arithmetic_status} · ${temporalLabels[c.temporal_relation] || c.temporal_relation}`).join(' | ');
  }
  if(calculated && !calculated.candidates?.length && calculated.status!=='no_exact_nomenclature_code')price.textContent+=` · Referencia calculada no disponible (${calculated.status})`;
  const comparison=ref.related_comparison || ref;
  const value=comparison.difference_ars_if_comparable;
  difference.textContent=value===null || value===undefined?'Sin diferencia determinable':`${value} · ${ref.related_comparison?'enlace sujeto a verificación':ref.declared_currency==='ARS' && ref.declared_unit==='por práctica'?'candidata':'condicional'}`;
  if(comparison.status==='numeric_above_candidate' && value!==null && value!==undefined)difference.classList.add('reference-over');
  const details=[comparison.use_limit || ref.use_limit || 'Comparación exploratoria; no es débito.',
    comparison.candidate_total_if_ars_and_same_unit!==null && comparison.candidate_total_if_ars_and_same_unit!==undefined?`Total de referencia si misma moneda/unidad: ${comparison.candidate_total_if_ars_and_same_unit}`:'',
    ref.source_id?`Fuente ${ref.source_id} · SHA ${ref.source_sha256} · ${ref.tariff?.source_locator || ''}`:'',
    ref.status?`Estado: ${ref.status}`:'',
    'La diferencia es total facturado menos referencia; no se multiplica otra vez el total facturado.'].filter(Boolean).join('\n');
  const linkDetails=related?.candidates?.map(c=>`${related.use_limit} Orden seq ${c.order_code_seqs.join(',')} · práctica ${c.practice_id} · convenio seq ${c.convention_code_seqs.join(',')} · ${c.source_locator} · documento ${c.document_source_id || 'sin identificar'}, página ${c.document_page ?? 'sin indicar'} · ${c.temporal_relation} · SHA ${c.source_sha256}`).join('\n') || '';
  const calculationDetails=calculated?.candidates?.map(c=>[
    calculated.use_limit, `Código exacto ${c.code} · ${c.description} · estado declarado ${c.component_status}`,
    `Fórmula: ${c.formula} · Q GAL ${c.qGal} × ${c.galenoRadiologico} + Gto ${c.gto} × ${c.unidadRadiologica}`,
    `Cálculo exacto ${c.calculated_amount_exact ?? 'no interpretable'} · cotejo a centavos ${c.calculated_amount_rounded ?? 'no interpretable'} · importe registrado ${c.recorded_amount ?? 'no interpretable'} · ${c.rounding_note || ''}`,
    `Desde ${c.valid_from || 'sin fecha acreditada'} · ${c.temporal_relation} · ${c.source_file}, fila ${c.source_row} · ${c.source_locator} · SHA ${calculated.source_sha256}`,
    `Norma literal: ${c.norma || 'sin texto'} · unidad arancelaria literal: ${c.unidadArancelaria || 'sin texto'} · forma de facturación literal: ${c.formaFacturacion || 'sin texto'}`,
    'Las normas pueden estar incompletas: consultar fuente. No se interpretan reglas especiales ni se acredita equivalencia o respaldo del factor automáticamente.'
  ].join('\n')).join('\n\n') || '';
  price.title=details+(linkDetails?'\n'+linkDetails:'')+(calculationDetails?'\n'+calculationDetails:'');difference.title=details;
  if(compact){
    const value=comparison.candidate_total_if_ars_and_same_unit;
    price.classList.add('column-reference');difference.classList.add('column-difference');
    const hasTotal=value!==null && value!==undefined;
    const relatedOne=related?.candidates?.length===1?related.candidates[0]:null;
    const calculatedOne=calculated?.candidates?.length===1?calculated.candidates[0]:null;
    const literal=ref.recorded_amount ?? relatedOne?.recorded_amount ?? calculatedOne?.recorded_amount;
    price.textContent=hasTotal?boardMoney(value):boardMoney(literal);
    const note=document.createElement('small');
    const temporal={outside_declared_dates:'Fuera de vigencia',withdrawn_reference:'Baja',
      undetermined_declared_dates:'Vigencia por verificar',ambiguous_hpc_tariff:'Varias referencias',
      source_or_evidence_unverifiable:'Fuente por verificar',status_evidence_unverifiable:'Respaldo por verificar'};
    note.textContent=temporal[ref.status] || (hasTotal?'Candidato':literal!=null?'Importe por verificar':
      related?.candidates?.length>1 || calculated?.candidates?.length>1?'Varias referencias':'Sin referencia');
    if(item.applicable_tariff){
      const t=item.applicable_tariff;price.textContent=boardMoney(t.total_ars);
      note.textContent='Aplicable · '+(t.from || 'Inicio sin informar')+' a '+t.through;
      price.title='HPC · ARS por práctica · '+t.locator;
    }else if(ref.effective_reference?.value_version?.effective_from || ref.tariff?.valid_from){
      note.textContent+=' · desde '+(ref.effective_reference?.value_version?.effective_from || ref.tariff.valid_from);
    }
    if(!boardConsultOnly() && typeof showEconomicApplicability==='function'){
      const link=document.createElement('button');link.type='button';link.className='value-link';
      link.textContent=price.textContent;link.append(note);
      link.setAttribute('aria-label','Consultar referencia de convenio para '+(item.description || 'esta prestación'));
      link.addEventListener('click',()=>showEconomicApplicability(item.source_row,ref.source_id || null));price.replaceChildren(link);
    }else price.append(note);
    difference.textContent=boardMoney(comparison.difference_ars_if_comparable);
    const state=document.createElement('small');state.textContent=comparison.difference_ars_if_comparable!=null?'Por verificar':'Sin determinar';difference.append(state);
  }
  const budget=item.authorization?.panel_signal?.csv_coverage?.budget;
  if(compact && budget && budget.status!=='otro_item' && !boardConsultOnly()){
    const label=budget.status==='over'?budgetMoney(budget.excess_ars)+' a revisar':budget.status==='within'?'Dentro del presupuesto':'Presupuesto por verificar';
    const button=sheetButton(label,()=>showBudgetDetail(item));button.className='budget-link';
    button.setAttribute('aria-label',label+' · ver presupuesto de '+(item.description || 'la prestación'));
    const source=document.createElement('small');source.textContent='Presupuesto CSV';
    if(comparison.difference_ars_if_comparable==null){difference.replaceChildren(button,source);}
    else{const extra=document.createElement('div');extra.append(button,source);difference.append(extra);}
    difference.title='Presupuesto del CSV: '+label+(comparison.difference_ars_if_comparable!=null?' · La diferencia de convenio se muestra por separado.':'');
    if(budget.status!=='within')difference.classList.add('budget-attention');
  }
  if(!compact){row.append(price,difference);return;}
  const authorized=document.createElement('td');authorized.className='numeric column-budget';
  const known=['over','within'].includes(budget?.status) && budget.authorized_ars!=null;
  authorized.textContent=known?boardMoney(budget.authorized_ars):'—';
  const info=document.createElement('small');
  info.textContent=known?'Orden '+(budget.order_id || 'CSV'):budget?.status==='otro_item'?'Asignado a otra práctica':budget?'Por verificar':'Sin presupuesto identificado';
  authorized.append(info);
  if(referenceChoiceNeeded(item)){
    difference.replaceChildren();difference.textContent='Elegir referencia';
    difference.title='Los dos totales difieren. Verificá cuál corresponde antes de proponer un importe.';
  }
  row.append(price,authorized,difference);
}

function renderPracticeRows(items) {
  const body=document.querySelector('#practice-rows');
  const reopen=typeof parkInlineReview==='function'?parkInlineReview():null;
  body.replaceChildren();
  const amounts=Boolean(document.querySelector('#board-show-amounts')?.checked);
  configureBoardColumns(amounts);
  const columnCount=amounts?15:13;
  let previousAffiliate=null;
  for(const item of items){
    if(['priority','affiliate_id'].includes(document.querySelector('#board-sort')?.value) && (previousAffiliate!==item.affiliate_id || !item.affiliate_id)){
      const group=document.createElement('tr'),heading=document.createElement('th');
      heading.colSpan=columnCount;
      const name=document.createElement('strong');name.textContent=item.affiliate_name || 'Paciente sin nombre';
      const identity=document.createElement('span');identity.className='patient-identity';
      identity.textContent='Afiliado '+(item.affiliate_id || 'por identificar');
      const count=document.createElement('span');count.className='patient-count';
      count.textContent=(item.patient_group_total===1?'1 prestación':(item.patient_group_total ?? 1)+' prestaciones')+(item.patient_group_position>1?' · continúa':'');
      heading.append(name,identity,count);
      heading.title=practicePage?.batch?.original_name || '';group.className='affiliate-group';group.append(heading);body.append(group);previousAffiliate=item.affiliate_id;
    }
    const row=document.createElement('tr');row.dataset.sourceRow=item.source_row;
    const date=document.createElement('td');date.className='column-date';date.textContent=item.practice_date?item.practice_date.split('-').reverse().join('/'):'Sin fecha';
    if(item.order_number!=null){
      const order=document.createElement('small');order.className='order-id';order.textContent='Orden '+item.order_number;order.title=order.textContent;date.append(order);
    }
    date.title=`${item.locator} · ${practicePage?.batch?.original_name || ''}`;row.append(date);
    const practice=document.createElement('td');practice.className='column-practice';practice.textContent=item.description || 'Práctica sin descripción';
    const code=document.createElement('small');code.textContent=`Cód. ${item.code || 'sin informar'} · Cant. ${item.quantity ?? '?'}`;practice.append(code);
    practice.title=[item.description,item.code,item.affiliate_name,item.affiliate_id,item.order_number,item.locator,item.family_basis].filter(Boolean).join(' · ');
    for(const source of [...(item.family_evidence?.code || []),...(item.family_evidence?.name || [])])
      practice.title+=` · ${source.source_file || source.table} · ${source.seq!==undefined?'seq='+source.seq:'fila='+source.source_row} · ${source.sheet || ''} · ${source.actor || ''} · ${source.source_id} · ${source.source_sha256}`;
    if(item.family_suggestion){const note=document.createElement('small');note.textContent=item.family_suggestion.label;practice.append(note);}
    if(item.family_basis==='exact_nomenclature_code')practice.title+=' · Código de nomenclador: no acredita equivalencia HPC.';
    if(item.corrected_fields?.length){practice.classList.add('corrected-cell');practice.title+=' · Interpretación corregida. Original e historia en Detalle.';}
    row.append(practice);
    renderCsvColumns(row,item);
    for(const kind of ['informe','autorizacion']){
      const cell=document.createElement('td');renderDocumentColumn(cell,item,kind);row.append(cell);
    }
    for(const key of ['honorarios_ars','derechos_ars','total_ars']){
      const cell=document.createElement('td');cell.className=key==='total_ars'?'numeric column-billed':'extra-amount numeric';
      cell.textContent=boardMoney(item[key]);cell.title='ARS · importe de fila';row.append(cell);
    }
    renderReferenceCells(row,item,true);
    const debit=document.createElement('td');debit.className='numeric column-debit';
    const proposal=item.debit_proposal;
    debit.textContent=proposal?.current_component_count?boardMoney(proposal.amount_ars):'—';
    const proposalLabel=document.createElement('small');
    proposalLabel.textContent=proposal?.state==='current'?'Propuesto':proposal?.state==='partially_current'?'Parcial':proposal?'Actualizar':'Sin propuesta';
    debit.append(proposalLabel);debit.title='Propuesta humana vigente de la prestación. Consultá los componentes y el respaldo en Detalle.';row.append(debit);
    const decision=document.createElement('td');decision.className='column-review';
    const noExecution=item.disposition==='included' && Object.keys(item.control_counts).length===1 && Boolean(item.control_counts.no_evaluado);
    let label=noExecution?'Sin análisis':item.disposition!=='included'?'Fuera de alcance':item.exception_reasons?.length?'Revisar':
      ['confirmada','descartada'].includes(item.decision)?'Aviso resuelto':'Sin avisos';
    const reasons=[];
    for(const obs of item.observations || []){
      if(obs.state==='referred' || obs.state==='waiting_information')reasons.push('Derivada');
      else if(obs.category==='inconsistency' && obs.state!=='resolved')
        reasons.push(({RN13:'Suma',RN17:'Repetición',RN14:'Valor'})[obs.rule_code] || obs.rule_code);
    }
    if(!noExecution && reasons.length)label=[...new Set(reasons)].join(' · ');
    const budget=item.authorization?.panel_signal?.csv_coverage?.budget;
    const budgetAlert=budget && ['over','por_verificar'].includes(budget.status);
    if(budgetAlert)label='Revisar presupuesto';
    if(item.late_billing_reason)label='Fuera de término · '+item.billing_window.days+' días';
    const admin=item.administrative_decision;
    if(admin?.current)label='Revisada · '+rowActionLabels[admin.previous.action]+' · '+rowAmount(admin.previous.amount_ars);
    else if(admin?.previous)label='Actualizar decisión';
    if(admin){
      if(admin.current){debit.replaceChildren();debit.textContent=boardMoney(admin.previous.amount_ars);proposalLabel.textContent='Decisión administrativa';debit.append(proposalLabel);}
      else if(admin.conflict){debit.replaceChildren();debit.textContent='Elegir referencia';}
      else if(admin.proposal){debit.replaceChildren();debit.textContent=boardMoney(admin.proposal.amount_ars);proposalLabel.textContent='Para decidir';debit.append(proposalLabel);}
      else if(admin.quantity_advisory){debit.replaceChildren();debit.textContent=boardMoney(admin.quantity_advisory.amount_ars);proposalLabel.textContent='A verificar';debit.append(proposalLabel);debit.title=admin.quantity_advisory.reason;}
      else if(item.authorization?.panel_signal?.csv_coverage?.coverage_note){
        debit.replaceChildren();debit.textContent='Pendiente de cotejo';debit.title=item.authorization.panel_signal.csv_coverage.coverage_note;
      }
      if(admin.current || admin.conflict || admin.proposal)debit.title='Importe en revisión administrativa';
    }
    decision.textContent=label;
    decision.title=(item.exception_details || []).join(' · ') || rowObservation(item);
    if(noExecution || item.indication_count || item.exception_reasons?.length)decision.classList.add('column-attention');
    const limits=(item.control_counts.no_concluyente || 0)+(item.control_counts.no_evaluado || 0);
    if(limits && !admin){const small=document.createElement('small');small.textContent=limits+' por comprobar';decision.append(small);}
    row.append(decision);
    const actions=document.createElement('td');actions.className='column-actions';
    if(boardConsultOnly()){actions.textContent='Solo consulta';row.append(actions);body.append(row);continue;}
    if(admin && typeof openRowDecision==='function' && observationDuty()==='administrative'){
      actions.append(sheetButton(admin.current?'Ver decisión':'Revisar',()=>openRowDecision(item)));
      row.append(actions);body.append(row);continue;
    }
    if(typeof showObservationReview==='function')actions.append(sheetButton('Revisar',()=>showObservationReview(item.source_row)));
    const detail=document.createElement('button');detail.type='button';detail.className='secondary';detail.textContent='Detalle';detail.dataset.row=item.source_row;
    detail.setAttribute('aria-label',`Ver evidencia de ${item.locator}`);detail.addEventListener('click',()=>budget?showBudgetDetail(item):openPracticeDetail(item.source_row));actions.append(detail);
    row.append(actions);body.append(row);
  }
  if(reopen!=null)mountInlineReview(reopen);
  if(!items.length){
    const row=document.createElement('tr'),cell=document.createElement('td');cell.colSpan=columnCount;
    cell.textContent='No hay prestaciones para estos filtros. Podés cambiar de vista o limpiar la búsqueda.';row.append(cell);body.append(row);
  }
}


function closePracticeDetail() {
  practiceDetailRequest++;
  document.querySelector('#practice-detail-panel').hidden=true;
  document.querySelector('#practice-detail-content').replaceChildren();
  document.querySelector('.board-layout').classList.remove('has-detail');
  if(practiceFocusedRow)document.querySelector(`#practice-rows button[data-row="${practiceFocusedRow}"]`)?.focus({preventScroll:true});
  practiceFocusedRow=null;
}

function detailText(parent,label,text) {
  const p=document.createElement('p'),strong=document.createElement('strong');strong.textContent=`${label}: `;
  p.append(strong,document.createTextNode(text===null || text===undefined?'No informado':String(text)));parent.append(p);
}

function evidenceText(value) {
  if(value?.reference_format && typeof economicEvidenceText==='function')return economicEvidenceText(value);
  if(value?.authorization_engine_version) {
    const lines=[value.data_origin==='synthetic'?'DATOS FICTICIOS · comparación de demostración':'Fuente real sin validar · resultado sin conclusión'];
    if(value.resolution)lines.push(value.resolution.reason);
    if(value.temporal) {
      lines.push(`Autorización: ${value.temporal.authorization.original ?? 'Fecha no acreditada'}`);
      lines.push(`Incorporación al consolidado: ${value.temporal.incorporation.original ?? 'Fecha no acreditada'}`);
      lines.push(value.temporal.reason);
    }
    if(value.quantity) {
      const q=value.quantity;
      lines.push(`Autorizado declarado: ${q.authorized ?? 'Desconocido'} ${q.unit || '(unidad desconocida)'}`);
      lines.push(`Facturado en conjunto: ${q.billed_joint ?? 'No se puede determinar con la información disponible'}`);
      if(q.member_count)lines.push(`Filas vinculadas: ${q.member_count}${q.members_truncated?' (detalle acotado; conjunto completo conservado en la captura)':''}`);
      const reasons={applicable_resolution_unresolved:'Resolución aplicable por aclarar',authorized_quantity_or_unit_unknown:'Cantidad o unidad autorizada desconocida',related_identity_unresolved:'Otra fila del mismo código y fecha tiene identidad por aclarar',other_lot_scope_unresolved:'Otro lote relacionado tiene fuentes por seleccionar o actualizar',association_candidates_incomplete:'No hay una lista completa y verificable de coincidencias',coverage_identity_between_captures_unverified:'La identidad de cobertura entre capturas sigue sin verificar',pending_or_ambiguous_association:'Hay vínculos pendientes o ambiguos',billed_quantity_or_unit_unverified:'Cantidad facturada o unidad sin comprobar'};
      for(const reason of q.limitations || [])lines.push(reasons[reason] || 'Información de cobertura pendiente de revisión');
      for(const m of q.members || [])lines.push(`${m.batch_name || 'Otro lote del conjunto'} · ${m.locator} · cantidad ${m.billed ?? 'desconocida'}`);
    }
    if(value.source_issues?.length)lines.push('Las fuentes requieren selección, actualización o verificación del original.');
    lines.push('Sin asignación de unidades ni propuesta monetaria.');
    return lines.join('\n');
  }
  const names={source_sha256:'SHA-256 de origen',locator:'Localizador',cells:'Celdas',amounts_ars:'Importes ARS',tolerance_ars:'Tolerancia ARS',quantity_not_applied:'Cantidad no multiplicada',value_cut:'Corte de valores',candidate_count:'Otras coincidencias candidatas',other_locators:'Localizadores de otras coincidencias',locators_truncated:'Listado de coincidencias acotado',currency:'Moneda',economic_unit:'Unidad económica',applicable_price:'Precio aplicable',period_relation:'Relación con período'};
  return Object.entries(value || {}).map(([key,v])=>`${names[key] || key.replaceAll('_',' ')}: ${v===null?'No acreditado':typeof v==='object'?JSON.stringify(v,null,2):v===true?'Sí':v===false?'No':String(v)}`).join('\n');
}

function appendControlEvidence(parent,value) {
  const evidence=document.createElement('pre');evidence.textContent=value?evidenceText(value):'No hay evidencia de ejecución de este control.';parent.append(evidence);
  if(value?.authorization_engine_version) {
    const trace=document.createElement('details'),title=document.createElement('summary'),raw=document.createElement('pre');
    title.textContent='Trazabilidad de esta captura';raw.textContent=JSON.stringify(value,null,2);trace.append(title,raw);parent.append(trace);
  }
}

async function openPracticeDetail(sourceRow) {
  if(typeof closeSheetReview==='function')closeSheetReview();
  const datasetId=selectedDataset?.id,batchId=document.querySelector('#invoice-batch').value;
  if(!practicePage || !datasetId || !batchId)return;
  closePracticeDetail();practiceFocusedRow=sourceRow;
  const requestId=++practiceDetailRequest;
  const panel=document.querySelector('#practice-detail-panel'),content=document.querySelector('#practice-detail-content');
  panel.hidden=false;document.querySelector('.board-layout').classList.add('has-detail');
  document.querySelector('#practice-detail-heading').textContent=`Hoja1!${sourceRow} · evidencia`;
  content.textContent='Consultando evidencia e historia…';
  try {
    const data=await request(`/api/datasets/${datasetId}/batches/${batchId}/rows/${sourceRow}/practice-detail`);
    if(requestId!==practiceDetailRequest || selectedDataset?.id!==datasetId || document.querySelector('#invoice-batch').value!==batchId)return;
    if(data.dataset_version!==practicePage?.dataset_version || data.revision_version!==practicePage?.batch.revision_version) {
      closePracticeDetail();await loadPracticeBoard();message.textContent='La revisión cambió; bandeja actualizada. Volvé a abrir la práctica.';return;
    }
    content.replaceChildren();
    const classified=practicePage.items.find(item=>item.source_row===sourceRow);
    if(classified)appendCategoryActions(content,classified);
    if(classified?.family_basis==='not_found_in_catalog' && !practicePage.batch.provider)
      detailText(content,'Categoría','Para registrar una categoría, primero confirmá el alcance HPC del lote.');
    if(classified?.code && practicePage.batch.provider==='HPC' && practicePage.batch.revision_state!=='cerrada')
      content.append(sheetButton('Solicitar alta al administrador',()=>showPracticeRequest(classified)));
    for(const source of classified?.family_evidence?.code || []){
      if(source.kind==='registered_hpc_category'){
        content.append(sheetButton('Ver historia de categoría',()=>showCategoryHistory(classified)));
        detailText(content,'Categoría registrada',source.area+' · '+source.source_file+' · '+source.sheet+
          ' · fila '+source.source_row+', columna '+source.source_column+' · '+source.actor);
      }
    }
    detailText(content,'Ámbito',data.disposition==='included'?'Elegible':data.eligibility_reasons.map(r=>r.replaceAll('_',' ')).join('; '));
    detailText(content,'Fecha',data.practice_date);
    const table=document.createElement('table');table.className='detail-fields';
    const header=document.createElement('tr');for(const label of ['Dato','Original','Interpretación actual']){const th=document.createElement('th');th.textContent=label;header.append(th);}table.append(header);
    const fields={B:'Nro. Orden (B)',C:'Afiliado (C)',E:'Código completo (E)',F:'Tipo (F)',G:'Cantidad (G)',H:'Nombre declarado (H)',K:'Descripción (K)'};
    for(const [key,label] of Object.entries(fields)) {const tr=document.createElement('tr');for(const value of [label,data.original_fields[key]??'No informado',data.effective_fields[key]??'No informado']){const td=document.createElement('td');td.textContent=String(value);tr.append(td);}table.append(tr);}
    content.append(table);
    if(data.disposition==='included' && typeof showEconomicApplicability==='function')content.append(sheetButton('Referencia económica HPC',()=>showEconomicApplicability(sourceRow)));
    if(data.disposition==='included' && typeof showRn14Proposal==='function')content.append(sheetButton('Revisar importe RN14',()=>showRn14Proposal(sourceRow)));
    detailText(content,'Importes originales ARS',`O ${data.amounts_original_ars.honorarios_ars} · P ${data.amounts_original_ars.derechos_ars} · Q ${data.amounts_original_ars.total_ars}. Son importes de fila, no débitos.`);
    const trace=document.createElement('details'),traceTitle=document.createElement('summary');traceTitle.textContent='Original y trazabilidad';trace.append(traceTitle);
    detailText(trace,'Archivo',data.invoice.original_name);detailText(trace,'SHA-256',data.invoice.source_sha256);
    const download=document.createElement('a');download.href=`/api/datasets/${datasetId}/batches/${batchId}/file`;download.textContent='Descargar original privado';trace.append(download);content.append(trace);
    for(const control of data.controls) {
      const block=document.createElement('details'),heading=document.createElement('summary');
      heading.textContent=`${ruleNames[control.rule_code] || control.rule_code} · ${control.freshness==='requires_update'?'Datos cambiaron: repetir':control.freshness==='outside_scope'?'Histórico, fuera del alcance':simpleResults[control.result] || control.result}`;
      block.append(heading);detailText(block,'Control',control.rule_code);detailText(block,'Resultado',simpleResults[control.result] || control.result);
      detailText(block,'Motivo',control.reason_label);
      if(control.freshness==='requires_update')detailText(block,'Vigencia','Datos o dependencias cambiaron. El resultado anterior es histórico hasta actualizar explícitamente el análisis.');
      appendControlEvidence(block,control.evidence);content.append(block);
    }
    const history=document.createElement('details'),historyTitle=document.createElement('summary');historyTitle.textContent=`Decisiones humanas · ${data.decision_history.length} antecedentes`;
    history.append(historyTitle);
    if(!data.decision_history.length)detailText(history,'Estado','Sin decisiones registradas; no implica aprobación.');
    for(const decision of data.decision_history){appendHistoryOrigin(history,decision,datasetId,batchId);detailText(history,`${decision.rule_code} · ${decisionLabels[decision.state]} · ${decision.actor_username} · ${decision.created_at}`,`${decision.foundation}${decision.evidence_note?' — '+decision.evidence_note:''}`);}
    content.append(history);
    if(data.interpretation_history.length){const edits=document.createElement('details'),title=document.createElement('summary');title.textContent='Historia de correcciones de interpretación';edits.append(title);for(const edit of data.interpretation_history){appendHistoryOrigin(edits,edit,datasetId,batchId);detailText(edits,`${edit.field} · ${edit.actor_username} · ${edit.created_at}`,`${edit.previous_json} → ${edit.new_json}. ${edit.reason}`);}content.append(edits);}
    detailText(content,'Referencias de valores',data.value_sources.length?data.value_sources.map(s=>s.cut_label || 'Corte no declarado').join('; ')+' · consultar aplicabilidad por prestación.':'No hay una fuente de valores registrada.');
    const actions=document.createElement('div');actions.className='detail-actions';
    for(const [label,view] of [['Ver autorizaciones de esta fila','autorizaciones'],['Consultar referencia HPC','valores'],['Ir a revisión de alertas','revision']]) {
      const button=document.createElement('button');button.type='button';button.className='secondary';button.textContent=label;
      button.addEventListener('click',()=>{
        if(view==='autorizaciones'){document.querySelector('#authorization-match-row').value=sourceRow;clearCorrespondence();}
        if(view==='valores'){document.querySelector('#hpc-row').value=sourceRow;document.querySelector('#value-code').value=data.effective_fields.E || '';document.querySelector('#value-date').value=data.practice_date || '';}
        if(view==='revision'){document.querySelector('#legacy-review').open=true;document.querySelector('#legacy-review').scrollIntoView({block:'start'});return;}
        activateWorkspaceView(view);
      });actions.append(button);
    }
    if(typeof showRowDocuments==='function')actions.append(sheetButton('Informes y PDF aportados',()=>showRowDocuments(sourceRow)));
    if(typeof showMedicalConsultations==='function')actions.append(sheetButton('Consultas y respuestas externas',()=>showMedicalConsultations(sourceRow)));
    content.append(actions);
  } catch(error) {if(requestId===practiceDetailRequest)content.textContent=`No se pudo cargar el detalle: ${error.message}`;}
}

function appendHistoryOrigin(parent,entry,datasetId,batchId){
  const note=document.createElement('p');
  note.textContent=entry.origin_revision_ordinal===null || entry.origin_revision_ordinal===undefined?'Antecedente: revisión de origen sin reconstruir. No acredita vigencia actual.':`Antecedente de revisión ${entry.origin_revision_ordinal} · ${entry.origin_revision_state||'estado sin reconstruir'}${entry.origin_is_current_revision?' · revisión actual':''}. No acredita vigencia actual.`;
  parent.append(note);
  if(entry.origin_closure_id && entry.origin_revision_id){const link=document.createElement('a');link.textContent='Descargar cierre de origen';link.href=`/api/datasets/${datasetId}/batches/${batchId}/export-closed?revision_id=${encodeURIComponent(entry.origin_revision_id)}`;parent.append(link);}
}

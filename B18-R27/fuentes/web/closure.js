/* C1: explicit preview, scoped justification, confirmation and frozen download. */
let closureEpoch = 0;
let closureDownloadRevision = null;
const closureDrafts = new Map();
const closureReasonLabels = {
  "specific_accepted_reference_pending": "Referencia específica aceptada identificada; sin cálculo general hasta resolver su aplicación",
  "economic_applicability_not_recorded": "Falta documentar la referencia aplicable a esta fila",
  "economic_applicability_not_current": "La referencia se retiró o sus dependencias cambiaron; requiere actualización",
  "tariff_above_applicable_reference": "El total facturado supera la referencia aplicable; revisar la diferencia",
  "tariff_below_applicable_reference": "El total facturado es inferior a la referencia aplicable; revisar la diferencia",
  "tariff_within_tolerance": "El total y la referencia aplicable concilian dentro de $0,01",
  "economic_reference_sufficient_for_row": "Referencia suficiente para esta fila, fecha, unidad y cantidad",
  "demo_autorizacion_declarada": "FICTICIO · autorización declarada compatible",
  "demo_rechazo_declarado": "FICTICIO · la resolución declara rechazo de esta práctica",
  "demo_resolucion_sin_conclusion": "FICTICIO · resolución o vínculo por aclarar",
  "demo_autorizacion_previa_incorporacion": "FICTICIO · autorización anterior a incorporación",
  "demo_autorizacion_posterior_incorporacion": "FICTICIO · autorización posterior a incorporación",
  "demo_secuencia_temporal_incompleta": "FICTICIO · falta evidencia para ordenar autorización e incorporación",
  "demo_cantidad_dentro_declarado": "FICTICIO · cantidad conjunta dentro de lo declarado",
  "demo_cantidad_supera_declarado": "FICTICIO · cantidad conjunta mayor que la declarada",
  "demo_cantidad_sin_conclusion": "FICTICIO · cantidad, cobertura o asociación pendiente",
  "autorizaciones_reales_sin_validar": "La fuente real de autorizaciones todavía no está validada",
  "evidencia_temporal_real_sin_validar": "Las fechas declaradas todavía no acreditan la secuencia real",
  "cobertura_real_sin_validar": "La cobertura real y sus unidades todavía no están validadas",
  "autorizaciones_sin_adaptador_validado": "Las autorizaciones todavía no se conciliaron con esta factura",
  "falta_fecha_incorporacion_por_practica": "Falta la fecha de incorporación de esta práctica al Excel",
  "cantidad_autorizada_no_acreditada": "Falta comprobar cuántas unidades fueron autorizadas",
  "diferencia_supera_tolerancia": "Honorarios + derechos no coinciden con el total",
  "suma_concilia": "La suma O + P concilia con Q",
  "posible_duplicacion_literal": "Posible coincidencia con otra facturación; revisar",
  "analysis_missing": "Análisis todavía no ejecutado",
  "control_not_recorded": "Control sin resultado registrado",
  "coincidencia_estricta_candidata": "Orden, afiliado, código y fecha repetidos en otra facturación",
  "sin_coincidencia_estricta": "Sin otra fila con la misma orden, afiliado, código y fecha",
  "referencia_economica_no_aplicable_aun": "Falta validar el valor del convenio para esta práctica",
  "referencia_arancelaria_insuficiente": "Falta una referencia arancelaria aplicable",
  "ordenes_validas_no_verificadas": "Control de órdenes todavía sin ejecutar",
  "importes_de_fila_sin_multiplicar": "Importes tomados de la fila, sin multiplicar por cantidad",
  "total_no_cero": "Este control sólo corresponde a importes cero",
  "fecha_en_periodo_confirmado": "Realizada dentro del mes de la factura",
  "facturacion_en_termino": "Facturación dentro de los 45 días",
  "facturacion_fuera_de_termino": "Facturación fuera de término",
  "cero_requiere_referencia_aplicable": "Importe cero: falta comprobar si corresponde",
  "codigo_no_valorizado_admite_cero": "El código admite importe cero según la regla declarada",
  "control_not_implemented": "Control documental sin implementar; aplicabilidad sin verificar",
  "requires_update": "Resultados afectados por cambios",
  "fecha_ilegible": "Fecha de realización ilegible o no informada; falta comprobar el mes",
  "ambito_no_identificado": "No se pudo identificar el ámbito de atención; falta aclararlo",
  "alcance_indeterminado": "No se pudo determinar si la práctica está dentro del alcance",
  "fuera_del_periodo": "La fecha de realización está fuera del período admitido",
  "internacion_fuera_de_alcance": "Internación fuera del alcance del prototipo",
  "tipo_no_reconocido": "Tipo de prestación por aclarar",
  "fecha_no_interpretable": "Fecha de realización por aclarar"
};
function closureReasonText(value) {
  const code=value===null || value===undefined?'':String(value);
  const label=Object.hasOwn(closureReasonLabels,code)?closureReasonLabels[code]:
    code?'Motivo sin etiqueta administrativa en esta versión':'Motivo no informado en esta captura';
  return code?`${label} · Código: ${code}`:label;
}
function resetClosure(options={}) {
  if(options.keepDrafts!==true)closureDrafts.clear();
  closureEpoch++;closureDownloadRevision=null;
  document.querySelector('#closure-content').replaceChildren();
  document.querySelector('#closure-download').disabled = true;
  document.querySelector('#export-provisional-button').disabled = false;
}
function closureContext() {
  const datasetId = selectedDataset?.id, batchId = document.querySelector('#invoice-batch').value;
  if (!datasetId || !batchId || currentRole === 'viewer') return null;
  return {datasetId,batchId,epoch:closureEpoch};
}
function closureCurrent(c) {
  const now=closureContext();
  return now && now.datasetId===c.datasetId && now.batchId===c.batchId && now.epoch===c.epoch;
}
function closureFailure(c,error,target) {
  if(!closureCurrent(c))return;
  if(error.status===401 || error.status===403){resetClosure();document.querySelector('#closure-content').textContent='Acceso revocado. Volvé a ingresar y comprobar permisos.';}
  else target.textContent=error.message+' · Consultá nuevamente antes de guardar.';
}
function closureBase(c) {return `/api/datasets/${c.datasetId}/batches/${c.batchId}`;}
async function loadClosurePreview(options={}) {
  resetClosure(options);
  const c=closureContext(),content=document.querySelector('#closure-content');
  if(!c){content.textContent='Seleccioná un conjunto y lote con permiso de revisión.';return;}
  content.textContent='Consultando condiciones de cierre…';
  try {
    const page=await request(closureBase(c)+'/closure-preview',{method:'POST'});
    if(!closureCurrent(c))return;
    renderClosure(page,c);
  } catch(error){if(closureCurrent(c))content.textContent=`No se preparó el cierre: ${error.message}`;}
}
function renderClosure(page,c) {
  const content=document.querySelector('#closure-content');content.replaceChildren();
  const summary=document.createElement('p');
  summary.textContent=page.state==='cerrada'?`Revisión ${page.ordinal??''} cerrada. La descarga reproduce la captura conservada.`:
    `${page.pending_alert_count} alertas pendientes · ${page.limitations.length} limitaciones compartidas · ${page.control_count} controles identificados.`;
  content.append(summary);
  const note=document.createElement('p');note.textContent=page.coverage_note;content.append(note);
  closureDownloadRevision=page.state==='cerrada'?page.revision_id:null;
  document.querySelector('#closure-download').disabled=page.state!=='cerrada';
  document.querySelector('#export-provisional-button').disabled=page.state==='cerrada';
  const coverage=document.createElement('p');
  coverage.textContent=`Cobertura: ${Object.entries(page.coverage_counts||{}).map(([k,v])=>`${k}: ${v}`).join(' · ')} · ${page.decision_count??0} decisiones registradas · ${page.proposal_version_count??0} versiones de propuestas · Total vigente al momento de la captura: ${page.current_proposal_total_ars===null || page.current_proposal_total_ars===undefined?'sin cuantificar':page.current_proposal_total_ars+' ARS'}. No aprueba débitos.`;
  content.append(coverage);
  if(page.medical_consultations){const note=document.createElement('p');const c=page.medical_consultations;note.textContent=`Consultas externas: ${c.consultation_ids.length}; respuestas registradas: ${c.response_ids.length}; sin respuesta: ${c.awaiting_response}. Se conservan en la salida; no resuelven alertas ni modifican importes.`;content.append(note);}
  if(page.rn14_simulations?.version_count){const simulation=document.createElement('p');simulation.textContent=`SIMULACIONES DEMO: ${page.rn14_simulations.current_count} vigentes, subtotal simulado ${page.rn14_simulations.current_simulated_total_ars ?? 'por determinar'} ARS. Se conservan por separado y no integran el total real ni aprueban débitos.`;content.append(simulation);}
  if(page.state==='cerrada'){
    for(const group of page.limitations){
      const section=document.createElement('section'),heading=document.createElement('h4'),foundation=document.createElement('p');
      heading.textContent=`${group.rule_codes.join(', ')} · ${closureReasonText(group.reason_code)} · ${group.control_count} controles`;
      foundation.textContent=group.justification?.foundation || 'Fundamento no disponible en esta captura histórica';
      section.append(heading,foundation);appendClosureMembers(section,page,group,c);content.append(section);
    }
    return;
  }
  if(page.processing_active){const p=document.createElement('p');p.textContent='Hay procesamiento activo. Esperá su finalización antes de cerrar.';content.append(p);}
  const confirmations=[];
  for(const group of page.limitations) {
    const section=document.createElement('section'),heading=document.createElement('h4');
    heading.textContent=`${group.rule_codes.join(', ')} · ${closureReasonText(group.reason_code)} · ${group.control_count} controles`;
    section.append(heading);appendClosureMembers(section,page,group,c);
    if(group.justification) {
      const p=document.createElement('p');p.textContent=group.justification.foundation;section.append(p);
      const label=document.createElement('label'),check=document.createElement('input');check.type='checkbox';
      label.append(check,document.createTextNode('Confirmo que esta limitación y su fundamento siguen vigentes para el alcance indicado.'));
      section.append(label);confirmations.push({check,id:group.justification.id});
    } else {
      if(group.legacy_reconfirmation_required){const warning=document.createElement('p');warning.textContent='Fundamento anterior conservado. El formato nuevo exige revisar el alcance y reconfirmarlo expresamente.';section.append(warning);}
      const form=document.createElement('form'),label=document.createElement('label'),input=document.createElement('textarea');
      label.textContent='Fundamento de la limitación compartida';input.value=closureDrafts.get(group.scope_sha256)||group.legacy_foundation||'';input.addEventListener('input',()=>closureDrafts.set(group.scope_sha256,input.value));input.required=true;input.minLength=10;input.maxLength=4000;label.append(input);
      const button=document.createElement('button');button.type='submit';button.textContent=group.legacy_reconfirmation_required?'Reconfirmar fundamento para el alcance actual':'Guardar fundamento para este alcance';
      const status=document.createElement('p');status.setAttribute('role','status');form.append(label,button,status);section.append(form);
      form.addEventListener('submit',async event=>{
        event.preventDefault();if(!closureCurrent(c)||button.disabled)return;button.disabled=true;
        try {
          await request(closureBase(c)+'/closure-limitations',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
            expected_dataset_version:page.dataset_version,expected_revision_version:page.revision_version,
            group_key:group.group_key,scope_sha256:group.scope_sha256,foundation:input.value})});
          if(closureCurrent(c)){closureDrafts.delete(group.scope_sha256);await loadClosurePreview({keepDrafts:true});}
        } catch(error){closureFailure(c,error,status);}
        finally {button.disabled=false;}
      });
    }
    content.append(section);
  }
  const confirm=document.createElement('button');confirm.type='button';confirm.textContent='Confirmar cierre de esta revisión';
  const status=document.createElement('p');status.setAttribute('role','status');
  function enabled(){confirm.disabled=!page.can_close || confirmations.some(x=>!x.check.checked);}
  for(const x of confirmations)x.check.addEventListener('change',enabled);
  enabled();content.append(confirm,status);
  confirm.addEventListener('click',async()=>{
    if(!closureCurrent(c)||confirm.disabled)return;confirm.disabled=true;
    try {
      await request(closureBase(c)+'/closure',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
        expected_dataset_version:page.dataset_version,expected_revision_version:page.revision_version,
        preview_sha256:page.preview_sha256,confirmed_limitation_ids:confirmations.filter(x=>x.check.checked).map(x=>x.id)})});
      if(closureCurrent(c))await loadClosurePreview();
    } catch(error){closureFailure(c,error,status);}
    // Uncertain responses never trigger an automatic second write.
  });
}
function appendClosureMembers(section,page,group,c){
  const button=document.createElement('button'),pane=document.createElement('div');button.type='button';button.textContent='Ver filas y controles de este alcance';section.append(button,pane);
  async function load(offset){
    if(!closureCurrent(c))return;button.disabled=true;pane.replaceChildren();
    const status=document.createElement('p');status.setAttribute('role','status');status.textContent='Consultando alcance…';pane.append(status);
    const params={group_key:group.group_key,scope_sha256:group.scope_sha256,offset,limit:50,
      expected_dataset_version:page.dataset_version,expected_revision_version:page.revision_version};
    if(page.state==='cerrada')params.revision_id=page.revision_id;
    const query=Object.entries(params).map(([k,v])=>encodeURIComponent(k)+'='+encodeURIComponent(v)).join('&');
    try{
      const data=await request(closureBase(c)+'/closure-members?'+query);
      if(!closureCurrent(c))return;pane.replaceChildren();
      const table=document.createElement('table');table.className='closure-scope-grid';
      const head=document.createElement('tr');for(const text of ['Fila Excel','Control','Resultado','Motivo']){const cell=document.createElement('th');cell.textContent=text;head.append(cell);}table.append(head);
      for(const item of data.items){const row=document.createElement('tr');for(const value of [item.source_row,item.rule_code,item.result,closureReasonText(item.reason_code)]){const cell=document.createElement('td');cell.textContent=String(value);row.append(cell);}table.append(row);}
      const count=document.createElement('p');count.textContent=`${data.total?data.offset+1:0}–${data.offset+data.items.length} de ${data.total} controles · ${data.frozen?'captura conservada':'alcance consultado'}`;
      const previous=document.createElement('button'),next=document.createElement('button');previous.type=next.type='button';previous.textContent='Página anterior del alcance';next.textContent='Página siguiente del alcance';
      previous.disabled=data.offset===0;next.disabled=data.offset+data.items.length>=data.total;
      previous.addEventListener('click',()=>load(Math.max(0,data.offset-data.limit)));next.addEventListener('click',()=>load(data.offset+data.limit));pane.append(table,count,previous,next);
    }catch(error){closureFailure(c,error,status);}finally{button.disabled=false;}
  }
  button.addEventListener('click',()=>load(0));
}
async function showFrozenClosure(revisionId){
  resetClosure();const c=closureContext();if(!c)return;
  try{const page=await request(closureBase(c)+'/closure-summary?revision_id='+encodeURIComponent(revisionId));if(closureCurrent(c))renderClosure(page,c);}
  catch(error){closureFailure(c,error,document.querySelector('#closure-content'));}
}
function initializeClosure() {
  document.querySelector('#closure-preview').addEventListener('click',loadClosurePreview);
  for(const id of ['invoice-dataset','invoice-batch','logout'])document.querySelector('#'+id).addEventListener(id==='logout'?'click':'change',resetClosure);
  document.querySelector('#closure-download').addEventListener('click',async()=>{
    const c=closureContext();if(!c)return;
    try {
      const response=await fetch(closureBase(c)+'/export-closed'+(closureDownloadRevision?'?revision_id='+encodeURIComponent(closureDownloadRevision):''),{credentials:'same-origin'});
      if(!response.ok)throw new Error((await response.json()).detail || 'No se pudo descargar el cierre');
      const blob=await response.blob();if(!closureCurrent(c))return;
      const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=`revision-${c.batchId}-closed.zip`;
      document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);
    } catch(error){if(closureCurrent(c)){resetClosure();document.querySelector('#closure-content').textContent=error.message;}}
  });
}

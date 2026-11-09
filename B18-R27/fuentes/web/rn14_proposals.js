/* RN25 decision and RN27 amount review are separate explicit actions. */
const rn14ReviewLabels={analysis_missing:'Primero ejecutá el análisis',closed_revision:'Revisión cerrada: historia conservada, sin recalcular',
  analysis_requires_update:'Los datos cambiaron; actualizá el análisis explícitamente',no_positive_rn14_difference:'No hay una diferencia positiva RN14 habilitada para este bloque',
  row_reference_missing:'Falta una referencia por fila vigente',captured_calculation_mismatch:'El cálculo conservado no concilia con su respaldo',
  invoice_original_unavailable:'El Excel original no se pudo verificar',finding_not_confirmed:'El indicio todavía no está confirmado con evidencia',
  other_components_require_review:'Hay otros componentes guardados; este bloque no los reemplaza',ready:'Cálculo disponible para revisión humana',
  current:'Importe revisado vigente',requires_update:'Importe afectado; requiere nueva revisión',not_current_by_decision:'Sin importe vigente por decisión descartada o no concluyente'};
function rn14ReviewLabel(code){return Object.hasOwn(rn14ReviewLabels,code)?rn14ReviewLabels[code]:`Estado sin etiqueta: ${code}`;}
function rn14AmountHistory(content,title,records) {
  const section=document.createElement('details'),heading=document.createElement('summary');heading.textContent=`${title} (${records.length})`;section.append(heading);
  for(const r of records){const p=r.payload_at_save;detailText(section,`${r.simulation_only?'SIMULACIÓN DEMO':'Propuesta de revisión'} · versión ${r.ordinal} · ${r.actor_username} · ${r.created_at}`,`Guardado ARS ${p.amount_ars} · ID ${r.id}`);
    if(p.basis?.decision_snapshot)detailText(section,'Decisión y fundamento conservados',`${p.basis.decision_snapshot.state} · ${p.basis.decision_snapshot.foundation} · ${p.basis.decision_snapshot.evidence_note || 'Sin evidencia adicional registrada'}`);
    for(const part of p.components || [])detailText(section,'Cálculo conservado',`Automático ARS ${part.automatic_amount_ars}; revisado ARS ${part.amount_ars}. ${part.adjustment_calculation || 'Sin ajuste manual'}. ${part.adjustment_reason || 'Se confirmó el cálculo disponible'}`);
  }content.append(section);
}
async function showRn14Proposal(sourceRow) {
  const content=sheetPanel(`Fila ${sourceRow} · revisión de importe RN14`),context=sheetContext();content.textContent='Consultando cálculo y decisiones…';
  try{
    const url=`/api/datasets/${context.datasetId}/batches/${context.batchId}/rows/${sourceRow}/rn14-proposal`;
    const p=await request(url);if(!sheetCurrent(context))return;content.replaceChildren();
    detailText(content,p.simulation_only?'SIMULACIÓN DEMO':'Propuesta de revisión',p.simulation_only?'Almacenamiento y salidas separados. No es una propuesta real ni integra sus totales.':'Sujeta a validación externa; no aplica un débito definitivo.');
    detailText(content,'Estado',rn14ReviewLabel(p.state));detailText(content,'Decisión RN14',decisionLabels[p.decision] || p.decision);
    if(p.decision_record){detailText(content,'Responsable y fecha de la decisión',`${p.decision_record.actor_username} · ${p.decision_record.created_at}`);detailText(content,'Fundamento de la decisión',p.decision_record.foundation);detailText(content,'Evidencia de la decisión',p.decision_record.evidence_note);}
    if(p.evidence){const evidence=document.createElement('pre');evidence.textContent=economicEvidenceText(p.evidence);content.append(evidence);}
    if(p.latest_evaluation){const e=p.latest_evaluation;detailText(content,'Última revisión de importe',rn14ReviewLabel(e.state));detailText(content,e.simulation_only?'Importe simulado vigente':'Importe propuesto vigente',e.simulation_only?(e.simulated_amount_ars ?? 'Por determinar'):(e.amount_ars ?? 'Por determinar'));}
    rn14AmountHistory(content,'Historia de propuestas reales',p.proposal_history);
    rn14AmountHistory(content,'Historia de simulaciones DEMO',p.simulation_history);
    if(p.revision_state==='cerrada')return;
    if(p.alert_id){const button=sheetButton('Revisar decisión RN14',()=>{
      if(!sheetCurrent(context))return;
      if(practicePage?.dataset_version!==p.dataset_version || practicePage?.batch.revision_version!==p.revision_version){detailText(content,'Actualizar','Volvé a cargar la planilla antes de elegir el aviso.');return;}
      const item=practicePage.items.find(i=>i.source_row===sourceRow),alert=item?.alerts.find(a=>a.id===p.alert_id);
      if(!alert){detailText(content,'Aviso','Volvé a consultar la fila en Planilla.');return;}
      clearSheetSelection();selectSheetAlert(alert,true);showSheetDecisionPreview();
    });content.append(button);}
    if(!p.can_save)return;
    const form=document.createElement('form');
    detailText(form,'Importe automático disponible',`ARS ${p.automatic_amount_ars}. Confirmarlo o ajustarlo no modifica el resultado del control ni la decisión RN14.`);
    const action=sheetField(form,'Tratamiento del importe','select');
    for(const [value,label] of [['confirm','Confirmar cálculo disponible'],['adjust','Ajustar con cálculo y fundamento']]){const option=document.createElement('option');option.value=value;option.textContent=label;action.append(option);}action.value='confirm';
    const amount=sheetField(form,'Importe ajustado ARS','input');amount.type='text';amount.inputMode='decimal';amount.maxLength=32;
    const calculation=sheetField(form,'Cálculo del ajuste');calculation.minLength=3;calculation.maxLength=2000;
    const reason=sheetField(form,'Fundamento del ajuste');reason.maxLength=2000;
    const adjustFields=()=>{for(const field of [amount,calculation,reason]){field.disabled=action.value!=='adjust';field.required=action.value==='adjust';}};action.addEventListener('change',adjustFields);adjustFields();
    const label=document.createElement('label'),ack=document.createElement('input');ack.type='checkbox';ack.required=true;label.append(ack,document.createTextNode('Revisé el cálculo y su respaldo. Esta acción no aprueba un débito definitivo.'));form.append(label);
    const submit=document.createElement('button');submit.type='submit';submit.textContent=p.simulation_only?'Guardar simulación DEMO':'Guardar propuesta de revisión';const status=document.createElement('p');status.setAttribute('role','status');form.append(submit,status);content.append(form);
    const writeState={};
    form.addEventListener('submit',async event=>{
      event.preventDefault();if(!ack.checked || !sheetCurrent(context))return;
      const body={expected_dataset_version:p.dataset_version,expected_revision_version:p.revision_version,preview_sha256:p.preview_sha256,action:action.value};
      if(action.value==='adjust')Object.assign(body,{adjusted_ars:amount.value,adjustment_calculation:calculation.value,adjustment_reason:reason.value});
      await settleSheetWrite({context,state:writeState,button:submit,status,content,
        send:()=>request(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}),
        refreshView:async()=>{await refreshProcessing({propagate:true});if(!sheetCurrent(context))return;await refreshSheetAfterWrite(context,p.simulation_only?'Simulación DEMO guardada con historia; no modifica totales reales ni ejecuta análisis.':'Propuesta guardada con historia; su validación definitiva es externa. No se ejecutó análisis.');},
        readHistory:async()=>{const current=await request(url);return [...current.proposal_history,...current.simulation_history].map(r=>({id:r.id,description:`${r.simulation_only?'SIMULACIÓN DEMO':'Propuesta'} · ${r.actor_username} · ${r.created_at} · ARS ${r.payload_at_save.amount_ars}. ${(r.payload_at_save.components || []).map(part=>`Automático ${part.automatic_amount_ars}; revisado ${part.amount_ars}. ${part.adjustment_calculation || 'Sin ajuste'} · ${part.adjustment_reason || 'Cálculo confirmado'}`).join(' ')}`}));}});
    });
  }catch(error){if(sheetCurrent(context))content.textContent=`No se pudo consultar: ${error.message}`;}
}

/* Documented HPC row reference. Saving never starts analysis or a proposal. */
const economicStatusLabels = {
  withdrawn_reference:'Arancel dado de baja para esta fecha; no se usa un precio anterior',
  status_evidence_unverifiable:'No se pudo verificar el respaldo del estado del arancel',
  ready_for_applicability:'Referencia candidata suficiente para documentar su aplicación',
  reference_source_unavailable:'Fuente de valores no disponible', outside_scope:'Prestación fuera del alcance de este control',
  hpc_provider_scope_missing:'Falta confirmar HPC y esta fuente para el lote en Convenios/valores',
  unsupported_value_identity_or_cut:'Código o corte de valores no compatible',
  ambiguous_reference:'Hay varias referencias compatibles; no se elige una por suposición',
  no_reference_for_code_and_date:'No se encontró una referencia suficiente para el código y la fecha',
  special_norm_or_calculation_requires_review:'Norma especial o cálculo fuera de este incremento',
  inconsistent_catalogue_formula:'La fórmula del catálogo no concilia',
  catalogue_amount_not_interpretable:'El importe original no es interpretable; revisar la fuente sin asignar cero',
  factor_observation_not_current_or_matching:'El cotejo del factor está afectado, difiere o es no concluyente',
  factor_evidence_missing:'Falta el cotejo documental del factor NBU en Convenios/valores',
  date_beyond_source_cut_without_version:'La fecha excede el corte documentado sin una nueva versión respaldada',
  value_version_unit_or_document_incompatible:'Unidad o respaldo de la versión incompatible',
  invalid_covered_quantity:'Cantidad cubierta no interpretable',
  fractional_cent_needs_rounding_rule:'Se necesita una regla de redondeo para fracciones de centavo',
  source_or_evidence_unverifiable:'No se pudo verificar la fuente o su evidencia',
  closed_reference_not_recorded:'La revisión se cerró sin una referencia aplicable registrada'
};
function economicStatus(code) {
  return `${Object.hasOwn(economicStatusLabels,code)?economicStatusLabels[code]:'Estado pendiente de interpretación'} · Código: ${code}`;
}
function economicEvidenceText(value) {
  const lines=[value.simulation_only?'DATOS FICTICIOS · ensayo económico':'Control económico documentado'];
  if(value.comparable_total_ars!==undefined) {
    lines.push(`Código facturado completo: ${value.code_complete}; equivalencia de valores HPC: ${value.value_code}`);
    lines.push(`ARS ${value.rate_ars} por práctica × ${value.covered_quantity} prácticas = ARS ${value.comparable_total_ars}`);
    lines.push(`Total facturado de fila ARS ${value.billed_total_ars} − comparable ARS ${value.comparable_total_ars} = diferencia ARS ${value.difference_ars}`);
    lines.push('El total facturado no se vuelve a multiplicar por cantidad. Tolerancia ARS 0,01.');
    lines.push(`Fecha: ${value.practice_date}. Fuente: ${value.source.id}; corte: ${value.source.cut_label}; SHA-256: ${value.source.source_sha256}`);
    lines.push(`Versión de valor: ${value.reference.value_version?.id || 'Original del catálogo'}; aplicabilidad: ${value.applicability_id}`);
    lines.push(`Convenio: ${value.agreement_document.original_name}; página ${value.confirmation.page_number}; SHA-256: ${value.agreement_document.sha256}`);
    lines.push(`Fragmento: ${value.confirmation.excerpt}`,`Fundamento: ${value.confirmation.note}`);
  } else lines.push(economicStatus(value.status || 'not_recorded'));
  lines.push('No confirma irregularidad, propuesta ni débito. La decisión de revisión es independiente.');
  return lines.join('\n');
}

async function showEconomicApplicability(sourceRow,sourceIdOverride=null) {
  const content=sheetPanel(`Fila ${sourceRow} · referencia económica HPC`),context=sheetContext();
  const sourceId=sourceIdOverride || document.querySelector('#value-source').value;
  if(!sourceId){detailText(content,'Referencia','Seleccioná una fuente en Convenios/valores.');return;}
  content.textContent='Consultando referencia e historia…';
  try {
    const url=`/api/datasets/${context.datasetId}/batches/${context.batchId}/rows/${sourceRow}/economic-applicability`;
    const data=await request(`${url}?source_id=${encodeURIComponent(sourceId)}`);
    if(!sheetCurrent(context))return;
    content.replaceChildren();
    detailText(content,'Estado',data.revision_state==='cerrada'?'Historia congelada; no se consulta el valor actual':economicStatus(data.basis.status));
    detailText(content,'Código',`${data.basis.code_complete} completo · ${data.basis.value_code ?? 'Sin equivalencia'} para valores`);
    detailText(content,'Fecha y cantidad',`${data.basis.practice_date} · ${data.basis.quantity} prácticas declaradas`);
    detailText(content,'Límite',data.use_limit);
    const currentReference=Boolean(data.latest?.current && data.latest?.matches_selected_source!==false);
    if(data.reference_display) {
      const ref=data.reference_display;
      detailText(content,data.revision_state==='cerrada'?'Importe histórico registrado':'Importe encontrado en convenio/catálogo',
        `${ref.recorded_amount ?? 'Importe no interpretable'}${ref.amount_status==='not_interpretable'?` (literal registrado: ${ref.recorded_amount_literal ?? 'sin dato'})`:''} · moneda declarada: ${ref.declared_currency ?? 'sin acreditar'} · unidad declarada: ${ref.declared_unit ?? 'sin acreditar'} · ${ref.provider} · código ${ref.code ?? data.basis.value_code} · ${ref.source_locator} · ${ref.value_version_id || 'Original del catálogo'}`);
      detailText(content,'Fuente del importe',`${ref.source_id ?? 'sin identificar'} · corte ${ref.source_cut ?? 'sin identificar'} · SHA-256 ${ref.source_sha256 ?? 'sin identificar'}`);
      if(ref.declaration_state==='historical_confirmation')detailText(content,'Declaración histórica','Moneda y unidad conservadas de la confirmación guardada; no constituyen aplicabilidad vigente.');
      detailText(content,'Vigencia de la referencia',`Desde ${ref.effective_from ?? 'sin determinar'} hasta ${ref.valid_until ?? 'sin fecha final declarada'}`);
      detailText(content,'Aplicabilidad del importe',ref.use_limit);
    }
    if(data.basis.candidate?.rate_ars && data.reference_display?.amount_status!=='not_interpretable') {
      const ref=data.reference_display;
      if(ref?.declared_currency && ref?.declared_unit) {
        detailText(content,'Tarifa evaluada',`${ref.declared_currency} ${data.basis.candidate.rate_ars} ${ref.declared_unit}. ${ref.declaration_state==='historical_confirmation'?'Declaración histórica conservada; no se recalcula ni se confirma vigencia.':currentReference?'Aplicabilidad confirmada para esta fila; ejecutar análisis explícito para obtener el control.':'Declaración registrada; todavía no confirmada para esta fila.'} No confirma un débito.`);
      } else detailText(content,'Importe candidato',`${data.basis.candidate.rate_ars} · moneda y unidad sin acreditar para esta fila. El cotejo del factor NBU no las confirma. No confirma un débito.`);
    }
    if(data.basis.status==='no_reference_for_code_and_date')detailText(content,'Revisión de autorización',
      'Sin valor de convenio determinable para esta fila. Revisar autorización y eventual presupuesto; no se presume que exista ni se asigna cero.');
    if(data.latest)detailText(content,'Último registro',`${data.latest.historical?'Histórico; sin recalcular':data.latest.state==='withdrawn'?'Retirado':data.latest.state==='unresolved'?'Referencia específica identificada; sin cuantificar':currentReference?'Aplicabilidad vigente; ejecutar análisis explícito':'Afectado; requiere nueva confirmación'} · versión ${data.latest.ordinal}`);
    const history=document.createElement('details'),summary=document.createElement('summary');summary.textContent=`Historia de esta revisión (${data.history.length})`;history.append(summary);
    for(const r of data.history)detailText(history,`Versión ${r.ordinal} · ${r.actor_username} · ${r.created_at}`,`${r.state} · ${r.confirmation.note} · ID ${r.id}`);
    content.append(history);
    if(data.revision_state==='cerrada'){detailText(content,'Revisión cerrada','Los resultados y referencias utilizados están en su captura de cierre; no se modifica su contenido.');return;}
    const writeState={};
    const write=(body,button,status)=>settleSheetWrite({context,state:writeState,button,status,content,
      send:()=>request(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_dataset_version:data.dataset_version,expected_revision_version:data.revision_version,source_id:sourceId,basis_sha256:data.basis_sha256,...body})}),
      refreshView:async()=>{await refreshProcessing({propagate:true});if(!sheetCurrent(context))return;await refreshSheetAfterWrite(context,'Aplicabilidad guardada con historia. No se ejecutó análisis ni se creó propuesta. Usá Actualizar análisis expresamente.');},
      readHistory:async()=>{const current=await request(`${url}?source_id=${encodeURIComponent(sourceId)}`);return current.history.map(r=>({id:r.id,description:`Versión ${r.ordinal} · ${r.actor_username} · ${r.created_at} · ${r.state}. ${r.confirmation.note}. ${r.confirmation.excerpt || ''}`}));}});
    if(data.latest && data.latest.state!=='withdrawn') {
      const withdrawal=document.createElement('form');detailText(withdrawal,'Retirar referencia','Conserva historia y deja sus resultados afectados, sin recalcularlos.');
      const note=sheetField(withdrawal,'Motivo del retiro');note.maxLength=2000;
      const button=document.createElement('button');button.type='submit';button.textContent='Retirar aplicabilidad';const status=document.createElement('p');withdrawal.append(button,status);content.append(withdrawal);
      withdrawal.addEventListener('submit',async e=>{e.preventDefault();await write({state:'withdrawn',note:note.value},button,status);});
    }
    if(!data.documents.length)return;
    const form=document.createElement('form');detailText(form,'Alcance','Sólo referencia general HPC en ARS por práctica y cantidad completa, sin adicionales ni normas especiales. Un acuerdo específico aceptado y aplicable prevalece cuando se identifica.');
    const state=sheetField(form,'Qué documentar','select');
    const allowGeneral=data.basis.status==='ready_for_applicability' && data.latest?.state!=='unresolved';
    for(const [value,text] of [...(allowGeneral?[['confirmed','Confirmar aplicación de la referencia general']]:[]),['unresolved','Registrar una referencia específica aceptada; sin cuantificar']]){const option=document.createElement('option');option.value=value;option.textContent=text;state.append(option);}
    state.value=allowGeneral?'confirmed':'unresolved';
    const doc=sheetField(form,'Convenio registrado','select');doc.required=true;
    for(const d of data.documents){const option=document.createElement('option');option.value=d.id;option.textContent=`${d.original_name} · SHA ${d.sha256}`;doc.append(option);}
    const page=sheetField(form,'Página del convenio','input');page.type='number';page.min='1';page.max='10000';page.required=true;
    const excerpt=sheetField(form,'Fragmento que respalda ARS, unidad y condiciones');excerpt.maxLength=2000;
    const quantity=sheetField(form,'Cantidad cubierta por esta referencia','input');quantity.value=data.basis.quantity;quantity.required=true;quantity.maxLength=64;
    const through=sheetField(form,'Cobertura documental comprobada hasta','input');through.type='date';through.required=true;through.value=data.basis.practice_date;
    const scopeFields=()=>{quantity.required=state.value==='confirmed';through.required=state.value==='confirmed';};state.addEventListener('change',scopeFields);scopeFields();
    detailText(form,'Vigencia','La cobertura comprobada no es una fecha de vencimiento contractual. No se presume caducidad por faltar fecha final.');
    const note=sheetField(form,'Fundamento de aplicación a esta fila');note.maxLength=2000;
    const label=document.createElement('label'),confirm=document.createElement('input');confirm.type='checkbox';confirm.required=true;label.append(confirm,document.createTextNode('Confirmo este registro documental, sin aprobar diferencias ni débitos.'));form.append(label);
    const button=document.createElement('button');button.type='submit';button.textContent='Guardar aplicabilidad sin analizar';const status=document.createElement('p');status.setAttribute('role','status');form.append(button,status);content.append(form);
    form.addEventListener('submit',async e=>{
      e.preventDefault();if(!confirm.checked || !sheetCurrent(context))return;
      await write({state:state.value,reference_kind:state.value==='unresolved'?'specific_accepted_reference':'general_hpc_base_no_additions',document_id:doc.value,page_number:Number(page.value),excerpt:excerpt.value,covered_quantity:quantity.value,currency:'ARS',billing_unit:'practice',coverage_through:through.value,note:note.value},button,status);
    });
  } catch(error){if(sheetCurrent(context))content.textContent=`No se pudo consultar: ${error.message}`;}
}

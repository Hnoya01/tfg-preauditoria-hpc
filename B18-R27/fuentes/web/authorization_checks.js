/* B03: explicit previews and append-only declarations, never control approval. */
async function showAuthorizationChecks(sourceRow) {
  const content=sheetPanel(`Fila ${sourceRow} · cantidades y fechas`),context=sheetContext();
  content.textContent='Comprobando vínculos, resoluciones y otras filas relacionadas…';
  try {
    const data=await request(`/api/datasets/${context.datasetId}/batches/${context.batchId}/rows/${sourceRow}/authorization-check-preview`);
    if(!sheetCurrent(context))return;
    content.replaceChildren();
    detailText(content,'Vista previa',data.mode==='synthetic_demo'?'DATOS FICTICIOS. Ensayo de comparaciones; no valida autorizaciones reales.':data.mode==='real_unvalidated'?'Fuente real sin validar. Las comparaciones no acreditan cobertura ni autorización real.':'Todavía no hay fuentes de autorizaciones seleccionadas para este lote.');
    detailText(content,'Alcance','No guarda resultados de controles, decisiones ni importes. Las capturas de análisis anteriores no cambian.');
    const labels={sin_observaciones:'La comparación no muestra diferencia',con_indicios:'Diferencia para revisar',no_concluyente:'Sin conclusión'};
    detailText(content,'Resolución declarada',`${declaredState(data.resolution.resolution?.status)}. ${data.resolution.reason}`);
    detailText(content,'Cantidades',`${labels[data.quantity.state]}. ${data.quantity.reason}`);
    detailText(content,'Autorizado declarado',`${data.quantity.authorized ?? 'Desconocido'} ${data.quantity.unit || '(unidad desconocida)'}`);
    detailText(content,'Facturado en conjunto',data.quantity.billed_joint ?? 'No se determina mientras haya información pendiente');
    const limitations={candidate_limit_1000:'Más de 1.000 filas posibles: se necesita procesamiento ampliado.',other_lot_scope_unresolved:'Otro lote relacionado no tiene fuentes vigentes seleccionadas.',coverage_identity_between_captures_unverified:'No está verificado que los ítems de distintas capturas sean la misma cobertura.',pending_or_ambiguous_association:'Hay una asociación ambigua, pendiente o desactualizada.',billed_quantity_or_unit_unverified:'Falta cantidad facturada interpretable o unidad declarada compatible.',related_identity_unresolved:'Otra fila del mismo código y fecha tiene identidad sin aclarar.',association_candidates_incomplete:'Las coincidencias de otra fila exceden la vista disponible: no se usa una lista recortada para concluir.'};
    for(const issue of data.quantity.limitations)detailText(content,'Pendiente',limitations[issue] || issue);
    if(data.quantity.members.length)authorizationTable(content,'Filas vinculadas (no asigna unidades)',[['Archivo','batch_name'],['Fila original','locator'],['Cantidad facturada','billed'],['Unidad declarada','unit']],data.quantity.members);
    detailText(content,'Secuencia temporal',`${labels[data.temporal.state]}. ${data.temporal.reason}`);
    for(const [key,label] of [['authorization','Autorización'],['incorporation','Incorporación al consolidado']]) {
      const t=data.temporal[key];const precision={day:'día',minute:'minuto',second:'segundo',fraction:'fracción de segundo',unknown:'desconocida'}[t.precision];
      detailText(content,label,`${t.original ?? 'Sin evidencia'} · precisión: ${precision} · zona: ${t.zone || 'no informada'}`);
    }
    detailText(content,'Unidades e importes','No se asignan unidades ni se calculan propuestas monetarias. Una declaración no acredita la fuente real.');
    for(const [kind,label] of [['incorporation','Incorporación al consolidado'],['quantity_unit','Unidad de la cantidad facturada']]) {
      const info=data.inputs[kind],history=document.createElement('details'),summary=document.createElement('summary');summary.textContent=`${label} · ${info.history.length} declaraciones`;history.append(summary);
      if(!info.current)detailText(history,'Sin dato','El Excel no aporta este dato con evidencia suficiente.');
      for(const entry of info.history)detailText(history,`v${entry.ordinal} · ${entry.actor_username} · ${entry.created_at}`,`${entry.state==='withdrawn'?'Retirada':entry.value} · ${entry.data_origin==='synthetic'?'FICTICIO':'Sin validar'} · ${entry.provenance} · ${entry.locator} · SHA-256 ${entry.record_sha256}`);
      content.append(history);
    }
    if(data.revision_state==='cerrada' || !data.mode)return;
    const details=document.createElement('details'),title=document.createElement('summary');title.textContent='Registrar o retirar un dato complementario';details.append(title);content.append(details);
    detailText(details,'Procedencia','Registrá sólo lo que expresa la fuente. Fecha de archivo, factura, realización o carga no sustituyen incorporación. La unidad no se deduce de la descripción.');
    const form=document.createElement('form');form.className='sheet-action-form';details.append(form);
    const kind=sheetField(form,'Dato a registrar','select');kind.append(new Option('Incorporación al consolidado','incorporation'),new Option('Unidad de la cantidad facturada','quantity_unit'));
    const state=sheetField(form,'Acción sobre el dato','select');state.append(new Option('Registrar declaración sin validar','declared'),new Option('Retirar declaración anterior','withdrawn'));
    const value=sheetField(form,'Valor declarado (fecha ISO o unidad literal)','input');value.required=true;value.maxLength=100;
    state.addEventListener('change',()=>{value.required=state.value==='declared';value.disabled=state.value==='withdrawn';});
    const provenance=sheetField(form,'Fuente y procedencia del dato');provenance.maxLength=2000;
    const locator=sheetField(form,'Localizador en esa fuente','input');locator.required=true;locator.minLength=3;locator.maxLength=300;
    const submit=document.createElement('button');submit.type='submit';submit.textContent='Guardar declaración con historia';const status=document.createElement('p');status.setAttribute('role','status');form.append(submit,status);
    let busy=false;
    form.addEventListener('submit',async event=>{
      event.preventDefault();if(busy || !sheetCurrent(context))return;busy=true;submit.disabled=true;
      try {
        await request(`/api/datasets/${context.datasetId}/batches/${context.batchId}/rows/${sourceRow}/authorization-input`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_version:data.dataset_version,expected_revision_version:data.revision_version,kind:kind.value,state:state.value,value:state.value==='withdrawn'?null:value.value,provenance:provenance.value,locator:locator.value})});
        await refreshSheetAfterWrite(context,'Declaración guardada. No se ejecutó análisis ni se validó la fuente. Volvé a abrir Cantidades y fechas para consultar la vista actual.');
      } catch(error){if(sheetCurrent(context))status.textContent=`No se guardó: ${error.message}. El texto sigue aquí; no se reintenta automáticamente.`;}
      finally{busy=false;if(sheetCurrent(context))submit.disabled=false;}
    });
  } catch(error){if(sheetCurrent(context))content.textContent=`No se pudo consultar: ${error.message}`;}
}

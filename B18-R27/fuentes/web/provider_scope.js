/* Explicit admin confirmation of HPC. No automatic confirmation or analysis. */
let hpcScopeEpoch=0,hpcScopeSending=false;
const hpcScopeUncertain=new Set();
function hpcScopeContext(){return {epoch:++hpcScopeEpoch,datasetId:selectedDataset?.id,
  batchId:document.querySelector('#invoice-batch').value,sourceId:document.querySelector('#value-source').value};}
function hpcScopeCurrent(c){return c.epoch===hpcScopeEpoch && c.datasetId===selectedDataset?.id &&
  c.batchId===document.querySelector('#invoice-batch').value && c.sourceId===document.querySelector('#value-source').value && currentRole && currentRole!=='viewer';}
function resetHpcScope(){hpcScopeEpoch++;document.querySelector('#hpc-scope-content').replaceChildren();}
async function showHpcScope(editUnit=false){
  if(hpcScopeSending)return;
  const context=hpcScopeContext(),content=document.querySelector('#hpc-scope-content');content.replaceChildren();
  if(!context.datasetId || !context.batchId || !context.sourceId || !currentRole || currentRole==='viewer'){
    content.textContent='Seleccioná un lote importado y una fuente de valores; se requiere acceso de revisión.';return;
  }
  const url=`/api/datasets/${context.datasetId}/batches/${context.batchId}/provider-scope`;
  content.textContent='Consultando alcance HPC…';
  try {
    const data=await request(url);if(!hpcScopeCurrent(context))return;content.replaceChildren();
    const batchLabel=document.querySelector('#invoice-batch').selectedOptions?.[0]?.textContent || context.batchId;
    const sourceLabel=document.querySelector('#value-source').selectedOptions?.[0]?.textContent || context.sourceId;
    detailText(content,'Factura y fuente',`${batchLabel} · período ${data.period ?? 'consultar factura'} · ${sourceLabel}`);
    detailText(content,'Identificadores',`${context.batchId} · ${context.sourceId}`);
    const matches=data.current?.provider==='HPC' && data.current?.source_id===context.sourceId;
    detailText(content,'Alcance',matches?'HPC confirmado para este lote y esta fuente.':
      data.current?'La confirmación anterior no corresponde a HPC y esta fuente seleccionada.':'Falta confirmar HPC para este lote y esta fuente.');
    detailText(content,'Límite','La unidad facturada puede documentarse para el lote; moneda, unidad del arancel y condiciones se comprueban por referencia. No acredita equivalencia clínica ni ejecuta análisis o débitos.');
    const history=document.createElement('details'),summary=document.createElement('summary');summary.textContent=`Historia (${data.history.length})`;history.append(summary);
    for(const item of data.history)detailText(history,`Versión ${item.ordinal} · ${item.created_at}`,
      `${item.provider} · fuente ${item.source_id} · ${item.confirmation_note}`);
    content.append(history);
    if(data.revision_state==='cerrada'){detailText(content,'Revisión cerrada','Alcance histórico; no se modifica.');return;}
    if(currentRole!=='admin'){detailText(content,'Permiso','La confirmación corresponde al administrador.');return;}
    if(matches && editUnit!==true){
      detailText(content,'Unidad de facturación',data.current.billing_unit==='practice'?'Prácticas, declaración documentada del administrador. No acredita cobertura ni equivalencia clínica.':'Sin verificar. La comparación de códigos relacionados no calcula diferencias hasta documentar unidades comparables.');
      const edit=document.createElement('button');edit.type='button';edit.textContent='Documentar o modificar unidad del lote';edit.addEventListener('click',()=>showHpcScope(true));content.append(edit);return;
    }
    const operationKey=`${context.datasetId}:${context.batchId}:${context.sourceId}`;
    if(hpcScopeUncertain.has(operationKey)){
      detailText(content,'Guardado incierto','La historia consultada todavía no confirma este alcance. No se reenvía automáticamente. Un reintento usará versiones frescas; si el intento anterior se confirma entretanto, el servidor rechazará la versión desactualizada.');
      const retry=document.createElement('button');retry.type='button';retry.textContent='Preparar reintento con versiones actualizadas';
      retry.addEventListener('click',async()=>{if(!hpcScopeCurrent(context) || hpcScopeSending)return;hpcScopeUncertain.delete(operationKey);await showHpcScope();});
      content.append(retry);return;
    }
    const form=document.createElement('form'),note=sheetField(form,'Fundamento del alcance HPC');
    note.value='La facturación de este lote corresponde exclusivamente a HPC; se utiliza la fuente de convenio seleccionada.';
    note.maxLength=2000;
    const label=document.createElement('label'),check=document.createElement('input');check.type='checkbox';check.required=true;
    label.append(check,document.createTextNode('Confirmo HPC como único prestador de este lote y la fuente indicada.'));form.append(label);
    const unitLabel=document.createElement('label'),unitCheck=document.createElement('input');unitCheck.type='checkbox';
    unitLabel.append(unitCheck,document.createTextNode('Declaro que la cantidad G de este lote está expresada en prácticas, no en U.B., horas u otras unidades. Sin declaración se conserva sin verificar.'));form.append(unitLabel);
    const unitNote=sheetField(form,'Respaldo de la unidad facturada: documento/ubicación y fundamento (mínimo20caracteres)');unitNote.maxLength=800;unitNote.required=false;

    const button=document.createElement('button');button.type='submit';button.textContent='Confirmar alcance HPC';
    const status=document.createElement('p');status.setAttribute('role','status');form.append(button,status);content.append(form);
    let busy=false,locked=false;
    form.addEventListener('submit',async event=>{
      event.preventDefault();if(busy || locked || !check.checked || !hpcScopeCurrent(context) || currentRole!=='admin')return;
      if(unitCheck.checked && (unitNote.value.trim().length<20 || note.value.trim().length>1000)){status.textContent='Indicá respaldo de la unidad (20 a800caracteres) y fundamento general de hasta1000caracteres.';return;}
      busy=true;hpcScopeSending=true;button.disabled=true;note.disabled=true;check.disabled=true;unitCheck.disabled=true;unitNote.disabled=true;
      try {
        const result=await request(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
          source_id:context.sourceId,provider:'HPC',billing_unit:unitCheck.checked?'practice':'unverified',billing_unit_note:unitCheck.checked?unitNote.value:null,confirmation_note:note.value,
          expected_dataset_version:data.dataset_version,expected_revision_version:data.revision_version})});
        locked=true;if(!hpcScopeCurrent(context))return;
        selectedDataset.version=result.dataset_version;
        status.textContent='HPC confirmado con historia. No se ejecutó análisis ni se confirmó un importe. Volvé a abrir la referencia económica para continuar.';
      } catch(error){
        if(!hpcScopeCurrent(context))return;
        if(error.status===401 || error.status===403){locked=true;content.replaceChildren();content.textContent='Sesión vencida o acceso revocado.';}
        else if(error.status && error.status<500){status.textContent=`No se guardó: ${error.message}. Tu fundamento se conserva; consultá de nuevo el alcance si cambió la revisión.`;}
        else {locked=true;hpcScopeUncertain.add(operationKey);status.textContent='Resultado incierto: no se reenviará. Usá Ver o confirmar alcance HPC para consultar la historia antes de otra acción.';}
      } finally {busy=false;hpcScopeSending=false;if(hpcScopeCurrent(context)){button.disabled=locked;note.disabled=locked;check.disabled=locked;unitCheck.disabled=locked;unitNote.disabled=locked;}}
    });
  }catch(error){if(hpcScopeCurrent(context))content.textContent=`No se pudo consultar el alcance: ${error.message}. No se modificó nada.`;}
}
document.querySelector('#hpc-scope-open').addEventListener('click',showHpcScope);
for(const id of ['invoice-dataset','invoice-batch','value-source'])document.querySelector(`#${id}`).addEventListener('change',resetHpcScope);

/* C2: explicit successors and revision-specific frozen downloads. */
let revisionsEpoch=0;
function resetRevisions(){revisionsEpoch++;document.querySelector('#revisions-content').replaceChildren();}
function revisionsContext(){
  if(!selectedDataset?.id || currentRole==='viewer')return null;
  const batchId=document.querySelector('#invoice-batch').value;
  return batchId?{datasetId:selectedDataset.id,batchId,epoch:revisionsEpoch}:null;
}
function revisionsCurrent(c){const now=revisionsContext();return now && now.datasetId===c.datasetId && now.batchId===c.batchId && now.epoch===c.epoch;}
function revisionsBase(c){return `/api/datasets/${c.datasetId}/batches/${c.batchId}`;}
function revisionsFailure(c,error,status){
  if(!revisionsCurrent(c))return;
  if(error.status===401 || error.status===403){resetRevisions();document.querySelector('#revisions-content').textContent='Acceso revocado. Volvé a ingresar.';}
  else status.textContent=error.message+' · Consultá otra vez el historial antes de guardar.';
}
async function loadRevisions(){
  resetRevisions();const c=revisionsContext(),content=document.querySelector('#revisions-content');
  if(!c){content.textContent='Seleccioná un conjunto y lote con permiso de revisión.';return;}
  content.textContent='Consultando revisiones…';
  try{const page=await request(revisionsBase(c)+'/revisions');if(revisionsCurrent(c))renderRevisions(page,c);}
  catch(error){revisionsFailure(c,error,content);}
}
function renderRevisions(page,c){
  const content=document.querySelector('#revisions-content');content.replaceChildren();
  const summary=document.createElement('p');summary.textContent=`${page.items.length} revisiones · Revisión actual ${page.items.find(x=>x.current)?.ordinal}: ${page.state}.`;content.append(summary);
  for(const item of page.items){
    const section=document.createElement('section'),heading=document.createElement('h4');heading.textContent=`Revisión ${item.ordinal} · ${item.state}`;section.append(heading);
    if(item.reason){const note=document.createElement('p'),previous=page.items.find(x=>x.id===item.previous_revision_id);note.textContent=`Motivo: ${item.reason}`+(previous?` · Anterior: revisión ${previous.ordinal}`:'');section.append(note);}
    if(item.opening_basis){const note=document.createElement('p');note.textContent=`${item.opening_basis.historical_decision_ids.length} decisiones anteriores conservadas como historia; ninguna heredada como vigente. Los controles de esta revisión requieren análisis explícito.`;section.append(note);}
    if(item.archive_sha256 && document.querySelector('#invoice-batch').selectedOptions?.[0]?.dataset.auditWorkflow==='1'){
      for(const [label,path] of [['PDF de observaciones','/observations.pdf'],['Excel del auditor','/handoff/audit/excel']]) {
        if(path.endsWith('excel') && page.invoice_duty!=='auditor')continue;
        const link=document.createElement('a');link.href=revisionsBase(c)+path+'?revision_id='+encodeURIComponent(item.id);link.textContent=label;section.append(link,document.createTextNode(' '));
      }
    }
    if(item.archive_sha256){
      const view=document.createElement('button');view.type='button';view.textContent=`Ver resumen congelado de revisión ${item.ordinal}`;section.append(view);
      view.addEventListener('click',()=>{if(revisionsCurrent(c))showFrozenClosure(item.id);});
      const button=document.createElement('button');button.type='button';button.textContent=`Descargar cierre de revisión ${item.ordinal}`;
      const status=document.createElement('p');status.setAttribute('role','status');section.append(button,status);
      button.addEventListener('click',async()=>{
        if(!revisionsCurrent(c)||button.disabled)return;button.disabled=true;
        try{
          const response=await fetch(revisionsBase(c)+'/export-closed?revision_id='+encodeURIComponent(item.id),{credentials:'same-origin'});
          if(!response.ok)throw Object.assign(new Error((await response.json()).detail || 'No se pudo descargar'),{status:response.status});
          const blob=await response.blob();if(!revisionsCurrent(c))return;
          const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=`revision-${item.id}-closed.zip`;
          document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);
        }catch(error){revisionsFailure(c,error,status);}finally{button.disabled=false;}
      });
    }
    content.append(section);
  }
  if(page.state!=='cerrada'){const note=document.createElement('p');note.textContent='Ya existe una revisión abierta. Trabajá en ella y solicitá Actualizar análisis cuando corresponda.';content.append(note);return;}
  if(page.invoice_duty==='auditor' && document.querySelector('#invoice-batch').selectedOptions?.[0]?.dataset.auditWorkflow==='1')return;
  const form=document.createElement('form'),label=document.createElement('label'),reason=document.createElement('textarea');
  label.textContent='Motivo de la nueva revisión';reason.required=true;reason.minLength=10;reason.maxLength=2000;label.append(reason);
  const confirmation=document.createElement('label'),check=document.createElement('input');check.type='checkbox';
  confirmation.append(check,document.createTextNode('Entiendo que parte del Excel original. Correcciones, selecciones de fuentes, vínculos, declaraciones, decisiones y limitaciones deben confirmarse de nuevo. El cierre anterior queda intacto.'));
  const button=document.createElement('button');button.type='submit';button.textContent='Iniciar nueva revisión del mismo lote';button.disabled=true;
  check.addEventListener('change',()=>{button.disabled=!check.checked;});
  const status=document.createElement('p');status.setAttribute('role','status');form.append(label,confirmation,button,status);content.append(form);
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(!revisionsCurrent(c)||button.disabled)return;button.disabled=true;
    try{
      await request(revisionsBase(c)+'/revisions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
        previous_revision_id:page.revision_id,expected_dataset_version:page.dataset_version,
        expected_revision_version:page.revision_version,reason:reason.value})});
      if(!revisionsCurrent(c))return;
      await refresh();await loadRevisions();
    }catch(error){revisionsFailure(c,error,status);}
    // No automatic repeat on a lost response or conflict.
  });
}
function initializeRevisions(){
  document.querySelector('#revisions-load').addEventListener('click',loadRevisions);
  for(const id of ['invoice-dataset','invoice-batch','logout'])document.querySelector('#'+id).addEventListener(id==='logout'?'click':'change',resetRevisions);
}

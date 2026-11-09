/* Native local identities. No automatic inference, analysis, or debit. */
const localNode=id=>document.querySelector(`#local-hpc-${id}`);
let localEpoch=0,localSaving=false;
function resetLocalHpc(){localEpoch++;for(const id of ['id','code','description','amount','unit','currency'])localNode(id).value='';for(const id of ['code','description','family'])localNode(id).disabled=false;localNode('family').value='unclassified';localNode('active').value='true';localNode('result').textContent='';}
function localPayload(){return {expected_dataset_version:selectedDataset.version,practice_id:localNode('id').value||null,
 code:localNode('code').value,description:localNode('description').value,family:localNode('family').value,
 amount_ars:localNode('amount').value,currency:localNode('currency').value,unit_label:localNode('unit').value,
 active:localNode('active').value==='true',effective_from:document.querySelector('#hpc-value-from').value,
 document_id:document.querySelector('#hpc-value-document').value,page_number:Number(document.querySelector('#hpc-value-page').value),
 excerpt:document.querySelector('#hpc-value-excerpt').value,reason:document.querySelector('#hpc-value-reason').value};}
async function loadLocalHpc(){
 const dataset=selectedDataset?.id,source=document.querySelector('#value-source').value,epoch=++localEpoch;
 if(!dataset||!source)return;
 const query=localNode('query').value;
 try{
  const rows=await request(`/api/datasets/${dataset}/sources/${source}/local-hpc${query?'?query='+encodeURIComponent(query):''}`);
  if(epoch!==localEpoch||selectedDataset?.id!==dataset||document.querySelector('#value-source').value!==source)return;
  localNode('list').replaceChildren();
  for(const p of rows){
   const item=document.createElement('section'),title=document.createElement('p');title.textContent=`${p.code} · ${p.description} · ${p.family} · UUID ${p.id}`;item.append(title);
   const history=document.createElement('pre');history.textContent=p.versions.map(v=>`Versión ${v.ordinal} · ${v.active?'activa':'baja'} desde ${v.effective_from} · ARS ${v.amount_ars} ${v.unit_label} · PDF SHA ${v.document_sha256} página ${v.page_number} · ${v.actor_username}\n${v.excerpt}\n${v.reason}`).join('\n\n');item.append(history);
   if(currentRole==='admin'){const button=document.createElement('button');button.type='button';button.textContent='Editar importe / baja / reactivar';button.addEventListener('click',()=>{
    if(localSaving)return;const v=p.versions.at(-1);localNode('id').value=p.id;for(const key of ['code','description','family']){localNode(key).value=p[key];localNode(key).disabled=true;}
    localNode('amount').value=v.amount_ars;localNode('unit').value=v.unit_label;localNode('currency').value='ARS';localNode('active').value=v.active?'true':'false';
    localNode('result').textContent='Identidad conservada. Indicá nuevo inicio y respaldo en el formulario de convenio.';
   });item.append(button);}localNode('list').append(item);
  }
 }catch(error){if(epoch===localEpoch)localNode('result').textContent=error.message;}
}
localNode('load').addEventListener('click',loadLocalHpc);
localNode('new').addEventListener('click',()=>{if(!localSaving)resetLocalHpc();});
document.querySelector('#value-source').addEventListener('change',()=>{resetLocalHpc();localNode('list').replaceChildren();});
localNode('form').addEventListener('submit',async event=>{
 event.preventDefault();if(localSaving||!selectedDataset||currentRole!=='admin')return;
 const dataset=selectedDataset.id,source=document.querySelector('#value-source').value,payload=localPayload();if(!source)return;
 localSaving=true;localNode('save').disabled=true;
 try{
  const result=await request(`/api/datasets/${dataset}/sources/${source}/local-hpc`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  if(selectedDataset?.id!==dataset)return;
  if(selectedDataset.version===payload.expected_dataset_version)selectedDataset.version=result.dataset_version;
  if(document.querySelector('#value-source').value!==source)return;
  resetLocalHpc();await loadLocalHpc();localNode('result').textContent=`Guardada versión ${result.ordinal}, UUID ${result.id}. No se ejecutaron controles ni decisiones.`;
 }catch(error){if(selectedDataset?.id===dataset)localNode('result').textContent=error.message;}
 finally{localSaving=false;localNode('save').disabled=false;}
});

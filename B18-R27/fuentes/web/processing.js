/* B-PROG: persistent attempt polling; no automatic analysis/retry on navigation. */
let processingEpoch=0,processingTimer=null,processingContext=null,processingPending=null,processingSending=false;
const processingSeenActive=new Set(),processingNotified=new Set();
const processingStates={queued:'En espera',running:'En ejecución',completed:'Terminado',failed:'No pudo completarse',interrupted:'Interrumpido',blocked:'Requiere un análisis nuevo'};
const processingStages={queued:'Esperando inicio',validating:'Comprobando datos y acceso',preparing:'Preparando comparaciones',evaluating:'Ejecutando controles',publishing:'Publicando la captura completa',completed:'Captura disponible'};

function initializeProcessing() {
  document.querySelector('#analyze-button').addEventListener('click',startProcessing);
  document.querySelector('#processing-refresh').addEventListener('click',refreshProcessing);
  for(const id of ['invoice-dataset','invoice-batch'])document.querySelector(`#${id}`).addEventListener('change',resetProcessing);
}

function resetProcessing() {
  processingEpoch++;if(processingTimer)clearTimeout(processingTimer);processingTimer=null;
  processingContext=null;processingPending=null;processingSending=false;processingSeenActive.clear();processingNotified.clear();
  document.querySelector('#processing-status').textContent='Elegí un lote importado.';
  document.querySelector('#processing-history').replaceChildren();document.querySelector('#processing-progress').hidden=true;
  document.querySelector('#processing-count').textContent='';document.querySelector('#processing-message').textContent='';
  document.querySelector('#analyze-button').disabled=true;document.querySelector('#analyze-button').textContent='Analizar lote';
}

function processingKey() {return `${selectedDataset?.id || ''}:${document.querySelector('#invoice-batch').value}`;}
function processingBase(datasetId,batchId) {return `/api/datasets/${datasetId}/batches/${batchId}/processing-attempts`;}
function processingStill(context) {return context.key===processingKey() && currentRole && currentRole!=='viewer';}
function processingDate(value) {return value?new Date(value).toLocaleString('es-AR',{timeZone:'America/Argentina/Buenos_Aires',hour12:false}):'Sin iniciar';}

async function refreshProcessing({propagate=false}={}) {
  if(processingTimer)clearTimeout(processingTimer);processingTimer=null;
  const datasetId=selectedDataset?.id,batchId=document.querySelector('#invoice-batch').value;
  if(!datasetId || !batchId || currentRole==='viewer'){resetProcessing();return;}
  const context={datasetId,batchId,key:processingKey()},epoch=++processingEpoch;
  try {
    const data=await request(processingBase(datasetId,batchId));
    if(epoch!==processingEpoch || !processingStill(context))return;
    processingContext={...context,data};renderProcessing(data);
    const active=data.items.filter(i=>i.state==='queued' || i.state==='running');
    for(const job of active)processingSeenActive.add(job.id);
    const completed=data.items.find(i=>i.state==='completed' && processingSeenActive.has(i.id) && !processingNotified.has(i.id));
    if(completed){processingNotified.add(completed.id);void refreshCompletedProcessing(context,completed);}
    if(active.length)processingTimer=setTimeout(refreshProcessing,1000);
  } catch(error) {
    if(epoch!==processingEpoch || !processingStill(context))return;
    if(error.status===401 || error.status===403){resetProcessing();document.querySelector('#processing-status').textContent='La sesión venció o ya no tenés permiso para este conjunto.';if(propagate)throw error;return;}
    document.querySelector('#processing-status').textContent=`No se pudo consultar el estado: ${error.message}. Actualizá para volver a consultar.`;
    document.querySelector('#analyze-button').disabled=!processingPending;
    // A caller that already committed a write must be able to report a pending view.
    if(propagate)throw error;
    // Failed reads never turn into automatic POST retries.
  }
}

function renderProcessing(data) {
  const latest=data.items[0],active=data.items.some(i=>i.state==='queued' || i.state==='running');
  const button=document.querySelector('#analyze-button');
  button.textContent=processingPending?'Reenviar la misma solicitud':'Analizar lote';
  button.disabled=processingSending || data.revision_state==='cerrada' || (active && !processingPending);
  const bar=document.querySelector('#processing-progress');bar.hidden=!latest;
  if(!latest){document.querySelector('#processing-status').textContent='Sin intentos de seguimiento. Las capturas anteriores siguen disponibles en Análisis.';document.querySelector('#processing-count').textContent='';}
  else {
    let status=`${processingStates[latest.state]} · ${processingStages[latest.stage] || latest.stage}`;
    if(latest.state==='completed' && latest.result_created===0)status='Terminado · este intento reutilizó una captura; no repitió resultados';
    if(latest.error_message)status+=`. ${latest.error_message}`;
    document.querySelector('#processing-status').textContent=(data.synthetic_data?'FICTICIO · ':'')+status;
    const measured=['evaluating','publishing','completed'].includes(latest.stage) && latest.total_rows!==null && latest.total_rows>0 && latest.result_created!==0;
    if(measured){bar.max=latest.total_rows;bar.value=latest.processed_rows;}else bar.removeAttribute('value');
    if(latest.state==='completed' || latest.state==='failed' || latest.state==='blocked' || latest.state==='interrupted')bar.hidden=true;
    document.querySelector('#processing-count').textContent=(latest.result_created===0?'Sin recálculo de filas.':`${latest.processed_rows.toLocaleString('es-AR')} de ${latest.total_rows===null?'total aún no determinado':latest.total_rows.toLocaleString('es-AR')} filas preparadas.`)+
      ` Última actividad: ${processingDate(latest.heartbeat_at || latest.created_at)}.`;
  }
  const body=document.querySelector('#processing-history');body.replaceChildren();
  document.querySelector('#processing-history-label').textContent=`Historial · ${data.items.length} ${data.has_more?'últimos intentos (hay anteriores)':data.items.length===1?'intento':'intentos'}`;
  const parents=new Set(data.items.map(i=>i.previous_id).filter(Boolean));
  for(const job of data.items) {
    const row=document.createElement('tr');
    for(const text of [`${processingDate(job.created_at)} · ${job.actor_username || 'Usuario registrado'}`,processingStates[job.state],processingStages[job.stage] || job.stage,
      `${job.processed_rows}/${job.total_rows ?? '?'}`,`${job.id.slice(0,8)}${job.previous_id?' ← '+job.previous_id.slice(0,8):''}`]){
      const cell=document.createElement('td');cell.textContent=text;row.append(cell);
    }
    const action=document.createElement('td');
    if(job.can_retry && !parents.has(job.id)) {
      const retry=document.createElement('button');retry.type='button';retry.textContent='Reintentar este intento';retry.className='secondary';
      retry.disabled=processingSending || (processingPending && processingPending.path!==processingBase(processingContext.datasetId,processingContext.batchId)+'/'+job.id+'/retry');
      retry.addEventListener('click',()=>{retry.disabled=true;retryProcessing(job);});action.append(retry);
    } else if(parents.has(job.id))action.textContent='Tiene un reintento posterior';
    else if(job.state==='interrupted' || job.state==='failed' || job.state==='blocked')action.textContent='Revisá datos/acceso e iniciá un análisis nuevo';
    else if(job.result_run_id){const link=document.createElement('button');link.type='button';link.className='secondary';link.textContent='Ver captura';link.addEventListener('click',()=>showProcessingResult(job));action.append(link);}
    if(job.error_message){const note=document.createElement('span');note.className='processing-error';note.textContent=job.error_message;action.append(note);}
    row.append(action);body.append(row);
  }
}

async function startProcessing() {
  if(processingPending){await submitProcessing(processingPending);return;}
  if(!processingContext || !processingStill(processingContext) || processingSending)return;
  const context=processingContext;
  await submitProcessing({...context,path:processingBase(context.datasetId,context.batchId),body:{
    expected_dataset_version:context.data.dataset_version,expected_revision_version:context.data.revision_version,request_key:crypto.randomUUID()}});
}

async function retryProcessing(job) {
  if(!processingContext || !processingStill(processingContext) || processingSending)return;
  const context=processingContext,path=processingBase(context.datasetId,context.batchId)+'/'+job.id+'/retry';
  if(processingPending && processingPending.path!==path){document.querySelector('#processing-message').textContent='Hay una solicitud sin recepción confirmada. Reenviá esa misma solicitud antes de iniciar otra.';return;}
  await submitProcessing(processingPending || {...context,path,body:{expected_attempt_version:job.version,request_key:crypto.randomUUID()}});
}

async function submitProcessing(submission) {
  if(processingSending || !processingStill(submission))return;
  processingPending=submission;processingSending=true;
  document.querySelector('#analyze-button').disabled=true;
  try {
    const job=await request(submission.path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(submission.body)});
    if(!processingStill(submission))return;
    processingPending=null;processingSeenActive.add(job.id);
    document.querySelector('#processing-message').textContent=job.state==='completed'?'Esta solicitud ya terminó. Se conserva su resultado.':'Solicitud recibida. Podés cambiar de sección o recargar; el intento queda registrado.';
  } catch(error) {
    if(!processingStill(submission))return;
    if(error.status>=400 && error.status<500)processingPending=null;
    document.querySelector('#processing-message').textContent=processingPending
      ?'No se pudo confirmar la recepción. Reenviar la misma solicitud conserva su identificador y no duplica resultados.'
      :`${error.message}. Actualizá el estado antes de intentar otra acción.`;
  } finally {
    if(processingStill(submission)){processingSending=false;await refreshProcessing();}
  }
}

async function refreshCompletedProcessing(context,job) {
  try {
    const datasets=await request('/api/datasets');if(!processingStill(context))return;
    selectedDataset=datasets.find(d=>d.id===context.datasetId);await refreshRuns();
    if(!processingStill(context))return;await refreshAlerts();
    document.querySelector('#processing-message').textContent=job.result_created?'Captura publicada completa. Revisá sus avisos y limitaciones.':'Este intento reutilizó una captura existente. Consultá su vigencia actual en los resultados.';
  } catch(error){if(processingStill(context))document.querySelector('#processing-message').textContent=`El intento terminó; falta actualizar los resultados en pantalla: ${error.message}`;}
}

async function showProcessingResult(job) {
  const context=processingContext;if(!context || !processingStill(context))return;
  try {await refreshRuns();if(!processingStill(context))return;document.querySelector('#control-run').value=job.result_run_id;await showRun(job.result_run_id);}
  catch(error){if(processingStill(context))document.querySelector('#processing-message').textContent=error.message;}
}

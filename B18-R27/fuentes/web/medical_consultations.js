/* External correspondence is recorded by reviewers; no medical login or automatic action. */
const correspondencePending = new Map();
let correspondenceOwner = null;
function resetMedicalConsultations() { correspondencePending.clear();correspondenceOwner=null; }
function correspondenceSession() {
  const owner=typeof csrfToken==='undefined'?null:csrfToken;
  if(owner!==correspondenceOwner){resetMedicalConsultations();correspondenceOwner=owner;}
  return owner;
}
if(typeof window!=='undefined')window.addEventListener('beforeunload',event=>{
  if(correspondencePending.size){event.preventDefault();event.returnValue='';}
});
async function showMedicalConsultations(sourceRow, drafts={}) {
  const content=sheetPanel(`Fila ${sourceRow} · consultas y respuestas externas`),context=sheetContext();
  const owner=correspondenceSession();
  const current=()=>sheetCurrent(context) && correspondenceSession()===owner;
  const prefix=JSON.stringify([context.datasetId,context.batchId,sourceRow]);
  const operationKey=(revision,key)=>JSON.stringify([prefix,revision,key]);
  const pending=(revision,key)=>correspondencePending.get(operationKey(revision,key));
  content.textContent='Consultando historial…';
  const url=`/api/datasets/${context.datasetId}/batches/${context.batchId}/rows/${sourceRow}/consultations`;
  try {
    const page=await request(url);if(!current())return;
    content.replaceChildren();
    detailText(content,'Alcance','Registro de intercambios externos. No envía mensajes, no resuelve alertas y no cambia autorizaciones ni importes.');
    detailText(content,'Historia','Los registros se conservan sin editar. Una aclaración o corrección se agrega como otra respuesta.');
    const open=page.revision_state!=='cerrada';
    for(const item of page.items) {
      const section=document.createElement('details'),title=document.createElement('summary');
      title.textContent=`Revisión ${item.revision_ordinal} · ${item.responses.length?'Con respuesta registrada':'Sin respuesta registrada'} · ${item.created_at}`;
      section.append(title);
      detailText(section,`Consulta de ${item.actor_username}`,item.question);
      detailText(section,'ID de consulta',item.id);
      const original=item.context.original_fields || {};
      detailText(section,'Prestación al consultar',`Código original ${original.E || 'sin código'} · ${original.K || 'sin descripción'}`);
      const trace=document.createElement('details'),traceTitle=document.createElement('summary'),raw=document.createElement('pre');
      traceTitle.textContent='Ver contexto conservado';raw.textContent=JSON.stringify(item.context,null,2);trace.append(traceTitle,raw);section.append(trace);
      for(const answer of item.responses) {
        detailText(section,`Respuesta de ${answer.author_name} · ${answer.responded_at}`,answer.response);
        detailText(section,'Procedencia',`${answer.channel} · ${answer.provenance}`);
        detailText(section,'Registro en el sistema por',`${answer.registrar_username} · ${answer.created_at}`);
      }
      if((open && item.revision_id===page.revision_id) || pending(item.revision_id,item.id)) {
        const form=correspondenceForm(section,'Registrar respuesta externa',item.id);
        correspondenceInput(form,'author_name','Emisor externo (nombre informado)','input',200);
        const date=correspondenceInput(form,'responded_at','Fecha de recepción informada (hora local)','input',80);date.type='datetime-local';date.step='1';
        const channel=correspondenceInput(form,'channel','Medio externo','select');
        for(const [value,label] of [['email','Correo'],['phone','Teléfono'],['document','Documento'],['other','Otro']]){const option=document.createElement('option');option.value=value;option.textContent=label;channel.append(option);}
        correspondenceInput(form,'provenance','Referencia del intercambio o documento (sin adjuntar archivos)','textarea',2000);
        correspondenceInput(form,'response','Respuesta o aclaración externa','textarea',4000);
        bind(form,`${url}/${item.id}/responses`,item.revision_id);
      } else if(item.revision_id!==page.revision_id)detailText(section,'Antecedente','Revisión anterior: sólo lectura. Para una respuesta posterior, registrá una consulta en la revisión actual e identificá este antecedente.');
      content.append(section);
    }
    if(!page.items.length)detailText(content,'Estado','Sin consultas registradas para esta prestación.');
    if(page.creation_block_reason==='internacion_fuera_de_alcance')detailText(content,'Internación fuera de alcance','No se permiten consultas nuevas. Se conserva el historial existente.');
    if((open && page.can_create_consultation) || pending(page.revision_id,'new')){const form=correspondenceForm(content,'Registrar consulta','new');correspondenceInput(form,'question','Consulta al auditor médico','textarea',4000);bind(form,url);}
    for(const operation of correspondencePending.values())if(operation.prefix===prefix && operation.key==='new' && operation.revision!==page.revision_id){
      const form=correspondenceForm(content,'Comprobar consulta de revisión anterior','new');
      correspondenceInput(form,'question','Consulta al auditor médico','textarea',4000);bind(form,url,operation.revision);
    }
    if(!open)detailText(content,'Cierre','Sólo lectura. Una respuesta posterior requiere abrir expresamente otra revisión del lote.');
    function bind(form,target,revision=page.revision_id) {
      const key=operationKey(revision,form.draftKey);
      let operation=correspondencePending.get(key);
      for(const [key,input] of Object.entries(form.fields)){if(drafts[form.draftKey]?.[key]!==undefined)input.value=drafts[form.draftKey][key];}
      const button=document.createElement('button');button.type='submit';button.textContent=form.title;
      const status=document.createElement('p');status.setAttribute('role','status');form.append(button,status);
      let body=operation?.body || null,finished=false;
      form.operationState=()=>operation;
      if(operation){
        for(const [key,input] of Object.entries(form.fields)){input.value=operation.fields[key];input.disabled=true;}
        status.textContent='Resultado pendiente de comprobar. Se conserva la operación exacta, sin editarla ni crear otra.';
        button.textContent='Comprobar / repetir la misma operación';
      }
      function saved(){
        finished=true;button.disabled=true;status.textContent='Registro guardado. Actualizá el historial para continuar.';
        form.append(sheetButton('Actualizar historial',()=>showMedicalConsultations(sourceRow,collect(form.draftKey))));
      }
      form.addEventListener('submit',async event=>{
        event.preventDefault();if(operation?.busy || finished || !current())return;
        if(operation?.outcome==='saved'){saved();return;}
        if(operation?.outcome==='rejected'){finished=true;button.disabled=true;status.textContent='La operación fue rechazada. Actualizá y revisá el borrador antes de guardar.';form.append(sheetButton('Actualizar conservando borradores',()=>showMedicalConsultations(sourceRow,collect())));return;}
        if(!body){
          body={expected_dataset_version:page.dataset_version,expected_revision_version:page.revision_version,revision_id:page.revision_id,request_id:crypto.randomUUID()};
          for(const [key,input] of Object.entries(form.fields))body[key]=input.value;
          if(body.responded_at){const date=new Date(body.responded_at);if(Number.isNaN(date.getTime())){body=null;status.textContent='Completá una fecha válida.';return;}body.responded_at=date.toISOString();}
        }
        if(!operation){operation={prefix,revision,key:form.draftKey,body,fields:Object.fromEntries(Object.entries(form.fields).map(([k,input])=>[k,input.value])),busy:false};correspondencePending.set(key,operation);}
        const sentOperation=operation;
        operation.busy=true;button.disabled=true;for(const input of Object.values(form.fields))input.disabled=true;
        try {
          await request(target,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
          operation.outcome='saved';if(correspondencePending.get(key)===operation)correspondencePending.delete(key);
          if(!current())return;
          saved();
        } catch(error) {
          const rejected=error.status && error.status<500;
          if(rejected){operation.outcome='rejected';if(correspondencePending.get(key)===operation)correspondencePending.delete(key);}
          if(!current())return;
          if(error.status===401 || error.status===403){resetMedicalConsultations();finished=true;content.replaceChildren();content.textContent='Acceso revocado o sesión vencida.';return;}
          if(error.status===409){finished=true;status.textContent=`${error.message}. Conservamos tu texto; actualizá y revisá antes de volver a guardar.`;form.append(sheetButton('Actualizar conservando borradores',()=>showMedicalConsultations(sourceRow,collect())));}
          else if(error.status && error.status<500){body=null;operation=null;status.textContent=error.message;for(const input of Object.values(form.fields))input.disabled=false;}
          else {status.textContent='Resultado incierto. Podés repetir la misma operación para comprobarla sin duplicar el registro.';button.textContent='Comprobar / repetir la misma operación';}
        } finally {sentOperation.busy=false;if(current())button.disabled=finished;}
      });
    }
    function collect(exclude) {
      const result={};for(const form of content.querySelectorAll('form'))if(form.draftKey!==exclude && (!form.operationState?.() || form.operationState().outcome==='rejected'))result[form.draftKey]=Object.fromEntries(Object.entries(form.fields).map(([key,input])=>[key,input.value]));return result;
    }
  } catch(error){if(current()){if(error.status===401 || error.status===403)resetMedicalConsultations();content.textContent=`No se pudo consultar: ${error.message}`;}}
}
function correspondenceForm(parent,title,key){const form=document.createElement('form');form.fields={};form.title=title;form.draftKey=key;const heading=document.createElement('h4');heading.textContent=title;form.append(heading);parent.append(form);return form;}
function correspondenceInput(form,key,label,kind,maximum){const input=sheetField(form,label,kind);input.required=true;if(maximum)input.maxLength=maximum;form.fields[key]=input;return input;}

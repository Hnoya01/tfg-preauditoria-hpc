/* Private PDFs, not clinical validation or structured authorization imports. */
const rowDocumentPending = new Map();
let rowDocumentOwner = null;
function documentSession() {
  const owner=typeof csrfToken==='undefined'?null:csrfToken;
  if(owner!==rowDocumentOwner){rowDocumentPending.clear();rowDocumentOwner=owner;}
  return owner;
}
function rowDocumentLabel(state) {
  return ({no_aportado:'No aportado',aportado_sin_revisar:'Aportado, sin revisión manual',revisado_manualmente:'Lectura manual registrada'})[state] || 'Sin consultar';
}
function renderRowDocuments(cell,item) {
  const wrapper=document.createElement('div');
  for(const [category,label] of [['informe','Informe PDF'],['autorizacion','Autorización PDF']]) {
    const button=sheetButton(`${label}: ${rowDocumentLabel(item.documents?.[category]?.state)}`,()=>showRowDocuments(item.source_row));
    button.title='Estado del PDF vinculado para lectura manual, separado de A1. No aportado no significa que no exista el documento ni que la prestación no se haya realizado; no acredita autorización ni cumplimiento clínico.';
    button.setAttribute('aria-label',`${label} de ${item.locator || `fila ${item.source_row}`}: ${rowDocumentLabel(item.documents?.[category]?.state)}`);
    wrapper.append(button);
  }
  cell.append(wrapper);
}

// A human reading aid, not an automated control or a confirmed documentary link.
const documentaryDimensions = [
  ['identity','Identidad'],['date','Fecha'],['study','Estudio'],
  ['region','Región'],['quantity','Cantidad'],['contrast','Mención de contraste']
];
const documentaryStates = {
  not_evaluated:'No evaluado', compatible:'Compatible según lectura manual',
  discrepancy:'Discrepancia para revisar', inconclusive:'No concluyente'
};
function documentaryReviewNote(answers, comment) {
  const lines=['COTEJO DOCUMENTAL MANUAL · no ejecuta RN20–RN22 ni confirma vínculo.'];
  let evaluated=0;
  for(const [key,label] of documentaryDimensions) {
    const answer=answers[key] || {},state=answer.state || 'not_evaluated';
    if(!Object.prototype.hasOwnProperty.call(documentaryStates,state))throw Error('Estado de cotejo inválido');
    const evidence=String(answer.evidence || '').trim(),page=String(answer.page || '').trim();
    if(evidence.length>180)throw Error(`${label}: limitá la evidencia a 180 caracteres`);
    if(state!=='not_evaluated') {
      if(!/^[1-9]\d{0,4}$/.test(page))throw Error(`${label}: indicá la página del PDF en el campo separado (entero positivo)`);
      if(evidence.length<10)throw Error(`${label}: indicá la evidencia observada (mínimo 10 caracteres)`);
      evaluated++;
    }
    lines.push(`${label}: ${documentaryStates[state]}${page ? ' · Página PDF '+page : ''}${evidence ? ' · '+evidence : ''}`);
  }
  if(!evaluated)throw Error('Registrá al menos una dimensión leída; las demás pueden quedar no evaluadas');
  comment=String(comment || '').trim();
  if(comment.length>250)throw Error('La observación general admite hasta 250 caracteres');
  if(comment)lines.push('Observación: '+comment);
  lines.push('La mención de contraste no acredita cantidad ni importe. Omisión o discrepancia no prueban prestación no realizada.');
  const note=lines.join('\n');
  if(note.length>2000)throw Error('La constancia supera 2000 caracteres; resumí la evidencia sin quitar sus localizadores');
  return note;
}
function documentaryReviewForm(field, form) {
  const inputs={};
  for(const [key,label] of documentaryDimensions) {
    const state=field(form,label,'select');
    for(const [value,text] of Object.entries(documentaryStates)) {
      const option=document.createElement('option');option.value=value;option.textContent=text;state.append(option);
    }
    state.value='not_evaluated';
    const page=field(form,`${label}: página del PDF (obligatoria si se evaluó)`,'input');
    page.type='number';page.min='1';page.max='99999';page.step='1';page.required=false;
    const evidence=field(form,`${label}: evidencia observada (sin datos personales innecesarios)`,'textarea');
    evidence.required=false;evidence.maxLength=180;
    state.addEventListener('change',()=>{page.required=evidence.required=state.value!=='not_evaluated';});
    inputs[key]={state,evidence,page};
  }
  const comment=field(form,'Observación general opcional','textarea');comment.required=false;comment.maxLength=250;
  return ()=>documentaryReviewNote(Object.fromEntries(Object.entries(inputs).map(([key,value])=>[key,{state:value.state.value,evidence:value.evidence.value,page:value.page.value}])),comment.value);
}

async function showRowDocuments(sourceRow) {
  const content=sheetPanel(`Fila ${sourceRow} · PDF aportados`),context=sheetContext(),owner=documentSession();
  const current=()=>sheetCurrent(context)&&documentSession()===owner;
  const url=`/api/datasets/${context.datasetId}/batches/${context.batchId}/rows/${sourceRow}/documents`;
  try {
    const page=await request(url);if(!current())return;
    detailText(content,'Límite',page.use_limit);
    detailText(content,'Seguridad','Archivos originales privados, descarga para revisión manual. No se ejecuta OCR ni análisis clínico. Un PDF puede contener contenido activo: abrilo sólo con un lector actualizado.');
    for(const item of page.items) {
      const section=document.createElement('section');
      detailText(section,item.category,`${item.original_name} · ${rowDocumentLabel(item.state)}`);
      detailText(section,'Origen',`${item.provenance} · registrado por ${item.actor_username} · ${item.created_at}`);
      detailText(section,'SHA-256',item.sha256);
      const link=document.createElement('a');link.href=`/api/datasets/${context.datasetId}/row-documents/${item.id}/file`;
      link.textContent='Descargar original';link.download='documento-aportado.pdf';section.append(link);
      for(const entry of item.reviews) {
        const reading=document.createElement('div');reading.className='document-reading-note';
        detailText(reading,`Lectura de ${entry.actor_username} · ${entry.created_at}`,entry.note);section.append(reading);
      }
      if(page.writable) {
        const form=document.createElement('form'),note=field(form,'Constancia de lectura manual (no dictamen clínico)','textarea');note.minLength=10;
        bind(form,`${url}/${item.id}/reviews`,async()=>({body:{...versions(),note:note.value},headers:{'Content-Type':'application/json'},json:true}),`review:${item.id}`);
        section.append(form);
        if(item.category==='informe') {
          const guided=document.createElement('details'),heading=document.createElement('summary');
          heading.textContent='Cotejo guiado del informe (lectura humana)';guided.append(heading);
          detailText(guided,'Alcance','Cotejá cada dimensión por separado con la factura. Ante varios candidatos, texto ilegible o duda, elegí No concluyente. No confirma un vínculo ni modifica alertas, RN20–RN22, A1 o decisiones. La falta de mención de contraste no prueba que no se administró.');
          const guidedForm=document.createElement('form'),prepareNote=documentaryReviewForm(field,guidedForm);
          bind(guidedForm,`${url}/${item.id}/reviews`,async()=>({body:{...versions(),note:prepareNote()},headers:{'Content-Type':'application/json'},json:true}),`guided-review:${item.id}`);
          guided.append(guidedForm);section.append(guided);
        }
      }
      content.append(section);
    }
    if(page.writable) {
      const form=document.createElement('form'),category=field(form,'Tipo de documento','select');
      for(const [value,label] of [['informe','Informe'],['autorizacion','Autorización PDF (no importación A1)']]){const option=document.createElement('option');option.value=value;option.textContent=label;category.append(option);}
      const file=field(form,'PDF original, máximo 10 MiB','input');file.type='file';file.accept='.pdf,application/pdf';
      const provenance=field(form,'Procedencia y vínculo con esta fila','textarea');provenance.minLength=10;
      bind(form,url,async()=>{
        const selected=file.files[0];if(!selected||selected.size>10*1024*1024)throw Error('Elegí un PDF de hasta 10 MiB');
        const bytes=await selected.arrayBuffer(),hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');
        // Headers require Latin-1; encode human metadata as URI components, decoded server-side.
        return {body:bytes,headers:{'Content-Type':'application/pdf','X-Expected-Version':String(page.dataset_version),
          'X-Revision-Version':String(page.revision_version),'X-Revision-Id':page.revision_id,'X-Request-Id':crypto.randomUUID(),
          'X-Document-Category':category.value,'X-Source-Filename':encodeURIComponent(selected.name),
          'X-Provenance-Note':encodeURIComponent(provenance.value),'X-Expected-SHA256':hash}};
      },'upload');content.append(form);
    } else detailText(content,'Revisión cerrada','Sólo lectura. Para aportar documentos posteriores, abrí una nueva revisión.');
    function versions(){return {expected_dataset_version:page.dataset_version,expected_revision_version:page.revision_version,revision_id:page.revision_id,request_id:crypto.randomUUID()};}
    function field(form,label,tag){const wrapper=document.createElement('label'),input=document.createElement(tag);wrapper.textContent=label;input.required=true;if(tag==='textarea')input.maxLength=2000;wrapper.append(input);form.append(wrapper);return input;}
    function bind(form,target,prepare,key) {
      const identity=JSON.stringify([url,key]),button=document.createElement('button'),status=document.createElement('p');button.type='submit';button.textContent='Registrar';form.append(button,status);
      let busy=false,done=false;
      if(rowDocumentPending.has(identity)){form.noValidate=true;button.textContent='Comprobar / repetir operación pendiente';status.textContent='Se conservará el contenido exacto enviado. No se crea otra operación.';}
      form.addEventListener('submit',async event=>{
        event.preventDefault();if(busy||done||!current())return;busy=true;button.disabled=true;
        try {
          let operation=rowDocumentPending.get(identity);
          if(!operation){operation=await prepare();if(!current())return;rowDocumentPending.set(identity,operation);}
          const response=await request(target,{method:'POST',headers:operation.headers,body:operation.json?JSON.stringify(operation.body):operation.body});
          rowDocumentPending.delete(identity);done=true;
          if(!current())return;
          selectedDataset.version=response.dataset_version;
          status.textContent='Guardado. No modifica controles ni decisiones.';
          form.append(sheetButton('Actualizar historial',()=>showRowDocuments(sourceRow)));
        } catch(error) {
          if(!current())return;
          if([401,403,404].includes(error.status)){rowDocumentPending.clear();content.replaceChildren();content.textContent='Acceso no disponible; datos retirados de la vista.';done=true;return;}
          if(error.status>=400 && error.status<500 && ![408,429].includes(error.status)){rowDocumentPending.delete(identity);done=true;form.append(sheetButton('Actualizar y corregir',()=>showRowDocuments(sourceRow)));}
          status.textContent=`${error.message}. Si el resultado es incierto, repetí la misma operación o consultá el historial.`;
          button.textContent='Comprobar / repetir la misma operación';
        } finally {busy=false;if(current())button.disabled=done;}
      });
    }
  } catch(error){if(current())detailText(content,'No se pudo cargar',error.message);}
}

if(typeof window!=='undefined')window.addEventListener('beforeunload',event=>{if(rowDocumentPending.size){event.preventDefault();event.returnValue='';}});

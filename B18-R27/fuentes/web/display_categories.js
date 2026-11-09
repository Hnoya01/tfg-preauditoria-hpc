/* Display-only classification from an operator-verified nomenclature row. */
function showCategoryRegistration(item,options={}) {
  const previous=options.previous;
  const action=previous?'Corregir categoría':'Registrar categoría';
  const panel=sheetPanel(action), context=sheetContext();
  const batchId=options.batchId || context.batchId;
  const version=options.version ?? practicePage.dataset_version, revision=options.revision ?? practicePage.batch.revision_version;
  detailText(panel,'Práctica',item.code+' · '+(item.description || 'Sin descripción'));
  const form=document.createElement('form');form.className='sheet-action-form';
  const family=sheetField(form,'Categoría según el nomenclador','select');
  family.append(new Option('Elegir categoría',''),new Option('Imágenes','images'),new Option('Otras prácticas','other'));
  family.required=true;
  let reason=null;
  if(previous){
    detailText(panel,'Categoría actual',previous.area+' · versión '+previous.ordinal);
    reason=sheetField(form,'Motivo de la corrección');reason.maxLength=2000;
  }
  const file=sheetField(form,'Nomenclador (.xlsx)','input');file.type='file';file.accept='.xlsx';file.required=true;
  const sheet=sheetField(form,'Hoja del nomenclador','input');sheet.required=true;sheet.maxLength=31;
  const cell=sheetField(form,'Celda del código','input');cell.placeholder='Por ejemplo, A2';cell.pattern='[A-Za-z]{1,3}[1-9][0-9]{0,6}';cell.required=true;
  const submit=document.createElement('button');submit.type='submit';submit.textContent=action;
  const status=document.createElement('p');status.setAttribute('role','status');form.append(submit,status);panel.append(form);
  form.addEventListener('submit',async event=>{
    event.preventDefault();
    if(submit.disabled || !sheetCurrent(context))return;
    const book=file.files[0];if(!book)return;
    submit.disabled=true;status.textContent='Verificando el código en el nomenclador…';
    const [,letters,row]=cell.value.toUpperCase().match(/^([A-Z]{1,3})([1-9][0-9]*)$/);
    const column=Array.from(letters).reduce((n,ch)=>26*n+ch.charCodeAt(0)-64,0);
    let saved=false;
    try {
      const result=await request(`/api/datasets/${context.datasetId}/batches/${batchId}/rows/${item.source_row}/display-category`,
        {method:'POST',body:book,headers:{'X-Dataset-Version':String(version),'X-Revision-Version':String(revision),
          ...(previous?{'X-Category-Version':String(previous.ordinal),'X-Correction-Reason':encodeURIComponent(reason.value)}:{}),
          'X-Practice-Code':encodeURIComponent(item.code),'X-Family':family.value,'X-Sheet':encodeURIComponent(sheet.value),
          'X-Evidence-Row':row,'X-Evidence-Column':String(column),'X-Source-Filename':encodeURIComponent(book.name)}});
      saved=true;
      if(!sheetCurrent(context))return;
      closeSheetReview();
      await loadPracticeBoard();
      if(selectedDataset?.id===context.datasetId && document.querySelector('#invoice-batch').value===context.batchId){
        const notice=document.querySelector('#category-feedback');notice.hidden=false;
        notice.textContent=(previous?'Corrección guardada':'Categoría registrada')+' · '+result.code+'.';
      }
    }catch(error){
      if(!sheetCurrent(context))return;
      status.textContent=saved?'Categoría registrada. Actualizá la bandeja.':String(error.message);
      submit.disabled=saved;
    }
  });
}

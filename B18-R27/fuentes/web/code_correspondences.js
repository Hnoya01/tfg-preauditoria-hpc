/* Reusable code relations and units. Only the administrator writes changes. */
let codeMapEpoch=0;
const relationLabels={direct:'Misma práctica',family:'Familia de prácticas',component:'Adicional',qualifier:'Atributo de la orden'};
function correspondenceUnit(item){
  if(item.relation_kind==='qualifier')
    return item.qualifier_kind==='projections'?item.qualifier_value+' exposiciones':'Atributo';
  if(item.relation_kind==='component')
    return {exposure:'Por exposición',side:'Por lado',area:'Por área',procedure:'Por procedimiento'}[item.billing_unit];
  return item.billing_unit==='side'?item.factor+' lado(s) por estudio':'Por práctica';
}
async function showCodeCorrespondences(){
  const epoch=++codeMapEpoch,dataset=selectedDataset?.id,source=document.querySelector('#value-source').value;
  const content=document.querySelector('#code-map-content');content.replaceChildren();
  if(!dataset || !source || !currentRole || currentRole==='viewer'){content.textContent='Seleccioná una factura y su fuente de convenio.';return;}
  content.textContent='Consultando correspondencias…';
  const current=()=>epoch===codeMapEpoch && dataset===selectedDataset?.id && source===document.querySelector('#value-source').value;
  const url='/api/datasets/'+dataset+'/sources/'+source+'/code-correspondences';
  try{
    const data=await request(url);if(!current())return;
    content.replaceChildren();
    const note=document.createElement('p');
    note.textContent=data.can_edit?'Revisá el tipo de relación y la unidad antes de registrar. Los cambios se conservan en el historial.':
      'Correspondencias registradas por el administrador.';
    content.append(note);
    const filters=document.createElement('div'),type=document.createElement('select'),query=document.createElement('input');
    query.placeholder='Código o práctica';query.setAttribute('aria-label','Buscar correspondencia');
    type.setAttribute('aria-label','Tipo de correspondencia');
    for(const [value,label] of [['','Todas'],...Object.entries(relationLabels)])type.append(new Option(label,value));
    filters.append(type,query);content.append(filters);
    const table=document.createElement('table'),head=table.createTHead().insertRow();
    for(const label of ['Usar','Tipo','Código factura','Código relacionado','Descripción relacionada','Unidad','Estado']){
      const th=document.createElement('th');th.textContent=label;head.append(th);
    }
    const choices=[];
    for(const item of data.items){
      const row=table.insertRow(),input=document.createElement('input');input.type='checkbox';input.checked=item.active;input.disabled=!data.can_edit;
      input.setAttribute('aria-label','Usar '+item.invoice_code+' con '+item.authorization_code);
      row.insertCell().append(input);
      const related=item.relation_kind==='component'?'Principal '+item.parent_code:item.authorization_code;
      for(const value of [relationLabels[item.relation_kind],item.invoice_code,related,item.authorization_description,
          correspondenceUnit(item),item.active?'Registrada':item.confirmation?'Retirada o por revisar':'Por verificar'])row.insertCell().textContent=value;
      row.title=item.invoice_description+'. '+item.locator;
      choices.push({row,item,input});
    }
    content.append(table);
    const applyFilter=()=>{
      const search=query.value.trim().toLocaleLowerCase();
      for(const {row,item} of choices)
        row.hidden=!!((type.value && type.value!==item.relation_kind) ||
          (search && ![item.invoice_code,item.authorization_code,item.invoice_description,item.authorization_description].join(' ').toLocaleLowerCase().includes(search)));
    };
    type.addEventListener('change',applyFilter);query.addEventListener('input',applyFilter);
    if(!choices.length)note.textContent='Cargá la factura y el CSV para revisar las correspondencias de esta fuente.';
    if(data.can_edit && choices.length){
      const mark=document.createElement('button');mark.type='button';mark.textContent='Marcar visibles';
      mark.addEventListener('click',()=>{for(const choice of choices)if(!choice.row.hidden)choice.input.checked=true;});filters.append(mark);
      const reason=sheetField(content,'Respaldo y motivo de los cambios');reason.minLength=10;reason.maxLength=2000;
      const save=document.createElement('button');save.type='button';save.textContent='Guardar correspondencias';
      const status=document.createElement('p');status.setAttribute('role','status');content.append(save,status);
      save.addEventListener('click',async()=>{
        if(!current())return;
        const changed=choices.filter(c=>c.item.active!==c.input.checked);
        if(!changed.length){status.textContent='Las correspondencias ya están guardadas.';return;}
        if(reason.value.trim().length<10){status.textContent='Indicá dónde verificaste los códigos y las unidades.';reason.focus();return;}
        save.disabled=true;mark.disabled=true;
        for(const c of choices)c.input.disabled=true;
        try{
          const result=await request(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
            expected_version:data.dataset_version,reason:reason.value,
            changes:changed.map(({item,input})=>({invoice_code:item.invoice_code,authorization_code:item.authorization_code,
              relation_kind:item.relation_kind,factor:item.factor,billing_unit:item.billing_unit,active:input.checked,locator:item.locator}))})});
          if(!current())return;
          selectedDataset.version=result.dataset_version;
          await showCodeCorrespondences();
        }catch(error){
          if(current()){status.textContent=error.message+' Consultá el historial antes de reintentar.';save.disabled=false;mark.disabled=false;
            for(const c of choices)c.input.disabled=false;}
        }
      });
    }
    if(data.history.length){
      const historyButton=document.createElement('button');historyButton.type='button';historyButton.textContent='Ver historial ('+data.history.length+')';
      const history=document.createElement('div');history.setAttribute('aria-live','polite');
      historyButton.addEventListener('click',()=>{
        history.replaceChildren();
        for(const entry of data.history.slice().reverse()){
          const p=document.createElement('p');
          p.textContent=entry.invoice_code+' / '+entry.authorization_code+' · '+(entry.active?'Registrada':'Retirada')+
            ' · '+entry.actor_username+' · '+entry.created_at+'. '+entry.reason;
          history.append(p);
        }
      });content.append(historyButton,history);
    }
  }catch(error){if(current())content.textContent=error.message;}
}
document.querySelector('#code-map-open').addEventListener('click',showCodeCorrespondences);
for(const selector of ['#value-source','#invoice-dataset'])
  document.querySelector(selector)?.addEventListener('change',()=>{codeMapEpoch++;document.querySelector('#code-map-content').replaceChildren();
    if(selector==='#invoice-dataset')document.querySelector('#code-map-open').disabled=true;});


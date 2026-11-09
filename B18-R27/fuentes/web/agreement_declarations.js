/* Source-scoped documentary support; never a per-row economic confirmation. */
let agreementEpoch=0, agreementPreview=null, agreementSaving=false;
const agreementNode=id=>document.querySelector(`#agreement-${id}`);
function resetAgreement(clearHistory=false){agreementEpoch++;agreementPreview=null;agreementNode('save').disabled=true;agreementNode('result').textContent='';if(clearHistory)agreementNode('history-result').textContent='';}
function agreementContext(){
 if(!selectedDataset || currentRole!=='admin')throw new Error('Se requiere acceso administrador.');
 const raw=agreementNode('seqs').value.trim();
 if(!/^[1-9][0-9]*(\s*,\s*[1-9][0-9]*)*$/.test(raw))throw new Error('Indicá secuencias exactas separadas por coma.');
 const seqs=raw.split(',').map(x=>Number(x.trim()));
 if(seqs.length>5000 || seqs.some(x=>!Number.isSafeInteger(x)) || new Set(seqs).size!==seqs.length)throw new Error('Selección demasiado grande o repetida.');
 if(agreementNode('currency').value!=='ARS' || agreementNode('unit').value!=='por práctica')throw new Error('Declarar explícitamente moneda y unidad según el PDF.');
 const source=document.querySelector('#value-source').value;
 if(!source)throw new Error('Elegí una fuente de convenio.');
 return {dataset:selectedDataset.id,source,payload:{expected_dataset_version:selectedDataset.version,tariff_seqs:seqs,
 document_id:document.querySelector('#hpc-value-document').value,currency:agreementNode('currency').value,unit_label:agreementNode('unit').value,
 valid_from:agreementNode('from').value,valid_until:agreementNode('until').value || null,
 page_number:Number(document.querySelector('#hpc-value-page').value),excerpt:document.querySelector('#hpc-value-excerpt').value,
 conditions_note:agreementNode('conditions').value,reason:agreementNode('reason').value,replaces_id:agreementNode('replaces').value.trim() || null}};
}
function agreementCurrent(context,epoch){try{return epoch===agreementEpoch && JSON.stringify(context)===JSON.stringify(agreementContext());}catch{return false;}}
function agreementUrl(context){return `/api/datasets/${encodeURIComponent(context.dataset)}/sources/${encodeURIComponent(context.source)}/agreement-declarations`;}
const agreementPost=(url,payload)=>request(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
agreementNode('preview').addEventListener('click',async()=>{
 if(agreementSaving)return;resetAgreement();const epoch=agreementEpoch;agreementNode('preview').disabled=true;
 try{const context=agreementContext(),result=await agreementPost(agreementUrl(context)+'/preview',context.payload);
 if(!agreementCurrent(context,epoch))return;
 const d=result.declaration;
 agreementNode('result').textContent=[`${result.count} tarifas seleccionadas. ${d.currency} · ${d.unit_label} · ${d.valid_from} hasta ${d.valid_until || 'sin fin declarado'}`,
 `Fuente SHA256 ${d.source_sha256}\nPDF ${d.document_id} · SHA256 ${d.document_sha256} · página ${d.page_number}`,
 ...d.tariffs.map(t=>`#${t.seq} | ${t.code} | importe original en centavos ${t.amount_cents} | práctica ${t.practice_id}`),
 `Respaldo: ${d.excerpt}\nCondiciones: ${d.conditions_note}\nFundamento: ${d.reason}`,
 d.replaces_id?`Reemplaza ${d.replaces_id}`:'Nueva declaración',d.limit || 'Comparación exploratoria; no débito.'].join('\n');
 agreementPreview={context,result,epoch};agreementNode('save').disabled=false;
 }catch(error){if(epoch===agreementEpoch)agreementNode('result').textContent=error.message;}
 finally{agreementNode('preview').disabled=false;}
});
agreementNode('save').addEventListener('click',async()=>{
 const pending=agreementPreview;if(agreementSaving || !pending)return;
 if(!agreementCurrent(pending.context,pending.epoch)){resetAgreement();return;}
 agreementSaving=true;agreementPreview=null;agreementNode('save').disabled=true;
 try{const result=await agreementPost(agreementUrl(pending.context),{...pending.context.payload,preview_sha256:pending.result.preview_sha256});
 if(selectedDataset?.id!==pending.context.dataset || selectedDataset.version!==pending.context.payload.expected_dataset_version)return;
 selectedDataset.version=result.dataset_version;if(document.querySelector('#value-source').value!==pending.context.source)return;resetAgreement();agreementNode('result').textContent=`Respaldo ${result.id} guardado para ${result.count} tarifas. No se modificaron importes, controles ni débitos. Consultá la historia y actualizá la bandeja.`;
 }catch(error){if(pending.epoch===agreementEpoch){resetAgreement();agreementNode('result').textContent=`${error.message}. Consultá la historia y actualizá la fuente antes de volver a intentar: el resultado podría haberse guardado.`;}}
 finally{agreementSaving=false;}
});
agreementNode('cancel').addEventListener('click',()=>{if(!agreementSaving)resetAgreement();});
agreementNode('history').addEventListener('click',async()=>{
 const context={dataset:selectedDataset?.id,source:document.querySelector('#value-source').value};const epoch=agreementEpoch;
 if(!context.dataset || !context.source)return;
 try{const result=await request(agreementUrl(context));
 if(epoch!==agreementEpoch || context.dataset!==selectedDataset?.id || context.source!==document.querySelector('#value-source').value)return;
 agreementNode('history-result').textContent=result.history.length?result.history.map(h=>`${h.id} · ${h.withdrawn_at?'RETIRADO: '+h.withdrawal_reason:'Registrado (la aplicabilidad depende de fecha y evidencia)'}\n${JSON.stringify(h.declaration,null,2)}`).join('\n\n'):'Sin declaraciones registradas.';
 }catch(error){if(epoch===agreementEpoch)agreementNode('history-result').textContent=error.message;}
});
agreementNode('withdraw').addEventListener('click',async()=>{
 if(agreementSaving || currentRole!=='admin' || !selectedDataset)return;
 const id=agreementNode('withdraw-id').value.trim(),reason=agreementNode('withdraw-reason').value.trim();
 if(!id || reason.length<10){agreementNode('result').textContent='Indicá el ID exacto y un motivo de al menos 10 caracteres.';return;}
 const context={dataset:selectedDataset.id,source:document.querySelector('#value-source').value},version=selectedDataset.version;
 if(!context.source)return;
 resetAgreement();const epoch=agreementEpoch;agreementSaving=true;
 try{const result=await agreementPost(agreementUrl(context)+'/'+encodeURIComponent(id)+'/withdraw',{expected_dataset_version:version,reason});
 if(selectedDataset?.id!==context.dataset || selectedDataset.version!==version)return;
 selectedDataset.version=result.dataset_version;if(document.querySelector('#value-source').value!==context.source)return;agreementNode('result').textContent='Respaldo retirado. La historia se conserva; actualizá la bandeja. No se retiraron precios ni decisiones.';
 }catch(error){if(epoch===agreementEpoch)agreementNode('result').textContent=`${error.message}. Consultá historia y actualizá antes de reintentar.`;}
 finally{agreementSaving=false;}
});
for(const selector of ['#agreement-seqs','#agreement-currency','#agreement-unit','#agreement-from','#agreement-until','#agreement-conditions','#agreement-reason','#agreement-replaces','#hpc-value-document','#hpc-value-page','#hpc-value-excerpt','#value-source']){
 for(const event of ['input','change'])document.querySelector(selector).addEventListener(event,()=>resetAgreement(selector==='#value-source'));
}

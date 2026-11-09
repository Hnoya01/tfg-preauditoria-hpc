/* Preview-bound change; never runs controls or proposes a debit. */
let hpcPercentagePreview = null;
let hpcPercentageEpoch = 0;
let hpcPercentageSaving = false;
const percentageNode = id => document.querySelector(`#hpc-percentage-${id}`);
function resetHpcPercentage() {
  hpcPercentageEpoch += 1;
  hpcPercentagePreview = null;
  percentageNode('apply').disabled = true;
  percentageNode('result').textContent = '';
}
function percentagePayload() {
  if (!selectedDataset || currentRole !== 'admin') throw new Error('Elegí un conjunto con acceso administrador.');
  const raw = percentageNode('seqs').value.trim();
  if (raw && !/^[1-9][0-9]*(\s*,\s*[1-9][0-9]*)*$/.test(raw)) throw new Error('Indicá secuencias enteras separadas por coma.');
  const seqs = raw ? raw.split(',').map(x => Number(x.trim())) : [];
  const nativeRaw = percentageNode('local-ids').value.trim();
  const localIds = nativeRaw ? nativeRaw.split(',').map(x=>x.trim()) : [];
  if(localIds.some(x=>!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(x)) || new Set(localIds).size!==localIds.length) throw new Error('Indicá UUID propios completos, sin repetir.');
  if (seqs.length + localIds.length < 1 || seqs.length + localIds.length > 1000 || seqs.some(x => !Number.isSafeInteger(x)) || new Set(seqs).size !== seqs.length) throw new Error('Selección inválida o repetida.');
  return {expected_dataset_version:selectedDataset.version, tariff_seqs:seqs,...(localIds.length ? {local_ids:localIds} : {}),
    percentage:percentageNode('rate').value.trim(),
    base_currency:percentageNode('base-currency').value || null,
    base_unit_label:percentageNode('base-unit').value || null,
    base_declaration:percentageNode('base-declaration').checked === true,
    effective_from:document.querySelector('#hpc-value-from').value,
    document_id:document.querySelector('#hpc-value-document').value,
    page_number:Number(document.querySelector('#hpc-value-page').value),
    excerpt:document.querySelector('#hpc-value-excerpt').value,
    reason:document.querySelector('#hpc-value-reason').value};
}
function percentageContext() {
  return {dataset:selectedDataset?.id,source:document.querySelector('#value-source').value,
    payload:percentagePayload()};
}
function percentageCurrent(context,epoch) {
  try { return epoch === hpcPercentageEpoch && JSON.stringify(context) === JSON.stringify(percentageContext()); }
  catch { return false; }
}
percentageNode('preview').addEventListener('click',async () => {
  if (hpcPercentageSaving) return;
  resetHpcPercentage();
  const epoch=hpcPercentageEpoch;
  percentageNode('preview').disabled=true;
  try {
    const context=percentageContext();
    if (!context.source) throw new Error('Elegí una fuente de valores.');
    const result=await request(`/api/datasets/${context.dataset}/sources/${context.source}/hpc-percentage/preview`,
      {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(context.payload)});
    if (!percentageCurrent(context,epoch)) return;
    hpcPercentagePreview={context,result,epoch};
    percentageNode('result').textContent=[`Cambio ${result.percentage}%; inicio ${result.effective_from}; ${result.rounding}`,
      ...result.items.map(x=>`${x.local_id ? `Alta propia ${x.local_id}` : `Catálogo #${x.tariff_seq}`} | ${x.code} | ARS ${x.before_ars} → ${x.after_ars} | ${x.unit_label} | ${x.base_origin === 'catalogue_original' ? 'Catálogo original: base declarada por operador, no verificada automáticamente' : 'Versión documentada'} | SHA256 fuente ${x.base_source_sha256 || ''}`),result.use_limit].join('\n');
    percentageNode('apply').disabled=false;
  } catch(error) { if(epoch===hpcPercentageEpoch) percentageNode('result').textContent=error.message; }
  finally { percentageNode('preview').disabled=false; }
});
percentageNode('apply').addEventListener('click',async () => {
  const preview=hpcPercentagePreview;
  if (!preview) return;
  if (!percentageCurrent(preview.context,preview.epoch)) { resetHpcPercentage(); return; }
  percentageNode('apply').disabled=true;
  hpcPercentagePreview=null; // repeated clicks cannot resubmit
  hpcPercentageSaving=true;
  percentageNode('cancel').disabled=true;
  percentageNode('preview').disabled=true;
  try {
    const result=await request(`/api/datasets/${preview.context.dataset}/sources/${preview.context.source}/hpc-percentage/apply`,
      {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...preview.context.payload,preview_sha256:preview.result.preview_sha256})});
    if (selectedDataset?.id !== preview.context.dataset) return;
    if (selectedDataset.version !== preview.context.payload.expected_dataset_version) return;
    selectedDataset.version=result.dataset_version;
    resetHpcPercentage();
    percentageNode('result').textContent=`${result.versions.length} versiones guardadas. Operación ${result.operation_id}. No se ejecutaron controles ni débitos.`;
  } catch(error) {
    if(preview.epoch===hpcPercentageEpoch) {
      resetHpcPercentage();
      const uncertain=!error.status || error.status>=500 || [408,429].includes(error.status);
      percentageNode('result').textContent=uncertain
        ? `${error.message} El resultado puede haberse guardado. Consultá la historia de los valores antes de previsualizar o aplicar nuevamente el porcentaje.`
        : `${error.message} No se aplicó esta solicitud. Actualizá y volvé a previsualizar.`;
    }
  } finally {
    hpcPercentageSaving=false;
    percentageNode('cancel').disabled=false;
    percentageNode('preview').disabled=false;
  }
});
percentageNode('cancel').addEventListener('click',() => { if (!hpcPercentageSaving) resetHpcPercentage(); });
for(const selector of ['#hpc-percentage-seqs','#hpc-percentage-local-ids','#hpc-percentage-rate','#hpc-value-from','#hpc-value-document',
  '#hpc-percentage-base-currency','#hpc-percentage-base-unit','#hpc-percentage-base-declaration',
  '#hpc-value-page','#hpc-value-excerpt','#hpc-value-reason','#value-source']) {
  document.querySelector(selector).addEventListener('input',resetHpcPercentage);
  document.querySelector(selector).addEventListener('change',resetHpcPercentage);
}

let csrfToken = null;
let currentRole = null;
let selectedDataset = null;
let currentPreview = null;
let alertPage = null;
let alertOffset = 0;
let selectedAlertDetail = null;
let hpcOffset = 0;
let hpcPage = null;
let authorizationPreview = null;
let authorizationEpoch = 0;
let correspondenceContext = null;
let correspondenceEpoch = 0;
let documentaryContext = null;
let documentaryRequest = 0;

function clearDocumentaryContext() {
  documentaryRequest += 1;
  documentaryContext = null;
  document.querySelector('#documentary-panel').hidden = true;
  document.querySelector('#documentary-form').reset();
  document.querySelector('#documentary-history').textContent = '';
  document.querySelector('#documentary-pdf').removeAttribute('href');
}

async function showDocumentaryAssessment(item, datasetId, sourceId, expectedVersion) {
  clearDocumentaryContext();
  const requestId = documentaryRequest;
  const pdf = item.checks?.factor_document;
  const seq = /^hpc_catalog_tariffs\.seq=(\d+)$/.exec(item.checks?.catalogue_formula?.tariff_locator || '');
  if (!seq || !pdf?.document_id || selectedDataset?.id !== datasetId ||
      document.querySelector('#value-source').value !== sourceId) return;
  const params = new URLSearchParams({provider: item.provider, code: item.code_complete, tariff_seq: seq[1]});
  const url = `/api/datasets/${datasetId}/sources/${sourceId}/documentary-assessments`;
  const history = await request(`${url}?${params}`);
  if (requestId !== documentaryRequest || selectedDataset?.id !== datasetId ||
      document.querySelector('#value-source').value !== sourceId) return;
  if (history.dataset_version !== expectedVersion) throw new Error('La fuente cambió durante la consulta. Volvé a abrir la ficha antes de registrar el cotejo.');
  documentaryContext = {url, datasetId, sourceId, provider: item.provider, code_complete: item.code_complete,
    tariff_seq: Number(seq[1]), document_id: pdf.document_id, version: history.dataset_version};
  document.querySelector('#documentary-panel').hidden = false;
  document.querySelector('#documentary-context').textContent =
    `Código ${item.code_complete} · corte ${item.value_cut}\nPDF SHA-256 ${pdf.sha256}\nFactor declarado por el catálogo: ${Number(item.checks.catalogue_formula.ub_milliunits_from_catalogue) / 1000} U.B.\nPágina citada por el catálogo: ${pdf.page_from_catalogue || 'sin localizador'}.`;
  document.querySelector('#documentary-pdf').href = `/api/datasets/${datasetId}/evidence-pdfs/${pdf.document_id}/file`;
  document.querySelector('#documentary-history').textContent = history.history.length
    ? history.history.map((v) => `Versión ${v.ordinal}: ${{matches: 'Coincide', differs: 'Difiere', inconclusive: 'No concluyente'}[v.conclusion]} · edición ${v.edition} · página ${v.page_number} · factor observado ${v.observed_factor ?? 'no determinado'} U.B. · responsable ${v.actor_username} · ${v.created_at}\n${v.note}`).join('\n\n') +
      `\n\nÚltima constancia: ${history.latest.freshness === 'current' ? 'vigente' : 'requiere actualización'}. No acredita aplicabilidad económica.`
    : item.general_reference?.review_id
      ? 'Sin constancia humana individual. Podés registrar una observación si necesitás corregir o ampliar el cotejo automático de fuentes.'
      : 'Sin cotejo individual registrado. Completá el formulario después de consultar el PDF.';
}
const loginPanel = document.querySelector("#login-panel");
const workspacePanel = document.querySelector("#workspace-panel");
const message = document.querySelector("#message");

async function request(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (csrfToken && !["GET", "HEAD"].includes(options.method || "GET")) {
    headers["X-CSRF-Token"] = csrfToken;
  }
  const response = await fetch(path, { ...options, headers, credentials: "same-origin" });
  const body = response.status === 204 ? null : await response.json();
  if (!response.ok) {
    const error = new Error(body?.detail || 'No se pudo completar la operación');error.status=response.status;throw error;
  }
  return body;
}

async function refresh() {
  if(typeof resetHpcScope==='function')resetHpcScope();
  resetProcessing();
  resetClosure();
  resetRevisions();
  csrfToken = null;
  currentRole = null;
  selectedDataset = null;
  practicePage = null;
  practiceContextKey = null;
  if(typeof resetHandoff==='function')resetHandoff(true);
  document.querySelector('#identity').textContent = '';
  document.querySelector('#datasets').replaceChildren();
  closeSheetReview();
  document.querySelector('#practice-rows').replaceChildren();
  closePracticeDetail();
  syncWorkspaceNavigation();
  try {
    const person = await request("/api/me");
    if(loginPanel.hidden===false)activeWorkspaceView='inicio';
    csrfToken = person.csrf_token;
    currentRole = person.role;
    const datasets = await request("/api/datasets");
    document.querySelector("#identity").textContent = `${person.username} · ${person.role}`;
    document.querySelector("#dataset-form").hidden = person.role !== "admin";
    const list = document.querySelector("#datasets");
    list.replaceChildren();
    for (const dataset of datasets) {
      const item = document.createElement("li");
      item.dataset.datasetId = dataset.id;
      item.textContent = `${dataset.label} · versión ${dataset.version}`;
      list.append(item);
    }
    const selector = document.querySelector("#invoice-dataset");
    const selected = selector.value;
    selector.replaceChildren();
    for (const dataset of datasets) {
      const option = document.createElement("option");
      option.value = dataset.id;
      option.textContent = dataset.label;
      selector.append(option);
    }
    if (datasets.some((dataset) => dataset.id === selected)) selector.value = selected;
    document.querySelector("#invoice-panel").hidden = !datasets.length || person.role === "viewer";
    document.querySelector("#source-panel").hidden = !datasets.length || person.role === "viewer";
    document.querySelector("#controls-panel").hidden = !datasets.length || person.role === "viewer";
    document.querySelector("#review-panel").hidden = !datasets.length || person.role === "viewer";
    syncWorkspaceNavigation();
    loginPanel.hidden = true;
    workspacePanel.hidden = false;
    document.body.classList.add('workspace-open');
    message.textContent = 'Cargando el contexto de trabajo…';
    if (datasets.length && person.role !== "viewer") await refreshBatches(datasets);
    if (!datasets.length) {
      selectedDataset = null;
      syncWorkspaceNavigation();
      if (person.role === 'admin') document.querySelector('#dataset-management').open = true;
      const item = document.createElement("li");
      item.textContent = "No tenés conjuntos asignados.";
      list.append(item);
    }
    loginPanel.hidden = true;
    workspacePanel.hidden = false;
    document.body.classList.add('workspace-open');
    message.textContent = "";
  } catch (error) {
    const authenticated = Boolean(csrfToken);
    loginPanel.hidden = authenticated;
    workspacePanel.hidden = !authenticated;
    document.body.classList.toggle('workspace-open', authenticated);
    message.textContent = error.message === "Sesión requerida" ? "" :
      authenticated ? `Ingresaste, pero no se pudo cargar la pantalla: ${error.message}` : error.message;
  }
}

async function refreshBatches(datasets) {
  selectedDataset = datasets.find((dataset) => dataset.id === document.querySelector("#invoice-dataset").value);
  const batches = await request(`/api/datasets/${selectedDataset.id}/batches`);
  const selector = document.querySelector("#invoice-batch");
  const previous = selector.value;
  selector.replaceChildren();
  for (const batch of batches) {
    const option = document.createElement("option");
    option.value = batch.id;
    option.dataset.auditWorkflow=batch.audit_workflow?"1":"0";
    option.textContent = `${batch.original_name} · ${batch.period || "sin importar"}`+(batch.audit_closed_at?" · Cerrada":batch.handoff_received_at?" · En auditoría":"");
    selector.append(option);
  }
  if (batches.some((batch) => batch.id === previous)) selector.value = previous;
  else if(batches[0]?.invoice_duty==='auditor'){
    const delivered=batches.filter(b=>b.handoff_received_at).sort((a,b)=>Number(!!a.audit_closed_at)-Number(!!b.audit_closed_at) || b.handoff_received_at.localeCompare(a.handoff_received_at));
    if(delivered.length)selector.value=delivered[0].id;
  }
  showInvoices(batches);
  clearPreview();
  if(activeWorkspaceView==='inicio'){
    syncWorkspaceNavigation();
    return;
  }
  await refreshSources();
  await refreshRuns();
  alertOffset = 0;
  await refreshAlerts();
}

async function refreshAlerts() {
  const batchId = document.querySelector("#invoice-batch").value;
  const list = document.querySelector("#alerts");
  list.replaceChildren();
  selectedAlertDetail = null;
  document.querySelector("#alert-detail").textContent = "";
  document.querySelector("#proposal-detail").textContent = "";
  if (!batchId || !selectedDataset) {
    alertPage = null;
    document.querySelector("#alert-count").textContent = "Elegí un lote importado.";
    await refreshWorkbench();
    return;
  }
  const includeHistorical = document.querySelector("#include-historical-alerts").checked;
  try {
    alertPage = await request(`/api/datasets/${selectedDataset.id}/batches/${batchId}/alerts?offset=${alertOffset}&limit=50&include_historical=${includeHistorical}`);
  } catch (error) {
    if (error.message !== 'Lote importado inexistente') throw error;
    alertPage = null;
    document.querySelector('#alert-count').textContent = 'El lote todavía no está importado. Confirmá su período en Facturación.';
    await refreshWorkbench();
    return;
  }
  document.querySelector("#alert-count").textContent =
    `${alertPage.total} alertas en esta vista · mostrando ${alertPage.items.length ? alertOffset + 1 : 0} a ${alertOffset + alertPage.items.length} · ${alertPage.historical_outside_scope_count || 0} conservadas como historia fuera de alcance`;
  for (const alert of alertPage.items) {
    const item = document.createElement("li");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = alert.id;
    checkbox.className = "alert-selection";
    checkbox.disabled = alert.freshness !== "current" || alert.current_result !== "con_indicios";
    const detail = document.createElement("button");
    detail.type = "button";
    detail.textContent = `Hoja1!${alert.source_row} · ${alert.rule_code} · ${alert.decision} · ${alert.freshness}`;
    detail.addEventListener("click", async () => {
      try { await showAlert(alert.id); } catch (error) { message.textContent = error.message; }
    });
    item.append(checkbox, detail);
    list.append(item);
  }
  document.querySelector("#alerts-previous").disabled = alertOffset === 0;
  document.querySelector("#alerts-next").disabled = alertOffset + alertPage.items.length >= alertPage.total;
  await refreshWorkbench();
}

async function showAlert(alertId) {
  selectedAlertDetail = await request(`/api/datasets/${selectedDataset.id}/alerts/${alertId}`);
  const a = selectedAlertDetail;
  document.querySelector("#alert-detail").textContent = [
    `Hoja1!${a.source_row} · ${a.rule_code} · ${a.result} · ${a.freshness}`,
    `Decisión: ${a.decision}; motivo: ${a.reason_code}`,
    `Factura: ${JSON.stringify(a.invoice)}`,
    `Evidencia del control: ${JSON.stringify(a.evidence)}`,
    `Decisiones previas: ${JSON.stringify(a.history)}`,
    `Reutilizaciones: ${JSON.stringify(a.reuses)}`,
  ].join("\n");
  document.querySelector("#work-row").value = a.source_row;
  const field = document.querySelector("#work-field").value;
  document.querySelector("#work-value").value = a.invoice.fields[field] ?? "";
  const proposal = await request(`/api/datasets/${selectedDataset.id}/batches/${a.batch_id}/rows/${a.source_row}/proposals`);
  const evaluation = proposal.latest_evaluation;
  if (!evaluation) {
    document.querySelector("#proposal-detail").textContent = "Sin propuesta guardada. Importe por determinar.";
    return;
  }
  const reasons = {
    saved_dependency_basis_missing: "La versión guardada no tiene una base de dependencias verificable.",
    shared_row_basis_changed: "Cambió la identidad, cantidad o interpretación de esta fila.",
    provider_scope_changed: "Cambió el alcance confirmado del prestador o su unidad.",
    value_source_selection_changed: "Cambió el conjunto de referencias de valores.",
    decision_not_current_confirmed: "La decisión que respalda este componente dejó de estar confirmada y vigente.",
    finding_dependencies_changed: "Cambió un dato o grupo del que depende el hallazgo.",
    economic_reference_withdrawn_or_missing: "La referencia económica fue retirada o no está disponible.",
    economic_verification_changed: "Cambió la evaluación económica que respaldaba el cálculo.",
    document_registration_changed: "Cambió el registro del documento de respaldo.",
    documentary_assessment_changed: "Se registró otro cotejo documental para el arancel de este componente.",
    documentary_assessment_not_current_match: "El cotejo documental requiere revisión o dejó de acreditar coincidencia.",
    reference_original_unavailable_or_changed: "Falta un original de respaldo o no coincide con su hash.",
    row_outside_scope: "La prestación está fuera del alcance actual.",
  };
  const lines = [
    `Versión ${evaluation.ordinal}. Total guardado: ARS ${evaluation.amount_ars_at_save}.`,
    evaluation.amount_ars === null ? "Importe vigente: por determinar." :
      `${evaluation.affected_component_count ? "Subtotal" : "Total"} vigente: ARS ${evaluation.amount_ars}.`,
    `Componentes vigentes: ${evaluation.current_component_count}; afectados: ${evaluation.affected_component_count}.`,
  ];
  for (const part of evaluation.components) {
    lines.push(`${part.rule_code} · ${part.rubric} · unidades ${part.unit_start} a ${part.unit_end} · ` +
      (part.current_amount_ars === null ? `sin importe vigente (guardado ARS ${part.amount_ars_at_save})` : `vigente ARS ${part.current_amount_ars}`));
    for (const reason of part.invalid_reasons) lines.push(reasons[reason] || "Este componente requiere una nueva evaluación de su respaldo.");
  }
  lines.push("Los componentes afectados quedan fuera del total vigente. La validación definitiva es externa.");
  document.querySelector("#proposal-detail").textContent = lines.join("\n");
}

document.querySelector("#work-field").addEventListener("change", () => {
  if (selectedAlertDetail) {
    const field = document.querySelector("#work-field").value;
    document.querySelector("#work-value").value = selectedAlertDetail.invoice.fields[field] ?? "";
  }
});

document.querySelector("#alerts-previous").addEventListener("click", async () => {
  alertOffset = Math.max(0, alertOffset - 50);
  try { await refreshAlerts(); } catch (error) { message.textContent = error.message; }
});
document.querySelector("#alerts-next").addEventListener("click", async () => {
  alertOffset += 50;
  try { await refreshAlerts(); } catch (error) { message.textContent = error.message; }
});
document.querySelector("#refresh-alerts-button").addEventListener("click", async () => {
  try { await refreshAlerts(); } catch (error) { message.textContent = error.message; }
});
document.querySelector("#include-historical-alerts").addEventListener("change", async () => {
  alertOffset = 0;
  try { await refreshAlerts(); } catch (error) { message.textContent = error.message; }
});
document.querySelector("#export-provisional-button").addEventListener("click", async () => {
  const batchId = document.querySelector("#invoice-batch").value;
  if (!selectedDataset || !batchId) return;
  const button = document.querySelector("#export-provisional-button");
  button.disabled = true;
  try {
    const response = await fetch(`/api/datasets/${selectedDataset.id}/batches/${batchId}/export-provisional`,
      { credentials: "same-origin" });
    if (!response.ok) {
      const body = await response.json();
      throw new Error(body?.detail || "No se pudo generar la salida");
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `revision-${batchId}-provisional.zip`;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    message.textContent = "Salida provisional descargada. Guardala en una ubicación privada.";
  } catch (error) { message.textContent = error.message; }
  finally { button.disabled = false; }
});
document.querySelector("#materialize-button").addEventListener("click", async () => {
  const batchId = document.querySelector("#invoice-batch").value;
  if (!batchId || !selectedDataset) return;
  try {
    const result = await request(`/api/datasets/${selectedDataset.id}/batches/${batchId}/alerts/materialize`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_version: selectedDataset.version })
    });
    selectedDataset.version = result.dataset_version;
    await refreshAlerts();
    message.textContent = `${result.created} alertas preparadas; todas pendientes de revisión humana.`;
  } catch (error) { message.textContent = error.message; }
});

document.querySelector("#decision-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const formElement = event.currentTarget;
  const batchId = document.querySelector("#invoice-batch").value;
  const selected = [...document.querySelectorAll(".alert-selection:checked")].map((box) =>
    alertPage.items.find((item) => item.id === box.value));
  if (!selected.length || !selectedDataset || !batchId) {
    message.textContent = "Seleccioná las alertas que comparten esta decisión.";
    return;
  }
  try {
    const result = await request(`/api/datasets/${selectedDataset.id}/batches/${batchId}/decisions`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_dataset_version: selectedDataset.version,
        expected_revision_version: alertPage.revision_version,
        items: selected.map((a) => ({ id: a.id, expected_version: a.version })),
        state: document.querySelector("#decision-state").value,
        foundation: document.querySelector("#decision-foundation").value,
        evidence_note: document.querySelector("#decision-evidence").value || null })
    });
    selectedDataset.version = result.dataset_version;
    await refreshAlerts();
    formElement.reset();
    message.textContent = `${result.decision_ids.length} decisiones guardadas con historial.`;
  } catch (error) { message.textContent = error.message; }
});

document.querySelector("#decision-state").addEventListener("change", (event) => {
  document.querySelector("#decision-evidence").required = event.target.value === "confirmada";
});
document.querySelector("#decision-form").addEventListener("reset", () => {
  document.querySelector("#decision-evidence").required = true;
});

document.querySelector("#work-change-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const batchId = document.querySelector("#invoice-batch").value;
  const sourceRow = Number(document.querySelector("#work-row").value);
  if (!selectedDataset || !batchId || !alertPage || !Number.isInteger(sourceRow)) return;
  try {
    const result = await request(`/api/datasets/${selectedDataset.id}/batches/${batchId}/rows/${sourceRow}/work-fields`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_dataset_version: selectedDataset.version,
        expected_revision_version: alertPage.revision_version,
        field: document.querySelector("#work-field").value,
        value: document.querySelector("#work-value").value,
        reason: document.querySelector("#work-reason").value })
    });
    selectedDataset.version = result.dataset_version;
    await refreshAlerts();
    await refreshRuns();
    message.textContent = `Corrección guardada para Hoja1!${sourceRow}. Actualizá el análisis explícitamente.`;
  } catch (error) { message.textContent = error.message; }
});

async function refreshRuns() {
  const batchId = document.querySelector("#invoice-batch").value;
  const selector = document.querySelector("#control-run");
  const previous = selector.value;
  selector.replaceChildren();
  document.querySelector("#control-summary").textContent = "";
  document.querySelector("#control-row-results").textContent = "";
  if (!batchId || !selectedDataset) return;
  await refreshProcessing();
  const runs = await request(`/api/datasets/${selectedDataset.id}/batches/${batchId}/control-runs`);
  for (const run of runs) {
    const option = document.createElement("option");
    option.value = run.id;
    option.textContent = `${run.created_at} · ${run.closed_revision ? 'captura de revisión cerrada' : run.freshness === "current" ? "vigente" : "requiere actualización"}`;
    selector.append(option);
  }
  if (runs.some((run) => run.id === previous)) selector.value = previous;
  if (selector.value) await showRun(selector.value);
}

async function showRun(runId) {
  const run = await request(`/api/datasets/${selectedDataset.id}/control-runs/${runId}`);
  const lines = [run.closed_revision ? `Captura histórica de revisión cerrada. Estado técnico: ${run.technical_state}; vigencia al cierre: ${run.freshness}. No valida la revisión actual.` : `Estado técnico: ${run.technical_state}; vigencia: ${run.freshness}`,
    `Captura SHA-256: ${run.snapshot_sha256}`,
    `Origen X1 SHA-256: ${run.snapshot.invoice_sha256}; período ${run.snapshot.period}`,
    `Valores: ${run.snapshot.sources.filter((s) => s.kind === "values").map((s) => s.cut_label).join(", ") || "sin fuente"}`];
  if (run.global_affected_rules.length) lines.push(`Dependencias compartidas que afectan estas reglas: ${run.global_affected_rules.join(", ")}.`);
  if (Object.keys(run.affected_rows).length) lines.push(`Hay cambios en ${Object.keys(run.affected_rows).length} filas o grupos relacionados. Los demás resultados conservan vigencia.`);
  for (const item of run.counts) lines.push(`${item.rule_code} · ${item.result}: ${item.total}`);
  document.querySelector("#control-summary").textContent = lines.join("\n");
}

document.querySelector("#control-run").addEventListener("change", async (event) => {
  try { await showRun(event.target.value); }
  catch (error) { message.textContent = error.message; }
});

document.querySelector("#control-row-button").addEventListener("click", async () => {
  const runId = document.querySelector("#control-run").value;
  const row = document.querySelector("#control-row").value;
  if (!runId || !row || !selectedDataset) return;
  try {
    const results = await request(`/api/datasets/${selectedDataset.id}/control-runs/${runId}/rows/${row}`);
    document.querySelector("#control-row-results").textContent = results.map((r) =>
      `${r.rule_code}: ${r.result} · ${r.freshness} · ${r.reason_code}${r.difference_ars === null ? "" : ` · diferencia ARS ${r.difference_ars}`} · ${r.evidence.locator}`
    ).join("\n");
  } catch (error) { message.textContent = error.message; }
});

async function refreshSources() {
  document.querySelector('#code-map-open').disabled=true;
  clearDocumentaryContext();
  const sources = await request(`/api/datasets/${selectedDataset.id}/sources`);
  const list = document.querySelector("#sources");
  const authorizationSources = document.querySelector('#authorization-source-status');
  const selector = document.querySelector("#value-source");
  const previous = selector.value;
  list.replaceChildren();
  authorizationSources.replaceChildren();
  selector.replaceChildren();
  for (const source of sources) {
    const item = document.createElement("li");
    item.textContent = source.kind === "authorizations"
      ? (source.status === 'pending' ? 'Autorizaciones reales: fuente pendiente de validación; cobertura desconocida'
        : `Autorizaciones JSON ${source.metadata.data_origin === 'synthetic' ? 'FICTICIAS' : 'DE ORIGEN REAL NO VALIDADO'} · captura incorporada; cobertura declarada ${source.coverage.declared || 'desconocida'}, no verificada`)
      : `Valores: ${source.cut_label} · versión ${source.source_version} · aplicabilidad no verificada`;
    (source.kind === 'authorizations' ? authorizationSources : list).append(item);
    if (source.kind === "values" && source.status === "registered") {
      const option = document.createElement("option");
      option.value = source.id;
      option.textContent = `${source.cut_label} · ${source.source_sha256.slice(0, 12)}`;
      selector.append(option);
    }
  }
  if (!sources.some(source => source.kind === 'values')) {
    const item = document.createElement("li");
    item.textContent = "Todavía no hay valores registrados en este conjunto.";
    list.append(item);
  }
  if (sources.some((source) => source.id === previous)) selector.value = previous;
  document.querySelector("#value-search-form").hidden = !selector.options.length;
  document.querySelector("#value-results").textContent = "";
  document.querySelector("#hpc-values-panel").hidden = !selector.options.length;
  document.querySelector("#local-hpc-panel").hidden = !selector.options.length;
  document.querySelector("#local-hpc-list").replaceChildren();
  if (typeof resetLocalHpc === "function") resetLocalHpc();
  document.querySelector("#code-map-panel").hidden = currentRole === "viewer" || !selector.options.length;
  document.querySelector("#code-map-open").disabled = !selector.options.length;
  document.querySelector("#local-hpc-form").hidden = currentRole !== "admin" || !selector.options.length;
  document.querySelector("#hpc-document-form").hidden = currentRole !== "admin" || !selector.options.length;
  document.querySelector("#hpc-value-form").hidden = currentRole !== "admin" || !selector.options.length;
  document.querySelector("#hpc-percentage-panel").hidden = currentRole !== "admin" || !selector.options.length;
  document.querySelector("#agreement-panel").hidden = currentRole !== "admin" || !selector.options.length;
  if (typeof resetAgreement === "function") resetAgreement(true);
  document.querySelector("#hpc-value-history").textContent = "";
  await refreshHpcDocuments();
  hpcOffset = 0;
  hpcPage = null;
  document.querySelector("#hpc-comparison-summary").textContent = "";
  document.querySelector("#hpc-readiness-summary").textContent = "";
  document.querySelector("#hpc-row-detail").textContent = "";
  document.querySelector("#hpc-row-readiness").textContent = "";
  await refreshAuthorizationIntake();
}

document.querySelector("#value-search-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const sourceId = document.querySelector("#value-source").value;
  if (!sourceId || !selectedDataset) return;
  const params = new URLSearchParams({ code: document.querySelector("#value-code").value });
  const date = document.querySelector("#value-date").value;
  const provider = document.querySelector("#value-provider").value;
  if (date) params.set("performed_on", date);
  if (provider) params.set("provider", provider);
  try {
    const result = await request(`/api/datasets/${selectedDataset.id}/sources/${sourceId}/value-candidates?${params}`);
    const lines = [
      `Corte ${result.cut_label}; código exacto ${result.code_exact}`,
      `Códigos: ${result.code_total}; aranceles: ${result.tariff_total}`,
      `Moneda y unidad: sin verificar; aplicabilidad: no determinada`,
    ];
    if (result.truncated) lines.push("Lista truncada: revisar la fuente completa.");
    for (const candidate of result.tariff_candidates) {
      if(candidate.local_id) lines.push(`Práctica propia HPC UUID ${candidate.local_id} · ${candidate.code} · ${candidate.description} · ${candidate.source_locator}`);
      else lines.push(`seq ${candidate.seq} · prestador ${candidate.provider} · ${candidate.amount_status==='not_interpretable'?`importe no interpretable (literal: ${candidate.amount_literal ?? candidate.amount_cents ?? 'sin dato'})`:`${candidate.amount_cents} centavos`} · inicio ${candidate.valid_from} · fin ${candidate.valid_until || "sin fecha declarada"} · ${candidate.temporal_relation} · ${candidate.source_locator}`);
      if(candidate.effective_reference) {
        const ref=candidate.effective_reference;
        lines.push(ref.selected?`Referencia para la fecha consultada: ${ref.recorded_amount ?? 'importe no interpretable'} · ${ref.declared_currency ?? 'moneda sin acreditar'} · ${ref.declared_unit ?? 'unidad sin acreditar'} · ${ref.value_version?.id || 'original del catálogo'} · desde ${ref.effective_from} · estado ${ref.status}. No acredita aplicabilidad a una fila.`:'Sin referencia efectiva para la fecha: '+ref.status);
      }
      if (candidate.conditions) lines.push(`Condiciones: ${candidate.conditions}`);
    }
    const related=result.related_hpc_references;
    if(related) {
      lines.push(related.use_limit);
      for(const candidate of related.candidates) {
        lines.push(`Enlace pendiente: orden ${candidate.order_code} → convenio ${candidate.tariff_code} · importe original registrado ${candidate.recorded_amount ?? 'no interpretable'} · moneda/unidad originales sin acreditar · ${candidate.temporal_relation} · ${candidate.source_locator} · documento ${candidate.document_source_id || 'sin identificar'}, página ${candidate.document_page ?? 'sin indicar'} · SHA fuente ${candidate.source_sha256}. No aplicado.`);
        const effective=candidate.effective_reference;
        if(effective?.value_version)lines.push(`Versión para la fecha: ${effective.recorded_amount ?? effective.value_version.amount_ars ?? 'importe no interpretable'} · estado ${effective.status} · versión ${effective.value_version.id} · ${effective.status==='documented_version_candidate'?effective.declared_currency+' · '+effective.declared_unit:'NO utilizable económicamente: evidencia/importe no verificable'} · enlace aún sujeto a verificación. El original anterior no es reemplazo automático.`);
        else if(effective?.agreement_declaration)lines.push(`Respaldo documental ${effective.agreement_declaration.id} · ${effective.recorded_amount ?? 'importe no interpretable'} · ${effective.status==='documented_agreement_candidate'?effective.declared_currency+' · '+effective.declared_unit:'NO utilizable: '+effective.status} · PDF ${effective.agreement_declaration.document_id} · página ${effective.agreement_declaration.page_number} · SHA ${effective.agreement_declaration.document_sha256}. Enlace sujeto a verificación; sin débito.`);
        else if(effective?.status==='withdrawn_reference')lines.push('BAJA para la fecha: importe original sólo histórico, no aplicable.');
        else if(effective)lines.push(`Estado de referencia: ${effective.status}; el importe original mostrado no acredita aplicabilidad.`);
      }
    }
    const calculated=result.calculated_nomenclature_references;
    if(calculated) {
      const arithmeticLabels={corroborated_technical_rounding:'cálculo y redondeo técnico coinciden',recorded_amount_invalid:'importe registrado no interpretable',recorded_amount_mismatch:'importe registrado distinto del cálculo',not_interpretable:'cálculo no interpretable',coefficient_conflict:'coeficientes contradictorios',unsupported_formula:'fórmula no admitida',provider_conflict:'prestador contradictorio'}, temporalLabels={inside_declared_dates:'dentro de fechas declaradas',outside_declared_dates:'fuera de fechas declaradas',undetermined_declared_dates:'fecha indeterminada'};
      lines.push(calculated.use_limit,`Referencias calculadas: ${calculated.status}`);
      for(const c of calculated.candidates || [])lines.push(
        `Código exacto de nomenclador ${c.code}: ${c.description} · ${c.component_status}`,
        `${c.formula} · Q GAL ${c.qGal} × ${c.galenoRadiologico} + Gto ${c.gto} × ${c.unidadRadiologica}`,
        `Resultado exacto ${c.calculated_amount_exact ?? 'no interpretable'} · cotejo a centavos ${c.calculated_amount_rounded ?? 'no interpretable'} · registrado ${c.recorded_amount ?? 'no interpretable'} · ${arithmeticLabels[c.arithmetic_status] || c.arithmetic_status} · ${c.rounding_note || ''}`,
        `Moneda y unidad económica pendientes. Inicio ${c.valid_from || 'indeterminado'} · ${temporalLabels[c.temporal_relation] || c.temporal_relation}. Fuente ${c.source_file}, fila ${c.source_row}; ${c.source_locator}; SHA ${calculated.source_sha256}`,
        `Norma literal: ${c.norma || 'sin texto'} · unidad arancelaria literal: ${c.unidadArancelaria || 'sin texto'} · forma de facturación: ${c.formaFacturacion || 'sin texto'}. El texto puede estar incompleto: revisar fuente. No se aplica equivalencia ni débito.`);
    }
    document.querySelector("#value-results").textContent = lines.join("\n");
    if (result.tariff_total === 1 && result.tariff_candidates[0]?.provider === 'HPC' && Number.isInteger(result.tariff_candidates[0].seq)) {
      document.querySelector('#hpc-tariff-seq').value = String(result.tariff_candidates[0].seq);
      document.querySelector('#hpc-value-code').value = result.code_exact;
      await showHpcValueHistory();
    }
  } catch (error) { message.textContent = error.message; }
});

async function refreshHpcDocuments() {
  const selector = document.querySelector('#hpc-value-document');
  selector.replaceChildren();
  if (!selectedDataset) return;
  const sourceId = document.querySelector('#value-source').value;
  if (!sourceId) return;
  const documents = await request(`/api/datasets/${selectedDataset.id}/evidence-pdfs`);
  for (const evidence of documents.filter((d) => d.source_id === sourceId && d.category === 'agreement')) {
    const option = document.createElement('option');
    option.value = evidence.id;
    option.textContent = `${evidence.original_name} · SHA ${evidence.sha256.slice(0, 12)}`;
    selector.append(option);
  }
}

async function showHpcValueHistory() {
  const sourceId = document.querySelector('#value-source').value;
  const seq = Number(document.querySelector('#hpc-tariff-seq').value);
  if (!selectedDataset || !sourceId || !Number.isInteger(seq) || seq < 1) throw new Error('Indicá la secuencia exacta del arancel HPC.');
  const history = await request(`/api/datasets/${selectedDataset.id}/sources/${sourceId}/hpc-values/${seq}`);
  document.querySelector('#hpc-value-history').textContent = [
    `Original ${history.cut_label} · seq ${seq} · código ${history.tariff.code} · ${Number.isSafeInteger(history.tariff.amount_cents) && history.tariff.amount_cents>=0?`${history.tariff.amount_cents} centavos`:`importe no interpretable (literal: ${history.tariff.amount_literal ?? history.tariff.amount_cents ?? 'sin dato'})`} · inicio ${history.tariff.valid_from}`,
    ...history.versions.map((v) => `Versión ${v.ordinal} · ARS ${v.amount_ars} ${v.unit_label} · desde ${v.effective_from} · PDF SHA ${v.document_sha256} · página ${v.page_number} · ${v.actor_username} · ${v.created_at}\n${v.excerpt}\nMotivo: ${v.reason}`),
    ...(history.status_history || []).map((v) => `Estado ${v.ordinal}: ${v.active ? 'ACTIVO' : 'BAJA'} desde ${v.effective_from} · PDF SHA ${v.document_sha256} · página ${v.page_number} · ${v.actor_username}\n${v.excerpt}\nMotivo: ${v.reason}`),
    history.use_limit,
  ].join('\n\n');
  return history;
}

document.querySelector('#hpc-value-history-button').addEventListener('click', async () => {
  try { await showHpcValueHistory(); } catch (error) { message.textContent = error.message; }
});

document.querySelector('#hpc-document-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const file = document.querySelector('#hpc-document-file').files[0];
  const sourceId = document.querySelector('#value-source').value;
  if (!selectedDataset || !sourceId || !file) return;
  try {
    const data = await file.arrayBuffer();
    const digest = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', data)),
      (byte) => byte.toString(16).padStart(2, '0')).join('');
    const result = await request(`/api/datasets/${selectedDataset.id}/evidence-pdfs`, {
      method: 'POST', headers: {'Content-Type': 'application/pdf', 'X-Expected-Version': String(selectedDataset.version),
        'X-Source-Id': sourceId, 'X-Source-Filename': file.name, 'X-Evidence-Category': 'agreement',
        'X-Provenance-Note': document.querySelector('#hpc-document-provenance').value,
        'X-Expected-SHA256': digest}, body: data,
    });
    selectedDataset.version = result.dataset_version;
    await refreshHpcDocuments();
    document.querySelector('#hpc-value-document').value = result.id;
    message.textContent = 'PDF original registrado. Revisá su cláusula antes de guardar un valor.';
  } catch (error) { message.textContent = error.message; }
});

document.querySelector('#hpc-value-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const sourceId = document.querySelector('#value-source').value;
  if (!selectedDataset || !sourceId) return;
  try {
    const payload = {expected_dataset_version: selectedDataset.version,
      tariff_seq: Number(document.querySelector('#hpc-tariff-seq').value),
      code: document.querySelector('#hpc-value-code').value,
      amount_ars: document.querySelector('#hpc-value-amount').value,
      unit_label: document.querySelector('#hpc-value-unit').value,
      effective_from: document.querySelector('#hpc-value-from').value,
      document_id: document.querySelector('#hpc-value-document').value,
      page_number: Number(document.querySelector('#hpc-value-page').value),
      excerpt: document.querySelector('#hpc-value-excerpt').value,
      reason: document.querySelector('#hpc-value-reason').value};
    const result = await request(`/api/datasets/${selectedDataset.id}/sources/${sourceId}/hpc-values`, {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload),
    });
    selectedDataset.version = result.dataset_version;
    await showHpcValueHistory();
    message.textContent = `Versión HPC ${result.ordinal} guardada; no modifica importes ni controles.`;
  } catch (error) { message.textContent = error.message; }
});

async function saveHpcStatus(active) {
  const sourceId = document.querySelector('#value-source').value;
  if (!selectedDataset || !sourceId) return;
  const payload = {expected_dataset_version: selectedDataset.version,
    tariff_seq: Number(document.querySelector('#hpc-tariff-seq').value), active,
    effective_from: document.querySelector('#hpc-value-from').value,
    document_id: document.querySelector('#hpc-value-document').value,
    page_number: Number(document.querySelector('#hpc-value-page').value),
    excerpt: document.querySelector('#hpc-value-excerpt').value,
    reason: document.querySelector('#hpc-value-reason').value};
  if (!window.confirm(`${active ? 'Reactivar' : 'Dar de baja'} el arancel HPC ${payload.tariff_seq} desde ${payload.effective_from}? Conserva originales e historia; no ejecuta controles.`)) return;
  try {
    const result = await request(`/api/datasets/${selectedDataset.id}/sources/${sourceId}/hpc-status`, {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
    selectedDataset.version = result.dataset_version;
    await showHpcValueHistory();
    document.querySelector('#value-results').textContent = '';
    message.textContent = 'Estado HPC registrado. Actualizá la consulta o comparación para ver la nueva referencia. No se ejecutaron controles.';
  } catch (error) { message.textContent = error.message; }
}
document.querySelector('#hpc-withdraw-button').addEventListener('click', () => saveHpcStatus(false));
document.querySelector('#hpc-reinstate-button').addEventListener('click', () => saveHpcStatus(true));

async function refreshHpcComparison() {
  const batchId = document.querySelector("#invoice-batch").value;
  const sourceId = document.querySelector("#value-source").value;
  if (!selectedDataset || !batchId || !sourceId) {
    throw new Error("Elegí un lote importado y la fuente de valores.");
  }
  const params = new URLSearchParams({ source_id: sourceId,
    status: document.querySelector("#hpc-comparison-filter").value,
    offset: String(hpcOffset), limit: "50" });
  hpcPage = await request(`/api/datasets/${selectedDataset.id}/batches/${batchId}/hpc-comparison?${params}`);
  const counts = hpcPage.counts;
  const lines = [
    `Prestador HPC · ${hpcPage.value_cut} · comparación exploratoria`,
    `Coinciden numéricamente: ${counts.numeric_equal || 0}; por encima: ${counts.numeric_above_candidate || 0}; por debajo: ${counts.numeric_below_candidate || 0}`,
    `Sin código HPC exacto: ${counts.no_exact_hpc_tariff || 0}; fuera de alcance por período o ámbito: ${counts.outside_scope || 0}`,
    `Mostrando ${hpcPage.items.length ? hpcOffset + 1 : 0}–${hpcOffset + hpcPage.items.length} de ${hpcPage.selected_total} para este filtro.`,
    ...hpcPage.caveats,
  ];
  for (const item of hpcPage.items) {
    const labels = { numeric_equal: "coincide numéricamente", numeric_above_candidate: "facturado por encima",
      numeric_below_candidate: "facturado por debajo", no_exact_hpc_tariff: "sin código HPC exacto",
      outside_scope: "fuera de alcance por período o ámbito", ambiguous_hpc_tariff: "arancel HPC ambiguo",
      undetermined_declared_dates: "vigencia no determinable con las fechas disponibles",
      outside_declared_dates: "fuera de fechas declaradas", unsupported_calculation: "cálculo no interpretado",
      version_evidence_unverifiable: "respaldo de la versión no verificable",
      withdrawn_reference: "arancel dado de baja para esta fecha",
      status_evidence_unverifiable: "respaldo del estado no verificable",
      value_version_unit_incompatible: "unidad de la versión no compatible con prácticas",
      catalogue_amount_not_interpretable: "importe original no interpretable",
      inconsistent_formula: "fórmula inconsistente", tariff_requires_review: "arancel requiere revisión",
      invalid_quantity: "cantidad no interpretable", fractional_cent_needs_rounding_rule: "falta regla de redondeo" };
    lines.push(`${item.locator} · ${labels[item.status] || item.status} · Q ARS ${item.billed_total_ars}${item.effective_reference?.value_version?` · versión ${item.effective_reference.value_version.id} desde ${item.effective_reference.effective_from}`:''}` +
      (item.candidate_total_if_ars_and_same_unit === null ? "" :
        ` · candidato ${item.candidate_total_if_ars_and_same_unit} · diferencia ${item.difference_ars_if_comparable}`));
  }
  document.querySelector("#hpc-comparison-summary").textContent = lines.join("\n");
  document.querySelector("#hpc-previous").disabled = hpcOffset === 0;
  document.querySelector("#hpc-next").disabled = hpcOffset + hpcPage.items.length >= hpcPage.selected_total;
}

document.querySelector("#hpc-comparison-button").addEventListener("click", async () => {
  hpcOffset = 0;
  const button = document.querySelector("#hpc-comparison-button");
  button.disabled = true;
  try { await refreshHpcComparison(); }
  catch (error) { message.textContent = error.message; }
  finally { button.disabled = false; }
});
document.querySelector("#hpc-readiness-button").addEventListener("click", async () => {
  const batchId = document.querySelector("#invoice-batch").value;
  const sourceId = document.querySelector("#value-source").value;
  if (!selectedDataset || !batchId || !sourceId) {
    message.textContent = "Elegí un lote importado y la fuente de valores.";
    return;
  }
  const button = document.querySelector("#hpc-readiness-button");
  button.disabled = true;
  try {
    const params = new URLSearchParams({ source_id: sourceId,
      status: "numeric_above_candidate", limit: "100" });
    const report = await request(`/api/datasets/${selectedDataset.id}/batches/${batchId}/reference-readiness?${params}`);
    const count = report.blocked_dimension_counts_on_page;
    const generalCount = report.general_reference_counts_on_page || {};
    document.querySelector("#hpc-readiness-summary").textContent = [
      `Corte ${report.value_cut}. ${report.selected_total} filas con Q por encima del candidato; se revisaron ${report.items.length} en esta página.`,
      `Referencia general documentada: ${generalCount.supported_base_reference || 0}; con norma NBU por interpretar: ${generalCount.requires_case_interpretation || 0}; sin cotejo suficiente: ${(generalCount.not_documented || 0) + (generalCount.requires_update || 0)}.`,
      `PDF de tarifa sin vínculo por hash: ${count.rate_document_not_hash_matched || 0}; anexo NBU no registrado: ${count.factor_document_not_registered || 0}.`,
      `Cotejo de unidades por código sin registro individual en la aplicación: ${count.factor_page_cotejo_not_recorded_per_code || 0}.`,
      `Cotejos con diferencias: ${count.factor_page_discrepancy || 0}; no concluyentes: ${count.factor_page_inconclusive || 0}; afectados: ${count.factor_page_assessment_affected || 0}.`,
      `Sin vigencia final verificada: ${count.end_or_supersession_not_verified || 0}; unidad de G sin verificar: ${count.billing_unit_not_verified_for_row || 0}.`,
      `Condiciones de cada fila pendientes: ${count.conditions_not_verified_for_row || 0}; decisión confirmada pendiente: ${count.confirmed_current_finding_missing || 0}.`,
      "No se creó una propuesta ni se calculó un débito.",
    ].join("\n");
  } catch (error) { message.textContent = error.message; }
  finally { button.disabled = false; }
});
document.querySelector("#hpc-comparison-filter").addEventListener("change", () => {
  hpcOffset = 0;
  document.querySelector("#hpc-comparison-summary").textContent = "";
});
document.querySelector('#value-source').addEventListener('change', async () => {
  clearDocumentaryContext();
  document.querySelector('#hpc-value-history').textContent = '';
  document.querySelector('#hpc-tariff-seq').value = '';
  document.querySelector('#hpc-value-code').value = '';
  try { await refreshHpcDocuments(); } catch (error) { message.textContent = error.message; }
});
document.querySelector('#hpc-row').addEventListener('input', clearDocumentaryContext);
document.querySelector('#documentary-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const context = documentaryContext;
  if (!context || selectedDataset?.id !== context.datasetId ||
      document.querySelector('#value-source').value !== context.sourceId) return;
  const button = event.currentTarget.querySelector('button');
  button.disabled = true;
  try {
    const factor = document.querySelector('#documentary-factor').value.trim().replace(',', '.');
    const result = await request(context.url, {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({expected_dataset_version: context.version, provider: context.provider,
        code_complete: context.code_complete, tariff_seq: context.tariff_seq, document_id: context.document_id,
        edition: document.querySelector('#documentary-edition').value,
        page_number: Number(document.querySelector('#documentary-page').value),
        fragment: document.querySelector('#documentary-fragment').value, observed_factor: factor || null,
        conclusion: document.querySelector('#documentary-conclusion').value,
        note: document.querySelector('#documentary-note').value})});
    if (selectedDataset?.id === context.datasetId) selectedDataset.version = result.dataset_version;
    message.textContent = 'Constancia documental guardada. No aprueba aplicabilidad económica ni crea importes.';
    if (context === documentaryContext) document.querySelector('#hpc-row-button').click();
  } catch (error) { message.textContent = error.message; }
  finally { button.disabled = false; }
});
document.querySelector("#hpc-previous").addEventListener("click", async () => {
  hpcOffset = Math.max(0, hpcOffset - 50);
  try { await refreshHpcComparison(); } catch (error) { message.textContent = error.message; }
});
document.querySelector("#hpc-next").addEventListener("click", async () => {
  hpcOffset += 50;
  try { await refreshHpcComparison(); } catch (error) { message.textContent = error.message; }
});
document.querySelector("#hpc-row-button").addEventListener("click", async () => {
  const batchId = document.querySelector("#invoice-batch").value;
  const sourceId = document.querySelector("#value-source").value;
  const row = Number(document.querySelector("#hpc-row").value);
  if (!selectedDataset || !batchId || !sourceId || !Number.isInteger(row)) return;
  clearDocumentaryContext();
  const datasetId = selectedDataset.id;
  const requestId = documentaryRequest;
  try {
    const params = new URLSearchParams({ source_id: sourceId, source_row: String(row) });
    const result = await request(`/api/datasets/${datasetId}/batches/${batchId}/hpc-comparison?${params}`);
    const readiness = await request(`/api/datasets/${datasetId}/batches/${batchId}/reference-readiness?${params}`);
    if (requestId !== documentaryRequest || selectedDataset?.id !== datasetId ||
        document.querySelector('#value-source').value !== sourceId ||
        document.querySelector('#invoice-batch').value !== batchId || Number(document.querySelector('#hpc-row').value) !== row) return;
    document.querySelector("#hpc-row-detail").textContent = JSON.stringify(result.items[0], null, 2);
    const item = readiness.items[0];
    const checks = item.checks;
    const labels = {
      no_unique_exact_tariff: "No hay un arancel único por código completo.",
      rate_document_not_hash_matched: "Falta vincular por hash el PDF de la tarifa.",
      factor_document_not_registered: "Falta registrar el anexo NBU correspondiente.",
      factor_page_cotejo_not_recorded_per_code: "Falta registrar el cotejo del factor U.B. de este código en el PDF.",
      factor_page_assessment_affected: "La constancia documental requiere actualización.",
      factor_page_discrepancy: "El factor observado difiere del catálogo; requiere revisión.",
      factor_page_inconclusive: "El cotejo documental registrado no permite concluir.",
      specific_nbu_norm_requires_case_interpretation: "El valor base está documentado; esta práctica tiene una norma NBU específica que requiere revisar su alcance.",
      agreement_document_review_affected: "Cambió la base documental del convenio cotejado; requiere actualización.",
      end_or_supersession_not_verified: "No se acreditó una fecha final ni la ausencia de un reemplazo.",
      currency_not_verified_per_reference: "La moneda de la referencia no está acreditada por fila.",
      billing_unit_not_verified_for_row: "No se acreditó que G use la unidad facturable del arancel.",
      conditions_not_verified_for_row: "Falta comprobar las condiciones para esta prestación.",
      specific_agreement_not_checked: "Falta descartar o aplicar un acuerdo particular.",
      confirmed_current_finding_missing: "No hay un hallazgo confirmado y vigente.",
      provider_scope_not_confirmed: "El alcance del prestador no está confirmado.",
    };
    document.querySelector("#hpc-row-readiness").textContent = [
      `${item.locator} · referencia ${item.value_cut} · sin importe propuesto`,
      checks.rate_document ? `Tarifa: ${checks.rate_document.status}; página citada ${checks.rate_document.page_from_catalogue || "sin localizador"}.` : "",
      checks.factor_document ? `Anexo NBU: ${checks.factor_document.status}; página citada ${checks.factor_document.page_from_catalogue || "sin localizador"}.` : "",
      item.general_reference?.rate_per_practice_ars ? `Valor general documentado: ARS ${item.general_reference.rate_per_practice_ars} por práctica; total base de la fila: ARS ${item.general_reference.general_row_value_ars}.` : '',
      item.general_reference?.no_end_date_is_not_expiry ? 'La referencia no declara fecha final; eso no la invalida por sí solo. Se conserva el corte de fuentes indicado.' : '',
      ...item.blocked_dimensions.map((code) => labels[code] || code),
    ].filter(Boolean).join("\n");
    await showDocumentaryAssessment(item, datasetId, sourceId, readiness.dataset_version);
  } catch (error) { message.textContent = error.message; }
});

function clearPreview() {
  currentPreview = null;
  document.querySelector("#invoice-preview").textContent = "";
  document.querySelector("#period-confirmed").checked = false;
  document.querySelector("#confirm-button").disabled = true;
}

document.querySelector("#invoice-dataset").addEventListener("change", async () => {
  try { await refreshBatches(await request("/api/datasets")); }
  catch (error) { message.textContent = error.message; }
});
document.querySelector("#invoice-batch").addEventListener("change", async () => {
  clearDocumentaryContext();
  clearPreview();
  alertOffset = 0;
  hpcOffset = 0;
  hpcPage = null;
  document.querySelector("#hpc-comparison-summary").textContent = "";
  document.querySelector("#hpc-readiness-summary").textContent = "";
  document.querySelector("#hpc-row-detail").textContent = "";
  document.querySelector("#hpc-row-readiness").textContent = "";
  try { await refreshRuns(); await refreshAlerts(); } catch (error) { message.textContent = error.message; }
});
document.querySelector("#invoice-period").addEventListener("change", clearPreview);
document.querySelector("#period-confirmed").addEventListener("change", (event) => {
  document.querySelector("#confirm-button").disabled = !currentPreview?.can_confirm || !event.target.checked;
});

document.querySelector("#upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = document.querySelector("#invoice-file").files[0];
  if (!file || !selectedDataset) return;
  try {
    const result = await request(`/api/datasets/${selectedDataset.id}/batches`, {
      method: "POST", body: file,
      headers: { "X-Expected-Version": String(selectedDataset.version), "X-Source-Filename": file.name,
                 "Content-Type": "application/octet-stream" }
    });
    await refreshBatches(await request("/api/datasets"));
    document.querySelector("#invoice-batch").value = result.id;
    await refreshRuns();
    await refreshAlerts();
    message.textContent = "Original guardado por hash. Revisá período y conciliación.";
  } catch (error) { message.textContent = error.message; }
});

document.querySelector("#preview-button").addEventListener("click", async () => {
  const batchId = document.querySelector("#invoice-batch").value;
  const period = document.querySelector("#invoice-period").value;
  if (!batchId || !period || !selectedDataset) return;
  try {
    currentPreview = await request(`/api/datasets/${selectedDataset.id}/batches/${batchId}/invoice-preview?period=${encodeURIComponent(period)}`);
    const p = currentPreview;
    document.querySelector("#invoice-preview").textContent =
      `Hoja: ${p.sheet}\nEncabezados usados: ${Object.entries(p.headers).map(([col, name]) => `${col} ${name}`).join(" · ")}\n` +
      `Filas físicas: ${p.physical_rows}; interpretadas: ${p.interpreted_rows}\n` +
      `Incluidas: ${p.included}; excluidas por período o ámbito: ${p.excluded}; alcance indeterminado: ${p.indeterminate}\n` +
      `O: ARS ${p.honorarios_ars}; P: ARS ${p.derechos_ars}; Q: ARS ${p.total_ars}\n` +
      `Diferencias dentro de $0,01: ${p.within_tolerance}; bloqueos: ${p.blocker_count}\n` +
      `Diferencias O+P frente a Q presentes en el original: ${p.source_arithmetic_difference_count}. Se conservarán para el control RN13.\n` +
      p.blocker_locators.join("\n");
    document.querySelector("#confirm-button").disabled = !p.can_confirm || !document.querySelector("#period-confirmed").checked;
  } catch (error) { clearPreview(); message.textContent = error.message; }
});

document.querySelector("#confirm-button").addEventListener("click", async () => {
  if (!currentPreview || !selectedDataset || !document.querySelector("#period-confirmed").checked) return;
  const batchId = document.querySelector("#invoice-batch").value;
  if (batchId !== currentPreview.batch_id || document.querySelector("#invoice-period").value !== currentPreview.period) return;
  try {
    const result = await request(`/api/datasets/${selectedDataset.id}/batches/${batchId}/invoice-import`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ period: currentPreview.period, expected_version: selectedDataset.version,
                             period_confirmed: true })
    });
    message.textContent = `Importación registrada: ${result.row_count || result.physical_rows} filas; revisión en preparación.`;
    await refresh();
  } catch (error) { message.textContent = error.message; }
});

function clearAuthorizationPreview() {
  authorizationEpoch += 1;
  authorizationPreview = null;
  document.querySelector('#authorization-summary').textContent = '';
  document.querySelector('#authorization-observations').replaceChildren();
  document.querySelector('#authorization-details').replaceChildren();
  document.querySelector('#authorization-import-button').disabled = true;
  document.querySelector('#authorization-original').hidden = true;
}

async function refreshAuthorizationIntake(preferredUploadId) {
  clearAuthorizationPreview();
  const epoch = authorizationEpoch;
  const datasetId = selectedDataset?.id;
  if (!datasetId) return;
  const inventory = await request(`/api/datasets/${datasetId}/authorization-captures`);
  if (epoch !== authorizationEpoch || selectedDataset?.id !== datasetId) return;
  selectedDataset.version = inventory.dataset_version;
  for (const item of document.querySelectorAll('#datasets li[data-dataset-id]')) {
    if (item.dataset.datasetId === datasetId) item.textContent = `${selectedDataset.label} · versión ${inventory.dataset_version}`;
  }
  const selector = document.querySelector('#authorization-upload');
  const previous = preferredUploadId || selector.value;
  selector.replaceChildren();
  for (const upload of inventory.uploads) {
    const option = document.createElement('option');
    option.value = upload.id;
    option.textContent = `${upload.original_name} · SHA ${upload.source_sha256.slice(0, 12)} · ${upload.capture_id ? `incorporado v${upload.imported_ordinal}` : 'pendiente de incorporación'}`;
    selector.append(option);
  }
  if (inventory.uploads.some((item) => item.id === previous)) selector.value = previous;
  document.querySelector('#authorization-preview-button').disabled = !inventory.uploads.length;
  const history = document.querySelector('#authorization-history');
  history.replaceChildren();
  for (const capture of inventory.captures) {
    const item = document.createElement('li');
    item.textContent = `${capture.data_origin === 'synthetic' ? 'DATOS FICTICIOS' : 'ORIGEN REAL SIN VALIDAR'} · ${capture.source_system}/${capture.stream_id} · versión recibida ${capture.ordinal} · ${capture.is_latest_import ? 'última recibida' : 'histórica'} · ${capture.summary.orders} órdenes, ${capture.summary.items} prácticas\n` +
      `${capture.actor_username} · ${capture.created_at} · ${capture.provenance_note}\nSHA-256 ${capture.source_sha256}`;
    history.append(item);
  }
  if (!inventory.captures.length) history.textContent = 'Todavía no hay capturas incorporadas.';
  await refreshCorrespondenceScope(inventory);
}

function authorizationTable(parent, title, columns, rows) {
  const heading = document.createElement('p');
  heading.textContent = `${title} (${rows.length})`;
  const table = document.createElement('table');
  const header = document.createElement('tr');
  for (const [label] of columns) {
    const cell = document.createElement('th'); cell.textContent = label; header.append(cell);
  }
  table.append(header);
  for (const row of rows.slice(0, 100)) {
    const line = document.createElement('tr');
    for (const [, key] of columns) {
      const cell = document.createElement('td');
      const value = row[key];
      cell.textContent = value === null || value === undefined || value === '' ? 'No informado' : Array.isArray(value) ? value.join(', ') || 'No informado' : String(value);
      line.append(cell);
    }
    table.append(line);
  }
  parent.append(heading, table);
  if (rows.length > 100) {
    const note = document.createElement('p'); note.textContent = 'Se muestran los primeros 100 registros; el original conserva todos.'; parent.append(note);
  }
}

async function showAuthorizationPreview() {
  clearAuthorizationPreview();
  const epoch = authorizationEpoch;
  const datasetId = selectedDataset?.id;
  const uploadId = document.querySelector('#authorization-upload').value;
  if (!datasetId || !uploadId) return;
  const p = await request(`/api/datasets/${datasetId}/authorization-uploads/${uploadId}/preview`);
  if (epoch !== authorizationEpoch || selectedDataset?.id !== datasetId || document.querySelector('#authorization-upload').value !== uploadId) return;
  authorizationPreview = {data: p, datasetId, uploadId};
  selectedDataset.version = p.dataset_version;
  const original = document.querySelector('#authorization-original');
  original.href = `/api/datasets/${datasetId}/authorization-uploads/${uploadId}/file`;
  original.hidden = false;
  const summary = document.querySelector('#authorization-summary');
  if (p.technical_state === 'format_error') {
    summary.textContent = `ERROR DE FORMATO. El original se conserva, pero no se puede incorporar.\nSHA-256 ${p.upload.source_sha256}\n` + p.format_errors.map((e) => `${e.path}: ${e.code}`).join('\n');
    return;
  }
  const s = p.summary;
  summary.textContent = `${s.data_origin === 'synthetic' ? 'DATOS FICTICIOS: no acreditan validación real.' : 'ORIGEN DECLARADO REAL: intercambio sin validar.'}\n` +
    `Formato interpretado: ${s.schema_version} · ${s.parser_version}\nSistema/flujo: ${s.source.system}/${s.source.stream_id}\n` +
    `Órdenes: ${s.orders}; prácticas: ${s.items}; resoluciones: ${s.resolutions}\n` +
    `Cobertura declarada: ${{unknown: 'desconocida', partial: 'parcial', complete: 'completa'}[s.declared_coverage.declared]} · NO VERIFICADA\n${s.declared_coverage.description}\n` +
    `Período declarado: ${s.declared_coverage.period || 'no informado'}; limitaciones: ${s.declared_coverage.limitations.join('; ') || 'no informadas'}\n` +
    `Observaciones: ${p.observations.length}; órdenes con posible ambigüedad: ${s.potentially_ambiguous_orders}; con contradicción aparente: ${s.orders_with_apparent_conflict}\n` +
    (s.adapter_provenance ? `Adaptador local: captura PARCIAL, intercambio actual NO VALIDADO. Filas sin representación: ${s.adapter_provenance.unrepresented_rows}. Sin autorización inferida por ítem.\nSHA-256 A1 derivado: ${s.adapter_provenance.output_sha256}\n` : '') +
    `SHA-256 original: ${p.upload.source_sha256}\n` +
    (p.reinterpretation_required ? 'Hay una interpretación nueva del mismo original. Confirmarla conserva la captura anterior. Luego seleccioná la nueva captura y reanalizá explícitamente; no cambia cierres ni decisiones.\n' : '') +
    (p.upload.capture_id ? `Ya incorporada como versión ${p.upload.imported_ordinal}; consultar no la reactiva ni crea otra versión.\n` : '') +
    'Importar no ejecuta análisis, no relaciona con Excel y no acredita cobertura ni aplicabilidad económica. Importe: por determinar.';
  const observations = document.querySelector('#authorization-observations');
  for (const observation of [...p.context_errors, ...p.observations].slice(0, 100)) {
    const item = document.createElement('li'); item.textContent = `${observation.path} · ${observation.code}: ${observation.message}`; observations.append(item);
  }
  if (p.observations.length > 100) {
    const item = document.createElement('li'); item.textContent = 'Se muestran las primeras 100 observaciones; la captura conserva la lista completa.'; observations.append(item);
  }
  const details = document.querySelector('#authorization-details');
  for (const order of p.canonical.orders.slice(0, 20)) {
    const block = document.createElement('details');
    const heading = document.createElement('summary');
    heading.textContent = `Orden ${order.order_id || 'sin ID'} · afiliado ${order.affiliate_id || 'no informado'} · prestador ${order.provider || 'no informado'} · estado global declarado: ${order.global_status || 'no informado'}`;
    block.append(heading);
    authorizationTable(block, 'Prácticas declaradas', [['ID', 'item_id'], ['Código completo', 'full_code'], ['Descripción', 'description'], ['Cantidad solicitada', 'requested_quantity'], ['Unidad', 'unit'], ['Fecha informada', 'service_date']], order.items);
    authorizationTable(block, 'Resoluciones declaradas (sin elegir la aplicable)', [['ID', 'resolution_id'], ['Alcance', 'scope'], ['Ítems', 'item_ids'], ['Estado', 'status'], ['Cantidad declarada', 'authorized_quantity'], ['Unidad', 'unit'], ['Fecha informada', 'decided_at'], ['Reemplazo declarado', 'supersedes_resolution_id']], order.resolutions);
    details.append(block);
  }
  if (p.canonical.orders.length > 20) details.append(document.createTextNode('Se muestran las primeras 20 órdenes; el original conserva todas.'));
  document.querySelector('#authorization-import-button').disabled = !p.can_import || (Boolean(p.upload.capture_id) && !p.reinterpretation_required);
  document.querySelector('#authorization-import-button').textContent = p.reinterpretation_required ? 'Confirmar nueva interpretación (conservar historia)' : 'Confirmar incorporación';
}

document.querySelector('#authorization-upload').addEventListener('change', clearAuthorizationPreview);
document.querySelector('#authorization-preview-button').addEventListener('click', async () => {
  try { await showAuthorizationPreview(); } catch (error) { clearAuthorizationPreview(); message.textContent = error.message; }
});
document.querySelector('#authorization-upload-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const file = document.querySelector('#authorization-file').files[0];
  const datasetId = selectedDataset?.id;
  if (!file || !datasetId) return;
  const button = event.currentTarget.querySelector('button');
  button.disabled = true;
  clearAuthorizationPreview();
  try {
    const result = await request(`/api/datasets/${datasetId}/authorization-uploads`, {method: 'POST', body: file,
      headers: {'X-Expected-Version': String(selectedDataset.version), 'X-Source-Filename': file.name, 'Content-Type': 'application/octet-stream'}});
    if (selectedDataset?.id !== datasetId) return;
    await refreshAuthorizationIntake(result.id);
    await showAuthorizationPreview();
    message.textContent = result.capture_id ? 'Original repetido reconocido; se conserva su captura anterior.' : 'Original conservado por hash. Revisá la vista previa y registrá su procedencia.';
  } catch (error) { message.textContent = `${error.message}. Si cambió la versión, actualizá la página antes de reintentar.`; }
  finally { button.disabled = false; }
});
document.querySelector('#authorization-import-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const context = authorizationPreview;
  if (!context?.data.can_import || context.datasetId !== selectedDataset?.id || context.uploadId !== document.querySelector('#authorization-upload').value) return;
  const button = document.querySelector('#authorization-import-button');
  button.disabled = true;
  try {
    const result = await request(`/api/datasets/${context.datasetId}/authorization-uploads/${context.uploadId}/import`, {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
        expected_version: context.data.dataset_version, preview_sha256: context.data.preview_sha256,
        provenance_note: document.querySelector('#authorization-provenance').value,
        reinterpret_capture_id: context.data.reinterpretation_required ? context.data.previous_capture_id : null})});
    if (selectedDataset?.id !== context.datasetId) return;
    document.querySelector('#authorization-provenance').value = '';
    await refreshSources();
    message.textContent = `Captura ${result.created ? 'incorporada' : 'ya existente'}, versión recibida ${result.ordinal}. Historia conservada; análisis sin ejecutar; cobertura sin verificar; importes por determinar.`;
  } catch (error) {
    clearAuthorizationPreview();
    message.textContent = `${error.message}. Volvé a consultar la vista previa; si cambió la versión, actualizá la página.`;
  }
});

document.querySelector("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const formElement = event.currentTarget;
  const form = new FormData(formElement);
  try {
    const result = await request("/api/session", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: form.get("username"), password: form.get("password") })
    });
    csrfToken = result.csrf_token;
    document.querySelector("#invoice-batch").replaceChildren();
    formElement.reset();
    await refresh();
  } catch (error) { message.textContent = error.message; }
});

document.querySelector("#logout").addEventListener("click", async () => {
  try { await request("/api/session", { method: "DELETE" }); } catch (_) { /* Session may have expired. */ }
  csrfToken = null;
  if(typeof resetMedicalConsultations==='function')resetMedicalConsultations();
  if(typeof observationSession==='function')observationSession();
  await refresh();
});

document.querySelector("#dataset-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const formElement = event.currentTarget;
  const form = new FormData(formElement);
  try {
    await request("/api/datasets", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ label: form.get("label") })
    });
    document.querySelector('#dataset-management').open = false;
    formElement.reset();
    await refresh();
  } catch (error) { message.textContent = error.message; }
});

function correspondenceBase(datasetId = selectedDataset?.id, batchId = document.querySelector('#invoice-batch').value) {
  return `/api/datasets/${datasetId}/batches/${batchId}`;
}

function clearCorrespondence() {
  correspondenceEpoch += 1;
  correspondenceContext = null;
  document.querySelector('#authorization-match-summary').textContent = '';
  document.querySelector('#authorization-match-candidates').replaceChildren();
  document.querySelector('#authorization-link-candidate').replaceChildren();
  document.querySelector('#authorization-link-history').textContent = '';
  document.querySelector('#authorization-link-save').disabled = true;
  document.querySelector('#authorization-link-state').value = 'unresolved';
  document.querySelector('#authorization-link-note').value = '';
}

function showExportPeriod(range=null){
  const check=document.querySelector('#csv-complete'),period=document.querySelector('#csv-export-period');
  check.checked=Boolean(range);period.hidden=!check.checked;
  for(const [i,id] of ['#csv-complete-from','#csv-complete-until'].entries()){
    const field=document.querySelector(id);field.required=check.checked;field.value=range?.[i] || '';
  }
}
document.querySelector('#csv-complete').addEventListener('change',event=>showExportPeriod(event.target.checked?['','']:null));
document.querySelector('#authorization-scope-captures').addEventListener('change',()=>showExportPeriod());
let csvSelectionSnapshot=null;
async function refreshCorrespondenceScope(inventory) {
  csvSelectionSnapshot=null;
  updateIntake();
  showExportPeriod();
  clearCorrespondence();
  const epoch = correspondenceEpoch;
  const datasetId = selectedDataset?.id;
  const batchId = document.querySelector('#invoice-batch').value;
  const summary = document.querySelector('#authorization-scope-summary');
  const selector = document.querySelector('#authorization-scope-captures');
  selector.replaceChildren();
  summary.textContent = 'Elegí un lote Excel importado para seleccionar sus fuentes de autorizaciones.';
  if (!datasetId || !batchId) return;
  try {
    const sources = inventory || await request(`/api/datasets/${datasetId}/authorization-captures`);
    const scope = await request(`${correspondenceBase(datasetId, batchId)}/authorization-scope`);
    if (epoch !== correspondenceEpoch || selectedDataset?.id !== datasetId || document.querySelector('#invoice-batch').value !== batchId) return;
    selectedDataset.version = scope.dataset_version;
    csvSelectionSnapshot={datasetId,batchId,version:scope.dataset_version};
    for (const capture of sources.captures.filter(c => c.is_latest_import)) {
      const option = document.createElement('option'); option.value = capture.id;
      option.textContent = `${capture.data_origin === 'synthetic' ? 'FICTICIO' : 'REAL SIN VALIDAR'} · ${capture.source_system}/${capture.stream_id} · v${capture.ordinal}`;
      option.selected = Boolean(scope.current?.capture_ids.includes(capture.id));
      selector.append(option);
    }
    if (scope.current) document.querySelector('#authorization-scope-mode').value = scope.current.mode;
    const chosen=sources.captures.filter(c=>scope.current?.capture_ids.includes(c.id));
    updateIntake(!scope.issues.length && chosen.some(c=>c.source_system==='HPC-CSV' && c.is_latest_import),Boolean(scope.current?.csv_complete_range));
    showExportPeriod(scope.current?.csv_complete_range);
    const periodText=scope.current?.csv_complete_range?.join(' a ');
    const coverageText=scope.csv_export_limitation || (periodText?'Período completo declarado: '+periodText:'Cobertura del CSV sin confirmar.');
    summary.textContent = scope.current
      ? `Lote ${document.querySelector('#invoice-batch').selectedOptions[0]?.textContent} · selección v${scope.current.ordinal} · ${scope.current.mode === 'synthetic_demo' ? 'DATOS FICTICIOS' : 'Origen real sin validar'}\n` +
        `Capturas elegidas: ${sources.captures.filter(c => scope.current.capture_ids.includes(c.id)).map(c => `${c.source_system}/${c.stream_id} v${c.ordinal}`).join('; ')}\n${scope.current.actor_username} · ${scope.current.note}\n${scope.issues.length ? 'Requiere actualizar la selección: captura reemplazada o fuente no verificable.' : coverageText}\nHistoria: ${scope.history.length} versiones. No se ejecutó análisis.`
      : 'Sin selección de fuentes para este lote. Seleccionar no implica cobertura verificada ni autorización aprobada.';
  } catch (error) { if (epoch === correspondenceEpoch) summary.textContent = error.message; }
}

const correspondenceLabels = {outside_scope:'Fuera del alcance operativo', scope_missing:'Fuentes no seleccionadas', requires_update:'Requiere actualizar fuentes', identity_or_code_unresolved:'Identidad o código insuficiente', ambiguous:'Varios candidatos: asociación ambigua', unambiguous_candidate:'Correspondencia candidata unívoca; autorización sin concluir', needs_review:'Correspondencia incompleta: requiere evidencia', incompatible_candidates:'Candidatos con fecha o prestador incompatibles', no_authorization_located:'Sin autorización localizada en la fuente; no demuestra rechazo', candidate_limit:'Demasiados candidatos: no se permite asignar'};

async function showCorrespondence() {
  clearCorrespondence();
  const epoch = correspondenceEpoch;
  const datasetId = selectedDataset?.id;
  const batchId = document.querySelector('#invoice-batch').value;
  const row = document.querySelector('#authorization-match-row').value;
  if (!datasetId || !batchId || !row) return;
  const data = await request(`${correspondenceBase(datasetId,batchId)}/rows/${row}/authorization-correspondence`);
  if (epoch !== correspondenceEpoch || selectedDataset?.id !== datasetId || document.querySelector('#invoice-batch').value !== batchId) return;
  correspondenceContext = {data, datasetId, batchId, row};
  selectedDataset.version = data.dataset_version;
  document.querySelector('#authorization-match-summary').textContent =
    `${data.mode === 'synthetic_demo' ? 'DATOS FICTICIOS' : 'INTERCAMBIO REAL SIN VALIDAR'} · ${data.invoice_locator}\n${correspondenceLabels[data.state] || data.state}\n` +
    `Candidatos mostrados: ${data.candidates.length}; total: ${data.candidate_count_total ?? 0}\nAfiliado (C): ${data.invoice_fields.C || 'no informado'} · código completo (E): ${data.invoice_fields.E || 'no informado'}\nDescripción (K): ${data.invoice_fields.K || 'no informada'} · fecha ${data.practice_date}\nAutorización: no concluyente. Cobertura sin verificar; unidades e importes por determinar.`;
  const panel = document.querySelector('#authorization-match-candidates');
  const selector = document.querySelector('#authorization-link-candidate');
  for (const candidate of data.candidates) {
    const details = document.createElement('details');
    const heading = document.createElement('summary');
    const resolutionLabel = {declared_authorized:'autorizada según la fuente',declared_rejected:'rechazada según la fuente',declared_referred:'derivada según la fuente',declared_pending:'pendiente según la fuente',declared_unknown:'desconocida según la fuente',apparent_conflict:'contradicción aparente: requiere revisión',unresolved:'alcance no resuelto',multiple_or_unidentified_resolutions:'varias resoluciones o identidad insuficiente',uninterpreted_status:'estado sin interpretación'}[candidate.resolution.state] || 'sin conclusión';
    heading.textContent = `${candidate.order_id || 'Orden sin ID'}/${candidate.item.item_id || 'ítem sin ID'} · ${{compatible:'Correspondencia compatible',incompatible:'Fecha o prestador incompatibles',needs_review:'Datos insuficientes o descripción diferente'}[candidate.compatibility]} · ${resolutionLabel}`;
    const body = document.createElement('pre');
    const checks = {identity:'DNI normalizado',complete_code:'Código completo',provider:'Prestador HPC',date:'Fecha de realización',description:'Descripción',unique_ids:'Identificadores de orden e ítem unívocos'};
    body.textContent = `Origen: ${candidate.data_origin === 'synthetic' ? 'DATOS FICTICIOS' : 'Fuente real sin validar'} · captura recibida v${candidate.capture_ordinal}\n` +
      `Afiliado original de autorización: ${candidate.affiliate_original}\nCódigo: ${candidate.item.full_code} · ${candidate.item.description || 'sin descripción'}\nPrestador: ${candidate.provider || 'no informado'} · fecha informada: ${candidate.item.service_date || 'no informada'}\n` +
      `Cantidad solicitada declarada: ${candidate.item.requested_quantity ?? 'desconocida'} · unidad ${candidate.item.unit || 'desconocida'}\n` +
      Object.entries(checks).map(([key,label]) => `${label}: ${candidate.checks[key] === true ? 'coincidencia suficiente para candidato' : candidate.checks[key] === false ? 'diferente o no unívoco' : 'no informado'}`).join('\n') +
      `\nLocalizador JSON: ${candidate.locator}\nSHA-256 del original: ${candidate.source_sha256}\nEl estado global no aprueba todos los ítems. Las resoluciones siguientes son declaraciones de la fuente, sin elegir la aplicable.`;
    details.append(heading, body);
    authorizationTable(details,`Resoluciones de la orden: ${candidate.resolution.records.length} de ${candidate.resolution.records_total}`, [['ID','resolution_id'],['Alcance declarado','scope'],['Ítems declarados','item_ids'],['Estado declarado','status'],['Cantidad declarada','authorized_quantity'],['Unidad','unit'],['Fecha informada','decided_at'],['Reemplazo declarado','supersedes_resolution_id'],['Motivo declarado','reason_display'],['Afecta expresamente este ítem','affects_label']], candidate.resolution.records.map(r=>({...r,reason_display:`${r.reason || 'No informado'}${r.reason_truncated ? ' [fragmento: consultar original]' : ''}${r.item_ids_truncated ? ' [lista de ítems parcial: consultar original]' : ''}`,affects_label:r.targets_item === true ? 'Sí' : r.targets_item === false ? 'No' : 'No determinado'})));
    if (candidate.resolution.records_truncated) details.append(document.createTextNode('Vista limitada a 20 resoluciones; consultar el original para la orden completa. No se elige una resolución aplicable.'));
    panel.append(details);
    if (candidate.compatibility === 'compatible') {
      const option = document.createElement('option'); option.value = candidate.key;
      option.textContent = `${candidate.order_id}/${candidate.item.item_id} · ${candidate.locator}`;
      selector.append(option);
    }
  }
  if (data.catalog_relationships) {
    const related = data.catalog_relationships;
    const note = document.createElement('p');
    note.textContent = `Candidatos por catálogo HPC: ${related.candidate_count_total}. ${related.use_limit}`;
    panel.append(note);
    for (const candidate of related.candidates) {
      const details = document.createElement('details');
      const heading = document.createElement('summary');
      heading.textContent = `${candidate.order_id || 'Orden sin ID'} · ${candidate.relation.invoice_code} → ${candidate.item.full_code} · ${candidate.compatibility === 'incompatible' ? 'Fecha o prestador incompatible' : 'Enlace de catálogo para revisar'}`;
      const body = document.createElement('pre');
      body.textContent = `${candidate.relation.category_is_broad ? 'Categoría amplia del nomenclador: varias prácticas posibles; NO equivalencia.' : candidate.relation.basis === 'explicit_neutral_category_to_hpc' ? 'Enlace explícito del nomenclador a HPC; equivalencia por verificar.' : 'Enlace explícito entre códigos HPC; equivalencia por verificar.'}\nIdentidad de práctica en catálogo: ${candidate.relation.practice_id}\nPráctica: ${candidate.item.description || 'sin descripción'}\nFecha de prestación: ${candidate.item.service_date || 'no informada'}\nLocalizador: ${candidate.locator}\nCatálogo SHA-256: ${candidate.relation.source_sha256}\nFilas de códigos: ${candidate.relation.invoice_code_seqs.join(', ')} → ${candidate.relation.authorization_code_seqs.join(', ')}\nNo seleccionable como correspondencia exacta. No acredita autorización individual ni cantidad.`;
      details.append(heading, body); panel.append(details);
    }
  }
  document.querySelector('#authorization-link-save').disabled = data.disposition !== 'included' || data.issues.length > 0;
  document.querySelector('#authorization-link-history').textContent = data.human_link.history.length
    ? data.human_link.history.map(v => `Vínculo humano v${v.ordinal}: ${v.state === 'selected' ? 'Seleccionado con evidencia' : 'No resuelto'} · ${v.actor_username} · ${v.created_at}\n${v.note}`).join('\n\n') + `\nÚltimo vínculo: ${data.human_link.current.freshness === 'current' ? 'vigente para esta correspondencia' : 'requiere actualización'}. Nunca se vuelve a uno anterior.`
    : 'Sin versiones de vínculo humano. El resultado automático se conserva separado de esa decisión.';
}

document.querySelector('#invoice-batch').addEventListener('change', () => refreshCorrespondenceScope());
document.querySelector('#authorization-match-row').addEventListener('input', clearCorrespondence);
document.querySelector('#authorization-scope-form').addEventListener('submit', async event => {
  event.preventDefault();
  const datasetId = selectedDataset?.id, batchId = document.querySelector('#invoice-batch').value;
  if (!datasetId || !batchId) return;
  try {
    if(csvSelectionSnapshot?.datasetId!==datasetId || csvSelectionSnapshot.batchId!==batchId){
      message.textContent='Actualizá la selección de fuentes de esta factura.';return;
    }
    await request(`${correspondenceBase(datasetId,batchId)}/authorization-scope`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({
      expected_version:csvSelectionSnapshot.version, capture_ids:[...document.querySelector('#authorization-scope-captures').selectedOptions].map(o=>o.value),
      mode:document.querySelector('#authorization-scope-mode').value, note:document.querySelector('#authorization-scope-note').value,
      csv_complete_from:document.querySelector('#csv-complete').checked?document.querySelector('#csv-complete-from').value:null,
      csv_complete_until:document.querySelector('#csv-complete').checked?document.querySelector('#csv-complete-until').value:null,
      synthetic_invoice_confirmed:document.querySelector('#authorization-demo-invoice').checked})});
    if (selectedDataset?.id !== datasetId || document.querySelector('#invoice-batch').value !== batchId) return;
    await refreshCorrespondenceScope(); message.textContent = 'Selección guardada. Si cambiaron las fuentes o el período, actualizá los controles en Procesamiento.';
  } catch(error) {
    if(error.status===409)await refreshCorrespondenceScope();
    else clearCorrespondence();
    message.textContent=error.message;
  }
});
document.querySelector('#authorization-match-form').addEventListener('submit', async event => {
  event.preventDefault(); try { await showCorrespondence(); } catch(error) { clearCorrespondence(); message.textContent = error.message; }
});
document.querySelector('#authorization-link-form').addEventListener('submit', async event => {
  event.preventDefault();
  const context = correspondenceContext;
  if (!context || context.datasetId !== selectedDataset?.id || context.batchId !== document.querySelector('#invoice-batch').value || context.row !== document.querySelector('#authorization-match-row').value) return;
  const state = document.querySelector('#authorization-link-state').value;
  document.querySelector('#authorization-link-save').disabled = true;
  try {
    await request(`${correspondenceBase(context.datasetId,context.batchId)}/rows/${context.row}/authorization-link`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({
      expected_version:context.data.dataset_version, expected_revision_version:context.data.revision_version,
      basis_sha256:context.data.basis_sha256, state,
      candidate_key:state === 'selected' ? document.querySelector('#authorization-link-candidate').value || null : null,
      note:document.querySelector('#authorization-link-note').value})});
    if (selectedDataset?.id !== context.datasetId || document.querySelector('#invoice-batch').value !== context.batchId) return;
    await showCorrespondence(); message.textContent = 'Versión del vínculo guardada. No aprueba autorización ni asigna unidades o importes.';
  } catch(error) { clearCorrespondence(); message.textContent = `${error.message}. Volvé a consultar antes de guardar.`; }
});

initializeProcessing();
initializeWorkbench();
initializeClosure();
initializeRevisions();
refresh();

const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

test('the HPC PDF selector renders after login with a registered agreement', async () => {
  const source = readFileSync(path.join(__dirname, '..', 'web', 'app.js'), 'utf8');
  const start = source.indexOf('async function refreshHpcDocuments()');
  const end = source.indexOf('\nasync function showHpcValueHistory()', start);
  assert.ok(start >= 0 && end > start);
  const options = [];
  const selector = { replaceChildren() { options.length = 0; }, append(option) { options.push(option); } };
  const document = {
    querySelector(name) {
      if (name === '#hpc-value-document') return selector;
      if (name === '#value-source') return { value: 'source-1' };
      throw new Error(`Unexpected selector: ${name}`);
    },
    createElement(name) {
      assert.equal(name, 'option');
      return {};
    },
  };
  const context = { document, selectedDataset: { id: 'dataset-1' },
    request: async () => [
      { id: 'pdf-1', source_id: 'source-1', category: 'agreement',
        original_name: 'convenio-ficticio.pdf', sha256: 'a'.repeat(64) },
      { id: 'pdf-2', source_id: 'source-2', category: 'agreement',
        original_name: 'otro.pdf', sha256: 'b'.repeat(64) },
    ] };
  const refreshHpcDocuments = vm.runInNewContext(`(${source.slice(start, end).trim()})`, context);
  await refreshHpcDocuments();
  assert.equal(options.length, 1);
  assert.equal(options[0].value, 'pdf-1');
  assert.match(options[0].textContent, /convenio-ficticio.pdf/);
});

function economicUi(handler=async()=>{}) {
  class Node {
    constructor(tag='div'){this.tag=tag;this.children=[];this.listeners={};this.value='';this.textContent='';this.disabled=false;this.checked=false;this.attrs={};}
    append(...nodes){this.children.push(...nodes);}replaceChildren(...nodes){this.children=[...nodes];this.textContent='';}
    addEventListener(k,v){this.listeners[k]=v;}setAttribute(k,v){this.attrs[k]=v;}
    querySelectorAll(selector){return selector.split(',').flatMap(tag=>nodesOf(this,tag));}
    set innerHTML(value){throw new Error('Source HTML must remain text');}
  }
  const content=new Node(),calls=[],selector={value:'source-a'};
  const context={document:{createElement:tag=>new Node(tag),createTextNode:text=>({textContent:text}),querySelector:()=>selector},
    sheetPanel:()=>content,sheetContext:()=>({epoch:1}),sheetCurrent:c=>c.epoch===context.epoch,
    epoch:1,detailText:(parent,label,text)=>{const n=new Node('p');n.textContent=`${label}: ${text}`;parent.append(n);},
    sheetField:(form,label,kind='textarea')=>{const n=new Node(kind);n.label=label;form.append(n);return n;},
    request:async(url,options)=>{calls.push({url,options});return handler(url,options);},
    refreshProcessing:async()=>{context.processingReads=(context.processingReads || 0)+1;},
    refreshSheetAfterWrite:async()=>{context.refreshed=true;}};
  vm.createContext(context);
  const actions=readFileSync(path.join(__dirname,'..','web','sheet_actions.js'),'utf8');
  vm.runInContext(actions.slice(actions.indexOf('async function settleSheetWrite(')),context);
  vm.runInContext(readFileSync(path.join(__dirname,'..','web','economic_applicability.js'),'utf8'),context);
  return {context,content,calls,run:code=>vm.runInContext(code,context)};
}
function economicPage(){return {dataset_version:7,revision_version:4,revision_state:'en_revision',basis_sha256:'frozen-basis',
  basis:{status:'ready_for_applicability',code_complete:'123456789',value_code:'123456',practice_date:'2026-08-16',quantity:'2',candidate:{rate_ars:'15.00',value_version:null}},
  latest:null,history:[],documents:[{id:'pdf-a',original_name:'<img src=x onerror=alert(1)>',sha256:'a'.repeat(64)}],use_limit:'Guardar no ejecuta análisis ni crea propuestas.'};}
function nodesOf(parent,tag){return parent.children.flatMap(n=>n && typeof n==='object'?[...(n.tag===tag?[n]:[]),...nodesOf({children:n.children || []},tag)]:[]);}

test('HPC labels keep unknown codes literal and never interpret prototype keys',()=>{
  const x=economicUi();
  assert.match(x.run('economicStatus("ambiguous_reference")'),/varias referencias/);
  for(const code of ['constructor','__proto__','<script>bad()</script>']){
    const text=x.run(`economicStatus(${JSON.stringify(code)})`);
    assert.match(text,/Estado pendiente de interpretación/);assert.ok(text.includes(code));
  }
});
test('HPC evidence explains row total and reference units with provenance, never a debit',()=>{
  const x=economicUi();
  const evidence={simulation_only:true,code_complete:'123456789',value_code:'123456',rate_ars:'15.00',covered_quantity:'2',
    comparable_total_ars:'30.00',billed_total_ars:'32.00',difference_ars:'2.00',practice_date:'2026-08-16',source:{id:'s',cut_label:'BASE_2026-10-09',source_sha256:'a'.repeat(64)},
    reference:{value_version:null},applicability_id:'ref-a',agreement_document:{original_name:'<b>convenio</b>',sha256:'b'.repeat(64)},confirmation:{page_number:1,excerpt:'Fragmento ficticio',note:'Cotejo ficticio'}};
  const text=x.run(`economicEvidenceText(${JSON.stringify(evidence)})`);
  assert.match(text,/DATOS FICTICIOS/);assert.match(text,/15\.00 por práctica × 2 prácticas = ARS 30\.00/);
  assert.match(text,/32\.00 − comparable ARS 30\.00 = diferencia ARS 2\.00/);assert.match(text,/no se vuelve a multiplicar/);
  assert.match(text,/No confirma irregularidad, propuesta ni débito/);assert.match(text,/<b>convenio<\/b>/);
});
test('HPC delayed response is discarded after changing row context',async()=>{
  let finish;const x=economicUi(()=>new Promise(resolve=>finish=resolve));
  const pending=x.run('showEconomicApplicability(3)');x.context.epoch=2;finish(economicPage());await pending;
  assert.equal(x.content.children.length,0);
});
test('HPC confirmation requires explicit action and keeps version conflicts and input visible',async()=>{
  const x=economicUi(async(url,options)=>{if(options)throw Object.assign(new Error('La revisión cambió'),{status:409});return economicPage();});
  await x.run('showEconomicApplicability(3)');
  const form=nodesOf(x.content,'form')[0],button=nodesOf(form,'button')[0];
  const fields=[...nodesOf(form,'input'),...nodesOf(form,'textarea'),...nodesOf(form,'select')];
  const confirm=fields.find(n=>n.type==='checkbox');
  await form.listeners.submit({preventDefault(){}});assert.equal(x.calls.length,1);
  fields.find(n=>n.label==='Convenio registrado').value='pdf-a';
  fields.find(n=>n.label==='Página del convenio').value='1';
  const note=fields.find(n=>n.label==='Fundamento de aplicación a esta fila');note.value='Fundamento ficticio conservado';
  fields.find(n=>n.label==='Fragmento que respalda ARS, unidad y condiciones').value='<script>literal</script>';
  confirm.checked=true;await form.listeners.submit({preventDefault(){}});
  assert.equal(x.calls.length,2);assert.match(x.calls[1].url,/economic-applicability$/);
  const body=JSON.parse(x.calls[1].options.body);
  assert.equal(body.expected_dataset_version,7);assert.equal(body.expected_revision_version,4);assert.equal(body.basis_sha256,'frozen-basis');
  assert.equal(body.currency,'ARS');assert.equal(body.billing_unit,'practice');assert.equal(body.covered_quantity,'2');
  assert.equal(body.excerpt,'<script>literal</script>');assert.equal(note.value,'Fundamento ficticio conservado');
  assert.match(nodesOf(form,'p').at(-1).textContent,/No se guardó: La revisión cambió/);assert.equal(button.disabled,false);assert.equal(x.context.refreshed,undefined);
  assert.ok(nodesOf(fields.find(n=>n.label==='Convenio registrado'),'option')[0].textContent.includes('<img src=x onerror=alert(1)>'));
});
test('HPC closed revision offers history without a write form',async()=>{
  const p=economicPage();p.revision_state='cerrada';p.history=[{ordinal:1,actor_username:'revisor',created_at:'2026-08-16',state:'confirmed',id:'old',confirmation:{note:'Fundamento histórico'}}];
  const x=economicUi(async()=>p);await x.run('showEconomicApplicability(3)');
  assert.equal(nodesOf(x.content,'form').length,0);assert.equal(x.calls.length,1);
  assert.ok(nodesOf(x.content,'p').some(n=>n.textContent.includes('Fundamento histórico')));
});
test('HPC successful save refreshes processing versions without starting analysis',async()=>{
  const x=economicUi(async(url,options)=>options?{dataset_version:8,revision_version:5}:economicPage());
  await x.run('showEconomicApplicability(3)');
  const form=nodesOf(x.content,'form')[0];nodesOf(form,'input').find(n=>n.type==='checkbox').checked=true;
  await form.listeners.submit({preventDefault(){}});
  assert.equal(x.calls.length,2);assert.equal(x.calls[1].options.method,'POST');assert.match(x.calls[1].url,/economic-applicability$/);
  assert.equal(x.context.processingReads,1);assert.equal(x.context.refreshed,true);
  assert.ok(x.calls.every(c=>!c.url.includes('processing-attempts') && !c.url.includes('control-runs')));
});

function rn14Ui(handler=async()=>{}) {
  const x=economicUi(handler);Object.assign(x.context,{decisionLabels:{pendiente:'Pendiente',confirmada:'Confirmada',descartada:'Descartada',no_concluyente:'No concluyente'},
    sheetContext:()=>({datasetId:'dataset-a',batchId:'batch-a',epoch:1}),
    sheetButton:(text,handler)=>{const n=x.context.document.createElement('button');n.textContent=text;n.addEventListener('click',handler);return n;}});
  vm.runInContext(readFileSync(path.join(__dirname,'..','web','rn14_proposals.js'),'utf8'),x.context);return x;
}
function rn14Page(simulation=true){return {simulation_only:simulation,state:'ready',decision:'confirmada',alert_id:null,can_save:true,
  dataset_version:7,revision_version:4,revision_state:'revision',automatic_amount_ars:'2.00',preview_sha256:'exact-preview',
  evidence:null,proposal_history:[],simulation_history:[],latest_evaluation:null};}
test('RN14 clearly separates simulated amounts, determined zero and unknown',async()=>{
  const p=rn14Page();p.latest_evaluation={simulation_only:true,state:'current',simulated_amount_ars:'0.00'};
  const x=rn14Ui(async()=>p);await x.run('showRn14Proposal(3)');
  const text=nodesOf(x.content,'p').map(n=>n.textContent).join('\n');
  assert.match(text,/SIMULACIÓN DEMO/);assert.match(text,/No es una propuesta real/);assert.match(text,/Importe simulado vigente: 0\.00/);
  p.latest_evaluation.simulated_amount_ars=null;await x.run('showRn14Proposal(3)');
  assert.ok(nodesOf(x.content,'p').some(n=>n.textContent==='Importe simulado vigente: Por determinar'));
  for(const code of ['constructor','__proto__','<script>x</script>'])assert.ok(x.run(`rn14ReviewLabel(${JSON.stringify(code)})`).includes(`Estado sin etiqueta: ${code}`));
});
test('RN14 adjustment is an explicit amount action with exact versions and conflict-safe input',async()=>{
  const x=rn14Ui(async(url,options)=>{if(options)throw Object.assign(new Error('Versión obsoleta'),{status:409});return rn14Page();});await x.run('showRn14Proposal(3)');
  const form=nodesOf(x.content,'form')[0],fields=[...nodesOf(form,'input'),...nodesOf(form,'textarea'),...nodesOf(form,'select')];
  const action=fields.find(n=>n.label==='Tratamiento del importe'),amount=fields.find(n=>n.label==='Importe ajustado ARS'),ack=fields.find(n=>n.type==='checkbox');
  assert.equal(amount.disabled,true);await form.listeners.submit({preventDefault(){}});assert.equal(x.calls.length,1);
  action.value='adjust';action.listeners.change();assert.equal(amount.disabled,false);assert.equal(amount.required,true);amount.value='1.50';
  const calculation=fields.find(n=>n.label==='Cálculo del ajuste'),reason=fields.find(n=>n.label==='Fundamento del ajuste');calculation.value='2.00 - 0.50 = 1.50';reason.value='<img src=x> fundamento ficticio';ack.checked=true;
  await form.listeners.submit({preventDefault(){}});assert.equal(x.calls.length,2);
  const body=JSON.parse(x.calls[1].options.body);assert.deepEqual(body,{expected_dataset_version:7,expected_revision_version:4,preview_sha256:'exact-preview',action:'adjust',adjusted_ars:'1.50',adjustment_calculation:calculation.value,adjustment_reason:reason.value});
  assert.equal(amount.value,'1.50');assert.match(nodesOf(form,'p').at(-1).textContent,/No se guardó: Versión obsoleta/);assert.equal(x.context.refreshed,undefined);
  assert.equal(x.calls.some(c=>c.url.includes('/decisions')),false);
});
test('RN14 delayed response after navigation cannot render or save another case',async()=>{
  let finish;const x=rn14Ui(()=>new Promise(resolve=>finish=resolve));const pending=x.run('showRn14Proposal(3)');x.context.epoch=2;finish(rn14Page());await pending;
  assert.equal(x.content.children.length,0);assert.equal(x.calls.length,1);
});
test('RN14 closed history keeps automatic and adjusted calculation as inert text without actions',async()=>{
  const p=rn14Page();p.state='closed_revision';p.revision_state='cerrada';p.alert_id='old-alert';
  p.simulation_history=[{id:'s1',simulation_only:true,ordinal:2,actor_username:'revisor',created_at:'2026-08-16',payload_at_save:{amount_ars:'1.50',components:[{automatic_amount_ars:'2.00',amount_ars:'1.50',adjustment_calculation:'2 - 0.5',adjustment_reason:'<img src=x> evidencia ficticia'}]}}];
  const x=rn14Ui(async()=>p);await x.run('showRn14Proposal(3)');assert.equal(nodesOf(x.content,'form').length,0);assert.equal(nodesOf(x.content,'button').length,0);
  const text=nodesOf(x.content,'p').map(n=>n.textContent).join('\n');assert.match(text,/Automático ARS 2\.00; revisado ARS 1\.50/);assert.match(text,/<img src=x>/);assert.match(text,/SIMULACIÓN DEMO · versión 2/);
});
test('RN14 confirmation refreshes processing versions and does not start analysis or change decisions',async()=>{
  const x=rn14Ui(async(url,options)=>options?{id:'sim1',simulation_only:true,amount_ars:null,simulated_amount_ars:'2.00'}:rn14Page());await x.run('showRn14Proposal(3)');
  const form=nodesOf(x.content,'form')[0];nodesOf(form,'input').find(n=>n.type==='checkbox').checked=true;
  await form.listeners.submit({preventDefault(){}});assert.equal(x.calls.length,2);assert.equal(x.context.processingReads,1);assert.equal(x.context.refreshed,true);
  assert.deepEqual(JSON.parse(x.calls[1].options.body),{expected_dataset_version:7,expected_revision_version:4,preview_sha256:'exact-preview',action:'confirm'});
  assert.ok(x.calls.every(c=>c.url.endsWith('/rows/3/rn14-proposal')));
});
test('RN14 finding review uses existing individual decisions, without creating a proposal',async()=>{
  const p=rn14Page();p.can_save=false;p.state='finding_not_confirmed';p.decision='pendiente';p.alert_id='alert-rn14';
  const x=rn14Ui(async()=>p);Object.assign(x.context,{practicePage:{dataset_version:7,batch:{revision_version:4},items:[{source_row:3,alerts:[{id:'alert-rn14',rule_code:'RN14'}]}]},
    clearSheetSelection:()=>{x.context.cleared=true;},selectSheetAlert:(a,checked)=>{x.context.selected=[a.id,checked];},showSheetDecisionPreview:()=>{x.context.decisionsShown=true;}});
  await x.run('showRn14Proposal(3)');assert.equal(nodesOf(x.content,'form').length,0);nodesOf(x.content,'button')[0].listeners.click();
  assert.equal(x.context.cleared,true);assert.deepEqual(x.context.selected,['alert-rn14',true]);assert.equal(x.context.decisionsShown,true);assert.equal(x.calls.length,1);
});
for(const kind of ['RN14','HPC'])test(`U1 ${kind} committed POST followed by failed refresh stays saved and cannot resubmit`,async()=>{
 const x=kind==='RN14'?rn14Ui(async(u,o)=>o?{id:'saved'}:rn14Page()):economicUi(async(u,o)=>o?{id:'saved'}:economicPage());
 x.context.refreshProcessing=async()=>{throw new Error('GET unavailable');};
 await x.run(kind==='RN14'?'showRn14Proposal(3)':'showEconomicApplicability(3)');
 const form=nodesOf(x.content,'form')[0];nodesOf(form,'input').find(n=>n.type==='checkbox').checked=true;
 await form.listeners.submit({preventDefault(){}});
 assert.doesNotMatch(nodesOf(form,'p').at(-1).textContent,/No se guardó/);
 assert.match(nodesOf(form,'p').at(-1).textContent,/guardad[ao]/i);
 await form.listeners.submit({preventDefault(){}});assert.equal(x.calls.filter(c=>c.options).length,1);
});
for(const kind of ['RN14','HPC'])test(`U1 ${kind} lost POST only offers read reconciliation, never a fresh write`,async()=>{
 let reads=0;const p=kind==='RN14'?rn14Page():economicPage();
 const handler=async(u,o)=>{if(o)throw new Error('response lost');reads++;return p;};
 const x=kind==='RN14'?rn14Ui(handler):economicUi(handler);
 await x.run(kind==='RN14'?'showRn14Proposal(3)':'showEconomicApplicability(3)');
 const form=nodesOf(x.content,'form')[0];nodesOf(form,'input').find(n=>n.type==='checkbox').checked=true;
 await form.listeners.submit({preventDefault(){}});
 assert.match(nodesOf(form,'p').at(-1).textContent,/Resultado incierto/);
 await form.listeners.submit({preventDefault(){}});assert.equal(x.calls.filter(c=>c.options).length,1);
 await nodesOf(x.content,'button').find(n=>n.textContent==='Comprobar historial sin reenviar').listeners.click();
 assert.equal(reads,2);assert.equal(x.calls.filter(c=>c.options).length,1);assert.equal(nodesOf(form,'button')[0].disabled,true);
 assert.match(nodesOf(x.content,'p').at(-1).textContent,/No demuestra rechazo/);
});
test('U1 withdrawal confirmed then refresh fails cannot be reissued or replaced by another applicability write',async()=>{
 const p=economicPage();p.latest={state:'confirmed'};const x=economicUi(async(u,o)=>o?{id:'withdrawn'}:p);
 x.context.refreshProcessing=async()=>{throw new Error('GET failed');};await x.run('showEconomicApplicability(3)');
 const forms=nodesOf(x.content,'form');await forms[0].listeners.submit({preventDefault(){}});
 assert.match(nodesOf(forms[0],'p').at(-1).textContent,/Guardado confirmado/);
 nodesOf(forms[1],'input').find(n=>n.type==='checkbox').checked=true;await forms[1].listeners.submit({preventDefault(){}});
 assert.equal(x.calls.filter(c=>c.options).length,1);
});
for(const outcome of ['success','unknown'])test(`U1 late ${outcome} after navigation cannot overwrite another view`,async()=>{
 let finish;const x=rn14Ui(async(u,o)=>o?new Promise((resolve,reject)=>{finish=outcome==='success'?resolve:reject;}):rn14Page());
 await x.run('showRn14Proposal(3)');const form=nodesOf(x.content,'form')[0];nodesOf(form,'input').find(n=>n.type==='checkbox').checked=true;
 const pending=form.listeners.submit({preventDefault(){}});x.context.epoch=2;x.content.replaceChildren();x.content.textContent='Another case';
 finish(outcome==='success'?{id:'saved'}:new Error('lost'));await pending;assert.equal(x.content.textContent,'Another case');assert.equal(x.content.children.length,0);assert.equal(x.context.processingReads,undefined);
});
test('U1 revoked refresh after commit preserves success but removes private evidence',async()=>{
 const x=rn14Ui(async(u,o)=>o?{id:'saved'}:rn14Page());x.context.refreshProcessing=async()=>{throw Object.assign(new Error('revoked'),{status:403});};
 await x.run('showRn14Proposal(3)');const form=nodesOf(x.content,'form')[0];nodesOf(form,'input').find(n=>n.type==='checkbox').checked=true;
 await form.listeners.submit({preventDefault(){}});assert.equal(x.content.children.length,0);assert.match(x.content.textContent,/Guardado confirmado/);assert.match(x.content.textContent,/acceso revocado/);
 await form.listeners.submit({preventDefault(){}});assert.equal(x.calls.filter(c=>c.options).length,1);
});


test('found HPC amount remains visible when documentary applicability is missing',async()=>{
  const page=economicPage();page.basis.status='factor_evidence_missing';
  page.basis.candidate={tariff:{amount_cents:1500}};
  page.reference_display={recorded_amount:'15.00',provider:'HPC',code:'123456',source_locator:'hpc_catalog_tariffs.seq=1',
    effective_from:'2026-06-01',valid_until:null,value_version_id:null,
    use_limit:'Importe registrado, no importe aplicable confirmado ni débito.'};
  const x=economicUi(async()=>page);await x.run('showEconomicApplicability(3)');
  const text=nodesOf(x.content,'p').map(n=>n.textContent).join('\n');
  assert.match(text,/Importe encontrado en convenio\/catálogo: 15\.00/);
  assert.match(text,/no importe aplicable confirmado ni débito/);
  assert.doesNotMatch(text,/ARS sin determinar/);
  const select=nodesOf(x.content,'select').find(n=>n.label==='Qué documentar');
  assert.ok(select.children.every(n=>n.value!=='confirmed'));
  assert.equal(x.calls.length,1);
});

test('declared hourly unit, currency and source cut remain visible while application is blocked',async()=>{
  const p=economicPage();p.basis.status='value_version_unit_or_document_incompatible';p.basis.candidate={value_version:{id:'version-hour'}};
  p.reference_display={recorded_amount:'14.00',provider:'HPC',code:'123456',source_locator:'hpc_catalog_tariffs.seq=1',
    value_version_id:'version-hour',effective_from:'2026-08-16',valid_until:null,declared_unit:'por hora',declared_currency:'ARS',
    source_id:'source-hour',source_cut:'BASE_2026-10-09',source_sha256:'b'.repeat(64),use_limit:'Aplicabilidad pendiente; no confirma débito.'};
  const x=economicUi(async()=>p);await x.run('showEconomicApplicability(3)');const text=nodesOf(x.content,'p').map(n=>n.textContent).join('\n');
  assert.match(text,/por hora/);assert.match(text,/ARS/);assert.match(text,/source-hour/);assert.match(text,/BASE_2026-10-09/);
  assert.match(text,/b{64}/);assert.doesNotMatch(text,/14\.00 por práctica/);
});


test('NBU-only candidate does not assert ARS or practice unit without explicit confirmation',async()=>{
  const p=economicPage();p.reference_display={recorded_amount:'15.00',declared_currency:null,declared_unit:null,provider:'HPC',code:'123456',
    source_locator:'hpc_catalog_tariffs.seq=1',source_id:'source1',source_cut:'BASE_2026-10-09',use_limit:'Referencia pendiente'};
  const x=economicUi(async()=>p);await x.run('showEconomicApplicability(3)');
  const text=nodesOf(x.content,'p').map(n=>n.textContent).join('\n');
  assert.match(text,/moneda declarada: sin acreditar/);assert.match(text,/unidad declarada: sin acreditar/);
  assert.match(text,/factor NBU no las confirma/);assert.doesNotMatch(text,/ARS 15\.00 por práctica/);
});
test('legacy unknown amount shows original literal and locator without zero or confirmation',async()=>{
  const p=economicPage();p.basis.status='inconsistent_catalogue_formula';p.basis.candidate={tariff:{amount_cents:'S/D'}};
  p.reference_display={recorded_amount:null,recorded_amount_literal:'S/D',amount_status:'not_interpretable',declared_currency:null,declared_unit:null,
    provider:'HPC',code:'123456',source_locator:'hpc_catalog_tariffs.seq=1',source_id:'source1',source_cut:'BASE_2026-10-09',use_limit:'No es aplicable'};
  const x=economicUi(async()=>p);await x.run('showEconomicApplicability(3)');
  const text=nodesOf(x.content,'p').map(n=>n.textContent).join('\n');
  assert.match(text,/Importe no interpretable/);assert.match(text,/literal registrado: S\/D/);assert.match(text,/hpc_catalog_tariffs.seq=1/);
  assert.doesNotMatch(text,/0\.00/);assert.doesNotMatch(text,/Tarifa evaluada/);
  const select=nodesOf(x.content,'select').find(n=>n.label==='Qué documentar');assert.ok(select.children.every(n=>n.value!=='confirmed'));
});

test('frozen explicit declarations remain labelled historical rather than current or unaccredited',async()=>{
  const p=economicPage();p.revision_state='cerrada';p.latest={historical:true,current:false,state:'confirmed',ordinal:1};
  p.reference_display={recorded_amount:'15.00',declared_currency:'ARS',declared_unit:'por práctica',declaration_state:'historical_confirmation',
    provider:'HPC',code:'123456',source_locator:'hpc_catalog_tariffs.seq=1',source_id:'s',source_cut:'BASE_2026-10-09',use_limit:'Historia conservada'};
  const x=economicUi(async()=>p);await x.run('showEconomicApplicability(3)');
  const text=nodesOf(x.content,'p').map(n=>n.textContent).join('\n');
  assert.match(text,/moneda declarada: ARS/);assert.match(text,/Declaración histórica/);
  assert.doesNotMatch(text,/Aplicabilidad confirmada para esta fila/);assert.doesNotMatch(text,/todavía no confirmada/);
  assert.equal(nodesOf(x.content,'form').length,0);
});

test('dated HPC withdrawal needs explicit confirmation and never runs controls',async()=>{
  const source=readFileSync(path.join(__dirname,'..','web','app.js'),'utf8');
  const start=source.indexOf('async function saveHpcStatus(active)');
  const end=source.indexOf("document.querySelector('#hpc-withdraw-button')",start);
  const nodes={};for(const id of ['value-source','hpc-tariff-seq','hpc-value-from','hpc-value-document','hpc-value-page','hpc-value-excerpt','hpc-value-reason','value-results'])nodes['#'+id]={value:'test',textContent:''};
  nodes['#hpc-tariff-seq'].value='1';nodes['#hpc-value-page'].value='2';nodes['#hpc-value-from'].value='2026-11-01';
  let confirmed=false;const calls=[];
  const c={document:{querySelector:id=>nodes[id]},window:{confirm:()=>confirmed},selectedDataset:{id:'d',version:5},message:{textContent:''},showHpcValueHistory:async()=>{},request:async(url,options)=>{calls.push({url,body:JSON.parse(options.body)});return {dataset_version:6};}};
  const save=vm.runInNewContext('('+source.slice(start,end).trim()+')',c);
  await save(false);assert.equal(calls.length,0);
  confirmed=true;await save(false);assert.equal(calls.length,1);assert.match(calls[0].url,/hpc-status$/);assert.equal(calls[0].body.active,false);assert.equal(c.selectedDataset.version,6);
});

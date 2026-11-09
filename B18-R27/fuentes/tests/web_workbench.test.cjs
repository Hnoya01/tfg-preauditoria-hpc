const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const test=require('node:test');
const source=readFileSync(path.join(__dirname,'..','web','workbench.js'),'utf8');

function setup(handler) {
  class Node {
    constructor(){this.children=[];this.value='';this.hidden=false;this.disabled=false;this.textContent='';this.dataset={};this.options=[];this.selectedOptions=[];this.attrs={};this.classList={values:new Set(),add(v){this.values.add(v);},remove(v){this.values.delete(v);},contains(v){return this.values.has(v);},toggle(v,on){if(on)this.values.add(v);else this.values.delete(v);}};}
    append(...nodes){this.children.push(...nodes);}
    replaceChildren(...nodes){this.children=[...nodes];}
    setAttribute(k,v){this.attrs[k]=v;}
    getAttribute(k){return this.attrs[k];}
    addEventListener(){}
    focus(){}
    get innerHTML(){throw new Error('Use textContent for source values');}
    set innerHTML(v){throw new Error('Unsafe source rendering');}
  }
  const nodes=new Map();
  const get=id=>{if(!nodes.has(id))nodes.set(id,new Node());return nodes.get(id);};
  for(const [id,value] of Object.entries({'invoice-batch':'batch-a','board-scope':'included','board-view':'all','board-sort':'source_row','board-direction':'asc'}))get(`#${id}`).value=value;
  const context={document:{body:new Node(),querySelector:get,querySelectorAll:selector=>selector.startsWith('#board-filters ')?['board-rule','board-state','board-text','board-reset'].map(id=>get(`#${id}`)):[],createElement:()=>new Node(),createTextNode:text=>({textContent:text})},
    Option:function(text,value){const n=new Node();n.textContent=text;n.value=value;return n;},
    selectedDataset:{id:'dataset-a',label:'Ficción',version:1},currentRole:'admin',request:handler,
    message:new Node(),clearCorrespondence(){}};
  vm.createContext(context);vm.runInContext(source,context);
  return {context,get,run:code=>vm.runInContext(code,context)};
}

function page() {
  return {physical_total:1205,scope_counts:{included:1201,excluded:3,indeterminate:1},scope_total:1201,filtered_total:1201,
    offset:500,limit:50,dataset_version:4,filters:{scope:'included',family:'images'},facets:[],
    family_counts:{images:1201,other:0,unclassified:0},classification:{available:true,sources:[{cut_label:'BASE_2026-10-09'}]},
    batch:{original_name:'FICTICIO.xlsx',period:'2026-08',run_freshness:'current',revision_version:2},
    items:Array.from({length:50},(_,i)=>({source_row:502+i,locator:`Hoja1!${502+i}`,practice_date:'2026-08-17',code:'00123456',
      description:'<script>texto ficticio</script>',order_number:'FICT-18',affiliate_id:'000123/4',affiliate_name:'Persona Ficticia',quantity:2,setting:'C',honorarios_ars:'0.00',derechos_ars:'0.00',total_ars:'0.00',disposition:'included',control_counts:{no_concluyente:6,sin_indicios:4,no_evaluado:1},
      state:'no_concluyente',motives:[],decision:'sin_indicios_vigentes'}))};
}

test('server filters stay out of URL, page is bounded and closing evidence preserves position',async()=>{
  const calls=[];
  const {get,run}=setup(async(url,options)=>{
    calls.push({url,options});
    if(url.endsWith('practice-search'))return page();
    return {dataset_version:4,revision_version:2,disposition:'included',practice_date:'2026-08-17',eligibility_reasons:[],
      original_fields:{C:'FICTICIO',E:'00123456'},effective_fields:{C:'FICTICIO',E:'00123456'},
      amounts_original_ars:{honorarios_ars:'0.00',derechos_ars:'0.00',total_ars:'0.00'},invoice:{original_name:'FICTICIO.xlsx',source_sha256:'a'.repeat(64)},
      controls:[],decision_history:[],interpretation_history:[],value_sources:[]};
  });
  get('#board-text').value='Descripción ficticia';
  await run('practiceOffset=500; loadPracticeBoard()');
  assert.equal(calls[0].options.method,'POST');
  assert.ok(!calls[0].url.includes('Descripción'));
  assert.equal(JSON.parse(calls[0].options.body).text,'Descripción ficticia');
  assert.equal(get('#practice-rows').children.length,50);
  assert.match(get('#board-count').textContent,/1\.201/);
  await run('openPracticeDetail(502)');
  assert.equal(get('#practice-detail-panel').hidden,false);
  run('closePracticeDetail()');
  assert.equal(get('#practice-detail-panel').hidden,true);
  assert.equal(get('#board-text').value,'Descripción ficticia');
  assert.equal(run('practiceOffset'),500);
  assert.equal(calls.length,2);
});

test('late response for another dataset is never rendered',async()=>{
  let release;
  const pending=new Promise(resolve=>release=resolve);
  const {context,get,run}=setup(()=>pending);
  const work=run('loadPracticeBoard()');
  context.selectedDataset={id:'dataset-b',label:'Otra ficción',version:1};
  get('#invoice-batch').value='batch-b';
  release(page());await work;
  assert.equal(get('#practice-rows').children.length,0);
  assert.equal(run('practicePage'),null);
});

test('viewer sees no operational section regardless of previous navigation',()=>{
  const {context,get,run}=setup(()=>{});
  context.currentRole='viewer';run('syncWorkspaceNavigation()');
  for(const id of ['invoice-panel','authorization-panel','source-panel','controls-panel','review-workbench','export-panel','workspace-nav','workspace-context'])assert.equal(get(`#${id}`).hidden,true,id);
});

test('a row without execution never presents lack of alerts as a completed evaluation',()=>{
  const {get,run}=setup(()=>{});
  const item=page().items[0];item.control_counts={no_evaluado:11};
  run(`renderPracticeRows(${JSON.stringify([item])})`);
  const row=get('#practice-rows').children[0];
  assert.equal(row.children[13].textContent,'Sin análisis');
});

test('columns keep practice identity, row amounts and unverified review state distinct',()=>{
  const {get,run}=setup(()=>{});
  run(`renderPracticeRows(${JSON.stringify([page().items[0]])})`);
  const cells=get('#practice-rows').children[0].children;
  assert.equal(cells[1].textContent,'<script>texto ficticio</script>');
  assert.match(cells[1].title,/00123456.*Persona Ficticia.*000123\/4.*FICT-18/);
  assert.deepEqual(cells.slice(6,9).map(c=>c.textContent),['0,00','0,00','0,00']);
  assert.equal(cells[12].textContent,'—');
  assert.match(cells[13].title,/controles pendientes/);
  assert.equal(cells[13].children[0].textContent,'7 por comprobar');
});

test('search and image family travel in the POST body without changing control results',async()=>{
  let body;
  const {get,run}=setup(async(url,options)=>{body=JSON.parse(options.body);return page();});
  get('#board-search').value='Persona Ficticia';get('#board-family').value='images';
  await run('loadPracticeBoard()');
  assert.equal(body.search,'Persona Ficticia');assert.equal(body.family,'images');
  assert.match(get('#board-classification').textContent,/BASE_2026-10-09/);
});

test('pending authorizations and prices are named without presenting an approval',()=>{
  const {run}=setup(()=>{});
  const item=page().items[0];item.checks=[{rule:'RN09',state:'no_concluyente'},{rule:'RN14',state:'no_concluyente'}];
  assert.equal(run(`rowObservation(${JSON.stringify(item)})`),'Autorización / valores pendientes');
});

test('filters remain disabled until the latest context query completes',async()=>{
  const releases=[];
  const {get,run}=setup(()=>new Promise(resolve=>releases.push(resolve)));
  const old=run('loadPracticeBoard()');
  assert.equal(get('#board-rule').disabled,true);
  assert.equal(get('#board-next').disabled,true);
  const latest=run('loadPracticeBoard()');
  releases[0](page());await old;
  assert.equal(get('#board-rule').disabled,true);
  assert.equal(get('#board-refresh').disabled,true);
  releases[1](page());await latest;
  assert.equal(get('#board-rule').disabled,false);
  assert.equal(get('#board-refresh').disabled,false);
  run('selectedDataset=null; loadPracticeBoard()');
  assert.equal(get('#board-rule').disabled,true);
});

test('B04 keeps fictional status visible and separates readable evidence from full trace',async()=>{
  const p=page();p.batch.synthetic_data=true;
  const {get,run}=setup(async()=>p);await run('loadPracticeBoard()');
  assert.match(get('#workspace-context-summary').textContent,/FICTICIO/);
  const evidence={authorization_engine_version:'B04-authorizations-v1',data_origin:'synthetic',
    quantity:{authorized:null,billed_joint:null,limitations:['pending_or_ambiguous_association'],members:[]},
    resolution:{reason:'<script>texto ficticio literal</script>'},authorization_source_sha256:'a'.repeat(64)};
  const rendered=run(`evidenceText(${JSON.stringify(evidence)})`);
  assert.match(rendered,/DATOS FICTICIOS/);assert.match(rendered,/Autorizado declarado: Desconocido/);
  assert.match(rendered,/pendientes o ambiguos/);assert.match(rendered,/<script>texto ficticio literal/);
  run(`appendControlEvidence(document.querySelector('#evidence'),${JSON.stringify(evidence)})`);
  const trace=get('#evidence').children[1];
  assert.equal(trace.children[0].textContent,'Trazabilidad de esta captura');
  assert.deepEqual(JSON.parse(trace.children[1].textContent),evidence);
});

test('history labels distinguish origin revision and frozen download without asserting validity',()=>{
 const x=setup(async()=>{});x.run("appendHistoryOrigin(document.querySelector('#history'),{origin_revision_id:'old',origin_revision_ordinal:1,origin_revision_state:'cerrada',origin_closure_id:'closure',origin_is_current_revision:false},'dataset-a','batch-a')");
 const nodes=x.get('#history').children;assert.match(nodes[0].textContent,/revisión 1/);assert.match(nodes[0].textContent,/No acredita vigencia actual/);assert.match(nodes[1].href,/revision_id=old/);
 x.run("appendHistoryOrigin(document.querySelector('#legacy'),{},'dataset-a','batch-a')");assert.match(x.get('#legacy').children[0].textContent,/sin reconstruir/);
});

test('resolved observation is not shown as pending and inconsistency precedes information gaps',()=>{
  const {context,run}=setup(()=>{});context.observationState=s=>s;
  const text=run(`rowObservation({disposition:'included',control_counts:{con_indicios:2,no_concluyente:1},observations:[
    {state:'pending',category:'insufficient_information',reason:'Información faltante'},
    {state:'resolved',category:'inconsistency',reason:'Duplicación ya revisada'},
    {state:'pending',category:'inconsistency',reason:'Suma pendiente'}]})`);
  assert.match(text,/^Suma pendiente/);assert.match(text,/Información faltante/);assert.doesNotMatch(text,/Duplicación/);
});
test('empty workflow list without analysis never means no alerts detected',()=>{
  const {run}=setup(()=>{});
  assert.equal(run(`rowObservation({disposition:'included',control_counts:{no_evaluado:11},observations:[]})`),'Análisis pendiente');
});
test('information request has distinct operational wording for both internal duties',()=>{
  const {context,run}=setup(()=>{});
  vm.runInContext(readFileSync(path.join(__dirname,'..','web','observation_workflow.js'),'utf8'),context);
  assert.equal(run("observationState('waiting_information','auditor')"),'Esperando información');
  assert.equal(run("observationState('waiting_information','administrative')"),'Completar información solicitada');
});

test('arithmetic summary uses exact decimals, labels the original sign and preserves missing data',()=>{
  const {context,run}=setup(()=>{});
  vm.runInContext(readFileSync(path.join(__dirname,'..','web','observation_workflow.js'),'utf8'),context);
  const summary=run(`observationSumSummary({evidence:{amounts_ars:{O:'10.00',P:'20.00',Q:'39.00'}},difference_ars:'-9.00'})`);
  assert.match(summary.summary,/Total informado 39,00 · Suma de honorarios y derechos 30,00 · Diferencia -9,00 \(suma menos informado\)/);
  assert.match(summary.support,/El total informado supera la suma en ARS 9,00/);
  assert.equal(summary.billed,'39,00');
  assert.equal(summary.sum,'30,00');
  assert.equal(summary.brief,'El total informado supera la suma en ARS 9,00.');
  assert.match(run(`observationSumSummary({evidence:{amounts_ars:{O:'20',P:'20',Q:'30'}},difference_ars:'10'})`).support,/La suma supera el total informado en ARS 10,00/);
  assert.match(run(`observationSumSummary({evidence:{amounts_ars:{O:'9007199254740993.10',P:'0.20',Q:'9007199254740993.30'}},difference_ars:'0.00'})`).summary,/Suma de honorarios y derechos 9007199254740993,30/);
  assert.match(run(`observationSumSummary({evidence:{amounts_ars:{O:'10',P:null,Q:'39'}},difference_ars:null})`).summary,/Datos insuficientes/);
});

test('a changed revision between pages restarts at zero and warns instead of skipping rows',async()=>{
  const offsets=[];let calls=0;
  const x=setup(async(_,options)=>{
    const offset=JSON.parse(options.body).offset;offsets.push(offset);calls++;
    const p=page();p.offset=offset;p.filtered_total=calls===1?61:60;
    p.dataset_version=calls===1?4:5;p.batch.revision_version=calls===1?2:3;
    const rows=Array.from({length:p.filtered_total},(_,i)=>({...p.items[0],source_row:i+(calls===1?2:3)}));
    p.items=rows.slice(offset,offset+50);return p;
  });
  await x.run('loadPracticeBoard()');await x.run('practiceOffset=50;loadPracticeBoard()');
  assert.deepEqual(offsets,[0,50,0]);assert.equal(x.run('practiceOffset'),0);
  assert.match(x.context.message.textContent,/cambió.*primera página/i);
  assert.ok(x.run('practicePage.items.some(row=>row.source_row===52)'));
});


test('neutral classification exposes provenance without calling it an HPC economic equivalence',()=>{
  const x=setup(()=>{});const item=page().items[0];item.family_basis='exact_nomenclature_code';
  item.family_evidence={display_only:true,code:[{table:'hpc_catalog_codes',seq:22,source_id:'neutral-source',source_sha256:'a'.repeat(64)}],name:[]};
  x.run(`renderPracticeRows(${JSON.stringify([item])})`);
  const title=x.get('#practice-rows').children[0].children[1].title;
  assert.match(title,/no acredita equivalencia HPC/);assert.match(title,/neutral-source/);assert.match(title,/seq=22/);
});
test('reviewed source and possible-image hint remain display evidence, not a classified image',()=>{
 const x=setup(async()=>{});const item=page().items[0];
 item.family='unclassified';item.family_basis='not_found_in_catalog';item.family_suggestion={label:'Posible imagen: verificar código y documentación; no clasificada'};
 item.family_evidence={code:[{kind:'reviewed_display_nomenclature',source_file:'Nomenclador.xlsx',source_row:1462,source_id:'reviewed-excerpt',source_sha256:'abc'}]};
 x.context.inputRows=[item];x.run('renderPracticeRows(inputRows)');
 const rendered=x.get('#practice-rows').children[0];
 assert.match(rendered.children[1].title,/Nomenclador.xlsx.*fila=1462.*abc/);
 assert.match(rendered.children[1].children[1].textContent,/Posible imagen.*no clasificada/);
 assert.equal(item.family,'unclassified');
});


test('multiple selected criteria serialize ANY/ALL without changing other filters or position',()=>{
  const {get,run}=setup(()=>{});
  get('#board-rule').selectedOptions=[{value:'RN13'},{value:'RN17'}];
  get('#board-rules-match').value='all';
  get('#board-family').value='images';get('#board-state').value='no_evaluado';
  get('#board-view').value='information';get('#board-search').value='Ficticio';
  get('#board-date-from').value='2026-08-01';get('#board-sort').value='affiliate_id';
  run('practiceOffset=50');
  const result=JSON.parse(run('JSON.stringify(practiceFilters())'));
  assert.deepEqual(result.rules,['RN13','RN17']);assert.equal(result.rules_match,'all');
  assert.equal(result.offset,50);assert.equal(result.family,'images');
  assert.equal(result.view,'information');assert.equal(result.state,'no_evaluado');
  assert.equal(result.date_from,'2026-08-01');assert.equal(result.search,'Ficticio');
  assert.equal(result.sort,'affiliate_id');assert.equal(result.rule,undefined);
  get('#board-rule').selectedOptions=[];get('#board-rules-match').value='any';
  assert.deepEqual(JSON.parse(run('JSON.stringify(practiceFilters().rules)')),[]);
  assert.equal(run('practiceFilters().rules_match'),'any');
});

test('work modes and multi-control semantics are visible and no execution switch is offered',()=>{
  const html=readFileSync(path.join(__dirname,'..','web','index.html'),'utf8');
  assert.match(html,/<select id="board-rule" multiple/);
  assert.match(html,/Todos en la misma prestación \(ALL\)/);
  assert.match(html,/Cualquiera \(ANY\)/);
  assert.match(html,/no ejecutan ni desactivan controles, ni cambian decisiones/);
  assert.ok(html.indexOf('data-queue="exceptions"')<html.indexOf('id="board-more-filters"'));
  assert.ok(html.indexOf('id="board-view"')>html.indexOf('id="board-more-filters"'));
  assert.match(html,/Información faltante o sin evaluar/);
});


test('image review view travels to server and exposes pending count without claiming classification',async()=>{
  const calls=[]; const result=page();result.offset=0;result.filters.family='images_and_candidates';result.image_candidate_count=32;
  const {get,run}=setup(async(url,options)=>{calls.push(JSON.parse(options.body));return result;});
  get('#board-family').value='images_and_candidates';
  await run('loadPracticeBoard()');
  assert.equal(calls[0].family,'images_and_candidates');
  assert.match(get('#board-count').textContent,/posibles imágenes por revisar \(sin reclasificar\)/);
  assert.match(get('#board-classification').textContent,/32 posibles imágenes por revisar/);
  const html=readFileSync(path.join(__dirname,'..','web','index.html'),'utf8');
  assert.match(html,/<option value="images_and_candidates">Imágenes \+ posibles imágenes por revisar<\/option>/);
});

test('quick views and next case retain chosen order, query and page',async()=>{
  const calls=[];
  const {get,run}=setup(async(url,opts)=>{
    calls.push(JSON.parse(opts.body));return {...page(),offset:50,next_source_row:61};
  });
  get('#board-filters').reset=()=>{};
  get('#board-direction').value='desc';
  for(const [name,view,family] of [['exceptions','exceptions','all'],['images','exceptions','images'],['candidates','all','image_candidates'],['referred','referred','images'],['all','all','all']]){
    run(`setQueuePreset('${name}')`);
    assert.equal(get('#board-view').value,view);
    assert.equal(get('#board-family').value,family);
  }
  get('#board-text').value='ficticio';
  const result=await run('loadPracticeBoard({afterRow:62})');
  assert.equal(result.next_source_row,61);
  assert.equal(calls[0].after_source_row,62);
  assert.equal(calls[0].direction,'desc');
  assert.equal(calls[0].text,'ficticio');
  assert.equal(run('practiceOffset'),50);
});

test('save receipt names the saved practice and does not infer exit from a missing row',()=>{
  const {context,run}=setup(async()=>{});
  vm.runInContext(readFileSync(path.join(__dirname,'..','web','observation_workflow.js'),'utf8'),context);
  assert.match(run("savedRowMessage({source_row:2,practice:'TAC',in_exceptions:true,pending:['Revisar el aval CSV']},2)"),/TAC .*sigue en Excepciones.*Revisar el aval CSV/);
  assert.match(run("savedRowMessage({source_row:4,practice:'Consulta',in_exceptions:false,pending:[]},4)"),/Consulta .*salió de Excepciones/);
  assert.match(run("savedRowMessage({source_row:2,practice:'Eco',in_exceptions:false,pending:[],inconclusive:5,unevaluated:1},2,{action:'resolve',rule_code:'RN13'})"),/suma resuelta.*Eco.*salió de Excepciones.*5 controles sin conclusión y 1 sin evaluar/);
  assert.match(run("savedRowMessage(null,2)"),/Falta verificar/);
});

test('columns distinguish absent PDF, unread PDF, missing CSV and explicit rejection',()=>{
  const {get,run}=setup(()=>{});
  run("const target=document.querySelector('#states');renderDocumentColumn(target,{source_row:2,documents:{informe:{state:'no_aportado',count:0}}},'informe')");
  assert.equal(get('#states').children.at(-1).textContent,'×');
  assert.match(get('#states').children[0].textContent,/Sin PDF/);
  run("const target2=document.querySelector('#unread');renderDocumentColumn(target2,{source_row:2,documents:{informe:{state:'aportado_sin_revisar',count:1}}},'informe')");
  assert.equal(get('#unread').children.at(-1).textContent,'✓');
  assert.equal(get('#unread').children[0].textContent,'Por leer');
  run("renderCsvColumns(document.querySelector('#csv'),{source_row:2,authorization:{panel_signal:{presence:'not_located',item_authorization:'not_determinable'}}})");
  assert.equal(get('#csv').children[0].children.at(-1).textContent,'×');
  assert.equal(get('#csv').children[1].children.at(-1).textContent,'?');
  run("renderCsvColumns(document.querySelector('#rejected'),{source_row:2,authorization:{panel_signal:{presence:'found',item_authorization:'rejected'}}})");
  assert.equal(get('#rejected').children[1].children.at(-1).textContent,'×');
});

test('currency formatting keeps decimals exact, zero visible and unknown unpriced',()=>{
 const {run}=setup(()=>{});
 assert.equal(run("boardMoney('1234567890123456.70')"),'1.234.567.890.123.456,70');
 assert.equal(run("boardMoney('0.00')"),'0,00');
 assert.equal(run("boardMoney(null)"),'—');
});

test('expanded sheet preserves invoice identity, filters and the return to navigation',()=>{
  const {get,run}=setup(()=>{throw Error('No write or reload expected');});
  get('#invoice-batch').selectedOptions=[{textContent:'FICTICIO_3000_ordenes.xlsx · 2026-08'}];
  get('#identity').textContent='operador ficticio';
  get('#board-csv-review-state').value='review';
  run('setSheetExpanded(true)');
  assert.equal(get('#board-expand').textContent,'Mostrar menú');
  assert.equal(get('#board-expand').getAttribute('aria-pressed'),'true');
  assert.match(get('#sheet-focus-context').textContent,/FICTICIO_3000_ordenes.*operador ficticio/);
  assert.equal(get('#board-csv-review-state').value,'review');
  run('setSheetExpanded(false)');
  assert.equal(get('#board-expand').textContent,'Ampliar planilla');
  assert.equal(get('#sheet-focus-context').hidden,true);
});

test('patient heading separates name and affiliate and preserves cross-page continuity',()=>{
  const {get,run}=setup(()=>{});
  get('#board-sort').value='affiliate_id';
  const one={...page().items[0],affiliate_name:'Paciente de prueba A',affiliate_id:'1000001/1',patient_group_total:4,patient_group_position:3};
  const two={...page().items[0],affiliate_name:'Paciente de prueba B',affiliate_id:'1000002/1',patient_group_total:1,patient_group_position:1};
  run('renderPracticeRows('+JSON.stringify([one,two])+')');
  const rows=get('#practice-rows').children;
  assert.equal(rows.length,4);
  assert.equal(rows[0].children[0].children[0].textContent,'Paciente de prueba A');
  assert.equal(rows[0].children[0].children[1].textContent,'Afiliado 1000001/1');
  assert.match(rows[0].children[0].children[2].textContent,/4 prestaciones.*continúa/);
  assert.equal(rows[2].children[0].children[0].textContent,'Paciente de prueba B');
  assert.equal(rows[2].children[0].children[2].textContent,'1 prestación');
});

test('large invoices start expanded and a manual return to the menu survives filtering',async()=>{
  const {get,run}=setup(async()=>page());
  await run('loadPracticeBoard()');
  assert.equal(get('#board-expand').getAttribute('aria-pressed'),'true');
  run('setSheetExpanded(false)');
  await run('loadPracticeBoard()');
  assert.equal(get('#board-expand').getAttribute('aria-pressed'),'false');
});

test('presupuesto: un párrafo identifica orden, fechas y exceso; si es incierto no presenta un monto',()=>{
  const {context,run}=setup();context.item={description:'TAC TRIDIMENSIONAL',code:'1234567890'};
  context.budget={order_id:'DEMO-01',authorized_on:'2026-07-02',performed_on:'2026-08-02',status:'over',
    billed_ars:'450000.00',authorized_ars:'200000.00',excess_ars:'250000.00',csv_row:2};
  const text=run('budgetParagraph(item,budget)');
  for(const expected of ['DEMO-01','02/07/2026','02/08/2026','$450.000','$200.000','$250.000','registro 2'])assert.ok(text.includes(expected));
  context.budget.status='por_verificar';context.budget.reason='Importe común a varias prácticas.';
  const pending=run('budgetParagraph(item,budget)');assert.ok(pending.includes('No se calculó una diferencia'));assert.ok(!pending.includes('$'));
});

test('TAC: presupuesto individual, diferencia y propuesta humana ocupan tres columnas diferentes',()=>{
 const {context,get,run}=setup();
 context.sheetButton=(text)=>{const b=context.document.createElement('button');b.textContent=text;return b;};
 const row=page().items[0];
 row.authorization={panel_signal:{csv_coverage:{budget:{status:'over',order_id:'ORD-TEST',authorized_ars:'200000.00',excess_ars:'250000.00'}}}};
 row.total_ars='450000.00';
 context.item=row;run('renderPracticeRows([item])');
 const cells=get('#practice-rows').children[0].children;
 assert.equal(cells[8].textContent,'450.000,00');
 assert.equal(cells[10].textContent,'200.000,00');
 assert.match(cells[11].children[0].textContent,/250.000 a revisar/);
 assert.equal(cells[12].textContent,'—');
 row.reference_comparison={candidate_total_if_ars_and_same_unit:'175000.00'};
 run('renderPracticeRows([item])');
 assert.equal(get('#practice-rows').children[0].children[11].textContent,'Elegir referencia');
 assert.equal(get('#practice-rows').children[0].children[12].textContent,'—');
 row.reference_comparison.candidate_total_if_ars_and_same_unit='200000.0';
 assert.equal(run('referenceChoiceNeeded(item)'),false);
 row.authorization.panel_signal.csv_coverage.budget.status='por_verificar';
 run('renderPracticeRows([item])');
 assert.equal(get('#practice-rows').children[0].children[10].textContent,'—');
});

test('la cantidad pendiente muestra el importe a verificar y no un débito propuesto',()=>{
 const {context,get,run}=setup();
 run(readFileSync(path.join(__dirname,'..','web','sheet_actions.js'),'utf8'));
 const row=page().items[0];
 row.authorization={panel_signal:{csv_coverage:{status:'one_unit_only',covered_units:1,billed_units:2,coverage_note:'CSV incompleto.'}}};
 row.administrative_decision={proposal:null,quantity_advisory:{amount_ars:'100000.00',reason:'Verificar una unidad pendiente.'}};
 context.item=row;run('renderPracticeRows([item])');
 const cells=get('#practice-rows').children[0].children;
 assert.equal(cells[12].textContent,'100.000,00');
 assert.equal(cells[12].children[0].textContent,'A verificar');
 assert.equal(cells[12].title,'Verificar una unidad pendiente.');
});

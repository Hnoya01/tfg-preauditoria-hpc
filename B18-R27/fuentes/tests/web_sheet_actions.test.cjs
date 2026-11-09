const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const test=require('node:test');

function setup(handler=async()=>{}) {
  class Node {
    constructor(tag='div'){this.tag=tag;this.children=[];this.value='';this.textContent='';this.disabled=false;this.hidden=false;this.dataset={};this.listeners={};this.classList={add(){},remove(){}};}
    append(...nodes){this.children.push(...nodes);}
    prepend(...nodes){this.children.unshift(...nodes);}
    replaceChildren(...nodes){this.children=[...nodes];}
    setAttribute(k,v){this[k]=v;}
    addEventListener(k,v){this.listeners[k]=v;}
    focus(){}
    set innerHTML(v){throw new Error('Never render source HTML');}
  }
  const nodes=new Map();const get=selector=>{if(!nodes.has(selector))nodes.set(selector,new Node());return nodes.get(selector);};
  get('#invoice-batch').value='batch-a';
  const context={document:{querySelector:get,querySelectorAll:()=>[],createElement:tag=>new Node(tag),createTextNode:text=>({textContent:text})},
    Option:function(label,value){const n=new Node('option');n.value=value;n.textContent=label;return n;},
    selectedDataset:{id:'dataset-a',version:4},currentRole:'reviewer',request:handler,message:new Node(),refreshAlerts:async()=>{},
    authorizationTable(){}};
  vm.createContext(context);
  for(const name of ['workbench.js','sheet_actions.js','authorization_checks.js'])vm.runInContext(readFileSync(path.join(__dirname,'..','web',name),'utf8'),context);
  const run=code=>vm.runInContext(code,context);
  run(`practicePage={dataset_version:4,batch:{revision_version:3,latest_run_id:'run-1',revision_state:'abierta'},items:[]}`);
  return {get,run,context,Node};
}

test('only explicit alert choices enter selection, bounded to 100 and cleared on version change',()=>{
  const {run,get}=setup();
  for(let i=0;i<101;i++)run(`selectSheetAlert({id:'a${i}',version:1},true)`);
  assert.equal(run('sheetSelection.size'),100);
  assert.match(get('#sheet-action-status').textContent,/límite/);
  run('syncSheetSelection({...practicePage,dataset_version:5})');
  assert.equal(run('sheetSelection.size'),0);
  assert.equal(get('#sheet-selection-bar').hidden,true);
});

test('a repeated fetch cannot auto-rebase the selected alert versions',()=>{
  const {run}=setup();run(`selectSheetAlert({id:'a1',version:7},true)`);
  run('syncSheetSelection(practicePage)');
  assert.equal(run(`sheetSelection.get('a1').expected_version`),7);
});

test('refreshing a changed revision closes authorization detail even without selected alerts',()=>{
  const {run,get}=setup();run(`sheetPanel('Autorizaciones')`);
  assert.equal(get('#sheet-review-panel').hidden,false);
  run('syncSheetSelection({...practicePage,dataset_version:5})');
  assert.equal(get('#sheet-review-panel').hidden,true);
});

test('late preview from a different dataset never creates a decision form',async()=>{
  let release;const pending=new Promise(resolve=>release=resolve);
  const {run,context,get}=setup(()=>pending);
  run(`selectSheetAlert({id:'a1',version:1},true)`);const work=run('showSheetDecisionPreview()');
  context.selectedDataset={id:'dataset-b'};release({count:1,items:[],preview_sha256:'a'.repeat(64)});await work;
  assert.equal(get('#sheet-review-content').children.length,0);
});

test('preview commits the exact selected IDs and frozen versions without money',async()=>{
  const calls=[];
  const {run,get}=setup(async(url,options)=>{
    calls.push({url,body:JSON.parse(options.body)});
    return url.endsWith('decision-preview')?{count:1,items:[],preview_sha256:'a'.repeat(64)}:{decision_ids:['saved']};
  });
  run(`selectSheetAlert({id:'a1',version:7},true)`);await run('showSheetDecisionPreview()');
  const form=get('#sheet-review-content').children.find(n=>n.tag==='form');
  const fields=form.children.filter(n=>n.tag==='label').map(n=>n.children[0]);
  fields[0].value='no_concluyente';fields[1].value='Fundamento ficticio suficiente.';fields[2].value='';
  await form.listeners.submit({preventDefault(){}});
  assert.deepEqual(calls[1].body.items,[{id:'a1',expected_version:7}]);
  assert.equal(calls[1].body.expected_dataset_version,4);assert.equal(calls[1].body.expected_revision_version,3);
  assert.equal(calls[1].body.preview_sha256,'a'.repeat(64));assert.ok(!('amount' in calls[1].body));
  assert.equal(run('sheetSelection.size'),0);
});

test('version conflict keeps the foundation and does not retry a write',async()=>{
  let writes=0;
  const {run,get}=setup(async(url)=>{
    if(url.endsWith('decision-preview'))return {count:1,items:[],preview_sha256:'a'.repeat(64)};
    writes++;throw new Error('La versión cambió');
  });
  run(`selectSheetAlert({id:'a1',version:1},true)`);await run('showSheetDecisionPreview()');
  const form=get('#sheet-review-content').children.find(n=>n.tag==='form');
  const fields=form.children.filter(n=>n.tag==='label').map(n=>n.children[0]);
  fields[0].value='no_concluyente';fields[1].value='Fundamento ficticio que debe conservarse.';
  await form.listeners.submit({preventDefault(){}});
  assert.equal(fields[1].value,'Fundamento ficticio que debe conservarse.');assert.equal(writes,1);
  assert.equal(get('#sheet-review-panel').hidden,false);
});

test('authorization labels never convert match or human link into approval',()=>{
  const {run}=setup();
  assert.equal(run(`authorizationLabel({state:'no_authorization_located'})`),'Sin coincidencia');
  assert.equal(run(`authorizationLabel({state:'unambiguous_candidate',link_state:'selected',link_freshness:'current'})`),'Ítem elegido');
  assert.equal(run(`authorizationLabel({state:'unambiguous_candidate',resolution_states:['apparent_conflict']})`),'Resoluciones diferentes');
  assert.equal(run(`authorizationLabel({link_state:'selected',link_freshness:'requires_update'})`),'Revisar vínculo');
});

function fictitiousCheck(){return {mode:'synthetic_demo',dataset_version:4,revision_version:3,revision_state:'abierta',
  resolution:{state:'declared_authorized',reason:'Declaración delimitada.',resolution:{status:'authorized'}},
  quantity:{state:'con_indicios',reason:'Cantidad conjunta mayor.',authorized:'1',unit:'practica',billed_joint:'2',members:[],limitations:[]},
  temporal:{state:'no_concluyente',reason:'Falta incorporación.',authorization:{original:'2026-08-15',precision:'day',zone:null},incorporation:{original:null,precision:'unknown',zone:null}},
  inputs:{incorporation:{current:null,history:[]},quantity_unit:{current:null,history:[]}}};}

test('B03 preview does not write or turn fictional comparisons into money',async()=>{
  const calls=[];const {run,get}=setup(async(url,options)=>{calls.push({url,options});return fictitiousCheck();});
  await run('showAuthorizationChecks(2)');
  assert.equal(calls.length,1);assert.equal(calls[0].options,undefined);
  const text=get('#sheet-review-content').children.map(n=>n.textContent).join(' ');
  // DOM text is built with textContent/detailText, never source HTML.
  assert.equal(run('sheetSelection.size'),0);assert.equal(get('#sheet-review-panel').hidden,false);
  assert.ok(!calls[0].url.includes('analyze'));assert.ok(!calls[0].url.includes('proposal'));
});

test('B03 rejected write preserves evidence and frozen versions without retry',async()=>{
  const calls=[];const {run,get}=setup(async(url,options)=>{
    calls.push({url,body:options?.body?JSON.parse(options.body):null});
    if(!options)return fictitiousCheck();throw new Error('La versión cambió');
  });
  await run('showAuthorizationChecks(2)');
  const details=get('#sheet-review-content').children.find(n=>n.tag==='details' && n.children.some(c=>c.tag==='form'));
  const form=details.children.find(n=>n.tag==='form');const fields=form.children.filter(n=>n.tag==='label').map(n=>n.children[0]);
  fields[0].value='incorporation';fields[1].value='declared';fields[2].value='2026-08-15';fields[3].value='Evidencia ficticia que debe conservarse.';fields[4].value='FICT!2';
  await form.listeners.submit({preventDefault(){}});
  assert.equal(calls.length,2);assert.equal(calls[1].body.expected_version,4);assert.equal(calls[1].body.expected_revision_version,3);
  assert.equal(fields[3].value,'Evidencia ficticia que debe conservarse.');assert.equal(get('#sheet-review-panel').hidden,false);
});

test('B03 late response from previous dataset is discarded',async()=>{
  let release;const promise=new Promise(resolve=>release=resolve);const {run,get}=setup(()=>promise);
  const pending=run('showAuthorizationChecks(2)');run("selectedDataset={id:'another-dataset'}");release(fictitiousCheck());await pending;
  assert.equal(get('#sheet-review-content').children.length,0);
});

test('catalog category candidates remain visible but never enter exact-link selector',async()=>{
  const candidate={order_id:'FICT-ORDER',item:{full_code:'1234560100',description:'<script>ficticio</script>',service_date:null},compatibility:'needs_review',locator:'$.orders[0].items[0]',source_sha256:'b'.repeat(64),relation:{invoice_code:'123456',practice_id:'FICT-P',invoice_code_seqs:[1],authorization_code_seqs:[2],source_sha256:'a'.repeat(64),basis:'explicit_neutral_category_to_hpc',category_is_broad:true}};
  const data={dataset_version:4,revision_version:3,mode:'real_unvalidated',state:'no_authorization_located',candidates:[],candidate_count_total:0,disposition:'included',issues:[],human_link:{current:null,history:[]},catalog_relationships:{candidate_count_total:1,candidates:[candidate],use_limit:'No acredita autorización'}};
  const {run,get}=setup(async()=>data);
  await run('showSheetAuthorization(2)');
  const walk=n=>[n,...(n.children||[]).flatMap(walk)];
  const nodes=walk(get('#sheet-review-content'));
  assert(nodes.some(n=>(n.textContent||'').includes('Categoría amplia del nomenclador')));
  assert(nodes.some(n=>(n.textContent||'').includes('NO equivalencia')));
  const selector=nodes.find(n=>n['aria-label']==='Ítem a vincular');
  assert.equal(selector.children.length,1);
  assert.equal(selector.children[0].value,'');
  assert.match(run(`authorizationLabel({state:'no_authorization_located',catalog_candidate_count:1,candidate_count:0})`),/candidatos por catálogo/);
});

test('panel separates practice presence, item status and CSV order history',()=>{
  const {run}=setup();
  const lines=run(`authorizationSignalText({presence:'candidate',item_authorization:'not_determinable',order_history_states:['autorizado','rechazado']})`);
  assert.match(lines[0],/Posible práctica/);assert.match(lines[1],/no determinable/);
  assert.match(lines[2],/AUTORIZADO \/ RECHAZADO/);assert.match(lines[2],/No determina/);
  const missing=run(`authorizationSignalText({presence:'not_located',item_authorization:'not_determinable'})`);
  assert.match(missing[0],/^— Práctica no localizada/);assert.doesNotMatch(missing[1],/Rechazada/);
  const approved=run(`authorizationSignalText({presence:'found',item_authorization:'authorized'})`);
  assert.match(approved[0],/^✓/);assert.match(approved[1],/^✓.*declaración individual/);
  assert.match(run(`authorizationSignalText({presence:'found',item_authorization:'rejected'})[1]`),/^✗.*Rechazada/);
});

test('CSV source decision remains visible when invoice correspondence is pending',()=>{
  const {run}=setup();
  for(const [state,label] of [['authorized','autorizada'],['rejected','no autorizada']]){
    const lines=run("authorizationSignalText("+JSON.stringify({presence:'found',item_authorization:'not_determinable',csv_item_declaration:state})+")");
    assert.ok(lines[1].includes('Ítem en el CSV: '+label));
    assert.match(lines[2],/Correspondencia.*pendiente/);
  }
});

test('CSV validity shows the supporting date and identifies the earlier billed row',()=>{
  const {run}=setup();
  const signal={presence:'found',item_authorization:'not_determinable',csv_item_declaration:'authorized',
    csv_coverage:{status:'one_unit_supported',authorization_date:'2026-07-02',performed_on:'2026-08-02',elapsed_days:31,locator:'item:0'}};
  const lines=run('authorizationSignalText('+JSON.stringify(signal)+')');
  assert.ok(lines.some(s=>s.includes('Con aval CSV')));
  assert.ok(lines.some(s=>s.includes('día 31 de 60')));
  assert.ok(!lines.some(s=>s.includes('pendiente de verificación')));
  signal.csv_coverage={status:'already_used',previous_rows:[{performed_on:'2026-08-02',source_row:2,batch_id:'Lote A'}]};
  const later=run('authorizationSignalText('+JSON.stringify(signal)+')');
  assert.ok(later.some(s=>s.includes('Sin otra unidad autorizada')));
  assert.ok(later.some(s=>s.includes('fila 2')));
});

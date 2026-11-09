const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const test=require('node:test');

function setup(handler) {
  class Node {
    constructor(){this.value='';this.hidden=false;this.disabled=false;this.children=[];this.textContent='';this.attrs={};}
    append(...nodes){this.children.push(...nodes);}
    replaceChildren(...nodes){this.children=[...nodes];}
    removeAttribute(name){delete this[name];}
    addEventListener(){}
    set innerHTML(value){throw new Error('Never render source HTML');}
  }
  const nodes=new Map();const get=id=>{if(!nodes.has(id))nodes.set(id,new Node());return nodes.get(id);};
  get('#invoice-batch').value='batch-a';
  const calls=[];const context={document:{querySelector:get,createElement:()=>new Node()},selectedDataset:{id:'dataset-a'},currentRole:'reviewer',
    crypto:{randomUUID:()=>`fictional-request-${calls.length}-unique`},clearTimeout(){},setTimeout(){return 1;},
    refreshRuns:async()=>{},refreshAlerts:async()=>{},showRun:async()=>{},request:async(url,options)=>{calls.push({url,options});return handler(url,options);}};
  vm.createContext(context);vm.runInContext(readFileSync(path.join(__dirname,'..','web','processing.js'),'utf8'),context);
  return {context,get,calls,run:code=>vm.runInContext(code,context)};
}
function history(items=[],version=4){return {items,dataset_version:version,revision_version:2,revision_state:'abierta',has_more:false};}
function job(overrides={}){return {id:'fictional-job',state:'running',stage:'evaluating',processed_rows:250,total_rows:1000,version:2,created_at:'2026-08-20T12:00:00Z',...overrides};}

test('known row progress and unknown denominator are distinguished without a made-up percentage',async()=>{
  const {run,get}=setup(()=>history([job()]));await run('refreshProcessing()');
  assert.equal(get('#processing-progress').max,1000);assert.equal(get('#processing-progress').value,250);
  assert.match(run(`processingDate('2026-08-20T18:00:00Z')`),/15:00/);
  assert.match(get('#processing-count').textContent,/250 de 1.000/);
  run(`renderProcessing(${JSON.stringify(history([job({stage:'preparing',total_rows:null,processed_rows:0})]))})`);
  assert.equal(get('#processing-progress').value,undefined);
});

test('uncertain receipt resends the same key and frozen versions only on a new click',async()=>{
  let posts=0;
  const {run,calls,get}=setup((url,options)=>{
    if(options?.method==='POST'){posts++;if(posts===1)throw new Error('Network failure');return job({state:'queued'});}
    return history([],posts?5:4);
  });
  await run('refreshProcessing()');await run('startProcessing()');
  assert.equal(posts,1);assert.match(get('#analyze-button').textContent,/Reenviar/);
  await run('refreshProcessing()');assert.equal(posts,1);
  await run('startProcessing()');
  const bodies=calls.filter(c=>c.options?.method==='POST').map(c=>JSON.parse(c.options.body));
  assert.deepEqual(bodies[0],bodies[1]);assert.equal(bodies[1].expected_dataset_version,4);
});

test('a definitive version conflict clears the request and never automatically retries',async()=>{
  let posts=0;
  const {run}=setup((url,options)=>{if(options?.method==='POST'){posts++;const e=new Error('La versión cambió');e.status=409;throw e;}return history();});
  await run('refreshProcessing()');await run('startProcessing()');
  assert.equal(posts,1);assert.equal(run('processingPending'),null);
});

test('a late response cannot display another dataset processing history',async()=>{
  let release;const promise=new Promise(resolve=>release=resolve);
  const {run,context,get}=setup(()=>promise);const pending=run('refreshProcessing()');
  context.selectedDataset={id:'dataset-b'};release(history([job()]));await pending;
  assert.equal(get('#processing-history').children.length,0);assert.equal(run('processingContext'),null);
});

test('an explicit retry keeps the original request after an uncertain response',async()=>{
  let posts=0;
  const {run,calls}=setup((url,options)=>{if(options?.method==='POST'){posts++;throw new Error('Network failure');}return history([job({state:'interrupted',can_retry:true})]);});
  await run('refreshProcessing()');await run(`retryProcessing(${JSON.stringify(job({state:'interrupted',can_retry:true}))})`);
  await run(`retryProcessing(${JSON.stringify(job({state:'interrupted',can_retry:true,version:3}))})`);
  const bodies=calls.filter(c=>c.options?.method==='POST').map(c=>JSON.parse(c.options.body));
  assert.equal(posts,2);assert.deepEqual(bodies[0],bodies[1]);assert.equal(bodies[1].expected_attempt_version,2);
});

test('reading completed history does not start analysis and reuse does not pretend to recalculate rows',async()=>{
  const {run,get,calls}=setup(()=>history([job({state:'completed',stage:'completed',result_created:0,processed_rows:0,result_run_id:'run-old'})]));
  await run('refreshProcessing()');
  assert.ok(calls.every(c=>!c.options));assert.equal(get('#processing-progress').hidden,true);
  assert.match(get('#processing-status').textContent,/reutilizó/);assert.match(get('#processing-count').textContent,/Sin recálculo/);
  assert.ok(!get('#processing-status').textContent.includes('vigente'));
});

test('reset removes timers, pending actions and history when context or session changes',async()=>{
  const {run,get}=setup(()=>history([job()]));await run('refreshProcessing()');run('resetProcessing()');
  assert.equal(get('#processing-history').children.length,0);assert.equal(get('#processing-progress').hidden,true);
  assert.equal(get('#analyze-button').disabled,true);assert.equal(run('processingTimer'),null);
});

test('a revoked session or permission clears processing history and pending actions',async()=>{
  let denied=false;
  const {run,get}=setup(()=>{if(denied){const e=new Error('Sin permiso');e.status=403;throw e;}return history([job()]);});
  await run('refreshProcessing()');denied=true;await run('refreshProcessing()');
  assert.equal(get('#processing-history').children.length,0);assert.equal(get('#analyze-button').disabled,true);
  assert.match(get('#processing-status').textContent,/no tenés permiso/);
});

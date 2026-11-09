const assert=require('node:assert/strict'),test=require('node:test'),vm=require('node:vm');
const {readFileSync}=require('node:fs');const path=require('node:path');
function nodes(parent,tag){return parent.children.flatMap(n=>n&&typeof n==='object'?[...(n.tag===tag?[n]:[]),...nodes({children:n.children||[]},tag)]:[]);}
function setup(handler,role='admin'){
  class Node{constructor(tag='div'){this.tag=tag;this.children=[];this.listeners={};this.value='';this.checked=false;this.disabled=false;this.textContent='';}
    append(...ns){this.children.push(...ns);}replaceChildren(...ns){this.children=[...ns];this.textContent='';}setAttribute(){}addEventListener(k,v){this.listeners[k]=v;}}
  const els=Object.fromEntries(['hpc-scope-content','hpc-scope-open','invoice-batch','invoice-dataset','value-source'].map(k=>[k,new Node()]));
  els['invoice-batch'].value='batch1';els['value-source'].value='source1';const calls=[];
  const c={selectedDataset:{id:'dataset1',version:1},currentRole:role,
    document:{querySelector:q=>els[q.slice(1)],createElement:t=>new Node(t),createTextNode:t=>({textContent:t})},
    detailText:(p,l,t)=>{const n=new Node('p');n.textContent=`${l}: ${t}`;p.append(n);},
    sheetField:(p,l)=>{const n=new Node('textarea');n.label=l;p.append(n);return n;},
    request:async(url,options)=>{calls.push({url,options});return handler(url,options);}};
  vm.createContext(c);vm.runInContext(readFileSync(path.join(__dirname,'../web/provider_scope.js'),'utf8'),c);
  return {c,els,calls,run:code=>vm.runInContext(code,c),content:els['hpc-scope-content']};
}
function page(){return {dataset_version:4,revision_version:7,revision_state:'en_revision',current:null,history:[]};}
const event={preventDefault(){}};
test('scope confirmation sends fixed HPC with fresh versions only after explicit check',async()=>{
  const x=setup(async(_,o)=>o?{id:'saved',dataset_version:5}:page());await x.run('showHpcScope()');
  const form=nodes(x.content,'form')[0];await form.listeners.submit(event);assert.equal(x.calls.length,1);
  nodes(form,'input')[0].checked=true;await form.listeners.submit(event);await form.listeners.submit(event);
  assert.equal(x.calls.length,2);const body=JSON.parse(x.calls[1].options.body);
  assert.equal(body.provider,'HPC');assert.equal(body.source_id,'source1');assert.equal(body.billing_unit,'unverified');
  assert.equal(body.expected_dataset_version,4);assert.equal(body.expected_revision_version,7);
  assert.equal(x.c.selectedDataset.version,5);assert.equal(nodes(form,'button')[0].disabled,true);
});
test('reviewer, closed revision and already confirmed scope cannot write',async()=>{
  for(const [role,data] of [['reviewer',page()],['admin',{...page(),revision_state:'cerrada'}],
    ['admin',{...page(),current:{provider:'HPC',source_id:'source1'}}]]){
    const x=setup(async()=>data,role);await x.run('showHpcScope()');assert.equal(nodes(x.content,'form').length,0);assert.equal(x.calls.length,1);
  }
});
test('navigation while reading discards response and stale form cannot send',async()=>{
  let finish;const x=setup(()=>new Promise(r=>finish=r));const pending=x.run('showHpcScope()');
  x.els['value-source'].value='other';finish(page());await pending;assert.equal(nodes(x.content,'form').length,0);
  const y=setup(async()=>page());await y.run('showHpcScope()');const form=nodes(y.content,'form')[0];nodes(form,'input')[0].checked=true;
  y.els['invoice-batch'].value='other';await form.listeners.submit(event);assert.equal(y.calls.length,1);
});
test('conflict preserves draft; uncertain result prevents resubmission even after history refresh',async()=>{
  for(const code of [409,500]){
    const x=setup(async(_,o)=>{if(o)throw Object.assign(new Error('failure'),{status:code});return page();});
    await x.run('showHpcScope()');const form=nodes(x.content,'form')[0],note=nodes(form,'textarea')[0];note.value='Mi fundamento conservado';nodes(form,'input')[0].checked=true;
    await form.listeners.submit(event);assert.equal(note.value,'Mi fundamento conservado');assert.equal(nodes(form,'button')[0].disabled,code===500);
    if(code===500){await form.listeners.submit(event);assert.equal(x.calls.length,2);await x.run('showHpcScope()');assert.equal(nodes(x.content,'form').length,0);assert.equal(x.calls.length,3);}
  }
});
test('repeated open and submit cannot duplicate an in-flight operation',async()=>{
  let finish;const x=setup(async(_,o)=>o?new Promise(r=>finish=r):page());await x.run('showHpcScope()');
  const form=nodes(x.content,'form')[0];nodes(form,'input')[0].checked=true;const pending=form.listeners.submit(event);
  await x.run('showHpcScope()');await form.listeners.submit(event);assert.equal(x.calls.length,2);
  finish({id:'done',dataset_version:5});await pending;
});


test('uncertain scope retry requires explicit preparation, fresh versions and a new confirmation',async()=>{
  let reads=0;const x=setup(async(_,options)=>{if(options)throw Object.assign(new Error('unknown'),{status:500});reads++;return {...page(),dataset_version:reads+10};});
  await x.run('showHpcScope()');let form=nodes(x.content,'form')[0];nodes(form,'input')[0].checked=true;await form.listeners.submit(event);
  await x.run('showHpcScope()');assert.equal(nodes(x.content,'form').length,0);
  const retry=nodes(x.content,'button').find(n=>n.textContent.startsWith('Preparar reintento'));
  await retry.listeners.click();form=nodes(x.content,'form')[0];assert.ok(form);assert.equal(x.calls.filter(c=>c.options).length,1);
  assert.equal(nodes(form,'input')[0].checked,false);nodes(form,'input')[0].checked=true;await form.listeners.submit(event);
  assert.equal(JSON.parse(x.calls.filter(c=>c.options)[1].options.body).expected_dataset_version,13);
});

test('batch unit stays unverified by default and needs explicit check plus documentary basis',async()=>{
 const x=setup(async(_,o)=>o?{dataset_version:5}:page());await x.run('showHpcScope()');
 const form=nodes(x.content,'form')[0],checks=nodes(form,'input'),notes=nodes(form,'textarea');
 assert.equal(checks[1].checked,false);checks[0].checked=true;checks[1].checked=true;
 await form.listeners.submit(event);assert.equal(x.calls.length,1);
 notes[1].value='Factura ficticia Hoja1 columna G: cantidad de prácticas, no unidades bioquímicas.';
 await form.listeners.submit(event);assert.equal(x.calls.length,2);
 const body=JSON.parse(x.calls[1].options.body);assert.equal(body.billing_unit,'practice');assert.equal(body.billing_unit_note,notes[1].value);
});
test('already confirmed scope can explicitly open unit editing without an automatic write',async()=>{
 const x=setup(async()=>({...page(),current:{provider:'HPC',source_id:'source1',billing_unit:'unverified'}}));await x.run('showHpcScope()');
 assert.equal(nodes(x.content,'form').length,0);
 await nodes(x.content,'button').find(b=>b.textContent.startsWith('Documentar o modificar')).listeners.click();
 assert.equal(nodes(x.content,'form').length,1);assert.equal(x.calls.filter(c=>c.options).length,0);
 assert.equal(nodes(nodes(x.content,'form')[0],'input')[1].checked,false);
});

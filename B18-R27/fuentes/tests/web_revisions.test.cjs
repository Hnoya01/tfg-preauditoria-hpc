const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),test=require('node:test');
function setup(handler=async()=>{}){
 class Node{
  constructor(tag='div'){this.tag=tag;this.value='';this.children=[];this.disabled=false;this.checked=false;this.textContent='';this.listeners={};}
  append(...nodes){this.children.push(...nodes);}replaceChildren(...nodes){this.children=[...nodes];}
  addEventListener(k,v){this.listeners[k]=v;}setAttribute(){}
  set innerHTML(value){throw new Error('Source HTML must not be interpreted');}
 }
 const nodes=new Map(),get=id=>{if(!nodes.has(id))nodes.set(id,new Node());return nodes.get(id);};get('#invoice-batch').value='batch-a';
 const calls=[],context={selectedDataset:{id:'dataset-a',version:999},currentRole:'reviewer',
  document:{querySelector:get,createElement:tag=>new Node(tag),createTextNode:text=>({textContent:text})},
  request:async(url,options)=>{calls.push({url,options});return handler(url,options);},setTimeout(){}};
 vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'..','web','revisions.js'),'utf8'),context);
 return {get,calls,context,run:code=>vm.runInContext(code,context)};
}
function page(state='cerrada'){return {state,dataset_version:4,revision_version:7,revision_id:'old-review',items:[{id:'old-review',ordinal:1,state,current:true,archive_sha256:'frozen-hash',reason:'FICTICIO <b>literal</b>'}]};}
function find(node,tag){return (node.children||[]).flatMap(n=>n&&typeof n==='object'?[...(n.tag===tag?[n]:[]),...find(n,tag)]:[]);}
test('successor needs explicit confirmation and sends displayed versions and predecessor once',async()=>{
 const x=setup(async()=>{throw Object.assign(new Error('Conflict'),{status:409});});x.run('renderRevisions('+JSON.stringify(page())+',revisionsContext())');
 const content=x.get('#revisions-content'),form=find(content,'form')[0],button=find(form,'button')[0],check=find(form,'input')[0];
 assert.equal(button.disabled,true);check.checked=true;check.listeners.change();find(form,'textarea')[0].value='FICTICIO evidencia nueva';
 await form.listeners.submit({preventDefault(){}});assert.equal(x.calls.length,1);assert.equal(button.disabled,true);
 const body=JSON.parse(x.calls[0].options.body);assert.deepEqual(body,{previous_revision_id:'old-review',expected_dataset_version:4,expected_revision_version:7,reason:'FICTICIO evidencia nueva'});
 await form.listeners.submit({preventDefault(){}});assert.equal(x.calls.length,1);
});
test('an open revision exposes history without offering another successor',()=>{
 const x=setup();x.run('renderRevisions('+JSON.stringify(page('preparacion'))+',revisionsContext())');
 assert.equal(find(x.get('#revisions-content'),'form').length,0);assert.equal(x.calls.length,0);
 assert.match(find(x.get('#revisions-content'),'p').at(-1).textContent,/Ya existe una revisión abierta/);
});
test('late history or submit from another batch cannot affect current context',async()=>{
 let finish;const x=setup(()=>new Promise(resolve=>finish=resolve));const pending=x.run('loadRevisions()');x.get('#invoice-batch').value='batch-b';finish(page());await pending;
 assert.equal(x.get('#revisions-content').children.length,0);
 x.get('#invoice-batch').value='batch-a';x.run('renderRevisions('+JSON.stringify(page())+',revisionsContext())');
 const form=find(x.get('#revisions-content'),'form')[0],check=find(form,'input')[0];check.checked=true;check.listeners.change();
 x.get('#invoice-batch').value='batch-b';await form.listeners.submit({preventDefault(){}});assert.equal(x.calls.length,1);
});
test('revocation removes history and does not retry a write',async()=>{
 const x=setup(async()=>{throw Object.assign(new Error('revoked'),{status:403});});x.run('renderRevisions('+JSON.stringify(page())+',revisionsContext())');
 const content=x.get('#revisions-content'),form=find(content,'form')[0],check=find(form,'input')[0];check.checked=true;check.listeners.change();
 await form.listeners.submit({preventDefault(){}});assert.equal(content.children.length,0);assert.match(content.textContent,/revocado/);assert.equal(x.calls.length,1);
});
test('frozen download specifies the selected historical revision and handles revoked access',async()=>{
 const x=setup();let url;x.context.fetch=async value=>{url=value;return {ok:false,status:403,json:async()=>({detail:'revoked'})};};
 x.run('renderRevisions('+JSON.stringify(page())+',revisionsContext())');
 const content=x.get('#revisions-content');assert.equal(find(content,'p').some(n=>n.textContent.includes('<b>literal</b>')),true);
 await find(content,'button').find(n=>n.textContent==='Descargar cierre de revisión 1').listeners.click();assert.equal(url,'/api/datasets/dataset-a/batches/batch-a/export-closed?revision_id=old-review');
 assert.match(content.textContent,/revocado/);assert.equal(x.calls.length,0);
});

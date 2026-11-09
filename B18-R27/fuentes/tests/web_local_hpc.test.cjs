const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function setup(handler=async()=>[]){
 class Node{constructor(){this.value='';this.disabled=false;this.textContent='';this.children=[];this.listeners={};}addEventListener(k,f){this.listeners[k]=f;}append(...v){this.children.push(...v);}replaceChildren(...v){this.children=v;}set innerHTML(v){throw Error('Untrusted HTML');}}
 const nodes={},calls=[];const node=id=>nodes[id]??=(new Node());
 const c={document:{querySelector:node,createElement:()=>new Node()},selectedDataset:{id:'d',version:5},currentRole:'admin',request:async(url,o)=>{calls.push({url,o});return handler(url,o);}};
 node('#value-source').value='s';vm.createContext(c);vm.runInContext(fs.readFileSync(path.join(__dirname,'..','web','local_hpc.js'),'utf8'),c);
 return {c,node,calls,run:s=>vm.runInContext(s,c)};
}
test('local identity payload preserves full code and requires explicit currency; cancel clears edits',()=>{
 const x=setup();x.node('#local-hpc-code').value='001234567-A';x.node('#local-hpc-description').value='Imagen';
 const payload=x.run('localPayload()');assert.equal(payload.code,'001234567-A');assert.equal(payload.currency,'');assert.equal(payload.practice_id,null);
 x.node('#local-hpc-id').value='uuid';x.node('#local-hpc-code').disabled=true;x.node('#local-hpc-new').listeners.click();
 assert.equal(x.node('#local-hpc-id').value,'');assert.equal(x.node('#local-hpc-code').value,'');assert.equal(x.node('#local-hpc-code').disabled,false);
});
test('double save submits once and refreshes only current dataset context',async()=>{
 let finish;const pending=new Promise(resolve=>finish=resolve);const x=setup(async(url,o)=>o?pending:[]);
 const submit=x.node('#local-hpc-form').listeners.submit;const first=submit({preventDefault(){}});await submit({preventDefault(){}});
 assert.equal(x.calls.length,1);finish({id:'uuid',ordinal:1,dataset_version:6});await first;
 assert.equal(x.c.selectedDataset.version,6);assert.match(x.node('#local-hpc-result').textContent,/No se ejecutaron controles/);
 assert.equal(x.calls.filter(c=>c.o).length,1);
});
test('stale list response is not rendered under newer source',async()=>{
 let finish;const x=setup(()=>new Promise(resolve=>finish=resolve));const pending=x.run('loadLocalHpc()');x.node('#value-source').value='new';finish([{id:'secret-old',versions:[]}]);await pending;
 assert.equal(x.node('#local-hpc-list').children.length,0);
});
test('practice description and evidence are rendered as text, never HTML',async()=>{
 const x=setup(async()=>[{id:'u',code:'A',description:'<img onerror=evil()>',family:'images',versions:[{ordinal:1,active:1,effective_from:'2026-08-01',amount_ars:'1.00',unit_label:'por práctica',document_sha256:'abc',page_number:1,excerpt:'<script>',reason:'ficticio'}]}]);
 await x.run('loadLocalHpc()');const item=x.node('#local-hpc-list').children[0];assert.match(item.children[0].textContent,/<img/);assert.match(item.children[1].textContent,/<script>/);
});

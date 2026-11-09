// The unchanged application renderer consumes an actual API response, not a hand-shaped substitute.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const p=JSON.parse(fs.readFileSync(0,'utf8'));
class Node{constructor(){this.children=[];this.value='';this.textContent='';this.disabled=true;}append(...x){this.children.push(...x);}}
const nodes=new Map();const get=id=>{if(!nodes.has(id))nodes.set(id,new Node());return nodes.get(id);};
get('#authorization-upload').value=p.upload.id;
const ctx={selectedDataset:{id:'synthetic-dataset',version:p.dataset_version},authorizationEpoch:1,authorizationPreview:null,
 document:{querySelector:get,createElement:()=>new Node(),createTextNode:s=>({textContent:s})},
 clearAuthorizationPreview(){},authorizationTable(block,title,cols,rows){assert.ok(Array.isArray(rows));},
 request:async url=>{assert.ok(url.endsWith('/preview'));return p;}};
const code=fs.readFileSync(path.join(__dirname,'../../web/app.js'),'utf8');
const start=code.indexOf('async function showAuthorizationPreview() {');
const end=code.indexOf("document.querySelector('#authorization-upload').addEventListener",start);
vm.createContext(ctx);vm.runInContext(code.slice(start,end),ctx);
ctx.showAuthorizationPreview().then(()=>{
 assert.match(get('#authorization-summary').textContent,/PARCIAL/);
 assert.match(get('#authorization-summary').textContent,/NO VALIDADO/);
 assert.match(get('#authorization-summary').textContent,/Sin autorización inferida/);
 assert.equal(get('#authorization-import-button').disabled,Boolean(p.upload.capture_id) && !p.reinterpretation_required);
 if(p.reinterpretation_required){
  assert.match(get('#authorization-import-button').textContent,/Confirmar nueva interpretación/);
  assert.match(get('#authorization-summary').textContent,/no cambia cierres ni decisiones/);
 }
 assert.equal(get('#authorization-original').hidden,false);
}).catch(e=>{process.stderr.write(String(e));process.exitCode=1;});

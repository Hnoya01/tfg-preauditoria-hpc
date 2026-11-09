const assert=require('node:assert/strict');
const fs=require('node:fs');const path=require('node:path');const vm=require('node:vm');const test=require('node:test');
function setup(handler=async()=>{}) {
 class Node {
  constructor(tag='div'){this.tag=tag;this.value='';this.children=[];this.disabled=false;this.textContent='';this.listeners={};this.checked=false;}
  append(...nodes){this.children.push(...nodes);}replaceChildren(...nodes){this.children=[...nodes];}
  addEventListener(k,v){this.listeners[k]=v;}setAttribute(){}
  set innerHTML(v){throw new Error('Never render source HTML');}
 }
 const nodes=new Map();const get=id=>{if(!nodes.has(id))nodes.set(id,new Node());return nodes.get(id);};get('#invoice-batch').value='batch-a';
 const calls=[];const context={selectedDataset:{id:'dataset-a',version:999},currentRole:'reviewer',
  document:{querySelector:get,createElement:tag=>new Node(tag),createTextNode:text=>({textContent:text})},
  request:async(url,options)=>{calls.push({url,options});return handler(url,options);},setTimeout(){}};
 vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'..','web','closure.js'),'utf8'),context);
 return {get,calls,run:code=>vm.runInContext(code,context),context};
}
function page(justified=true){return {state:'revision',dataset_version:4,revision_version:2,preview_sha256:'frozen-preview',pending_alert_count:0,can_close:justified,control_count:3,limitations:[{group_key:'frozen-group',scope_sha256:'frozen-scope',rule_codes:['RN20','RN21','RN22'],reason_code:'control_not_implemented',control_count:3,justification:justified?{id:'frozen-limitation',foundation:'FICTICIO fundamento compartido'}:null}]};}
function find(node,tag){return (node.children || []).flatMap(n=>n && typeof n==='object'?[...(n.tag===tag?[n]:[]),...find(n,tag)]:[]);}
test('closure keeps DEMO simulated subtotal separate from the real total',()=>{
 const x=setup();const p=page();p.current_proposal_total_ars=null;p.rn14_simulations={simulation_only:true,version_count:2,current_count:1,current_simulated_total_ars:'1.50'};
 x.run('renderClosure('+JSON.stringify(p)+',closureContext())');
 const text=find(x.get('#closure-content'),'p').map(n=>n.textContent).join('\n');
 assert.match(text,/Total vigente al momento de la captura: sin cuantificar/);
 assert.match(text,/SIMULACIONES DEMO: 1 vigentes, subtotal simulado 1\.50 ARS/);
 assert.match(text,/no integran el total real/);
});
test('late preview for another batch is discarded',async()=>{
 let finish;const x=setup(()=>new Promise(resolve=>finish=resolve));const pending=x.run('loadClosurePreview()');x.get('#invoice-batch').value='batch-b';finish(page());await pending;
 assert.equal(x.get('#closure-content').children.length,0);assert.equal(x.get('#closure-download').disabled,true);
});
test('closing requires explicit limitation confirmation and sends frozen versions once',async()=>{
 const x=setup(async()=>{throw Object.assign(new Error('Version conflict'),{status:409});});
 x.run('renderClosure('+JSON.stringify(page())+',closureContext())');
 const content=x.get('#closure-content'),button=find(content,'button').at(-1),check=find(content,'input')[0];
 assert.equal(button.disabled,true);check.checked=true;check.listeners.change();assert.equal(button.disabled,false);
 await button.listeners.click();assert.equal(x.calls.length,1);assert.match(x.calls[0].url,/\/closure$/);
 const body=JSON.parse(x.calls[0].options.body);assert.equal(body.expected_dataset_version,4);assert.equal(body.expected_revision_version,2);
 assert.equal(body.preview_sha256,'frozen-preview');assert.deepEqual(body.confirmed_limitation_ids,['frozen-limitation']);
 assert.equal(button.disabled,true);assert.equal(x.calls.length,1);
});
test('justification binds the exact scope and conflict preserves typed foundation',async()=>{
 const x=setup(async()=>{throw Object.assign(new Error('Scope conflict'),{status:409});});x.run('renderClosure('+JSON.stringify(page(false))+',closureContext())');
 const content=x.get('#closure-content'),form=find(content,'form')[0],input=find(form,'textarea')[0];input.value='FICTICIO fundamento a conservar';
 await form.listeners.submit({preventDefault(){}});const body=JSON.parse(x.calls[0].options.body);
 assert.equal(body.group_key,'frozen-group');assert.equal(body.scope_sha256,'frozen-scope');assert.equal(body.foundation,input.value);
 assert.equal(input.value,'FICTICIO fundamento a conservar');assert.equal(x.calls.length,1);
});
test('revoked access removes closure evidence and never retries',async()=>{
 const x=setup(async()=>{throw Object.assign(new Error('revoked'),{status:403});});x.run('renderClosure('+JSON.stringify(page())+',closureContext())');
 const content=x.get('#closure-content'),check=find(content,'input')[0];check.checked=true;check.listeners.change();
 await find(content,'button').at(-1).listeners.click();assert.equal(content.children.length,0);assert.match(content.textContent,/revocado/);assert.equal(x.calls.length,1);
});
test('closed preview shows frozen limitations and read-only scopes; switching context clears it',()=>{
 const x=setup();x.run('renderClosure('+JSON.stringify({...page(),state:'cerrada'})+',closureContext())');
 assert.equal(x.get('#closure-download').disabled,false);assert.equal(x.get('#export-provisional-button').disabled,true);
 assert.equal(find(x.get('#closure-content'),'form').length,0);assert.equal(find(x.get('#closure-content'),'button')[0].textContent,'Ver filas y controles de este alcance');assert.equal(find(x.get('#closure-content'),'input').length,0);x.run('resetClosure()');assert.equal(x.get('#closure-download').disabled,true);
 assert.equal(x.calls.length,0);
});
test('saving one shared cause preserves the typed foundation of another unchanged scope',async()=>{
 const first=page(false);first.limitations.push({...first.limitations[0],group_key:'other-group',scope_sha256:'other-scope'});
 const next=JSON.parse(JSON.stringify(first));next.dataset_version++;next.revision_version++;next.limitations[0].justification={id:'saved',foundation:'FICTICIO saved'};
 const x=setup(async(url)=>url.endsWith('/closure-preview')?next:{});x.run('renderClosure('+JSON.stringify(first)+',closureContext())');
 const forms=find(x.get('#closure-content'),'form'),second=find(forms[1],'textarea')[0];second.value='FICTICIO otro fundamento en elaboración';second.listeners.input();
 find(forms[0],'textarea')[0].value='FICTICIO primer fundamento';await forms[0].listeners.submit({preventDefault(){}});
 assert.equal(find(x.get('#closure-content'),'textarea')[0].value,'FICTICIO otro fundamento en elaboración');
 x.run('resetClosure()');assert.equal(x.run('closureDrafts.size'),0);
});

test('scope query binds revision and hash and renders exact row/control without a write',async()=>{
 const x=setup(async()=>({items:[{source_row:2,rule_code:'RN20',result:'no_evaluado',reason_code:'control_not_implemented'},{source_row:3,rule_code:'RN21',result:'no_evaluado',reason_code:'control_not_implemented'}],total:2,offset:0,limit:50,scope_sha256:'frozen-scope'}));
 x.run('renderClosure('+JSON.stringify({...page(),state:'cerrada',revision_id:'old-review'})+',closureContext())');
 await find(x.get('#closure-content'),'button')[0].listeners.click();
 assert.match(x.calls[0].url,/revision_id=old-review/);assert.match(x.calls[0].url,/scope_sha256=frozen-scope/);assert.equal(x.calls[0].options,undefined);
 const cells=find(x.get('#closure-content'),'td').map(n=>n.textContent);assert.deepEqual(cells,['2','RN20','no_evaluado','Control documental sin implementar; aplicabilidad sin verificar · Código: control_not_implemented','3','RN21','no_evaluado','Control documental sin implementar; aplicabilidad sin verificar · Código: control_not_implemented']);
});

test('known closure reasons explain administrative limitations and preserve their codes',()=>{
 const x=setup();
 const expected={control_not_implemented:'aplicabilidad sin verificar',control_not_recorded:'sin resultado registrado',
  requiere_actualizacion:'Motivo sin etiqueta administrativa',requires_update:'afectados por cambios',
  falta_fecha_incorporacion_por_practica:'incorporación',cantidad_autorizada_no_acreditada:'unidades',
  autorizaciones_sin_adaptador_validado:'no se conciliaron',referencia_economica_no_aplicable_aun:'Falta validar',
  ordenes_validas_no_verificadas:'sin ejecutar',fecha_ilegible:'Fecha',tipo_no_reconocido:'aclarar'};
 for(const [code,label] of Object.entries(expected)){
  const text=x.run('closureReasonText('+JSON.stringify(code)+')');assert.ok(text.includes(label),code);assert.ok(text.includes('Código: '+code),code);
 }
 const source=fs.readFileSync(path.join(__dirname,'..','app','practice_board.py'),'utf8').split('REASONS = {')[1].split('\n}')[0];
 const known=[...source.matchAll(/^\s*'([^']+)'\s*:/gm)].map(match=>match[1]);assert.ok(known.length>20);
 for(const code of known){const text=x.run('closureReasonText('+JSON.stringify(code)+')');assert.ok(!text.includes('sin etiqueta administrativa'),code);assert.ok(text.includes('Código: '+code));if(code.startsWith('demo_'))assert.ok(text.includes('FICTICIO'));}
});

test('historical unknown reasons stay literal safe text in closed headings and scope rows',async()=>{
 for(const code of ['legacy_reason_v0','constructor','__proto__','<img src=x onerror=alert(1)>']){
  const data={items:[{source_row:2,rule_code:'RN20',result:'no_evaluado',reason_code:code}],total:1,offset:0,limit:50,frozen:true};
  const before=JSON.stringify(data),x=setup(async()=>data),frozen={...page(),state:'cerrada',revision_id:'old-review'};frozen.limitations[0].reason_code=code;
  x.run('renderClosure('+JSON.stringify(frozen)+',closureContext())');await find(x.get('#closure-content'),'button')[0].listeners.click();
  const heading=find(x.get('#closure-content'),'h4')[0].textContent,reason=find(x.get('#closure-content'),'td').at(-1).textContent;
  assert.ok(heading.includes('Motivo sin etiqueta administrativa'));assert.ok(heading.includes('Código: '+code));assert.equal(reason,'Motivo sin etiqueta administrativa en esta versión · Código: '+code);
  assert.equal(find(x.get('#closure-content'),'img').length,0);assert.equal(find(x.get('#closure-content'),'form').length,0);assert.equal(JSON.stringify(data),before);assert.equal(x.calls.length,1);assert.equal(x.calls[0].options,undefined);
 }
});

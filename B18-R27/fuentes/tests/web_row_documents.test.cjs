const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),test=require('node:test');
function setup(handler=async()=>page()) {
 class Node {
  constructor(tag='div'){this.tag=tag;this.children=[];this.listeners={};this.value='';this.textContent='';}
  append(...children){this.children.push(...children);}replaceChildren(...children){this.children=[...children];this.textContent='';}
  addEventListener(k,v){this.listeners[k]=v;}setAttribute(){}querySelectorAll(tag){return find(this,tag);}
  set innerHTML(v){throw new Error('HTML must stay inert');}
 }
 const content=new Node(),calls=[];let epoch=0;
 const c={selectedDataset:{version:5},csrfToken:'session-a',Date,crypto:{randomUUID:()=>`fictional-key-${calls.length}`},document:{createElement:tag=>new Node(tag)},
  sheetPanel:()=>{epoch++;content.replaceChildren();return content;},sheetContext:()=>({epoch,datasetId:'d',batchId:'b'}),sheetCurrent:ctx=>ctx.epoch===epoch,
  sheetField:(form,label,kind)=>{const n=new Node(kind);n.label=label;form.append(n);return n;},
  detailText:(parent,label,text)=>{const n=new Node('p');n.textContent=label+': '+text;parent.append(n);},
  sheetButton:(label,fn)=>{const n=new Node('button');n.textContent=label;n.listeners.click=fn;return n;},
  request:async(url,options)=>{calls.push({url,options});return handler(url,options);}};
 vm.createContext(c);vm.runInContext(fs.readFileSync('web/row_documents.js','utf8'),c);
 return {content,calls,context:c,run:code=>vm.runInContext(code,c),leave:()=>epoch++};
}
function find(node,tag){return (node.children||[]).flatMap(n=>[...(n.tag===tag?[n]:[]),...find(n,tag)]);}
function page(items=[]){return {dataset_version:5,revision_version:3,revision_id:'r',writable:true,use_limit:'No clínico',items};}
const submit=form=>form.listeners.submit({preventDefault(){}});
function item(){return {id:'doc',category:'informe',original_name:'<script>.pdf',provenance:'Ficticio',actor_username:'operator',created_at:'today',sha256:'abc',state:'aportado_sin_revisar',reviews:[]};}
test('private originals are links, names inert, closed history has no writes',async()=>{
 const x=setup(async()=>({...page([item()]),writable:false}));await x.run('showRowDocuments(2)');
 assert.equal(find(x.content,'form').length,0);assert.equal(find(x.content,'a')[0].href,'/api/datasets/d/row-documents/doc/file');
 assert.match(find(x.content,'p').map(n=>n.textContent).join(' '),/<script>/);
});
test('late context never renders evidence',async()=>{
 let resolve;const x=setup(()=>new Promise(r=>resolve=r));const p=x.run('showRowDocuments(2)');x.leave();resolve(page([item()]));await p;assert.equal(find(x.content,'form').length,0);
});
test('manual reading uncertain retry keeps same payload across reopen and double submit',async()=>{
 let writes=0;const x=setup(async(u,o)=>{if(!o)return page([item()]);if(++writes===1)throw Error('lost');return {dataset_version:6};});
 await x.run('showRowDocuments(2)');let form=find(x.content,'form')[0];find(form,'textarea')[0].value='Lectura ficticia sin dictamen';await submit(form);
 const body=x.calls.at(-1).options.body;
 await x.run('showRowDocuments(2)');form=find(x.content,'form')[0];assert.equal(form.noValidate,true);await submit(form);await submit(form);
 assert.equal(writes,2);assert.equal(x.calls.at(-1).options.body,body);
});
test('version conflict ends operation; revocation removes visible data',async()=>{
 const x=setup(async(u,o)=>{if(o)throw Object.assign(Error('changed'),{status:409});return page([item()]);});await x.run('showRowDocuments(2)');
 const f=find(x.content,'form')[0];find(f,'textarea')[0].value='Lectura ficticia';await submit(f);await submit(f);assert.equal(x.calls.filter(c=>c.options).length,1);
 const y=setup(async(u,o)=>{if(o)throw Object.assign(Error('revoked'),{status:403});return page([item()]);});await y.run('showRowDocuments(2)');const g=find(y.content,'form')[0];await submit(g);assert.equal(y.content.children.length,0);
});

test('row separately shows report PDF and authorization PDF, without changing A1 or clinical status',async()=>{
 const x=setup();const cell={children:[],append(n){this.children.push(n);}};x.context.cell=cell;
 x.run("renderRowDocuments(cell,{source_row:2,locator:'Hoja1!2',documents:{informe:{state:'no_aportado'},autorizacion:{state:'aportado_sin_revisar'}}})");
 const buttons=find(cell,'button');assert.equal(buttons.length,2);
 assert.equal(buttons[0].textContent,'Informe PDF: No aportado');
 assert.equal(buttons[1].textContent,'Autorización PDF: Aportado, sin revisión manual');
 for(const b of buttons){assert.match(b.title,/No aportado no significa/);assert.match(b.title,/no acredita autorización ni cumplimiento clínico/);}
 assert.equal(x.calls.length,0);await buttons[1].listeners.click();assert.equal(x.calls[0].url,'/api/datasets/d/batches/b/rows/2/documents');
});
test('missing document summary is unknown rather than absence; manual reading is not approval',()=>{
 const x=setup();const cell={children:[],append(n){this.children.push(n);}};x.context.cell=cell;
 x.run('renderRowDocuments(cell,{source_row:3})');assert.deepEqual(find(cell,'button').map(b=>b.textContent),['Informe PDF: Sin consultar','Autorización PDF: Sin consultar']);
 cell.children=[];x.run("renderRowDocuments(cell,{source_row:3,documents:{informe:{state:'revisado_manualmente'},autorizacion:{state:'no_aportado'}}})");
 assert.equal(find(cell,'button')[0].textContent,'Informe PDF: Lectura manual registrada');
});
test('structured authorization button is explicitly CSV / A1 and does not imply a PDF was supplied',()=>{
 const source=fs.readFileSync('web/sheet_actions.js','utf8'),start=source.indexOf('function authorizationSignalText('),end=source.indexOf('\nfunction sheetButton(',start);
 const x=setup();const cell={children:[],append(n){this.children.push(n);}};x.context.authorizationLabel=()=> 'Sin coincidencia';x.context.showSheetAuthorization=()=>{};x.context.cell=cell;
 vm.runInContext(source.slice(start,end),x.context);x.run("renderSheetAuthorization(cell,{source_row:2,locator:'Hoja1!2'})");
 assert.equal(cell.children[0].textContent,'Ver CSV / A1: Sin coincidencia');assert.match(cell.children[0].title,/separada de los PDF/);
});

test('guided reading defaults are unknown and unsupported assertions require a locator',()=>{
 const x=setup();assert.throws(()=>x.run('documentaryReviewNote({}, "")'),/al menos una/);
 assert.throws(()=>x.run('documentaryReviewNote({identity:{state:"compatible"}}, "")'),/página del PDF/);
 assert.throws(()=>x.run('documentaryReviewNote({identity:{state:"approved",evidence:"página 1 identidad"}}, "")'),/inválido/);
 const note=x.run('documentaryReviewNote({identity:{state:"compatible",page:"1",evidence:"Cotejado con factura"},contrast:{state:"inconclusive",page:"2",evidence:"Texto ilegible; no interpretable"}}, "Requiere revisión")');
 assert.match(note,/Identidad: Compatible según lectura manual/);assert.match(note,/Fecha: No evaluado/);
 assert.match(note,/no ejecuta RN20–RN22 ni confirma vínculo/);assert.match(note,/no acredita cantidad ni importe/);
 assert.ok(note.length<=2000);
});
test('guided form is report only; original simple reading remains available',async()=>{
 const x=setup(async()=>page([item(),{...item(),id:'auth',category:'autorizacion'}]));await x.run('showRowDocuments(2)');
 assert.equal(find(x.content,'details').length,1);assert.equal(find(x.content,'form').length,4);
 const f=find(x.content,'details')[0];assert.equal(find(f,'select').length,6);
 assert.ok(find(f,'select').every(n=>n.value==='not_evaluated'));
});
test('guided save keeps the exact note and request id on uncertain retry',async()=>{
 let writes=0;const x=setup(async(u,o)=>{if(!o)return page([item()]);if(++writes===1)throw Error('connection lost');return {dataset_version:6};});
 await x.run('showRowDocuments(2)');let form=find(find(x.content,'details')[0],'form')[0];
 find(form,'select')[0].value='compatible';find(form,'input')[0].value='1';find(form,'textarea')[0].value='Página 1: identidad cotejada con factura';await submit(form);
 const first=x.calls.at(-1).options.body;assert.match(JSON.parse(first).note,/COTEJO DOCUMENTAL MANUAL/);
 await x.run('showRowDocuments(2)');form=find(find(x.content,'details')[0],'form')[0];await submit(form);
 assert.equal(x.calls.at(-1).options.body,first);assert.equal(writes,2);
});
test('guided validation failure never sends a write, and long evidence is rejected',async()=>{
 const x=setup(async()=>page([item()]));await x.run('showRowDocuments(2)');const form=find(find(x.content,'details')[0],'form')[0];
 await submit(form);assert.equal(x.calls.filter(c=>c.options).length,0);
 x.context.long='x'.repeat(181);assert.throws(()=>x.run('documentaryReviewNote({identity:{state:"compatible",evidence:long}}, "")'),/180/);
});

 test('guided evaluated dimension requires its separate positive PDF page, never infers it from prose',()=>{
 const x=setup();
 for(const state of ['compatible','discrepancy','inconclusive']) {
  for(const page of ['', '0', '-1','1.5','texto','1e2']) {
   x.context.answer={identity:{state,page,evidence:'Todo coincide en la página 1'}};
   assert.throws(()=>x.run('documentaryReviewNote(answer, "")'),/página del PDF/);
  }
 }
 x.context.answer={identity:{state:'compatible',page:'2',evidence:'Coincide identidad comparada'}};
 assert.match(x.run('documentaryReviewNote(answer, "")'),/Página PDF 2/);
 });

test('saved multiline reading is inert and has whitespace-preserving presentation',async()=>{
 const x=setup(async()=>page([{...item(),reviews:[{actor_username:'Ficticio',created_at:'hoy',note:'Identidad: compatible\nFecha: no evaluado\n<script>no ejecutar</script>'}]}]));
 await x.run('showRowDocuments(2)');
 const wrappers=find(x.content,'div').filter(n=>n.className==='document-reading-note');assert.equal(wrappers.length,1);
 assert.match(find(wrappers[0],'p')[0].textContent,/compatible\nFecha/);assert.match(find(wrappers[0],'p')[0].textContent,/<script>/);
 assert.match(fs.readFileSync('web/style.css','utf8'),/\.document-reading-note\s*\{[^}]*white-space:\s*pre-wrap/);
});

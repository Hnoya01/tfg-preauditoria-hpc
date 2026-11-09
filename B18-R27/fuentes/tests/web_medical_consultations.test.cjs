const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),test=require('node:test');
function setup(handler=async()=>page()) {
 class Node {
  constructor(tag='div'){this.tag=tag;this.children=[];this.listeners={};this.value='';this.textContent='';}
  append(...children){this.children.push(...children);}replaceChildren(...children){this.children=[...children];this.textContent='';}
  addEventListener(k,v){this.listeners[k]=v;}setAttribute(){}querySelectorAll(tag){return find(this,tag);}
  set innerHTML(v){throw new Error('HTML must stay inert');}
 }
 const content=new Node(),calls=[];let epoch=0;
 const c={csrfToken:'session-a',Date,crypto:{randomUUID:()=>`fictional-key-${calls.length}`},document:{createElement:tag=>new Node(tag)},
  sheetPanel:()=>{epoch++;content.replaceChildren();return content;},sheetContext:()=>({epoch,datasetId:'d',batchId:'b'}),sheetCurrent:ctx=>ctx.epoch===epoch,
  sheetField:(form,label,kind)=>{const n=new Node(kind);n.label=label;form.append(n);return n;},
  detailText:(parent,label,text)=>{const n=new Node('p');n.textContent=label+': '+text;parent.append(n);},
  sheetButton:(label,fn)=>{const n=new Node('button');n.textContent=label;n.listeners.click=fn;return n;},
  request:async(url,options)=>{calls.push({url,options});return handler(url,options);}};
 vm.createContext(c);vm.runInContext(fs.readFileSync('web/medical_consultations.js','utf8'),c);
 return {content,calls,context:c,run:code=>vm.runInContext(code,c),leave:()=>epoch++};
}
function find(node,tag){return (node.children||[]).flatMap(n=>[...(n.tag===tag?[n]:[]),...find(n,tag)]);}
function page(items=[]){return {dataset_version:5,revision_version:3,revision_id:'r',revision_state:'revision',can_create_consultation:true,items};}
function item(revision='r'){return {id:'q',revision_id:revision,revision_ordinal:1,actor_username:'reviewer',question:'<img src=x onerror=alert(1)>',created_at:'2026-10-30T10:00:00Z',context:{},responses:[]};}
const submit=form=>form.listeners.submit({preventDefault(){}});
test('history stays inert; closed and historical consultations have no response form',async()=>{
 const x=setup(async()=>({...page([item()]),revision_state:'cerrada'}));await x.run('showMedicalConsultations(2)');
 assert.equal(find(x.content,'form').length,0);assert.match(find(x.content,'p').map(n=>n.textContent).join(' '),/<img src=x/);
 const y=setup(async()=>page([item('old')]));await y.run('showMedicalConsultations(2)');assert.equal(find(y.content,'form').length,1);assert.equal(find(y.content,'form')[0].draftKey,'new');
});
test('late history after switching context is ignored',async()=>{
 let resolve;const x=setup(()=>new Promise(r=>resolve=r));const pending=x.run('showMedicalConsultations(2)');x.leave();resolve(page([item()]));await pending;assert.equal(find(x.content,'form').length,0);
});
test('uncertain write preserves identical body and key for explicit retry',async()=>{
 let writes=0;const x=setup(async(url,opt)=>{if(!opt)return page();if(++writes===1)throw new Error('lost reply');return {id:'saved'};});
 await x.run('showMedicalConsultations(2)');const form=find(x.content,'form')[0];form.fields.question.value='FICTICIO consulta de prueba';await submit(form);
 assert.equal(writes,1);assert.equal(form.fields.question.disabled,true);await submit(form);
 const bodies=x.calls.filter(c=>c.options).map(c=>c.options.body);assert.equal(bodies.length,2);assert.equal(bodies[0],bodies[1]);
 const body=JSON.parse(bodies[0]);assert.equal(body.expected_dataset_version,5);assert.equal(body.expected_revision_version,3);assert.equal(body.revision_id,'r');
 await submit(form);assert.equal(writes,2);
});
test('conflict does not retry and explicit reload preserves draft',async()=>{
 const x=setup(async(url,opt)=>{if(opt)throw Object.assign(new Error('changed'),{status:409});return page();});await x.run('showMedicalConsultations(2)');
 const form=find(x.content,'form')[0];form.fields.question.value='FICTICIO texto que debe conservarse';await submit(form);await submit(form);
 assert.equal(x.calls.filter(c=>c.options).length,1);await find(form,'button').at(-1).listeners.click();
 assert.equal(find(x.content,'form')[0].fields.question.value,'FICTICIO texto que debe conservarse');
});
test('successful save carries other response drafts when explicitly refreshing',async()=>{
 const x=setup(async()=>page([item()]));await x.run('showMedicalConsultations(2)');const forms=find(x.content,'form');
 forms[0].fields.response.value='FICTICIO otra aclaración todavía no guardada';forms[1].fields.question.value='FICTICIO nueva consulta';await submit(forms[1]);
 await find(forms[1],'button').at(-1).listeners.click();assert.equal(find(x.content,'form')[0].fields.response.value,'FICTICIO otra aclaración todavía no guardada');
 assert.equal(find(x.content,'form')[1].fields.question.value,'');
});
test('revocation clears evidence and stops writes',async()=>{
 const x=setup(async(url,opt)=>{if(opt)throw Object.assign(new Error('revoked'),{status:403});return page([item()]);});await x.run('showMedicalConsultations(2)');
 const form=find(x.content,'form').at(-1);form.fields.question.value='FICTICIO consulta de prueba';await submit(form);assert.equal(x.content.children.length,0);assert.match(x.content.textContent,/revocado/);
});
test('response sends external author, provenance and zoned time separately',async()=>{
 const x=setup(async()=>page([item()]));await x.run('showMedicalConsultations(2)');const form=find(x.content,'form')[0];
 Object.assign(form.fields.author_name,{value:'Dra. Ficticia'});form.fields.responded_at.value='2026-10-30T11:00:00';form.fields.channel.value='email';form.fields.response.value='FICTICIO respuesta externa';form.fields.provenance.value='FICTICIO correo 001';await submit(form);
 const call=x.calls.at(-1),body=JSON.parse(call.options.body);assert.equal(call.options.headers['Content-Type'],'application/json');assert.match(call.url,/\/q\/responses$/);assert.equal(body.author_name,'Dra. Ficticia');assert.match(body.responded_at,/Z$/);assert.equal(body.actor_id,undefined);
});
test('U2 response lost then another form conflicts: refresh retains exact operation',async()=>{
 let version=5,first=null,writes=0;
 const x=setup(async(url,opt)=>{
  if(!opt)return {...page([item()]),dataset_version:version,revision_version:version-2};
  if(url.endsWith('/responses')){writes++;if(!first){first=opt.body;version++;throw new Error('reply lost after commit');}assert.equal(opt.body,first);return {id:'one-answer',replayed:true};}
  throw Object.assign(new Error('Version conflict'),{status:409});
 });
 await x.run('showMedicalConsultations(2)');let forms=find(x.content,'form');
 const f=forms[0];for(const [k,v] of Object.entries({author_name:'Emisora ficticia',responded_at:'2026-10-31T12:00:00',channel:'email',provenance:'Referencia ficticia 01',response:'Respuesta ficticia conservada'}))f.fields[k].value=v;
 await submit(f);forms[1].fields.question.value='Otra consulta ficticia';await submit(forms[1]);
 await find(forms[1],'button').at(-1).listeners.click();forms=find(x.content,'form');
 await submit(forms[0]);assert.equal(writes,2);assert.equal(x.calls.filter(c=>c.options && c.url.endsWith('/responses')).at(-1).options.body,first);assert.equal(JSON.parse(first).expected_dataset_version,5);
});
test('U2 navigation and closed revision retain pending exact replay; another row or session cannot reuse it',async()=>{
 let closed=false;const x=setup(async(u,o)=>{if(o)throw new Error('lost');return {...page([item()]),revision_state:closed?'cerrada':'revision'};});
 await x.run('showMedicalConsultations(2)');let form=find(x.content,'form')[0];form.fields.response.value='Respuesta ficticia original';await submit(form);
 const original=x.calls.at(-1).options.body;x.leave();await x.run('showMedicalConsultations(3)');assert.equal(find(x.content,'form')[0].fields.response.value,'');
 closed=true;await x.run('showMedicalConsultations(2)');form=find(x.content,'form')[0];assert.equal(form.fields.response.disabled,true);
 form.fields.response.value='Intento de editar contenido bloqueado';await submit(form);assert.equal(x.calls.at(-1).options.body,original);
 x.context.csrfToken='session-b';await x.run('showMedicalConsultations(2)');assert.equal(find(x.content,'form').length,0);
});
test('U2 in-flight reconstruction and double click cannot issue concurrent replay',async()=>{
 let reject;const x=setup(async(u,o)=>o?new Promise((_,r)=>reject=r):page([item()]));
 await x.run('showMedicalConsultations(2)');const old=find(x.content,'form')[0];old.fields.response.value='Respuesta ficticia';const sending=submit(old);
 await submit(old);await x.run('showMedicalConsultations(2)');const fresh=find(x.content,'form')[0];await submit(fresh);
 assert.equal(x.calls.filter(c=>c.options).length,1);reject(new Error('lost'));await sending;
 assert.equal(fresh.fields.response.value,'Respuesta ficticia');assert.equal(fresh.fields.response.disabled,true);
});
test('U2 an uncertain old-revision question is not copied into a new-revision draft',async()=>{
 let revision='r';const x=setup(async(u,o)=>{if(o)throw new Error('lost');return {...page(),revision_id:revision};});
 await x.run('showMedicalConsultations(2)');let form=find(x.content,'form')[0];form.fields.question.value='Consulta ficticia incierta';await submit(form);const original=x.calls.at(-1).options.body;
 revision='next';await x.run('showMedicalConsultations(2)');const forms=find(x.content,'form');assert.equal(forms.length,2);assert.equal(forms[0].fields.question.value,'');
 await submit(forms[1]);assert.equal(x.calls.at(-1).options.body,original);
});
test('U2 revoked history clears pending data; late acknowledgement never posts again',async()=>{
 let finish,deny=false,lose=false;const x=setup(async(u,o)=>{if(o){if(lose)throw new Error('lost');return new Promise(r=>finish=r);}if(deny)throw Object.assign(new Error('revoked'),{status:403});return page([item()]);});
 await x.run('showMedicalConsultations(2)');const original=find(x.content,'form')[0];original.fields.response.value='Respuesta ficticia pendiente';const waiting=submit(original);
 await x.run('showMedicalConsultations(2)');const restored=find(x.content,'form')[0];finish({id:'one'});await waiting;
 await submit(restored);assert.equal(x.calls.filter(c=>c.options).length,1);assert.equal(find(restored,'button').at(-1).textContent,'Actualizar historial');
 await x.run('showMedicalConsultations(2)');lose=true;await submit(find(x.content,'form')[0]);assert.equal(x.run('correspondencePending.size'),1);
 deny=true;await x.run('showMedicalConsultations(2)');assert.equal(x.run('correspondencePending.size'),0);assert.equal(find(x.content,'form').length,0);
});

test('Q1 blocks only new creation while keeping history and response forms',async()=>{
 const x=setup(async()=>({...page([item()]),can_create_consultation:false,creation_block_reason:'internacion_fuera_de_alcance'}));
 await x.run('showMedicalConsultations(2)');const forms=find(x.content,'form');assert.equal(forms.length,1);assert.equal(forms[0].draftKey,'q');
 assert.match(find(x.content,'p').map(n=>n.textContent).join(' '),/No se permiten consultas nuevas/);
 assert.equal(forms[0].fields.responded_at.label,'Fecha de recepción informada (hora local)');
 forms[0].fields.responded_at.value='2020-01-01T12:00:01';await submit(forms[0]);
 assert.match(JSON.parse(x.calls.at(-1).options.body).responded_at,/^2020-01-01T/);
});
test('Q1 newly blocked creation retains only exact pending operation across refresh',async()=>{
 let blocked=false;const x=setup(async(u,o)=>{if(o)throw new Error('lost');return {...page(),can_create_consultation:!blocked,creation_block_reason:blocked?'internacion_fuera_de_alcance':null};});
 await x.run('showMedicalConsultations(2)');let form=find(x.content,'form')[0];form.fields.question.value='FICTICIO consulta previa pendiente';await submit(form);const body=x.calls.at(-1).options.body;
 blocked=true;await x.run('showMedicalConsultations(2)');form=find(x.content,'form')[0];assert.equal(form.fields.question.disabled,true);
 await submit(form);assert.equal(x.calls.at(-1).options.body,body);
 x.context.csrfToken='new-session';await x.run('showMedicalConsultations(2)');assert.equal(find(x.content,'form').length,0);
});

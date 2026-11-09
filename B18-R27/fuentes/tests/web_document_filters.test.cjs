const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const test=require('node:test');
const source=readFileSync(path.join(__dirname,'..','web','workbench.js'),'utf8');
test('document filters are independent POST payload fields, not clinical approvals',()=>{
 const nodes={};const get=id=>nodes[id]??={value:''};
 get('#board-report-document-state').value='no_aportado';get('#board-authorization-document-state').value='revisado_manualmente';
 const start=source.indexOf('function practiceFilters()'),end=source.indexOf('\nasync function loadPracticeBoard(',start);
 const ctx={document:{querySelector:get},practiceOffset:50};
 const fn=vm.runInNewContext('('+source.slice(start,end)+')',ctx),filters=fn();
 assert.equal(filters.report_document_state,'no_aportado');assert.equal(filters.authorization_document_state,'revisado_manualmente');assert.equal(filters.offset,50);
 const html=readFileSync(path.join(__dirname,'..','web','index.html'),'utf8');
 assert.match(html,/Autorización PDF <select id="board-authorization-document-state"/);assert.match(html,/No aportado no significa que el documento no exista/);
 assert.ok(!Object.hasOwn(filters,'medical_compliant'));
});
test('both document selector changes clear selection and pagination before loading',()=>{
 const start=source.indexOf("  for(const id of ['board-report-document-state'");
 const end=source.indexOf('\n',start);assert.ok(start>=0);
 const events={},trace=[];const ctx={practiceOffset:500,document:{querySelector:id=>({addEventListener:(name,fn)=>events[id]=fn})},clearSheetSelection:()=>trace.push('clear'),closePracticeDetail:()=>trace.push('close'),loadPracticeBoard:()=>trace.push('load')};
 vm.createContext(ctx);vm.runInContext(source.slice(start,end),ctx);
 for(const id of ['#board-report-document-state','#board-authorization-document-state']){
  ctx.practiceOffset=500;events[id]();assert.equal(ctx.practiceOffset,0);assert.deepEqual(trace.splice(0),['clear','close','load']);
 }
});

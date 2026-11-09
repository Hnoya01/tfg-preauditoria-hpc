const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../web/invoice_handoff.js'),'utf8');

function scenario(duty){
  const calls=[];
  const ctx={activeWorkspaceView:'revision',selectedDataset:{id:'synthetic'},practicePage:{batch:{id:'lot'}},
    document:{hidden:false},request:async url=>{calls.push(url);return {items:[{batch_id:'lot'}]};},
    loadPracticeBoard:async()=>calls.push('refresh')};
  vm.createContext(ctx);vm.runInContext(source,ctx);
  vm.runInContext("handoffView={current:()=>true,data:{duty:'"+duty+"',state:'administrative'}}",ctx);
  return {calls,ctx};
}

test('auditor already in the invoice sees a new delivery without selecting the lot again',async()=>{
  const {ctx,calls}=scenario('auditor');
  await vm.runInContext('pollAuditorInbox()',ctx);
  assert.deepEqual(calls,['/api/datasets/synthetic/auditor-handoffs','refresh']);
});

test('opening a receipt never interrupts an administrative editing session or a hidden tab',async()=>{
  const {ctx,calls}=scenario('administrative');
  await vm.runInContext('pollAuditorInbox()',ctx);
  vm.runInContext("handoffView.data.duty='auditor';document.hidden=true",ctx);
  await vm.runInContext('pollAuditorInbox()',ctx);
  assert.deepEqual(calls,[]);
});


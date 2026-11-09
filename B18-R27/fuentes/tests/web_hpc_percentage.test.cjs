const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm');
const {readFileSync}=require('node:fs'),path=require('node:path');
function ui(handler) {
 const nodes=new Map();
 function node(id) {if(!nodes.has(id)) nodes.set(id,{value:'',disabled:false,textContent:'',listeners:{},addEventListener(k,f){this.listeners[k]=f;}});return nodes.get(id);}
 const values={'#value-source':'source1','#hpc-percentage-seqs':'1, 2','#hpc-percentage-rate':'10','#hpc-value-from':'2026-11-02',
 '#hpc-value-document':'pdf1','#hpc-value-page':'2','#hpc-value-excerpt':'Cláusula ficticia porcentaje','#hpc-value-reason':'Cambio ficticio documentado'};
 for(const [k,v]of Object.entries(values))node(k).value=v;
 const calls=[],context={document:{querySelector:node},selectedDataset:{id:'dataset1',version:7},currentRole:'admin',
 request:async(url,options)=>{calls.push({url,payload:JSON.parse(options.body)});return handler(url,options);}};
 vm.createContext(context);vm.runInContext(readFileSync(path.join(__dirname,'../web/hpc_percentage.js'),'utf8'),context);
 return {context,calls,node,click:name=>node('#hpc-percentage-'+name).listeners.click()};
}
const preview={percentage:'10',effective_from:'2026-11-02',rounding:'ROUND_HALF_UP',preview_sha256:'a'.repeat(64),
 items:[{tariff_seq:1,code:'<script>',before_ars:'1.05',after_ars:'1.16',unit_label:'por práctica'}],use_limit:'No débitos'};
test('preview then apply binds exact payload, disables repeated submit and advances once',async()=>{
 let release;
 const x=ui(async url=>url.endsWith('preview')?preview:await new Promise(r=>release=r));
 await x.click('preview');assert.equal(x.node('#hpc-percentage-apply').disabled,false);
 assert.match(x.node('#hpc-percentage-result').textContent,/<script>/); // literal text, not HTML
 const saving=x.click('apply');await x.click('apply');assert.equal(x.calls.length,2);
 release({dataset_version:8,versions:[{id:'v'}],operation_id:'operation1'});await saving;
 assert.equal(x.context.selectedDataset.version,8);assert.equal(x.node('#hpc-percentage-apply').disabled,true);
 assert.equal(x.calls[1].payload.preview_sha256,preview.preview_sha256);
});
test('cancel and changed navigation discard delayed previews',async()=>{
 let release;const x=ui(async()=>await new Promise(r=>release=r));
 const pending=x.click('preview');await x.click('cancel');release(preview);await pending;
 assert.equal(x.node('#hpc-percentage-apply').disabled,true);assert.equal(x.node('#hpc-percentage-result').textContent,'');
 const second=x.click('preview');x.context.selectedDataset={id:'another',version:1};release(preview);await second;
 assert.equal(x.node('#hpc-percentage-apply').disabled,true);
});
test('edited fields and newer dataset version require new preview',async()=>{
 const x=ui(async()=>preview);await x.click('preview');x.node('#hpc-percentage-rate').value='11';
 await x.click('apply');assert.equal(x.calls.length,1);
 await x.click('preview');x.context.selectedDataset.version++;await x.click('apply');assert.equal(x.calls.length,2);
 await x.click('preview');x.node('#hpc-value-document').listeners.change();assert.equal(x.node('#hpc-percentage-apply').disabled,true);
});
test('uncertain apply clears preview and requires checking history before repeating',async()=>{
 const x=ui(async url=>{if(url.endsWith('preview'))return preview;throw new Error('409 versión cambió');});
 await x.click('preview');await x.click('apply');await x.click('apply');assert.equal(x.calls.length,2);
 assert.match(x.node('#hpc-percentage-result').textContent,/409.*previsualizar/);
 assert.match(x.node('#hpc-percentage-result').textContent,/puede haberse guardado.*historia/);
});
test('invalid or repeated sequences never hit API',async()=>{
 const x=ui(async()=>preview);
 for(const value of ['1, 1','1.2','0','-1','9007199254740993']){x.node('#hpc-percentage-seqs').value=value;await x.click('preview');}
 assert.equal(x.calls.length,0);
});
test('original declaration starts false and currency/unit empty; changes invalidate preview',async()=>{
 const x=ui(async()=>preview);await x.click('preview');
 assert.equal(x.calls[0].payload.base_declaration,false);
 assert.equal(x.calls[0].payload.base_currency,null);assert.equal(x.calls[0].payload.base_unit_label,null);
 x.node('#hpc-percentage-base-currency').value='ARS';
 x.node('#hpc-percentage-base-unit').value='por práctica';
 x.node('#hpc-percentage-base-declaration').checked=true;
 x.node('#hpc-percentage-base-declaration').listeners.change();
 assert.equal(x.node('#hpc-percentage-apply').disabled,true);
 await x.click('preview');assert.equal(x.calls[1].payload.base_declaration,true);
 assert.equal(x.calls[1].payload.base_currency,'ARS');assert.equal(x.calls[1].payload.base_unit_label,'por práctica');
});
test('native-only and mixed selections preserve UUID identity and reject numeric substitute',async()=>{
 const id='11111111-2222-4333-8444-555555555555';
 const x=ui(async()=>({...preview,items:[{local_id:id,code:'987654321',before_ars:'2.05',after_ars:'2.26',unit_label:'por práctica'}]}));
 x.node('#hpc-percentage-seqs').value='';x.node('#hpc-percentage-local-ids').value=id;
 await x.click('preview');assert.deepEqual(x.calls[0].payload.tariff_seqs,[]);
 assert.deepEqual(x.calls[0].payload.local_ids,[id]);assert.match(x.node('#hpc-percentage-result').textContent,/Alta propia/);
 x.node('#hpc-percentage-seqs').value='1';await x.click('preview');assert.deepEqual(x.calls[1].payload.tariff_seqs,[1]);
 x.node('#hpc-percentage-local-ids').value='1';await x.click('preview');assert.equal(x.calls.length,2);
 x.node('#hpc-percentage-local-ids').value=`${id},${id}`;await x.click('preview');assert.equal(x.calls.length,2);
});

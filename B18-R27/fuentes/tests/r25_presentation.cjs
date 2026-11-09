// Windows smoke test. Creates its own fictitious demo and browser profile under .tmp.
const fs=require('node:fs'), path=require('node:path'), {spawn}=require('node:child_process');
const assert=require('node:assert/strict'), {createInterface}=require('node:readline');
const py=process.env.TFG_BROWSER_PYTHON;
const billingDates=process.argv.includes('--plazo');
const browserExe=[process.env.ProgramFiles+'/Google/Chrome/Application/chrome.exe',process.env['ProgramFiles(x86)']+'/Microsoft/Edge/Application/msedge.exe'].find(fs.existsSync);
if(!py || !browserExe)throw Error('Set TFG_BROWSER_PYTHON to the test venv; Chrome or Edge is required.');
const serverCode=String.raw`
import os,socket,sys,threading,uuid,subprocess,time,json,shutil
from pathlib import Path
import uvicorn
from app.api import create_app
base=Path.cwd().resolve(); root=base/'.tmp'/('r25-ui-'+uuid.uuid4().hex)
version='R26' if sys.argv[1]=='--plazo' else 'R25'
assert base.name=='fuentes' and base.parent.name=='B18-'+version
for k in ('TEMP','TMP','TMPDIR'):os.environ[k]=str(root.parent)
shutil.copytree(base/'.tmp'/('presentacion-'+version),root)
s=socket.socket();s.bind(('127.0.0.1',0));s.listen();url='http://127.0.0.1:'+str(s.getsockname()[1])
server=uvicorn.Server(uvicorn.Config(create_app(root,public_origin=url,local_http=True,processing_enabled=False),log_level='error'))
t=threading.Thread(target=server.run,kwargs={'sockets':[s]});t.start()
try:
 for _ in range(500):
  if server.started:break
  time.sleep(.02)
 if not server.started:raise RuntimeError('startup')
 print(json.dumps({'url':url,'fixture':root.name}),flush=True)
 sys.stdin.readline()
finally:server.should_exit=True;t.join(12);s.close()
`;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 let child,browser,session,stop,chromeExit; const pending=new Map(); let serial=0,buf='',stage='inicio';
 try{
   child=spawn(py,['-B','-u','-c',serverCode,billingDates?'--plazo':'--autorizaciones'],{stdio:['pipe','pipe','inherit'],windowsHide:true});
   const first=await createInterface({input:child.stdout})[Symbol.asyncIterator]().next();
   assert.ok(!first.done,'No inició la demo sintética');
   const {url,fixture}=JSON.parse(first.value);assert.match(fixture,/^r25-ui-[a-f0-9]{32}$/);
   const credential=fs.readFileSync(path.join('.tmp',fixture,'credenciales-demo.txt'),'utf8').split(/\r?\n/).find(x=>x.startsWith('demo-administrativo: ')).split(': ')[1];
   const profile=path.resolve('.tmp',fixture,'browser-profile');
   browser=spawn(browserExe,['--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--disable-background-networking','--disable-component-update','--disable-sync','--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1','--window-size=1440,900','--user-data-dir='+profile,'--remote-debugging-pipe','about:blank'],{stdio:['ignore','ignore','ignore','pipe','pipe'],windowsHide:true});
   chromeExit=new Promise(resolve=>browser.on('exit',resolve));
   browser.stdio[4].setEncoding('utf8');browser.stdio[4].on('data',v=>{
     buf+=v;let j;while((j=buf.indexOf('\0'))>=0){const r=JSON.parse(buf.slice(0,j));buf=buf.slice(j+1);if(r.method==='Page.javascriptDialogOpening' && r.params.type==='confirm' && (r.params.message.includes('pasar') || r.params.message.includes('Confirmar el débito total')))cmd('Page.handleJavaScriptDialog',{accept:true},r.sessionId).catch(()=>{});if(pending.has(r.id)){const f=pending.get(r.id);pending.delete(r.id);r.error?f.reject(Error(r.error.message)):f.resolve(r.result);}}
   });
   async function cmd(method,params={},sid=session){const id=++serial;
     return new Promise((resolve,reject)=>{const timer=setTimeout(()=>{pending.delete(id);reject(Error('CDP timeout: '+method));},12000);
       pending.set(id,{resolve:x=>{clearTimeout(timer);resolve(x);},reject:e=>{clearTimeout(timer);reject(e);}});
       browser.stdio[3].write(JSON.stringify({id,method,params,...(sid?{sessionId:sid}:{})})+'\0');});
   }
   stop=()=>cmd('Browser.close',{},null).catch(()=>{});
   const {targetId}=await cmd('Target.createTarget',{url:'about:blank'});
   session=(await cmd('Target.attachToTarget',{targetId,flatten:true})).sessionId;
   await cmd('Page.enable');await cmd('Page.navigate',{url});
   async function ev(expression){const r=await cmd('Runtime.evaluate',{expression,returnByValue:true});if(r.exceptionDetails)throw Error(stage+' · '+(r.exceptionDetails.exception?.description || r.exceptionDetails.text));return r.result.value;}
   async function wait(expression,label){stage=label;for(let i=0;i<120;i++){if(await ev(expression))return;await sleep(100);}console.error('Vista:',await ev("JSON.stringify({view:activeWorkspaceView,home:document.querySelector('#home-rows')?.innerText,intake:document.querySelector('#intake-status')?.innerText,board:document.querySelector('#board-count')?.textContent,msg:document.querySelector('#message')?.textContent,maps:document.querySelector('#code-map-content')?.textContent,role:currentRole,ds:selectedDataset?.id,mapType:typeof showCodeCorrespondences,mapEpoch:typeof codeMapEpoch==='number'?codeMapEpoch:null,mapHidden:document.querySelector('#code-map-panel')?.hidden,source:document.querySelector('#value-source')?.value})"));throw Error(label+' · '+await ev("document.querySelector('.row-decision-form [role=status]')?.textContent || document.querySelector('#sheet-review-content')?.textContent?.slice(0,150) || document.querySelector('#message')?.textContent || document.querySelector('#board-count')?.textContent || document.readyState"));}
   const q=s=>'document.querySelector('+JSON.stringify(s)+')';
   await wait("document.readyState==='complete' && typeof refresh==='function' && document.querySelector('[name=username]')!==null",'Login');await ev(q('[name=username]')+'.value="demo-administrativo";'+q('[name=password]')+'.value='+JSON.stringify(credential)+';'+q('#login-form')+'.requestSubmit();true');
   await wait(q('#invoice-batch')+'?.value','Factura ficticia');
   await ev("var s=document.querySelector('#invoice-dataset');s.value=Array.from(s.options).find(o=>o.textContent.includes('Autorizaciones y adicionales')).value;s.dispatchEvent(new Event('change'));true");
   await wait(q('#home-rows')+'.textContent.includes("autorizaciones_'+(billingDates?'R26':'R25')+'")','Factura ficticia de Imágenes');
   await ev(q('#home-rows button')+'.click();true');
   if(billingDates){
     const chip="Array.from(document.querySelectorAll('#exception-reasons button')).find(b=>b.textContent.startsWith('Facturación fuera de término'))";
     await wait(chip+"?.textContent.includes('1')",'Filtro con una prestación fuera de término');
     await ev(chip+'.click();true');
     const row='tr[data-source-row="9"]';
     await wait(q(row+' .column-review')+'?.innerText.includes("46 días") && practicePage.filtered_total===1','16 de julio fuera de término');
     assert.match(await ev(q(row+' .column-debit')+'.innerText'),/100\.000/);
     await ev(q(row+' .column-actions button')+'.click();true');
     await wait(q('#sheet-review-content')+'.innerText.includes("31/08/2026")','Motivo con fecha de prestación y cierre');
     assert.match(await ev(q('#sheet-review-content')+'.innerText'),/16\/07\/2026/);
     await ev(q('[data-queue=all]')+'.click();true');
     await wait("practicePage.items.some(r=>r.source_row===8 && r.billing_window.days===45)",'17 de julio en la planilla');
     assert.doesNotMatch(await ev(q('tr[data-source-row="8"] .column-review')+'.innerText'),/Fuera de término/);
     console.log('OK R26: filtro de plazo, motivo, importe de la TAC del 16/07 y fila del 17/07 en Chrome.');
     return;
   }
   const firstRow='tr[data-source-row="6"]';
   await wait(q(firstRow)+'?.innerText.includes("Posible débito")','TAC con orden posterior');
   assert.match(await ev(q(firstRow+' .column-debit')+'.innerText'),/100\.000/);
   await ev(q(firstRow+' .column-actions button')+'.click();true');
   await wait(q('#sheet-review-content')+'.innerText.includes("FICTICIO-TAC-03")','ID de la orden');
   const detail=await ev(q('#sheet-review-content')+'.innerText');
   assert.match(detail,/2026-08-03/);assert.match(detail,/2026-08-02/);
   await ev("window.prompt=()=> 'Verificación ficticia de la orden en el sistema de origen';Array.from(document.querySelectorAll('#sheet-review-content button')).find(b=>b.textContent.startsWith('Vincular orden')).click();true");
   await wait("practicePage.items.some(r=>r.source_row===7 && r.authorization?.panel_signal?.csv_coverage?.status==='already_used')",'No se duplica el aval de la segunda TAC');
   await ev(q('[data-queue=all]')+'.click();true');
   await wait("practicePage.items.some(r=>r.source_row===6 && r.authorization?.panel_signal?.csv_coverage?.verified_link)",'Primera TAC verificada');
   await ev(q('#board-source-info')+'.open=true;'+q('#incorporation-group')+'.click();true');
   await ev("const f=document.querySelector('#sheet-review-content form'),v=f.querySelectorAll('input');v[0].value='6, 7';v[1].value='2026-08-10';v[2].value='Comprobante FICTICIO R25, hoja 1';f.requestSubmit();true");
   await wait(q('#sheet-action-status')+'.textContent.includes("2 prestaciones")','Fecha común para ambas prestaciones');
   assert.equal(await ev("practicePage.items.find(r=>r.source_row===6).authorization.panel_signal.csv_coverage.temporal.state"),'sin_observaciones');
   console.log('OK R25: propuesta, ID y fechas, reasignación de uso único y comprobante para dos filas en Chrome.');
 }finally{
   if(stop)await stop();if(browser && (await Promise.race([chromeExit.then(()=>true),sleep(2500).then(()=>false)]))===false)browser.kill();
   if(child)child.stdin.end();
 }
})().catch(e=>{console.error(e.message);process.exitCode=1;});



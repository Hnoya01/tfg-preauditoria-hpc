// Windows smoke test. Creates its own fictitious demo and browser profile under .tmp.
const fs=require('node:fs'), path=require('node:path'), {spawn}=require('node:child_process');
const assert=require('node:assert/strict'), {createInterface}=require('node:readline');
const py=process.env.TFG_BROWSER_PYTHON;
const browserExe=[process.env.ProgramFiles+'/Google/Chrome/Application/chrome.exe',process.env['ProgramFiles(x86)']+'/Microsoft/Edge/Application/msedge.exe'].find(fs.existsSync);
if(!py || !browserExe)throw Error('Set TFG_BROWSER_PYTHON to the test venv; Chrome or Edge is required.');
const serverCode=String.raw`
import os,socket,sys,threading,uuid,subprocess,time,json,shutil
from pathlib import Path
import uvicorn
from app.api import create_app
base=Path.cwd().resolve(); root=base/'.tmp'/('r22-ui-'+uuid.uuid4().hex)
assert base.name=='fuentes' and base.parent.name=='B18-R22'
for k in ('TEMP','TMP','TMPDIR'):os.environ[k]=str(root.parent)
shutil.copytree(base/'.tmp'/'presentacion-HPC',root)
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
   child=spawn(py,['-B','-u','-c',serverCode],{stdio:['pipe','pipe','inherit'],windowsHide:true});
   const first=await createInterface({input:child.stdout})[Symbol.asyncIterator]().next();
   assert.ok(!first.done,'No inició la demo sintética');
   const {url,fixture}=JSON.parse(first.value);assert.match(fixture,/^r22-ui-[a-f0-9]{32}$/);
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
   async function wait(expression,label){stage=label;for(let i=0;i<120;i++){if(await ev(expression))return;await sleep(100);}console.error('Vista:',await ev("JSON.stringify({view:activeWorkspaceView,home:document.querySelector('#home-rows')?.innerText,intake:document.querySelector('#intake-status')?.innerText,board:document.querySelector('#board-count')?.textContent,msg:document.querySelector('#message')?.textContent})"));throw Error(label+' · '+await ev("document.querySelector('.row-decision-form [role=status]')?.textContent || document.querySelector('#sheet-review-content')?.textContent?.slice(0,150) || document.querySelector('#message')?.textContent || document.querySelector('#board-count')?.textContent || document.readyState"));}
   const q=s=>'document.querySelector('+JSON.stringify(s)+')';
   await wait("document.readyState==='complete' && typeof refresh==='function' && document.querySelector('[name=username]')!==null",'Login');await ev(q('[name=username]')+'.value="demo-administrativo";'+q('[name=password]')+'.value='+JSON.stringify(credential)+';'+q('#login-form')+'.requestSubmit();true');
   await wait(q('#invoice-batch')+'?.value','Factura ficticia');
   await wait(q('#home-rows button')+'!==null','Lista de facturas');await ev(q('#home-rows button')+'.click();true');
   const row='#practice-rows tr[data-source-row="2"]';
   await wait(q(row+' .column-budget')+'?.innerText.includes("200.000")','Importe autorizado de la TAC');
   assert.equal(await ev(q('#board-family')+'.value'),'images');assert.equal(await ev(q('#board-view')+'.value'),'exceptions');
   assert.match(await ev(q(row+' .column-billed')+'.innerText'),/450\.000/);
   assert.match(await ev(q(row+' .column-difference')+'.innerText'),/250\.000/);
   assert.match(await ev(q(row+' .column-debit')+'.innerText'),/250\.000.*|Para decidir/);
   await ev(q(row+' .column-actions button')+'.click();true');
   await wait(q(row+' + tr.inline-review-row .budget-summary')+'?.innerText.includes("DEMO-PRES-01")','Resumen debajo de la TAC');
   assert.match(await ev(q('.inline-review-row .budget-summary')+'.innerText'),/Operador ficticio/);
   await ev(q('#sheet-review-close')+'.click();true');assert.equal(await ev('document.querySelectorAll(".inline-review-row").length'),0);
   await ev(q('[data-queue=all]')+'.click();true');await wait(q(row+' .column-actions')+'?.innerText.includes("Solo consulta")','Factura completa');
   assert.equal(await ev(q(row)+'?.querySelectorAll("button").length'),0);
   await ev(q('[data-queue=images]')+'.click();true');await wait(q(row+' .column-actions button'),'Volver a pendientes');
   const click=async sel=>{for(let n=0;n<250;n++){const did=await ev("(()=>{const el="+q(sel)+";if(!el || el.disabled || el.closest('[hidden]'))return false;el.click();return true})()");if(did)return;await sleep(60);}throw Error('Acción no disponible: '+sel);};
   const form='.row-decision-form',save=form+' button[type=submit]';
   await click(row+' .column-actions button');await wait(q(form),'Decisión única');
   assert.equal(await ev('document.querySelectorAll(".row-decision-form input[type=radio]").length'),4);
   assert.equal(await ev(q('#handoff-send')+'.disabled'),true);
   for(const action of ['partial','total','none']){
     await click(form+' input[value='+action+']');assert.equal(await ev(q(save)+'.disabled'),true);
   }
   await click(form+' input[value=accept]');assert.equal(await ev(q(save)+'.disabled'),false);
   await click(save);
   await wait(q('tr[data-source-row="3"] + tr.inline-review-row .row-decision-form')+'!==null','Guardar y abrir la segunda TAC');
   assert.equal(await ev(q(row)+'===null'),true);
   assert.match(await ev(q('#sheet-action-status')+'.textContent'),/250\.000/);
   await click('[data-queue=row_reviewed]');await wait(q(row+' .column-review')+'?.innerText.includes("Revisada")','TAC revisada');
   assert.match(await ev(q(row+' .column-debit')+'.innerText'),/250\.000/);
   assert.equal(await ev(q('#handoff-send')+'.disabled'),true);
   await click('[data-queue=images]');const repeat='#practice-rows tr[data-source-row="3"]';
   await wait(q(repeat+' .column-actions button'),'Segunda TAC pendiente');
   await click(repeat+' .column-actions button');await wait(q(form),'Decidir sobre segunda TAC');
   await click(form+' input[value=accept]');
   await click(save);
   await wait(q('#handoff-send')+' && !'+q('#handoff-send')+'.disabled && !'+q('#handoff-send')+'.hidden','Cerrar habilitado tras ambas decisiones');
   await click('#handoff-send');
   await wait(q('#handoff-decisions tbody')+'?.rows.length===2','Administrativo ve las dos decisiones entregadas');
   assert.equal(await ev('document.querySelectorAll(".row-decision-form").length'),0);
   await click('#handoff-full');
   await wait(q('#review-workbench')+'.dataset.handoffView==="invoice" && '+q(row+' .column-actions')+'?.textContent==="Solo consulta"','Administrativo sin edición en la factura');
   assert.equal(await ev(q(row)+'.querySelectorAll("button").length'),0);
   await click('#logout');await wait('!'+q('#login-panel')+'.hidden','Cerrar sesión');
   const auditor=fs.readFileSync(path.join('.tmp',fixture,'credenciales-demo.txt'),'utf8').split(/\r?\n/).find(x=>x.startsWith('demo-auditor: ')).split(': ')[1];
   await ev(q('[name=username]')+'.value="demo-auditor";'+q('[name=password]')+'.value='+JSON.stringify(auditor)+';'+q('#login-form')+'.requestSubmit();true');
   await wait(q('#home-rows button')+'?.textContent==="Revisar decisiones"','Factura recibida');await click('#home-rows button');
   await wait(q('#handoff-decisions tbody')+'?.rows.length===2 && '+q('#handoff-inbox')+'?.innerText.includes("Facturas recibidas (1)")','Auditor recibe la factura');
   const cells=await ev('Array.from(document.querySelectorAll("#handoff-decisions tbody tr"),r=>Array.from(r.cells,c=>c.textContent))');
   assert.deepEqual(cells.map(r=>r[0]),['02/08/2026','04/08/2026']);
   assert.match(cells[0][4],/250\.000/);assert.match(cells[1][4],/450\.000/);
   assert.match(cells[0][5],/DEMO-PRES-01/);assert.match(cells[1][5],/aval/i);
   assert.equal(await ev(q('#handoff-send')+'.hidden'),true);
   assert.match(await ev(q('[data-total=images_ars]')+'.textContent'),/900\.000/);
   assert.match(await ev(q('[data-total=debit_ars]')+'.textContent'),/700\.000/);
   const firstTAC='#handoff-decisions tr[data-source-row="2"]';
   const order=cells[0][1],finalReason='Presupuesto ficticio cotejado: débito final de la primera TAC';
   await click(firstTAC+' .audit-adjust');await wait(q('.audit-edit'),'Editor del auditor');
   assert.equal(await ev(q('#audit-confirm')+'.disabled'),true);
   await ev(q('.audit-edit [name=amount]')+'.value="200000,00";'+q('.audit-edit [name=reason]')+'.value='+JSON.stringify(finalReason)+';'+q('.audit-edit')+'.requestSubmit();true');
   await wait(q('[data-total=debit_ars]')+'?.textContent.includes("650.000")','Totales tras el ajuste');
   assert.match(await ev(q('[data-total=net_ars]')+'.textContent'),/250\.000/);
   assert.match(await ev(q(firstTAC)+'.innerText'),/Administrativo: \$250\.000/);
   await click('#audit-confirm');
   await wait(q('a.audit-download')+'!==null','Cierre confirmado y Excel disponible');
   assert.equal(await ev(q('#audit-confirm')+'===null'),true);
   assert.equal(await ev('document.querySelectorAll(".audit-adjust").length'),0);
   const dir=path.resolve('.tmp',fixture,'downloads');fs.mkdirSync(dir);
   await cmd('Browser.setDownloadBehavior',{behavior:'allow',downloadPath:dir},null);
   await click('a.audit-download');
   const out=path.join(dir,'Debitos-Imagenes-HPC.xlsx');
   for(let i=0;i<100 && !fs.existsSync(out);i++)await sleep(100);
   assert.ok(fs.existsSync(out),'Descarga real en Chrome/Edge');
   const check=String.raw`from openpyxl import load_workbook
import sys
w=load_workbook(sys.argv[1]); s=w.active
values=list(s.values);assert values[:2]==[('Orden','Importe final (ARS)','Motivo final'),(sys.argv[2],200000,sys.argv[3])];assert len(values)==3 and values[2][1]==450000
assert s['B2'].data_type=='n'
w.close()`;
   const verify=require('node:child_process').spawnSync(py,['-B','-c',check,out,order,finalReason],{stdio:'inherit',windowsHide:true});
   assert.equal(verify.status,0);
   const dest=path.resolve('.test-results-r22');fs.mkdirSync(dest,{recursive:true});
   fs.copyFileSync(out,path.join(dest,'Demo-final-TAC.xlsx'));
   await click('a.audit-report-download');
   const pdfFile=path.join(dir,'Observaciones-HPC.pdf');
   for(let i=0;i<100 && !fs.existsSync(pdfFile);i++)await sleep(100);
   assert.ok(fs.readFileSync(pdfFile).subarray(0,5).equals(Buffer.from('%PDF-')));
   fs.copyFileSync(pdfFile,path.join(dest,'Demo-final-observaciones.pdf'));
   await ev('window.oldDocumentForTest=true');await cmd('Page.reload');await wait("typeof window.oldDocumentForTest==='undefined' && document.readyState==='complete' && "+q('#home-rows button')+"?.textContent==='Ver cierre'",'Historial al reingresar');await click('#home-rows button');
   await wait(q('a.audit-download')+'!==null && '+q('#audit-confirm')+'===null','Factura permanece cerrada tras reabrir');
   await click('#logout');await wait('!'+q('#login-panel')+'.hidden','Salir de auditor');
   await ev(q('[name=username]')+'.value="demo-administrativo";'+q('[name=password]')+'.value='+JSON.stringify(credential)+';'+q('#login-form')+'.requestSubmit();true');
   await wait(q('#home-rows button')+"?.textContent==='Ver cierre'",'Volver al cierre');
   await click('#home-rows button');await click('[data-workspace-view=salida]');await click('#revisions-load');
   await wait(q('#revisions-content textarea'),'Nueva revisión');
   await ev(q('#revisions-content textarea')+'.value="Evidencia adicional ficticia recibida después del cierre";'+q('#revisions-content input[type=checkbox]')+'.click();'+q('#revisions-content form')+'.requestSubmit();true');
   await wait(q('#revisions-content')+"?.textContent.includes('2 revisiones')",'Historial con dos revisiones');
   await click('[data-workspace-view=inicio]');
   await ev("const sel=document.querySelector('#invoice-dataset');sel.value=Array.from(sel.options).find(o=>o.textContent.includes('Orden mixta')).value;sel.dispatchEvent(new Event('change'));true");
   await wait(q('#home-rows')+".textContent.includes('Eco_y_resonancia')",'Factura mixta');
   await click('#home-rows button');await wait(q('tr[data-source-row="3"] .column-actions button'),'Ecografía pendiente');
   await click('tr[data-source-row="3"] .column-actions button');
   await wait("Array.from(document.querySelectorAll('#sheet-review-content button')).some(x=>x.textContent.includes('Vincular presupuesto'))",'Vínculo desde la prestación');
   await ev("Array.from(document.querySelectorAll('#sheet-review-content button')).find(x=>x.textContent.includes('Vincular presupuesto')).click();true");
   await ev("const f=document.querySelector('#sheet-review-content form');const inp=f.querySelectorAll('input');inp[0].value='200000';inp[1].value='Orden MIXTA-22, anexo ecografía';inp[2].value='Importe verificado exclusivamente para la eco';f.requestSubmit();true");
   await wait(q('tr[data-source-row="3"] .column-budget')+"?.innerText.includes('200.000')",'Importe solo de la eco');
   await wait(q('tr[data-source-row="3"] .column-difference')+"?.innerText.includes('250.000')",'Exceso de la eco');
   await click('[data-queue=all]');await wait(q('tr[data-source-row="2"] .column-reference')+"?.innerText.includes('120.000')",'Convenio independiente de resonancia');
   console.log('OK demo real de presentación en copia ficticia: dos decisiones, cierre por 650000, neto 250000, PDF y Excel con dos prestaciones, nueva revisión visible, resonancia en convenio y presupuesto solo para eco.');
 }finally{
   if(stop)await stop();if(browser && (await Promise.race([chromeExit.then(()=>true),sleep(2500).then(()=>false)]))===false)browser.kill();
   if(child)child.stdin.end();
 }
})().catch(e=>{console.error(e.message);process.exitCode=1;});

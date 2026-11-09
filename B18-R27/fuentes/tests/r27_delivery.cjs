// Windows smoke test. Creates its own fictitious demo and browser profile under .tmp.
const fs=require('node:fs'), path=require('node:path'), {spawn}=require('node:child_process');
const assert=require('node:assert/strict'), {createInterface}=require('node:readline');
const py=process.env.TFG_BROWSER_PYTHON;
const browserExe=[process.env.ProgramFiles+'/Google/Chrome/Application/chrome.exe',process.env['ProgramFiles(x86)']+'/Microsoft/Edge/Application/msedge.exe'].find(fs.existsSync);
if(!py || !browserExe)throw Error('Set TFG_BROWSER_PYTHON to the test venv; Chrome or Edge is required.');
const serverCode=String.raw`
import os,socket,sys,threading,uuid,time,json,shutil
from pathlib import Path
import uvicorn
from app.api import create_app
base=Path.cwd().resolve(); root=base/'.tmp'/('r27-ui-'+uuid.uuid4().hex)
assert base.name=='fuentes' and base.parent.name=='B18-R27'
for k in ('TEMP','TMP','TMPDIR'):os.environ[k]=str(root.parent)
shutil.copytree(base/'.tmp'/'presentacion-R27',root)
s=socket.socket();s.bind(('127.0.0.1',0));s.listen();url='http://127.0.0.1:'+str(s.getsockname()[1])
server=uvicorn.Server(uvicorn.Config(create_app(root,public_origin=url,local_http=True,processing_enabled=True),log_level='error'))
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
   const {url,fixture}=JSON.parse(first.value);assert.match(fixture,/^r27-ui-[a-f0-9]{32}$/);
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
   await cmd('Page.enable');await cmd('Runtime.enable');await cmd('Page.navigate',{url});
   async function ev(expression){const r=await cmd('Runtime.evaluate',{expression,returnByValue:true});if(r.exceptionDetails)throw Error(stage+' · '+(r.exceptionDetails.exception?.description || r.exceptionDetails.text));return r.result.value;}
   async function wait(expression,label){stage=label;for(let i=0;i<120;i++){if(await ev(expression))return;await sleep(100);}console.error('Vista:',await ev("JSON.stringify({view:activeWorkspaceView,home:document.querySelector('#home-rows')?.innerText,intake:document.querySelector('#intake-status')?.innerText,board:document.querySelector('#board-count')?.textContent,msg:document.querySelector('#message')?.textContent})"));throw Error(label+' · '+await ev("document.querySelector('.row-decision-form [role=status]')?.textContent || document.querySelector('#sheet-review-content')?.textContent?.slice(0,150) || document.querySelector('#message')?.textContent || document.querySelector('#board-count')?.textContent || document.readyState"));}
   const q=s=>'document.querySelector('+JSON.stringify(s)+')';
   await wait("document.readyState==='complete' && typeof refresh==='function' && document.querySelector('[name=username]')!==null",'Login');await ev(q('[name=username]')+'.value="demo-administrativo";'+q('[name=password]')+'.value='+JSON.stringify(credential)+';'+q('#login-form')+'.requestSubmit();true');

   const click=async sel=>{for(let n=0;n<250;n++){const did=await ev("(()=>{const el="+q(sel)+";if(!el || el.disabled || el.closest('[hidden]'))return false;el.click();return true})()");if(did)return;await sleep(60);}throw Error('Acción no disponible: '+sel);};
   const chooseIntake=async()=>{
     await wait("Array.from(document.querySelector('#invoice-dataset').options).some(o=>o.textContent.includes('Carga nueva'))",'Conjunto de carga ficticia');
     await ev("(()=>{const sel=document.querySelector('#invoice-dataset');sel.value=Array.from(sel.options).find(o=>o.textContent.includes('Carga nueva')).value;sel.dispatchEvent(new Event('change'));return true})()");
     await wait("selectedDataset?.label.includes('Carga nueva') && document.querySelector('#invoice-dataset').value===selectedDataset.id",'Cambio de conjunto');
   };
   const switchRole=async(user)=>{
     await click('#logout');await wait('!'+q('#login-panel')+'.hidden','Cerrar sesión');
     const pass=fs.readFileSync(path.join('.tmp',fixture,'credenciales-demo.txt'),'utf8').split(/\r?\n/).find(x=>x.startsWith(user+': ')).split(': ')[1];
     await ev(q('[name=username]')+'.value='+JSON.stringify(user)+';'+q('[name=password]')+'.value='+JSON.stringify(pass)+';'+q('#login-form')+'.requestSubmit();true');
     await chooseIntake();
   };
   await chooseIntake();
   await wait("selectedDataset?.label.includes('Carga nueva') && invoiceList.length===0",'Carga vacía');
   await ev(q('#home-add')+'.click();true');
   await wait("activeWorkspaceView==='facturacion' && !document.querySelector('#invoice-panel').hidden && !document.querySelector('#authorization-panel').hidden",'Excel y CSV juntos');
   assert.equal(await ev(q('#intake-open')+'.disabled'),true);
   const setFile=async(selector,file)=>{
       const doc=await cmd('DOM.getDocument');
       const field=await cmd('DOM.querySelector',{nodeId:doc.root.nodeId,selector});
       await cmd('DOM.setFileInputFiles',{nodeId:field.nodeId,files:[path.resolve('.tmp',fixture,file)]});
   };
   await setFile('#invoice-file','entrada-ficticia/TAC-ficticia.xlsx');
   await ev(q('#upload-form')+'.requestSubmit();true');
   await wait(q('#invoice-batch')+'.value && '+q('#message')+'.textContent.includes("Original guardado")','Guardar Excel');
   await ev(q('#invoice-period')+'.value="2026-08";'+q('#preview-button')+'.click();true');
   await wait("currentPreview?.can_confirm",'Conciliación del Excel');
   await ev(q('#period-confirmed')+'.click();'+q('#confirm-button')+'.click();true');
   await wait("invoiceList[0]?.import_id && !document.querySelector('#invoice-panel').hidden",'Excel incorporado');
   assert.equal(await ev(q('#intake-open')+'.disabled'),true);
   await setFile('#authorization-file','entrada-ficticia/Avales-ficticios.csv');
   await ev(q('#authorization-upload-form')+'.requestSubmit();true');
   await wait("authorizationPreview?.data.can_import",'CSV verificable');
   await ev(q('#authorization-provenance')+'.value="CSV ficticio recibido para la prueba de carga";'+q('#authorization-import-form')+'.requestSubmit();true');
   await wait(q('#authorization-scope-captures')+'.options.length===1','CSV incorporado');
   await ev(q('#authorization-scope-captures')+'.options[0].selected=true;'+q('#authorization-scope-note')+'.value="Exportación ficticia completa para este escenario de las dos TAC";'+q('#csv-complete')+'.click();'+q('#csv-complete-from')+'.value="2026-06-01";'+q('#csv-complete-until')+'.value="2026-08-31";'+q('#authorization-scope-form')+'.requestSubmit();true');
   await wait("!document.querySelector('#intake-open').disabled && document.querySelector('#intake-status').textContent.includes('con período declarado')",'Listo sin afirmar completitud');
   await ev(q('#intake-open')+'.click();true');
   await wait("activeWorkspaceView==='revision' && practicePage?.physical_total===2",'Planilla de la nueva factura');

   console.log('Excel y CSV incorporados por el administrativo; factura abierta.');
   const invoiceId=await ev(q('#invoice-batch')+'.value');
   await switchRole('demo-admin');
   await wait(q('#invoice-batch')+'.value==='+JSON.stringify(invoiceId),'Administrador en la misma factura');
   await click('#home-agreement');await wait(q('#value-source')+'.value','Fuente de convenio ficticio');
   await click('#hpc-scope-open');await wait(q('#hpc-scope-content form'),'Confirmar el alcance de esta factura');
   await click('#hpc-scope-content form input[type=checkbox]');
   await ev(q('#hpc-scope-content form')+'.requestSubmit();true');
   await wait(q('#hpc-scope-content')+'.innerText.includes("HPC confirmado con historia")','Confirmación explícita');
   await switchRole('demo-administrativo');
   await wait(q('#home-rows button')+'?.textContent==="Abrir factura"','Factura lista para analizar');await click('#home-rows button');
   await wait("document.querySelector('#invoice-batch').value==="+JSON.stringify(invoiceId)+" && activeWorkspaceView==='revision'",'Planilla de la misma factura');
   await click('#invoice-source-notices button');await click('#analyze-button');
   await wait(q('#processing-status')+'.innerText.includes("Terminado")','Análisis terminado');
   await click('[data-workspace-view=revision]');
   await wait("!document.querySelector('#practice-table').inert && practicePage?.batch.latest_run_id && activeWorkspaceView==='revision'",'Controles de la factura visibles en planilla');
   const row='#practice-rows tr[data-source-row="2"]';
   await wait(q(row+' .column-budget')+'?.innerText.includes("200.000")','Importe autorizado de la TAC');
   assert.equal(await ev(q('#board-family')+'.value'),'images');assert.equal(await ev(q('#board-view')+'.value'),'exceptions');
   assert.deepEqual(await ev("Array.from(document.querySelectorAll('#practice-rows tr[data-source-row]'),r=>r.dataset.sourceRow)"),['2','3']);
   assert.match(await ev(q(row+' .column-billed')+'.innerText'),/450\.000/);
   assert.match(await ev(q(row+' .column-difference')+'.innerText'),/250\.000/);
   assert.match(await ev(q(row+' .column-debit')+'.innerText'),/250\.000.*|Para decidir/);
   await click(row+' .column-actions button');
   await wait(q(row+' + tr.inline-review-row .budget-summary')+'?.innerText.includes("DEMO-PRES-01")','Resumen debajo de la TAC');
   assert.match(await ev(q('.inline-review-row .budget-summary')+'.innerText'),/Operador ficticio/);
   const evidence=path.resolve('.test-results-r27-browser');fs.mkdirSync(evidence,{recursive:true});
   const screenshot=await cmd('Page.captureScreenshot',{format:'png'});
   fs.writeFileSync(path.join(evidence,'TAC-en-revision.png'),Buffer.from(screenshot.data,'base64'));
   await ev(q('#sheet-review-close')+'.click();true');assert.equal(await ev('document.querySelectorAll(".inline-review-row").length'),0);
   await ev(q('[data-queue=all]')+'.click();true');await wait(q(row+' .column-actions')+'?.innerText.includes("Solo consulta")','Factura completa');
   assert.equal(await ev(q(row)+'?.querySelectorAll("button").length'),0);
   await ev(q('[data-queue=images]')+'.click();true');await wait(q(row+' .column-actions button'),'Volver a pendientes');

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
   await switchRole('demo-auditor');
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
   const secondReason=await ev(q('#handoff-decisions tr[data-source-row="3"]')+'.cells[5].firstChild.textContent');
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
values=list(s.values)
assert values==[('Orden','Importe final (ARS)','Motivo final'),(sys.argv[2],200000,sys.argv[3]),(sys.argv[4],450000,sys.argv[5])]
assert s['B2'].data_type==s['B3'].data_type=='n'
assert sum(r[1] for r in values[1:])==650000
w.close()`;
   const verify=require('node:child_process').spawnSync(py,['-B','-c',check,out,order,finalReason,cells[1][1],secondReason],{stdio:'inherit',windowsHide:true});
   assert.equal(verify.status,0);
   const dest=path.resolve('.test-results-r27-browser');fs.mkdirSync(dest,{recursive:true});
   fs.copyFileSync(out,path.join(dest,'Demo-final-TAC.xlsx'));
   await click('a.audit-report-download');
   const pdfFile=path.join(dir,'Observaciones-HPC.pdf');
   for(let i=0;i<100 && !fs.existsSync(pdfFile);i++)await sleep(100);
   assert.ok(fs.readFileSync(pdfFile).subarray(0,5).equals(Buffer.from('%PDF-')));
   fs.copyFileSync(pdfFile,path.join(dest,'Demo-final-observaciones.pdf'));
   await ev('window.oldDocumentForTest=true');await cmd('Page.reload');await wait("typeof window.oldDocumentForTest==='undefined' && document.readyState==='complete' && document.querySelector('#invoice-dataset').options.length>0",'Historial al reingresar');await chooseIntake(); await wait(q('#home-rows button')+"?.textContent==='Ver cierre'",'Factura de carga cerrada'); await click('#home-rows button');
   await wait(q('a.audit-download')+'!==null && '+q('#audit-confirm')+'===null','Factura permanece cerrada tras reabrir');
   console.log('OK Windows: carga por pantalla, análisis de la misma factura, dos TAC, pase, ajuste del auditor, cierre único, Excel descargado y comprobado, recarga del cierre.');
 }finally{
   if(stop)await stop();if(browser && (await Promise.race([chromeExit.then(()=>true),sleep(2500).then(()=>false)]))===false)browser.kill();
   if(child)child.stdin.end();
 }
})().catch(e=>{console.error(e.message);process.exitCode=1;});

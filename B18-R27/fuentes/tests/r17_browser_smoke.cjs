// Windows smoke test. Creates its own fictitious demo and browser profile under .tmp.
const fs=require('node:fs'), path=require('node:path'), {spawn}=require('node:child_process');
const assert=require('node:assert/strict'), {createInterface}=require('node:readline');
const py=process.env.TFG_BROWSER_PYTHON;
const browserExe=[process.env.ProgramFiles+'/Google/Chrome/Application/chrome.exe',process.env['ProgramFiles(x86)']+'/Microsoft/Edge/Application/msedge.exe'].find(fs.existsSync);
if(!py || !browserExe)throw Error('Set TFG_BROWSER_PYTHON to the test venv; Chrome or Edge is required.');
const serverCode=String.raw`
import os,socket,sys,threading,uuid,subprocess,time,json
from pathlib import Path
import uvicorn
from app.api import create_app
base=Path.cwd().resolve(); root=base/'.tmp'/('r17-ui-'+uuid.uuid4().hex)
assert base.name=='fuentes' and base.parent.name=='B18-R17'
for k in ('TEMP','TMP','TMPDIR'):os.environ[k]=str(root.parent)
subprocess.run([sys.executable,'-B','-m','scripts.create_review_journey_demo','--name',root.name,'--presupuesto'],stdout=subprocess.DEVNULL,check=True)
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
 let child,browser,session,stop,chromeExit; const pending=new Map(); let serial=0,buf='';
 try{
   child=spawn(py,['-B','-u','-c',serverCode],{stdio:['pipe','pipe','inherit'],windowsHide:true});
   const first=await createInterface({input:child.stdout})[Symbol.asyncIterator]().next();
   assert.ok(!first.done,'No inició la demo sintética');
   const {url,fixture}=JSON.parse(first.value);assert.match(fixture,/^r17-ui-[a-f0-9]{32}$/);
   const credential=fs.readFileSync(path.join('.tmp',fixture,'credenciales-demo.txt'),'utf8').split(/\r?\n/).find(x=>x.startsWith('demo-administrativo: ')).split(': ')[1];
   const profile=path.resolve('.tmp',fixture,'browser-profile');
   browser=spawn(browserExe,['--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--disable-background-networking','--disable-component-update','--disable-sync','--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1','--window-size=1440,900','--user-data-dir='+profile,'--remote-debugging-pipe','about:blank'],{stdio:['ignore','ignore','ignore','pipe','pipe'],windowsHide:true});
   chromeExit=new Promise(resolve=>browser.on('exit',resolve));
   browser.stdio[4].setEncoding('utf8');browser.stdio[4].on('data',v=>{
     buf+=v;let j;while((j=buf.indexOf('\0'))>=0){const r=JSON.parse(buf.slice(0,j));buf=buf.slice(j+1);if(pending.has(r.id)){const f=pending.get(r.id);pending.delete(r.id);r.error?f.reject(Error(r.error.message)):f.resolve(r.result);}}
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
   async function ev(expression){const r=await cmd('Runtime.evaluate',{expression,returnByValue:true});if(r.exceptionDetails)throw Error('Error al evaluar la pantalla: '+r.exceptionDetails.text);return r.result.value;}
   async function wait(expression,label){for(let i=0;i<120;i++){if(await ev(expression))return;await sleep(100);}throw Error(label+' · '+await ev("document.querySelector('.row-decision-form [role=status]')?.textContent || document.querySelector('#sheet-review-content')?.textContent?.slice(0,150) || document.querySelector('#message')?.textContent || document.querySelector('#board-count')?.textContent || document.readyState"));}
   const q=s=>'document.querySelector('+JSON.stringify(s)+')';
   await wait("document.readyState==='complete' && typeof refresh==='function' && document.querySelector('[name=username]')!==null",'Login');await ev(q('[name=username]')+'.value="demo-administrativo";'+q('[name=password]')+'.value='+JSON.stringify(credential)+';'+q('#login-form')+'.requestSubmit();true');
   await wait(q('#invoice-batch')+'?.value','Factura ficticia');
   await ev('let select='+q('#invoice-batch')+';select.value=Array.from(select.options).find(x=>x.value).value;select.dispatchEvent(new Event("change"));true');
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
   const click=async sel=>ev(q(sel)+'.click();true');
   const form='.row-decision-form',save=form+' button[type=submit]';
   await click(row+' .column-actions button');await wait(q(form),'Decisión única');
   assert.equal(await ev('document.querySelectorAll(".row-decision-form input[type=radio]").length'),4);
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
   await click(row+' .column-actions button');await wait(q(form),'Abrir decisión guardada');
   await click(form+' input[value=partial]');
   await ev(q(form+' [name=partial_ars]')+'.value="100000,50";'+q(form+' [name=partial_ars]')+'.dispatchEvent(new Event("input",{bubbles:true}));true');
   assert.equal(await ev(q(save)+'.disabled'),true);
   await ev(q(form+' [name=reason]')+'.value="Rectificación ficticia comprobada";'+q(form+' [name=reason]')+'.dispatchEvent(new Event("input",{bubbles:true}));true');
   await click(save);await wait(q('tr[data-source-row="3"] + tr.inline-review-row .row-decision-form')+'!==null','Corrección guardada; continúa la otra TAC');
   await click(form+' input[value=none]');
   await ev(q(form+' [name=reason]')+'.value="Sin débito tras revisión ficticia";'+q(form+' [name=reason]')+'.dispatchEvent(new Event("input",{bubbles:true}));true');
   await click(save);await wait(q('#sheet-action-status')+'?.textContent.includes("No quedan pendientes")','Último caso guardado');
   await click('[data-queue=row_reviewed]');await wait(q(row+' .column-debit')+'?.innerText.includes("100.000,50")','Importe corregido persistido');
   await click(row+' .column-actions button');await wait(q('.inline-review-row details')+'?.innerText.includes("Historial")','Historial persistido');
   console.log('OK: cuatro opciones, motivos, $250.000 aceptados, siguiente TAC, corrección parcial e historial, último caso sin débito.');

 }finally{
   if(stop)await stop();if(browser && (await Promise.race([chromeExit.then(()=>true),sleep(2500).then(()=>false)]))===false)browser.kill();
   if(child)child.stdin.end();
 }
})().catch(e=>{console.error(e.message);process.exitCode=1;});

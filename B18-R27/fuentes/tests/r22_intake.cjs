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
base=Path.cwd().resolve(); root=base/'.tmp'/('r22-ui-'+uuid.uuid4().hex)
assert base.name=='fuentes' and base.parent.name=='B18-R22'
for k in ('TEMP','TMP','TMPDIR'):os.environ[k]=str(root.parent)
subprocess.run([sys.executable,'-B','-m','scripts.create_review_journey_demo','--name',root.name,'--presupuesto'],stdout=subprocess.DEVNULL,check=True)
from app.db import connect
from app.security import issue_session,token_digest
from app.service import create_dataset,grant_access
from app.storage import read_verified
db=connect(root)
actor=db.execute("SELECT id FROM users WHERE username='demo-admin'").fetchone()[0]
token=token_digest(issue_session(db,actor)[0])
empty=create_dataset(db,token,'DEMO FICTICIO · Carga nueva')
grant_access(db,token,empty['id'],empty['version'],'demo-administrativo','reviewer','administrative')
(root/'entrada-ficticia.xlsx').write_bytes(read_verified(root,db.execute('SELECT source_sha256 FROM batches LIMIT 1').fetchone()[0]))
(root/'entrada-ficticia.csv').write_bytes(read_verified(root,db.execute('SELECT source_sha256 FROM authorization_uploads LIMIT 1').fetchone()[0]))
db.close()
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
   await wait("document.querySelector('#invoice-dataset').options.length===2",'Conjuntos');
   await ev("const dsSel=document.querySelector('#invoice-dataset');dsSel.value=Array.from(dsSel.options).find(o=>o.textContent.includes('Carga nueva')).value;dsSel.dispatchEvent(new Event('change'));true");
   await wait("selectedDataset?.label.includes('Carga nueva') && invoiceList.length===0",'Carga vacía');
   await ev(q('#home-add')+'.click();true');
   await wait("activeWorkspaceView==='facturacion' && !document.querySelector('#invoice-panel').hidden && !document.querySelector('#authorization-panel').hidden",'Excel y CSV juntos');
   assert.equal(await ev(q('#intake-open')+'.disabled'),true);
   const setFile=async(selector,file)=>{
       const doc=await cmd('DOM.getDocument');
       const field=await cmd('DOM.querySelector',{nodeId:doc.root.nodeId,selector});
       await cmd('DOM.setFileInputFiles',{nodeId:field.nodeId,files:[path.resolve('.tmp',fixture,file)]});
   };
   await setFile('#invoice-file','entrada-ficticia.xlsx');
   await ev(q('#upload-form')+'.requestSubmit();true');
   await wait(q('#invoice-batch')+'.value && '+q('#message')+'.textContent.includes("Original guardado")','Guardar Excel');
   await ev(q('#invoice-period')+'.value="2026-08";'+q('#preview-button')+'.click();true');
   await wait("currentPreview?.can_confirm",'Conciliación del Excel');
   await ev(q('#period-confirmed')+'.click();'+q('#confirm-button')+'.click();true');
   await wait("invoiceList[0]?.import_id && !document.querySelector('#invoice-panel').hidden",'Excel incorporado');
   assert.equal(await ev(q('#intake-open')+'.disabled'),true);
   await setFile('#authorization-file','entrada-ficticia.csv');
   await ev(q('#authorization-upload-form')+'.requestSubmit();true');
   await wait("authorizationPreview?.data.can_import",'CSV verificable');
   await ev(q('#authorization-provenance')+'.value="CSV ficticio recibido para la prueba de carga";'+q('#authorization-import-form')+'.requestSubmit();true');
   await wait(q('#authorization-scope-captures')+'.options.length===1','CSV incorporado');
   await ev(q('#authorization-scope-captures')+'.options[0].selected=true;'+q('#authorization-scope-note')+'.value="Ficticio asociado a esta factura; cobertura sin declarar";'+q('#authorization-scope-form')+'.requestSubmit();true');
   await wait("!document.querySelector('#intake-open').disabled && document.querySelector('#intake-status').textContent.includes('Cobertura sin confirmar')",'Listo sin afirmar completitud');
   await ev(q('#intake-open')+'.click();true');
   await wait("activeWorkspaceView==='revision' && practicePage?.physical_total===2",'Planilla de la nueva factura');
   await ev(q('#logout')+'.click();true');await wait('!'+q('#login-panel')+'.hidden','Salir del operador');
   const admin=fs.readFileSync(path.join('.tmp',fixture,'credenciales-demo.txt'),'utf8').split(/\r?\n/).find(x=>x.startsWith('demo-admin: ')).split(': ')[1];
   await ev(q('[name=username]')+'.value="demo-admin";'+q('[name=password]')+'.value='+JSON.stringify(admin)+';'+q('#login-form')+'.requestSubmit();true');
   await wait(q('#home-requests')+"?.textContent.includes('(0)')",'Contador del administrador');
   await ev(q('#home-requests')+'.click();true');await wait(q('#requests-home-content')+".textContent.includes('No hay solicitudes')",'Bandeja administrativa desde Facturas');
   console.log('OK Windows: alta desde Excel y CSV en una pantalla; Abrir planilla bloqueado hasta incorporar y seleccionar ambos, cobertura sin confirmar.');
 }finally{
   if(stop)await stop();if(browser && (await Promise.race([chromeExit.then(()=>true),sleep(2500).then(()=>false)]))===false)browser.kill();
   if(child)child.stdin.end();
 }
})().catch(e=>{console.error(e.message);process.exitCode=1;});

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
shutil.copytree(base/'.tmp'/'medicion-final-13000',root)
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
   async function ev(expression){const r=await cmd('Runtime.evaluate',{expression,returnByValue:true});if(r.exceptionDetails)throw Error('Error al evaluar la pantalla: '+r.exceptionDetails.text);return r.result.value;}
   async function wait(expression,label){for(let i=0;i<1000;i++){if(await ev(expression))return;await sleep(100);}console.error('Vista:',await ev("JSON.stringify({view:activeWorkspaceView,home:document.querySelector('#home-rows')?.innerText,intake:document.querySelector('#intake-status')?.innerText,board:document.querySelector('#board-count')?.textContent,msg:document.querySelector('#message')?.textContent})"));throw Error(label+' · '+await ev("document.querySelector('.row-decision-form [role=status]')?.textContent || document.querySelector('#sheet-review-content')?.textContent?.slice(0,150) || document.querySelector('#message')?.textContent || document.querySelector('#board-count')?.textContent || document.readyState"));}
   const q=s=>'document.querySelector('+JSON.stringify(s)+')';
   await wait("document.readyState==='complete' && typeof refresh==='function' && document.querySelector('[name=username]')!==null",'Login');await ev(q('[name=username]')+'.value="demo-administrativo";'+q('[name=password]')+'.value='+JSON.stringify(credential)+';'+q('#login-form')+'.requestSubmit();true');
   await wait(q('#home-rows button')+' && '+q('#home-rows button')+'.innerText.includes("Abrir")','Inicio volumen');
   await ev("window.t0=performance.now();document.querySelector('#home-rows button').click();true");
   await wait("practicePage && practicePage.physical_total===13000 && !document.querySelector('#review-workbench').hidden",'Abrir 13.000');
   const opening=await ev("performance.now()-window.t0");
   const runs=[];
   for(let i=0;i<20;i++){
     await ev("window.pageBefore=practicePage;window.t0=performance.now();document.querySelector('#exception-reasons button[aria-pressed=false]').click();true");
     await wait("practicePage!==window.pageBefore && document.querySelector('#board-refresh').disabled===false",'Aplicar filtro');
     runs.push(await ev('performance.now()-window.t0'));
   }
   await ev("window.pageBefore=practicePage;document.querySelector('[data-queue=images]').click();true");
   await wait("practicePage!==window.pageBefore && practicePage.items.length>1",'Pendientes');
   const form='.row-decision-form',save=form+' button[type=submit]';
   await ev("window.oldNum=practicePage.items[0].source_row;window.oldPending=practicePage.row_decision_counts.pending;document.querySelector('#practice-rows tr[data-source-row] .column-actions button').click();true");
   await wait(q(form),'Abrir decisión');
   await ev(q(form+' [value=total]')+'.click();'+q(form+' textarea')+'.value="Medición ficticia de revisión total";'+q(form+' textarea')+'.dispatchEvent(new Event("input",{bubbles:true}));true');
   await ev('window.t0=performance.now();'+q(save)+'.click();true');
   await wait("practicePage.row_decision_counts.pending===window.oldPending-1 && document.querySelector('tr.inline-review-row')?.previousElementSibling?.dataset.sourceRow!=window.oldNum && document.querySelector('.row-decision-form')",'Guardar y seguir');
   const saved=await ev('performance.now()-window.t0');
   const result={prestaciones:13000,opening_ms:opening,filter_ms:runs,save_next_ms:saved,pendientes_antes:await ev('window.oldPending'),pendientes_despues:await ev('practicePage.row_decision_counts.pending')};
   fs.mkdirSync('.test-results-r22',{recursive:true});fs.writeFileSync('.test-results-r22/volumen.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }finally{
   if(stop)await stop();if(browser && (await Promise.race([chromeExit.then(()=>true),sleep(2500).then(()=>false)]))===false)browser.kill();
   if(child)child.stdin.end();
 }
})().catch(e=>{console.error(e.message);process.exitCode=1;});

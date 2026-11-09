/* Real browser and loopback server; fixture data only. */
const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const {createInterface}=require('node:readline');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const code=String.raw`
import json,sys,threading,time,subprocess,uuid,shutil
from pathlib import Path
import uvicorn
from app.db import connect
from app.api import create_app
name='browser-journey-'+uuid.uuid4().hex
subprocess.run([sys.executable,'-B','-m','scripts.create_review_journey_demo','--name',name],check=True,stdout=subprocess.DEVNULL)
root=Path('.tmp')/name
credentials=dict(line.split(': ',1) for line in (root/'credenciales-demo.txt').read_text().splitlines())
c=connect(root)
dataset=c.execute('SELECT id FROM datasets').fetchone()[0]
batch=c.execute("SELECT id FROM batches WHERE original_name='FICTICIO_factura_A.xlsx'").fetchone()[0]
c.close()
server=uvicorn.Server(uvicorn.Config(create_app(root,public_origin='http://127.0.0.1:18784',local_http=True,processing_enabled=False),host='127.0.0.1',port=18784,log_level='error'))
t=threading.Thread(target=server.run);t.start()
try:
 for _ in range(200):
  if server.started:break
  time.sleep(.025)
 print(json.dumps({'dataset':dataset,'batch':batch,'credentials':credentials}),flush=True)
 sys.stdin.readline()
finally:
 server.should_exit=True;t.join(10);shutil.rmtree(root)

`;
(async()=>{
 fs.mkdirSync('.test-results',{recursive:true});
 const child=spawn(process.env.TFG_BROWSER_PYTHON || path.resolve(process.platform==='win32'?'.venv/Scripts/python.exe':'.venv/bin/python'),['-u','-B','-c',code]);let stderr='';child.stderr.on('data',v=>stderr+=v);
 const lines=createInterface({input:child.stdout})[Symbol.asyncIterator]();
 let browser;const report={errors:[],external:[],checks:[]};
 try{
  const first=await lines.next();if(first.done)throw Error(stderr);const info=JSON.parse(first.value);
  browser=await chromium.launch({headless:true,executablePath:fs.existsSync('/usr/bin/chromium')?'/usr/bin/chromium':undefined,args:['--no-sandbox']});
  const page=await browser.newPage({viewport:{width:1440,height:900}});page.setDefaultTimeout(10000);
  page.on('pageerror',e=>report.errors.push(e.message));
  page.on('request',r=>{if(!r.url().startsWith('http://127.0.0.1:18784'))report.external.push(r.url());});
  const login=async(username)=>{
   await page.goto('http://127.0.0.1:18784');await page.locator('[name=username]').fill(username);await page.locator('[name=password]').fill(info.credentials[username]);await page.locator('#login-form button').click();
   await page.locator('#invoice-dataset').selectOption(info.dataset);await page.locator('#invoice-batch').selectOption(info.batch);await page.locator('[data-queue=all]').click();
   await page.locator('tr[data-source-row="13"]').waitFor();
  };
  await login('demo-administrativo');
  assert.equal(await page.locator('#practice-rows tr[data-source-row]').count(),12);
  assert.equal(await page.locator('#practice-rows .affiliate-group').count(),3);
  assert.ok(await page.evaluate(()=>practicePage.items.some(i=>i.indication_count===0)));
  await page.screenshot({path:'.test-results/planilla-representativa.png',fullPage:false});
  const capture=async(name,button)=>{
   for(const size of [{width:1440,height:900},{width:1366,height:768}]){
    await page.setViewportSize(size);
    await page.waitForTimeout(80);
    await page.screenshot({path:'.test-results/ui-layout-diagnostic.png',fullPage:false});
    const layout=await page.evaluate(()=>{
     const rect=e=>{const r=e.getBoundingClientRect();return {top:r.top,bottom:r.bottom,left:r.left,right:r.right};};
     const panel=document.querySelector('#sheet-review-panel'),heading=document.querySelector('#sheet-review-heading'),grid=document.querySelector('.board-layout');
     const form=panel.querySelector('form');
     return {panel:rect(panel),heading:rect(heading),grid:rect(grid),form:form?{client:form.clientHeight,scroll:form.scrollHeight}:null,visibleRows:[...document.querySelectorAll('#practice-rows tr[data-source-row]')].filter(e=>{const r=e.getBoundingClientRect(),g=grid.getBoundingClientRect();return r.top>=g.top&&r.bottom<=g.bottom;}).length};
    });
    assert.ok(layout.grid.bottom<=layout.panel.top+1,JSON.stringify(layout));
    assert.ok(layout.visibleRows>=3,JSON.stringify(layout));
    assert.ok(layout.heading.top>=0 && layout.heading.bottom<size.height,JSON.stringify(layout));
    if(button){const r=await panel.getByRole('button',{name:button,exact:true}).boundingBox();assert.ok(r && r.y+r.height<=size.height && r.y>=layout.panel.top,JSON.stringify({r,layout}));}
    if(layout.form)assert.ok(layout.form.scroll<=layout.form.client+1,JSON.stringify(layout));
    assert.equal(await panel.locator('pre:visible').count(),0);
    await page.screenshot({path:`.test-results/${name}-${size.width}x${size.height}.png`,fullPage:false});
    report.checks.push(`${name} ${size.width}x${size.height}: header, action, ${layout.visibleRows} rows`);
   }
  };
  await page.locator('tr[data-source-row="2"]').getByRole('button',{name:'Revisar',exact:true}).click();
  const panel=page.locator('#sheet-review-panel');
  const selectControl=async(code)=>{
    await panel.getByLabel('Observación a revisar').evaluate(select=>{select.closest('details').open=true;});
    await panel.getByLabel('Observación a revisar').selectOption(code);
  };

  await selectControl('RN13');
  await panel.locator('.review-amounts').getByText('39,00 ARS',{exact:true}).waitFor();
  await capture('diferencia-suma','Guardar y seguir');
  await selectControl('RN17');
  await panel.getByRole('radio',{name:'Consultar al auditor'}).check();
  const fill=async(text)=>{await panel.getByLabel('Motivo y respaldo').fill(text+' FICTICIO: cotejadas constancias A y B; alcance pendiente de juicio humano.');};
  await fill('FICTICIO: ¿las dos constancias corresponden a prácticas independientes?');
  assert.equal(await panel.getByRole('radio',{checked:true}).count(),1);
  await capture('administrativo','Guardar y seguir');
  await panel.getByRole('button',{name:'Guardar y seguir',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#practice-rows .review-selected')?.dataset.sourceRow==='3');
  await page.locator('tr[data-source-row="2"]').getByRole('button',{name:'Revisar',exact:true}).click();
  await selectControl('RN17');
  await panel.getByLabel('Observación a revisar').locator('option:checked').filter({hasText:'Consulta al auditor'}).waitFor({state:'attached'});
  await page.locator('#logout').click();await login('demo-auditor');
  await page.locator('#observation-duty').selectOption('auditor');
  await panel.getByRole('button',{name:'Revisar e historia'}).first().click();
  await panel.getByRole('radio',{name:'Pedir información'}).check();await fill('FICTICIO: precisar qué documento respalda cada prestación.');
  assert.equal(await panel.getByRole('radio',{checked:true}).count(),1);
  await capture('solicitar-informacion','Guardar y seguir');
  await panel.getByRole('button',{name:'Guardar y seguir',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#practice-rows .review-selected')?.dataset.sourceRow==='3');
  await page.locator('tr[data-source-row="2"]').getByRole('button',{name:'Revisar',exact:true}).click();
  await selectControl('RN17');
  await panel.getByLabel('Observación a revisar').locator('option:checked').filter({hasText:'Esperando información'}).waitFor({state:'attached'});report.checks.push('solicitar no resuelve');
  await page.locator('#logout').click();await login('demo-administrativo');
  await page.locator('#observation-duty').selectOption('administrative');
  await page.locator('tr[data-source-row="2"]').getByRole('button',{name:'Revisar',exact:true}).click();await selectControl('RN17');
  await fill('FICTICIO: se agregan constancias identificadas para las dos prestaciones.');
  await panel.getByRole('radio',{name:'Completar información'}).check(); await panel.getByRole('button',{name:'Guardar y seguir',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#practice-rows .review-selected')?.dataset.sourceRow==='3');
  await page.locator('tr[data-source-row="2"]').getByRole('button',{name:'Revisar',exact:true}).click();
  await selectControl('RN17');
  await panel.getByLabel('Observación a revisar').locator('option:checked').filter({hasText:'Consulta al auditor'}).waitFor({state:'attached'});report.checks.push('completar no resuelve');
  await page.locator('#logout').click();await login('demo-auditor');
  await page.locator('#observation-duty').selectOption('auditor');await panel.getByRole('button',{name:'Revisar e historia'}).first().click();
  await panel.getByRole('radio',{name:'Descartar observación'}).check();await fill('FICTICIO: se descarta sólo la duplicación tras revisar las dos constancias independientes.');
  await capture('auditor','Guardar y seguir');
  // Lose the response after the server has committed; reopen and replay exact request.
  let lose=true;
  await page.route('**/observations',async route=>{if(route.request().method()==='POST'&&lose){lose=false;await route.fetch();await route.abort('failed');}else await route.continue();});
  await panel.getByRole('button',{name:'Guardar y seguir',exact:true}).click();await panel.getByText('No pudimos confirmar el guardado.',{exact:false}).waitFor();
  await page.locator('#sheet-review-close').click();await page.locator('tr[data-source-row="2"]').getByRole('button',{name:'Revisar',exact:true}).click();
  await panel.getByRole('button',{name:'Comprobar guardado',exact:true}).click();
  await selectControl('RN17');
  const response=await page.request.get(`http://127.0.0.1:18784/api/datasets/${info.dataset}/batches/${info.batch}/rows/2/observations`);const data=await response.json();
  const duplicate=data.items.find(i=>i.rule_code==='RN17'),sum=data.items.find(i=>i.rule_code==='RN13');
  assert.equal(duplicate.state,'resolved');assert.equal(sum.state,'pending');assert.equal(duplicate.history.filter(h=>h.action==='resolve').length,1);
  report.checks.push('cierre parcial','respuesta perdida y reenvío sin duplicación');
  assert.equal(report.errors.length,0);assert.equal(report.external.length,0);
  assert.doesNotMatch(await page.locator('tr[data-source-row="2"] .sheet-observation').innerText(),/\(\+1\)/);
  assert.equal(duplicate.history[0].actor,'demo-administrativo');assert.equal(duplicate.history.at(-1).actor,'demo-auditor');
  await capture('cierre-parcial');
  await panel.getByRole('button',{name:'Siguiente caso',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#sheet-review-heading').textContent.includes('Control ficticio'));
  const unchanged=await (await page.request.get(`http://127.0.0.1:18784/api/datasets/${info.dataset}/batches/${info.batch}/rows/3/observations`)).json();
  assert.ok(unchanged.items.every(i=>i.history.length===0));
  report.checks.push('dos cuentas atribuidas; siguiente no decide; 12 prestaciones y tres afiliados');
 }finally{if(browser)await browser.close();child.stdin.end('\n');await new Promise(resolve=>child.on('close',resolve));fs.writeFileSync('.test-results/observation-browser.json',JSON.stringify(report,null,2));}
 console.log(JSON.stringify(report));
})().catch(e=>{console.error(e);process.exitCode=1;});

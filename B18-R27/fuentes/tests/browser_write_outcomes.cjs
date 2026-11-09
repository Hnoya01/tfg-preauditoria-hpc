/* Optional real Chromium + real loopback HTTP check. No production data.
   Requires an available Playwright/Chromium runtime; not an npm dependency.
   node tests/browser_write_outcomes.cjs [--baseline-u2]
   Baseline uses immutable 91a69cff JavaScript served by the browser route only. */
const {chromium}=require('playwright');
const {spawn,execFileSync}=require('node:child_process');
const {createInterface}=require('node:readline');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const baseline=process.argv.includes('--baseline-u2');
const python=process.env.TFG_BROWSER_PYTHON || path.resolve(process.platform==='win32'?'.venv/Scripts/python.exe':'.venv/bin/python');
// datetime-local canonicalizes zero seconds; retain the same local wall time.
function localDateTimeValue(instant=Date.now()) {
 const d=new Date(instant);
 return new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,19).replace(/:00$/, '');
}
async function verifyDateTimeField(page,field) {
 const evidence={count:await field.count(),cases:[]};
 const save=()=>fs.writeFileSync('.test-results/browser-datetime.json',JSON.stringify(evidence,null,2));
 save();assert.equal(evidence.count,1);
 const inspect=element=>({outerHTML:element.outerHTML,type:element.type,step:element.step,value:element.value,
  valueAsNumber:element.valueAsNumber,valid:element.validity.valid,stepMismatch:element.validity.stepMismatch,
  badInput:element.validity.badInput,valueMissing:element.validity.valueMissing,checkValidity:element.checkValidity()});
 evidence.initial=await field.evaluate(inspect);save();
 assert.equal(evidence.initial.type,'datetime-local');assert.equal(evidence.initial.step,'1');
 for(const [requested,expected] of [['2026-10-31T14:11:00','2026-10-31T14:11'],
   ['2026-10-31T14:11:01','2026-10-31T14:11:01'],['2026-10-31T14:11','2026-10-31T14:11']]) {
  const record={requested,expected};evidence.cases.push(record);save();
  // Native assignment is diagnostic only; the verified interaction uses fill below.
  await field.evaluate((element,value)=>{element.value=value;},requested);
  record.native=await field.evaluate(inspect);
  await field.fill('');
  try {await field.fill(requested);record.rawFill={outcome:'success'};}
  catch(error){record.rawFill={outcome:'error',message:error.message};}
  record.afterRawFill=await field.evaluate(inspect);save();
  await field.fill('');
  record.generated=await page.evaluate(localDateTimeValue,requested);
  assert.equal(record.generated,expected);
  record.temporal=await page.evaluate(({requested,generated})=>({requested:new Date(requested).getTime(),
   generated:new Date(generated).getTime(),zone:Intl.DateTimeFormat().resolvedOptions().timeZone}),{requested,generated:record.generated});
  assert.equal(record.temporal.generated,record.temporal.requested);
  await field.fill(record.generated);record.afterCanonicalFill=await field.evaluate(inspect);save();
  assert.equal(record.afterCanonicalFill.value,expected);assert.equal(record.afterCanonicalFill.valid,true);
  assert.equal(record.afterCanonicalFill.checkValidity,true);assert.equal(record.afterCanonicalFill.stepMismatch,false);
  assert.equal(record.afterCanonicalFill.valueAsNumber,record.native.valueAsNumber);
 }
 await field.fill('');
}
const serverCode=String.raw`
import json,sys,threading,time
import uvicorn
from app.api import create_app
from app.db import connect
from tests.test_medical_consultations import MedicalConsultationTests
from tests.test_rn14_proposals import Rn14ProposalTests
from tests.test_p02 import PASSWORD
kind=sys.argv[1]
f=MedicalConsultationTests() if kind in ('u2','q1_q2') else Rn14ProposalTests()
f.setUp()
try:
    if kind=='q1_q2':
        from tests.test_p02 import book
        from unittest.mock import patch
        f.batch=f.import_book(book([('15/08/2026',10,20,30,'I')]),'FICTICIO internacion historica.xlsx')
        # Synthetic legacy correspondence, created under the previous Q1 policy.
        with patch('app.medical_consultations._inpatient',return_value=False): consultation,_=f.ask()
    elif kind=='u2': consultation,_=f.ask()
    elif kind.startswith('rn14'): f.ready(simulation=True)
    else: f.demo()
    def snapshot():
        c=connect(f.root)
        try:
            result={t:[dict(r) for r in c.execute('SELECT * FROM '+t+' ORDER BY rowid')] for t in ('medical_consultations','medical_responses','audit_events','rn14_simulation_versions','proposal_versions','row_economic_references','control_runs','review_decisions','revision_closures')}
            result['dataset_version']=c.execute('SELECT version FROM datasets WHERE id=?',(f.dataset['id'],)).fetchone()[0]
            return result
        finally:c.close()
    before=snapshot()
    f.client.__exit__(None,None,None)
    app=create_app(f.root,public_origin='http://127.0.0.1:18783',local_http=True,processing_enabled=False)
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=18783,log_level='error'))
    thread=threading.Thread(target=server.run);thread.start()
    try:
        for _ in range(200):
            if server.started:break
            time.sleep(.025)
        if not server.started:raise RuntimeError('Server did not start')
        print(json.dumps({'dataset':f.dataset['id'],'batch':f.batch,'password':PASSWORD,'source':getattr(f,'source_id',None),'document':getattr(f,'agreement_id',None)}),flush=True)
        sys.stdin.readline()
        after=snapshot()
        print(json.dumps({'before':before,'after':after}),flush=True)
    finally:server.should_exit=True;thread.join(10)
finally:f.temp.cleanup()
`;
async function scenario(browser,kind){
 const child=spawn(python,['-u','-B','-c',serverCode,kind],{stdio:['pipe','pipe','pipe']});
 let stderr='';child.stderr.on('data',v=>stderr+=v);const lines=createInterface({input:child.stdout})[Symbol.asyncIterator]();
 const first=await lines.next();if(first.done)throw Error('Fixture failed: '+stderr);const info=JSON.parse(first.value);
 const page=await browser.newPage({viewport:{width:1440,height:1100}});page.setDefaultTimeout(10000);
 const errors=[],external=[],posts=[];let inject=false,failedRead=false,lossDelivered=false,thrown=null;
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',async route=>{
  const req=route.request(),url=new URL(req.url());
  if(url.hostname!=='127.0.0.1'){external.push(url.origin);return route.abort();}
  if(baseline && url.pathname==='/assets/medical_consultations.js')return route.fulfill({status:200,contentType:'application/javascript',body:execFileSync('git',['show','91a69cff9c94e4acfba7a081dc49fb44ce8c8b8c:web/medical_consultations.js'])});
  const target=(kind==='u2'||kind==='q1_q2')?url.pathname.endsWith('/responses'):url.pathname.endsWith(kind.startsWith('rn14')?'/rn14-proposal':'/economic-applicability');
  if(inject && target && req.method()==='POST'){
   const result=await route.fetch();const body=await result.json();posts.push({request:JSON.parse(req.postData()),status:result.status(),id:body.id,replayed:body.replayed});
   if(!lossDelivered && (kind==='u2'||kind.endsWith('unknown'))){lossDelivered=true;return route.abort('failed');}
   return route.fulfill({response:result});
  }
  if(inject && posts.length && kind.endsWith('confirmed') && req.method()==='GET' && url.pathname.endsWith('/processing-attempts')){failedRead=true;return route.abort('failed');}
  return route.continue();
 });
 try {
  await page.goto('http://127.0.0.1:18783');await page.locator('[name=username]').fill('owner');await page.locator('[name=password]').fill(info.password);await page.locator('#login-form button').click();
  await page.locator('#invoice-dataset').selectOption(info.dataset);await page.locator('#invoice-batch').selectOption(info.batch);await page.locator('#board-family').selectOption('all');if(kind==='q1_q2'){await page.locator('#board-more-filters summary').click();await page.locator('#board-scope').selectOption('excluded');}
  await page.waitForFunction(()=>typeof selectedDataset!=='undefined' && selectedDataset && document.querySelector('#practice-rows button'));
  if(kind==='q1_q2'){
   await page.locator('#practice-rows button[data-row="2"]').click();await page.getByRole('button',{name:'Consultas y respuestas externas',exact:true}).click();
   await page.getByText('No se permiten consultas nuevas.',{exact:false}).waitFor();
   assert.equal(await page.getByRole('button',{name:'Registrar consulta',exact:true}).count(),0);
   await page.locator('#sheet-review-content details summary').first().click();
   await page.getByLabel('Emisor externo (nombre informado)',{exact:true}).fill('Emisora ficticia histórica');
   await page.getByLabel('Fecha de recepción informada (hora local)',{exact:true}).fill('2020-01-01T12:00:01');
   await page.getByLabel('Medio externo',{exact:true}).selectOption('email');
   await page.getByLabel('Referencia del intercambio o documento (sin adjuntar archivos)',{exact:true}).fill('FICTICIO correo histórico con fecha informada');
   await page.getByLabel('Respuesta o aclaración externa',{exact:true}).fill('FICTICIO respuesta anterior al registro de la consulta.');
   inject=true;await page.getByRole('button',{name:'Registrar respuesta externa',exact:true}).click();
   await page.getByText('Registro guardado.',{exact:false}).waitFor();assert.equal(posts.length,1);
   await page.getByRole('button',{name:'Actualizar historial',exact:true}).click();
   await page.locator('#sheet-review-content details summary').first().click();
   await page.getByText('Registro en el sistema por',{exact:false}).waitFor();
   assert.match(await page.locator('#sheet-review-content').innerText(),/2020-01-01/);
   assert.equal(await page.getByRole('button',{name:'Registrar consulta',exact:true}).count(),0);
  }else if(kind==='u2'){
   await page.locator('#practice-rows button[data-row="2"]').click();await page.getByRole('button',{name:'Consultas y respuestas externas',exact:true}).click();
   await page.locator('#sheet-review-content details summary').first().click();
   await page.getByLabel('Emisor externo (nombre informado)',{exact:true}).fill('Emisora ficticia U2');
   await verifyDateTimeField(page,page.getByLabel(baseline?'Fecha de respuesta (hora local)':'Fecha de recepción informada (hora local)',{exact:true}));
   const local=await page.evaluate(localDateTimeValue);
   await page.getByLabel(baseline?'Fecha de respuesta (hora local)':'Fecha de recepción informada (hora local)',{exact:true}).fill(local);await page.getByLabel('Medio externo',{exact:true}).selectOption('email');
   await page.getByLabel('Referencia del intercambio o documento (sin adjuntar archivos)',{exact:true}).fill('FICTICIO correo U2 001');await page.getByLabel('Respuesta o aclaración externa',{exact:true}).fill('FICTICIO respuesta U2 conservada exactamente.');
   inject=true;await page.getByRole('button',{name:'Registrar respuesta externa',exact:true}).click();await page.getByText('Resultado incierto.',{exact:false}).waitFor();
   await page.getByLabel('Consulta al auditor médico',{exact:true}).fill('FICTICIO consulta concurrente que obtiene conflicto.');await page.getByRole('button',{name:'Registrar consulta',exact:true}).click();
   await page.getByRole('button',{name:'Actualizar conservando borradores',exact:true}).click();await page.locator('#sheet-review-content details summary').first().click();
   await page.getByRole('button',{name:baseline?'Registrar respuesta externa':'Comprobar / repetir la misma operación',exact:true}).click();await page.getByText('Registro guardado.',{exact:false}).waitFor();
   assert.equal(posts.length,2);
   if(baseline){assert.notEqual(posts[0].id,posts[1].id);assert.notDeepEqual(posts[0].request,posts[1].request);}
   else {assert.equal(posts[0].id,posts[1].id);assert.deepEqual(posts[0].request,posts[1].request);assert.equal(posts[1].replayed,true);}
  }else {
   if(kind.startsWith('rn14')){
    await page.evaluate(()=>showRn14Proposal(3));
    await page.getByLabel('Tratamiento del importe',{exact:true}).selectOption('adjust');
    await page.getByLabel('Importe ajustado ARS',{exact:true}).fill('1.50');await page.getByLabel('Cálculo del ajuste',{exact:true}).fill('2.00 - 0.50 = 1.50');await page.getByLabel('Fundamento del ajuste',{exact:true}).fill('FICTICIO fundamento U1 de ajuste conservado.');
    await page.getByRole('checkbox',{name:'Revisé el cálculo y su respaldo.',exact:false}).check();
   }else{
    await page.evaluate(source=>{document.querySelector('#value-source').value=source;return showEconomicApplicability(3);},info.source);
    await page.getByLabel('Convenio registrado',{exact:true}).selectOption(info.document);await page.getByLabel('Página del convenio',{exact:true}).fill('1');await page.getByLabel('Fragmento que respalda ARS, unidad y condiciones',{exact:true}).fill('FICTICIO: ARS por práctica según referencia general.');await page.getByLabel('Fundamento de aplicación a esta fila',{exact:true}).fill('FICTICIO fundamento U1 de aplicabilidad conservado.');await page.getByRole('checkbox',{name:'Confirmo este registro documental',exact:false}).check();
   }
   const button=page.getByRole('button',{name:kind.startsWith('rn14')?'Guardar simulación DEMO':'Guardar aplicabilidad sin analizar',exact:true});
   inject=true;await button.click();
   if(kind.endsWith('confirmed')){await page.getByText('Guardado confirmado',{exact:false}).waitFor();await page.getByText('Falta actualizar la pantalla',{exact:false}).waitFor();assert.equal(failedRead,true);}
   else {await page.getByText('Resultado incierto del guardado',{exact:false}).waitFor();await page.getByRole('button',{name:'Comprobar historial sin reenviar',exact:true}).click();await page.getByText('Historial consultado',{exact:false}).waitFor();assert.match(await page.locator('#sheet-review-content').innerText(),new RegExp(posts[0].id));}
   assert.equal(await button.isDisabled(),true);assert.equal(posts.length,1);
  }
  await page.screenshot({path:`.test-results/${baseline?'baseline-':''}${kind}-browser.png`,fullPage:true});
 }catch(e){thrown=e;await page.screenshot({path:`.test-results/${kind}-browser-failure.png`,fullPage:true});}
 finally {await page.close();child.stdin.end('stop\n');}
 const last=await lines.next();if(last.done)throw Error('Missing fixture evidence '+stderr);const state=JSON.parse(last.value);
 const exited=await new Promise(resolve=>child.exitCode!==null?resolve(child.exitCode):child.on('exit',resolve));assert.equal(exited,0,stderr);
 if(thrown)throw thrown;
 const b=state.before,a=state.after;
 for(const table of ['medical_consultations','control_runs','review_decisions','proposal_versions','revision_closures'])assert.deepEqual(a[table],b[table]);
 if(kind==='u2'||kind==='q1_q2'){
  if(kind==='q1_q2'){const response=a.medical_responses.at(-1);assert.ok(response.responded_at<a.medical_consultations[0].created_at);assert.ok(response.created_at>=a.medical_consultations[0].created_at);}
  const count=baseline?2:1;assert.equal(a.medical_responses.length-b.medical_responses.length,count);
  assert.equal(a.dataset_version-b.dataset_version,count);
  assert.equal(a.audit_events.filter(e=>e.action==='external_response_recorded').length-b.audit_events.filter(e=>e.action==='external_response_recorded').length,count);
 }else {const table=kind.startsWith('rn14')?'rn14_simulation_versions':'row_economic_references';assert.equal(a[table].length-b[table].length,1);}
 if(thrown)throw thrown;assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
 return {kind,baseline,posts,counts:{responses:a.medical_responses.length,simulations:a.rn14_simulation_versions.length,realProposals:a.proposal_versions.length},unchanged:['medical_consultations','control_runs','review_decisions','proposal_versions','revision_closures'],errors,external};
}
(async()=>{
 fs.mkdirSync('.test-results',{recursive:true});const executablePath=process.env.TFG_CHROMIUM || (fs.existsSync('/usr/bin/chromium')?'/usr/bin/chromium':undefined);
 const browser=await chromium.launch({headless:true,executablePath,args:['--no-sandbox']});const results=[];
 try {for(const kind of baseline?['u2']:(process.env.TFG_BROWSER_CASE?[process.env.TFG_BROWSER_CASE]:['u2','rn14_confirmed','rn14_unknown','hpc_confirmed','hpc_unknown','q1_q2']))results.push(await scenario(browser,kind));}
 finally {await browser.close();fs.writeFileSync(`.test-results/${baseline?'u2-before':'u1-u2-final'}-browser.json`,JSON.stringify(results,null,2));}
 console.log(JSON.stringify({scenarios:results.map(r=>r.kind),baseline,passed:true}));
})().catch(e=>{console.error(e);process.exitCode=1;});

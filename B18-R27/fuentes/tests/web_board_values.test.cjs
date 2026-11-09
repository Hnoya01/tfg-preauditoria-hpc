const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm');
const fs=require('node:fs'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../web/workbench.js'),'utf8');
function render(ref){
 const rows=[];const document={createElement:()=>({textContent:'',title:'',classList:{values:[],add(v){this.values.push(v);}}})};
 const start=source.indexOf('function renderReferenceCells'),end=source.indexOf('\nfunction renderPracticeRows',start);
 const fn=vm.runInNewContext('('+source.slice(start,end)+')',{document});
 fn({append:(...cells)=>rows.push(...cells)},{reference_comparison:ref});return rows;
}
test('reference columns display unknown dimensions and conditional difference, not debit',()=>{
 const [price,difference]=render({recorded_amount:'15.00',declared_currency:null,declared_unit:null,difference_ars_if_comparable:'2.00',status:'numeric_above_candidate',candidate_total_if_ars_and_same_unit:'30.00'});
 assert.match(price.textContent,/moneda pendiente/);assert.match(price.textContent,/unidad pendiente/);
 assert.equal(difference.textContent,'2.00 · condicional');assert.ok(difference.classList.values.includes('reference-over'));
 assert.match(difference.title,/no es débito/);assert.doesNotMatch(price.textContent,/ARS/);
});
test('known documented dimensions and missing prices remain distinct',()=>{
 const [price,diff]=render({recorded_amount:'14.00',declared_currency:'ARS',declared_unit:'por práctica',difference_ars_if_comparable:'0.00',status:'numeric_equal'});
 assert.match(price.textContent,/ARS · por práctica/);assert.equal(diff.textContent,'0.00 · candidata');assert.equal(diff.classList.values.length,0);
 const unknown=render({status:'no_exact_hpc_tariff'});assert.match(unknown[0].textContent,/indeterminado/);assert.equal(unknown[1].textContent,'Sin diferencia determinable');
 const closed=render({status:'closed_revision_not_compared'});assert.match(closed[0].textContent,/cerrada/);assert.equal(closed[1].classList.values.length,0);
 const html=fs.readFileSync(path.join(__dirname,'../web/index.html'),'utf8');assert.match(html,/class="column-reference"[^>]*>Convenio HPC/);assert.match(html,/class="column-debit"[^>]*>Débito<br>propuesto/);
 assert.match(source,/heading.colSpan=columnCount/);assert.match(source,/cell.colSpan=columnCount/);
});
test('exploratory filter travels separately from RN14 and resets pagination',()=>{
 const nodes={},events={},trace=[];const get=id=>nodes[id]??={value:'',addEventListener:(name,fn)=>events[id]=fn};
 get('#board-reference-comparison-state').value='differences';get('#board-rule').selectedOptions=[{value:'RN14'}];
 let start=source.indexOf('function practiceFilters()'),end=source.indexOf('\nasync function loadPracticeBoard(',start);
 const ctx={document:{querySelector:get},practiceOffset:50,clearSheetSelection:()=>trace.push('clear'),closePracticeDetail:()=>trace.push('close'),loadPracticeBoard:()=>trace.push('load')};
 const fn=vm.runInNewContext('('+source.slice(start,end)+')',ctx);assert.equal(fn().reference_comparison_state,'differences');assert.deepEqual(Array.from(fn().rules),['RN14']);assert.equal(fn().rule,undefined);
 start=source.indexOf("  for(const id of ['board-report-document-state'");end=source.indexOf('\n',start);
 vm.runInNewContext(source.slice(start,end),ctx);events['#board-reference-comparison-state']();assert.equal(ctx.practiceOffset,0);assert.deepEqual(trace,['clear','close','load']);
});
test('linked catalog suggestions show a price but never a numeric difference or applied identity',()=>{
 const [price,difference]=render({status:'no_exact_hpc_tariff',recorded_amount:null,difference_ars_if_comparable:null,
 related_hpc_references:{use_limit:'Enlace declarado, no equivalencia clínica verificada; no aplicado.',candidates:[{order_code:'180104',tariff_code:'18010400',recorded_amount:'31786.61',order_code_seqs:[1],convention_code_seqs:[2],practice_id:'p',source_locator:'seq=1',document_source_id:'doc',document_page:5,temporal_relation:'inside_declared_dates',source_sha256:'abc'}]}});
 assert.match(price.textContent,/31786.61.*moneda\/unidad pendientes.*sin verificar/);
 assert.match(price.title,/no equivalencia clínica/);assert.match(price.title,/página 5/);
 assert.equal(difference.textContent,'Sin diferencia determinable');assert.equal(difference.classList.values.length,0);
});
test('related comparison shows conditional linkage even with documented dimensions',()=>{
 const [price,difference]=render({status:'no_exact_hpc_tariff',related_comparison:{status:'numeric_above_candidate',difference_ars_if_comparable:'4.00',candidate_total_if_ars_and_same_unit:'28.00',use_limit:'Enlace sujeto a verificación; no débito.'},related_hpc_references:{use_limit:'Enlace declarado',candidates:[{order_code:'180104',tariff_code:'18010400',recorded_amount:'99.00',effective_reference:{status:'documented_version_candidate',value_version:{id:'v'},recorded_amount:'14.00',declared_unit:'por práctica'},order_code_seqs:[1],convention_code_seqs:[2],practice_id:'p'}]}});
 assert.match(price.textContent,/14.00.*ARS.*por práctica.*sin verificar/);
 assert.equal(difference.textContent,'4.00 · enlace sujeto a verificación');assert.match(difference.title,/no débito/);
});
test('related corrupt version and withdrawal never silently display original as current price',()=>{
 const candidate={order_code:'180104',tariff_code:'18010400',recorded_amount:'15.00',order_code_seqs:[1],convention_code_seqs:[2],practice_id:'p',effective_reference:{status:'version_evidence_unverifiable',value_version:{id:'v',amount_ars:'14.00'},recorded_amount:'14.00'}};
 const ref={status:'no_exact_hpc_tariff',related_hpc_references:{use_limit:'No aplicada',candidates:[candidate]}};
 let [price,difference]=render(ref);assert.match(price.textContent,/14.00.*no verificable/);assert.doesNotMatch(price.textContent,/15.00/);assert.equal(difference.textContent,'Sin diferencia determinable');
 candidate.effective_reference={status:'version_amount_not_interpretable',value_version:{id:'v',amount_ars:'S\/D'},recorded_amount:null};
 [price,difference]=render(ref);assert.match(price.textContent,/S\/D.*no interpretable/);assert.doesNotMatch(price.textContent,/15.00/);
 candidate.effective_reference={status:'withdrawn_reference',value_version:null};
 [price,difference]=render(ref);assert.match(price.textContent,/BAJA.*original histórico 15.00.*no aplicable/);assert.equal(difference.textContent,'Sin diferencia determinable');
});
function calculatedFixture(extra={}){return {status:'no_exact_hpc_tariff',recorded_amount:null,difference_ars_if_comparable:null,calculated_nomenclature_references:{status:'calculated_reference_candidates',use_limit:'Referencia, no equivalencia ni débito',source_sha256:'abc',candidates:[{code:'340301',description:'Práctica ficticia <script>',recorded_amount:'12934.14',calculated_amount_exact:'12934.1375',calculated_amount_rounded:'12934.14',arithmetic_status:'matches_technical_rounding',formula:'Q GAL × GR + Gto × UR',qGal:'6.75',gto:'25',galenoRadiologico:'477.65',unidadRadiologica:'388.40',valid_from:'2026-06-01',temporal_relation:'inside_declared_dates',source_file:'FICTICIO.xlsx',source_row:42,source_locator:'component row42',norma:'En el caso de facturaci',unidadArancelaria:'D',component_status:'pendiente_equivalencia',rounding_note:'Redondeo técnico, no contractual',...extra}]}};}
test('calculated nomenclature is literal source reference with formula and no debit',()=>{
 const [price,difference]=render(calculatedFixture());assert.match(price.textContent,/12934.14.*nomenclador.*moneda\/unidad pendientes/);assert.match(price.title,/12934.1375/);assert.match(price.title,/Q GAL 6.75 × 477.65/);assert.match(price.title,/En el caso de facturaci/);assert.match(price.title,/pueden estar incompletas/);assert.match(price.title,/<script>/);assert.equal(difference.textContent,'Sin diferencia determinable');assert.equal(difference.classList.values.length,0);
});
test('invalid calculated amount is not zero and multiple references remain ambiguous',()=>{
 const fixture=calculatedFixture({recorded_amount:null,arithmetic_status:'recorded_amount_uninterpretable'});fixture.calculated_nomenclature_references.candidates.push({...fixture.calculated_nomenclature_references.candidates[0],recorded_amount:'12.00'});
 const [price,difference]=render(fixture);assert.match(price.textContent,/Referencias múltiples/);assert.match(price.textContent,/no interpretable/);assert.equal(difference.textContent,'Sin diferencia determinable');
});
test('calculated presentation cannot replace an existing exact reference',()=>{
 const fixture=calculatedFixture();Object.assign(fixture,{recorded_amount:'20.00',declared_currency:'ARS',declared_unit:'por práctica'});const [price]=render(fixture);assert.match(price.textContent,/20.00/);assert.doesNotMatch(price.textContent,/12934/);
});

// Exact pure producer excerpts from HPC Sync 0.5.1. No network or browser initialization.
const HPC_CONTRACT = (() => {
  const version='historico-0.4',qualityVersion='quality-1',maxOrderBytes=80000;
  const typeLabels=Object.freeze({"orden.imagen": "Imágenes", "orden.laboratorio": "Laboratorio", "orden.cardiologia": "Cardiología", "orden.neurologia": "Neurología", "orden.neumonologia": "Neumonología", "orden.hemoterapia": "Hemoterapia", "consulta_medica": "Consultas médicas", "orden.patologia": "Patología", "orden.oftalmologia": "Oftalmología", "orden.audiologia": "Audiología"});
  const supportedTypes=Object.freeze(Object.keys(typeLabels));
  const supportsType=value=>typeof value==='string'&&Object.hasOwn(typeLabels,value);
  const internalTypeVariants=Object.freeze({
    'orden.imagen':Object.freeze(['orden.imagen.digital']),
    'orden.laboratorio':Object.freeze(['orden.laboratorio.digital','orden.laboratorio.preingresada','orden.laboratorio.urgencia'])
  });
  const matchesRequestedType=(requested,internal)=>supportsType(requested)&&
    (internal===requested||(internalTypeVariants[requested]||[]).includes(internal));
  const isDigitalType=internal=>internal==='orden.imagen.digital'||internal==='orden.laboratorio.digital';
  const supportsExtractor=(type,version)=>supportsType(type)&&(version==='historico-0.4'||type==='orden.imagen'&&['imagen-0.1','imagen-0.2','imagen-0.3'].includes(version));
  const text=value=>value.replace(/\s+/g,' ').trim();
  const emptyRule='hpc-imagen-empty-2026-10-08';
  // Literal response supplied by the user; treated as data, never executed.
  const emptyTemplate="<style>\n    .ocultar{\n        display: none;\n    }\n    .ocultar2{\n        display: none;\n    }\n\n\n\n</style>\n\n<script>\n    function VerArchivo(archivo, tipo, id, anio, mes) {\n        if (tipo === \".pdf\") {\n            $(\"#area\").hide();\n            $(\"#imagen_attach\").find('img').attr(\"src\", \"\");\n            $(\"#imagen_attach\").hide();\n            $(\"#frame\").show();\n            $(\".modal-body\").find('iframe').attr(\"src\", \"api_remoto/PdfReader.jsp?anio=\" + anio + \"&mes=\" + mes + \"&orden=\" + id + \"&archivo=\" + archivo);\n            $(\"#myModal\").modal();\n        } else if (tipo === \".jpg\" || tipo === \".png\" || tipo === \"jpeg\") {\n            $(\"#area\").hide();\n            $(\"#frame\").hide();\n            $(\"#imagen_attach\").hide();\n            $(\"#imagen_attach\").load(\"api_remoto/getImagenes.jsp\", {orden: id, anio: anio, mes: mes}, function () {\n                $(\"#imagen_attach\").show();\n                $(\"#myModal\").modal();\n            });\n            /* $(\"#frame\").hide();\n             $.ajax({\n             type: \"Post\",\n             url: \"JPGviewer.jsp\",\n             data: {anio: anio, mes: mes, orden: id, archivo: archivo},\n             cache: false,\n             dataType: \"text\"\n             }).success(function (out) {\n             out = $.trim(out);\n             $(\"#imagen_attach\").html(out);\n             $(\"#imagen_attach\").show();\n             $(\"#myModal\").modal();\n             });*/\n        } else if (tipo === \".txt\") {\n            $(\"#frame\").hide();\n            $(\"#area\").show();\n            $.ajax({\n                type: \"Post\",\n                url: \"TxtReader.jsp\",\n                data: {ruta: ruta},\n                cache: false,\n                dataType: \"text\"\n            }).success(function (out) {\n                out = $.trim(out);\n                $(\"#area\").val(out);\n                $(\"#myModal\").modal();\n            });\n        } else if (tipo === \".xls\" || tipo === \".ods\" | tipo === \".xlsx\") {\n            $(\"#frame\").attr(\"src\", \"api_remoto/ExcelReader.jsp?anio=\" + anio + \"&mes=\" + mes + \"&orden=\" + id + \"&archivo=\" + archivo);\n        } else {\n            $(\"#frame\").attr(\"src\", \"api_remoto/Download.jsp?anio=\" + anio + \"&mes=\" + mes + \"&orden=\" + id + \"&archivo=\" + archivo);\n        }\n    }\n</script>\n\n\n\n<div style=\"max-height: 470px; height: 450px;  overflow: auto; padding-top: 10px; padding-bottom: 10px;\">\n    <table class=\"table table-hover table-striped\"  style=\"width: 100%\">\n        <thead>\n            <tr>\n                <th></th>\n                <th style=\"text-align: center\">Id.</th> \n                <th style=\"text-align: center\">Nro Afiliado</th>\n                <th style=\"text-align: center\">Apellido y Nombre</th>       \n                <th style=\"text-align: center\">Medico</th>       \n                <th style=\"text-align: center\">Mail</th>  \n                <th style=\"text-align: center\">Fecha</th> \n                <th style=\"text-align: center\">Archivos</th> \n            </tr> \n        </thead>\n        <tbody>\n            \n\n        </tbody>\n    </table>\n\n\n    <div id=\"myModal\" class=\"modal fade\" role=\"dialog\">\n        <div class=\"modal-dialog\" style=\"width: 800px\">\n            <div class=\"modal-content\">\n                <div class=\"modal-header\">\n                    <button type=\"button\" class=\"close\" data-dismiss=\"modal\">&times;</button>\n                    <div style='background-size: cover; width:100px; height:100px; position:absolute;'></div>\n                </div>\n                <div class=\"modal-body\">\n                    <iframe id=\"frame\" src=\"\" style=\"width: 770px; height: 600px;\" frameborder=\"0\"></iframe>\n                    <textarea id=\"area\" rows=\"35\" cols=\"100\" readonly=\"true\"></textarea>\n                    <iframe id=\"imagen_attach\" src=\"\" style=\"width: 770px; height: 600px;\" frameborder=\"0\"></iframe>\n                </div>\n            </div>\n        </div>\n    </div>\n\n</div>\n";
  const knownEmpty=html=>typeof html==='string'&&html.length<=16000&&text(html)===text(emptyTemplate);
  const validEmpty=e=>e!==null&&typeof e==='object'&&e.rule===emptyRule&&knownEmpty(e.html);

  function dateValid(value,withTime=true) {
    const m=(withTime?/^(\d{2})\/(\d{2})\/(\d{4}) (\d{2}):(\d{2})$/:
      /^(\d{2})\/(\d{2})\/(\d{4})(?: (\d{2}):(\d{2})(?::(\d{2}))?)?$/).exec(value);
    if(!m)return false;
    const [,day,month,year,hour='0',minute='0',second='0']=m.map(v=>v===undefined?undefined:Number(v));
    if(month<1||month>12||hour>23||minute>59||second>59)return false;
    const d=new Date(Date.UTC(year,month-1,day));
    return d.getUTCFullYear()===year&&d.getUTCMonth()===month-1&&d.getUTCDate()===day;
  }
  function practices(original,digital) {
    const hits=[...original.matchAll(/\b(\d{6,12})\s*--/g)];
    const prefix=hits.length?original.slice(0,hits[0].index):original;
    const items=hits.map((hit,index)=>{
      const raw=original.slice(hit.index,hits[index+1]?.index??original.length);
      return {position:index,codeText:hit[1],sourceText:raw,descriptionAndAmountText:raw.slice(hit[0].length).trim()};
    });
    return {sourceText:original,status:digital&&!original.trim()?'external_content_not_migrated':
      !original.trim()?'empty_in_source':!hits.length?'unparsed':prefix.trim()?'partially_parsed':'pattern_parsed',
      unparsedPrefix:prefix.trim(),items};
  }
  function derivations(log,movements) {
    const hits=[...log.matchAll(/\[DER:([A-Z0-9_]+)\]\[(COMPLETA|PARCIAL)\]/gi)];
    return {markerPresent:/\[DER:/i.test(log),items:hits.map(hit=>{
      const reason=movements.length===1?movements[0].reasonText:'';
      const marker=`[DER:${hit[1]}][${hit[2]}]`.toUpperCase();
      const linked=hits.length===1&&movements.length===1&&reason.length>0&&reason.toUpperCase().includes(marker)&&
        log.includes(reason)&&log.indexOf(reason)===log.lastIndexOf(reason);
      return {destinationCode:hit[1].toUpperCase(),scope:hit[2].toUpperCase(),
        association:linked?'one_matching_movement':'order_only',movementPosition:linked?movements[0].position:null,affectedPractices:null};
    })};
  }
  function quality(p) {
    const codes=new Set((p.problems||[]).map(x=>x.code));
    if(['id','affiliate','name'].some(k=>!p.source[k].trim()))codes.add('identity_fields_incomplete');
    if(['unparsed','partially_parsed'].includes(p.practices.status))codes.add('practice_text_not_fully_segmented');
    if(p.movements.some(m=>!dateValid(m.dateText)))codes.add('invalid_movement_date');
    if(!dateValid(text(p.displayed_raw?.orderDate??p.displayedRaw?.orderDate??''),false))codes.add('invalid_order_date');
    if(!p.movements.length&&p.source.log.trim())codes.add('history_missing');
    const starts=[...p.source.log.matchAll(/\[DER:/gi)].length;
    if(starts>p.derivations.items.length)codes.add('derivation_marker_unparsed');
    return [...codes].sort();
  }
  function summary(rows,sourceProblems=[]) {
    const result={rows:rows.length,confirmed:0,rejected:0,extraction:0,review:0,reasons:{}};
    for(const row of rows) {
      const codes=new Set();
      if(row.extraction_issue){result.extraction++;codes.add(row.extraction_issue);}
      if(row.operation_status==='confirmed') {
        result.confirmed++;
        if(row.quality_status!=='usable'||row.projection_status==='needs_review') {
          result.review++;
          const issues=row.issues_json?JSON.parse(row.issues_json):['legacy_quality_unassessed'];
          issues.forEach(code=>codes.add(code));
        }
      }
      if(row.operation_status==='rejected'){result.rejected++;codes.add(row.error_reason||'rejected');}
      for(const code of codes)result.reasons[code]=(result.reasons[code]||0)+1;
    }
    for(const code of new Set(sourceProblems))result.reasons[code]=(result.reasons[code]||0)+1;
    return result;
  }
  return Object.freeze({version,qualityVersion,maxOrderBytes,typeLabels,supportedTypes,supportsType,internalTypeVariants,matchesRequestedType,isDigitalType,supportsExtractor,emptyRule,knownEmpty,validEmpty,text,dateValid,practices,derivations,quality,summary});
})();


const encoder=new TextEncoder();
function canonical(value) {
  if(Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if(value!==null && typeof value==='object')
    return `{${Object.keys(value).sort().map(k=>`${JSON.stringify(k)}:${canonical(value[k])}`).join(',')}}`;
  return JSON.stringify(value);
}
async function sha256(value) {
  const hash=await crypto.subtle.digest('SHA-256',encoder.encode(canonical(value)));
  return [...new Uint8Array(hash)].map(n=>n.toString(16).padStart(2,'0')).join('');
}
function payloadFor(order) {
  return {hpc_id:order.id,internal_type:order.type,source:order.source,
    displayed:order.displayed,displayed_raw:order.displayedRaw,practices:order.practices,
    movements:order.movements,derivations:order.derivations,
    attachment_references:order.attachmentReferences,external_content:order.externalContent,
    problems:order.problems,ready_for_ingest:order.readyForIngest};
}
async function prepareImageDay(extracted,{attemptId=crypto.randomUUID(),
  extractorVersion=HPC_CONTRACT.version,capturedAt,retryOfAttemptId=null}={}) {
  if(!Number.isSafeInteger(capturedAt)||capturedAt<=0)
    throw new Error('capture_time_required');
  if(!extracted || !['recognized','partial'].includes(extracted.outcome))
    throw new Error('unverifiable_day');
  if(!HPC_CONTRACT.supportsType(extracted.request?.requestedType) ||
      typeof extracted.request.requestedDate!=='string' ||
      !/^\d{4}-\d{2}-\d{2}$/.test(extracted.request.requestedDate))
    throw new Error('unexpected_request');
  if(Array.isArray(extracted.orders) && extracted.orders.length===0 &&
      extracted.structure?.markers===0 && extracted.outcome==='recognized' &&
      extracted.problems?.length===0 && HPC_CONTRACT.validEmpty(extracted.emptyEvidence)) {
    return {attempt_id:attemptId,queried_date:extracted.request.requestedDate,
      extractor_version:extractorVersion,captured_at:capturedAt,retry_of_attempt_id:retryOfAttemptId,
      source_outcome:'recognized',source_problems:[],rows:[],items:[],empty_evidence:extracted.emptyEvidence};
  }
  if(!Array.isArray(extracted.orders) || !extracted.orders.length ||
      extracted.orders.length!==extracted.structure?.markers)
    throw new Error('unaccounted_marker_review_required');
  const counts=new Map();
  for(const order of extracted.orders) counts.set(order.id,(counts.get(order.id)||0)+1);
  const rows=[],items=[];
  for(const order of extracted.orders) {
    // ALL occurrences of a repeated source ID must be reviewed.
    let issue=counts.get(order.id)>1?'duplicate_order_id':order.readyForIngest?null:
      (order.problems?.[0]?.code||'extraction_issue');
    const payload=payloadFor(order);
    if(!issue && encoder.encode(canonical(payload)).length>HPC_CONTRACT.maxOrderBytes) issue='order_too_large';
    if(issue) {
      rows.push({position:order.position,hpc_id:order.id||null,
        operation_id:null,payload_digest:null,extraction_issue:issue});
      continue;
    }
    const operationId=crypto.randomUUID();
    rows.push({position:order.position,hpc_id:order.id,operation_id:operationId,
      payload_digest:await sha256(payload),extraction_issue:null});
    items.push({operation_id:operationId,payload});
  }
  const sourceProblems=[...new Set((extracted.problems||[]).map(p=>p.code))];
  return {attempt_id:attemptId,queried_date:extracted.request.requestedDate,
    extractor_version:extractorVersion,captured_at:capturedAt,retry_of_attempt_id:retryOfAttemptId,
    source_outcome:sourceProblems.length || rows.some(r=>r.extraction_issue) ||
      extracted.outcome==='partial'?'partial':'recognized',
    source_problems:sourceProblems,rows,items};
}


module.exports = {prepareImageDay};

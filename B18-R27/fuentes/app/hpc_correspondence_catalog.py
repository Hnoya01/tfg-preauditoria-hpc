"""Source-backed candidates for administrative matching, units and components."""
import json
import re
import unicodedata
from collections import defaultdict
from .authorization_catalog_candidates import CodeRelations
from .storage import read_verified
from .values_v1 import source_db
from .service import Problem

COMPONENTS = {'340202':'340201','340210':'340209','340212':'340211',
              '340302':'340301','260509':'260508','340602':'340601','340103':'340402'}
# These source relationships require documentary clarification, not a code union.
REVIEW_PAIRS = {('340402','3404020100'),('340301','3403010200')}
PROJECTIONS = {'FRENTE':1,'PERFIL':1,'FRENTE Y PERFIL':2}


def text_key(value):
    text=unicodedata.normalize('NFKD',str(value or '')).upper()
    return re.sub(r'\s+',' ',''.join(c for c in text if not unicodedata.combining(c))).strip(' .')


def catalogue_candidates(conn,root,dataset_id,source_id):
    source=conn.execute("SELECT source_sha256 FROM source_registry WHERE id=? AND dataset_id=? AND kind='values' AND status='registered'",
                        (source_id,dataset_id)).fetchone()
    if not source:
        raise Problem(404,'Fuente HPC inexistente.')
    cat=source_db(read_verified(root,source['source_sha256']))
    try:
        relations=CodeRelations(cat,source_id,source['source_sha256'])
        names=defaultdict(set);seqs=defaultdict(list);hpc=set()
        for row in cat.execute("SELECT seq,code,provider,description FROM hpc_catalog_codes WHERE provider IN ('HPC','NOMENCLADOR')"):
            names[row['code']].add(row['description'] or '')
            seqs[row['code']].append(row['seq'])
            if row['provider']=='HPC' and len(row['code'])==10:hpc.add(row['code'])
        nomen={}
        if cat.execute("SELECT 1 FROM sqlite_master WHERE name='hpc_catalog_components'").fetchone():
            parts=cat.execute("SELECT text_data FROM hpc_catalog_components WHERE component='seed.nomencladorImagenes' ORDER BY part").fetchall()
            if parts:
                for r in json.loads(''.join(p[0] for p in parts)).get('rows',[]):
                    nomen[r['nomencladorCode']]=r
                    names[r['nomencladorCode']].add(r['description'])
        codes={r[0] for r in conn.execute("SELECT DISTINCT json_extract(r.permitted_json,'$.E') FROM invoice_rows r JOIN current_invoice_imports i ON i.id=r.import_id JOIN batches b ON b.id=i.batch_id WHERE b.dataset_id=?",(dataset_id,))}
        # Missing normalized catalogue codes may still be documented by the invoice.
        invoice_names=defaultdict(set)
        for r in conn.execute("SELECT DISTINCT json_extract(r.permitted_json,'$.E'),json_extract(r.permitted_json,'$.K') FROM invoice_rows r JOIN current_invoice_imports i ON i.id=r.import_id JOIN batches b ON b.id=i.batch_id WHERE b.dataset_id=?",(dataset_id,)):
            invoice_names[r[0]].add(r[1] or '')
        result=[]
        for code in sorted(c for c in codes if isinstance(c,str)):
            if code in COMPONENTS:
                parent=COMPONENTS[code]
                if code not in names or parent not in names:continue
                description=' / '.join(sorted(names[code]))
                if not re.search(r'subsiguiente|axia|radioscop',description,re.I):continue
                unit='side' if code=='340602' else 'area' if code=='260509' else 'exposure' if code!='340103' else 'procedure'
                result.append(dict(invoice_code=code,authorization_code=parent,relation_kind='component',
                    billing_unit=unit,factor='1',parent_code=parent,related_code='3406010300' if code=='340602' else None,
                    invoice_description=description,authorization_description=' / '.join(sorted(names[parent])),
                    source_sha256=source['source_sha256'],source_id=source_id,
                    locator='Nomenclador fila '+str(nomen.get(code,{}).get('sourceRow','por verificar')),
                    allowed_kinds=['component']))
                continue
            existing={r['authorization_code']:r for r in relations.aliases(code) if r['authorization_code'] in hpc}
            targets=set(existing)
            # Same base code supplies a proposal. The administrator records the documentary basis.
            targets.update(target for target in hpc if target[:6]==code)
            if code=='345020':
                targets.update(target for target in hpc if any('RESONANCIA' in text_key(n) for n in names[target]))
            description=' / '.join(sorted(names[code] or invoice_names[code]))
            for target in sorted(targets):
                if (code,target) in REVIEW_PAIRS:continue
                link=existing.get(target)
                kind='family' if not link or link.get('category_is_broad') else 'direct'
                target_description=' / '.join(sorted(names[target]))
                if code=='340301' and target=='3403010500':kind='direct'
                if code=='345304' and text_key(description).startswith('COLANGIO') and text_key(target_description).startswith('COLANGIO'):kind='direct'
                unit='side' if code=='340601' else 'practice'
                if code=='340601' and target not in ('3406010100','3406010200'):continue
                factor='2' if unit=='side' and 'BILATERAL' in text_key(target_description) and 'UNILATERAL' not in text_key(target_description) else '1'
                if code=='260508':continue  # one area and unspecified/whole-body scope need a separate statement
                result.append(dict(invoice_code=code,authorization_code=target,relation_kind=kind,
                    billing_unit=unit,factor=factor,parent_code=None,related_code=None,
                    invoice_description=description,authorization_description=target_description,
                    source_sha256=source['source_sha256'],source_id=source_id,
                    locator='Catálogo códigos seq '+','.join(str(v) for v in sorted(set(seqs[code]+seqs[target]))),
                    allowed_kinds=[kind]))
        return result
    finally:cat.close()


def qualifier_candidates(conn,root,dataset_id,source_id):
    from .authorization_matching import _captures
    captures=[r[0] for r in conn.execute(
        "SELECT id FROM authorization_captures c WHERE dataset_id=? AND source_system='HPC-CSV' AND ordinal=(SELECT max(ordinal) FROM authorization_captures x WHERE x.dataset_id=c.dataset_id AND x.source_system=c.source_system AND x.stream_id=c.stream_id)",(dataset_id,))]
    if not captures:return []
    selected,issues=_captures(conn,root,dataset_id,captures[:8],'real_unvalidated')
    if issues:return []
    seen={}
    for capture in selected:
        for oi,order in enumerate(json.loads(capture['canonical_json'])['orders']):
            for ii,item in enumerate(order['items']):
                name=text_key(item['description'])
                # Attribute roles are exact source labels, not prefix equivalence.
                if name in PROJECTIONS:role,value='projections',str(PROJECTIONS[name])
                elif name in ('DERECHO','IZQUIERDO','BILATERAL','CON CARGA','CON APOYO','PARADO','AXIAL','OBLICUA','OBLICUAS','HIPEREXTENSION','HIPERFLEXION','HOMBLADT','LOWEINSTEIN','RODILLAS AL CENIT','ROTULA','PANORAMICA','COMPARATIVA'):
                    role,value='attribute',None
                else:continue
                key=item['full_code']
                entry=dict(invoice_code=key,authorization_code=key,relation_kind='qualifier',billing_unit='attribute',factor='1',
                    parent_code=None,related_code=None,qualifier_kind=role,qualifier_value=value,
                    invoice_description='Atributo del estudio',authorization_description=item['description'],
                    source_sha256=capture['source_sha256'],source_id=source_id,
                    locator=f"CSV {capture['source_sha256']} $.orders[{oi}].items[{ii}]",
                    allowed_kinds=['qualifier'])
                if key in seen and text_key(seen[key]['authorization_description'])!=name:
                    seen[key]['conflict']=True
                else:seen[key]=entry
    return [r for r in seen.values() if not r.get('conflict')]

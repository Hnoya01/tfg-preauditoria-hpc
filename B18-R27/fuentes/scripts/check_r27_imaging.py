"""Verify the August HPC validation in memory. Print aggregates only."""
import argparse
from collections import Counter, defaultdict
from contextlib import closing
from datetime import date
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3

from app import authorization_matching as matching
from app.authorization_source import parse_authorization_source
from app.code_correspondences import candidates, save
from app.csv_coverage import coverage, dated_item
from app.eligibility import classify
from app.practice_families import catalog_families, classify_family
from app.display_categories import add_categories
from app.review import _batch
from app.practice_board import practice_search
from app.proposal_freshness import provider_basis
from app.security import issue_session, token_digest
from app.storage import read_verified
from app.authorization_catalog_candidates import load_relations

FULL = {'units_supported', 'one_unit_supported', 'component_supported'}


def register_verified_link(c, root, token, ds, bid, source):
    pair = ('187013','1870130000')
    relations = load_relations(c, root, ds, bid)
    matches = [p for p in candidates(c,root,ds,source)
               if (p['invoice_code'],p['authorization_code']) == pair and p['relation_kind']=='direct']
    assert len(matches)==1 and Decimal(str(matches[0]['factor']))==1
    assert any(a['authorization_code']==pair[1] and not a.get('category_is_broad') for a in relations.aliases(pair[0]))
    entry = {k:matches[0][k] for k in ('invoice_code','authorization_code','relation_kind','factor','billing_unit','locator')}
    version = c.execute('SELECT version FROM datasets WHERE id=?',(ds,)).fetchone()[0]
    save(c,root,token,ds,source,expected_version=version,changes=[dict(entry,active=True)],
         reason='Validación local R27: correspondencia individual del catálogo HPC para marcación mamaria con clips bajo guía ecográfica. Unidad uno a uno.')


def prepare_private_copy(run, target):
    """Create an independent validation including its verified catalog and source objects."""
    private_root=(Path(os.environ['LOCALAPPDATA'])/'TFG-HPC-Privado').resolve()
    target=target.resolve()
    if target.parent!=private_root or target==run.resolve() or not target.name.startswith('R27-'):
        raise ValueError('Se requiere un directorio privado nuevo R27 en TFG-HPC-Privado.')
    source_root=run.resolve()/'datos'
    file=source_root/'app.sqlite3'
    wal=Path(str(file)+'-wal')
    if not file.is_file() or (wal.exists() and wal.stat().st_size):
        raise ValueError('La base de origen debe estar cerrada.')
    target.mkdir(exist_ok=False)
    root=target/'datos'
    root.mkdir()
    for path in (source_root/'objects').glob('*/*'):
        if not re.fullmatch('[0-9a-f]{64}',path.name) or path.parent.name!=path.name[:2]:
            raise ValueError('El almacén de objetos requiere revisión.')
        dest=root/'objects'/path.name[:2]/path.name
        dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_bytes(read_verified(source_root,path.name))
        read_verified(root,path.name)
    with closing(sqlite3.connect(file.as_uri()+'?mode=ro&immutable=1',uri=True)) as original, closing(sqlite3.connect(root/'app.sqlite3',isolation_level=None)) as conn:
        original.backup(conn)
        conn.row_factory=sqlite3.Row
        batch,=conn.execute('SELECT id,dataset_id FROM batches').fetchall()
        actor=conn.execute("SELECT id FROM users WHERE role='admin' AND active=1 LIMIT 1").fetchone()[0]
        token=token_digest(issue_session(conn,actor)[0])
        try:
            register_verified_link(conn,root,token,batch['dataset_id'],batch['id'],provider_basis(conn,batch['id'])['source_id'])
        finally:
            conn.execute('DELETE FROM sessions WHERE token_hash=?',(token,))
        assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')


def check(run, csv, registered=False):
    root = run.resolve()/'datos'
    db = root/'app.sqlite3'
    wal = Path(str(db)+'-wal')
    if not db.is_file() or (wal.exists() and wal.stat().st_size):
        raise ValueError('Se requiere la validación cerrada con su carpeta de objetos.')
    with closing(sqlite3.connect(db.as_uri()+'?mode=ro&immutable=1',uri=True)) as source, closing(sqlite3.connect(':memory:',isolation_level=None)) as c:
        source.execute('PRAGMA query_only=ON')
        source.backup(c)
        c.row_factory=sqlite3.Row
        c.execute('PRAGMA temp_store=MEMORY')
        batch, = c.execute('SELECT b.id,b.dataset_id,b.source_sha256,i.id AS imp,i.period FROM batches b JOIN current_invoice_imports i ON i.batch_id=b.id').fetchall()
        ds,bid,imp=batch['dataset_id'],batch['id'],batch['imp']
        scope=provider_basis(c,bid)
        assert scope['provider']=='HPC' and batch['period']=='2026-08'
        read_verified(root,batch['source_sha256'])
        selected,caps,issues=matching._context(c,root,ds,bid,budgets=True)
        assert selected and not issues and len(caps)==1 and caps[0]['source_system']=='HPC-CSV'
        cap=caps[0]
        raw=csv.read_bytes()
        assert hashlib.sha256(raw).hexdigest()==cap['source_sha256'] and parse_authorization_source(raw).preview_sha256==cap['preview_sha256']
        actor=c.execute("SELECT id FROM users WHERE role='admin' AND active=1 LIMIT 1").fetchone()[0]
        token=token_digest(issue_session(c,actor)[0])
        families,names,meta=catalog_families(c,root,ds)
        assert meta['available'] and not meta['source_unavailable']
        add_categories(c,root,ds,{**_batch(c,ds,bid),'batch_id':bid},families)
        edits=defaultdict(dict)
        for e in c.execute('SELECT * FROM work_fields WHERE import_id=?',(imp,)):
            edits[e['source_row']][e['field']]=json.loads(e['value_json'])
        fields={}
        images={}
        for r in c.execute('SELECT source_row,permitted_json,practice_date,total_ars FROM invoice_rows WHERE import_id=?',(imp,)):
            n=r['source_row']
            original=json.loads(r['permitted_json'])
            f=fields[n]={**original,**edits[n]}
            scope_row=classify(r['practice_date'],original.get('F'),batch['period'])
            if scope_row['disposition']=='included' and classify_family(f.get('E'),families,f.get('K'),names)[0]=='images':
                images[n]=(scope_row['billing_window']['status'],r['practice_date'])
        assert Counter(t for t,_ in images.values())=={'in_term':463,'late':9}
        idx=matching._index(caps)
        def calculate():
            return coverage(c,ds,bid,set(images),idx,captures=caps,root=root,image_numbers=set(images))
        if not registered:
            before=calculate()
            register_verified_link(c,root,token,ds,bid,scope['source_id'])
        else:
            receipt,=c.execute("SELECT active,factor,locator FROM hpc_code_correspondences WHERE source_id=? AND invoice_code='187013' AND authorization_code='1870130000'",(scope['source_id'],)).fetchall()
            assert receipt['active'] and Decimal(receipt['factor'])==1 and receipt['locator']
        c.execute('PRAGMA query_only=ON')
        after=calculate()
        if not registered:
            changed=[n for n in images if before[imp,n]['status']!=after[imp,n]['status']]
            assert len(changed)==1 and before[imp,changed[0]]['status'] not in FULL and after[imp,changed[0]]['status'] in FULL
            assert len(after[imp,changed[0]]['allocations'])==2
        items={}
        for records in idx.values():
            for record in records:
                item=dated_item(*record)
                items[item['sha256'],item['locator']]=item
        spent=Counter()
        used_days=defaultdict(set)
        extra=Counter()
        limits={}
        for (lot,n),s in after.items():
            assert lot==imp
            receipts=set()
            for a in s.get('allocations',[]):
                k=(a['source_sha256'],a['locator'])
                item=items[k]
                assert k not in receipts and item['authorized'] and item['unique'] and item['provider']=='HPC'
                assert item['order_id']==a['order_id'] and matching.dni(fields[n]['C'])==matching.dni(item['affiliate'])
                assert 0 <= (date.fromisoformat(a['performed_on'])-item['day']).days == a['elapsed_days'] <= 60
                q=Decimal(a['assigned_studies'])
                assert q>0 and a['capacity']==item['authorized_units']
                receipts.add(k)
                spent[k]+=q
                used_days[k].add(a['performed_on'])
            if s['status']=='component_supported':
                parent=after[lot,s['parent_row']]
                assert parent['status'] in FULL and parent['locator']==s['locator'] and parent['source_sha256']==s['source_sha256']
                assert fields[n]['B']==fields[s['parent_row']]['B'] and matching.dni(fields[n]['C'])==matching.dni(fields[s['parent_row']]['C'])
                if n in images and s['parent_row'] in images:
                    assert images[n][1]==images[s['parent_row']][1]
                k=(s['source_sha256'],s['locator'],s['component_rule_id'])
                extra[k]+=s['covered_units']
                limits[k]=s['component_capacity']
        assert all(q<=items[k]['authorized_units'] and len(used_days[k])==1 for k,q in spent.items())
        assert all(q<=limits[k] for k,q in extra.items())
        states=Counter()
        pending=Counter()
        amounts=Counter()
        seen=set()
        for off in range(0,len(images),100):
            page=practice_search(c,token,ds,bid,dict(family='images',scope='included',view='all',limit=100,offset=off,sort='source_row'),root=root)
            assert page['filtered_total']==len(images)
            for row in page['items']:
                n=row['source_row']
                assert n in images and n not in seen
                seen.add(n)
                tier=images[n][0]
                sig=after[imp,n]
                ui=row['authorization']['panel_signal']['csv_coverage']
                assert tier==row['billing_window']['status'] and all(ui.get(k)==sig.get(k) for k in ('status','allocations','parent_row'))
                dec=row.get('administrative_decision') or {}
                if tier=='late':
                    assert dec['proposal']['amount_ars']==row['total_ars']
                    amounts['fuera_plazo']+=Decimal(row['total_ars'])
                    continue
                states[sig['status']]+=1
                if sig['status'] in FULL:
                    assert sig['covered_units']==sig['billed_units']
                elif dec.get('proposal'):
                    assert sig['status']=='unidentified'
                    pending['afiliado_sin_identificar']+=1
                    amounts['identidad']+=Decimal(dec['proposal']['amount_ars'])
                elif dec.get('quantity_advisory'):
                    assert not dec['proposal']
                    pending['cantidad_por_verificar']+=1
                    amounts['cantidad_por_verificar']+=Decimal(dec['quantity_advisory']['amount_ars'])
                else:
                    pending['otro_cotejo']+=1
        assert seen==set(images)
        assert not c.execute('SELECT 1 FROM invoice_row_decisions LIMIT 1').fetchone()
        return dict(imagenes=len(seen),en_termino=sum(states.values()),fuera_plazo=len(seen)-sum(states.values()),
                    cobertura_completa=sum(states[k] for k in FULL),estados=states,pendientes=pending,
                    importes_ARS={k:format(v,'.2f') for k,v in amounts.items()},correspondencias_agregadas=1,
                    items_usados=len(spent),items_sobreasignados=0,adicionales_verificados=sum(extra.values()))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--validacion',type=Path,required=True)
    parser.add_argument('--csv',type=Path,required=True)
    parser.add_argument('--guardar-copia-privada',type=Path)
    args=parser.parse_args()
    result=check(args.validacion,args.csv)
    if args.guardar_copia_privada:
        prepare_private_copy(args.validacion,args.guardar_copia_privada)
        assert check(args.guardar_copia_privada,args.csv,registered=True)==result
        (args.guardar_copia_privada/'resultado-agregado.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True))

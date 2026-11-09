"""Validate a local HPC invoice in an exclusively new private directory. Aggregate output only."""
import argparse
from collections import Counter,defaultdict
from datetime import date,timedelta
import csv,hashlib,io,json,os,secrets,sys,tempfile
from pathlib import Path
from app import authorization_matching as match
from app.authorization_imports import stage_authorization,preview_authorization,confirm_authorization
from app.db import connect,migrate
from app.economic_evidence import confirm_provider_scope
from app.practice_board import practice_search
from app.review import _batch
from app.security import create_user,issue_session,token_digest
from app.service import create_dataset,create_batch,confirm_invoice
from app.values_v1 import register_values,SOURCE_NAME


def unique(files):
    seq=list(files)
    if len(seq)!=1:raise ValueError('No se identificó una única fuente del tipo requerido.')
    return seq[0]


def check_destination(conn,db):
    target=Path(conn.execute('PRAGMA database_list').fetchone()['file']).resolve()
    if target!=db.resolve():raise RuntimeError('Destino incorrecto')



def prefix_order_dates(orders):
    dates=defaultdict(set)
    for order in orders:
        affiliate=match.dni(order['affiliate_id'])
        if not affiliate:
            continue
        for item in order['items']:
            code=item.get('full_code')
            if not isinstance(code,str) or len(code)<6:
                continue
            days=dates[affiliate,code[:6]]
            if order['ordered_at']:
                days.add(date.fromisoformat(order['ordered_at'][:10]))
    return dates


def verify_private(root,inputs,csv_file):
    """Read the frozen local import back through the selected CSV and current rules."""
    from app.authorization_source import parse_authorization_source
    from app.csv_coverage import coverage
    from app.practice_families import catalog_families,classify_family
    import sqlite3
    target=root/'datos'
    c=sqlite3.connect((target/'app.sqlite3').as_uri()+'?mode=ro',uri=True)
    c.row_factory=sqlite3.Row;c.execute('PRAGMA query_only=ON')
    try:
        prior=json.loads((root/'resultado-agregado.json').read_text(encoding='utf-8'))
        b=c.execute('SELECT b.id,b.dataset_id,i.id AS imp FROM batches b JOIN current_invoice_imports i ON i.batch_id=b.id').fetchone()
        ds,bid=b['dataset_id'],b['id']
        scope,captures,issues=match._context(c,target,ds,bid,budgets=True)
        assert scope and not issues and len(captures)==1
        raw=csv_file.read_bytes()
        assert hashlib.sha256(raw).hexdigest()==captures[0]['source_sha256']
        assert parse_authorization_source(raw).preview_sha256==captures[0]['preview_sha256']
        areas,names,_=catalog_families(c,target,ds)
        rows=[]
        for r in c.execute("SELECT source_row,practice_date,permitted_json FROM invoice_rows WHERE import_id=? AND disposition='included'",(b['imp'],)):
            f=json.loads(r['permitted_json'])
            if classify_family(f['E'],areas,f['K'],names)[0]=='images':
                rows.append((r['source_row'],date.fromisoformat(r['practice_date']),match.dni(f['C']),f['E']))
        index=match._index(captures)
        numbers={r[0] for r in rows}
        signals=coverage(c,ds,bid,numbers,index,captures=captures,root=target,image_numbers=numbers)
        stages=Counter(signals.get((b['imp'],r[0]),{}).get('status','unresolved') for r in rows)
        assert stages==prior['estados_motor'] and len(rows)==prior['imagenes']
        prefix_days=prefix_order_dates(json.loads(captures[0]['canonical_json'])['orders'])
        with_prefix=sum((aff,code[:6]) in prefix_days for _,_,aff,code in rows)
        candidates=sum(any(0<=(d-when).days<=60 for when in prefix_days.get((aff,code[:6]),())) for _,d,aff,code in rows)
        print(json.dumps({'imagenes_verificadas':len(rows),'recuento_conservado':True,'prefijo_afiliado_fecha_solicitud_en_ventana':candidates,
                          'con_afiliado_y_prefijo':with_prefix,'sin_afiliado_y_prefijo':len(rows)-with_prefix,
                          'lineas_fisicas_csv_incluida_cabecera':len(raw.splitlines()),'origen_csv_verificado':True}))
    finally:c.close()


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--inputs',type=Path,required=True);p.add_argument('--csv',type=Path,required=True)
    p.add_argument('--private',type=Path,required=True);p.add_argument('--period',required=True)
    p.add_argument('--verify-only',action='store_true');args=p.parse_args()
    root=args.private.resolve()
    if args.verify_only:
        return verify_private(root,args.inputs,args.csv)
    if not root.is_dir() or any(root.iterdir()):raise SystemExit('Se requiere una carpeta privada vacía.')
    inputs=args.inputs.resolve()
    if any(root.is_relative_to(x) for x in (Path(__file__).resolve().parents[1],inputs)):
        raise SystemExit('El destino debe estar fuera del proyecto y de las fuentes.')
    tmp=root/'temporales';tmp.mkdir();tempfile.tempdir=str(tmp)
    for k in ('TEMP','TMP','TMPDIR'):os.environ[k]=str(tmp)
    os.environ['TFG_DATA_DIR']=str(root/'datos')
    def guard(event,args):
        if event.startswith(('socket.','subprocess.')):raise PermissionError('Operación externa excluida.')
        if event=='open' and isinstance(args[0],(str,bytes)) and (args[2] or 0)&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC):
            if not Path(os.fsdecode(args[0])).resolve().is_relative_to(root):raise PermissionError('Escritura fuera de la base privada.')
    sys.addaudithook(guard)
    book=unique(x for x in inputs.rglob('*.xlsx') if not x.name.startswith('~$'))
    cat=unique(inputs.rglob('*.sqlite'))
    manifest=unique(x for x in inputs.rglob('*.json') if 'manif' in x.name.lower())
    originals=[book,cat,manifest,args.csv]
    def hashes():return [hashlib.sha256(p.read_bytes()).hexdigest() for p in originals]
    before=hashes()
    catalog_manifest=manifest.read_bytes();expected=json.loads(catalog_manifest)['files'][SOURCE_NAME]['sha256']
    assert before[1]==expected
    src=args.csv.read_bytes();raw=list(csv.DictReader(io.StringIO(src.decode('utf-8-sig'),newline='')))
    dbroot=root/'datos';conn=connect(dbroot)
    def guard_db():check_destination(conn,dbroot/'app.sqlite3')
    try:
        guard_db();migrate(conn)
        actor=create_user(conn,'validacion-local',secrets.token_urlsafe(40),'admin')
        token=token_digest(issue_session(conn,actor)[0])
        ds=create_dataset(conn,token,'Validación local privada HPC')['id']
        def version():return conn.execute('SELECT version FROM datasets WHERE id=?',(ds,)).fetchone()[0]
        guard_db();v,_=register_values(conn,dbroot,token,ds,version(),cat.read_bytes(),catalog_manifest,expected)
        guard_db();lot,_=create_batch(conn,dbroot,token,ds,version(),'Facturacion-HPC.xlsx',book.read_bytes())
        bid=lot['id']
        guard_db();invoice,_=confirm_invoice(conn,dbroot,token,ds,bid,args.period,version())
        guard_db();up,_=stage_authorization(conn,dbroot,token,ds,version(),'Autorizaciones-HPC.csv',src)
        pre=preview_authorization(conn,dbroot,token,ds,up['id'])
        if not pre['can_import']:raise ValueError('El CSV no pudo interpretarse.')
        cap,_=confirm_authorization(conn,dbroot,token,ds,up['id'],version(),pre['preview_sha256'],'Exportación local suministrada de julio y agosto. Exhaustividad no acreditada.')
        guard_db();match.save_scope(conn,dbroot,token,ds,bid,version(),[cap['id']],'real_unvalidated','Cotejo de la exportación recibida; no se declara cobertura completa.')
        guard_db();confirm_provider_scope(conn,dbroot,token,ds,bid,v['id'],'HPC','unverified','Factura HPC y catálogo identificados por el operador para esta validación local.',version(),_batch(conn,ds,bid)['revision_version'])
        def page(offset):
            return practice_search(conn,token,ds,bid,{'scope':'included','family':'images','view':'all','sort':'source_row','limit':100,'offset':offset},root=dbroot)
        first=page(0);rows=first['items'][:]
        for off in range(100,first['filtered_total'],100):rows.extend(page(off)['items'])
        assert len(rows)==len({r['source_row'] for r in rows})==first['filtered_total']
        counts=Counter();reasons=Counter();details=Counter();candidate_counts=Counter()
        orders=pre['canonical']['orders']
        prefixes=prefix_order_dates(orders)
        usage=Counter()
        for r in rows:
            a=r['authorization'];panel=a['panel_signal'];signal=panel.get('csv_coverage') or {}
            state=signal.get('status','unresolved');details[state]+=1
            possible=(match.dni(r['affiliate_id']),str(r['code'])[:6]) in prefixes
            exact=bool(a.get('candidate_count'))
            if exact:candidate_counts['codigo_completo_y_afiliado']+=1
            elif possible:candidate_counts['solo_prefijo_y_afiliado']+=1
            else:candidate_counts['sin_coincidencia_por_afiliado_y_prefijo']+=1
            if state in ('units_supported','one_unit_supported'):
                label='autorizadas';usage[signal['source_sha256'],signal['locator']]+=signal.get('covered_units',1)
            elif state=='declared_rejected':label='rechazadas'
            elif signal.get('export_scope') and not signal.get('coverage_note') and state in ('no_aval','already_used','outside_window'):label='sin_aval'
            else:
                label='pendientes'
                reason=('resolución individual o correspondencia no concluyente' if exact else
                        'candidato por prefijo y afiliado, sin equivalencia acreditada' if possible else
                        'sin coincidencia exacta y cobertura de la exportación no acreditada')
                if state in ('one_unit_only','units_partial'):reason='cobertura parcial de unidades'
                if state.startswith('temporal_'):reason='evidencia de incorporación insuficiente o posterior'
                reasons[reason]+=1
            counts[label]+=1
        days=[date.fromisoformat(r['practice_date']) for r in rows]
        result={'periodo':args.period,'filas_factura':invoice.get('row_count',invoice.get('physical_rows')),
                'filas_incluidas':first['scope_counts']['included'],'imagenes':len(rows),
                'facturado_imagenes_ARS':format(sum(__import__('decimal').Decimal(r['total_ars']) for r in rows),'.2f'),
                'csv_registros':len(raw),'ordenes_utilizables':len(orders),
                'fechas_orden_csv':[min(o['ordered_at'] for o in orders),max(o['ordered_at'] for o in orders)],
                'primer_y_ultimo_dia_de_prestacion':[min(days).isoformat(),max(days).isoformat()],
                'requerido_desde_60_dias':(min(days)-timedelta(days=60)).isoformat(),
                'resultado':{k:counts[k] for k in ('autorizadas','rechazadas','sin_aval','pendientes')},
                'motivos_pendientes':dict(reasons),'presencia':dict(candidate_counts),'estados_motor':dict(details),
                'completitud_declarada':False,'originales_verificados':hashes()==before,
                'decisiones_humanas_registradas':conn.execute('SELECT count(*) FROM invoice_row_decisions').fetchone()[0]}
        assert sum(counts.values())==len(rows) and result['originales_verificados']
        conn.execute('DELETE FROM sessions')
        (root/'resultado-agregado.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(result,ensure_ascii=True),flush=True)
    finally:conn.close()


if __name__=='__main__':
    try:main()
    except Exception as e:
        import traceback
        safe=traceback.extract_tb(e.__traceback__)[-1]
        print('Validación interrumpida:',type(e).__name__,Path(safe.filename).name,safe.lineno,flush=True)
        raise SystemExit(1)

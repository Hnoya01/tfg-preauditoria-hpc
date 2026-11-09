"""Create a new, isolated fictional journey; never open an existing data directory."""
import argparse
from io import BytesIO
import os
from pathlib import Path
import secrets
from openpyxl import load_workbook
from app.db import connect,migrate
from app.security import create_user,issue_session,token_digest
from app.service import create_dataset,create_batch,confirm_invoice
from app.controls import run_controls
from tests.test_p02 import book


def fictional_tac_capture(conn,root,token,dataset_id,version):
    from app.authorization_imports import stage_authorization,preview_authorization,confirm_authorization
    from tests.test_hpc_csv_intake import row,encode
    records=[]
    for num,affiliate,practice,movement in [
        (1,'000111/1','1234567890 -- TAC de abdomen,','AUTORIZADO | Resolución por ítems - AUTORIZAR: 1234567890'),
        (2,'000222/1','1234567891 -- Estudio ficticio,','Derivado | Consulta')
    ]:
        records.append(row(orden_hpc=f'TEST-{num}',afiliado=affiliate,practicas=practice,
                           movimientos='02/07/2026 12:00 | Ficticio | '+movement,
                           fecha_orden='2026-07-02',fecha_orden_original='02/07/2026'))
    upload,_=stage_authorization(conn,root,token,dataset_id,version,'ficticio.csv',encode(records))
    preview=preview_authorization(conn,root,token,dataset_id,upload['id'])
    version=conn.execute('SELECT version FROM datasets WHERE id=?',(dataset_id,)).fetchone()[0]
    capture,_=confirm_authorization(conn,root,token,dataset_id,upload['id'],version,preview['preview_sha256'],
                                    'Captura ficticia para cotejar fechas e ítems.')
    return capture['id']


def fictional_budget_capture(conn,root,token,dataset_id,version,*,with_budget=True,units=None):
    from app.authorization_imports import stage_authorization,preview_authorization,confirm_authorization
    from tests.test_hpc_csv_intake import row,encode
    movement = ('02/07/2026 12:00 | Operador ficticio | AUTORIZADO | Resolución por ítems - '
                'AUTORIZAR: 1234567890 - TAC TRIDIMENSIONAL')
    if units is not None:movement+=' x'+str(units)
    if with_budget:movement += ' por un total autorizado de ARS 200.000'
    source=encode([row(orden_hpc='DEMO-PRES-01',afiliado='000111/1',fecha_orden='2026-07-02',
                       fecha_orden_original='02/07/2026',practicas='1234567890 -- TAC TRIDIMENSIONAL,',movimientos=movement)])
    upload,_=stage_authorization(conn,root,token,dataset_id,version,'FICTICIO_presupuesto.csv',source)
    preview=preview_authorization(conn,root,token,dataset_id,upload['id'])
    current=conn.execute('SELECT version FROM datasets WHERE id=?',(dataset_id,)).fetchone()[0]
    capture,_=confirm_authorization(conn,root,token,dataset_id,upload['id'],current,preview['preview_sha256'],
                                    'Resolución individual ficticia HPC para probar el alcance de la orden.')
    return capture['id']


def volume_orders(conn,root,token,ds,version):
    from tests.test_hpc_csv_intake import row,encode
    from app.authorization_imports import stage_authorization,preview_authorization,confirm_authorization
    orders=[row(orden_hpc='FICT-'+str(i),afiliado=f'{100000+i}/1',fecha_orden='2026-07-02',fecha_orden_original='02/07/2026',
                practicas='1234567890 -- TAC TRIDIMENSIONAL,',movimientos='02/07/2026 12:00 | Ficticio | AUTORIZADO | Resolución por ítems - AUTORIZAR: 1234567890')
            for i in range(100)]
    up,_=stage_authorization(conn,root,token,ds,version,'FICTICIO-100.csv',encode(orders))
    pre=preview_authorization(conn,root,token,ds,up['id'])
    cap,_=confirm_authorization(conn,root,token,ds,up['id'],pre['dataset_version'],pre['preview_sha256'],'Prueba ficticia de volumen.')
    return cap['id']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name',default='recorrido-ficticio')
    scenarios=parser.add_mutually_exclusive_group()
    scenarios.add_argument('--categorias',action='store_true',help='Dos facturas HPC para registrar una categoría sin precio')
    scenarios.add_argument('--tac',action='store_true',help='Crear el recorrido ficticio de la TAC repetida')
    scenarios.add_argument('--presupuesto',action='store_true',help='TAC ficticia: factura de 450.000 y presupuesto autorizado por 200.000 ARS')
    scenarios.add_argument('--cierre-auditor',action='store_true',help='Dos TAC ficticias ya recibidas por el auditor, todavía sin cierre')
    scenarios.add_argument('--cobertura-csv',action='store_true',help='Tres TAC para revisar la cobertura completa, parcial y fuera del período exportado')
    scenarios.add_argument('--dos-tac',action='store_true',help='Aval por dos TAC y una tercera realización sin otro aval')
    scenarios.add_argument('--volumen',action='store_true',help='13.000 prestaciones ficticias, catálogo HPC y CSV de 100 órdenes')
    args=parser.parse_args()
    if args.cierre_auditor or args.cobertura_csv or args.dos_tac or args.volumen:args.presupuesto=True
    if not args.name.replace('-','').replace('_','').isalnum():raise SystemExit('Nombre simple requerido')
    root=Path(__file__).resolve().parents[1]/'.tmp'/args.name
    root.mkdir(parents=True,exist_ok=False)
    os.chmod(root,0o700)
    c=connect(root)
    try:
        migrate(c)
        credentials=[];users={}
        for username,role in [('demo-admin','admin'),('demo-administrativo','reviewer'),('demo-auditor','reviewer')]:
            password=secrets.token_urlsafe(24);users[username]=create_user(c,username,password,role);credentials.append(f'{username}: {password}')
        token,_=issue_session(c,users['demo-admin']);token=token_digest(token)
        ds=create_dataset(c,token,'DEMO FICTICIO · recorrido administrativo y auditor')
        for username in ('demo-administrativo','demo-auditor'):c.execute('INSERT INTO dataset_access VALUES(?,?,?)',(ds['id'],users[username],'reviewer'))
        for username,duty in [('demo-administrativo','administrative'),('demo-auditor','auditor')]:
            c.execute('INSERT INTO invoice_review_duties VALUES(?,?,?)',(ds['id'],users[username],duty))
        version=ds['version'];target=None
        capture=None; category_source=None
        if args.presupuesto:
            from tests.test_display_categories import price_free_hpc_catalog
            from app.values_v1 import register_values
            source,_=register_values(c,root,token,ds['id'],version,*price_free_hpc_catalog(root))
            category_source=source['id']
            capture=volume_orders(c,root,token,ds['id'],source['dataset_version']) if args.volumen else fictional_budget_capture(c,root,token,ds['id'],source['dataset_version'],with_budget=not (args.cobertura_csv or args.dos_tac),units=2 if args.dos_tac else None)
            version=c.execute('SELECT version FROM datasets WHERE id=?',(ds['id'],)).fetchone()[0]
            invoices=[('FICTICIO_presupuesto_TAC.xlsx',[('02/08/2026',400000,50000,450000),('04/08/2026',400000,50000,450000)])]
            if args.volumen:
                invoices=[('FICTICIO_13000.xlsx',[('02/08/2026',10,20,39 if i < 357 and i%3==0 else 30) for i in range(13000)])]
            if args.cobertura_csv:
                invoices=[('FICTICIO_cobertura_Imagenes.xlsx',[
                    ('02/08/2026',80000,20000,100000),('02/08/2026',160000,40000,200000),('04/08/2026',80000,20000,100000)])]
            if args.dos_tac:
                invoices=[('FICTICIO_Tres_TAC.xlsx',[('02/08/2026',160000,40000,200000),('04/08/2026',80000,20000,100000)])]
        elif args.tac:
            capture=fictional_tac_capture(c,root,token,ds['id'],version)
            version=c.execute('SELECT version FROM datasets WHERE id=?',(ds['id'],)).fetchone()[0]
            invoices=[('FICTICIO_factura_A.xlsx',[('04/08/2026',10,20,39),('05/08/2026',10,20,39),('06/08/2026',10,20,39)]),
                      ('FICTICIO_factura_B.xlsx',[('02/08/2026',10,20,30)])]
        elif args.categorias:
            from tests.test_display_categories import nomenclature,price_free_hpc_catalog
            from app.values_v1 import register_values
            source,_=register_values(c,root,token,ds['id'],version,*price_free_hpc_catalog(root))
            category_source=source['id'];version=source['dataset_version']
            (root/'Nomenclador-ficticio.xlsx').write_bytes(nomenclature('0098765432'))
            (root/'Nomenclador-corregido.xlsx').write_bytes(nomenclature('0098765432','Otras prácticas'))
            invoices=[('FICTICIO_factura_A.xlsx',[('04/08/2026',10,20,39)]),
                      ('FICTICIO_factura_B.xlsx',[('05/08/2026',10,20,39)])]
        else:
            invoices=[('FICTICIO_factura_A.xlsx',[('15/08/2026' if i==0 else f'{16+i%4:02d}/08/2026',10,20,39 if i==0 else 30) for i in range(12)]),('FICTICIO_factura_B.xlsx',[('15/08/2026',10,20,30)])]
        for name,rows in invoices:
            wb=load_workbook(BytesIO(book(rows)));ws=wb.active
            for row in range(2,ws.max_row+1):
                if args.presupuesto:
                    for col,value in [(3,'000111/1'),(5,'1234567890'),(7,1),(11,'TAC TRIDIMENSIONAL')]:ws.cell(row,col).value=value
                    if args.volumen:
                        i=row-2
                        ws.cell(row,2).value=str(70000+i)
                        ws.cell(row,3).value=f'{100000+i}/1'
                        if i>=357:
                            ws.cell(row,5).value='9900000000';ws.cell(row,11).value='Otra área ficticia'
                    if args.dos_tac:
                        ws.cell(row,7).value=2 if row==2 else 1
                    if args.cobertura_csv:
                        ws.cell(row,3).value={2:'000222/1',3:'000111/1',4:'000333/1'}[row]
                        ws.cell(row,7).value=2 if row==3 else 1
                    continue
                if args.categorias:
                    ws.cell(row,5).value='0098765432'
                    ws.cell(row,11).value='Eco de prueba' if name.endswith('A.xlsx') else 'Descripción distinta'
                    continue
                if args.tac:
                    ws.cell(row,3).value={2:'000111/1',3:'000222/1',4:'000333/1'}[row]
                    ws.cell(row,5).value={2:1234567890,3:1234567891,4:1234567892}[row]
                    ws.cell(row,7).value=1
                    ws.cell(row,11).value={2:'TAC de abdomen',3:'Estudio ficticio',4:'Consulta ficticia'}[row]
                    continue
                group=(row-2)//4
                ws.cell(row,8).value=['Carla Ficticia','Bruno Ficticio','Diana Ficticia'][group]
                ws.cell(row,3).value=['000123/4','000456/7','000789/0'][group]
                ws.cell(row,11).value=['Consulta ficticia','Control ficticio','Estudio ficticio','Seguimiento ficticio'][(row-2)%4]
            buffer=BytesIO();wb.save(buffer);wb.close()
            batch,_=create_batch(c,root,token,ds['id'],version,name,buffer.getvalue())
            imported,_=confirm_invoice(c,root,token,ds['id'],batch['id'],'2026-08',batch['dataset_version']);version=imported['dataset_version']
            if capture:
                from app.authorization_matching import save_scope
                save_scope(c,root,token,ds['id'],batch['id'],version,[capture],'real_unvalidated',
                           'Captura ficticia para el recorrido de prueba.',
                           csv_complete_from='2026-06-03' if args.cobertura_csv or args.dos_tac or args.volumen else None,
                           csv_complete_until='2026-08-04' if args.dos_tac or args.volumen else ('2026-08-02' if args.cobertura_csv else None))
                version=c.execute('SELECT version FROM datasets WHERE id=?',(ds['id'],)).fetchone()[0]
            if category_source:
                from app.economic_evidence import confirm_provider_scope
                from app.review import _batch
                scope=confirm_provider_scope(c,root,token,ds['id'],batch['id'],category_source,'HPC','unverified',
                    'Confirmación ficticia del prestador, sin arancel asociado.',version,_batch(c,ds['id'],batch['id'])['revision_version'])
                version=scope['dataset_version']
                if args.presupuesto:
                    from app.display_categories import save_category
                    from openpyxl import Workbook
                    evidence=Workbook(); ws=evidence.active; ws.title='Prácticas'
                    ws.append(['Código','Descripción','Categoría']);ws.append(['1234567890','TAC TRIDIMENSIONAL','Imágenes'])
                    payload=BytesIO();evidence.save(payload);evidence.close()
                    result=save_category(c,root,token,ds['id'],batch['id'],2,version=version,
                        revision=_batch(c,ds['id'],batch['id'])['revision_version'],code='1234567890',family='images',
                        sheet='Prácticas',evidence_row=2,evidence_column=1,filename='Nomenclador-TAC-ficticio.xlsx',content=payload.getvalue())
                    version=result['dataset_version']
            if target is None:target=batch['id']
        run_controls(c,token,ds['id'],target,version)
        if args.cierre_auditor:
            from uuid import uuid4
            from app.row_decisions import detail,save
            from app.invoice_handoff import send,status
            op=token_digest(issue_session(c,users['demo-administrativo'])[0])
            for n,action,reason in [(2,'accept',''),(3,'none','Sin débito tras cotejo ficticio')]:
                info=detail(c,root,op,ds['id'],target,n)
                save(c,root,op,ds['id'],target,n,{'revision_id':info['revision_id'],'expected_dataset_version':info['dataset_version'],
                     'expected_revision_version':info['revision_version'],'evidence_hash':info['evidence_hash'],
                     'request_id':str(uuid4()),'action':action,'reason':reason})
            s=status(c,root,op,ds['id'],target)
            send(c,root,op,ds['id'],target,{'revision_id':s['revision_id'],'expected_dataset_version':s['dataset_version'],
                 'expected_revision_version':s['revision_version'],'request_id':str(uuid4())})
        c.execute('DELETE FROM sessions')
        output=root/'credenciales-demo.txt';fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w',encoding='utf-8') as f:f.write('\n'.join(credentials)+'\n')
        print(f'Datos ficticios creados en {root}. Credenciales locales: {output}. No se imprimen contraseñas.')
        if args.cierre_auditor:print('Factura ficticia lista para demo-auditor: 2 decisiones recibidas; cierre sin confirmar.')
        elif args.dos_tac:print('Ver factura completa: dos TAC autorizadas el 02/08 y una tercera el 04/08 para revisar.')
        elif args.cobertura_csv:print('Tres prestaciones ficticias en Pendientes de Imágenes; aún sin decisiones.')
        elif args.presupuesto:print('Factura FICTICIO_presupuesto_TAC.xlsx: abrir Revisar en la TAC de Imágenes, fila 2.')
        elif args.tac:print('Factura A: revisar la TAC del 04/08 y su antecedente del 02/08 en la factura B.')
        elif args.categorias:print('Nomenclador-ficticio.xlsx · hoja Prácticas · celda A2. Registrar desde la factura A y comprobar en la B.')
        else:print('Factura A: Carla tiene diferencia de suma y posible repetición con factura B. Resolver una no cierra la otra.')
    finally:c.close()


if __name__=='__main__':main()

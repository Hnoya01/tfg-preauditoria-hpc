"""Fictional R24 presentation of bilateral units and same-order additional views."""
import argparse,sys
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from openpyxl import load_workbook
from scripts import create_r23_demo
from app.db import connect
from app.security import token_digest,issue_session
from app.service import create_dataset,grant_access,create_batch,confirm_invoice
from app.values_v1 import register_values
from app.authorization_imports import stage_authorization,preview_authorization,confirm_authorization
from app.authorization_matching import save_scope
from app.economic_evidence import confirm_provider_scope
from app.code_correspondences import listing,save
from app.review import _batch
from app.controls import run_controls
from tests.test_r24 import catalogue
from tests.test_hpc_csv_intake import row,encode
from tests.test_p02 import book

def prepare(c,root,token):
    ds=create_dataset(c,token,'DEMO FICTICIO · Unidades y adicionales R24')['id']
    def version():return c.execute('SELECT version FROM datasets WHERE id=?',(ds,)).fetchone()[0]
    for name,duty in [('demo-administrativo','administrative'),('demo-auditor','auditor')]:
        grant_access(c,token,ds,version(),name,'reviewer',duty)
    folder=root/'catalogo-unidades-ficticio';folder.mkdir()
    source,_=register_values(c,root,token,ds,version(),*catalogue(folder))
    entries=[('02/08/2026','340601',2,'000222/1','MAMO-1','Mamografía bilateral ficticia',100000),
             ('04/08/2026','340601',2,'000222/1','MAMO-2','Mamografía bilateral ficticia',100000),
             ('02/08/2026','340301',1,'000333/1','RX-1','RX tórax ficticia',100000),
             ('02/08/2026','340302',1,'000333/1','RX-1','Exposición subsiguiente ficticia',20000)]
    wb=load_workbook(BytesIO(book([(d,total/2,total/2,total) for d,co,qty,aff,order,desc,total in entries])))
    for n,(_,co,qty,aff,order,desc,_) in enumerate(entries,2):
        for col,value in [(2,order),(3,aff),(5,co),(7,qty),(11,desc)]:wb.active.cell(n,col).value=value
    out=BytesIO();wb.save(out);wb.close()
    lot,_=create_batch(c,root,token,ds,version(),'FICTICIO_unidades_y_adicionales_R24.xlsx',out.getvalue());bid=lot['id']
    confirm_invoice(c,root,token,ds,bid,'2026-08',version())
    confirm_provider_scope(c,root,token,ds,bid,source['id'],'HPC','unverified','Factura enteramente ficticia de unidades.',version(),_batch(c,ds,bid)['revision_version'])
    raw=encode([row(orden_hpc='FICTICIO-MAMO',afiliado='000222/1',fecha_orden='2026-07-02',fecha_orden_original='02/07/2026',
                    practicas='3406010200 -- Mamografía bilateral ficticia,',movimientos='02/07/2026 12:00 | Operador ficticio | AUTORIZADO | '),
                row(orden_hpc='FICTICIO-RX',afiliado='000333/1',fecha_orden='2026-07-02',fecha_orden_original='02/07/2026',
                    practicas='3402130020 -- FRENTE Y PERFIL,3403010500 -- RX tórax ficticia,',movimientos='02/07/2026 12:00 | Operador ficticio | AUTORIZADO | ')])
    up,_=stage_authorization(c,root,token,ds,version(),'FICTICIO_unidades.csv',raw)
    pre=preview_authorization(c,root,token,ds,up['id'])
    cap,_=confirm_authorization(c,root,token,ds,up['id'],version(),pre['preview_sha256'],'Datos académicos enteramente ficticios.')
    save_scope(c,root,token,ds,bid,version(),[cap['id']],'real_unvalidated','CSV ficticio completo del ejemplo.',csv_complete_from='2026-06-01',csv_complete_until='2026-08-31')
    allowed={('340601','3406010200'),('340301','3403010500'),('340302','340301'),('3402130020','3402130020')}
    page=listing(c,root,token,ds,source['id'])
    selected=[p for p in page['items'] if (p['invoice_code'],p['authorization_code']) in allowed]
    changes=[{k:p[k] for k in ('invoice_code','authorization_code','relation_kind','factor','billing_unit','locator')} for p in selected]
    for entry in changes:entry['active']=True
    save(c,root,token,ds,source['id'],expected_version=version(),changes=changes,
         reason='Cotejo ficticio de mamografía por lado, estudio bilateral, primera exposición y proyección frente/perfil.')
    run_controls(c,token,ds,bid,version())
    return ds,bid

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--name',default='presentacion-R24');args=parser.parse_args()
    with patch.object(sys,'argv',['demo','--name',args.name]):create_r23_demo.main()
    root=Path(__file__).resolve().parents[1]/'.tmp'/args.name
    c=connect(root)
    try:
        user=c.execute("SELECT id FROM users WHERE username='demo-admin'").fetchone()[0]
        token=token_digest(issue_session(c,user)[0])
        prepare(c,root,token);c.execute('DELETE FROM sessions')
        print('R24 ficticia preparada. Cuatro conjuntos, sin decisiones ni cierres.')
    finally:c.close()

if __name__=='__main__':main()

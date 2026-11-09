"""Create the R23 fictional presentation, including reusable code correspondence."""
import argparse
from io import BytesIO
from pathlib import Path
import sys
from unittest.mock import patch
from openpyxl import load_workbook
from scripts import create_r22_demo
from app.db import connect
from app.security import token_digest,issue_session
from app.service import create_dataset,grant_access,create_batch,confirm_invoice
from app.values_v1 import register_values
from app.authorization_imports import stage_authorization,preview_authorization,confirm_authorization
from app.authorization_matching import save_scope
from app.economic_evidence import confirm_provider_scope
from app.review import _batch
from app.code_correspondences import save
from app.controls import run_controls
from tests.test_p02 import book
from tests.test_hpc_csv_intake import row,encode
from tests.test_r23 import catalog,INVOICE,CSV


def prepare_codes(c,root,token):
    ds=create_dataset(c,token,'DEMO FICTICIO · Códigos Excel y CSV')['id']
    def version():
        return c.execute('SELECT version FROM datasets WHERE id=?',(ds,)).fetchone()[0]
    for username,duty in [('demo-administrativo','administrative'),('demo-auditor','auditor')]:
        grant_access(c,token,ds,version(),username,'reviewer',duty)
    folder=root/'catalogo-codigos-ficticio';folder.mkdir()
    source,_=register_values(c,root,token,ds,version(),*catalog(folder))
    wb=load_workbook(BytesIO(book([('02/08/2026',50000,50000,100000),('04/08/2026',50000,50000,100000)])))
    for n in (2,3):
        for col,value in [(2,23000+n),(3,'000111/1'),(5,INVOICE),(7,1),(11,'TAC de abdomen ficticia')]:
            wb.active.cell(n,col).value=value
    buffer=BytesIO();wb.save(buffer);wb.close()
    lot,_=create_batch(c,root,token,ds,version(),'FICTICIO_equivalencias_TAC.xlsx',buffer.getvalue())
    bid=lot['id']
    confirm_invoice(c,root,token,ds,bid,'2026-08',version())
    confirm_provider_scope(c,root,token,ds,bid,source['id'],'HPC','unverified','Factura ficticia de prueba de códigos.',version(),_batch(c,ds,bid)['revision_version'])
    raw=encode([row(orden_hpc='FICTICIO-R23-01',afiliado='000111/1',
                    fecha_orden='2026-07-02',fecha_orden_original='02/07/2026',
                    practicas=f'{CSV} -- TAC ficticia,',
                    movimientos='02/07/2026 12:00 | Operador ficticio | AUTORIZADO | Autorizado por profesional ficticio.')])
    up,_=stage_authorization(c,root,token,ds,version(),'FICTICIO_codigos.csv',raw)
    pre=preview_authorization(c,root,token,ds,up['id'])
    cap,_=confirm_authorization(c,root,token,ds,up['id'],version(),pre['preview_sha256'],'Autorización enteramente ficticia.')
    save_scope(c,root,token,ds,bid,version(),[cap['id']],'real_unvalidated','CSV ficticio exhaustivo del ejemplo.',
               csv_complete_from='2026-06-01',csv_complete_until='2026-08-31')
    save(c,root,token,ds,source['id'],expected_version=version(),pairs=[[INVOICE,CSV]],active=True,
         reason='Los códigos del catálogo ficticio pertenecen a la misma práctica específica.')
    run_controls(c,token,ds,bid,version())
    return ds,bid


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--name',default='presentacion-R23')
    args=p.parse_args()
    with patch.object(sys,'argv',['demo','--name',args.name]):
        create_r22_demo.main()
    root=Path(__file__).resolve().parents[1]/'.tmp'/args.name
    c=connect(root)
    try:
        user=c.execute("SELECT id FROM users WHERE username='demo-admin'").fetchone()[0]
        token=token_digest(issue_session(c,user)[0])
        prepare_codes(c,root,token)
        c.execute('DELETE FROM sessions')
        print('R23 preparada con tres conjuntos ficticios y sin decisiones.')
    finally:
        c.close()

if __name__=='__main__':
    main()


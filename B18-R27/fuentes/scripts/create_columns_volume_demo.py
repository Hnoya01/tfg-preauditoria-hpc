"""A reproducible local sheet with 3,000 fictional orders for visual testing."""
import argparse
from io import BytesIO
import json
from pathlib import Path
import sys
from openpyxl import load_workbook

from . import create_columns_demo
from app.authorization_imports import stage_authorization,preview_authorization,confirm_authorization
from app.authorization_matching import save_scope
from app.controls import run_controls
from app.db import connect
from app.economic_evidence import confirm_provider_scope
from app.review import _batch
from app.security import issue_session,token_digest
from app.service import create_batch,confirm_invoice
from tests.test_p02 import book
from tests.test_hpc_csv_intake import row,encode


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name',default='demo-3000-ordenes')
    args=parser.parse_args()
    previous=sys.argv
    sys.argv=[previous[0],'--name',args.name]
    try:create_columns_demo.main()
    finally:sys.argv=previous
    root=Path(__file__).resolve().parents[1]/'.tmp'/args.name
    conn=connect(root)
    try:
        ds=conn.execute('SELECT id FROM datasets').fetchone()[0]
        actor=conn.execute("SELECT id FROM users WHERE username='demo-admin'").fetchone()[0]
        token=token_digest(issue_session(conn,actor)[0])
        def version():return conn.execute('SELECT version FROM datasets WHERE id=?',(ds,)).fetchone()[0]
        rows=[(f'{2+2*(i%4):02d}/08/2026',10,20,39 if i%20==0 else 30) for i in range(3000)]
        wb=load_workbook(BytesIO(book(rows)))
        descriptions=['TAC de abdomen','TAC de abdomen','Ecografía Doppler de miembros inferiores bilateral','Consulta ambulatoria de prueba']
        for number in range(2,3002):
            index=number-2
            group=index//4
            values={2:100000+index,3:f'{1000000+group}/1',5:['1234567890','1234567890','1234567891','1234567892'][index%4],
                    7:1,8:f'Paciente de prueba {group+1:04d}',11:descriptions[index%4]}
            for column,value in values.items():wb.active.cell(number,column).value=value
        buf=BytesIO();wb.save(buf);wb.close()
        lot,_=create_batch(conn,root,token,ds,version(),'FICTICIO_3000_ordenes.xlsx',buf.getvalue())
        bid=lot['id'];confirm_invoice(conn,root,token,ds,bid,'2026-08',version())
        orders=[row(orden_hpc=f'ORDEN-FICTICIA-{i+1}',afiliado=f'{1000000+i}/1',
                    practicas='1234567890 -- TAC de abdomen,',movimientos='02/07/2026 12:00 | Ficticio | AUTORIZADO | Resolución por ítems - AUTORIZAR: 1234567890',
                    fecha_orden='2026-07-02',fecha_orden_original='02/07/2026') for i in range(750)]
        up,_=stage_authorization(conn,root,token,ds,version(),'Autorizaciones-ficticias-750.csv',encode(orders))
        preview=preview_authorization(conn,root,token,ds,up['id'])
        capture,_=confirm_authorization(conn,root,token,ds,up['id'],version(),preview['preview_sha256'],'Captura ficticia para revisar la visualización de 3000 órdenes.')
        save_scope(conn,root,token,ds,bid,version(),[capture['id']],'real_unvalidated','Captura ficticia seleccionada para este lote.')
        source=conn.execute("SELECT id FROM source_registry WHERE kind='values'").fetchone()[0]
        batch=_batch(conn,ds,bid)
        confirm_provider_scope(conn,root,token,ds,bid,source,'HPC','unverified','HPC ficticio; referencia candidata para el ensayo visual.',version(),batch['revision_version'])
        print('Analizando 3.000 órdenes ficticias...',flush=True)
        run_controls(conn,token,ds,bid,version())
        conn.execute('DELETE FROM sessions')
        print('Factura de 3.000 filas, 750 pacientes ficticios, 750 órdenes CSV y catálogo HPC preparada.',flush=True)
    finally:conn.close()


if __name__=='__main__':
    main()

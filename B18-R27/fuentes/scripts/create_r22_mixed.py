"""Add the mixed fictional order in a separate dataset inside the prepared demo."""
import hashlib
from io import BytesIO
from openpyxl import load_workbook
from app.authorization_imports import stage_authorization,preview_authorization,confirm_authorization
from app.authorization_matching import save_scope
from app.controls import run_controls
from app.display_categories import save_category
from app.economic_evidence import confirm_provider_scope,register_evidence_pdf
from app.economic_applicability import preview,save_reference
from app.local_hpc import save as save_tariff
from app.report_pdf import make_pdf
from app.review import _batch
from app.service import create_dataset,create_batch,confirm_invoice,grant_access
from app.storage import read_verified
from app.values_v1 import register_values
from tests.test_display_categories import nomenclature
from tests.test_hpc_csv_intake import encode,row
from tests.test_p02 import book

MR='2211221100'
ECO='3300334400'
LABEL='DEMO FICTICIO · Orden mixta de Imágenes'

def prepare(conn,root,token):
    if conn.execute('SELECT 1 FROM datasets WHERE label=?',(LABEL,)).fetchone():
        raise ValueError('El ejemplo ya existe.')
    original=conn.execute("SELECT source_sha256,manifest_sha256 FROM source_registry WHERE kind='values' LIMIT 1").fetchone()
    ds=create_dataset(conn,token,LABEL)['id']
    def version():return conn.execute('SELECT version FROM datasets WHERE id=?',(ds,)).fetchone()[0]
    for username,duty in [('demo-administrativo','administrative'),('demo-auditor','auditor')]:
        grant_access(conn,token,ds,version(),username,'reviewer',duty)
    src,_=register_values(conn,root,token,ds,version(),read_verified(root,original[0]),read_verified(root,original[1]),original[0])
    source=src['id']
    excerpt='Resonancia ficticia, 120.000 ARS por práctica, válida desde el 01/08/2026.'
    pdf=make_pdf('Convenio HPC ficticio',[excerpt])
    doc,_=register_evidence_pdf(conn,root,token,ds,source,version(),'Convenio-ficticio.pdf','agreement',
        'Convenio académico para la demostración de presupuesto.',hashlib.sha256(pdf).hexdigest(),pdf)
    save_tariff(conn,root,token,ds,source,expected_dataset_version=version(),code=MR,description='Resonancia ficticia',family='images',
        amount_ars='120000.00',currency='ARS',unit_label='por práctica',active=True,effective_from='2026-08-01',
        document_id=doc['id'],page_number=1,excerpt=excerpt,reason='Alta documentada de resonancia ficticia en convenio.')
    wb=load_workbook(BytesIO(book([('02/08/2026',100000,20000,120000),('02/08/2026',400000,50000,450000)])))
    for n,code,desc in [(2,MR,'Resonancia ficticia'),(3,ECO,'Ecografía TV ficticia')]:
        for col,value in [(2,22001),(3,'000111/1'),(5,code),(7,1),(11,desc)]:wb.active.cell(n,col).value=value
    out=BytesIO();wb.save(out);wb.close()
    batch,_=create_batch(conn,root,token,ds,version(),'FICTICIO_Eco_y_resonancia.xlsx',out.getvalue())
    bid=batch['id'];confirm_invoice(conn,root,token,ds,bid,'2026-08',version())
    def rev():return _batch(conn,ds,bid)['revision_version']
    confirm_provider_scope(conn,root,token,ds,bid,source,'HPC','unverified','Factura ficticia del prestador HPC.',version(),rev())
    save_category(conn,root,token,ds,bid,3,version=version(),revision=rev(),code=ECO,family='images',sheet='Prácticas',
        evidence_row=2,evidence_column=1,filename='Nomenclador-eco-ficticio.xlsx',content=nomenclature(ECO))
    orders=encode([row(orden_hpc='MIXTA-22',afiliado='000111/1',practicas=f'{MR} -- Resonancia ficticia,{ECO} -- Ecografía TV ficticia,',
        movimientos=f'02/07/2026 12:00 | Operador ficticio | AUTORIZADO | Resolución por ítems - AUTORIZAR: {MR}; AUTORIZAR: {ECO}',
        observacion='Presupuesto ARS 200.000. Ver anexo ficticio de la orden MIXTA-22, ítem de ecografía.',
        fecha_orden='2026-07-02',fecha_orden_original='02/07/2026')])
    up,_=stage_authorization(conn,root,token,ds,version(),'Autorizaciones-mixtas-ficticias.csv',orders)
    pre=preview_authorization(conn,root,token,ds,up['id'])
    cap,_=confirm_authorization(conn,root,token,ds,up['id'],version(),pre['preview_sha256'],'Orden ficticia con presupuesto pendiente de asociación.')
    save_scope(conn,root,token,ds,bid,version(),[cap['id']],'real_unvalidated','Fuente ficticia completa del ejemplo.',
        csv_complete_from='2026-06-03',csv_complete_until='2026-08-04')
    ref=preview(conn,root,token,ds,bid,2,source)
    save_reference(conn,root,token,ds,bid,2,expected_dataset_version=version(),expected_revision_version=rev(),source_id=source,
        basis_sha256=ref['basis_sha256'],state='confirmed',document_id=doc['id'],page_number=1,excerpt=excerpt,covered_quantity='1',
        coverage_through='2026-08-31',note='Resonancia ficticia sin adicionales, unidad y vigencia comprobadas.')
    run_controls(conn,token,ds,bid,version())
    return ds,bid

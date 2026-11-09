"""Create a new fictional TAC journey with visible column states."""
import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from uuid import uuid4

from . import create_review_journey_demo
from app.controls import run_controls
from app.db import connect
from app.economic_evidence import confirm_provider_scope
from app.review import _batch
from app.row_documents import register
from app.security import issue_session, token_digest
from app.values_v1 import register_values
from tests.test_practice_families import fictional_family_values
from tests.test_row_documents import PDF


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name',default='demo-columnas')
    args = parser.parse_args()
    previous = sys.argv
    sys.argv = [previous[0],'--name',args.name,'--tac']
    try:
        create_review_journey_demo.main()
    finally:
        sys.argv = previous
    root = Path(__file__).resolve().parents[1]/'.tmp'/args.name
    _, manifest_bytes, _ = fictional_family_values(root)
    catalog = sqlite3.connect(root/'catalogo_ficticio.sqlite')
    catalog.execute("UPDATE hpc_catalog_providers SET id='HPC',name='HPC ficticio' WHERE id='P1'")
    catalog.execute("UPDATE hpc_catalog_codes SET code='1234567890',description='TAC de abdomen' WHERE seq=1")
    catalog.execute('DELETE FROM hpc_catalog_tariffs WHERE seq<>1')
    catalog.execute("UPDATE hpc_catalog_tariffs SET provider='HPC',code='1234567890',amount_cents=1500,"
                    "valid_from='2026-06-01',valid_until='2026-12-31',data_json=?",
                    (json.dumps({'conditions':'FICTICIO: un importe por práctica.',
                                 'calculation':{'kind':'nbu','ubMilliunits':1000,'rateCents':1500,'reviewRequired':False}}),))
    counts = {row[0]:catalog.execute('SELECT count(*) FROM "'+row[0]+'"').fetchone()[0]
              for row in catalog.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    catalog.commit()
    catalog.close()
    content = (root/'catalogo_ficticio.sqlite').read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    manifest = json.loads(manifest_bytes)
    manifest['counts'] = counts
    manifest['files']['valores_convenios_base_2026-10-09.sqlite'] = {'sha256':digest,'bytes':len(content)}
    conn = connect(root)
    try:
        ds = conn.execute('SELECT id FROM datasets').fetchone()[0]
        admin = conn.execute("SELECT id FROM users WHERE username='demo-admin'").fetchone()[0]
        token = token_digest(issue_session(conn,admin)[0])
        def version():
            return conn.execute('SELECT version FROM datasets WHERE id=?',(ds,)).fetchone()[0]
        source,_ = register_values(conn,root,token,ds,version(),content,json.dumps(manifest).encode(),digest)
        batches = conn.execute('SELECT id FROM batches ORDER BY original_name').fetchall()
        for lot in batches:
            batch = _batch(conn,ds,lot['id'])
            confirm_provider_scope(conn,root,token,ds,lot['id'],source['id'],'HPC','unverified',
                                   'HPC ficticio confirmado para mostrar columnas; aplicabilidad pendiente.',
                                   version(),batch['revision_version'])
        first = batches[0]['id']
        batch = _batch(conn,ds,first)
        register(conn,root,token,ds,first,2,expected_dataset_version=version(),
                 expected_revision_version=batch['revision_version'],revision_id=batch['revision_id'],
                 request_id=str(uuid4()),category='informe',original_name='Informe-ficticio.pdf',
                 provenance='PDF ficticio adjuntado expresamente para mostrar presencia y lectura pendiente.',
                 expected_sha256=hashlib.sha256(PDF).hexdigest(),content=PDF)
        run_controls(conn,token,ds,first,version())
        conn.execute('DELETE FROM sessions')
    finally:
        conn.close()
    print('Demo de columnas creada. La TAC tiene una referencia candidata y un PDF ficticio por leer. Débitos sin proponer.')


if __name__=='__main__':
    main()

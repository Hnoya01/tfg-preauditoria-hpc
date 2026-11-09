"""Prepare a fresh fictional presentation and its two original intake files."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
from contextlib import closing
from unittest.mock import patch
import sys

from scripts import create_r25_demo
from app.db import connect
from app.security import issue_session, token_digest
from app.service import create_dataset, grant_access
from app.storage import read_verified
from app.values_v1 import register_values
from tests.test_display_categories import price_free_hpc_catalog


def intake_catalog(folder):
    _, manifest, _ = price_free_hpc_catalog(folder)
    path = folder / 'catalogo_ficticio.sqlite'
    with closing(sqlite3.connect(path)) as catalog:
        catalog.execute("INSERT INTO hpc_catalog_practices VALUES (13,'TAC TRIDIMENSIONAL','Imágenes')")
        catalog.execute("INSERT INTO hpc_catalog_codes VALUES (8,13,'tac-ficticia',1,'HPC','1234567890','orden','TAC TRIDIMENSIONAL')")
        catalog.commit()
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    info = json.loads(manifest)
    info['counts']['hpc_catalog_practices'] += 1
    info['counts']['hpc_catalog_codes'] += 1
    info['files']['valores_convenios_base_2026-10-09.sqlite'] = {'sha256': digest, 'bytes': len(data)}
    return data, json.dumps(info).encode(), digest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--name', default='presentacion-R27')
    name = parser.parse_args().name
    with patch.object(sys, 'argv', ['demo', '--plazo', '--name', name]):
        create_r25_demo.main()
    root = Path(__file__).resolve().parents[1] / '.tmp' / name
    conn = connect(root)
    try:
        source = conn.execute("SELECT dataset_id,source_sha256 FROM batches WHERE original_name='FICTICIO_presupuesto_TAC.xlsx'").fetchone()
        csv = conn.execute('SELECT source_sha256 FROM authorization_uploads WHERE dataset_id=?', (source['dataset_id'],)).fetchone()
        entries = root / 'entrada-ficticia'
        entries.mkdir()
        for filename, digest in [('TAC-ficticia.xlsx', source['source_sha256']), ('Avales-ficticios.csv', csv[0])]:
            (entries / filename).write_bytes(read_verified(root, digest))
        actor = conn.execute("SELECT id FROM users WHERE username='demo-admin'").fetchone()[0]
        token = token_digest(issue_session(conn, actor)[0])
        dataset = create_dataset(conn, token, 'DEMO FICTICIO · Carga nueva R27')
        ds = dataset['id']
        def version():
            return conn.execute('SELECT version FROM datasets WHERE id=?', (ds,)).fetchone()[0]
        for account, duty in [('demo-administrativo','administrative'), ('demo-auditor','auditor')]:
            grant_access(conn, token, ds, version(), account, 'reviewer', duty)
        catalog = root / 'catalogo-carga-ficticia'
        catalog.mkdir()
        register_values(conn, root, token, ds, version(), *intake_catalog(catalog))
        conn.execute('DELETE FROM sessions')
        for table in ('invoice_row_decisions', 'invoice_handoffs', 'audit_invoice_closures'):
            assert conn.execute('SELECT count(*) FROM '+table).fetchone()[0] == 0
        print('B18-R27 lista. Archivos de carga ficticios preparados. Cero decisiones, pases o cierres.')
    finally:
        conn.close()


if __name__ == '__main__':
    main()

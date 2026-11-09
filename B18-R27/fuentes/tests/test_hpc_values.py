"""Fictional, document-linked HPC value history."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
from tests.temp_support import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient

from app.api import create_app
from app.db import connect, migrate
from app.economic_evidence import register_evidence_pdf
from app.hpc_values import save_value_version, value_history
from app.security import create_user, issue_session, token_digest
from app.service import Problem, create_dataset
from app.values_v1 import register_values
from tests.test_p03 import fictional_values
from tests.test_p02 import PASSWORD


class HpcValueTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(dir='.tmp')
        self.root = Path(self.temp.name)
        self.conn = connect(self.root)
        migrate(self.conn)
        owner = create_user(self.conn, 'owner', PASSWORD, 'admin')
        token, csrf = issue_session(self.conn, owner)
        self.raw_token, self.csrf, self.digest = token, csrf, token_digest(token)
        self.dataset = create_dataset(self.conn, self.digest, 'Valores ficticios HPC')
        _, manifest_bytes, _ = fictional_values(self.root)
        path = self.root / 'catalogo_ficticio.sqlite'
        catalog = sqlite3.connect(path)
        catalog.execute("UPDATE hpc_catalog_providers SET id = 'HPC' WHERE id = 'P1'")
        catalog.execute("UPDATE hpc_catalog_codes SET provider = 'HPC' WHERE provider = 'P1'")
        catalog.execute("UPDATE hpc_catalog_tariffs SET provider = 'HPC' WHERE provider = 'P1'")
        catalog.commit()
        catalog.close()
        content = path.read_bytes()
        sha = hashlib.sha256(content).hexdigest()
        manifest = json.loads(manifest_bytes)
        manifest['files']['valores_convenios_base_2026-10-09.sqlite'] = {'sha256': sha, 'bytes': len(content)}
        source, _ = register_values(self.conn, self.root, self.digest, self.dataset['id'],
                                    self.dataset['version'], content, json.dumps(manifest).encode(), sha)
        self.source = source['id']
        self.dataset['version'] = source['dataset_version']
        pdf = b'%PDF-1.4\n% Documento ficticio HPC\n1 0 obj\n<<>>\nendobj\n%%EOF'
        document, _ = register_evidence_pdf(self.conn, self.root, self.digest, self.dataset['id'],
                                             self.source, self.dataset['version'], 'convenio-ficticio.pdf',
                                             'agreement', 'Convenio ficticio para probar historia',
                                             hashlib.sha256(pdf).hexdigest(), pdf)
        self.document = document['id']
        self.dataset['version'] = document['dataset_version']

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def payload(self, **changes):
        value = dict(expected_dataset_version=self.dataset['version'], tariff_seq=1,
                     code='123456', amount_ars='145.20', unit_label='por práctica',
                     effective_from='2026-11-01', document_id=self.document, page_number=2,
                     excerpt='Cláusula ficticia: nuevo arancel HPC 145,20 por práctica.',
                     reason='Aumento según convenio ficticio para ensayo local')
        value.update(changes)
        return value

    def test_version_history_and_original_untouched(self):
        original = self.conn.execute('SELECT source_sha256 FROM source_registry WHERE id = ?', (self.source,)).fetchone()[0]
        first = save_value_version(self.conn, self.root, self.digest, self.dataset['id'], self.source,
                                   **self.payload())
        self.assertEqual(first['ordinal'], 1)
        self.dataset['version'] = first['dataset_version']
        second = save_value_version(self.conn, self.root, self.digest, self.dataset['id'], self.source,
                                    **self.payload(amount_ars='149.00', reason='Corrección documentada ficticia'))
        history = value_history(self.conn, self.root, self.digest, self.dataset['id'], self.source, 1)
        self.assertEqual([v['amount_ars'] for v in history['versions']], ['145.20', '149.00'])
        self.assertEqual(history['versions'][1]['previous_id'], first['id'])
        self.assertEqual(history['cut_label'], 'BASE_2026-10-09')
        self.assertEqual(self.conn.execute('SELECT source_sha256 FROM source_registry WHERE id = ?', (self.source,)).fetchone()[0], original)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM control_runs').fetchone()[0], 0)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM economic_verifications').fetchone()[0], 0)
        self.assertEqual(second['dataset_version'], first['dataset_version'] + 1)

    def test_reject_stale_wrong_scope_invalid_amount_and_earlier_date(self):
        with self.assertRaises(Problem) as invalid:
            save_value_version(self.conn, self.root, self.digest, self.dataset['id'], self.source,
                               **self.payload(amount_ars='145.205'))
        self.assertEqual(invalid.exception.status, 422)
        with self.assertRaises(Problem) as wrong:
            save_value_version(self.conn, self.root, self.digest, self.dataset['id'], self.source,
                               **self.payload(tariff_seq=3))
        self.assertEqual(wrong.exception.status, 422)
        first = save_value_version(self.conn, self.root, self.digest, self.dataset['id'], self.source,
                                   **self.payload())
        with self.assertRaises(Problem) as stale:
            save_value_version(self.conn, self.root, self.digest, self.dataset['id'], self.source,
                               **self.payload())
        self.assertEqual(stale.exception.status, 409)
        self.dataset['version'] = first['dataset_version']
        with self.assertRaises(Problem) as earlier:
            save_value_version(self.conn, self.root, self.digest, self.dataset['id'], self.source,
                               **self.payload(effective_from='2026-10-01'))
        self.assertEqual(earlier.exception.status, 409)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM hpc_value_versions').fetchone()[0], 1)

    def test_api_session_csrf_and_version(self):
        app = create_app(self.root, public_origin='https://testserver')
        route = f'/api/datasets/{self.dataset["id"]}/sources/{self.source}/hpc-values'
        with TestClient(app, base_url='https://testserver') as client:
            self.assertEqual(client.get(route + '/1').status_code, 401)
            client.cookies.set('tfg_session', self.raw_token)
            self.assertEqual(client.post(route, json=self.payload(), headers={'Origin': 'https://testserver'}).status_code, 403)
            posted = client.post(route, json=self.payload(), headers={'Origin': 'https://testserver', 'X-CSRF-Token': self.csrf})
            self.assertEqual(posted.status_code, 201, posted.text)
            self.assertEqual(client.get(route + '/1').json()['versions'][0]['amount_ars'], '145.20')
            stale = client.post(route, json=self.payload(), headers={'Origin': 'https://testserver', 'X-CSRF-Token': self.csrf})
            self.assertEqual(stale.status_code, 409)


if __name__ == '__main__':
    unittest.main()

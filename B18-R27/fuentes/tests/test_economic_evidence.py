"""P06 source evidence registration with invented documents and provider IDs."""

from __future__ import annotations

from contextlib import closing
import hashlib
import json
import sqlite3
from pathlib import Path
from tests.temp_support import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient

from app.api import create_app
from app.controls import run_controls
from app.db import connect, migrate
from app.security import create_user, token_digest
from app.values_v1 import register_values
from tests.test_p02 import ORIGIN, PASSWORD, book
from tests.test_p03 import fictional_values


PDF = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\n%%EOF\n"


class EconomicEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(dir=".tmp")
        self.root = Path(self.temp.name)
        conn = connect(self.root)
        migrate(conn)
        create_user(conn, "owner", PASSWORD, "admin")
        create_user(conn, "viewer", PASSWORD, "viewer")
        conn.close()
        self.client = TestClient(create_app(self.root, public_origin=ORIGIN), base_url=ORIGIN)
        self.client.__enter__()
        login = self.client.post("/api/session", json={"username": "owner", "password": PASSWORD},
                                 headers={"Origin": ORIGIN})
        self.csrf = login.json()["csrf_token"]
        self.digest = token_digest(self.client.cookies.get("tfg_session"))
        self.dataset = self.client.post("/api/datasets", json={"label": "Evidencia ficticia"},
                                        headers=self.headers()).json()
        staged = self.client.post(f'/api/datasets/{self.dataset["id"]}/batches',
            content=book([("15/08/2026", 10, 20, 30)]),
            headers=self.headers(**{"X-Expected-Version": str(self.dataset["version"]),
                                    "X-Source-Filename": "ficticio.xlsx",
                                    "Content-Type": "application/octet-stream"}))
        self.assertEqual(staged.status_code, 201, staged.text)
        self.batch = staged.json()["id"]
        self.dataset["version"] = staged.json()["dataset_version"]
        imported = self.client.post(f'/api/datasets/{self.dataset["id"]}/batches/{self.batch}/invoice-import',
            json={"period": "2026-08", "period_confirmed": True,
                  "expected_version": self.dataset["version"]}, headers=self.headers())
        self.assertEqual(imported.status_code, 201, imported.text)
        self.dataset["version"] = imported.json()["dataset_version"]
        content, manifest, sha = fictional_values(self.root)
        path = self.root/'catalogo_ficticio.sqlite'
        with closing(sqlite3.connect(path)) as catalog, catalog:
            catalog.execute("INSERT INTO hpc_catalog_providers VALUES (3,'HPC','HPC ficticio')")
        content = path.read_bytes(); sha = hashlib.sha256(content).hexdigest()
        data = json.loads(manifest);data['counts']['hpc_catalog_providers'] += 1
        data['files']['valores_convenios_base_2026-10-09.sqlite'] = {'sha256':sha,'bytes':len(content)}
        manifest = json.dumps(data).encode()

        conn = connect(self.root)
        self.source, _ = register_values(conn, self.root, self.digest, self.dataset["id"],
                                         self.dataset["version"], content, manifest, sha)
        self.dataset["version"] = self.source["dataset_version"]
        conn.close()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def headers(self, **other):
        return {"Origin": ORIGIN, "X-CSRF-Token": self.csrf, **other}

    def scope_url(self):
        return f'/api/datasets/{self.dataset["id"]}/batches/{self.batch}/provider-scope'

    def scope_body(self, **changes):
        page = self.client.get(self.scope_url()).json()
        return {"expected_dataset_version": self.dataset["version"],
                "expected_revision_version": page["revision_version"],
                "source_id": self.source["id"], "provider": "HPC",
                "billing_unit": "unverified",
                "confirmation_note": "El lote ficticio corresponde al prestador HPC.", **changes}

    def pdf_url(self):
        return f'/api/datasets/{self.dataset["id"]}/evidence-pdfs'

    def pdf_headers(self, **changes):
        return self.headers(**{"X-Expected-Version": str(self.dataset["version"]),
                              "X-Source-Id": self.source["id"],
                              "X-Source-Filename": "acuerdo-ficticio.pdf",
                              "X-Evidence-Category": "agreement",
                              "X-Provenance-Note": "Original ficticio aportado para prueba.",
                              "X-Expected-SHA256": hashlib.sha256(PDF).hexdigest(), **changes})

    def test_scope_is_versioned_and_only_rn14_15_become_affected(self):
        conn = connect(self.root)
        run, _ = run_controls(conn, self.digest, self.dataset["id"], self.batch,
                              self.dataset["version"])
        self.dataset["version"] += 1
        conn.close()
        body = self.scope_body()
        wrong = self.client.post(self.scope_url(), json={**body, "provider": "P1"},
                                 headers=self.headers())
        self.assertEqual(wrong.status_code, 422, wrong.text)
        unproven_unit = self.client.post(self.scope_url(),
            json={**body, "billing_unit": "practice"}, headers=self.headers())
        self.assertEqual(unproven_unit.status_code, 422)
        saved = self.client.post(self.scope_url(), json=body, headers=self.headers())
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["billing_unit"], "unverified")
        self.assertEqual(saved.json()["cut_label"], "BASE_2026-10-09")
        stale = self.client.post(self.scope_url(), json=body, headers=self.headers())
        self.assertEqual(stale.status_code, 409)
        self.dataset["version"] = saved.json()["dataset_version"]
        repeated = self.client.post(self.scope_url(), json=self.scope_body(), headers=self.headers())
        self.assertEqual(repeated.status_code, 200)
        self.assertFalse(repeated.json()["created"])
        history = self.client.get(self.scope_url()).json()
        self.assertEqual(len(history["history"]), 1)
        self.assertEqual(history["dataset_version"], self.dataset["version"])
        self.assertEqual(history["revision_version"], saved.json()["revision_version"])
        self.assertNotEqual(history["revision_state"], "cerrada")
        summary = self.client.get(f'/api/datasets/{self.dataset["id"]}/control-runs/{run["id"]}')
        self.assertEqual(summary.status_code, 200, summary.text)
        self.assertIn("RN14", summary.json()["affected_rules"])
        self.assertIn("RN15", summary.json()["affected_rules"])
        self.assertNotIn("RN17", summary.json()["affected_rules"])

    def test_pdf_registration_hash_privacy_dedup_and_permissions(self):
        wrong = self.client.post(self.pdf_url(), content=PDF,
            headers=self.pdf_headers(**{"X-Expected-SHA256": "0" * 64}))
        self.assertEqual(wrong.status_code, 422)
        self.assertEqual(self.client.get(self.pdf_url()).json(), [])
        added = self.client.post(self.pdf_url(), content=PDF, headers=self.pdf_headers())
        self.assertEqual(added.status_code, 201, added.text)
        self.assertEqual(added.json()["source_match"], "no_catalog_hash")
        self.assertEqual(added.json()["cut_label"], "BASE_2026-10-09")
        self.dataset["version"] = added.json()["dataset_version"]
        again = self.client.post(self.pdf_url(), content=PDF, headers=self.pdf_headers())
        self.assertEqual(again.status_code, 200, again.text)
        self.assertEqual(again.json()["id"], added.json()["id"])
        listed = self.client.get(self.pdf_url()).json()
        self.assertEqual(len(listed), 1)
        download = self.client.get(f'{self.pdf_url()}/{added.json()["id"]}/file')
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.content, PDF)
        self.assertEqual(download.headers["X-Content-SHA256"], hashlib.sha256(PDF).hexdigest())
        conn = connect(self.root)
        self.assertEqual(conn.execute("SELECT count(*) FROM evidence_documents").fetchone()[0], 1)
        conn.close()
        viewer = TestClient(create_app(self.root, public_origin=ORIGIN), base_url=ORIGIN)
        viewer.__enter__()
        try:
            login = viewer.post("/api/session", json={"username": "viewer", "password": PASSWORD},
                                headers={"Origin": ORIGIN})
            self.assertEqual(login.status_code, 200)
            denied = viewer.post(self.pdf_url(), content=PDF,
                headers={**self.pdf_headers(), "X-CSRF-Token": login.json()["csrf_token"]})
            self.assertEqual(denied.status_code, 403)
            self.assertEqual(viewer.get(self.pdf_url()).status_code, 403)
        finally:
            viewer.__exit__(None, None, None)

    def test_batch_practice_unit_requires_explicit_basis_and_keeps_invoice_hash_history(self):
        body=self.scope_body(billing_unit='practice')
        rejected=self.client.post(self.scope_url(),json=body,headers=self.headers())
        self.assertEqual(rejected.status_code,422)
        body['billing_unit_note']='Factura ficticia Hoja1: la columna G representa número de prácticas, no U.B. ni horas.'
        saved=self.client.post(self.scope_url(),json=body,headers=self.headers())
        self.assertEqual(saved.status_code,200,saved.text)
        self.assertEqual(saved.json()['billing_unit'],'practice')
        page=self.client.get(self.scope_url()).json()
        self.assertIn(body['billing_unit_note'],page['current']['confirmation_note'])
        self.assertIn('Factura original SHA-256:',page['current']['confirmation_note'])
        self.assertIn('No acredita autorización',page['current']['confirmation_note'])
        c=connect(self.root)
        try:
            self.assertEqual(c.execute('SELECT count(*) FROM control_runs').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT count(*) FROM row_economic_references').fetchone()[0],0)
        finally:c.close()

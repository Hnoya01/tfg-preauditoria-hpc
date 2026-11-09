"""P06 proposal persistence uses invented X1, V1 and PDF bytes only."""

from __future__ import annotations

import json
from pathlib import Path
from tests.temp_support import TemporaryDirectory
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api import create_app
from app.controls import run_controls
from app.db import connect, migrate
from app.proposals import save_verified_proposal
from app.security import create_user, issue_session, now_utc, token_digest
from app.service import Problem
from app.storage import publish_bytes
from app.values_v1 import register_values
from tests.test_p02 import ORIGIN, PASSWORD, book
from tests.test_p03 import fictional_values


class ProposalPersistenceTests(unittest.TestCase):
    INVOICE_TOTAL = 150
    SOURCE_DIFFERENCE = 0
    def setUp(self):
        self.temp = TemporaryDirectory(dir=".tmp")
        self.root = Path(self.temp.name)
        conn = connect(self.root)
        migrate(conn)
        create_user(conn, "owner", PASSWORD, "admin")
        conn.close()
        self.client = TestClient(create_app(self.root, public_origin=ORIGIN), base_url=ORIGIN)
        self.client.__enter__()
        login = self.client.post("/api/session", json={"username": "owner", "password": PASSWORD},
                                 headers={"Origin": ORIGIN})
        self.csrf = login.json()["csrf_token"]
        self.digest = token_digest(self.client.cookies.get("tfg_session"))
        self.dataset = self.client.post("/api/datasets", json={"label": "Ficción P06"},
                                        headers=self.headers()).json()
        self.batch = self.import_book(book([("15/08/2026", self.INVOICE_TOTAL, 0,
                                             self.INVOICE_TOTAL + self.SOURCE_DIFFERENCE)]), "uno.xlsx")
        self.other_batch = self.import_book(book([("15/08/2026", self.INVOICE_TOTAL + 1, 0,
                                                   self.INVOICE_TOTAL + self.SOURCE_DIFFERENCE + 1)]), "dos.xlsx")
        content, manifest, digest = fictional_values(self.root, getattr(self, 'VALUES_CALCULATION', None))
        conn = connect(self.root)
        self.source, _ = register_values(conn, self.root, self.digest, self.dataset["id"],
                                         self.dataset["version"], content, manifest, digest)
        self.dataset["version"] = self.source["dataset_version"]
        result, _ = run_controls(conn, self.digest, self.dataset["id"], self.batch,
                                 self.dataset["version"])
        self.dataset["version"] += 1
        conn.close()
        alerts = self.client.get(f'/api/datasets/{self.dataset["id"]}/batches/{self.batch}/alerts').json()
        alert = next(a for a in alerts["items"] if a["source_row"] == 2 and a["rule_code"] == "RN17")
        decided = self.client.post(f'/api/datasets/{self.dataset["id"]}/batches/{self.batch}/decisions',
            json={"expected_dataset_version": self.dataset["version"],
                  "expected_revision_version": alerts["revision_version"],
                  "items": [{"id": alert["id"], "expected_version": alert["version"]}],
                  "state": "confirmada", "foundation": "Duplicación ficticia cotejada en el lote.",
                  "evidence_note": "Se revisaron ambos originales ficticios."},
            headers=self.headers())
        self.assertEqual(decided.status_code, 200, decided.text)
        self.decision_id = decided.json()["decision_ids"][0]
        self.dataset["version"] = decided.json()["dataset_version"]
        self.revision_version = decided.json()["revision_version"]
        pdf_sha, pdf_len, pdf_path = publish_bytes(self.root, b"%PDF-1.4\nDocumento ficticio\n")
        conn = connect(self.root)
        self.verification_id = str(uuid4())
        user_id = conn.execute("SELECT id FROM users WHERE username = 'owner'").fetchone()[0]
        import_id, revision_id = conn.execute("SELECT id, revision_id FROM invoice_imports "
                                              "WHERE batch_id = ?", (self.batch,)).fetchone()
        conn.execute("INSERT INTO stored_files VALUES (?, ?, ?, ?)",
                     (pdf_sha, pdf_len, pdf_path, now_utc()))
        conn.execute("INSERT INTO batch_provider_scopes VALUES (?, ?, ?, ?, ?, ?)",
                     (self.batch, "P1", "practice", "Prestador y unidad ficticios confirmados.",
                      user_id, now_utc()))
        conn.execute("INSERT INTO batch_provider_scope_history VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?)",
                     (str(uuid4()), self.batch, 1, self.source["id"], "P1", "practice",
                      "Prestador y unidad ficticios confirmados.", user_id, now_utc()))
        conn.execute("INSERT INTO evidence_documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (str(uuid4()), self.dataset["id"], self.source["id"], pdf_sha,
                      "ficticio.pdf", "agreement", "no_catalog_hash",
                      "Documento ficticio de prueba solamente.", user_id, now_utc()))
        conn.execute("INSERT INTO economic_verifications VALUES "
                     "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
                     (self.verification_id, self.dataset["id"], self.source["id"],
                      self.source["source_sha256"], pdf_sha, "PDF ficticio:página 1",
                      "hpc_catalog_tariffs.seq=1", "P1", "123456", "ARS", "practice",
                      "123.45", "2026-07-01", "2026-08-31",
                      "Condiciones del convenio ficticio cotejadas para esta fila.",
                      user_id, now_utc()))
        conn.close()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def headers(self, **other):
        return {"Origin": ORIGIN, "X-CSRF-Token": self.csrf, **other}

    def import_book(self, content, name):
        staged = self.client.post(f'/api/datasets/{self.dataset["id"]}/batches', content=content,
            headers=self.headers(**{"X-Expected-Version": str(self.dataset["version"]),
                                    "X-Source-Filename": name,
                                    "Content-Type": "application/octet-stream"}))
        self.assertEqual(staged.status_code, 201, staged.text)
        self.dataset["version"] = staged.json()["dataset_version"]
        batch_id = staged.json()["id"]
        imported = self.client.post(f'/api/datasets/{self.dataset["id"]}/batches/{batch_id}/invoice-import',
            json={"period": "2026-08", "period_confirmed": True,
                  "expected_version": self.dataset["version"]}, headers=self.headers())
        self.assertEqual(imported.status_code, 201, imported.text)
        self.dataset["version"] = imported.json()["dataset_version"]
        return batch_id

    def spec(self, **changes):
        return {"decision_id": self.decision_id, "verification_id": self.verification_id,
                "rubric": "honorarios", "unit_start": "0", "unit_end": "1",
                "billed_scope_ars": "150.00", **changes}

    def save(self, conn, **changes):
        return save_verified_proposal(conn, self.root, self.digest, self.dataset["id"],
                                      self.batch, 2, self.dataset["version"],
                                      self.revision_version, (self.spec(**changes),))

    def test_immutable_versions_stale_save_and_revoked_evidence(self):
        conn = connect(self.root)
        first = self.save(conn)
        self.assertEqual(first["amount_ars"], "26.55")
        self.assertEqual(first["ordinal"], 1)
        history = self.client.get(
            f'/api/datasets/{self.dataset["id"]}/batches/{self.batch}/rows/2/proposals')
        self.assertEqual(history.status_code, 200, history.text)
        self.assertEqual(history.json()["current_proposal"]["amount_ars"], "26.55")
        self.assertEqual(history.json()["versions"][0]["payload_at_save"]["verification_snapshots"][0]
                         ["source_sha256"], self.source["source_sha256"])
        with self.assertRaises(Problem) as stale:
            self.save(conn)
        self.assertEqual(stale.exception.status, 409)
        self.dataset["version"] = first["dataset_version"]
        self.revision_version = first["revision_version"]
        second = self.save(conn, adjusted_ars="20.00", adjustment_calculation="150 - 130 = 20",
                           adjustment_reason="Ajuste ficticio con fundamento documental.")
        self.assertEqual(second["ordinal"], 2)
        self.assertEqual(second["previous_id"], first["id"])
        rows = conn.execute("SELECT * FROM proposal_versions ORDER BY ordinal").fetchall()
        self.assertEqual([r["amount_ars"] for r in rows], ["26.55", "20.00"])
        self.assertEqual(json.loads(rows[1]["payload_json"])["components"][0]["automatic_amount_ars"],
                         "26.55")
        self.dataset["version"] = second["dataset_version"]
        self.revision_version = second["revision_version"]
        conn.execute("UPDATE economic_verifications SET active = 0 WHERE id = ?",
                     (self.verification_id,))
        with self.assertRaises(Problem) as revoked:
            self.save(conn)
        self.assertEqual(revoked.exception.status, 409)
        self.assertEqual(conn.execute("SELECT count(*) FROM proposal_versions").fetchone()[0], 2)
        conn.close()

    def test_changed_tariff_and_overlapping_components_cannot_save(self):
        conn = connect(self.root)
        conn.execute("UPDATE economic_verifications SET rate_ars = '1.00' WHERE id = ?",
                     (self.verification_id,))
        with self.assertRaises(Problem) as mismatch:
            self.save(conn)
        self.assertEqual(mismatch.exception.status, 409)
        conn.execute("UPDATE economic_verifications SET rate_ars = '123.45' WHERE id = ?",
                     (self.verification_id,))
        with self.assertRaises(Problem) as overlap:
            save_verified_proposal(conn, self.root, self.digest, self.dataset["id"], self.batch,
                                   2, self.dataset["version"], self.revision_version,
                                   (self.spec(), self.spec()))
        self.assertEqual(overlap.exception.status, 422)
        self.assertEqual(conn.execute("SELECT count(*) FROM proposal_versions").fetchone()[0], 0)
        conn.close()

    def test_viewer_cannot_save(self):
        conn = connect(self.root)
        user_id = create_user(conn, "reader", PASSWORD, "viewer")
        token, _ = issue_session(conn, user_id)
        with self.assertRaises(Problem) as denied:
            save_verified_proposal(conn, self.root, token_digest(token), self.dataset["id"],
                                   self.batch, 2, self.dataset["version"],
                                   self.revision_version, (self.spec(),))
        self.assertEqual(denied.exception.status, 403)
        self.assertEqual(conn.execute("SELECT count(*) FROM proposal_versions").fetchone()[0], 0)
        conn.close()

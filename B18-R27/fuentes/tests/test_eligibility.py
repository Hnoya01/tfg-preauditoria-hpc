"""ALC02 regression: A and C eligible, I excluded, legacy history preserved."""

from __future__ import annotations

import hashlib
from io import BytesIO
import json
from pathlib import Path
from tests.temp_support import TemporaryDirectory
import unittest
from uuid import uuid4
from zipfile import ZipFile

from fastapi.testclient import TestClient

from app.api import create_app
from app.controls import _snapshot
from app.db import connect, migrate
from app.eligibility import POLICY_VERSION, classify
from app.invoice_x1 import parse_x1
from app.proposals import save_verified_proposal
from app.security import create_user, now_utc, token_digest
from app.service import Problem
from tests import test_hpc_comparison as hpc_fixture
from tests import test_p05 as review_fixture
from tests.test_p02 import ORIGIN, PASSWORD, book


class EligibilityTests(unittest.TestCase):
    headers = review_fixture.P05Tests.headers
    import_book = review_fixture.P05Tests.import_book
    run_url = review_fixture.P05Tests.run_url
    register_fictional_hpc = hpc_fixture.HpcComparisonTests.register_fictional_hpc

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
        self.dataset = self.client.post("/api/datasets", json={"label": "Alcance ficticio ALC02"},
                                        headers=self.headers()).json()
        self.content = book([("15/08/2026", 20, 20, 40, kind) for kind in ("A", "I", "C")])
        self.batch = self.import_book(self.content, "uno.xlsx")
        self.import_book(book([("15/08/2026", 21, 20, 41, kind) for kind in ("A", "I", "C")]),
                         "dos.xlsx")
        self.source_id = self.register_fictional_hpc()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def seed_legacy(self):
        conn = connect(self.root)
        invoice = conn.execute("SELECT i.*, b.source_sha256 FROM invoice_imports i JOIN batches b "
                               "ON b.id = i.batch_id WHERE b.id = ?", (self.batch,)).fetchone()
        conn.execute("UPDATE invoice_rows SET disposition = 'included', disposition_reason = NULL "
                     "WHERE import_id = ?", (invoice["id"],))
        conn.execute("UPDATE invoice_imports SET included_count = 3, excluded_count = 0, "
                     "eligibility_version = 'period-only-v0' WHERE id = ?", (invoice["id"],))
        snapshot = _snapshot(conn, self.dataset["id"], invoice)
        snapshot["rule_version"] = "P05.1"
        snapshot.pop("eligibility_policy")
        snapshot.pop("eligibility")
        raw = json.dumps(snapshot, sort_keys=True)
        run_id, actor_id = str(uuid4()), conn.execute("SELECT id FROM users").fetchone()[0]
        conn.execute("INSERT INTO control_runs VALUES (?, ?, ?, ?, ?, ?, 'completed', 'current', ?, ?)",
                     (run_id, self.dataset["id"], invoice["revision_id"], invoice["id"],
                      hashlib.sha256(raw.encode()).hexdigest(), raw, actor_id, now_utc()))
        alerts = []
        for number in (2, 3, 4):
            conn.execute("INSERT INTO control_results VALUES (?, ?, ?, 'RN17', 'P05.1', 'con_indicios', "
                         "'coincidencia_estricta_candidata', '{}', NULL, NULL)",
                         (run_id, invoice["id"], number))
            alert_id = str(uuid4())
            conn.execute("INSERT INTO alerts VALUES (?, ?, ?, ?, 'RN17', ?, 1, ?)",
                         (alert_id, invoice["revision_id"], invoice["id"], number, run_id, now_utc()))
            alerts.append({"id": alert_id, "expected_version": 1})
        conn.close()
        return run_id, alerts

    def test_period_and_setting_are_independent_and_unknown_is_not_approved(self):
        parsed = parse_x1(self.content, "2026-08")
        self.assertEqual((parsed.summary["included"], parsed.summary["excluded"]), (2, 1))
        self.assertEqual([r[1] for r in parsed.rows], ["included", "excluded", "included"])
        self.assertEqual(parsed.rows[1][2], "internacion_fuera_de_alcance")
        self.assertEqual(classify("2026-08-01", " c ", "2026-08")["disposition"], "included")
        self.assertEqual(classify("2026-08-01", "?", "2026-08")["disposition"], "indeterminate")
        unknown_outside = classify("2026-07-01", "?", "2026-08")
        self.assertEqual((unknown_outside["disposition"], unknown_outside["period_disposition"],
                          unknown_outside["setting_disposition"]), ("excluded", "excluded", "indeterminate"))
        both = classify("2026-07-01", "I", "2026-08")
        self.assertEqual(both["eligibility_reasons"], ["fuera_del_periodo", "internacion_fuera_de_alcance"])

    def test_legacy_internation_stays_historical_and_all_consumers_exclude_it(self):
        legacy_id, legacy_alerts = self.seed_legacy()
        base = f'/api/datasets/{self.dataset["id"]}/batches/{self.batch}'
        metadata = self.client.get(f"{base}/invoice-import").json()
        self.assertEqual(metadata["included_count"], 2)
        self.assertEqual(metadata["classification_at_import"]["included_count"], 3)
        stale = self.client.get(f'/api/datasets/{self.dataset["id"]}/control-runs/{legacy_id}').json()
        self.assertIn("RN17", stale["affected_rules"])
        self.assertEqual((stale["freshness"], stale["stored_freshness"]), ("requires_update", "current"))
        run_list = self.client.get(f"{base}/control-runs").json()
        self.assertEqual((run_list[0]["freshness"], run_list[0]["stored_freshness"]),
                         ("requires_update", "current"))
        conn = connect(self.root)
        self.assertEqual(conn.execute("SELECT count(*) FROM control_runs").fetchone()[0], 1)
        conn.close()
        page = self.client.get(f"{base}/alerts").json()
        self.assertEqual(page["total"], 2)
        self.assertEqual(page["historical_outside_scope_count"], 1)
        attempted = self.client.post(f"{base}/decisions", json={
            "expected_dataset_version": self.dataset["version"],
            "expected_revision_version": page["revision_version"], "items": legacy_alerts,
            "state": "confirmada", "foundation": "Fundamento ficticio de alcance.",
            "evidence_note": "Evidencia ficticia revisada por alcance."}, headers=self.headers())
        self.assertEqual(attempted.status_code, 409)
        analyzed = self.client.post(self.run_url(), json={"expected_version": self.dataset["version"]},
                                    headers=self.headers())
        self.assertEqual(analyzed.status_code, 201, analyzed.text)
        current_id = analyzed.json()["id"]
        self.dataset["version"] += 1
        self.assertNotEqual(current_id, legacy_id)
        page = self.client.get(f"{base}/alerts").json()
        self.assertEqual([a["source_row"] for a in page["items"]], [2, 4])
        history = self.client.get(f"{base}/alerts?include_historical=true").json()
        self.assertEqual(history["total"], 3)
        self.assertEqual(history["items"][1]["freshness"], "outside_scope")
        group = self.client.post(f"{base}/decisions", json={
            "expected_dataset_version": self.dataset["version"],
            "expected_revision_version": page["revision_version"],
            "items": [{"id": a["id"], "expected_version": a["version"]} for a in history["items"][:2]],
            "state": "confirmada", "foundation": "Fundamento ficticio del grupo.",
            "evidence_note": "Evidencia ficticia del grupo revisada."}, headers=self.headers())
        self.assertEqual(group.status_code, 409)
        comparison = self.client.get(f"{base}/hpc-comparison", params={"source_id": self.source_id}).json()
        self.assertEqual(comparison["counts"], {"numeric_above_candidate": 2, "outside_scope": 1})
        readiness = self.client.get(f"{base}/reference-readiness",
            params={"source_id": self.source_id, "source_row": 3}).json()["items"][0]
        self.assertIn("row_outside_scope", readiness["blocked_dimensions"])
        response = self.client.get(f"{base}/export-provisional")
        self.assertEqual(response.status_code, 200, response.text)
        with ZipFile(BytesIO(response.content)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            rows = [json.loads(line) for line in archive.read("rows.jsonl").splitlines()]
        self.assertEqual(manifest["batch"]["included_count"], 2)
        self.assertEqual(manifest["batch"]["classification_at_import"]["included_count"], 3)
        self.assertEqual(manifest["alert_counts"]["historical_outside_scope"], 1)
        self.assertEqual(rows[1]["proposal_state"], "outside_scope")
        self.assertEqual(rows[1]["import_disposition"], "included")
        conn = connect(self.root)
        try:
            self.assertEqual(conn.execute("SELECT count(*) FROM control_results WHERE run_id = ?",
                                          (legacy_id,)).fetchone()[0], 3)
            self.assertEqual(conn.execute("SELECT count(*) FROM review_decisions").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT disposition FROM invoice_rows WHERE import_id = ? "
                                          "AND source_row = 3", (metadata["id"],)).fetchone()[0], "included")
            self.assertEqual(analyzed.json()["snapshot"]["eligibility_policy"]["version"], POLICY_VERSION)
            actor_id = conn.execute("SELECT id FROM users").fetchone()[0]
            conn.execute("INSERT INTO batch_provider_scope_history VALUES (?, ?, 1, NULL, ?, 'HPC', "
                         "'unverified', 'Alcance ficticio confirmado.', ?, ?)",
                         (str(uuid4()), self.batch, self.source_id, actor_id, now_utc()))
            with self.assertRaises(Problem) as blocked:
                save_verified_proposal(conn, self.root, self.digest, self.dataset["id"], self.batch, 3,
                                       self.dataset["version"], page["revision_version"], ({},))
            self.assertEqual(blocked.exception.status, 422)
        finally:
            conn.close()

"""P06 provisional export checks use invented X1 rows only."""

from __future__ import annotations

from io import BytesIO
import hashlib
import json
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from tests import test_p05 as fixture


class P06Tests(unittest.TestCase):
    setUp = fixture.P05Tests.setUp
    tearDown = fixture.P05Tests.tearDown
    headers = fixture.P05Tests.headers
    import_book = fixture.P05Tests.import_book
    run_url = fixture.P05Tests.run_url
    alerts = fixture.P05Tests.alerts
    decide = fixture.P05Tests.decide

    def export(self):
        return self.client.get(
            f'/api/datasets/{self.dataset["id"]}/batches/{self.batch}/export-provisional')

    @staticmethod
    def unpack(response):
        with ZipFile(BytesIO(response.content)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            rows = [json.loads(line) for line in archive.read("rows.jsonl").splitlines()]
            results = [json.loads(line) for line in archive.read("control_results.jsonl").splitlines()]
            decisions = [json.loads(line) for line in archive.read("decisions.jsonl").splitlines()]
            return manifest, rows, results, decisions

    def test_provisional_pending_not_zero_and_complete_evidence(self):
        self.assertIn('id="value-provider" type="text" value="HPC" readonly',
                      self.client.get("/").text)
        response = self.export()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["content-type"], "application/zip")
        self.assertEqual(response.headers["x-content-sha256"],
                         hashlib.sha256(response.content).hexdigest())
        manifest, rows, results, decisions = self.unpack(response)
        self.assertEqual(manifest["kind"], "provisional_review_export")
        self.assertEqual(manifest["batch"]["id"], self.batch)
        self.assertEqual(manifest["batch"]["period"], "2026-08")
        self.assertEqual(manifest["control_run"]["id"], self.run["id"])
        self.assertEqual(manifest["alert_counts"]["pendiente"], 2)
        self.assertTrue(any(item["rule_code"] == "RN10" for item in
                            manifest["coverage_limitations"]))
        self.assertIsNone(manifest["current_proposal_total_ars"])
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(results), 22)
        self.assertEqual(decisions, [])
        self.assertEqual({r["proposal_state"] for r in rows}, {"pending_review"})
        self.assertTrue(all(r["proposed_amount_ars"] is None for r in rows))
        self.assertEqual(rows[0]["locator"], "Hoja1!2")
        self.assertTrue(any(r["rule_code"] == "RN17" and
                            r["evidence"]["candidate_count"] == 1 for r in results))

    def test_confirmed_candidate_stays_unquantified_and_history_exported(self):
        alert = self.alerts()["items"][0]
        response = self.decide([{"id": alert["id"], "expected_version": alert["version"]}],
                               state="confirmada", evidence_note="Caso ficticio cotejado por revisor.")
        self.assertEqual(response.status_code, 200, response.text)
        self.dataset["version"] = response.json()["dataset_version"]
        manifest, rows, _, decisions = self.unpack(self.export())
        self.assertEqual(manifest["alert_counts"]["confirmada"], 1)
        self.assertEqual(manifest["alert_counts"]["pendiente"], 1)
        self.assertEqual(rows[0]["proposal_state"], "unquantified_no_economic_basis")
        self.assertIsNone(rows[0]["proposed_amount_ars"])
        self.assertIsNone(manifest["current_proposal_total_ars"])
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]["id"], response.json()["decision_ids"][0])

    def test_viewer_cannot_export(self):
        from fastapi.testclient import TestClient
        from app.api import create_app
        from tests.test_p02 import ORIGIN, PASSWORD

        with TestClient(create_app(self.root, public_origin=ORIGIN), base_url=ORIGIN) as viewer:
            login = viewer.post("/api/session", json={"username": "viewer", "password": PASSWORD},
                                headers={"Origin": ORIGIN})
            self.assertEqual(login.status_code, 200)
            response = viewer.get(
                f'/api/datasets/{self.dataset["id"]}/batches/{self.batch}/export-provisional')
            self.assertEqual(response.status_code, 403)

    def test_change_marks_affected_result_and_row_without_reanalysis(self):
        page = self.alerts()
        response = self.client.post(
            f'/api/datasets/{self.dataset["id"]}/batches/{self.batch}/rows/2/work-fields',
            json={"expected_dataset_version": self.dataset["version"],
                  "expected_revision_version": page["revision_version"],
                  "field": "E", "value": "999999",
                  "reason": "Código ficticio corregido tras cotejo."},
            headers=self.headers())
        self.assertEqual(response.status_code, 200, response.text)
        manifest, rows, results, _ = self.unpack(self.export())
        self.assertIn("RN17", manifest["control_run"]["affected_rules"])
        self.assertEqual(rows[0]["proposal_state"], "requires_update")
        self.assertEqual(rows[0]["fields"]["E"], "123456")
        self.assertEqual(rows[0]["work_fields"]["E"]["value"], "999999")
        self.assertIsNone(rows[0]["proposed_amount_ars"])
        row_results = {r["rule_code"]: r for r in results if r["source_row"] == 2}
        self.assertEqual(row_results["RN13"]["freshness"], "current")
        self.assertEqual(row_results["RN17"]["freshness"], "requires_update")

    def test_concurrent_change_rejects_export_without_event(self):
        from app import provisional
        from app.db import connect

        original = provisional._write_lines
        def concurrent_change(archive, name, records):
            original(archive, name, records)
            if name == "rows.jsonl":
                other = connect(self.root)
                try:
                    other.execute("UPDATE datasets SET version = version + 1 WHERE id = ?",
                                  (self.dataset["id"],))
                finally:
                    other.close()

        with patch.object(provisional, "_write_lines", side_effect=concurrent_change):
            response = self.export()
        self.assertEqual(response.status_code, 409, response.text)
        conn = connect(self.root)
        try:
            self.assertEqual(conn.execute("SELECT count(*) FROM audit_events "
                                          "WHERE action = 'provisional_exported'").fetchone()[0], 0)
        finally:
            conn.close()

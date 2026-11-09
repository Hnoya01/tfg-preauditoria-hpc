"""P04 tests use invented rows and never inspect real patient data."""

from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path
from tests.temp_support import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient

from app.api import create_app
from app.controls import evaluate_row, run_controls
from app.db import MIGRATIONS, backup_before_upgrade, connect, migrate
from app.security import create_user, token_digest
from app.service import Problem
from unittest.mock import patch
from app.values_v1 import register_values
from tests.test_p02 import ORIGIN, PASSWORD, book
from tests.test_p03 import fictional_values


class P04Tests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(dir=".tmp")
        self.root = Path(self.temp.name)
        conn = connect(self.root)
        migrate(conn)
        create_user(conn, "owner", PASSWORD, "admin")
        conn.close()
        self.client = TestClient(create_app(self.root, public_origin=ORIGIN), base_url=ORIGIN)
        self.client.__enter__()
        session = self.client.post("/api/session", json={"username": "owner", "password": PASSWORD},
                                   headers={"Origin": ORIGIN})
        self.csrf = session.json()["csrf_token"]
        self.digest = token_digest(self.client.cookies.get("tfg_session"))
        self.dataset = self.client.post("/api/datasets", json={"label": "Ficción P04"},
                                        headers=self.headers()).json()
        content = book([("15/08/2026", 10, 20, 30), ("16/08/2026", 0, 0, 0),
                        ("15/07/2026", 4, 6, 10), ("sin fecha", 1, 2, 3)])
        staged = self.client.post(f'/api/datasets/{self.dataset["id"]}/batches', content=content,
                                  headers=self.headers(**{"X-Expected-Version": str(self.dataset["version"]),
                                                          "X-Source-Filename": "ficticio.xlsx",
                                                          "Content-Type": "application/octet-stream"})).json()
        self.batch = staged["id"]
        self.dataset["version"] = staged["dataset_version"]
        imported = self.client.post(f'/api/datasets/{self.dataset["id"]}/batches/{self.batch}/invoice-import',
                                    json={"period": "2026-08", "period_confirmed": True,
                                          "expected_version": self.dataset["version"]},
                                    headers=self.headers()).json()
        self.dataset["version"] = imported["dataset_version"]

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def headers(self, **other):
        return {"Origin": ORIGIN, "X-CSRF-Token": self.csrf, **other}

    def endpoint(self):
        return f'/api/datasets/{self.dataset["id"]}/batches/{self.batch}/control-runs'

    def test_snapshot_results_scope_and_idempotence(self):
        response = self.client.post(self.endpoint(), json={"expected_version": self.dataset["version"]},
                                    headers=self.headers())
        self.assertEqual(response.status_code, 201, response.text)
        run = response.json()
        self.assertEqual(run["technical_state"], "completed")
        self.assertEqual(run["snapshot"]["period"], "2026-08")
        self.assertEqual(sum(x["total"] for x in run["counts"]), 44)
        self.dataset["version"] += 1
        repeated = self.client.post(self.endpoint(), json={"expected_version": self.dataset["version"]},
                                    headers=self.headers())
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertEqual(repeated.json()["id"], run["id"])
        inside = self.client.get(f'/api/datasets/{self.dataset["id"]}/control-runs/{run["id"]}/rows/2').json()
        by_rule = {item["rule_code"]: item for item in inside}
        self.assertEqual(by_rule["RN10"]["result"], "no_concluyente")
        self.assertEqual(by_rule["RN13"]["result"], "sin_observaciones")
        self.assertEqual(by_rule["RN13"]["difference_ars"], "0.00")
        self.assertEqual(by_rule["RN14"]["result"], "no_concluyente")
        self.assertEqual(by_rule["RN18"]["result"], "no_evaluado")
        self.assertEqual(by_rule["RN19"]["result"], "sin_observaciones")
        self.assertEqual(by_rule["RN13"]["evidence"]["amounts_ars"]["Q"], "30.00")
        zero = self.client.get(f'/api/datasets/{self.dataset["id"]}/control-runs/{run["id"]}/rows/3').json()
        self.assertEqual(next(x for x in zero if x["rule_code"] == "RN16")["result"], "no_concluyente")
        late = self.client.get(f'/api/datasets/{self.dataset["id"]}/control-runs/{run["id"]}/rows/4').json()
        period_check = next(x for x in late if x["rule_code"] == "RN19")
        self.assertEqual((period_check["result"], period_check["evidence"]["days"]), ("con_indicios", 47))
        unknown = self.client.get(f'/api/datasets/{self.dataset["id"]}/control-runs/{run["id"]}/rows/5').json()
        self.assertEqual(next(x for x in unknown if x["rule_code"] == "RN19")["result"], "no_concluyente")
        self.assertEqual(next(x for x in unknown if x["rule_code"] == "RN13")["result"], "no_evaluado")
        self.assertNotIn("Paciente Ficticio", json.dumps(run))

    def test_stale_version_denied_and_decimal_threshold(self):
        conn = connect(self.root)
        with self.assertRaises(Problem) as stale:
            run_controls(conn, self.digest, self.dataset["id"], self.batch, self.dataset["version"] - 1)
        self.assertEqual(stale.exception.status, 409)
        self.assertEqual(conn.execute("SELECT count(*) FROM control_runs").fetchone()[0], 0)
        conn.close()
        fictional = {"import_id": "ficticio", "source_row": 9, "disposition": "included",
                     "practice_date": "2026-08-15", "permitted_json": json.dumps({"E": "660001"}),
                     "honorarios_ars": "0.00", "derechos_ars": "0.00", "total_ars": "0.00"}
        result = {x[0]: x for x in evaluate_row(fictional, duplicate_refs=[],
                  invoice_sha256="a" * 64, value_cut="BASE_2026-10-09")}
        self.assertEqual(result["RN16"][1], "sin_observaciones")
        fictional.update(honorarios_ars="0.02", total_ars="0.00")
        result = {x[0]: x for x in evaluate_row(fictional, duplicate_refs=[],
                  invoice_sha256="a" * 64, value_cut="BASE_2026-10-09")}
        self.assertEqual(result["RN13"][1], "con_indicios")
        self.assertEqual(Decimal(result["RN13"][4]), Decimal("0.02"))

    def test_v3_requires_coherent_backup_before_current_schema(self):
        with TemporaryDirectory(dir=".tmp") as folder:
            root = Path(folder)
            conn = connect(root)
            self.assertEqual(migrate(conn, migrations=MIGRATIONS[:3]), 3)
            with self.assertRaisesRegex(RuntimeError, "backup-and-upgrade"):
                migrate(conn)
            backup = backup_before_upgrade(conn, root)
            self.assertEqual(json.loads((backup / "manifest.json").read_text())["schema"], 3)
            self.assertEqual(migrate(conn, allow_existing_upgrade=True), MIGRATIONS[-1][0])
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            conn.close()

    def test_new_source_invalidates_old_capture_and_preserves_cut(self):
        conn = connect(self.root)
        first, created = run_controls(conn, self.digest, self.dataset["id"], self.batch,
                                      self.dataset["version"])
        self.assertTrue(created)
        self.dataset["version"] += 1
        content, manifest, sha = fictional_values(self.root)
        registered, _ = register_values(conn, self.root, self.digest, self.dataset["id"],
                                        self.dataset["version"], content, manifest, sha)
        self.dataset["version"] = registered["dataset_version"]
        self.assertEqual(conn.execute("SELECT freshness FROM control_runs WHERE id = ?",
                                      (first["id"],)).fetchone()[0], "requires_update")
        old = self.client.get(f'/api/datasets/{self.dataset["id"]}/control-runs/{first["id"]}').json()
        self.assertEqual(old["affected_rules"],
                         ["RN09", "RN10", "RN11", "RN14", "RN15", "RN16", "RN18"])
        old_row = self.client.get(f'/api/datasets/{self.dataset["id"]}/control-runs/{first["id"]}/rows/2').json()
        self.assertEqual(next(x for x in old_row if x["rule_code"] == "RN13")["freshness"], "current")
        self.assertEqual(next(x for x in old_row if x["rule_code"] == "RN14")["freshness"], "requires_update")
        second, created = run_controls(conn, self.digest, self.dataset["id"], self.batch,
                                       self.dataset["version"])
        self.assertTrue(created)
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual([s["cut_label"] for s in second["snapshot"]["sources"]
                          if s["kind"] == "values"], ["BASE_2026-10-09"])
        self.assertEqual(conn.execute("SELECT count(*) FROM control_runs").fetchone()[0], 2)
        conn.close()

    def test_duplicate_candidate_is_indication_only(self):
        fictional = {"import_id": "lote-ficticio", "source_row": 2,
                     "disposition": "included", "practice_date": "2026-08-15",
                     "permitted_json": json.dumps({"C": "000123/4", "B": 7, "E": "123456"}),
                     "honorarios_ars": "10.00", "derechos_ars": "20.00", "total_ars": "30.00"}
        result = {x[0]: x for x in evaluate_row(fictional,
                  duplicate_refs=[("lote-ficticio", 2), ("otro-lote", 8)],
                  invoice_sha256="a" * 64, value_cut=None)}
        self.assertEqual(result["RN17"][1], "con_indicios")
        self.assertEqual(result["RN17"][3]["other_locators"],
                         [{"import_id": "otro-lote", "locator": "Hoja1!8"}])
        self.assertIsNone(result["RN17"][4])
        self.assertEqual(result["RN18"][1], "no_evaluado")

    def test_second_import_invalidates_cross_lot_comparison(self):
        conn = connect(self.root)
        first, _ = run_controls(conn, self.digest, self.dataset["id"], self.batch,
                                self.dataset["version"])
        self.dataset["version"] += 1
        other = self.client.post(f'/api/datasets/{self.dataset["id"]}/batches',
                                 content=book([("15/08/2026", 11, 21, 32)]),
                                 headers=self.headers(**{"X-Expected-Version": str(self.dataset["version"]),
                                                         "X-Source-Filename": "otro-ficticio.xlsx",
                                                         "Content-Type": "application/octet-stream"})).json()
        self.dataset["version"] = other["dataset_version"]
        self.assertEqual(conn.execute("SELECT freshness FROM control_runs WHERE id = ?",
                                      (first["id"],)).fetchone()[0], "current")
        imported = self.client.post(f'/api/datasets/{self.dataset["id"]}/batches/{other["id"]}/invoice-import',
                                    json={"period": "2026-08", "period_confirmed": True,
                                          "expected_version": self.dataset["version"]},
                                    headers=self.headers()).json()
        self.dataset["version"] = imported["dataset_version"]
        self.assertEqual(conn.execute("SELECT freshness FROM control_runs WHERE id = ?",
                                      (first["id"],)).fetchone()[0], "requires_update")
        old = self.client.get(f'/api/datasets/{self.dataset["id"]}/control-runs/{first["id"]}').json()
        self.assertEqual(old["affected_rules"], ["RN11", "RN17"])
        second, _ = run_controls(conn, self.digest, self.dataset["id"], self.batch,
                                 self.dataset["version"])
        result = conn.execute("SELECT result, evidence_json FROM control_results WHERE run_id = ? "
                              "AND source_row = 2 AND rule_code = 'RN17'", (second["id"],)).fetchone()
        self.assertEqual(result["result"], "con_indicios")
        self.assertEqual(json.loads(result["evidence_json"])["candidate_count"], 1)
        conn.close()

    def test_analysis_prepares_without_writer_lock_and_rejects_changed_version(self):
        from app import controls
        conn = connect(self.root)
        evaluate = controls.evaluate_row
        changed = False
        def change_during_read(*args, **kwargs):
            nonlocal changed
            if not changed:
                changed = True
                other = connect(self.root, timeout=0)
                try:
                    other.execute("UPDATE datasets SET version = version + 1 WHERE id = ?",
                                  (self.dataset["id"],))
                finally:
                    other.close()
            return evaluate(*args, **kwargs)
        try:
            with patch.object(controls, "evaluate_row", side_effect=change_during_read):
                with self.assertRaises(Problem) as rejected:
                    run_controls(conn, self.digest, self.dataset["id"], self.batch, self.dataset["version"])
            self.assertEqual(rejected.exception.status, 409)
            self.assertTrue(changed)
            self.assertEqual(conn.execute("SELECT count(*) FROM control_runs").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT count(*) FROM control_results").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT count(*) FROM audit_events WHERE action='controls_completed'").fetchone()[0], 0)
        finally:
            conn.close()

    def test_analysis_rechecks_revoked_session_before_publication(self):
        conn = connect(self.root)
        def revoke_after_prepare():
            other = connect(self.root)
            try:
                other.execute("DELETE FROM sessions WHERE token_hash = ?", (self.digest,))
            finally:
                other.close()
        try:
            with self.assertRaises(Problem) as denied:
                run_controls(conn, self.digest, self.dataset["id"], self.batch,
                             self.dataset["version"], after_prepare=revoke_after_prepare)
            self.assertEqual(denied.exception.status, 401)
            self.assertEqual(conn.execute("SELECT count(*) FROM control_runs").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT count(*) FROM control_results").fetchone()[0], 0)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()

"""P05 shared-review tests use only invented patients, orders, and amounts."""

from __future__ import annotations

import json
from pathlib import Path
from tests.temp_support import TemporaryDirectory
from io import BytesIO
from zipfile import ZipFile
import unittest

from fastapi.testclient import TestClient

from app.api import create_app
from app.controls import row_results, run_controls, run_summary
from app.db import MIGRATIONS, backup_before_upgrade, connect, migrate
from app.security import create_user, token_digest
from tests.test_p02 import ORIGIN, PASSWORD, book


class P05Tests(unittest.TestCase):
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
        self.dataset = self.client.post("/api/datasets", json={"label": "Ficción P05"},
                                        headers=self.headers()).json()
        first = book([("15/08/2026", 10, 20, 30), ("16/08/2026", 11, 21, 32)])
        second = book([("15/08/2026", 12, 22, 34), ("16/08/2026", 13, 23, 36)])
        self.batch = self.import_book(first, "primero.xlsx")
        self.import_book(second, "segundo.xlsx")
        analyzed = self.client.post(self.run_url(), json={"expected_version": self.dataset["version"]},
                                    headers=self.headers())
        self.assertEqual(analyzed.status_code, 201, analyzed.text)
        self.run = analyzed.json()
        self.dataset["version"] += 1

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
        batch = staged.json()
        self.dataset["version"] = batch["dataset_version"]
        imported = self.client.post(f'/api/datasets/{self.dataset["id"]}/batches/{batch["id"]}/invoice-import',
                                    json={"period": "2026-08", "period_confirmed": True,
                                          "expected_version": self.dataset["version"]},
                                    headers=self.headers())
        self.assertEqual(imported.status_code, 201, imported.text)
        self.dataset["version"] = imported.json()["dataset_version"]
        return batch["id"]

    def run_url(self):
        return f'/api/datasets/{self.dataset["id"]}/batches/{self.batch}/control-runs'

    def alerts(self):
        response = self.client.get(f'/api/datasets/{self.dataset["id"]}/batches/{self.batch}/alerts')
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def decide(self, selected, *, state="descartada", foundation="Revisión ficticia de las dos filas.",
               evidence_note=None, dataset_version=None, revision_version=None):
        page = self.alerts()
        return self.client.post(f'/api/datasets/{self.dataset["id"]}/batches/{self.batch}/decisions',
            json={"expected_dataset_version": self.dataset["version"] if dataset_version is None else dataset_version,
                  "expected_revision_version": page["revision_version"] if revision_version is None else revision_version,
                  "items": selected, "state": state, "foundation": foundation,
                  "evidence_note": evidence_note}, headers=self.headers())

    def test_alerts_evidence_group_decision_and_history(self):
        page_html = self.client.get("/")
        self.assertEqual(page_html.status_code, 200)
        self.assertIn('id="review-panel"', page_html.text)
        page = self.alerts()
        self.assertEqual(page["total"], 2)
        self.assertEqual([(a["source_row"], a["rule_code"], a["decision"]) for a in page["items"]],
                         [(2, "RN17", "pendiente"), (3, "RN17", "pendiente")])
        detail = self.client.get(f'/api/datasets/{self.dataset["id"]}/alerts/{page["items"][0]["id"]}')
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()["evidence"]["candidate_count"], 1)
        self.assertEqual(detail.json()["invoice"]["fields"]["E"], "123456")
        selected = [{"id": a["id"], "expected_version": a["version"]} for a in page["items"]]
        self.assertEqual(self.decide(selected, state="confirmada").status_code, 422)
        confirmed = self.decide(selected, state="confirmada",
                                evidence_note="Se cotejaron ambas filas ficticias y su misma ocasión.")
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual(len(confirmed.json()["decision_ids"]), 2)
        self.assertIsNotNone(confirmed.json()["group_id"])
        self.dataset["version"] = confirmed.json()["dataset_version"]
        page = self.alerts()
        self.assertEqual([a["decision"] for a in page["items"]], ["confirmada", "confirmada"])
        changed = self.decide([{"id": page["items"][0]["id"],
                               "expected_version": page["items"][0]["version"]}],
                              state="descartada", foundation="Unidades ficticias legítimas verificadas.")
        self.assertEqual(changed.status_code, 200, changed.text)
        self.dataset["version"] = changed.json()["dataset_version"]
        detail = self.client.get(f'/api/datasets/{self.dataset["id"]}/alerts/{page["items"][0]["id"]}').json()
        self.assertEqual(detail["decision"], "descartada")
        self.assertEqual(len(detail["history"]), 2)
        self.assertEqual(detail["history"][1]["previous_id"], detail["history"][0]["id"])
        self.assertTrue(all(x["actor"] == "owner" for x in detail["history"]))

    def test_stale_selection_is_atomic_and_viewer_denied(self):
        page = self.alerts()
        before = [{"id": a["id"], "expected_version": a["version"]} for a in page["items"]]
        changed = self.decide([before[1]])
        self.assertEqual(changed.status_code, 200, changed.text)
        self.dataset["version"] = changed.json()["dataset_version"]
        rejected = self.decide(before)
        self.assertEqual(rejected.status_code, 409, rejected.text)
        conn = connect(self.root)
        self.assertEqual(conn.execute("SELECT count(*) FROM review_decisions").fetchone()[0], 1)
        self.assertEqual(conn.execute("SELECT version FROM alerts WHERE id = ?",
                                      (before[0]["id"],)).fetchone()[0], 1)
        conn.close()
        outsider = TestClient(create_app(self.root, public_origin=ORIGIN), base_url=ORIGIN)
        with outsider:
            login = outsider.post("/api/session", json={"username": "viewer", "password": PASSWORD},
                                  headers={"Origin": ORIGIN})
            self.assertEqual(login.status_code, 200)
            self.assertEqual(outsider.get(f'/api/datasets/{self.dataset["id"]}/batches/{self.batch}/alerts').status_code,
                             403)

    def test_two_reviewers_share_history_and_stale_save_is_rejected(self):
        conn = connect(self.root)
        create_user(conn, "revisor_a", PASSWORD, "reviewer")
        create_user(conn, "revisor_b", PASSWORD, "reviewer")
        conn.close()
        for username in ("revisor_a", "revisor_b"):
            response = self.client.post(f'/api/datasets/{self.dataset["id"]}/access',
                json={"username": username, "role": "reviewer", "expected_version": self.dataset["version"]},
                headers=self.headers())
            self.assertEqual(response.status_code, 200, response.text)
            self.dataset["version"] = response.json()["version"]
        with TestClient(create_app(self.root, public_origin=ORIGIN), base_url=ORIGIN) as a, \
             TestClient(create_app(self.root, public_origin=ORIGIN), base_url=ORIGIN) as b:
            login_a = a.post("/api/session", json={"username": "revisor_a", "password": PASSWORD},
                             headers={"Origin": ORIGIN}).json()
            login_b = b.post("/api/session", json={"username": "revisor_b", "password": PASSWORD},
                             headers={"Origin": ORIGIN}).json()
            url = f'/api/datasets/{self.dataset["id"]}/batches/{self.batch}'
            seen_a = a.get(f"{url}/alerts").json()
            seen_b = b.get(f"{url}/alerts").json()
            self.assertEqual(seen_a["revision_version"], seen_b["revision_version"])
            common = {"state": "descartada", "foundation": "Cotejo ficticio compartido con fundamento."}
            first = a.post(f"{url}/decisions", json={**common,
                "expected_dataset_version": self.dataset["version"],
                "expected_revision_version": seen_a["revision_version"],
                "items": [{"id": seen_a["items"][0]["id"],
                           "expected_version": seen_a["items"][0]["version"]}]},
                headers={"Origin": ORIGIN, "X-CSRF-Token": login_a["csrf_token"]})
            self.assertEqual(first.status_code, 200, first.text)
            stale = b.post(f"{url}/decisions", json={**common,
                "expected_dataset_version": self.dataset["version"],
                "expected_revision_version": seen_b["revision_version"],
                "items": [{"id": seen_b["items"][1]["id"],
                           "expected_version": seen_b["items"][1]["version"]}]},
                headers={"Origin": ORIGIN, "X-CSRF-Token": login_b["csrf_token"]})
            self.assertEqual(stale.status_code, 409, stale.text)
            refreshed = b.get(f"{url}/alerts").json()
            second = b.post(f"{url}/decisions", json={**common,
                "expected_dataset_version": first.json()["dataset_version"],
                "expected_revision_version": refreshed["revision_version"],
                "items": [{"id": refreshed["items"][1]["id"],
                           "expected_version": refreshed["items"][1]["version"]}]},
                headers={"Origin": ORIGIN, "X-CSRF-Token": login_b["csrf_token"]})
            self.assertEqual(second.status_code, 200, second.text)
            detail_a = a.get(f'/api/datasets/{self.dataset["id"]}/alerts/{seen_a["items"][0]["id"]}').json()
            detail_b = b.get(f'/api/datasets/{self.dataset["id"]}/alerts/{seen_b["items"][1]["id"]}').json()
            self.assertEqual(detail_a["history"][0]["actor"], "revisor_a")
            self.assertEqual(detail_b["history"][0]["actor"], "revisor_b")

    def test_work_change_marks_only_dependencies_and_reuses_unaffected_decision(self):
        page = self.alerts()
        selected = [{"id": a["id"], "expected_version": a["version"]} for a in page["items"]]
        decided = self.decide(selected)
        self.assertEqual(decided.status_code, 200, decided.text)
        self.dataset["version"] = decided.json()["dataset_version"]
        page = self.alerts()
        changed = self.client.post(f'/api/datasets/{self.dataset["id"]}/batches/{self.batch}/rows/2/work-fields',
            json={"expected_dataset_version": self.dataset["version"],
                  "expected_revision_version": page["revision_version"],
                  "field": "E", "value": "999999", "reason": "Código ficticio corregido tras cotejo."},
            headers=self.headers())
        self.assertEqual(changed.status_code, 200, changed.text)
        self.dataset["version"] = changed.json()["dataset_version"]
        conn = connect(self.root)
        summary = run_summary(conn, self.digest, self.dataset["id"], self.run["id"])
        self.assertIn("RN17", summary["affected_rules"])
        current = {r["rule_code"]: r for r in row_results(conn, self.digest, self.dataset["id"],
                                                            self.run["id"], 2)}
        self.assertEqual(current["RN13"]["freshness"], "current")
        self.assertEqual(current["RN17"]["freshness"], "requires_update")
        original = conn.execute("SELECT permitted_json FROM invoice_rows WHERE source_row = 2 "
                                "AND import_id = (SELECT id FROM invoice_imports WHERE batch_id = ?)",
                                (self.batch,)).fetchone()[0]
        self.assertEqual(json.loads(original)["E"], "123456")
        self.assertEqual(conn.execute("SELECT count(*) FROM work_changes").fetchone()[0], 1)
        conn.close()
        history = self.client.get(f'/api/datasets/{self.dataset["id"]}/batches/{self.batch}/rows/2/work-fields').json()
        self.assertEqual(history[0]["new"], "999999")
        self.assertEqual(self.alerts()["items"][0]["decision"], "pendiente")
        independent = self.alerts()["items"][1]
        self.assertEqual((independent["freshness"], independent["decision"]), ("current", "descartada"))
        connect_for_read = connect(self.root)
        try:
            independent_results = row_results(connect_for_read, self.digest, self.dataset["id"], self.run["id"], 3)
        finally:
            connect_for_read.close()
        self.assertEqual(next(r for r in independent_results if r["rule_code"] == "RN17")["freshness"], "current")
        export = self.client.get(f'/api/datasets/{self.dataset["id"]}/batches/{self.batch}/export-provisional')
        self.assertEqual(export.status_code, 200, export.text)
        with ZipFile(BytesIO(export.content)) as archive:
            exported = [json.loads(line) for line in archive.read("rows.jsonl").splitlines()]
        self.assertEqual(exported[1]["alerts"][0]["decision"], "descartada")
        self.assertEqual(exported[1]["alerts"][0]["freshness"], "current")
        analyzed = self.client.post(self.run_url(), json={"expected_version": self.dataset["version"]},
                                    headers=self.headers())
        self.assertEqual(analyzed.status_code, 201, analyzed.text)
        self.dataset["version"] += 1
        page = self.alerts()
        self.assertEqual(page["items"][0]["current_result"], "sin_observaciones")
        self.assertEqual(page["items"][0]["decision"], "pendiente")
        self.assertEqual(page["items"][1]["current_result"], "con_indicios")
        self.assertEqual(page["items"][1]["decision"], "descartada")
        detail = self.client.get(f'/api/datasets/{self.dataset["id"]}/alerts/{page["items"][1]["id"]}').json()
        self.assertEqual(len(detail["reuses"]), 1)
        self.assertEqual(len(detail["history"]), 1)

    def test_rn17_invalidates_old_and_new_groups_across_imports_only(self):
        from app.review import change_work_field, decide_alerts, list_alerts
        batch_a = self.import_book(book([("17/08/2026", 10, 20, 30)] * 3), "grupos-a.xlsx")
        batch_b = self.import_book(book([("17/08/2026", 11, 20, 31)] * 3), "grupos-b.xlsx")
        conn = connect(self.root)
        try:
            for batch in (batch_a, batch_b):
                run_controls(conn, self.digest, self.dataset["id"], batch, self.dataset["version"])
                self.dataset["version"] += 1
            page = list_alerts(conn, self.digest, self.dataset["id"], batch_a)
            decision = decide_alerts(conn, self.digest, self.dataset["id"], batch_a,
                self.dataset["version"], page["revision_version"],
                [{"id": a["id"], "expected_version": a["version"]} for a in page["items"]],
                "descartada", "Tres grupos ficticios revisados independientemente.", None)
            self.dataset["version"] = decision["dataset_version"]
            changed = change_work_field(conn, self.digest, self.dataset["id"], batch_a, 2,
                "B", "3", "Cambio ficticio que une el primer grupo con el segundo.",
                self.dataset["version"], decision["revision_version"])
            self.dataset["version"] = changed["dataset_version"]
            page = list_alerts(conn, self.digest, self.dataset["id"], batch_a)
            self.assertEqual([a["freshness"] for a in page["items"]],
                             ["requires_update", "requires_update", "current"])
            self.assertEqual(page["items"][2]["decision"], "descartada")
            peers = list_alerts(conn, self.digest, self.dataset["id"], batch_b)
            self.assertEqual([a["freshness"] for a in peers["items"]],
                             ["requires_update", "requires_update", "current"])
            changed_again = change_work_field(conn, self.digest, self.dataset["id"], batch_a, 2,
                "B", "999", "Segundo cambio ficticio que deja independiente el segundo grupo.",
                self.dataset["version"], page["revision_version"])
            self.dataset["version"] = changed_again["dataset_version"]
            page = list_alerts(conn, self.digest, self.dataset["id"], batch_a)
            self.assertEqual([a["freshness"] for a in page["items"]],
                             ["requires_update", "current", "current"])
            self.assertEqual(page["items"][1]["decision"], "descartada")
        finally:
            conn.close()

    def test_v4_requires_backup_before_v5(self):
        with TemporaryDirectory(dir=".tmp") as folder:
            root = Path(folder)
            conn = connect(root)
            self.assertEqual(migrate(conn, migrations=MIGRATIONS[:4]), 4)
            with self.assertRaisesRegex(RuntimeError, "backup-and-upgrade"):
                migrate(conn)
            backup = backup_before_upgrade(conn, root)
            self.assertEqual(json.loads((backup / "manifest.json").read_text())["schema"], 4)
            self.assertEqual(migrate(conn, allow_existing_upgrade=True), MIGRATIONS[-1][0])
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            conn.close()


if __name__ == "__main__":
    unittest.main()

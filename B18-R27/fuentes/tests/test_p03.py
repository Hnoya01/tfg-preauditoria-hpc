"""P03 source and candidate tests use a fictional SQLite catalog only."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
from tests.temp_support import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient

from app.api import create_app
from app.authorization_proposal import synthetic_candidates
from app.db import MIGRATIONS, backup_before_upgrade, connect, migrate
from app.security import create_user, issue_session, token_digest
from app.service import Problem, create_dataset
from app.storage import inventory
from app.values_v1 import candidate_values, list_sources, register_values, validate_values


PASSWORD = "Frase ficticia para pruebas 2026"
TABLES = (
    "budget_records", "custom_practices", "hpc_catalog_codes", "hpc_catalog_components",
    "hpc_catalog_documents", "hpc_catalog_history", "hpc_catalog_practices",
    "hpc_catalog_providers", "hpc_catalog_tariffs", "hpc_migration_manifest",
    "practice_links", "reference_proposals", "reference_reviews", "tariff_batch_documents",
    "tariff_unit_changes", "tariff_update_batches", "tariff_update_lines", "trial_changes",
    "uploaded_documents",
)


def fictional_values(folder: Path, calculation=None):
    path = folder / "catalogo_ficticio.sqlite"
    conn = sqlite3.connect(path)
    for table in TABLES:
        if table == "hpc_catalog_codes":
            conn.execute("CREATE TABLE hpc_catalog_codes(seq INTEGER, practice_seq INTEGER, practice_id TEXT, "
                         "code_seq INTEGER, provider TEXT, code TEXT, kind TEXT, description TEXT)")
        elif table == "hpc_catalog_tariffs":
            conn.execute("CREATE TABLE hpc_catalog_tariffs(seq INTEGER, id TEXT, provider TEXT, code TEXT, "
                         "practice_id TEXT, amount_cents INTEGER, valid_from TEXT, valid_until TEXT, "
                         "source_id TEXT, page INTEGER, data_json TEXT)")
        elif table == "hpc_catalog_providers":
            conn.execute("CREATE TABLE hpc_catalog_providers(seq INTEGER, id TEXT, name TEXT)")
        elif table == "hpc_migration_manifest":
            conn.execute("CREATE TABLE hpc_migration_manifest(source_project_id TEXT, source_commit TEXT, "
                         "source_version INTEGER, source_captured_at TEXT)")
        else:
            conn.execute(f'CREATE TABLE "{table}"(id TEXT)')
    conn.executemany("INSERT INTO hpc_catalog_providers VALUES (?, ?, ?)",
                     [(1, "P1", "Prestador Ficticio 1"), (2, "P2", "Prestador Ficticio 2")])
    conn.executemany("INSERT INTO hpc_catalog_codes VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     [(1, 11, "practice-1", 1, "P1", "123456", "HPC", "Ficticio"),
                      (2, 12, "practice-2", 1, "P1", "123456", "HPC", "Ficticio repetido"),
                      (3, 13, "practice-3", 1, "P2", "123456", "HPC", "Otro prestador")])
    for seq, provider, amount in [(1, "P1", 12345), (2, "P1", 23456), (3, "P2", 34567)]:
        data = {"conditions": "Revisar unidad", "notes": "No aplicar automáticamente"}
        if calculation:
            data['calculation'] = {**calculation, 'rateCents': amount}
        conn.execute("INSERT INTO hpc_catalog_tariffs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (seq, f"tariff-{seq}", provider, "123456", None, amount,
                      "2026-07-01", None, "documento-ficticio", 1, json.dumps(data)))
    conn.execute("INSERT INTO hpc_migration_manifest VALUES (?, ?, ?, ?)",
                 ("proyecto-ficticio", "commit-ficticio", 26, "2026-10-09T14:49:29.225Z"))
    conn.commit()
    counts = {table: conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0] for table in TABLES}
    conn.close()
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    manifest = {
        "format_version": 1,
        "source": {"catalog_captured_at": "2026-10-09T14:49:29.225Z",
                   "source_version": 26, "source_project_id": "proyecto-ficticio",
                   "source_commit": "commit-ficticio", "platform_current_database_exported": False},
        "counts": counts,
        "files": {"valores_convenios_base_2026-10-09.sqlite":
                  {"sha256": digest, "bytes": len(content)}},
    }
    return content, json.dumps(manifest).encode(), digest


class P03Tests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(dir=".tmp")
        self.root = Path(self.temp.name)
        self.conn = connect(self.root)
        migrate(self.conn)
        user_id = create_user(self.conn, "owner", PASSWORD, "admin")
        token, _ = issue_session(self.conn, user_id)
        self.raw_token = token
        self.digest = token_digest(token)
        self.dataset = create_dataset(self.conn, self.digest, "Ficción P03")
        self.content, self.manifest, self.sha = fictional_values(self.root)

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def register(self, expected=None, after_publish=None):
        return register_values(self.conn, self.root, self.digest, self.dataset["id"],
                               expected or self.dataset["version"], self.content,
                               self.manifest, self.sha, after_publish=after_publish)

    def test_versioned_values_pending_a1_and_exact_ambiguous_candidates(self):
        result, created = self.register()
        self.assertTrue(created)
        self.assertEqual(result["cut_label"], "BASE_2026-10-09")
        self.dataset["version"] = result["dataset_version"]
        sources = list_sources(self.conn, self.digest, self.dataset["id"])
        self.assertEqual({(item["kind"], item["status"]) for item in sources},
                         {("values", "registered"), ("authorizations", "pending")})
        pending = next(item for item in sources if item["kind"] == "authorizations")
        self.assertIsNone(pending["source_sha256"])
        self.assertEqual(pending["coverage"]["scope"], "unknown")
        value_id = result["id"]
        found = candidate_values(self.conn, self.root, self.digest, self.dataset["id"],
                                 value_id, "123456", "2026-08-10", None)
        self.assertEqual(found["code_total"], 3)
        self.assertEqual(found["tariff_total"], 3)
        self.assertEqual([item["seq"] for item in found["tariff_candidates"]], [1, 2, 3])
        self.assertEqual(found["tariff_candidates"][0]["amount_cents"], 12345)
        self.assertEqual(found["tariff_candidates"][0]["temporal_relation"], "no_declared_end")
        self.assertEqual(found["applicability"], "not_determined")
        self.assertEqual(found["currency"], "unverified")
        exact = candidate_values(self.conn, self.root, self.digest, self.dataset["id"],
                                 value_id, "123456", "2026-08-10", "P1")
        self.assertEqual(exact["tariff_total"], 2)
        wrong = candidate_values(self.conn, self.root, self.digest, self.dataset["id"],
                                 value_id, "12345", "2026-08-10", None)
        self.assertEqual(wrong["tariff_total"], 0)
        repeat, created = self.register()
        self.assertFalse(created)
        self.assertEqual(repeat["id"], value_id)
        changed_manifest = json.loads(self.manifest)
        changed_manifest["note"] = "Manifiesto ficticio revisado"
        with self.assertRaises(Problem) as changed:
            register_values(self.conn, self.root, self.digest, self.dataset["id"],
                            self.dataset["version"], self.content,
                            json.dumps(changed_manifest).encode(), self.sha)
        self.assertEqual(changed.exception.status, 409)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM source_registry").fetchone()[0], 2)
        registered = {row[0] for row in self.conn.execute("SELECT sha256 FROM stored_files")}
        self.assertEqual(inventory(self.root, registered)["missing_objects"], 0)

    def test_manifest_mismatch_stale_and_revoked_commit(self):
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            validate_values(self.content, self.manifest, "0" * 64)
        changed = json.loads(self.manifest)
        changed["source"]["platform_current_database_exported"] = True
        with self.assertRaisesRegex(ValueError, "Procedencia"):
            validate_values(self.content, json.dumps(changed).encode(), self.sha)
        with self.assertRaises(Problem) as stale:
            self.register(expected=self.dataset["version"] + 1)
        self.assertEqual(stale.exception.status, 409)
        def revoke():
            other = connect(self.root)
            other.execute("DELETE FROM sessions WHERE token_hash = ?", (self.digest,))
            other.close()
        with self.assertRaises(Problem) as denied:
            self.register(after_publish=revoke)
        self.assertEqual(denied.exception.status, 401)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM source_registry").fetchone()[0], 0)

    def test_authenticated_source_api_keeps_cut_and_candidates_separate(self):
        registered, _ = self.register()
        app = create_app(self.root, public_origin="https://testserver")
        with TestClient(app, base_url="https://testserver") as client:
            endpoint = f'/api/datasets/{self.dataset["id"]}/sources'
            self.assertEqual(client.get(endpoint).status_code, 401)
            client.cookies.set("tfg_session", self.raw_token)
            sources = client.get(endpoint)
            self.assertEqual(sources.status_code, 200, sources.text)
            self.assertEqual({item["kind"] for item in sources.json()}, {"authorizations", "values"})
            response = client.get(f'{endpoint}/{registered["id"]}/value-candidates',
                                  params={"code": "123456", "performed_on": "2026-08-10"})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["cut_label"], "BASE_2026-10-09")
            self.assertEqual(response.json()["applicability"], "not_determined")

    def test_v2_backup_then_v3_and_synthetic_auth_ambiguity(self):
        with TemporaryDirectory(dir=".tmp") as folder:
            root = Path(folder)
            conn = connect(root)
            self.assertEqual(migrate(conn, migrations=MIGRATIONS[:2]), 2)
            with self.assertRaisesRegex(RuntimeError, "backup-and-upgrade"):
                migrate(conn)
            backup = backup_before_upgrade(conn, root)
            self.assertEqual(json.loads((backup / "manifest.json").read_text())["schema"], 2)
            self.assertEqual(migrate(conn, allow_existing_upgrade=True), MIGRATIONS[-1][0])
            conn.close()
        capture = {"schema": "proposed-A1-v0", "orders": [
            {"order_id": "O1", "affiliate_id": "0001/2", "name": "Ficticio",
             "global_status": "AUTORIZADO", "items": [
                 {"item_id": "A", "full_code": "123456"},
                 {"item_id": "B", "full_code": "123456"},
                 {"item_id": "C", "full_code": "1234567"}]},
            {"order_id": "O2", "affiliate_id": "9999/9", "name": "Ficticio",
             "items": [{"item_id": "D", "full_code": "123456"}]},
        ]}
        matches = synthetic_candidates({"affiliate_id": "0001/2", "full_code": "123456"}, capture)
        self.assertEqual(matches["state"], "ambiguous")
        self.assertEqual([x["item_id"] for x in matches["candidates"]], ["A", "B"])
        self.assertEqual(matches["authorization_result"], "not_evaluated")
        self.assertEqual(synthetic_candidates({"affiliate_id": "0001/2", "full_code": "12345"}, capture)["state"],
                         "no_candidate_unproven")
        self.assertEqual(synthetic_candidates({"affiliate_id": "", "full_code": "123456"}, capture)["state"],
                         "identity_or_code_unresolved")


if __name__ == "__main__":
    unittest.main()

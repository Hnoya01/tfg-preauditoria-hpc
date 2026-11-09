"""P01 acceptance tests with entirely fictional accounts and file bytes."""

from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3
from tests.temp_support import TemporaryDirectory
from tests.resource_support import ConnectionTracker
import unittest

from fastapi.testclient import TestClient

from app.api import create_app
from app.db import MIGRATIONS, connect, migrate
from app.security import create_user, token_digest, validate_password
from app.service import create_batch
from app.storage import inventory


ORIGIN = "https://testserver"
PASSWORD = "Frase ficticia para pruebas 2026"
SOURCE = b"FICTIONAL-XLSX-SOURCE-FOR-P01\n"


class P01Tests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(dir=".tmp")
        self.root = Path(self.temp.name)
        self.resources = ConnectionTracker(self.root);self.resources.start()
        self.addCleanup(self.resources.stop)
        self.managers = []
        conn = connect(self.root)
        migrate(conn)
        for username, role in (("owner", "admin"), ("reviewer", "reviewer"),
                               ("viewer", "viewer"), ("outsider", "viewer")):
            create_user(conn, username, PASSWORD, role)
        conn.close()
        self.app = create_app(self.root, public_origin=ORIGIN)
        self.clients = []
        self.login_responses = {}

    def tearDown(self):
        self.resources.report(self.id(),'before_shutdown',self.managers)
        errors=[]
        for client in reversed(self.clients):
            try:client.__exit__(None, None, None)
            except Exception as error:errors.append(error)
        state=self.resources.report(self.id(),'before_cleanup',self.managers,errors[0] if errors else None)
        if errors:raise errors[0]
        self.assertEqual(state['unclosed_connections'],[],state)
        self.assertFalse(any(m['coordinator_alive'] or m['worker_alive'] for m in state['managers']),state)
        try:self.temp.cleanup()
        except OSError as error:
            self.resources.report(self.id(),'cleanup_error',self.managers,error)
            raise

    def client(self):
        client = TestClient(self.app, base_url=ORIGIN)
        client.__enter__()
        self.clients.append(client)
        manager=self.app.state.processing_manager
        if manager is not None:self.managers.append(manager)
        return client

    def login(self, username):
        client = self.client()
        response = client.post("/api/session", json={"username": username, "password": PASSWORD},
                               headers={"Origin": ORIGIN})
        self.assertEqual(response.status_code, 200, response.text)
        self.login_responses[username] = response
        return client, response.json()["csrf_token"]

    def write_headers(self, csrf, **other):
        return {"Origin": ORIGIN, "X-CSRF-Token": csrf, **other}

    def dataset(self, client, csrf, label="Ficción 1"):
        response = client.post("/api/datasets", json={"label": label},
                               headers=self.write_headers(csrf))
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def grant(self, client, csrf, dataset, username, role):
        response = client.post(f"/api/datasets/{dataset['id']}/access",
                               json={"username": username, "role": role,
                                     "expected_version": dataset["version"]},
                               headers=self.write_headers(csrf))
        self.assertEqual(response.status_code, 200, response.text)
        dataset["version"] = response.json()["version"]

    def stage(self, client, csrf, dataset, filename, content=SOURCE, expected=None):
        return client.post(
            f"/api/datasets/{dataset['id']}/batches", content=content,
            headers=self.write_headers(csrf, **{
                "X-Expected-Version": str(dataset["version"] if expected is None else expected),
                "X-Source-Filename": filename,
                "Content-Type": "application/octet-stream",
            }),
        )

    def test_migration_is_idempotent_and_failure_rolls_back(self):
        conn = connect(self.root)
        self.assertEqual(migrate(conn), MIGRATIONS[-1][0])
        before = conn.execute("SELECT count(*) FROM users").fetchone()[0]
        self.assertEqual(before, 4)
        with self.assertRaises(sqlite3.OperationalError):
            migrate(conn, migrations=tuple((v, ()) for v in range(1, MIGRATIONS[-1][0] + 1)) + ((MIGRATIONS[-1][0] + 1, (
                "CREATE TABLE should_rollback(id INTEGER)", "INVALID SQL"
            )),), allow_existing_upgrade=True)
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], MIGRATIONS[-1][0])
        self.assertIsNone(conn.execute("SELECT name FROM sqlite_master WHERE name='should_rollback'").fetchone())
        self.assertEqual(conn.execute("SELECT count(*) FROM users").fetchone()[0], before)
        conn.close()

    def test_data_root_cannot_be_public_assets_or_sources(self):
        project = Path(__file__).resolve().parent.parent
        with self.assertRaises(ValueError):
            create_app(project / "web", public_origin=ORIGIN)
        with self.assertRaises(ValueError):
            create_app(project / "trabajo_final_auditoria_fuentes", public_origin=ORIGIN)

    def test_private_file_hash_idempotence_and_dataset_scope(self):
        admin, admin_csrf = self.login("owner")
        dataset = self.dataset(admin, admin_csrf)
        self.grant(admin, admin_csrf, dataset, "reviewer", "reviewer")
        self.grant(admin, admin_csrf, dataset, "viewer", "viewer")
        reviewer, reviewer_csrf = self.login("reviewer")
        viewer, _ = self.login("viewer")
        outsider, _ = self.login("outsider")

        first = self.stage(reviewer, reviewer_csrf, dataset, "primer_nombre.xlsx")
        self.assertEqual(first.status_code, 201, first.text)
        batch = first.json()
        dataset["version"] = batch["dataset_version"]
        self.assertEqual(batch["sha256"], hashlib.sha256(SOURCE).hexdigest())
        second = self.stage(reviewer, reviewer_csrf, dataset, "otro_nombre.xlsx")
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(second.json()["id"], batch["id"])
        self.assertEqual(second.json()["dataset_version"], dataset["version"])

        file_url = f"/api/datasets/{dataset['id']}/batches/{batch['id']}/file"
        self.assertEqual(reviewer.get(file_url).content, SOURCE)
        self.assertEqual(viewer.get(file_url).status_code, 403)
        self.assertEqual(outsider.get(file_url).status_code, 403)
        self.assertEqual(self.client().get(file_url).status_code, 401)
        self.assertEqual(self.client().get(f"/objects/{batch['sha256'][:2]}/{batch['sha256']}").status_code, 404)

        second_dataset = self.dataset(admin, admin_csrf, "Ficción 2")
        another = self.stage(admin, admin_csrf, second_dataset, "copia.xlsx")
        self.assertEqual(another.status_code, 201, another.text)
        self.assertNotEqual(another.json()["id"], batch["id"])
        conn = connect(self.root)
        self.assertEqual(conn.execute("SELECT count(*) FROM stored_files").fetchone()[0], 1)
        self.assertEqual(conn.execute("SELECT count(*) FROM batches").fetchone()[0], 2)
        conn.close()

    def test_stale_save_and_role_rejection_leave_current_state(self):
        admin, csrf = self.login("owner")
        dataset = self.dataset(admin, csrf)
        viewer, viewer_csrf = self.login("viewer")
        self.assertEqual(self.stage(viewer, viewer_csrf, dataset, "solo_lectura.xlsx").status_code, 403)
        first_version = dataset["version"]
        changed = admin.patch(f"/api/datasets/{dataset['id']}",
                              json={"label": "Ficción editada", "expected_version": first_version},
                              headers=self.write_headers(csrf))
        self.assertEqual(changed.status_code, 200)
        stale = admin.patch(f"/api/datasets/{dataset['id']}",
                            json={"label": "Sobrescritura", "expected_version": first_version},
                            headers=self.write_headers(csrf))
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(self.stage(admin, csrf, dataset, "obsoleto.xlsx", expected=first_version).status_code, 409)
        self.assertEqual(admin.get("/api/datasets").json()[0]["label"], "Ficción editada")
        conn = connect(self.root)
        self.assertEqual(conn.execute("SELECT count(*) FROM batches").fetchone()[0], 0)
        conn.close()

    def test_failed_commit_keeps_orphan_visible_then_safe_retry(self):
        admin, csrf = self.login("owner")
        dataset = self.dataset(admin, csrf)
        conn = connect(self.root)
        digest = token_digest(admin.cookies.get("tfg_session"))

        def fail():
            raise RuntimeError("Falla ficticia luego de publicar")

        with self.assertRaises(RuntimeError):
            create_batch(conn, self.root, digest, dataset["id"], dataset["version"],
                         "falla.xlsx", SOURCE, after_publish=fail)
        self.assertEqual(conn.execute("SELECT count(*) FROM batches").fetchone()[0], 0)
        self.assertEqual(inventory(self.root, set())["orphan_objects"], 1)
        self.assertEqual(inventory(self.root, set())["temporary_files"], 0)
        retry = self.stage(admin, csrf, dataset, "reintento.xlsx")
        self.assertEqual(retry.status_code, 201, retry.text)
        registered = {row[0] for row in conn.execute("SELECT sha256 FROM stored_files")}
        self.assertEqual(inventory(self.root, registered)["orphan_objects"], 0)
        conn.close()

    def test_permission_is_rechecked_after_file_preparation(self):
        admin, csrf = self.login("owner")
        dataset = self.dataset(admin, csrf)
        self.grant(admin, csrf, dataset, "reviewer", "reviewer")
        reviewer, _ = self.login("reviewer")
        conn = connect(self.root)
        digest = token_digest(reviewer.cookies.get("tfg_session"))

        def revoke():
            other = connect(self.root)
            other.execute("DELETE FROM dataset_access WHERE dataset_id = ? AND user_id = "
                          "(SELECT id FROM users WHERE username = 'reviewer')", (dataset["id"],))
            other.close()

        from app.service import Problem
        with self.assertRaises(Problem) as rejected:
            create_batch(conn, self.root, digest, dataset["id"], dataset["version"],
                         "revocado.xlsx", SOURCE, after_publish=revoke)
        self.assertEqual(rejected.exception.status, 403)
        self.assertEqual(conn.execute("SELECT count(*) FROM batches").fetchone()[0], 0)
        conn.close()

    def test_cookie_csrf_origin_lockout_and_idle_expiry(self):
        admin, csrf = self.login("owner")
        self.assertEqual(admin.get("/").status_code, 200)
        self.assertEqual(admin.get("/assets/app.js").status_code, 200)
        cookie_header = self.login_responses["owner"].headers["set-cookie"].lower()
        self.assertIn("httponly", cookie_header)
        self.assertIn("secure", cookie_header)
        self.assertIn("samesite=lax", cookie_header)
        self.assertEqual(admin.post("/api/datasets", json={"label": "Sin CSRF"},
                                    headers={"Origin": ORIGIN}).status_code, 403)
        self.assertEqual(admin.post("/api/datasets", json={"label": "Origen ajeno"},
                                    headers={"Origin": "https://evil.invalid", "X-CSRF-Token": csrf}).status_code, 403)
        self.assertEqual(admin.get("/api/me").status_code, 200)
        self.assertEqual(admin.get("/api/me").headers["cache-control"], "no-store")
        conn = connect(self.root)
        conn.execute("UPDATE sessions SET last_active_at = '2000-01-01T00:00:00+00:00'")
        conn.close()
        self.assertEqual(admin.get("/api/me").status_code, 401)

        second, _ = self.login("owner")
        conn = connect(self.root)
        conn.execute("UPDATE sessions SET expires_at = '2000-01-01T00:00:00+00:00'")
        conn.close()
        self.assertEqual(second.get("/api/me").status_code, 401)

        bad = self.client()
        for _ in range(5):
            self.assertEqual(bad.post("/api/session", json={"username": "owner", "password": "incorrecta"},
                                      headers={"Origin": ORIGIN}).status_code, 401)
        self.assertEqual(bad.post("/api/session", json={"username": "owner", "password": PASSWORD},
                                  headers={"Origin": ORIGIN}).status_code, 429)

    def test_password_policy_and_permission_change_revoke_session(self):
        with self.assertRaises(ValueError):
            validate_password("short")
        with self.assertRaises(ValueError):
            validate_password("password123456789")
        conn = connect(self.root)
        stored = conn.execute("SELECT password_hash FROM users WHERE username = 'owner'").fetchone()[0]
        self.assertTrue(stored.startswith("$argon2id$"))
        conn.close()

        admin, csrf = self.login("owner")
        dataset = self.dataset(admin, csrf)
        viewer, _ = self.login("viewer")
        self.assertEqual(viewer.get("/api/me").status_code, 200)
        self.grant(admin, csrf, dataset, "viewer", "viewer")
        self.assertEqual(viewer.get("/api/me").status_code, 401)

    def test_restart_recovers_state_without_repeating_batch(self):
        admin, csrf = self.login("owner")
        dataset = self.dataset(admin, csrf)
        staged = self.stage(admin, csrf, dataset, "ficticio.xlsx")
        self.assertEqual(staged.status_code, 201, staged.text)
        batch = staged.json()
        admin.__exit__(None, None, None)
        self.clients.remove(admin)

        self.app = create_app(self.root, public_origin=ORIGIN)
        again, again_csrf = self.login("owner")
        self.assertEqual(again.get(f"/api/datasets/{dataset['id']}/batches/{batch['id']}/file").content, SOURCE)
        dataset["version"] = batch["dataset_version"]
        repeat = self.stage(again, again_csrf, dataset, "renombrado.xlsx")
        self.assertEqual(repeat.status_code, 200, repeat.text)
        self.assertEqual(repeat.json()["id"], batch["id"])
        conn = connect(self.root)
        self.assertEqual(conn.execute("SELECT count(*) FROM batches").fetchone()[0], 1)
        conn.close()


if __name__ == "__main__":
    unittest.main()

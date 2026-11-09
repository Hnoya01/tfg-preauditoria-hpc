"""P02 tests create tiny fictional OOXML books without real source rows."""

from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
from tests.temp_support import TemporaryDirectory
import unittest
from xml.sax.saxutils import escape
from zipfile import ZipFile

from fastapi.testclient import TestClient

from app.api import create_app
from app.db import MIGRATIONS, backup_before_upgrade, connect, migrate
from app.invoice_x1 import HEADERS, parse_x1
from app.security import create_user


ORIGIN = "https://testserver"
PASSWORD = "Frase ficticia para pruebas 2026"


def book(rows, *, debit="", header_override=None, styled=False):
    headers = list(HEADERS)
    if header_override:
        headers[4] = header_override
    def cell(reference, value):
        if value is None:
            return ""
        if isinstance(value, (int, float)):
            return f'<c r="{reference}"><v>{value}</v></c>'
        return f'<c r="{reference}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'
    letters = [chr(65 + i) for i in range(26)] + ["AA"]
    xml_rows = ['<row r="1">' + "".join(cell(f"{letter}1", value) for letter, value in zip(letters, headers)) + '</row>']
    for index, row in enumerate(rows, start=2):
        values = {"A": 1, "B": index, "C": "000123/4", "D": "P", "E": 123456,
                  "F": row[4] if len(row) > 4 else "A", "G": 2, "H": "Paciente Ficticio", "I": row[0], "J": 999,
                  "K": "Práctica ficticia", "L": "", "M": "", "N": "", "O": row[1],
                  "P": row[2], "Q": row[3], "V": debit, "Y": "etiqueta histórica"}
        row_style = ' ht="40" customHeight="1"' if styled else ''
        xml_rows.append(f'<row r="{index}"{row_style}>' + "".join(cell(f"{key}{index}", value)
                        for key, value in values.items()) + '</row>')
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             f'<dimension ref="A1:AA{len(rows)+1}"/><sheetData>{"".join(xml_rows)}</sheetData></worksheet>')
    files = {
        '[Content_Types].xml': '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
        '_rels/.rels': '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        'xl/workbook.xml': '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Hoja1" sheetId="1" r:id="rId1"/></sheets></workbook>',
        'xl/_rels/workbook.xml.rels': '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        'xl/worksheets/sheet1.xml': sheet,
    }
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return output.getvalue()


class P02Tests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(dir=".tmp")
        self.root = Path(self.temp.name)
        conn = connect(self.root)
        migrate(conn)
        create_user(conn, "owner", PASSWORD, "admin")
        conn.close()
        self.client = TestClient(create_app(self.root, public_origin=ORIGIN), base_url=ORIGIN)
        self.client.__enter__()
        login = self.client.post('/api/session', json={"username": "owner", "password": PASSWORD},
                                 headers={"Origin": ORIGIN})
        self.csrf = login.json()["csrf_token"]
        response = self.client.post('/api/datasets', json={"label": "Ficción P02"}, headers=self.headers())
        self.dataset = response.json()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def headers(self, **other):
        return {"Origin": ORIGIN, "X-CSRF-Token": self.csrf, **other}

    def stage(self, content, name="ficticio.xlsx"):
        return self.client.post(f'/api/datasets/{self.dataset["id"]}/batches', content=content,
            headers=self.headers(**{"X-Expected-Version": str(self.dataset["version"]),
                                    "X-Source-Filename": name, "Content-Type": "application/octet-stream"}))

    def test_preview_import_exclusions_hash_and_row_amounts(self):
        source = book([("01/08/2026", 10, 20, 30), ("31/07/2026", 4, 6, 10),
                       ("sin fecha", 3, 7, 10)])
        staged = self.stage(source)
        self.assertEqual(staged.status_code, 201, staged.text)
        batch = staged.json()
        self.dataset["version"] = batch["dataset_version"]
        preview = self.client.get(f'/api/datasets/{self.dataset["id"]}/batches/{batch["id"]}/invoice-preview?period=2026-08')
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual((preview.json()["included"], preview.json()["excluded"], preview.json()["indeterminate"]), (2, 0, 1))
        self.assertEqual(preview.json()["total_ars"], "50.00")
        self.assertEqual(preview.json()["blocker_count"], 0)
        url = f'/api/datasets/{self.dataset["id"]}/batches/{batch["id"]}/invoice-import'
        body = {"period": "2026-08", "period_confirmed": False, "expected_version": self.dataset["version"]}
        self.assertEqual(self.client.post(url, json=body, headers=self.headers()).status_code, 422)
        body["period_confirmed"] = True
        imported = self.client.post(url, json=body, headers=self.headers())
        self.assertEqual(imported.status_code, 201, imported.text)
        self.dataset["version"] = imported.json()["dataset_version"]
        repeat = self.stage(source, "renombrado.xlsx")
        self.assertEqual(repeat.status_code, 200)
        self.assertEqual(repeat.json()["id"], batch["id"])
        conn = connect(self.root)
        self.assertEqual(conn.execute("SELECT count(*) FROM invoice_imports").fetchone()[0], 1)
        self.assertEqual(conn.execute("SELECT count(*) FROM revisions").fetchone()[0], 1)
        rows = conn.execute("SELECT source_row, disposition, permitted_json, total_ars "
                            "FROM invoice_rows ORDER BY source_row").fetchall()
        self.assertEqual([(r["source_row"], r["disposition"]) for r in rows],
                         [(2, "included"), (3, "included"), (4, "indeterminate")])
        self.assertEqual(rows[0]["total_ars"], "30.00")  # G=2 must not multiply row money.
        self.assertEqual(json.loads(rows[0]["permitted_json"])["E"], "123456")
        self.assertEqual(json.loads(rows[0]["permitted_json"])["B"], 2)
        self.assertNotIn("J", rows[0]["permitted_json"])
        self.assertNotIn("V", rows[0]["permitted_json"])
        conn.close()

    def test_historical_labels_do_not_change_interpretation_and_source_difference_reaches_rn13(self):
        rows = [("15/08/2026", 10, 20, 30)]
        first = parse_x1(book(rows, debit=""), "2026-08")
        second = parse_x1(book(rows, debit="999", styled=True), "2026-08")
        self.assertEqual(first.summary, second.summary)
        self.assertEqual(first.rows, second.rows)
        wrong = book([("15/08/2026", 10, 20, 31)])
        staged = self.stage(wrong).json()
        self.dataset["version"] = staged["dataset_version"]
        preview = self.client.get(f'/api/datasets/{self.dataset["id"]}/batches/{staged["id"]}/invoice-preview?period=2026-08').json()
        self.assertTrue(preview["can_confirm"])
        self.assertEqual(preview["blocker_locators"], [])
        self.assertEqual(preview["source_arithmetic_difference_count"], 1)
        result = self.client.post(f'/api/datasets/{self.dataset["id"]}/batches/{staged["id"]}/invoice-import',
            json={"period": "2026-08", "period_confirmed": True, "expected_version": self.dataset["version"]},
            headers=self.headers())
        self.assertEqual(result.status_code, 201, result.text)
        self.dataset["version"] = result.json()["dataset_version"]
        analyzed = self.client.post(f'/api/datasets/{self.dataset["id"]}/batches/{staged["id"]}/control-runs',
            json={"expected_version": self.dataset["version"]}, headers=self.headers())
        self.assertEqual(analyzed.status_code, 201, analyzed.text)
        conn = connect(self.root)
        original = conn.execute("SELECT honorarios_ars, derechos_ars, total_ars, amount_check FROM invoice_rows").fetchone()
        self.assertEqual(tuple(original), ("10.00", "20.00", "31.00", "difference_exceeds_tolerance"))
        finding = conn.execute("SELECT result, difference_ars, currency FROM control_results "
                               "WHERE run_id = ? AND rule_code = 'RN13'", (analyzed.json()["id"],)).fetchone()
        self.assertEqual(tuple(finding), ("con_indicios", "-1.00", "ARS"))
        self.assertEqual(conn.execute("SELECT count(*) FROM review_decisions").fetchone()[0], 0)
        conn.close()
        with self.assertRaisesRegex(ValueError, "Encabezados"):
            parse_x1(book(rows, header_override="Otro código"), "2026-08")

    def test_stale_version_and_postparse_revocation_roll_back(self):
        from app.service import Problem, confirm_invoice
        from app.security import token_digest
        staged = self.stage(book([("15/08/2026", 1, 2, 3)])).json()
        self.dataset["version"] = staged["dataset_version"]
        conn = connect(self.root)
        digest = token_digest(self.client.cookies.get("tfg_session"))
        with self.assertRaises(Problem) as stale:
            confirm_invoice(conn, self.root, digest, self.dataset["id"], staged["id"], "2026-08", 1)
        self.assertEqual(stale.exception.status, 409)
        def revoke():
            other = connect(self.root)
            other.execute("DELETE FROM sessions WHERE token_hash = ?", (digest,))
            other.close()
        with self.assertRaises(Problem) as denied:
            confirm_invoice(conn, self.root, digest, self.dataset["id"], staged["id"],
                            "2026-08", self.dataset["version"], after_parse=revoke)
        self.assertEqual(denied.exception.status, 401)
        self.assertEqual(conn.execute("SELECT count(*) FROM invoice_imports").fetchone()[0], 0)
        conn.close()

    def test_backup_is_required_and_restorable_before_existing_upgrade(self):
        with TemporaryDirectory(dir=".tmp") as folder:
            root = Path(folder)
            conn = connect(root)
            migrate(conn, migrations=MIGRATIONS[:1])
            with self.assertRaisesRegex(RuntimeError, "backup-and-upgrade"):
                migrate(conn)
            backup = backup_before_upgrade(conn, root)
            self.assertTrue((backup / "app.sqlite3").is_file())
            self.assertEqual(json.loads((backup / "manifest.json").read_text())["schema"], 1)
            self.assertEqual(migrate(conn, allow_existing_upgrade=True), MIGRATIONS[-1][0])
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], MIGRATIONS[-1][0])
            conn.close()
            restored = connect(backup)
            self.assertEqual(restored.execute("PRAGMA user_version").fetchone()[0], 1)
            restored.close()

    def test_v9_row_table_rebuild_preserves_referenced_history_and_foreign_keys(self):
        import sqlite3
        from app.controls import run_controls
        from app.review import change_work_field, decide_alerts, list_alerts
        from app.security import issue_session, token_digest
        from app.service import confirm_invoice, create_batch, create_dataset
        with TemporaryDirectory(dir=".tmp") as folder:
            root = Path(folder)
            conn = connect(root)
            try:
                migrate(conn, migrations=MIGRATIONS[:8])
                user_id = create_user(conn, "owner", PASSWORD, "admin")
                token, _ = issue_session(conn, user_id)
                digest = token_digest(token)
                dataset = create_dataset(conn, digest, "Migración ficticia con historia")
                version, first_batch = dataset["version"], None
                for number in (1, 2):
                    batch, _ = create_batch(conn, root, digest, dataset["id"], version,
                                             f"ficticio-{number}.xlsx",
                                             book([("15/08/2026", number, 20, number + 20)]))
                    imported, _ = confirm_invoice(conn, root, digest, dataset["id"], batch["id"],
                                                   "2026-08", batch["dataset_version"])
                    version = imported["dataset_version"]
                    first_batch = first_batch or batch["id"]
                # Seed stored v8 history directly: the current evaluator requires
                # the new durable-history schema. Keep this migration's input at
                # v8 and retain every preservation/FK/rollback assertion below.
                from app.controls import _snapshot, _json, RULE_VERSION
                from app.review import materialize_alerts
                import hashlib
                invoice = conn.execute("SELECT i.*, b.source_sha256 FROM invoice_imports i "
                                       "JOIN batches b ON b.id=i.batch_id WHERE b.id=?", (first_batch,)).fetchone()
                capture = _json(_snapshot(conn, dataset['id'], invoice))
                conn.execute("INSERT INTO control_runs VALUES(?,?,?,?,?,?,'completed','current',?,?)",
                             ('legacy-run', dataset['id'], invoice['revision_id'], invoice['id'],
                              hashlib.sha256(capture.encode()).hexdigest(), capture, user_id, '2026-08-16'))
                conn.execute("INSERT INTO control_results VALUES(?,?,?,?,?,?,?,?,?,?)",
                             ('legacy-run', invoice['id'], 2, 'RN17', RULE_VERSION, 'con_indicios',
                              'synthetic_legacy_duplicate', '{}', None, None))
                materialize_alerts(conn, 'legacy-run')
                conn.execute('UPDATE datasets SET version=version+1 WHERE id=?', (dataset['id'],))
                conn.execute('UPDATE revisions SET version=version+1 WHERE id=?', (invoice['revision_id'],))
                version += 1
                page = list_alerts(conn, digest, dataset["id"], first_batch)
                alert = page["items"][0]
                decided = decide_alerts(conn, digest, dataset["id"], first_batch, version,
                    page["revision_version"], [{"id": alert["id"], "expected_version": alert["version"]}],
                    "descartada", "Decisión ficticia anterior a la migración.", None)
                change_work_field(conn, digest, dataset["id"], first_batch, 2, "E", "999999",
                    "Corrección ficticia anterior a la migración.", decided["dataset_version"],
                    decided["revision_version"])
                tables = ("invoice_rows", "control_results", "alerts", "review_decisions", "work_changes", "work_fields")
                before = {table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY {'1,2,3' if table == 'work_fields' else 'rowid'}")]
                          for table in tables}
                backup_before_upgrade(conn, root)
                broken = MIGRATIONS[:8] + ((9, MIGRATIONS[8][1] + ("INVALID SQL",)),)
                with self.assertRaises(sqlite3.OperationalError):
                    migrate(conn, migrations=broken, allow_existing_upgrade=True)
                self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 8)
                self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
                self.assertEqual([tuple(row) for row in conn.execute("SELECT * FROM invoice_rows ORDER BY rowid")],
                                 before["invoice_rows"])
                migrate(conn, allow_existing_upgrade=True)
                for table in tables:
                    self.assertEqual([tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY {'1,2,3' if table == 'work_fields' else 'rowid'}")],
                                     before[table], table)
                self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
                self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
                self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()

"""RN27/RN28/MD10: component freshness with fictional references only."""

from __future__ import annotations

from io import BytesIO
import json
import unittest
from unittest.mock import patch
from uuid import uuid4
from zipfile import ZipFile

from app.db import connect
from app.proposals import save_verified_proposal, withdraw_economic_verification
from app.security import create_user, issue_session, now_utc, token_digest
from app.service import Problem
from app.storage import object_path, publish_bytes
from tests import test_proposal_persistence as fixture
from tests.test_p02 import PASSWORD


class ComponentFreshnessTests(unittest.TestCase):
    INVOICE_TOTAL = 400
    SOURCE_DIFFERENCE = 1
    tearDown = fixture.ProposalPersistenceTests.tearDown
    headers = fixture.ProposalPersistenceTests.headers
    import_book = fixture.ProposalPersistenceTests.import_book
    spec = fixture.ProposalPersistenceTests.spec

    def setUp(self):
        fixture.ProposalPersistenceTests.setUp(self)
        page = self.client.get(f'{self.base()}/alerts').json()
        alert = next(a for a in page["items"] if a["rule_code"] == "RN13")
        response = self.client.post(f'{self.base()}/decisions', json={
            "expected_dataset_version": self.dataset["version"],
            "expected_revision_version": page["revision_version"],
            "items": [{"id": alert["id"], "expected_version": alert["version"]}],
            "state": "confirmada", "foundation": "Discrepancia ficticia cotejada para otra unidad.",
            "evidence_note": "Se verificaron los importes originales ficticios de la fila."}, headers=self.headers())
        self.assertEqual(response.status_code, 200, response.text)
        self.second_decision_id = response.json()["decision_ids"][0]
        self.dataset["version"] = response.json()["dataset_version"]
        self.revision_version = response.json()["revision_version"]
        self.second_verification_id = str(uuid4())
        conn = connect(self.root)
        try:
            conn.execute("INSERT INTO economic_verifications SELECT ?, dataset_id, source_id, source_sha256, "
                         "evidence_sha256, evidence_locator, tariff_locator, provider, code_complete, currency, "
                         "economic_unit, rate_ars, valid_from, verified_through, applicability_note, "
                         "verified_by, verified_at, active FROM economic_verifications WHERE id = ?",
                         (self.second_verification_id, self.verification_id))
        finally:
            conn.close()

    def base(self, batch=None):
        return f'/api/datasets/{self.dataset["id"]}/batches/{batch or self.batch}'

    def parts(self):
        return (self.spec(billed_scope_ars="200.00"),
                self.spec(decision_id=self.second_decision_id, verification_id=self.second_verification_id,
                          unit_start="1", unit_end="2", billed_scope_ars="200.00"))

    def save_parts(self, parts=None):
        conn = connect(self.root)
        try:
            saved = save_verified_proposal(conn, self.root, self.digest, self.dataset["id"],
                self.batch, 2, self.dataset["version"], self.revision_version,
                self.parts() if parts is None else parts)
        finally:
            conn.close()
        self.dataset["version"], self.revision_version = saved["dataset_version"], saved["revision_version"]
        return saved

    def history(self):
        response = self.client.get(f'{self.base()}/rows/2/proposals')
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def export(self):
        response = self.client.get(f'{self.base()}/export-provisional')
        self.assertEqual(response.status_code, 200, response.text)
        with ZipFile(BytesIO(response.content)) as archive:
            return (json.loads(archive.read("manifest.json")),
                    [json.loads(line) for line in archive.read("rows.jsonl").splitlines()],
                    [json.loads(line) for line in archive.read("proposal_versions.jsonl").splitlines()])

    def withdraw(self, verification_id):
        conn = connect(self.root)
        try:
            result = withdraw_economic_verification(conn, self.digest, self.dataset["id"],
                verification_id, self.dataset["version"], "Retiro ficticio documentado de esta referencia.")
            self.dataset["version"] = result["dataset_version"]
        finally:
            conn.close()

    def change_work(self, field, value, batch=None):
        base = self.base(batch)
        version = self.client.get(f'{base}/provider-scope').json()["revision_version"]
        response = self.client.post(f'{base}/rows/2/work-fields', json={
            "expected_dataset_version": self.dataset["version"], "expected_revision_version": version,
            "field": field, "value": value, "reason": "Cambio ficticio para verificar dependencias económicas."},
            headers=self.headers())
        self.assertEqual(response.status_code, 200, response.text)
        self.dataset["version"] = response.json()["dataset_version"]
        if batch is None:
            self.revision_version = response.json()["revision_version"]

    def test_declaring_invoice_fictional_excludes_previously_supported_amounts(self):
        from app.authorization_imports import stage_authorization,preview_authorization,confirm_authorization
        from app.authorization_matching import save_scope
        from scripts.create_b02_demo import capture
        self.save_parts()
        self.assertIsNotNone(self.history()['current_proposal'])
        conn=connect(self.root)
        try:
            upload,_=stage_authorization(conn,self.root,self.digest,self.dataset['id'],self.dataset['version'],
                'AUTORIZACIONES_FICTICIAS.json',json.dumps(capture()).encode())
            p=preview_authorization(conn,self.root,self.digest,self.dataset['id'],upload['id'])
            c,_=confirm_authorization(conn,self.root,self.digest,self.dataset['id'],upload['id'],p['dataset_version'],p['preview_sha256'],'Captura enteramente ficticia para ensayo de bloqueo monetario.')
            save_scope(conn,self.root,self.digest,self.dataset['id'],self.batch,c['dataset_version'],[c['id']],
                'synthetic_demo','Se declara expresamente que este Excel es ficticio.',True)
        finally:conn.close()
        h=self.history()
        self.assertIsNone(h['current_proposal'])
        for part in h['latest_evaluation']['components']:
            self.assertIn('synthetic_batch_not_monetary_evidence',part['invalid_reasons'])
        manifest,_,_=self.export()
        self.assertIsNone(manifest['current_proposal_total_ars'])

    def test_withdrawal_excludes_only_one_component_and_export_matches(self):
        saved = self.save_parts()
        self.assertEqual(saved["amount_ars"], "153.10")
        original_payload = self.history()["versions"][0]["payload_at_save"]
        self.withdraw(self.verification_id)
        history = self.history()
        current = history["current_proposal"]
        self.assertEqual((current["state"], current["amount_ars"], current["affected_amount_ars_at_save"]),
                         ("partially_current", "76.55", "76.55"))
        self.assertEqual([c["current_amount_ars"] for c in current["components"]], [None, "76.55"])
        self.assertIn("economic_reference_withdrawn_or_missing", current["components"][0]["invalid_reasons"])
        self.assertEqual(history["versions"][0]["payload_at_save"], original_payload)
        manifest, rows, versions = self.export()
        self.assertEqual(manifest["current_proposal_total_ars"], "76.55")
        self.assertEqual(manifest["monetary_status"], "partially_current")
        self.assertEqual(rows[0]["proposed_amount_ars"], "76.55")
        self.assertEqual(versions[0]["payload_at_save"]["amount_ars"], "153.10")
        # A withdrawal is permanent for this record, even if an out-of-band
        # database edit changes active back to one.
        conn = connect(self.root)
        conn.execute("UPDATE economic_verifications SET active = 1 WHERE id = ?", (self.verification_id,))
        conn.close()
        self.assertEqual(self.history()["current_proposal"]["amount_ars"], "76.55")
        with self.assertRaises(Problem) as retired:
            self.save_parts()
        self.assertEqual(retired.exception.status, 409)

    def test_manual_adjustment_survives_independent_withdrawal_with_automatic_basis(self):
        first, second = self.parts()
        second = {**second, "adjusted_ars": "80.00", "adjustment_calculation": "200 - 120 = 80",
                  "adjustment_reason": "Ajuste ficticio documentado para la segunda unidad."}
        self.save_parts((first, second))
        self.withdraw(self.verification_id)
        current = self.history()["current_proposal"]
        self.assertEqual(current["amount_ars"], "80.00")
        self.assertEqual(current["components"][1]["automatic_amount_ars"], "76.55")
        self.assertEqual(current["components"][1]["adjustment_calculation"], "200 - 120 = 80")
        self.assertEqual(self.export()[0]["current_proposal_total_ars"], "80.00")

    def test_withdrawal_checks_permission_and_version_without_partial_change(self):
        conn = connect(self.root)
        try:
            user_id = create_user(conn, "reader", PASSWORD, "viewer")
            token, _ = issue_session(conn, user_id)
            with self.assertRaises(Problem) as denied:
                withdraw_economic_verification(conn, token_digest(token), self.dataset["id"],
                    self.verification_id, self.dataset["version"], "Motivo ficticio de retiro de referencia.")
            self.assertEqual(denied.exception.status, 403)
            with self.assertRaises(Problem) as stale:
                withdraw_economic_verification(conn, self.digest, self.dataset["id"], self.verification_id,
                    self.dataset["version"] - 1, "Motivo ficticio de retiro de referencia.")
            self.assertEqual(stale.exception.status, 409)
            self.assertEqual(conn.execute("SELECT count(*) FROM economic_verification_withdrawals").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT active FROM economic_verifications WHERE id = ?",
                                           (self.verification_id,)).fetchone()[0], 1)
        finally:
            conn.close()

    def test_replacing_one_decision_preserves_other_component(self):
        self.save_parts()
        page = self.client.get(f'{self.base()}/alerts').json()
        alert = next(a for a in page["items"] if a["rule_code"] == "RN17")
        response = self.client.post(f'{self.base()}/decisions', json={
            "expected_dataset_version": self.dataset["version"], "expected_revision_version": self.revision_version,
            "items": [{"id": alert["id"], "expected_version": alert["version"]}],
            "state": "descartada", "foundation": "Nueva revisión ficticia descarta únicamente este hallazgo."},
            headers=self.headers())
        self.assertEqual(response.status_code, 200, response.text)
        current = self.history()["current_proposal"]
        self.assertEqual(current["amount_ars"], "76.55")
        self.assertIn("decision_not_current_confirmed", current["components"][0]["invalid_reasons"])
        self.assertEqual(current["components"][1]["invalid_reasons"], [])

    def test_peer_identity_change_affects_rn17_component_only_before_reanalysis(self):
        self.save_parts()
        self.change_work("E", "999999", self.other_batch)
        current = self.history()["current_proposal"]
        self.assertEqual(current["amount_ars"], "76.55")
        self.assertIn("finding_dependencies_changed", current["components"][0]["invalid_reasons"])
        self.assertEqual(current["components"][1]["invalid_reasons"], [])

    def test_shared_quantity_change_leaves_all_amounts_unknown_even_after_reanalysis(self):
        self.save_parts()
        self.change_work("G", "3")
        self.assertIsNone(self.history()["current_proposal"])
        self.assertTrue(all("shared_row_basis_changed" in c["invalid_reasons"]
                            for c in self.history()["latest_evaluation"]["components"]))
        analyzed = self.client.post(f'{self.base()}/control-runs', json={"expected_version": self.dataset["version"]},
                                    headers=self.headers())
        self.assertEqual(analyzed.status_code, 201, analyzed.text)
        self.assertIsNone(self.history()["current_proposal"])
        self.assertIsNone(self.export()[0]["current_proposal_total_ars"])

    def test_unrelated_change_and_explicit_analysis_preserve_same_proposal(self):
        saved = self.save_parts()
        self.change_work("K", "Descripción ficticia independiente", self.other_batch)
        self.assertEqual(self.history()["current_proposal"]["amount_ars"], "153.10")
        analyzed = self.client.post(f'{self.base()}/control-runs', json={"expected_version": self.dataset["version"]},
                                    headers=self.headers())
        self.assertEqual(analyzed.status_code, 201, analyzed.text)
        history = self.history()
        self.assertEqual(history["current_proposal"]["proposal_id"], saved["id"])
        self.assertEqual(history["current_proposal"]["amount_ars"], "153.10")
        self.assertEqual(len(history["versions"]), 1)

    def test_reference_record_change_is_scoped_and_source_context_change_is_shared(self):
        self.save_parts()
        conn = connect(self.root)
        conn.execute("UPDATE economic_verifications SET applicability_note = 'Nueva interpretación ficticia.' WHERE id = ?",
                     (self.verification_id,))
        conn.close()
        current = self.history()["current_proposal"]
        self.assertEqual(current["amount_ars"], "76.55")
        self.assertIn("economic_verification_changed", current["components"][0]["invalid_reasons"])
        conn = connect(self.root)
        conn.execute("UPDATE source_registry SET metadata_json = ? WHERE id = ?", ('{"version":"changed"}', self.source["id"]))
        conn.close()
        history = self.history()
        self.assertIsNone(history["current_proposal"])
        self.assertIn("value_source_selection_changed", history["latest_evaluation"]["invalid_reasons"])

    def test_latest_version_never_falls_back_to_an_older_valid_part(self):
        first = self.save_parts()
        second = self.save_parts((self.parts()[1],))
        self.withdraw(self.second_verification_id)
        history = self.history()
        self.assertIsNone(history["current_proposal"])
        self.assertEqual(history["latest_evaluation"]["proposal_id"], second["id"])
        self.assertEqual([version["id"] for version in history["versions"]], [first["id"], second["id"]])
        self.assertIsNone(self.export()[0]["current_proposal_total_ars"])

    def test_legacy_basis_does_not_activate_a_known_historical_amount(self):
        saved = self.save_parts()
        conn = connect(self.root)
        try:
            payload = json.loads(conn.execute("SELECT payload_json FROM proposal_versions WHERE id = ?", (saved["id"],)).fetchone()[0])
            payload.pop("basis")
            payload.pop("format_version")
            conn.execute("INSERT INTO proposal_versions SELECT ?, revision_id, import_id, source_row, 2, id, "
                         "run_id, provider_scope_at_save, work_basis_json, amount_ars, currency, ?, actor_id, created_at "
                         "FROM proposal_versions WHERE id = ?", (str(uuid4()), json.dumps(payload), saved["id"]))
        finally:
            conn.close()
        history = self.history()
        self.assertIsNone(history["current_proposal"])
        self.assertIn("saved_dependency_basis_missing", history["latest_evaluation"]["invalid_reasons"])
        self.assertIsNone(self.export()[0]["current_proposal_total_ars"])

    def test_zero_is_current_only_while_supported_and_never_replaces_unknown(self):
        self.save_parts((self.spec(billed_scope_ars="100.00"),))
        self.assertEqual(self.history()["current_proposal"]["amount_ars"], "0.00")
        self.assertEqual(self.export()[0]["current_proposal_total_ars"], "0.00")
        self.withdraw(self.verification_id)
        history = self.history()
        self.assertIsNone(history["current_proposal"])
        self.assertEqual(history["latest_evaluation"]["affected_amount_ars_at_save"], "0.00")
        self.assertIsNone(self.export()[0]["current_proposal_total_ars"])

    def test_missing_original_excludes_only_its_reference(self):
        sha, size, path = publish_bytes(self.root, b"%PDF-1.4\nOtro original ficticio\n")
        conn = connect(self.root)
        try:
            actor_id = conn.execute("SELECT id FROM users WHERE username='owner'").fetchone()[0]
            conn.execute("INSERT INTO stored_files VALUES (?, ?, ?, ?)", (sha, size, path, now_utc()))
            conn.execute("INSERT INTO evidence_documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (str(uuid4()), self.dataset["id"], self.source["id"], sha, "otro-ficticio.pdf", "agreement",
                 "no_catalog_hash", "Otro original ficticio para esta referencia.", actor_id, now_utc()))
            conn.execute("UPDATE economic_verifications SET evidence_sha256 = ? WHERE id = ?", (sha, self.second_verification_id))
        finally:
            conn.close()
        self.save_parts()
        object_path(self.root, sha).unlink()
        current = self.history()["current_proposal"]
        self.assertEqual(current["amount_ars"], "76.55")
        self.assertIn("reference_original_unavailable_or_changed", current["components"][1]["invalid_reasons"])

    def test_withdrawal_during_export_rejects_stale_package(self):
        from app import provisional
        self.save_parts()
        original = provisional._write_lines
        def concurrent_withdrawal(archive, name, records):
            original(archive, name, records)
            if name == "rows.jsonl":
                self.withdraw(self.verification_id)
        with patch.object(provisional, "_write_lines", side_effect=concurrent_withdrawal):
            response = self.client.get(f'{self.base()}/export-provisional')
        self.assertEqual(response.status_code, 409, response.text)
        conn = connect(self.root)
        try:
            self.assertEqual(conn.execute("SELECT count(*) FROM audit_events WHERE action='provisional_exported'").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT count(*) FROM proposal_versions").fetchone()[0], 1)
        finally:
            conn.close()

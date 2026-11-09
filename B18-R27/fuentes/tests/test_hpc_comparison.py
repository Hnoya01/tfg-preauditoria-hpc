"""HPC candidate comparisons use fictional invoices and a fictional catalog."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import unittest

from fastapi.testclient import TestClient

from app.api import create_app
from app.db import connect
from app.hpc_comparison import _compare
from app.reference_readiness import DOCUMENT_LINKS, REAL_V1_SHA, assess_reference_item
from app.values_v1 import register_values
from tests import test_p05 as fixture
from tests.test_p03 import fictional_values
from tests.test_p02 import ORIGIN, PASSWORD


class HpcComparisonTests(unittest.TestCase):
    setUp = fixture.P05Tests.setUp
    tearDown = fixture.P05Tests.tearDown
    headers = fixture.P05Tests.headers
    import_book = fixture.P05Tests.import_book
    run_url = fixture.P05Tests.run_url

    def register_fictional_hpc(self, calculation_extra=None):
        _, manifest_bytes, _ = fictional_values(self.root)
        path = self.root / "catalogo_ficticio.sqlite"
        source = sqlite3.connect(path)
        source.execute("UPDATE hpc_catalog_providers SET id = 'HPC' WHERE id = 'P1'")
        source.execute("UPDATE hpc_catalog_codes SET provider = 'HPC' WHERE provider = 'P1'")
        source.execute("DELETE FROM hpc_catalog_tariffs WHERE seq = 2")
        calculation = {"kind": "nbu", "ubMilliunits": 1000, "rateCents": 1500,
                       "formula": "U.B. por tarifa de unidad", "reviewRequired": False}
        calculation.update(calculation_extra or {})
        raw = {"conditions": "Una práctica por unidad; adicionales no incluidos",
               "calculation": calculation}
        source.execute("UPDATE hpc_catalog_tariffs SET provider = 'HPC', amount_cents = 1500, "
                       "valid_from = '2026-06-01', data_json = ? WHERE seq = 1",
                       (json.dumps(raw),))
        source.commit()
        counts = {row[0]: source.execute(f'SELECT count(*) FROM "{row[0]}"').fetchone()[0]
                  for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        source.close()
        content = path.read_bytes()
        sha = hashlib.sha256(content).hexdigest()
        manifest = json.loads(manifest_bytes)
        manifest["counts"] = counts
        manifest["files"]["valores_convenios_base_2026-10-09.sqlite"] = {
            "sha256": sha, "bytes": len(content)}
        conn = connect(self.root)
        try:
            result, created = register_values(
                conn, self.root, self.digest, self.dataset["id"], self.dataset["version"],
                content, json.dumps(manifest).encode(), sha)
        finally:
            conn.close()
        self.assertTrue(created)
        self.dataset["version"] = result["dataset_version"]
        return result["id"]

    def endpoint(self, source_id, **params):
        return self.client.get(
            f'/api/datasets/{self.dataset["id"]}/batches/{self.batch}/hpc-comparison',
            params={"source_id": source_id, **params})

    def test_exact_hpc_formula_and_invoice_total_are_exploratory(self):
        source_id = self.register_fictional_hpc()
        response = self.endpoint(source_id, status="differences")
        self.assertEqual(response.status_code, 200, response.text)
        report = response.json()
        self.assertEqual(report["value_cut"], "BASE_2026-10-09")
        self.assertEqual(report["provider"], "HPC")
        self.assertEqual(report["counts"]["numeric_equal"], 1)
        self.assertEqual(report["counts"]["numeric_above_candidate"], 1)
        self.assertEqual(report["selected_total"], 1)
        item = report["items"][0]
        self.assertEqual(item["source_row"], 3)
        self.assertEqual(item["billed_total_ars"], "32.00")
        self.assertEqual(item["candidate_total_if_ars_and_same_unit"], "30.00")
        self.assertEqual(item["difference_ars_if_comparable"], "2.00")
        self.assertEqual(item["tariff"]["source_locator"], "hpc_catalog_tariffs.seq=1")
        self.assertEqual(item["assessment"], "exploratory_not_rn14_or_debit")
        self.assertEqual(item["currency_compatibility"], "unverified")
        self.assertEqual(self.endpoint(source_id, source_row=2).json()["items"][0]["status"],
                         "numeric_equal")
        self.assertEqual(self.endpoint(source_id, status="differences", offset=1).json()["items"], [])
        self.assertEqual(self.endpoint("missing").status_code, 404)

    def test_readiness_api_keeps_all_unverified_dimensions_unquantified(self):
        source_id = self.register_fictional_hpc()
        response = self.client.get(
            f'/api/datasets/{self.dataset["id"]}/batches/{self.batch}/reference-readiness',
            params={"source_id": source_id, "source_row": 3})
        self.assertEqual(response.status_code, 200, response.text)
        report = response.json()
        self.assertEqual(report["value_cut"], "BASE_2026-10-09")
        self.assertEqual(report["monetary_state"], "unquantified")
        item = report["items"][0]
        self.assertEqual(item["comparison_status"], "numeric_above_candidate")
        self.assertEqual(item["checks"]["catalogue_formula"]["status"], "reproduced")
        self.assertFalse(item["ready_for_amount"])
        self.assertIsNone(item["proposal_amount_ars"])
        self.assertIn("billing_unit_not_verified_for_row", item["blocked_dimensions"])
        self.assertIn("end_or_supersession_not_verified", item["blocked_dimensions"])
        self.assertIn("conditions_not_verified_for_row", item["blocked_dimensions"])
        conn = connect(self.root)
        self.assertEqual(conn.execute("SELECT count(*) FROM proposal_versions").fetchone()[0], 0)
        conn.close()

    def test_document_alias_is_explicitly_limited_to_real_v1_cut(self):
        source_id = self.register_fictional_hpc()
        item = self.endpoint(source_id, source_row=3).json()["items"][0]
        item["source_sha256"] = REAL_V1_SHA
        item["tariff"]["calculation"].update({
            "rateSource": "IF-2026-82616470-APN-DCS_IOSFA-1.pdf", "ratePage": 1,
            "catalogueSource": "Anexo-11.2023-NBU-2012-16-Final.pdf", "cataloguePage": 3})
        documents = [
            {"id": "agreement", "sha256": DOCUMENT_LINKS["IF-2026-82616470-APN-DCS_IOSFA-1.pdf"],
             "original_name": "IF-2026-82616470-APN-DCS_IOSFA-1.pdf",
             "category": "agreement",
             "source_match": "catalog_hash_match"},
            {"id": "annex", "sha256": DOCUMENT_LINKS["Anexo-11.2023-NBU-2012-16-Final.pdf"],
             "original_name": "Anexo-Noviembre-2023-de-Practicas-normas-e-interpretaciones.pdf",
             "category": "nomenclator",
             "source_match": "no_catalog_hash"},
        ]
        assessed = assess_reference_item(item, documents=documents,
                                         scope={"provider": "HPC", "billing_unit": "unverified"},
                                         decision_state="sin_confirmacion_vigente")
        self.assertEqual(assessed["checks"]["rate_document"]["link_basis"], "catalog_hash")
        self.assertEqual(assessed["checks"]["factor_document"]["link_basis"],
                         "edition_alias_reviewed")
        self.assertFalse(assessed["ready_for_amount"])
        self.assertIn("factor_page_cotejo_not_recorded_per_code", assessed["blocked_dimensions"])

    def test_work_change_changes_candidate_without_reanalysis(self):
        source_id = self.register_fictional_hpc()
        page = self.client.get(
            f'/api/datasets/{self.dataset["id"]}/batches/{self.batch}/alerts').json()
        changed = self.client.post(
            f'/api/datasets/{self.dataset["id"]}/batches/{self.batch}/rows/2/work-fields',
            json={"expected_dataset_version": self.dataset["version"],
                  "expected_revision_version": page["revision_version"],
                  "field": "E", "value": "999999",
                  "reason": "Código ficticio corregido tras cotejo."},
            headers=self.headers())
        self.assertEqual(changed.status_code, 200, changed.text)
        report = self.endpoint(source_id, source_row=2).json()
        self.assertEqual(report["items"][0]["status"], "no_exact_hpc_tariff")
        self.assertEqual(report["items"][0]["work_change_ids"]["E"],
                         changed.json()["change_id"])

    def test_viewer_cannot_read_comparison(self):
        source_id = self.register_fictional_hpc()
        with TestClient(create_app(self.root, public_origin=ORIGIN), base_url=ORIGIN) as viewer:
            login = viewer.post("/api/session", json={"username": "viewer", "password": PASSWORD},
                                headers={"Origin": ORIGIN})
            self.assertEqual(login.status_code, 200)
            response = viewer.get(
                f'/api/datasets/{self.dataset["id"]}/batches/{self.batch}/hpc-comparison',
                params={"source_id": source_id})
            self.assertEqual(response.status_code, 403)

    def test_invalid_basis_and_quantity_never_create_numeric_difference(self):
        source = {"id": "ficticio", "source_sha256": "a" * 64,
                  "cut_label": "BASE_2026-10-09"}
        row = {"source_row": 2, "disposition": "included", "practice_date": "2026-08-10",
               "total_ars": "10.00"}
        tariff = {"source_locator": "hpc_catalog_tariffs.seq=1", "amount_cents": 1000,
                  "valid_from": "2026-06-01", "valid_until": None,
                  "calculation": {"kind": "nbu", "ubMilliunits": 1000, "rateCents": 1000}}
        def status(fields, candidates):
            return _compare(row, fields, {}, candidates, source, "Hoja1")["status"]
        self.assertEqual(status({"E": "123456", "G": 1}, {"123456": [tariff]}),
                         "numeric_equal")
        for invalid in ('S/D', '1000', 1000.0, None, -1):
            result = _compare(row, {'E':'123456','G':1}, {}, {'123456':[{**tariff,'amount_cents':invalid}]}, source, 'Hoja1')
            self.assertEqual(result['status'],'catalogue_amount_not_interpretable')
            self.assertIsNone(result['difference_ars_if_comparable'])

        self.assertEqual(status({"E": "123456", "G": 0}, {"123456": [tariff]}),
                         "invalid_quantity")
        self.assertEqual(status({"E": "123456", "G": "9" * 65}, {"123456": [tariff]}),
                         "invalid_quantity")
        self.assertEqual(status({"E": "123456", "G": 0.5}, {"123456": [tariff]}),
                         "numeric_above_candidate")
        self.assertEqual(status({"E": "123456", "G": 0.0005}, {"123456": [tariff]}),
                         "fractional_cent_needs_rounding_rule")
        self.assertEqual(status({"E": "123456", "G": 1}, {"123456": [tariff, tariff]}),
                         "ambiguous_hpc_tariff")
        self.assertEqual(status({"E": "123456", "G": 1}, {"123456": [
            {**tariff, "amount_cents": 999}]}), "inconsistent_formula")
        self.assertEqual(status({"E": "123456", "G": 1}, {"123456": [
            {**tariff, "valid_from": "2026-09-01"}]}), "outside_declared_dates")
        self.assertEqual(status({"E": "123456", "G": 1}, {"123456": [
            {**tariff, "calculation": {**tariff["calculation"],
                                       "reviewRequired": True}}]}), "tariff_requires_review")


class HpcDateSelectionTests(unittest.TestCase):
    def test_date_selection_precedes_ambiguity_and_keeps_boundaries(self):
        row = {'source_row': 2, 'disposition': 'included', 'practice_date': '2026-08-10', 'total_ars': '10.00'}
        source = {'id': 'synthetic', 'source_sha256': 'a' * 64, 'cut_label': 'BASE_2026-10-09'}
        tariff = {'source_locator': 'current', 'amount_cents': 1000, 'valid_from': '2026-08-01',
                  'valid_until': None, 'calculation': {'kind': 'nbu', 'ubMilliunits': 1000, 'rateCents': 1000}}
        historical = {**tariff, 'source_locator': 'old', 'valid_from': '2026-06-01', 'valid_until': '2026-07-31'}
        future = {**tariff, 'source_locator': 'future', 'valid_from': '2026-09-01'}
        def compare(date, tariffs):
            return _compare({**row, 'practice_date': date}, {'E': '123456', 'G': 1}, {},
                            {'123456': tariffs}, source, 'Hoja1')
        for date in ('2026-08-01', '2026-08-10', '2026-08-31'):
            result = compare(date, [historical, tariff, future])
            self.assertEqual(result['status'], 'numeric_equal')
            self.assertEqual(result['tariff']['source_locator'], 'current')
        self.assertEqual(compare('2026-07-31', [historical, tariff])['tariff']['source_locator'], 'old')
        self.assertEqual(compare('2026-09-01', [tariff, future])['status'], 'ambiguous_hpc_tariff')
        for date in (None, '2026-05-01'):
            result = compare(date, [historical, tariff, future])
            self.assertEqual(result['status'], 'undetermined_declared_dates' if date is None else 'outside_declared_dates')
            self.assertIsNone(result['difference_ars_if_comparable'])
        self.assertEqual(compare('2026-08-10', [{**tariff, 'valid_from': None}])['status'], 'undetermined_declared_dates')


if __name__ == "__main__":
    unittest.main()

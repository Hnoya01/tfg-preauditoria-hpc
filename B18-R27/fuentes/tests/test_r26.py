"""Billing month end is independent of authorization, import date and statement date."""
import unittest
from uuid import uuid4

from app.controls import run_controls
from app.eligibility import LATE_REASON, billing_window, classify
from app.invoice_x1 import practice_date_iso
from app.practice_board import practice_search
from app.row_decisions import detail, save
from tests import test_r23, test_r24


class BillingDates(unittest.TestCase):
    def test_month_ends_and_inclusive_limit(self):
        for period, service, days in [
            ("2026-08", "2026-07-17", 45), ("2026-08", "2026-07-16", 46),
            ("2026-08", "2026-08-31", 0), ("2026-09", "2026-08-16", 45),
            ("2026-01", "2025-12-17", 45), ("2024-02", "2024-01-15", 45),
            ("2026-02", "2026-01-14", 45),
        ]:
            with self.subTest(period=period, service=service):
                result = billing_window(service, period)
                self.assertEqual(result["days"], days)
                self.assertEqual(result["status"], "late" if days == 46 else "in_term")
        self.assertEqual(practice_date_iso("17/07/2026"), "2026-07-17")
        self.assertIsNone(practice_date_iso("31/02/2026"))

    def test_future_missing_date_and_inpatient(self):
        for day, kind, scope, state in [
            ("2026-09-01", "A", "excluded", "after_close"),
            (None, "A", "indeterminate", "unknown"),
            ("2026-07-16", "I", "excluded", "late"),
        ]:
            result = classify(day,kind,"2026-08")
            self.assertEqual((result["disposition"], result["billing_window"]["status"]), (scope,state))


class BillingBoard(unittest.TestCase):
    def test_august_excel_through_review_decision(self):
        fixture = test_r24.R24()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        orders = [test_r23.row(orden_hpc=order, afiliado=affiliate,
                   practicas=f"{test_r23.CSV} -- TAC ficticia x{qty},",
                   movimientos="02/07/2026 12:00 | Ficticio | AUTORIZADO | ")
                  for order,affiliate,qty in [("TAC-17","001111/1",1),("TAC-16","002222/1",2)]]
        up,_ = test_r23.stage_authorization(fixture.c,fixture.root,fixture.token,fixture.ds,
            fixture.f.version(),"FICTICIO.csv",test_r23.encode(orders))
        preview = test_r23.preview_authorization(fixture.c,fixture.root,fixture.token,fixture.ds,up["id"])
        capture,_ = test_r23.confirm_authorization(fixture.c,fixture.root,fixture.token,fixture.ds,up["id"],
            fixture.f.version(),preview["preview_sha256"],"Dos órdenes ficticias independientes.")
        fixture.cap = capture["id"]
        fixture.invoice([dict(code=test_r23.INVOICE, date="17/07/2026", affiliate="001111/1"),
                         dict(code=test_r23.INVOICE, date="16/07/2026", affiliate="002222/1", qty=2)])
        fixture.register([[test_r23.INVOICE,test_r23.CSV]])
        conn,root,token,dataset,batch = fixture.c,fixture.root,fixture.token,fixture.ds,fixture.bid
        run_controls(conn,token,dataset,batch,fixture.f.version())
        def board(view, **filters):
            return practice_search(conn,token,dataset,batch,dict(view=view,family="images",**filters),root=root)
        both = board("all")["items"]
        self.assertEqual([(r["source_row"],r["billing_window"]["days"]) for r in both],[(2,45),(3,46)])
        self.assertTrue(all(r["disposition"]=="included" for r in both))
        self.assertEqual([next(c["state"] for c in r["checks"] if c["rule"]=="RN19") for r in both],
                         ["sin_indicios","con_indicios"])
        signals = fixture.signals()
        self.assertEqual([signals[n]["status"] for n in (2,3)], ["one_unit_supported","units_supported"])
        self.assertIsNone(both[0].get("late_billing_reason"))
        self.assertFalse((both[0].get("administrative_decision") or {}).get("proposal"))
        late = board("exceptions",exception_reason=LATE_REASON)
        self.assertEqual([r["source_row"] for r in late["items"]],[3])
        info = detail(conn,root,token,dataset,batch,3)
        self.assertEqual(info["proposal"]["amount_ars"],"100000.00")
        self.assertIn("46 días",info["proposal"]["reason"])
        self.assertTrue(any("16/07/2026" in reason and "31/08/2026" in reason for reason in info["reasons"]))
        self.assertEqual(conn.execute("SELECT count(*) FROM invoice_row_decisions").fetchone()[0],0)
        save(conn,root,token,dataset,batch,3,dict(
            expected_dataset_version=info["dataset_version"],expected_revision_version=info["revision_version"],
            revision_id=info["revision_id"],evidence_hash=info["evidence_hash"],
            action="accept",request_id=str(uuid4())))
        self.assertEqual(board("exceptions",exception_reason=LATE_REASON)["filtered_total"],0)
        reviewed = board("row_reviewed")["items"]
        self.assertEqual([(r["source_row"],r["administrative_decision"]["previous"]["amount_ars"]) for r in reviewed],
                         [(3,"100000.00")])
        self.assertEqual(conn.execute("SELECT count(*) FROM audit_invoice_closures").fetchone()[0],0)

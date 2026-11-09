"""Regression cases for an incomplete CSV and a later negative resolution."""
import unittest
from decimal import Decimal
from app.authorization_matching import save_scope
from app.row_decisions import advisory_gap, authorization_shortfall
from tests.test_r24 import R24 as scenario, base


class Delivery(unittest.TestCase):
    setUp = scenario.setUp
    source_csv = scenario.source_csv
    invoice = scenario.invoice
    register = scenario.register
    signals = scenario.signals
    exposure = scenario.exposure

    def test_partial_export_is_quantified_without_an_acceptable_proposal(self):
        self.source_csv(base.CSV+' -- TAC ficticia,')
        self.invoice([dict(code=base.INVOICE,qty=2)])
        self.register([[base.INVOICE,base.CSV]])
        save_scope(self.c,self.root,self.token,self.ds,self.bid,self.f.version(),[self.cap],'real_unvalidated','Exportación parcial ficticia para el ensayo.')
        signal=self.signals()[2]
        self.assertEqual(advisory_gap(Decimal('200000'),signal)['amount_ars'],'100000.00')
        self.assertIsNone(authorization_shortfall(Decimal('200000'),signal))

    def test_coverage_for_single_additional_has_no_implicit_split(self):
        signal=self.exposure(qty=3)[3]
        self.assertEqual(advisory_gap(Decimal(3000),signal)['amount_ars'],'2000.00')
        self.assertIsNone(authorization_shortfall(Decimal(3000),signal))
        self.assertIsNone(advisory_gap(Decimal('100'),signal))
        self.assertIsNone(advisory_gap(Decimal(3000),{**signal,'billed_units':None}))

    def test_rejection_after_service_stays_pending(self):
        self.source_csv(base.CSV+' -- TAC ficticia,',movement='03/08/2026 12:00 | Operador ficticio | RECHAZADO | ')
        self.invoice([dict(code=base.INVOICE)])
        self.register([[base.INVOICE,base.CSV]])
        s=self.signals()[2]
        self.assertEqual((s['status'],s['movement'],s['authorization_date'],s['performed_on']),('later_movement','rechazo','2026-08-03','2026-08-02'))
        self.assertIsNone(authorization_shortfall(Decimal(100000),s))
        self.assertNotIn('allocations',s)

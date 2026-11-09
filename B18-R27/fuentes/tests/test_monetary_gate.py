"""Pure monetary gate checks use fictional references and amounts only."""

from dataclasses import replace
from datetime import date
from decimal import Decimal
import unittest

from app.monetary_gate import (EconomicReference, GateBlocked, ProposedComponent,
                               RowContext, consolidate_current)


SHA = "a" * 64


def context() -> RowContext:
    return RowContext(2, "HPC", "660999", date(2026, 8, 15), Decimal("2"),
                      Decimal("30.00"), Decimal("20.00"), Decimal("50.00"), "practice",
                      True, frozenset({("decision-1", "RN14"), ("decision-2", "RN14")}),
                      frozenset({("source-1", SHA)}))


def reference() -> EconomicReference:
    return EconomicReference("source-1", SHA, "FICTIONAL_CUT", "tariff:42", "HPC",
                             "660999", "ARS", "practice", Decimal("10.00"),
                             date(2026, 6, 1), date(2026, 8, 31), True,
                             "Convenio ficticio cotejado para esta fila.")


def component(*, decision="decision-1", rubric="honorarios", start="0", end="1",
              billed="15.00") -> ProposedComponent:
    return ProposedComponent(2, decision, "RN14", rubric, Decimal(start), Decimal(end),
                             Decimal(billed), reference())


class MonetaryGateTests(unittest.TestCase):
    def assert_blocked(self, code, row=None, parts=None):
        with self.assertRaises(GateBlocked) as raised:
            consolidate_current(row if row is not None else context(),
                                parts if parts is not None else (component(),))
        self.assertEqual(raised.exception.code, code)

    def test_two_independent_rubrics_and_preserved_adjustment(self):
        adjusted = replace(component(decision="decision-2", rubric="derechos", billed="12.00"),
                           adjusted_ars=Decimal("3.00"), adjustment_calculation="12 - 9 = 3",
                           adjustment_reason="Referencia ficticia específica verificada.")
        result = consolidate_current(context(), (component(), adjusted))
        self.assertEqual(result["amount_ars"], "8.00")
        self.assertEqual(result["components"][0]["automatic_amount_ars"], "5.00")
        self.assertEqual(result["components"][1]["automatic_amount_ars"], "2.00")
        self.assertEqual(result["components"][1]["amount_ars"], "3.00")
        self.assertEqual(result["components"][1]["adjustment_reason"],
                         "Referencia ficticia específica verificada.")

    def test_pending_or_stale_decision_and_source_cannot_activate(self):
        self.assert_blocked("decision_not_current_confirmed",
                            parts=(component(decision="pending"),))
        self.assert_blocked("decision_not_current_confirmed",
                            parts=(replace(component(), rule_code="RN17"),))
        self.assert_blocked("component_row_mismatch",
                            parts=(replace(component(), source_row=3),))
        self.assert_blocked("source_not_current", row=replace(context(),
                            current_sources=frozenset()))
        self.assert_blocked("row_outside_scope", row=replace(context(), included=False))

    def test_reference_date_unit_conditions_and_cent_are_required(self):
        base = component()
        self.assert_blocked("reference_date_unverified", parts=(replace(base,
                            reference=replace(reference(), verified_through=date(2026, 7, 31))),))
        self.assert_blocked("currency_or_unit_mismatch", parts=(replace(base,
                            reference=replace(reference(), economic_unit="U.B.")),))
        self.assert_blocked("reference_applicability_unverified", parts=(replace(base,
                            reference=replace(reference(), conditions_verified=False)),))
        self.assert_blocked("fractional_cent", parts=(replace(base,
                            billed_scope_ars=Decimal("15.001")),))

    def test_overlap_and_scope_are_rejected_without_partial_total(self):
        self.assert_blocked("overlapping_components", parts=(component(),
                            component(decision="decision-2", start="0.5", end="1.5")))
        self.assert_blocked("overlapping_components", parts=(component(),
                            component(decision="decision-2", rubric="total")))
        self.assert_blocked("overlapping_components", parts=(component(),
                            component(decision="decision-2", rubric="cantidad")))
        self.assert_blocked("unit_scope_invalid", parts=(component(end="3"),))

    def test_billed_allocation_cannot_reuse_more_than_original_row(self):
        self.assert_blocked("billed_allocation_exceeds_row",
                            parts=(component(billed="31.00"),))
        self.assert_blocked("billed_allocation_exceeds_row",
                            parts=(component(billed="30.00"),
                                   component(decision="decision-2", rubric="derechos",
                                             billed="21.00")))

    def test_adjustment_requires_calculation_and_foundation(self):
        self.assert_blocked("adjustment_incomplete", parts=(replace(component(),
                            adjusted_ars=Decimal("4.00")),))
        self.assert_blocked("adjustment_incomplete", parts=(replace(component(),
                            adjustment_reason="Motivo sin ajuste."),))

    def test_determined_zero_is_distinct_from_missing_proposal(self):
        result = consolidate_current(context(), (component(billed="9.00"),))
        self.assertEqual(result["amount_ars"], "0.00")
        self.assert_blocked("no_components", parts=())


if __name__ == "__main__":
    unittest.main()

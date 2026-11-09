"""Pure RN27/MD10 gate for a *current* row proposal.

The caller must build the context and references from authenticated, versioned
server records inside its write transaction. Client-supplied attestations are
not evidence. This module neither reads V1 nor writes proposals.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import re


CENT = Decimal("0.01")
RUBRICS = {"honorarios", "derechos", "total", "cantidad"}


class GateBlocked(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _decimal(value: Decimal | str, *, allow_zero: bool = True) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise GateBlocked("invalid_decimal")
    try:
        result = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        raise GateBlocked("invalid_decimal") from None
    if not result.is_finite() or result < 0 or (not allow_zero and result == 0):
        raise GateBlocked("invalid_decimal")
    return result


def _cents(value: Decimal | str) -> Decimal:
    result = _decimal(value)
    if result.quantize(CENT) != result:
        raise GateBlocked("fractional_cent")
    return result


def _money(value: Decimal) -> str:
    return format(value, ".2f")


@dataclass(frozen=True)
class RowContext:
    source_row: int
    provider: str
    code_complete: str
    performed_on: date
    billed_quantity: Decimal
    billed_honorarios_ars: Decimal
    billed_derechos_ars: Decimal
    billed_total_ars: Decimal
    billing_unit: str
    included: bool
    current_confirmed_decisions: frozenset[tuple[str, str]]  # (decision_id, rule_code) for this row
    current_sources: frozenset[tuple[str, str]]  # (source_id, SHA-256)


@dataclass(frozen=True)
class EconomicReference:
    source_id: str
    source_sha256: str
    cut_label: str
    locator: str
    provider: str
    code_complete: str
    currency: str
    economic_unit: str
    rate_ars: Decimal
    valid_from: date
    verified_through: date
    conditions_verified: bool
    applicability_note: str


@dataclass(frozen=True)
class ProposedComponent:
    source_row: int
    decision_id: str
    rule_code: str
    rubric: str
    unit_start: Decimal
    unit_end: Decimal
    billed_scope_ars: Decimal
    reference: EconomicReference
    adjusted_ars: Decimal | None = None
    adjustment_calculation: str | None = None
    adjustment_reason: str | None = None


def consolidate_current(context: RowContext,
                        components: tuple[ProposedComponent, ...]) -> dict:
    """Return a supported proposal or reject the entire set, with no partial sum.

    A service must verify the billed allocation against immutable O/P/Q and
    the documentary reference against stored evidence before calling this.
    """
    if not context.included:
        raise GateBlocked("row_outside_scope")
    if context.source_row < 2:
        raise GateBlocked("row_identity_or_unit_missing")
    quantity = _decimal(context.billed_quantity, allow_zero=False)
    billed_limits = {"honorarios": _cents(context.billed_honorarios_ars),
                     "derechos": _cents(context.billed_derechos_ars),
                     "total": _cents(context.billed_total_ars),
                     "cantidad": _cents(context.billed_total_ars)}
    if not context.provider or not context.code_complete or not context.billing_unit:
        raise GateBlocked("row_identity_or_unit_missing")
    if not components:
        raise GateBlocked("no_components")
    if len(components) > 100:
        raise GateBlocked("too_many_components")
    occupied: list[tuple[str, Decimal, Decimal]] = []
    allocated = {rubric: Decimal("0.00") for rubric in RUBRICS}
    allocated_total = Decimal("0.00")
    breakdown = []
    total = Decimal("0.00")
    for component in components:
        if component.source_row != context.source_row:
            raise GateBlocked("component_row_mismatch")
        if (component.decision_id, component.rule_code) not in context.current_confirmed_decisions:
            raise GateBlocked("decision_not_current_confirmed")
        if not re.fullmatch(r"RN\d{2}", component.rule_code):
            raise GateBlocked("rule_missing")
        if component.rubric not in RUBRICS:
            raise GateBlocked("rubric_invalid")
        start = _decimal(component.unit_start)
        end = _decimal(component.unit_end, allow_zero=False)
        if end <= start or end > quantity:
            raise GateBlocked("unit_scope_invalid")
        for rubric, previous_start, previous_end in occupied:
            if (rubric == component.rubric or rubric in {"total", "cantidad"} or
                    component.rubric in {"total", "cantidad"}) and start < previous_end and previous_start < end:
                raise GateBlocked("overlapping_components")
        occupied.append((component.rubric, start, end))

        reference = component.reference
        if (reference.source_id, reference.source_sha256) not in context.current_sources:
            raise GateBlocked("source_not_current")
        if not re.fullmatch(r"[0-9a-f]{64}", reference.source_sha256):
            raise GateBlocked("source_hash_invalid")
        if not reference.cut_label or not reference.locator:
            raise GateBlocked("reference_locator_missing")
        if reference.provider != context.provider or reference.code_complete != context.code_complete:
            raise GateBlocked("reference_scope_mismatch")
        if reference.currency != "ARS" or reference.economic_unit != context.billing_unit:
            raise GateBlocked("currency_or_unit_mismatch")
        if not reference.valid_from <= context.performed_on <= reference.verified_through:
            raise GateBlocked("reference_date_unverified")
        if not reference.conditions_verified or len(reference.applicability_note.strip()) < 10:
            raise GateBlocked("reference_applicability_unverified")
        rate = _cents(reference.rate_ars)
        allowed = rate * (end - start)
        if allowed.quantize(CENT) != allowed:
            raise GateBlocked("fractional_cent")
        billed = _cents(component.billed_scope_ars)
        allocated[component.rubric] += billed
        allocated_total += billed
        if (allocated[component.rubric] > billed_limits[component.rubric] + CENT or
                allocated_total > billed_limits["total"] + CENT):
            raise GateBlocked("billed_allocation_exceeds_row")
        automatic = max(Decimal("0.00"), billed - allowed)
        if component.adjusted_ars is None:
            if component.adjustment_calculation or component.adjustment_reason:
                raise GateBlocked("adjustment_incomplete")
            amount = automatic
        else:
            amount = _cents(component.adjusted_ars)
            if (not component.adjustment_calculation or
                    len(component.adjustment_calculation.strip()) < 3 or
                    not component.adjustment_reason or
                    len(component.adjustment_reason.strip()) < 10):
                raise GateBlocked("adjustment_incomplete")
        total += amount
        breakdown.append({
            "decision_id": component.decision_id,
            "rule_code": component.rule_code,
            "rubric": component.rubric,
            "unit_start": format(start, "f"),
            "unit_end": format(end, "f"),
            "billed_scope_ars": _money(billed),
            "allowed_scope_ars": _money(allowed),
            "automatic_amount_ars": _money(automatic),
            "amount_ars": _money(amount),
            "adjustment_calculation": component.adjustment_calculation,
            "adjustment_reason": component.adjustment_reason,
            "reference": {
                "source_id": reference.source_id,
                "source_sha256": reference.source_sha256,
                "cut_label": reference.cut_label,
                "locator": reference.locator,
                "currency": reference.currency,
                "economic_unit": reference.economic_unit,
                "provider": reference.provider,
                "code_complete": reference.code_complete,
                "rate_ars": _money(rate),
                "valid_from": reference.valid_from.isoformat(),
                "verified_through": reference.verified_through.isoformat(),
                "applicability_note": reference.applicability_note,
            },
        })
    return {"state": "current_supported_proposal", "currency": "ARS",
            "amount_ars": _money(total), "components": breakdown}

"""Fixture-only candidate finder for the proposed A1 shape, not a real adapter."""

from __future__ import annotations


def synthetic_candidates(invoice: dict, capture: dict) -> dict:
    """Return exact literal candidates without interpreting authorization decisions.

    This shape is deliberately unusable as evidence of coverage until a real A1
    sample, extraction coverage, and identity normalization are validated.
    """
    if capture.get("schema") != "proposed-A1-v0":
        raise ValueError("Solo se admite el contrato sintético propuesto")
    affiliate = invoice.get("affiliate_id")
    code = invoice.get("full_code")
    if not isinstance(affiliate, str) or not affiliate or not isinstance(code, str) or not code:
        return {"state": "identity_or_code_unresolved", "candidates": [],
                "coverage": "unvalidated", "authorization_result": "not_evaluated"}
    candidates = []
    for order_index, order in enumerate(capture.get("orders", [])):
        if order.get("affiliate_id") != affiliate:
            continue
        for item_index, item in enumerate(order.get("items", [])):
            if item.get("full_code") != code:
                continue
            candidates.append({"order_id": order.get("order_id"),
                               "item_id": item.get("item_id"),
                               "source_locator": f"orders[{order_index}].items[{item_index}]"})
    return {"state": "ambiguous" if len(candidates) > 1 else
            "candidate_only" if candidates else "no_candidate_unproven",
            "candidates": candidates, "coverage": "unvalidated",
            "authorization_result": "not_evaluated"}

"""Read-only, source-backed readiness of HPC tariff candidates for P06.

Document presence and a reproducible NBU formula are useful evidence, never
proof of the billed row's unit, contractual conditions or continued validity.
No assessment in this module creates a decision, verification or amount.
"""

from __future__ import annotations

from .revision_scope import revision_table

from collections import Counter
import re
import sqlite3
from pathlib import Path

from .controls import _run_summary
from .hpc_comparison import compare_batch
from .review import _decision_status, _latest_run
from .service import Problem, authorized_dataset
from .storage import read_verified
from .dependencies import result_affected
from .documentary_assessments import DocumentaryEvaluator, latest_assessment
from .agreement_review import general_reference, load_agreement_review


from .document_links import DOCUMENT_LINKS, REAL_V1_SHA, _document

NUMERIC_STATUSES = {"numeric_equal", "numeric_above_candidate", "numeric_below_candidate"}


def assess_reference_item(item: dict, *, documents: list[dict], scope: dict | None,
                          decision_state: str, documentary_assessment: dict | None = None,
                          agreement_review: dict | None = None) -> dict:
    """Explain each independent gate without treating unverified as false/zero."""
    blocked: list[str] = []
    tariff = item.get("tariff")
    result = {"source_row": item["source_row"], "locator": item["locator"],
              "code_complete": item["code_complete"], "comparison_status": item["status"],
              "source_id": item["source_id"], "source_sha256": item["source_sha256"],
              "value_cut": item["value_cut"], "provider": item["provider"],
              "proposal_amount_ars": None, "assessment": "documentary_readiness_only"}
    general = general_reference(item, agreement_review, documentary_assessment)
    result['general_reference'] = general
    documented_base = general['status'] in {'supported_base_reference', 'requires_case_interpretation'}
    shared_agreement = general.get('shared_agreement_supported', False)
    if item["disposition"] != "included":
        blocked.append("row_outside_scope")
    if tariff is None:
        blocked.append("no_unique_exact_tariff")
        return {**result, "checks": {}, "blocked_dimensions": blocked,
                "ready_for_amount": False}
    calculation = tariff.get("calculation") if isinstance(tariff.get("calculation"), dict) else {}
    formula_ok = item["status"] in NUMERIC_STATUSES
    if not formula_ok:
        blocked.append("catalogue_formula_or_quantity_unresolved")
    rate_document = _document(calculation.get("rateSource"), item["source_sha256"],
                              documents, "agreement")
    factor_document = _document(calculation.get("catalogueSource"), item["source_sha256"],
                                documents, "nomenclator")
    rate_document["page_from_catalogue"] = calculation.get("ratePage")
    factor_document["page_from_catalogue"] = calculation.get("cataloguePage")
    if rate_document["status"] != "registered" or rate_document.get("source_match") != "catalog_hash_match":
        blocked.append("rate_document_not_hash_matched")
    if factor_document["status"] != "registered":
        blocked.append("factor_document_not_registered")
    for document, reason in ((rate_document, 'rate_document_original_unavailable'),
                             (factor_document, 'factor_document_original_unavailable')):
        if any(doc['sha256'] == document.get('sha256') and doc.get('original_available') is False for doc in documents):
            blocked.append(reason)
    # The catalog's page and factor are locators and assertions from V1. A
    # registered PDF does not prove that every code/factor was checked visually.
    cotejo = documentary_assessment
    if cotejo is None and not documented_base:
        blocked.append("factor_page_cotejo_not_recorded_per_code")
    elif cotejo and cotejo['freshness'] != 'current':
        blocked.append('factor_page_assessment_affected')
    elif cotejo and cotejo['document_id'] != factor_document.get('document_id'):
        blocked.append('factor_page_assessment_affected')
    elif cotejo and cotejo['conclusion'] == 'differs':
        blocked.append('factor_page_discrepancy')
    elif cotejo and cotejo['conclusion'] != 'matches':
        blocked.append('factor_page_inconclusive')
    declared_dates = {"valid_from": tariff["valid_from"], "valid_until": tariff["valid_until"],
                      "practice_date": item["practice_date"],
                      "declared_relation": ("undetermined_declared_dates" if item["status"] == "undetermined_declared_dates"
                                            else "outside_declared_dates" if item["status"] == "outside_declared_dates"
                                            else "start_met_end_not_declared" if tariff["valid_until"] is None
                                            else "inside_declared_dates")}
    if item["status"] == "undetermined_declared_dates":
        blocked.append("declared_dates_not_determined")
    if item["status"] == "outside_declared_dates":
        blocked.append("practice_outside_declared_dates")
    if tariff["valid_until"] is None and not shared_agreement:
        blocked.append("end_or_supersession_not_verified")
    # Neither the symbol '$' nor quantity G establishes an ISO currency or
    # compatible economic unit for the individual billed row.
    if shared_agreement:
        if general['status'] == 'requires_case_interpretation':
            blocked.append('specific_nbu_norm_requires_case_interpretation')
    else:
        blocked.extend(("currency_not_verified_per_reference", "billing_unit_not_verified_for_row",
                        "conditions_not_verified_for_row", "specific_agreement_not_checked"))
    if agreement_review and agreement_review['freshness'] != 'current':
        blocked.append('agreement_document_review_affected')
    if decision_state != "confirmada_vigente":
        blocked.append("confirmed_current_finding_missing")
    if scope is None or scope.get("provider") != item["provider"]:
        blocked.append("provider_scope_not_confirmed")
    result["checks"] = {
        "catalogue_formula": {"status": "reproduced" if formula_ok else "unresolved",
                              "ub_milliunits_from_catalogue": calculation.get("ubMilliunits"),
                              "rate_cents_from_catalogue": calculation.get("rateCents"),
                              "tariff_locator": tariff["source_locator"]},
        "rate_document": rate_document,
        "factor_document": factor_document,
        "factor_page_cotejo": cotejo or ({'status': 'automated_pdf_crosschecked_not_human_approval',
                                          'review_id': agreement_review['id']} if documented_base else
                                         {"status": "not_recorded_per_code_in_application"}),
        "declared_dates": declared_dates,
        "currency": general['currency_basis'] if shared_agreement else "not_verified_per_reference",
        "billing_unit": 'exact_NBU_practice_base_reference' if shared_agreement else scope.get("billing_unit") if scope else "unverified",
        "conditions_from_catalogue": tariff.get("conditions"),
        "case_conditions": ('specific_nbu_norm_pending' if general['status'] == 'requires_case_interpretation' else
                            'base_tariff_no_additions' if documented_base else 'not_verified'),
        "specific_agreement": 'specific_accepted_reference_prevails_if_linked' if shared_agreement else "not_checked",
        "human_decision": decision_state,
    }
    result["blocked_dimensions"] = blocked
    result["ready_for_amount"] = False
    return result


def reference_readiness(conn: sqlite3.Connection, root: Path, token_hash: str,
                        dataset_id: str, batch_id: str, source_id: str, *,
                        status: str = "differences", offset: int = 0,
                        limit: int = 50, source_row: int | None = None) -> dict:
    comparison = compare_batch(conn, root, token_hash, dataset_id, batch_id, source_id,
                               status=status, offset=offset, limit=limit, source_row=source_row)
    authorized_dataset(conn, token_hash, dataset_id, "reviewer")
    documents = [dict(row) for row in conn.execute(
        "SELECT id, sha256, original_name, category, source_match FROM evidence_documents "
        "WHERE dataset_id = ? AND source_id = ?", (dataset_id, source_id))]
    for document in documents:
        try:
            read_verified(root, document['sha256'])
            document['original_available'] = True
        except (OSError, RuntimeError):
            document['original_available'] = False
    scope_row = conn.execute("SELECT h.provider, h.billing_unit, h.source_id FROM "
                             f"{revision_table(conn, 'batch_provider_scope_history')} h WHERE h.batch_id = ? "
                             "ORDER BY h.ordinal DESC LIMIT 1", (batch_id,)).fetchone()
    scope = dict(scope_row) if scope_row and scope_row["source_id"] == source_id else None
    batch = conn.execute(f"SELECT i.revision_id, r.version FROM {revision_table(conn, 'invoice_imports')} i "
                         "JOIN revisions r ON r.id = i.revision_id WHERE i.batch_id = ?",
                         (batch_id,)).fetchone()
    latest = _latest_run(conn, batch["revision_id"]) if batch else None
    summary = _run_summary(conn, dataset_id, latest["id"]) if latest else None
    items = []
    counts: Counter[str] = Counter()
    evaluator = DocumentaryEvaluator(conn, root, dataset_id)
    agreement_review = load_agreement_review(conn, root, dataset_id, source_id)
    general_counts: Counter[str] = Counter()
    for candidate in comparison["items"]:
        decision_state = "sin_confirmacion_vigente"
        if latest and not result_affected(summary, candidate["source_row"], "RN14"):
            alert = conn.execute("SELECT id FROM alerts WHERE revision_id = ? AND source_row = ? "
                                 "AND rule_code = 'RN14'", (batch["revision_id"],
                                                           candidate["source_row"])).fetchone()
            if alert and _decision_status(conn, alert["id"], latest["id"])[0] == "confirmada":
                decision_state = "confirmada_vigente"
        tariff = candidate.get('tariff')
        locator = re.fullmatch(r'hpc_catalog_tariffs\.seq=(\d+)', tariff['source_locator']) if tariff else None
        record = latest_assessment(conn, source_id, candidate['provider'], candidate['code_complete'],
                                   int(locator.group(1))) if locator else None
        cotejo = evaluator.evaluate(record) if record else None
        assessed = assess_reference_item(candidate, documents=documents, scope=scope,
                                         decision_state=decision_state, documentary_assessment=cotejo,
                                         agreement_review=agreement_review)
        items.append(assessed)
        counts.update(assessed["blocked_dimensions"])
        general_counts[assessed['general_reference']['status']] += 1
    _, dataset = authorized_dataset(conn, token_hash, dataset_id, "reviewer")
    current_revision = conn.execute("SELECT version FROM revisions WHERE id = ?",
                                    (batch["revision_id"],)).fetchone() if batch else None
    if (dataset["version"] != comparison["dataset_version"] or current_revision is None or
            current_revision["version"] != comparison["revision_version"]):
        raise Problem(409, "La revisión cambió durante la lectura; reintentá")
    return {"kind": "economic_reference_readiness", "source_id": source_id,
            "value_cut": comparison["value_cut"], "dataset_version": dataset["version"],
            "revision_version": comparison["revision_version"],
            "filter": comparison["filter"], "selected_total": comparison["selected_total"],
            "offset": comparison["offset"], "limit": comparison["limit"],
            "items": items, "blocked_dimension_counts_on_page": dict(counts),
            'general_reference_counts_on_page': dict(general_counts),
            "monetary_state": "unquantified", "proposal_total_ars": None,
            "note": "Lectura documental y de catálogo; ninguna ficha crea hallazgo ni importe."}

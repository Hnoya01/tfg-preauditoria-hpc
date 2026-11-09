"""Exploratory X1/HPC numerical comparison; never a control decision or debit."""

from __future__ import annotations

from .revision_scope import revision_table
from .effective_hpc_values import EffectiveHpcValues

from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
import json
import sqlite3
from pathlib import Path

from .service import Problem, authorized_dataset
from .storage import read_verified
from .values_v1 import CUT, source_db, json_safe_catalog_amount
from .eligibility import POLICY_VERSION, effective_row


CENT = Decimal("0.01")
FILTERS = {"all", "differences", "numeric_equal", "numeric_above_candidate",
           "numeric_below_candidate", "no_exact_hpc_tariff", "needs_interpretation"}


def _money(value: Decimal) -> str:
    return format(value, ".2f")


def _compare(row: sqlite3.Row, fields: dict, changes: dict,
             tariffs: dict[str, list[dict]], source: sqlite3.Row,
             sheet: str, resolver=None, billing_unit=None) -> dict:
    number = row["source_row"]
    code = str(fields.get("E") or "")
    base = {
        "source_row": number, "locator": f"{sheet}!{number}",
        "disposition": row["disposition"], "practice_date": row["practice_date"],
        "disposition_reason": dict(row).get("disposition_reason"),
        "eligibility_reasons": dict(row).get("eligibility_reasons", []),
        "eligibility_version": POLICY_VERSION,
        "code_complete": code, "quantity_billed": fields.get("G"),
        "billed_total_ars": row["total_ars"],
        "work_change_ids": changes,
        "assessment": "exploratory_not_rn14_or_debit",
        "source_id": source["id"], "source_sha256": source["source_sha256"],
        "value_cut": source["cut_label"], "provider": "HPC",
        "currency_compatibility": "unverified",
        "economic_unit_compatibility": "unverified",
        "candidate_total_if_ars_and_same_unit": None,
        "difference_ars_if_comparable": None,
        "tariff": None,
    }
    if row["disposition"] != "included":
        return {**base, "status": "outside_scope"}
    matches = tariffs.get(code, [])
    if not matches:
        return {**base, "status": "no_exact_hpc_tariff",
                "note": "No se aplicó equivalencia por prefijo de seis dígitos."}
    effective = None
    if resolver is not None:
        resolved = [(item, resolver.resolve(item, row['practice_date'])) for item in matches]
        dated = [(item, candidate) for item, candidate in resolved if candidate['selected'] and candidate['status']!='withdrawn_reference']
        if not dated and any(c['status']=='withdrawn_reference' for _,c in resolved):
            return {**base,'status':'withdrawn_reference','withdrawn_references':[c['status_version'] for _,c in resolved if c['status']=='withdrawn_reference']}
        if not dated:
            status = ('undetermined_declared_dates' if any(c['status']=='undetermined_declared_dates' for _,c in resolved)
                      else 'outside_declared_dates')
            if len(matches)==1:base['tariff']=matches[0]
            return {**base,'status':status,'candidate_locators':[x['source_locator'] for x in matches]}
        if len(dated)!=1:
            return {**base,'status':'ambiguous_hpc_tariff','candidate_locators':[x['source_locator'] for x,_ in dated]}
        tariff,effective=dated[0]
        base['tariff']=tariff
        base['effective_reference']=effective
        if effective['status'] in ('withdrawn_reference','status_evidence_unverifiable'):
            return {**base,'status':effective['status']}
        base['temporal_note']='documented_version_start' if effective['value_version'] else ('end_date_not_declared' if tariff['valid_until'] is None else 'inside_declared_dates')
    else:
        practice_date = row["practice_date"]
        if not practice_date or any(not item.get("valid_from") for item in matches):
            if len(matches) == 1:
                base["tariff"] = matches[0]
            return {**base, "status": "undetermined_declared_dates",
                    "candidate_locators": [x["source_locator"] for x in matches]}
        dated_matches = [item for item in matches
                         if practice_date and item.get("valid_from")
                         and practice_date >= item["valid_from"]
                         and (item.get("valid_until") is None
                              or practice_date <= item["valid_until"])]
        if not dated_matches:
            if len(matches) == 1:
                base["tariff"] = matches[0]
            return {**base, "status": "outside_declared_dates",
                    "candidate_locators": [x["source_locator"] for x in matches]}
        if len(dated_matches) != 1:
            return {**base, "status": "ambiguous_hpc_tariff",
                    "candidate_locators": [x["source_locator"] for x in dated_matches]}
        tariff = dated_matches[0]
        base["tariff"] = tariff
        base["temporal_note"] = ("end_date_not_declared" if tariff["valid_until"] is None
                                 else "inside_declared_dates")
    if effective and effective['status'].startswith('agreement_declaration_'):
        return {**base, 'status': effective['status']}
    if effective and effective['status'] == 'documented_agreement_candidate':
        if (billing_unit != 'practice' or effective['declared_currency'] != 'ARS'
                or effective['declared_unit'] != 'por práctica'):
            return {**base, 'status': 'agreement_unit_or_currency_unverified'}
        amount_cents = Decimal(effective['recorded_amount']) * 100
    elif effective and effective['value_version']:
        if effective['status']!='documented_version_candidate':
            return {**base,'status':'version_evidence_unverifiable'}
        if effective['declared_unit']!='por práctica':
            return {**base,'status':'value_version_unit_incompatible'}
        amount_cents=Decimal(effective['recorded_amount'])*100
    else:
        if type(tariff.get("amount_cents")) is not int or tariff["amount_cents"] < 0:
            return {**base, "status": "catalogue_amount_not_interpretable"}
        calculation = tariff["calculation"]
        if not isinstance(calculation, dict) or calculation.get("kind") != "nbu":
            return {**base, "status": "unsupported_calculation"}
        if calculation.get("reviewRequired") is True:
            return {**base, "status": "tariff_requires_review"}
        units, rate = calculation.get("ubMilliunits"), calculation.get("rateCents")
        if (not isinstance(units, int) or isinstance(units, bool) or units <= 0 or
                not isinstance(rate, int) or isinstance(rate, bool) or rate <= 0 or
                Decimal(units) * Decimal(rate) / 1000 != tariff["amount_cents"]):
            return {**base, "status": "inconsistent_formula"}
        amount_cents=Decimal(tariff['amount_cents'])
    try:
        quantity_literal = str(fields.get("G"))
        if len(quantity_literal) > 64:
            return {**base, "status": "invalid_quantity"}
        quantity = Decimal(quantity_literal)
    except (InvalidOperation, TypeError, ValueError):
        return {**base, "status": "invalid_quantity"}
    if (not quantity.is_finite() or quantity <= 0 or quantity > Decimal("1000000000") or
            quantity.as_tuple().exponent < -6):
        return {**base, "status": "invalid_quantity"}
    total_cents = amount_cents * quantity
    if total_cents != total_cents.to_integral_value():
        return {**base, "status": "fractional_cent_needs_rounding_rule"}
    candidate_ars = total_cents / 100
    billed_ars = Decimal(row["total_ars"])
    difference = billed_ars - candidate_ars
    if abs(difference) <= CENT:
        status = "numeric_equal"
    elif difference > 0:
        status = "numeric_above_candidate"
    else:
        status = "numeric_below_candidate"
    return {**base, "status": status,
            "candidate_total_if_ars_and_same_unit": _money(candidate_ars),
            "difference_ars_if_comparable": _money(difference)}


def compare_batch(conn: sqlite3.Connection, root: Path, token_hash: str,
                  dataset_id: str, batch_id: str, source_id: str,
                  *, status: str = "all", offset: int = 0, limit: int = 50,
                  source_row: int | None = None) -> dict:
    if status not in FILTERS or not 0 <= offset <= 1_000_000 or not 1 <= limit <= 100:
        raise Problem(422, "Filtro o paginación inválida")
    if source_row is not None and source_row < 2:
        raise Problem(422, "Fila física inválida")
    authorized_dataset(conn, token_hash, dataset_id, "reviewer")
    source = conn.execute(
        "SELECT id, source_sha256, cut_label, source_version FROM source_registry "
        "WHERE id = ? AND dataset_id = ? AND kind = 'values' AND status = 'registered'",
        (source_id, dataset_id)).fetchone()
    if source is None:
        raise Problem(404, "Fuente de valores inexistente")
    if source["cut_label"] != CUT:
        raise Problem(422, "Esta comparación requiere el corte V1 explícito")
    catalog = source_db(read_verified(root, source["source_sha256"]))
    try:
        tariffs: dict[str, list[dict]] = defaultdict(list)
        for item in catalog.execute(
            "SELECT seq, code, practice_id, amount_cents, valid_from, valid_until, source_id, page, data_json "
            "FROM hpc_catalog_tariffs WHERE provider = 'HPC' ORDER BY seq"):
            raw = json.loads(item["data_json"])
            tariffs[item["code"]].append({
                "seq": item["seq"], "code": item["code"], "provider": "HPC", "practice_id": item["practice_id"],
                "source_locator": f"hpc_catalog_tariffs.seq={item['seq']}",
                "amount_cents": json_safe_catalog_amount(item["amount_cents"]), "valid_from": item["valid_from"],
                "valid_until": item["valid_until"], "document_source_id": item["source_id"],
                "document_page": item["page"], "conditions": raw.get("conditions"),
                "calculation": raw.get("calculation"),
            })
    finally:
        catalog.close()
    conn.execute("BEGIN")
    try:
        _, dataset = authorized_dataset(conn, token_hash, dataset_id, "reviewer", touch=False)
        batch = conn.execute(
            "SELECT i.id AS import_id, i.revision_id, i.sheet_name, i.period, r.version "
            f"AS revision_version FROM {revision_table(conn, 'invoice_imports')} i "
            "JOIN batches b ON b.id = i.batch_id JOIN revisions r ON r.id = i.revision_id "
            "WHERE b.id = ? AND b.dataset_id = ?", (batch_id, dataset_id)).fetchone()
        if batch is None:
            raise Problem(404, "Lote importado inexistente")
        from .local_hpc import tariffs as local_tariffs
        for item in local_tariffs(conn,dataset_id,source_id):tariffs[item['code']].append(item)
        from .agreement_declarations import ExploratoryResolver
        from .proposal_freshness import provider_basis
        scope = provider_basis(conn, batch_id) or {}
        resolver = EffectiveHpcValues(conn, root, dataset_id, source_id)
        billing_unit = None
        if scope.get('provider') == 'HPC' and scope.get('source_id') == source_id:
            billing_unit = scope.get('billing_unit')
            resolver = ExploratoryResolver(resolver, source['source_sha256'])
        work: dict[int, dict] = defaultdict(dict)
        changes: dict[int, dict] = defaultdict(dict)
        for field in conn.execute(
            "SELECT source_row, field, value_json, latest_change_id FROM work_fields "
            "WHERE import_id = ?", (batch["import_id"],)):
            work[field["source_row"]][field["field"]] = json.loads(field["value_json"])
            changes[field["source_row"]][field["field"]] = field["latest_change_id"]
        counts: Counter[str] = Counter()
        matched = 0
        items = []
        found_row = False
        for original in conn.execute(
            "SELECT source_row, disposition, disposition_reason, practice_date, permitted_json, total_ars "
            "FROM invoice_rows WHERE import_id = ? ORDER BY source_row", (batch["import_id"],)):
            row = effective_row(original, batch["period"])
            fields = json.loads(row["permitted_json"])
            fields.update(work.get(row["source_row"], {}))
            item = _compare(row, fields, changes.get(row["source_row"], {}),
                            tariffs, source, batch["sheet_name"], resolver=resolver, billing_unit=billing_unit)
            counts[item["status"]] += 1
            if source_row is not None:
                if row["source_row"] == source_row:
                    items.append(item)
                    found_row = True
                continue
            selected = (status == "all" or item["status"] == status or
                        status == "differences" and item["status"] in {
                            "numeric_above_candidate", "numeric_below_candidate"} or
                        status == "needs_interpretation" and item["status"] not in {
                            "outside_scope", "no_exact_hpc_tariff", "numeric_equal",
                            "numeric_above_candidate", "numeric_below_candidate"})
            if selected:
                if matched >= offset and len(items) < limit:
                    items.append(item)
                matched += 1
        if source_row is not None and not found_row:
            raise Problem(404, "Fila inexistente")
        result = {
            "kind": "exploratory_hpc_numeric_comparison", "provider": "HPC",
            "dataset_version": dataset["version"], "revision_version": batch["revision_version"],
            "batch_id": batch_id, "period": batch["period"],
            "source_id": source["id"], "source_sha256": source["source_sha256"],
            "value_cut": source["cut_label"], "source_version": source["source_version"],
            "filter": status, "offset": offset, "limit": limit,
            "selected_total": matched if source_row is None else 1,
            "counts": dict(counts), "items": items,
            "caveats": ["El cálculo numérico supone ARS y la misma unidad económica; no están acreditados por fila.",
                        "La fecha final no está declarada en V1; condiciones y acuerdos particulares requieren revisión.",
                        "Una marca urgent del catálogo no prueba que la prestación facturada haya sido urgente ni incluye adicionales.",
                        "No se aplicó equivalencia por prefijo, ni se creó un resultado RN14 o débito."],
        }
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    # A changed interpretation or permission during the scan invalidates this response.
    _, current_dataset = authorized_dataset(conn, token_hash, dataset_id, "reviewer")
    current_revision = conn.execute("SELECT version FROM revisions WHERE id = ?",
                                    (batch["revision_id"],)).fetchone()
    if (current_dataset["version"] != result["dataset_version"] or current_revision is None or
            current_revision["version"] != result["revision_version"]):
        raise Problem(409, "La revisión cambió durante la comparación; reintentá")
    return result

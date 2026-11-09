"""Shared X1 eligibility under RF03/ALC02/MD02; originals remain unchanged."""

from __future__ import annotations

from collections import Counter
from calendar import monthrange
from datetime import date
from functools import lru_cache
import json
import sqlite3


POLICY_VERSION = "X1-ALC02-v2-plazo45"
MAX_BILLING_DAYS = 45
POLICY = {"version": POLICY_VERSION, "included_types": ["A", "C"],
          "excluded_types": ["I"], "unknown_type": "indeterminate",
          "type_normalization": "strip outer whitespace and uppercase; original F preserved",
          "period": "A/C through month end enter review, including late rows; elapsed days 0 through 45 are timely",
          "urgency": "not inferred from type C or nomenclator flags"}


@lru_cache(maxsize=64)
def billing_close(period: str) -> date:
    first = date.fromisoformat(period + "-01")
    return first.replace(day=monthrange(first.year, first.month)[1])


def billing_window(practice_date: str | None, period: str) -> dict:
    close = billing_close(period)
    try:
        service = date.fromisoformat(practice_date)
    except (TypeError, ValueError):
        return {"status": "unknown", "days": None, "close": close.isoformat()}
    days = (close - service).days
    status = "after_close" if days < 0 else "late" if days > MAX_BILLING_DAYS else "in_term"
    return {"status": status, "days": days, "close": close.isoformat()}


LATE_REASON = "Facturación fuera de término"


def late_reason(term: dict, practice_date: str) -> str:
    service = date.fromisoformat(practice_date).strftime("%d/%m/%Y")
    closing = date.fromisoformat(term["close"]).strftime("%d/%m/%Y")
    return (f"{LATE_REASON}. Del {service} al cierre del {closing} pasaron "
            f"{term['days']} días. El plazo es de {MAX_BILLING_DAYS} días.")


def classify(practice_date: str | None, original_type: object, period: str) -> dict:
    kind = original_type.strip().upper() if isinstance(original_type, str) else None
    reasons = []
    term = billing_window(practice_date, period)
    status = term["status"]
    if status == "unknown":
        reasons.append("fecha_ilegible")
    elif status == "after_close" or (status == "late" and kind not in {"A", "C"}):
        reasons.append("fuera_del_periodo")
    if kind == "I":
        reasons.append("internacion_fuera_de_alcance")
    elif kind not in {"A", "C"}:
        reasons.append("ambito_no_identificado")
    excluded = next((reason for reason in ("fuera_del_periodo", "internacion_fuera_de_alcance")
                     if reason in reasons), None)
    disposition = "excluded" if excluded else "indeterminate" if reasons else "included"
    return {"disposition": disposition,
            "period_disposition": "indeterminate" if status == "unknown" else
                "included" if status == "in_term" else "excluded",
            "billing_window": term,
            "setting_disposition": "excluded" if kind == "I" else
                "included" if kind in {"A", "C"} else "indeterminate",
            "disposition_reason": excluded or (reasons[0] if reasons else None),
            "eligibility_reasons": reasons, "scope_type": kind,
            "eligibility_version": POLICY_VERSION}


def effective_row(row: sqlite3.Row | dict, period: str, *, fields: dict | None = None) -> dict:
    result = dict(row)
    if fields is None:
        fields = json.loads(result["permitted_json"])
    result["import_disposition"] = result["disposition"]
    result["import_disposition_reason"] = result.get("disposition_reason")
    result.update(classify(result["practice_date"], fields.get("F"), period))
    return result


def eligibility_summary(conn: sqlite3.Connection, import_id: str, period: str) -> dict:
    counts: Counter[str] = Counter()
    reasons: Counter[tuple[str, str]] = Counter()
    all_reasons: Counter[str] = Counter()
    types: Counter[str] = Counter()
    # Eligibility depends only on the date, setting and confirmed period.
    for day, setting, n in conn.execute("""SELECT practice_date,json_extract(permitted_json,'$.F'),count(*)
            FROM invoice_rows WHERE import_id=? GROUP BY 1,2""",(import_id,)):
        row=classify(day,setting,period)
        counts[row["disposition"]] += n
        types[row["scope_type"] or "unknown"] += n
        for reason in row["eligibility_reasons"]:all_reasons[reason]+=n
        if row["disposition"] != "included":
            reasons[(row["disposition"], row["disposition_reason"])] += n
    return {"eligibility_version": POLICY_VERSION,
            "included_count": counts["included"], "excluded_count": counts["excluded"],
            "indeterminate_count": counts["indeterminate"],
            "exclusions": [{"disposition": key[0], "disposition_reason": key[1], "total": total}
                           for key, total in sorted(reasons.items())],
            "all_reason_counts": dict(all_reasons), "source_type_counts": dict(types)}

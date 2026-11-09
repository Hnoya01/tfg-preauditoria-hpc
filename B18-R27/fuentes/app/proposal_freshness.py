"""RN27/RN28/MD10 currentness of saved components; evaluation never writes.

Only the latest version in a row/revision is considered. Saved calculations and
their evidence are immutable history; an affected component is not recalculated
or replaced by an older version during a read.
"""

from __future__ import annotations

from .revision_scope import revision_table

from datetime import date
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sqlite3

from .controls import _run_summary
from .dependencies import result_affected
from .documentary_assessments import DocumentaryEvaluator, reference_documentary_dependency
from .eligibility import effective_row
from .monetary_gate import EconomicReference, GateBlocked, ProposedComponent, RowContext, consolidate_current
from .review import _decision_status, _latest_run, _result
from .storage import read_verified


BASIS_VERSION = "P06-component-basis-v1"
VERIFICATION_FIELDS = ("id", "source_id", "source_sha256", "evidence_sha256", "evidence_locator",
                       "tariff_locator", "provider", "code_complete", "currency", "economic_unit",
                       "rate_ars", "valid_from", "verified_through", "applicability_note",
                       "verified_by", "verified_at", "cut_label")


def value_source_basis(conn: sqlite3.Connection, dataset_id: str) -> list[dict]:
    return [dict(row) for row in conn.execute(
        "SELECT id, kind, status, source_sha256, manifest_sha256, cut_label, source_version, "
        "captured_at, coverage_json, metadata_json FROM source_registry "
        "WHERE dataset_id = ? AND kind = 'values' ORDER BY id", (dataset_id,))]


def provider_basis(conn: sqlite3.Connection, batch_id: str) -> dict | None:
    row = conn.execute(f"SELECT * FROM {revision_table(conn, 'batch_provider_scope_history')} WHERE batch_id = ? "
                       "ORDER BY ordinal DESC LIMIT 1", (batch_id,)).fetchone()
    return dict(row) if row else None


def document_basis(conn: sqlite3.Connection, dataset_id: str, source_id: str, sha256: str) -> dict | None:
    row = conn.execute("SELECT * FROM evidence_documents WHERE dataset_id = ? AND source_id = ? AND sha256 = ?",
                       (dataset_id, source_id, sha256)).fetchone()
    return dict(row) if row else None


def row_basis(conn: sqlite3.Connection, row: dict, fields: dict) -> dict:
    return {"practice_date": row["practice_date"], "scope_type": row["scope_type"],
            "eligibility_version": row["eligibility_version"],
            "fields": {field: fields.get(field) for field in ("B", "C", "E", "G", "K")},
            "amounts": {key: row[key] for key in ("honorarios_ars", "derechos_ars", "total_ars")},
            "work_change_ids": {w["field"]: w["latest_change_id"] for w in conn.execute(
                "SELECT field, latest_change_id FROM work_fields WHERE import_id = ? AND source_row = ?",
                (row["import_id"], row["source_row"]))}}


def reference_from_snapshot(verification: dict) -> EconomicReference:
    return EconomicReference(verification["source_id"], verification["source_sha256"],
        verification["cut_label"], verification["tariff_locator"], verification["provider"],
        verification["code_complete"], verification["currency"], verification["economic_unit"],
        Decimal(verification["rate_ars"]), date.fromisoformat(verification["valid_from"]),
        date.fromisoformat(verification["verified_through"]), True, verification["applicability_note"])


def part_from_snapshot(source_row: int, part: dict, verification: dict) -> ProposedComponent:
    adjusted = part.get("adjustment_calculation") is not None or part.get("adjustment_reason") is not None
    return ProposedComponent(source_row, part["decision_id"], part["rule_code"], part["rubric"],
        Decimal(part["unit_start"]), Decimal(part["unit_end"]), Decimal(part["billed_scope_ars"]),
        reference_from_snapshot(verification), Decimal(part["amount_ars"]) if adjusted else None,
        part.get("adjustment_calculation"), part.get("adjustment_reason"))


def _known_money(value: object) -> Decimal | None:
    if not isinstance(value, str):
        return None
    try:
        money = Decimal(value)
        return money if money.is_finite() and money >= 0 and money.quantize(Decimal("0.01")) == money else None
    except InvalidOperation:
        return None


class ProposalEvaluator:
    """Reuse caches inside an already authorized, consistent database snapshot."""

    def __init__(self, conn: sqlite3.Connection, root: Path, dataset_id: str,
                 batch_id: str, batch: dict | sqlite3.Row, summary: dict | None = None):
        self.conn, self.root, self.dataset_id, self.batch_id = conn, root, dataset_id, batch_id
        self.batch = batch
        self.scope = provider_basis(conn, batch_id)
        self.values = value_source_basis(conn, dataset_id)
        self.invoice_sha = conn.execute("SELECT source_sha256 FROM batches WHERE id = ? AND dataset_id = ?",
                                        (batch_id, dataset_id)).fetchone()[0]
        latest = _latest_run(conn, batch["revision_id"])
        self.latest_run_id = latest["id"] if latest else None
        self.summaries = {summary["id"]: summary} if summary else {}
        self.objects: dict[str, bool] = {}
        self.documentary = DocumentaryEvaluator(conn, root, dataset_id)

    def _summary(self, run_id: str) -> dict:
        if run_id not in self.summaries:
            self.summaries[run_id] = _run_summary(self.conn, self.dataset_id, run_id)
        return self.summaries[run_id]

    def _original_available(self, sha256: str) -> bool:
        if sha256 not in self.objects:
            try:
                read_verified(self.root, sha256)
                self.objects[sha256] = True
            except (OSError, RuntimeError, ValueError):
                self.objects[sha256] = False
        return self.objects[sha256]

    def evaluate(self, version: sqlite3.Row | dict) -> dict:
        payload = json.loads(version["payload_json"])
        if payload.get('format_version') == 3:
            from .rn14_proposals import evaluate_version
            return evaluate_version(self.conn,self.root,self.dataset_id,self.batch_id,self.batch,version,
                summary=self._summary(self.latest_run_id) if self.latest_run_id else None,summary_reader=self._summary)
        parts = payload.get("components", [])
        basis = payload.get("basis", {})
        common = []
        from .authorization_controls import synthetic_batch
        if synthetic_batch(self.conn,self.batch_id):
            common.append('synthetic_batch_not_monetary_evidence')
        if payload.get("format_version") != 2 or basis.get("version") != BASIS_VERSION:
            common.append("saved_dependency_basis_missing")
        if version["revision_id"] != self.batch["revision_id"] or version["import_id"] != self.batch["import_id"]:
            common.append("proposal_revision_mismatch")
        if self.batch["state"] == "cerrada":
            common.append("closed_revision_snapshot_required")
        original = self.conn.execute("SELECT * FROM invoice_rows WHERE import_id = ? AND source_row = ?",
                                     (self.batch["import_id"], version["source_row"])).fetchone()
        row = effective_row(original, self.batch["period"])
        fields = json.loads(row["permitted_json"])
        for work in self.conn.execute("SELECT field, value_json FROM work_fields WHERE import_id = ? AND source_row = ?",
                                       (row["import_id"], row["source_row"])):
            fields[work["field"]] = json.loads(work["value_json"])
        if row["disposition"] != "included":
            common.append("row_outside_scope")
        if basis.get("row") != row_basis(self.conn, row, fields):
            common.append("shared_row_basis_changed")
        if basis.get("provider_scope") != self.scope or self.scope is None:
            common.append("provider_scope_changed")
        if basis.get("value_sources") != self.values:
            common.append("value_source_selection_changed")
        if basis.get("invoice_sha256") != self.invoice_sha or not self._original_available(self.invoice_sha):
            common.append("invoice_original_unavailable_or_changed")
        saved_summary = self._summary(version["run_id"])
        if basis.get("run_sha256") != saved_summary["snapshot_sha256"]:
            common.append("supporting_analysis_changed")
        latest_summary = self._summary(self.latest_run_id) if self.latest_run_id else None
        if latest_summary is None:
            common.append("current_analysis_missing")
        ids = [part.get("component_id") for part in parts]
        if not ids or any(not isinstance(identity, str) or not identity for identity in ids) or len(set(ids)) != len(ids):
            common.append("saved_component_identity_missing")
        amounts = [_known_money(part.get("amount_ars")) for part in parts]
        if (any(amount is None for amount in amounts) or
                sum((amount for amount in amounts if amount is not None), Decimal("0.00")) != _known_money(version["amount_ars"]) or
                payload.get("amount_ars") != version["amount_ars"]):
            common.append("saved_proposal_amount_inconsistent")
        snapshots = {v["id"]: v for v in payload.get("verification_snapshots", []) if isinstance(v, dict) and "id" in v}
        evaluated, candidates = [], []
        for index, part in enumerate(parts):
            reasons = list(common)
            verification = snapshots.get(part.get("verification_id"))
            decision = self.conn.execute(
                "SELECT d.id, d.state, d.rule_code, d.alert_id, a.source_row, a.revision_id "
                "FROM review_decisions d JOIN alerts a ON a.id = d.alert_id WHERE d.id = ?",
                (part.get("decision_id"),)).fetchone()
            if (decision is None or decision["state"] != "confirmada" or
                    decision["source_row"] != row["source_row"] or decision["revision_id"] != self.batch["revision_id"] or
                    decision["rule_code"] != part.get("rule_code") or self.latest_run_id is None or
                    _decision_status(self.conn, decision["alert_id"], self.latest_run_id) != ("confirmada", decision["id"])):
                reasons.append("decision_not_current_confirmed")
            elif (result_affected(saved_summary, row["source_row"], decision["rule_code"]) or
                  result_affected(latest_summary, row["source_row"], decision["rule_code"])):
                reasons.append("finding_dependencies_changed")
            else:
                result = _result(self.conn, self.latest_run_id, row["source_row"], decision["rule_code"])
                if result is None or result["result"] != "con_indicios":
                    reasons.append("current_finding_missing")
            current = self.conn.execute(
                "SELECT v.*, s.cut_label FROM economic_verifications v JOIN source_registry s ON s.id = v.source_id "
                "WHERE v.id = ? AND v.dataset_id = ? AND s.dataset_id = ?",
                (part.get("verification_id"), self.dataset_id, self.dataset_id)).fetchone()
            withdrawn = self.conn.execute("SELECT 1 FROM economic_verification_withdrawals WHERE verification_id = ?",
                                          (part.get("verification_id"),)).fetchone()
            if current is None or not current["active"] or withdrawn:
                reasons.append("economic_reference_withdrawn_or_missing")
            if verification is None or current is None or verification != {key: current[key] for key in VERIFICATION_FIELDS}:
                reasons.append("economic_verification_changed")
            if verification:
                cotejo = reference_documentary_dependency(self.conn, self.root, self.dataset_id,
                                                          verification, self.documentary)
                if (cotejo['id'] if cotejo else None) != part.get('documentary_assessment_id_at_save'):
                    reasons.append('documentary_assessment_changed')
                elif cotejo and not cotejo['usable_match']:
                    reasons.append('documentary_assessment_not_current_match')
                document = document_basis(self.conn, self.dataset_id, verification["source_id"], verification["evidence_sha256"])
                if document is None or document != part.get("document_snapshot"):
                    reasons.append("document_registration_changed")
                if (not self._original_available(verification["source_sha256"]) or
                        not self._original_available(verification["evidence_sha256"])):
                    reasons.append("reference_original_unavailable_or_changed")
            evaluated.append({**part, "amount_ars_at_save": part.get("amount_ars"),
                              "current_amount_ars": None,
                              "freshness": "requires_update" if reasons else "current",
                              "invalid_reasons": list(dict.fromkeys(reasons))})
            if not reasons:
                try:
                    candidate = part_from_snapshot(row["source_row"], part, verification)
                    context = self._context(row, fields, {(part["decision_id"], part["rule_code"])})
                    reproduced = consolidate_current(context, (candidate,))["components"][0]
                    if any(part.get(key) != value for key, value in reproduced.items()):
                        raise ValueError("Saved calculation differs")
                    candidates.append((index, candidate))
                except (ValueError, TypeError, ArithmeticError, KeyError):
                    evaluated[-1]["freshness"] = "requires_update"
                    evaluated[-1]["invalid_reasons"].append("saved_calculation_not_reproducible")
        current_total = None
        if candidates:
            try:
                context = self._context(row, fields, {(part.decision_id, part.rule_code) for _, part in candidates})
                current_total = consolidate_current(context, tuple(part for _, part in candidates))["amount_ars"]
                for index, _ in candidates:
                    evaluated[index]["current_amount_ars"] = evaluated[index]["amount_ars_at_save"]
            except (ValueError, TypeError, ArithmeticError):
                for index, _ in candidates:
                    evaluated[index]["freshness"] = "requires_update"
                    evaluated[index]["invalid_reasons"].append("component_consolidation_invalid")
        current_count = sum(part["current_amount_ars"] is not None for part in evaluated)
        affected = [part for part in evaluated if part["current_amount_ars"] is None]
        affected_amounts = [_known_money(part["amount_ars_at_save"]) for part in affected]
        affected_total = (format(sum(affected_amounts, Decimal("0.00")), ".2f")
                          if affected and all(amount is not None for amount in affected_amounts) else None)
        return {"proposal_id": version["id"], "ordinal": version["ordinal"], "source_row": version["source_row"],
                "state": "partially_current" if current_count and affected else "current" if current_count else "requires_update",
                "currency": "ARS", "amount_ars": current_total, "amount_ars_at_save": version["amount_ars"],
                "affected_amount_ars_at_save": affected_total, "current_component_count": current_count,
                "affected_component_count": len(affected), "components": evaluated,
                "invalid_reasons": list(dict.fromkeys(common))}

    def _context(self, row: dict, fields: dict, decisions: set) -> RowContext:
        return RowContext(row["source_row"], self.scope["provider"], str(fields.get("E") or ""),
            date.fromisoformat(row["practice_date"]), Decimal(str(fields.get("G"))),
            Decimal(row["honorarios_ars"]), Decimal(row["derechos_ars"]), Decimal(row["total_ars"]),
            self.scope["billing_unit"], row["disposition"] == "included", frozenset(decisions),
            frozenset((source["id"], source["source_sha256"]) for source in self.values if source["status"] == "registered"))

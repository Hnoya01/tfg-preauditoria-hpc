"""Consistent, private RN31 provisional export of an open revision."""

from __future__ import annotations

from .revision_scope import revision_table

from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
from io import BytesIO, TextIOWrapper
import json
import sqlite3
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from .controls import _run_summary
from .storage import read_verified
from .db import transaction
from .review import _decision_status
from .service import Problem, authorized_dataset, event
from .eligibility import POLICY, effective_row, eligibility_summary
from .dependencies import result_affected
from .proposal_freshness import ProposalEvaluator
from .documentary_assessments import DocumentaryEvaluator
from .agreement_review import load_agreement_review
from .authorization_imports import capture_export_records
from .authorization_matching import export_correspondence_history


def _dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _write_lines(archive: ZipFile, name: str, records) -> None:
    with archive.open(name, "w") as binary:
        with TextIOWrapper(binary, encoding="utf-8", write_through=True) as output:
            for record in records:
                output.write(_dump(record) + "\n")


@contextmanager
def _read_snapshot(conn: sqlite3.Connection):
    """Keep a WAL read snapshot while building ZIP, without blocking reviewers' writes."""
    if conn.in_transaction:
        yield  # The caller owns this snapshot and its commit/rollback boundary.
        return
    conn.execute("BEGIN")
    try:
        yield
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def provisional_export(conn: sqlite3.Connection, root: Path, token_hash: str,
                       dataset_id: str, batch_id: str, *, _capture_only=False,
                       _allow_unexecuted=False) -> tuple[bytes, str, dict]:
    """Capture latest results and effective decisions; no monetary proposal is inferred."""
    with _read_snapshot(conn):
        _, dataset = authorized_dataset(conn, token_hash, dataset_id, "reviewer", touch=False)
        batch = conn.execute(
            "SELECT b.id, b.source_sha256, b.original_name, i.id AS import_id, i.period, "
            "i.sheet_name, i.row_count, i.included_count, i.excluded_count, "
            "i.indeterminate_count, i.eligibility_version, i.honorarios_ars, i.derechos_ars, i.total_ars, "
            "r.id AS revision_id, r.ordinal, r.state, r.version AS revision_version "
            f"FROM batches b JOIN {revision_table(conn, 'invoice_imports')} i ON i.batch_id = b.id "
            "JOIN revisions r ON r.id = i.revision_id "
            "WHERE b.id = ? AND b.dataset_id = ?", (batch_id, dataset_id)).fetchone()
        if batch is None:
            raise Problem(404, "Lote importado inexistente")
        if batch["state"] == "cerrada":
            raise Problem(409, "La exportación de cierre requiere la captura de cierre")
        run = conn.execute("SELECT id FROM control_runs WHERE revision_id = ? "
                           "ORDER BY created_at DESC, rowid DESC LIMIT 1",
                           (batch["revision_id"],)).fetchone()
        if run is None and not _allow_unexecuted:
            raise Problem(409, "Primero ejecutá el análisis")
        if run is None:
            from .controls import _snapshot
            invoice = conn.execute(f'SELECT i.*,b.source_sha256 FROM {revision_table(conn, "invoice_imports")} i JOIN batches b ON b.id=i.batch_id WHERE i.id=?', (batch['import_id'],)).fetchone()
            snapshot = _snapshot(conn, dataset_id, invoice)
            summary = {'snapshot': snapshot, 'snapshot_sha256': hashlib.sha256(_dump(snapshot).encode()).hexdigest(),
                       'technical_state': 'not_executed', 'freshness': 'not_evaluated', 'stored_freshness': None,
                       'affected_rules': [], 'global_affected_rules': [], 'affected_rows': {}, 'counts': []}
            run = {'id': None}
        else:
            summary = _run_summary(conn, dataset_id, run["id"])
        eligibility = eligibility_summary(conn, batch["import_id"], batch["period"])
        exclusions = eligibility["exclusions"]
        row_scope = {row["source_row"]: effective_row(row, batch["period"])["disposition"]
                     for row in conn.execute("SELECT source_row, disposition, disposition_reason, "
                                              "practice_date, permitted_json FROM invoice_rows WHERE import_id = ?",
                                              (batch["import_id"],))}
        limitations: Counter[tuple] = Counter()
        for row in conn.execute(
            "SELECT source_row, rule_code, result, reason_code FROM control_results "
            "WHERE run_id = ? AND result IN ('no_concluyente', 'no_evaluado') "
            "ORDER BY rule_code, result, reason_code", (run["id"],)):
            if row_scope[row["source_row"]] == "included":
                limitations[(row["rule_code"], row["result"], row["reason_code"])] += 1
        coverage_limitations = [{"rule_code": key[0], "result": key[1], "reason_code": key[2], "total": total}
                                for key, total in sorted(limitations.items())]
        sources = [dict(row) for row in conn.execute(
            "SELECT id, kind, status, source_sha256, manifest_sha256, format_label, "
            "cut_label, source_version, captured_at, coverage_json, metadata_json "
            "FROM source_registry WHERE dataset_id = ? ORDER BY kind, created_at, id",
            (dataset_id,))]
        for source in sources:
            source["coverage"] = json.loads(source.pop("coverage_json"))
            source["metadata"] = json.loads(source.pop("metadata_json"))
        work_fields: dict[int, dict] = defaultdict(dict)
        for field in conn.execute(
            "SELECT source_row, field, value_json, latest_change_id FROM work_fields "
            "WHERE import_id = ? ORDER BY source_row, field", (batch["import_id"],)):
            work_fields[field["source_row"]][field["field"]] = {
                "value": json.loads(field["value_json"]),
                "change_id": field["latest_change_id"]}

        alert_by_row: dict[int, list[dict]] = defaultdict(list)
        alert_counts: Counter[str] = Counter()
        for alert in conn.execute(
            "SELECT id, source_row, rule_code, version, first_run_id FROM alerts "
            "WHERE revision_id = ? ORDER BY source_row, rule_code", (batch["revision_id"],)):
            result = conn.execute("SELECT result FROM control_results WHERE run_id = ? "
                                  "AND source_row = ? AND rule_code = ?",
                                  (run["id"], alert["source_row"], alert["rule_code"])).fetchone()
            in_scope = row_scope[alert["source_row"]] == "included"
            current = in_scope and result is not None and result["result"] == "con_indicios"
            fresh = not result_affected(summary, alert["source_row"], alert["rule_code"])
            status, decision_id = _decision_status(conn, alert["id"], run["id"])
            if not current or not fresh:
                status, decision_id = "pendiente", None
            category = ("historical_outside_scope" if not in_scope else
                        "requires_update" if not fresh else
                        "historical" if not current else status)
            alert_counts[category] += 1
            alert_by_row[alert["source_row"]].append({
                **dict(alert), "current_result": result["result"] if result else None,
                "freshness": "outside_scope" if not in_scope else "current" if fresh else "requires_update",
                "decision": status, "decision_id": decision_id,
                "category": category})

        row_counts: Counter[str] = Counter()
        monetary_counts: Counter[str] = Counter()
        monetary_total = Decimal("0.00")
        latest_proposals = {row["source_row"]: row for row in conn.execute(
            "SELECT p.* FROM proposal_versions p WHERE p.revision_id = ? AND p.import_id = ? "
            "AND NOT EXISTS (SELECT 1 FROM proposal_versions newer WHERE newer.revision_id = p.revision_id "
            "AND newer.import_id = p.import_id AND newer.source_row = p.source_row AND newer.ordinal > p.ordinal)",
            (batch["revision_id"], batch["import_id"]))}
        evaluator = ProposalEvaluator(conn, root, dataset_id, batch_id, batch, summary) if latest_proposals else None
        def row_records():
            nonlocal monetary_total
            for original in conn.execute(
                "SELECT source_row, disposition, disposition_reason, practice_date, permitted_json, "
                "honorarios_ars, derechos_ars, total_ars, amount_check "
                "FROM invoice_rows WHERE import_id = ? ORDER BY source_row", (batch["import_id"],)):
                row = effective_row(original, batch["period"])
                alerts = alert_by_row.get(row["source_row"], [])
                if row["disposition"] != "included":
                    proposal_state = "outside_scope"
                elif any(a["category"] == "requires_update" for a in alerts):
                    proposal_state = "requires_update"
                elif any(a["category"] == "pendiente" for a in alerts):
                    proposal_state = "pending_review"
                elif any(a["category"] == "confirmada" for a in alerts):
                    proposal_state = "unquantified_no_economic_basis"
                else:
                    proposal_state = "no_current_proposal"
                evaluation = evaluator.evaluate(latest_proposals[row["source_row"]]) if row["source_row"] in latest_proposals else None
                if evaluation:
                    monetary_counts["current_components"] += evaluation["current_component_count"]
                    monetary_counts["affected_components"] += evaluation["affected_component_count"]
                    if evaluation["amount_ars"] is not None:
                        monetary_total += Decimal(evaluation["amount_ars"])
                        proposal_state = ("partially_current_proposal" if evaluation["affected_component_count"]
                                          else "current_supported_proposal")
                    elif row["disposition"] == "included":
                        proposal_state = ('not_current_by_decision' if evaluation['state']=='not_current_by_decision' else 'requires_update')
                row_counts[proposal_state] += 1
                record = dict(row)
                record["fields"] = json.loads(record.pop("permitted_json"))
                record["work_fields"] = work_fields.get(row["source_row"], {})
                record["locator"] = f"{batch['sheet_name']}!{row['source_row']}"
                record["alerts"] = alerts
                record["proposal_state"] = proposal_state
                record["proposed_amount_ars"] = evaluation["amount_ars"] if evaluation else None
                record["monetary_components"] = evaluation["components"] if evaluation else []
                record["proposal_evaluation"] = evaluation
                if conn.execute('PRAGMA user_version').fetchone()[0]>=24:
                    from .rn14_proposals import _latest, evaluate_version
                    simulation=_latest(conn,'rn14_simulation_versions',batch,row['source_row'])
                    record['rn14_simulation']=(evaluate_version(conn,root,dataset_id,batch_id,batch,simulation,simulation=True,summary=summary) if simulation else None)
                yield record

        def result_records():
            for row in conn.execute(
                "SELECT source_row, rule_code, rule_version, result, reason_code, "
                "evidence_json, difference_ars, currency FROM control_results "
                "WHERE run_id = ? ORDER BY source_row, rule_code", (run["id"],)):
                record = dict(row)
                record["evidence"] = json.loads(record.pop("evidence_json"))
                record["freshness"] = ("requires_update" if result_affected(summary, row["source_row"], row["rule_code"])
                                       else "current")
                yield record

        def decision_records():
            for row in conn.execute(
                "SELECT d.id, d.alert_id, d.run_id, d.source_row, d.rule_code, d.state, "
                "d.foundation, d.evidence_note, d.previous_id, d.group_id, "
                "u.username AS actor, d.created_at FROM review_decisions d "
                "JOIN alerts a ON a.id = d.alert_id JOIN users u ON u.id = d.actor_id "
                "WHERE a.revision_id = ? ORDER BY d.created_at, d.rowid",
                (batch["revision_id"],)):
                yield dict(row)

        def reuse_records():
            for row in conn.execute(
                "SELECT r.alert_id, r.decision_id, r.run_id, r.source_row, "
                "r.rule_code, r.created_at FROM decision_reuses r "
                "JOIN alerts a ON a.id = r.alert_id WHERE a.revision_id = ? "
                "ORDER BY r.created_at, r.rowid", (batch["revision_id"],)):
                yield dict(row)

        def work_change_records():
            for row in conn.execute(
                "SELECT w.id, w.source_row, w.field, w.previous_json, w.new_json, "
                "w.reason, u.username AS actor, w.created_at FROM work_changes w "
                "JOIN users u ON u.id = w.actor_id WHERE w.revision_id = ? "
                "ORDER BY w.created_at, w.rowid", (batch["revision_id"],)):
                record = dict(row)
                record["previous"] = json.loads(record.pop("previous_json"))
                record["new"] = json.loads(record.pop("new_json"))
                yield record

        def proposal_version_records():
            for row in conn.execute("SELECT * FROM proposal_versions WHERE revision_id = ? AND import_id = ? "
                                    "ORDER BY source_row, ordinal", (batch["revision_id"], batch["import_id"])):
                record = dict(row)
                record["payload_at_save"] = json.loads(record.pop("payload_json"))
                record["work_basis_at_save"] = json.loads(record.pop("work_basis_json"))
                yield record

        def documentary_records():
            evaluator = DocumentaryEvaluator(conn, root, dataset_id)
            for row in conn.execute('SELECT d.*, u.username AS actor_username FROM documentary_assessments d '
                                    'JOIN users u ON u.id = d.actor_id WHERE d.dataset_id = ? '
                                    'ORDER BY d.source_id, d.provider, d.code_complete, d.tariff_seq, d.ordinal', (dataset_id,)):
                latest = conn.execute('SELECT max(ordinal) FROM documentary_assessments WHERE source_id = ? '
                                      'AND provider = ? AND code_complete = ? AND tariff_seq = ?',
                                      (row['source_id'], row['provider'], row['code_complete'], row['tariff_seq'])).fetchone()[0]
                if row['ordinal'] == latest:
                    yield {**evaluator.evaluate(row), 'is_latest': True}
                else:
                    record = dict(row)
                    record['basis_at_save'] = json.loads(record.pop('basis_json'))
                    yield {**record, 'is_latest': False, 'freshness': 'historical', 'economic_approval': False}

        data = BytesIO()
        general_reviews = [load_agreement_review(conn, root, dataset_id, source['id']) for source in sources
                           if source['kind'] == 'values']
        with ZipFile(data, "w", ZIP_DEFLATED, compresslevel=6) as archive:
            archive.writestr('analysis_snapshot.json',_dump(summary['snapshot']))
            if conn.execute('PRAGMA user_version').fetchone()[0] >= 25:
                from .medical_consultations import records
                _write_lines(archive, 'medical_consultations.jsonl', records(conn, revision_id=batch['revision_id']))
            _write_lines(archive, "rows.jsonl", row_records())
            _write_lines(archive, "control_results.jsonl", result_records())
            _write_lines(archive, "decisions.jsonl", decision_records())
            _write_lines(archive, "decision_reuses.jsonl", reuse_records())
            _write_lines(archive, "work_changes.jsonl", work_change_records())
            _write_lines(archive, "proposal_versions.jsonl", proposal_version_records())
            if conn.execute('PRAGMA user_version').fetchone()[0]>=24:
                _write_lines(archive,'rn14_simulation_versions.jsonl',(
                    {**{k:r[k] for k in r.keys() if k!='payload_json'},'simulation_only':True,'payload_at_save':json.loads(r['payload_json'])}
                    for r in conn.execute('SELECT * FROM rn14_simulation_versions WHERE revision_id=? ORDER BY source_row,ordinal',(batch['revision_id'],))))
                _write_lines(archive,'rn14_proposal_references.jsonl',(dict(r) for r in conn.execute(
                    'SELECT * FROM rn14_proposal_references WHERE proposal_id IN (SELECT id FROM proposal_versions WHERE revision_id=?) '
                    'OR simulation_id IN (SELECT id FROM rn14_simulation_versions WHERE revision_id=?) ORDER BY id',
                    (batch['revision_id'],batch['revision_id']))))
            _write_lines(archive, "documentary_assessments.jsonl", documentary_records())
            _write_lines(archive, 'agreement_document_reviews.jsonl', (r for r in general_reviews if r))
            _write_lines(archive, 'authorization_captures.jsonl', capture_export_records(conn, dataset_id))
            _write_lines(archive, 'authorization_links.jsonl', export_correspondence_history(conn, root, dataset_id, batch_id))
            if conn.execute('PRAGMA user_version').fetchone()[0] >= 40:
                _write_lines(archive, 'hpc_code_correspondences.jsonl', (dict(r) for r in conn.execute(
                    'SELECT * FROM hpc_code_correspondences WHERE dataset_id=? ORDER BY id', (dataset_id,))))
            _write_lines(archive, 'authorization_inputs.jsonl', (dict(r) for r in conn.execute(
                f'SELECT h.*,u.username AS actor_username FROM {revision_table(conn, "authorization_input_versions")} h JOIN users u ON u.id=h.actor_id WHERE batch_id=? ORDER BY source_row,kind,ordinal', (batch_id,))))
            _write_lines(archive, 'authorization_scopes.jsonl', (dict(r) for r in conn.execute(
                f'SELECT s.*, u.username AS actor_username FROM {revision_table(conn, "authorization_match_scopes")} s JOIN users u ON u.id=s.actor_id WHERE batch_id=? ORDER BY ordinal', (batch_id,))))
            manifest = {
                "kind": "provisional_review_export", "export_id": str(uuid4()),
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "warning": "Propuesta sujeta a validación externa; no aplica débitos definitivos.",
                "dataset": {"id": dataset["id"], "version": dataset["version"]},
                "batch": {**dict(batch),
                          "classification_at_import": {key: batch[key] for key in
                              ("included_count", "excluded_count", "indeterminate_count", "eligibility_version")},
                          **{key: eligibility[key] for key in
                              ("included_count", "excluded_count", "indeterminate_count", "eligibility_version")}},
                "eligibility_policy": POLICY, "eligibility": eligibility,
                "control_run": {"id": run["id"],
                                "snapshot_sha256": summary["snapshot_sha256"],
                                "technical_state": summary["technical_state"],
                                "freshness": summary["freshness"],
                                "stored_freshness": summary["stored_freshness"],
                                "affected_rules": summary["affected_rules"],
                                "global_affected_rules": summary["global_affected_rules"],
                                "affected_rows": summary["affected_rows"],
                                "result_counts": summary["counts"]},
                "sources": sources, "alert_counts": dict(alert_counts),
                "authorization_analysis": {
                    'version':summary['snapshot'].get('authorization_engine',{}).get('version'),
                    'captured_mode':(summary['snapshot'].get('authorization_engine',{}).get('scope') or {}).get('mode'),
                    'source_validation':'not_verified','monetary_eligible':False,
                    'note':'Las comparaciones ficticias no acreditan autorizaciones ni importes reales.'},
                "exclusions": exclusions, "coverage_limitations": coverage_limitations,
                "row_proposal_states": dict(row_counts),
                "current_proposal_total_ars": format(monetary_total, ".2f") if monetary_counts["current_components"] else None,
                "current_proposal_currency": "ARS",
                "monetary_status": ("partially_current" if monetary_counts["current_components"] and monetary_counts["affected_components"]
                                    else "current_components_only" if monetary_counts["current_components"] else "unquantified"),
                "monetary_component_counts": dict(monetary_counts),
                "contents": ['analysis_snapshot.json',"rows.jsonl", "control_results.jsonl", "decisions.jsonl",
                             "decision_reuses.jsonl", "work_changes.jsonl", "proposal_versions.jsonl",
                             "documentary_assessments.jsonl", 'agreement_document_reviews.jsonl', 'authorization_captures.jsonl',
                             'authorization_links.jsonl', 'authorization_scopes.jsonl', 'authorization_inputs.jsonl'],
            }
            if conn.execute('PRAGMA user_version').fetchone()[0] >= 21:
                origin = conn.execute('SELECT * FROM revision_openings WHERE revision_id=?', (batch['revision_id'],)).fetchone()
                manifest['revision_origin'] = ({**dict(origin), 'basis': json.loads(origin['basis_json'])} if origin else None)
                if manifest['revision_origin']:
                    del manifest['revision_origin']['basis_json']
            if conn.execute('PRAGMA user_version').fetchone()[0]>=24:
                from .rn14_proposals import simulation_summary
                manifest['rn14_simulations']=simulation_summary(conn,root,dataset_id,batch_id,batch,summary)
                manifest['contents'].append('rn14_simulation_versions.jsonl')
                manifest['contents'].append('rn14_proposal_references.jsonl')
            if conn.execute('PRAGMA user_version').fetchone()[0] >= 25:
                from .medical_consultations import summary as consultation_summary
                manifest['medical_consultations'] = consultation_summary(conn, batch['revision_id'])
                manifest['contents'].append('medical_consultations.jsonl')
            if conn.execute('PRAGMA user_version').fetchone()[0]>=27:
                from .observation_workflow import records as observation_records
                _write_lines(archive,'observation_events.jsonl',observation_records(conn,batch['revision_id']))
                manifest['contents'].append('observation_events.jsonl')
            if conn.execute('PRAGMA user_version').fetchone()[0]>=34:
                from .csv_reviews import history as csv_history
                csv_records = csv_history(conn,batch['revision_id'])
                if csv_records:
                    _write_lines(archive,'csv_coverage_reviews.jsonl',csv_records)
                    manifest['contents'].append('csv_coverage_reviews.jsonl')
            if conn.execute('PRAGMA user_version').fetchone()[0]>=28:
                from .row_documents import export_records as row_document_records, LIMIT as row_document_limit
                attachments=row_document_records(conn,batch['import_id'],batch['revision_id'])
                _write_lines(archive,'row_documents.jsonl',attachments)
                manifest['contents'].append('row_documents.jsonl')
                objects=[]
                for sha in sorted({d['sha256'] for d in attachments}):
                    try:content=read_verified(root,sha)
                    except (OSError,RuntimeError) as exc:raise Problem(409,'Un PDF aportado no supera la comprobación de integridad; no se exportó') from exc
                    name=f'row_documents/{sha}.pdf'
                    archive.writestr(name,content);manifest['contents'].append(name)
                    objects.append({'path':name,'sha256':sha,'bytes':len(content)})
                manifest['row_documents']={'records':len(attachments),'objects':objects,'use_limit':row_document_limit}
            if conn.execute('PRAGMA user_version').fetchone()[0]>=29:
                from .local_hpc import export_history as local_history
                local=local_history(conn,dataset_id)
                _write_lines(archive,'local_hpc_history.jsonl',local)
                manifest['contents'].append('local_hpc_history.jsonl')
                objects=[]
                for sha in sorted({v['document_sha256'] for p in local for v in p['versions']}):
                    try:content=read_verified(root,sha)
                    except (OSError,RuntimeError) as exc:raise Problem(409,'Respaldo de práctica propia no verificable; no se exportó') from exc
                    name=f'local_hpc_documents/{sha}.pdf';archive.writestr(name,content);manifest['contents'].append(name)
                    objects.append({'path':name,'sha256':sha,'bytes':len(content)})
                manifest['local_hpc']={'practices':len(local),'objects':objects,'use_limit':'Historia declarada por operador; no acredita aplicabilidad automática.'}
            archive.writestr("manifest.json", _dump(manifest))
        content = data.getvalue()
        digest = hashlib.sha256(content).hexdigest()
    if _capture_only:
        return content, digest, manifest
    with transaction(conn):
        current_user, current_dataset = authorized_dataset(conn, token_hash, dataset_id, "reviewer")
        current_revision = conn.execute("SELECT version, state FROM revisions WHERE id = ?",
                                        (batch["revision_id"],)).fetchone()
        if (current_dataset["version"] != dataset["version"] or current_revision is None or
                current_revision["version"] != batch["revision_version"] or
                current_revision["state"] == "cerrada"):
            raise Problem(409, "La revisión cambió durante la exportación; reintentá")
        event(conn, current_user["id"], "provisional_exported", "revision", batch["revision_id"])
    return content, digest, manifest

"""P04 administrative controls. Results are evidence, never human decisions or debits."""

from __future__ import annotations

from .revision_scope import revision_table

from collections import Counter, defaultdict
from decimal import Decimal
import hashlib
import json
import sqlite3
from itertools import islice
from tempfile import SpooledTemporaryFile
from uuid import uuid4

from .db import transaction
from .security import now_utc
from .service import Problem, authorized_dataset, check_version, event
from .eligibility import POLICY, effective_row, eligibility_summary
from .dependencies import ALL_RULES, dependency_changes, result_affected
from .consistent_reads import consistent_read


RULES = ALL_RULES
RULE_VERSION = "P06.2-ALC02"
AUTH_RULE_VERSION = 'B04-authorizations-v1'
CENT = Decimal("0.01")


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _snapshot(conn: sqlite3.Connection, dataset_id: str, invoice: sqlite3.Row, *, stored_auth=None) -> dict:
    sources = [dict(row) for row in conn.execute(
        "SELECT id, kind, status, source_sha256, manifest_sha256, cut_label, source_version, "
        "captured_at, coverage_json, metadata_json FROM source_registry WHERE dataset_id = ? ORDER BY id",
        (dataset_id,))]
    comparisons = [dict(row) for row in conn.execute(
        f"SELECT i.id AS import_id, i.revision_id, b.source_sha256 FROM {revision_table(conn, 'invoice_imports')} i "
        "JOIN batches b ON b.id = i.batch_id WHERE b.dataset_id = ? AND i.period = ? "
        "ORDER BY i.id", (dataset_id, invoice["period"]))]
    scope = conn.execute("SELECT h.id, h.source_id, h.provider, h.billing_unit FROM "
                         f"{revision_table(conn, 'batch_provider_scope_history')} h WHERE h.batch_id = ? "
                         "ORDER BY h.ordinal DESC LIMIT 1", (invoice["batch_id"],)).fetchone()
    result = {"rule_version": RULE_VERSION, "revision_id": invoice["revision_id"],
            "import_id": invoice["id"], "invoice_sha256": invoice["source_sha256"],
            "period": invoice["period"], "sheet": invoice["sheet_name"],
            "sources": sources, "comparison_imports": comparisons,
            "provider_scope": dict(scope) if scope else None,
            "eligibility_policy": POLICY,
            "eligibility": eligibility_summary(conn, invoice["id"], invoice["period"]),
            "matching": "literal C+B+complete E+practice date; candidate only"}
    work = [dict(row) for item in comparisons for row in conn.execute(
        "SELECT import_id, source_row, field, latest_change_id FROM work_fields "
        "WHERE import_id = ? ORDER BY source_row, field", (item["import_id"],))]
    if work:
        result["work_values"] = work  # Immutable change IDs identify the effective values.
    from .authorization_matching import dependency_snapshot
    result.update(dependency_snapshot(conn, invoice['batch_id'], invoice['id']))
    from .authorization_controls import dependency_snapshot as authorization_dependencies
    result['rule_versions'] = {rule: AUTH_RULE_VERSION for rule in ('RN09','RN10','RN11')}
    result['rule_versions']['RN19'] = POLICY['version']
    if stored_auth is None:
        result['authorization_engine'] = authorization_dependencies(conn, dataset_id, invoice['batch_id'])
    else:
        from .authorization_controls import verified_dependency_snapshot
        result['authorization_engine'] = verified_dependency_snapshot(conn,dataset_id,invoice['batch_id'],*stored_auth)
    from .economic_applicability import dependency_snapshot as economic_dependencies, VERSION as economic_version
    result['economic_engine'] = economic_dependencies(conn, dataset_id, invoice['batch_id'])
    result['rule_versions'].update({rule: economic_version for rule in ('RN14', 'RN15')})
    return result


def _work_overlay(conn: sqlite3.Connection, imports: list[dict]) -> dict[tuple, dict]:
    overlay = defaultdict(dict)
    for item in imports:
        for row in conn.execute("SELECT import_id, source_row, field, value_json FROM work_fields "
                                "WHERE import_id = ?", (item["import_id"],)):
            overlay[(row["import_id"], row["source_row"])][row["field"]] = json.loads(row["value_json"])
    return overlay


def _duplicate_groups(conn: sqlite3.Connection, imports: list[dict],
                      overlay: dict[tuple, dict], period: str, *, checkpoint=None) -> dict[tuple, list[tuple]]:
    groups = defaultdict(list)
    for item in imports:
        for number, original in enumerate(conn.execute("SELECT source_row, disposition, disposition_reason, practice_date, "
                                     "permitted_json FROM invoice_rows WHERE import_id = ?", (item["import_id"],)), start=1):
            if checkpoint and number % 500 == 0:
                checkpoint()
            row = effective_row(original, period)
            if row["disposition"] != "included":
                continue
            fields = json.loads(row["permitted_json"])
            fields.update(overlay.get((item["import_id"], row["source_row"]), {}))
            key = tuple(str(fields.get(name) or "").strip() for name in ("C", "B", "E")) + (row["practice_date"],)
            if all(key):
                groups[key].append((item["import_id"], row["source_row"]))
    return groups


def evaluate_row(row: sqlite3.Row | dict, *, duplicate_refs: list[tuple],
                 invoice_sha256: str, value_cut: str | None,
                 effective_fields: dict | None = None) -> list[tuple]:
    """Return rule/result/reason/evidence/difference/currency without private field values."""
    source_row = row["source_row"]
    locator = f"Hoja1!{source_row}"
    base = {"source_sha256": invoice_sha256, "locator": locator}
    disposition = row["disposition"]
    if disposition != "included":
        reason = row.get("disposition_reason") if isinstance(row, dict) else row["disposition_reason"]
        reason = reason or ("fuera_del_periodo" if disposition == "excluded" else "alcance_indeterminado")
        base = {**base, "eligibility_version": POLICY["version"],
                "eligibility_reasons": row.get("eligibility_reasons", [reason]) if isinstance(row, dict) else [reason]}
        other = "no_aplicable" if disposition == "excluded" else "no_evaluado"
        results = [(rule, other, reason, base, None, None) for rule in RULES[:-1]]
        results.append(("RN19", "no_aplicable" if disposition == "excluded" else "no_concluyente",
                        reason, {**base, "period_relation": disposition}, None, None))
        return results

    fields = effective_fields if effective_fields is not None else json.loads(row["permitted_json"])
    o, p, q = (Decimal(row[key]) for key in ("honorarios_ars", "derechos_ars", "total_ars"))
    difference = o + p - q
    result13 = "con_indicios" if abs(difference) > CENT else "sin_observaciones"
    reason13 = "diferencia_supera_tolerancia" if result13 == "con_indicios" else "suma_concilia"
    money_evidence = {**base, "cells": [f"O{source_row}", f"P{source_row}", f"Q{source_row}"],
                      "amounts_ars": {"O": str(o), "P": str(p), "Q": str(q)},
                      "tolerance_ars": "0.01", "quantity_not_applied": True}
    code = str(fields.get("E") or "")
    if q != 0:
        zero_result, zero_reason = "no_aplicable", "total_no_cero"
    elif code in {"660001", "661001"}:
        zero_result, zero_reason = "sin_observaciones", "codigo_no_valorizado_admite_cero"
    else:
        zero_result, zero_reason = "no_concluyente", "cero_requiere_referencia_aplicable"
    peers = [(import_id, number) for import_id, number in duplicate_refs
             if import_id != row["import_id"] or number != source_row]
    match_key = [str(fields.get(name) or "").strip() for name in ("C", "B", "E")]
    match_key.append(row["practice_date"])
    duplicate_evidence = {**base, "comparison": "literal_C_B_E_I", "candidate_count": len(peers),
                          "match_key_sha256": hashlib.sha256(_json(match_key).encode("utf-8")).hexdigest(),
                          "other_locators": [{"import_id": imp, "locator": f"Hoja1!{number}"}
                                             for imp, number in peers[:20]],
                          "locators_truncated": len(peers) > 20}
    tariff_evidence = {**base, "value_cut": value_cut, "applicable_price": None,
                       "currency": "unverified", "economic_unit": "unverified"}
    term = row["billing_window"] if "billing_window" in row.keys() else {}
    period_result, period_reason = {
        "in_term": ("sin_observaciones", "facturacion_en_termino"),
        "late": ("con_indicios", "facturacion_fuera_de_termino"),
    }.get(term.get("status"), ("no_concluyente", "plazo_sin_fechas"))
    return [
        ("RN09", "no_concluyente", "autorizaciones_sin_adaptador_validado", base, None, None),
        ("RN10", "no_concluyente", "falta_fecha_incorporacion_por_practica", base, None, None),
        ("RN11", "no_concluyente", "cantidad_autorizada_no_acreditada", base, None, None),
        ("RN12", "sin_observaciones", "importes_de_fila_sin_multiplicar", money_evidence, None, None),
        ("RN13", result13, reason13, money_evidence, str(difference), "ARS"),
        ("RN14", "no_concluyente", "referencia_economica_no_aplicable_aun", tariff_evidence, None, None),
        ("RN15", "no_concluyente", "referencia_arancelaria_insuficiente", tariff_evidence, None, None),
        ("RN16", zero_result, zero_reason, {**base, "cells": [f"E{source_row}", f"Q{source_row}"],
                                             "total_ars": str(q)}, None, None),
        ("RN17", "con_indicios" if peers else "sin_observaciones",
         "coincidencia_estricta_candidata" if peers else "sin_coincidencia_estricta",
         duplicate_evidence, None, None),
        ("RN18", "no_evaluado", "ordenes_validas_no_verificadas", base, None, None),
        ("RN19", period_result, period_reason,
         {**base, "practice_date": row["practice_date"], **term}, None, None),
    ]


def run_controls(conn: sqlite3.Connection, token_hash: str, dataset_id: str,
                 batch_id: str, expected_version: int, *, after_prepare=None, progress=None,
                 before_publish=None, published=None, expected_input_sha256=None) -> tuple[dict, bool]:
    _, visible = authorized_dataset(conn, token_hash, dataset_id, "reviewer")
    check_version(visible, expected_version)
    if progress:
        progress('validating', 0, None)
    # Compute against a WAL read snapshot, staging private results outside the
    # write transaction. Publication is atomic after every permission/version
    # and dependency is checked again. Closing the spool removes staged bytes.
    with SpooledTemporaryFile(max_size=4 * 1024 * 1024, mode="w+t", encoding="utf-8") as staged:
        conn.execute("BEGIN")
        try:
            _, dataset = authorized_dataset(conn, token_hash, dataset_id, "reviewer")
            check_version(dataset, expected_version)
            invoice = conn.execute(
                f"SELECT i.*, b.source_sha256 FROM {revision_table(conn, 'invoice_imports')} i JOIN batches b ON b.id = i.batch_id "
                "WHERE b.id = ? AND b.dataset_id = ?", (batch_id, dataset_id)).fetchone()
            if invoice is None:
                raise Problem(404, "Importación inexistente")
            revision = conn.execute("SELECT state, version FROM revisions WHERE id = ?", (invoice["revision_id"],)).fetchone()
            if revision["state"] == "cerrada":
                raise Problem(409, "La revisión está cerrada")
            snapshot = _snapshot(conn, dataset_id, invoice)
            serialized = _json(snapshot)
            snapshot_sha = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
            if expected_input_sha256 is not None and snapshot_sha != expected_input_sha256:
                raise Problem(409, 'Los datos cambiaron desde la solicitud; iniciar un análisis nuevo')
            total_rows = conn.execute('SELECT count(*) FROM invoice_rows WHERE import_id=?', (invoice['id'],)).fetchone()[0]
            previous = conn.execute("SELECT id FROM control_runs WHERE revision_id = ? "
                                    "AND snapshot_sha256 = ?", (invoice["revision_id"], snapshot_sha)).fetchone()
            if previous is not None:
                existing = _run_summary(conn, dataset_id, previous["id"])
                if existing["freshness"] != "current":
                    raise Problem(409, "La captura anterior requiere actualización; revisar dependencias")
                conn.commit()
                if published:
                    if progress:
                        progress('publishing', 0, total_rows)
                    with transaction(conn):
                        _, current = authorized_dataset(conn, token_hash, dataset_id, 'reviewer')
                        check_version(current, expected_version)
                        current_revision = conn.execute('SELECT state,version FROM revisions WHERE id=?', (invoice['revision_id'],)).fetchone()
                        if current_revision['state']=='cerrada' or current_revision['version']!=revision['version'] or _json(_snapshot(conn,dataset_id,invoice))!=serialized:
                            raise Problem(409, 'La revisión cambió durante la consulta')
                        if before_publish:
                            before_publish(conn)
                        published(conn, previous['id'], False)
                return existing, False
            from .analysis_history import capture_analysis
            run_id = capture_analysis(conn, token_hash, dataset_id, snapshot, serialized, snapshot_sha, expected_version)
            if progress:
                progress('preparing', 0, total_rows)
            overlay = _work_overlay(conn, snapshot["comparison_imports"])
            groups = _duplicate_groups(conn, snapshot["comparison_imports"], overlay, invoice["period"],
                checkpoint=(lambda: progress('preparing', 0, total_rows)) if progress else None)
            from .authorization_controls import Evaluator
            authorizations = Evaluator(conn, dataset_id, batch_id,
                (lambda: progress('preparing', 0, total_rows)) if progress else None)
            value_cuts = [source["cut_label"] for source in snapshot["sources"]
                          if source["kind"] == "values" and source["status"] == "registered"]
            value_cut = value_cuts[0] if len(value_cuts) == 1 else None
            counts = Counter()
            from .economic_applicability import control_results as economic_results
            if progress:
                progress('evaluating', 0, total_rows)
            for number, original in enumerate(conn.execute("SELECT * FROM invoice_rows WHERE import_id = ? ORDER BY source_row", (invoice["id"],)), start=1):
                row = effective_row(original, invoice["period"])
                fields, peers = None, []
                if row["disposition"] == "included":
                    fields = json.loads(row["permitted_json"])
                    fields.update(overlay.get((invoice["id"], row["source_row"]), {}))
                    key = tuple(str(fields.get(name) or "").strip() for name in ("C", "B", "E")) + (row["practice_date"],)
                    peers = groups.get(key, []) if all(key) else []
                authorizations.checkpoint = (lambda: progress('evaluating', number-1, total_rows)) if progress else None
                authorization_results = authorizations.evaluate(row['source_row'], {
                    'source_sha256':invoice['source_sha256'],'locator':f'Hoja1!{row["source_row"]}'}) if row['disposition']=='included' else {}
                economic = economic_results(snapshot['economic_engine']['rows'].get(str(row['source_row'])),
                    {'source_sha256': invoice['source_sha256'], 'locator': f'Hoja1!{row["source_row"]}'},
                    synthetic=snapshot['economic_engine'].get('simulation_only', False)) if row['disposition'] == 'included' else {}
                for rule, result, reason, evidence, difference, currency in evaluate_row(
                        row, duplicate_refs=peers, invoice_sha256=invoice["source_sha256"],
                        value_cut=value_cut, effective_fields=fields):
                    if rule in authorization_results:
                        rule,result,reason,evidence,difference,currency=authorization_results[rule]
                    if rule in economic:
                        rule,result,reason,evidence,difference,currency=economic[rule]
                    rule_version = snapshot['rule_versions'].get(rule, RULE_VERSION)
                    staged.write(_json((run_id, invoice["id"], row["source_row"], rule, rule_version,
                                        result, reason, _json(evidence), difference, currency)) + "\n")
                    counts[(rule, result)] += 1
                if progress and (number % 250 == 0 or number==total_rows):
                    progress('evaluating', number, total_rows)
            if counts[("RN19", "sin_observaciones")] + counts[("RN19", "con_indicios")] != snapshot["eligibility"]["included_count"]:
                raise RuntimeError("La captura no concilia con X1")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        if progress:
            progress('publishing', total_rows, total_rows)
        from .analysis_history import save_prepared
        save_prepared(conn, run_id, staged)
        if after_prepare is not None:
            after_prepare()
        try:
            with transaction(conn):
                user, dataset = authorized_dataset(conn, token_hash, dataset_id, "reviewer")
                check_version(dataset, expected_version)
                current_revision = conn.execute("SELECT state, version FROM revisions WHERE id = ?",
                                                 (invoice["revision_id"],)).fetchone()
                if (current_revision is None or current_revision["state"] == "cerrada" or
                        current_revision["version"] != revision["version"] or
                        _json(_snapshot(conn, dataset_id, invoice)) != serialized):
                    raise Problem(409, "La revisión o sus dependencias cambiaron durante el análisis")
                if before_publish:
                    before_publish(conn)
                conn.execute("INSERT INTO control_runs VALUES (?, ?, ?, ?, ?, ?, 'completed', 'current', ?, ?)",
                             (run_id, dataset_id, invoice["revision_id"], invoice["id"], snapshot_sha,
                              serialized, user["id"], now_utc()))
                conn.execute("UPDATE analysis_history SET state='published',published_run_id=? WHERE id=?", (run_id,run_id))
                staged.seek(0)
                records = (json.loads(line) for line in staged)
                while chunk := list(islice(records, 5000)):
                    conn.executemany("INSERT INTO control_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", chunk)
                conn.execute("UPDATE control_runs SET freshness = 'requires_update' WHERE revision_id = ? "
                             "AND id != ? AND freshness = 'current'", (invoice["revision_id"], run_id))
                from .review import materialize_alerts
                materialize_alerts(conn, run_id)
                conn.execute("UPDATE datasets SET version = version + 1 WHERE id = ?", (dataset_id,))
                conn.execute("UPDATE revisions SET version = version + 1 WHERE id = ?", (invoice["revision_id"],))
                event(conn, user["id"], "controls_completed", "control_run", run_id)
                if published:
                    published(conn, run_id, True)
        except Problem as exc:
            with transaction(conn):
                conn.execute("UPDATE analysis_history SET state='historical',reason_code=? WHERE id=?",
                             ('inputs_changed' if exc.status == 409 else 'access_changed', run_id))
            raise
    return run_summary(conn, token_hash, dataset_id, run_id), True


def run_summary(conn: sqlite3.Connection, token_hash: str, dataset_id: str, run_id: str, *, after_read=None) -> dict:
    return consistent_read(conn,token_hash,dataset_id,lambda:_run_summary(conn,dataset_id,run_id),after_read=after_read)


def _run_summary(conn: sqlite3.Connection, dataset_id: str, run_id: str) -> dict:
    """Summarize inside a caller-authorized, consistent read snapshot."""
    run = conn.execute("SELECT id, revision_id, import_id, snapshot_sha256, snapshot_json, "
                       "technical_state, freshness, created_at FROM control_runs "
                       "WHERE id = ? AND dataset_id = ?", (run_id, dataset_id)).fetchone()
    if run is None:
        raise Problem(404, "Análisis inexistente")
    snapshot = json.loads(run["snapshot_json"])
    invoice = conn.execute(
        f"SELECT i.*, b.source_sha256 FROM {revision_table(conn, 'invoice_imports')} i JOIN batches b ON b.id = i.batch_id "
        "WHERE i.id = ? AND b.dataset_id = ?", (run["import_id"], dataset_id)).fetchone()
    closed = conn.execute("SELECT state FROM revisions WHERE id=?", (run['revision_id'],)).fetchone()['state'] == 'cerrada'
    stored_auth = (snapshot.get('authorization_engine'), hashlib.sha256(run['snapshot_json'].encode()).digest())
    if stored_auth[1].hex()!=run['snapshot_sha256']:
        stored_auth=(None,None)
    current = snapshot if closed else _snapshot(conn,dataset_id,invoice,stored_auth=stored_auth)
    changes = dependency_changes(conn, snapshot, current)
    if closed:
        closure = conn.execute('SELECT manifest_json FROM revision_closures WHERE revision_id=?', (run['revision_id'],)).fetchone()
        frozen = json.loads(closure['manifest_json'])['control_run'] if closure else None
        if frozen and frozen['id'] == run_id:
            changes = {key: frozen[key] for key in ('affected_rules','global_affected_rules','affected_rows')}
            changes['known_dependency_change'] = True
        else:
            changes = {'affected_rules': list(RULES), 'global_affected_rules': list(RULES),
                       'affected_rows': {}, 'known_dependency_change': True}
    if not closed and run["freshness"] == "requires_update" and not changes["affected_rules"] and not changes["known_dependency_change"]:
        changes["global_affected_rules"] = list(RULES)
        changes["affected_rules"] = list(RULES)  # Unknown dependency change: fail closed.
    rows = conn.execute("SELECT rule_code, result, count(*) AS total FROM control_results "
                        "WHERE run_id = ? GROUP BY rule_code, result", (run_id,)).fetchall()
    return {**{k: run[k] for k in run.keys() if k != "snapshot_json"},
            "stored_freshness": run["freshness"],
            "closed_revision": closed,
            "freshness": "requires_update" if changes["affected_rules"] else "current",
            "snapshot": snapshot, **{key: changes[key] for key in
                ("affected_rules", "global_affected_rules", "affected_rows")},
            "counts": [dict(row) for row in rows]}


def list_runs(conn: sqlite3.Connection, token_hash: str, dataset_id: str,
              batch_id: str, *, after_read=None) -> list[dict]:
    return consistent_read(conn,token_hash,dataset_id,lambda:_list_runs(conn,token_hash,dataset_id,batch_id),after_read=after_read)


def _list_runs(conn,token_hash,dataset_id,batch_id):
    authorized_dataset(conn, token_hash, dataset_id, "reviewer")
    runs = conn.execute("SELECT r.id, r.snapshot_sha256, r.technical_state, r.freshness, "
                        f"r.created_at FROM control_runs r JOIN {revision_table(conn, 'invoice_imports')} i ON i.id = r.import_id "
                        "JOIN batches b ON b.id = i.batch_id WHERE b.dataset_id = ? AND b.id = ? AND r.revision_id=i.revision_id "
                        "ORDER BY r.created_at DESC, r.rowid DESC", (dataset_id, batch_id)).fetchall()
    return [{**dict(row), **{key: summary[key] for key in
                            ("freshness", "stored_freshness", "affected_rules", "closed_revision")}}
            for row in runs for summary in [_run_summary(conn, dataset_id, row["id"])]]


def row_results(conn: sqlite3.Connection, token_hash: str, dataset_id: str,
                run_id: str, source_row: int) -> list[dict]:
    summary = run_summary(conn, token_hash, dataset_id, run_id)
    rows = conn.execute("SELECT rule_code, rule_version, result, reason_code, evidence_json, "
                        "difference_ars, currency FROM control_results WHERE run_id = ? "
                        "AND source_row = ? ORDER BY rule_code", (run_id, source_row)).fetchall()
    if not rows:
        raise Problem(404, "Fila sin resultados en este análisis")
    return [{**{k: row[k] for k in row.keys() if k != "evidence_json"},
             "freshness": "requires_update" if result_affected(summary, source_row, row["rule_code"]) else "current",
             "evidence": json.loads(row["evidence_json"])} for row in rows]

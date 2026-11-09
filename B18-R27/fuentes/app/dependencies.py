"""RN28 dependency scope shared by results, decisions and exports."""

from __future__ import annotations

from collections import defaultdict
import json
import sqlite3

from .eligibility import effective_row


ALL_RULES = tuple(f"RN{number:02d}" for number in range(9, 20))
FIELD_RULES = {
    "B": {"RN09", "RN10", "RN11", "RN17", "RN18"},
    "C": {"RN09", "RN10", "RN11", "RN17", "RN18"},
    "E": {"RN09", "RN10", "RN11", "RN14", "RN15", "RN16", "RN17", "RN18"},
    "G": {"RN11", "RN14", "RN15"},
    "K": {"RN09", "RN14", "RN15"},
}


def _group_index(conn: sqlite3.Connection, snapshot: dict) -> tuple[dict, dict]:
    """Reconstruct immutable old/current values, including complete peer sets.

    Using only the displayed 20 peer locators would miss dependencies in larger
    groups. Change IDs in each snapshot point to immutable work_changes records.
    """
    overlay = defaultdict(dict)
    for work in snapshot.get("work_values", []):
        change = conn.execute("SELECT import_id, source_row, field, new_json FROM work_changes WHERE id = ?",
                              (work["latest_change_id"],)).fetchone()
        if change is None or (change["import_id"], change["source_row"], change["field"]) != (
                work["import_id"], work["source_row"], work["field"]):
            raise ValueError("Missing immutable interpretation dependency")
        overlay[(work["import_id"], work["source_row"])][work["field"]] = json.loads(change["new_json"])
    keys, groups = {}, defaultdict(set)
    for imported in snapshot["comparison_imports"]:
        import_id = imported["import_id"]
        for original in conn.execute("SELECT source_row, disposition, disposition_reason, practice_date, "
                                     "permitted_json FROM invoice_rows WHERE import_id = ?", (import_id,)):
            row = effective_row(original, snapshot["period"])
            if row["disposition"] != "included":
                continue
            identity = (import_id, row["source_row"])
            fields = json.loads(row["permitted_json"])
            fields.update(overlay.get(identity, {}))
            key = tuple(str(fields.get(name) or "").strip() for name in ("C", "B", "E")) + (row["practice_date"],)
            if all(key):
                keys[identity] = key
                groups[key].add(identity)
    return keys, groups


def dependency_changes(conn: sqlite3.Connection, old: dict, current: dict) -> dict:
    """Return shared causes and row/control causes for the target import."""
    global_rules = set()
    rows = defaultdict(set)
    economic_bound = (old.get('economic_engine', {}).get('rows', {}).keys() |
                      current.get('economic_engine', {}).get('rows', {}).keys())
    def unbound_economic_changed():
        if not economic_bound:
            global_rules.update(('RN14','RN15'))
        else:
            for row in conn.execute('SELECT source_row FROM invoice_rows WHERE import_id=?', (current['import_id'],)):
                if str(row['source_row']) not in economic_bound:
                    rows[row['source_row']].update(('RN14','RN15'))
    if (old["invoice_sha256"] != current["invoice_sha256"] or
            old["rule_version"] != current["rule_version"] or
            old.get("eligibility_policy") != current.get("eligibility_policy")):
        global_rules.update(ALL_RULES)
    for rule in ALL_RULES:
        if old.get('rule_versions',{}).get(rule,old['rule_version']) != current.get('rule_versions',{}).get(rule,current['rule_version']):
            global_rules.add(rule)
    for kind, rules in (("authorizations", {"RN09", "RN10", "RN11", "RN18"}),
                        ("values", {"RN14", "RN15", "RN16"})):
        if (kind=='authorizations' and old.get('authorization_engine',{}).get('scope') and
                current.get('authorization_engine',{}).get('scope')):
            continue  # Selected captures and affected cohorts define B04 dependencies.
        if [s for s in old["sources"] if s["kind"] == kind] != [s for s in current["sources"] if s["kind"] == kind]:
            # Applicable HPC results capture only their selected source/version.
            global_rules.update(rules - {'RN14','RN15'} if kind == 'values' and
                                old.get('economic_engine') and current.get('economic_engine') else rules)
            if kind == 'values' and old.get('economic_engine') and current.get('economic_engine'):
                unbound_economic_changed()
    before_economic = old.get('economic_engine', {}).get('rows', {})
    after_economic = current.get('economic_engine', {}).get('rows', {})
    if old.get('economic_engine', {}).get('simulation_only') != current.get('economic_engine', {}).get('simulation_only'):
        for number in economic_bound:
            rows[int(number)].update(('RN14','RN15'))
    for number in before_economic.keys() | after_economic.keys():
        if before_economic.get(number) != after_economic.get(number):
            rows[int(number)].update(('RN14','RN15'))
    before_auth=old.get('authorization_engine',{});after_auth=current.get('authorization_engine',{})
    old_auth_rows,new_auth_rows=before_auth.get('rows',{}),after_auth.get('rows',{})
    for number in (() if old_auth_rows is new_auth_rows else old_auth_rows.keys() | new_auth_rows.keys()):
        for rule in ('RN09','RN10','RN11','RN18'):
            if old_auth_rows.get(number,{}).get(rule)!=new_auth_rows.get(number,{}).get(rule):
                rows[int(number)].add(rule)
    if old.get("provider_scope") != current.get("provider_scope"):
        if old.get('economic_engine') and current.get('economic_engine'):
            unbound_economic_changed()
        else:
            global_rules.update(("RN14", "RN15"))
    if old.get('authorization_scope_id') != current.get('authorization_scope_id'):
        global_rules.update(('RN09', 'RN10', 'RN11', 'RN18'))
    old_links = {x['source_row']: x['id'] for x in old.get('authorization_links', [])}
    new_links = {x['source_row']: x['id'] for x in current.get('authorization_links', [])}
    for number in old_links.keys() | new_links.keys():
        if old_links.get(number) != new_links.get(number):
            rows[number].update(('RN09', 'RN10', 'RN11', 'RN18'))
    old_inputs = {(x['source_row'], x['kind']): x['id'] for x in old.get('authorization_inputs', [])}
    new_inputs = {(x['source_row'], x['kind']): x['id'] for x in current.get('authorization_inputs', [])}
    for number, kind in old_inputs.keys() | new_inputs.keys():
        if old_inputs.get((number, kind)) != new_inputs.get((number, kind)):
            rows[number].add('RN10' if kind == 'incorporation' else 'RN11')
    before = {(w["import_id"], w["source_row"], w["field"]): w["latest_change_id"]
              for w in old.get("work_values", [])}
    after = {(w["import_id"], w["source_row"], w["field"]): w["latest_change_id"]
             for w in current.get("work_values", [])}
    changed = {key for key in before.keys() | after.keys() if before.get(key) != after.get(key)}
    for import_id, source_row, field in changed:
        if import_id == current["import_id"]:
            rows[source_row].update(FIELD_RULES[field])
    groups_changed = (old["comparison_imports"] != current["comparison_imports"] or
                      any(field in {"B", "C", "E", "G"} for _, _, field in changed))
    if groups_changed and not {"RN11", "RN17"}.issubset(global_rules):
        try:
            old_keys, old_groups = _group_index(conn, old)
            new_keys, new_groups = _group_index(conn, current)
            changed_quantity = {(import_id, number) for import_id, number, field in changed if field == "G"}
            target = {identity for identity in old_keys.keys() | new_keys.keys()
                      if identity[0] == current["import_id"]}
            for identity in target:
                old_key, new_key = old_keys.get(identity), new_keys.get(identity)
                old_members = old_groups.get(old_key, set())
                new_members = new_groups.get(new_key, set())
                if old_key != new_key or old_members != new_members:
                    rows[identity[1]].update(("RN11", "RN17"))
                elif (old_members | new_members) & changed_quantity:
                    rows[identity[1]].add("RN11")
        except (ValueError, KeyError):
            global_rules.update(("RN11", "RN17"))
    affected_rows = {str(number): sorted(rules - global_rules) for number, rules in rows.items()
                     if rules - global_rules}
    union = global_rules | {rule for rules in affected_rows.values() for rule in rules}
    return {"global_affected_rules": sorted(global_rules), "affected_rows": affected_rows,
            "affected_rules": sorted(union), "known_dependency_change": old != current}


def result_affected(summary: dict, source_row: int, rule_code: str) -> bool:
    return (rule_code in summary["global_affected_rules"] or
            rule_code in summary["affected_rows"].get(str(source_row), []))

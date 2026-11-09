"""Versioned V1 source registry and exact catalog candidate lookup.

Catalog entries are evidence candidates, never applicable prices or debit amounts.
"""

from __future__ import annotations

from datetime import date
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from .db import transaction
from .security import now_utc
from .service import Problem, authorized_dataset, check_version, event
from .storage import publish_bytes, read_verified


CUT = "BASE_2026-10-09"
SOURCE_NAME = "valores_convenios_base_2026-10-09.sqlite"
MANIFEST_NAME = "MANIFIESTO_TFG.json"
MAX_CANDIDATES = 100


def json_safe_catalog_amount(value):
    """Represent malformed legacy values in memory, never rewrite source objects."""
    if isinstance(value, bytes):
        return {'storage_type':'blob', 'byte_count':len(value), 'hex_prefix':value[:64].hex(),
                'sha256':hashlib.sha256(value).hexdigest()}
    if isinstance(value, float) and not math.isfinite(value):
        return {'storage_type':'real', 'literal':str(value)}
    return value


def catalog_amount_literal(value):
    value = json_safe_catalog_amount(value)
    if isinstance(value, dict) and value.get('storage_type') == 'blob':
        return f"BLOB ({value['byte_count']} bytes; SHA-256 {value['sha256']})"
    if isinstance(value, dict) and value.get('storage_type') == 'real':
        return value['literal']
    return str(value) if value is not None else None


def source_db(content: bytes) -> sqlite3.Connection:
    if not content.startswith(b"SQLite format 3\x00"):
        raise ValueError("La fuente de valores no es SQLite")
    conn = sqlite3.connect(":memory:")
    try:
        conn.deserialize(content)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        return conn
    except Exception:
        conn.close()
        raise ValueError("No se pudo leer la fuente SQLite de valores") from None


def validate_values(content: bytes, manifest_bytes: bytes, expected_sha256: str) -> dict:
    digest = hashlib.sha256(content).hexdigest()
    if digest != expected_sha256:
        raise ValueError("El SHA-256 de V1 no coincide con el inventario")
    try:
        manifest = json.loads(manifest_bytes)
        source = manifest["source"]
        entry = manifest["files"][SOURCE_NAME]
        counts = manifest["counts"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError("Manifiesto V1 inválido") from exc
    if (manifest.get("format_version") != 1 or entry.get("sha256") != digest or
            entry.get("bytes") != len(content) or source.get("catalog_captured_at", "")[:10] != "2026-10-09" or
            source.get("platform_current_database_exported") is not False):
        raise ValueError("Procedencia o corte V1 incompatible con BASE_2026-10-09")
    if not isinstance(counts, dict) or any(not re.fullmatch(r"[a-z][a-z0-9_]*", key) for key in counts):
        raise ValueError("Recuentos de tablas V1 inválidos")
    conn = source_db(content)
    try:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Integridad SQLite V1 fallida")
        if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError("Claves foráneas V1 inválidas")
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if tables != set(counts) or len(tables) != 19:
            raise ValueError("Esquema V1 no coincide con el manifiesto")
        for table, expected in counts.items():
            if not isinstance(expected, int) or conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0] != expected:
                raise ValueError("Recuento V1 incompatible con manifiesto")
        inner = conn.execute("SELECT source_project_id, source_commit, source_version, source_captured_at "
                             "FROM hpc_migration_manifest").fetchone()
        if (inner is None or inner["source_project_id"] != source.get("source_project_id") or
                inner["source_commit"] != source.get("source_commit") or
                inner["source_version"] != source.get("source_version") or
                inner["source_captured_at"] != source.get("catalog_captured_at")):
            raise ValueError("Procedencia interna V1 incompatible con manifiesto")
        for tariff in conn.execute("SELECT seq, amount_cents, typeof(amount_cents) AS amount_type FROM hpc_catalog_tariffs"):
            if tariff['amount_type'] != 'integer' or type(tariff['amount_cents']) is not int or tariff['amount_cents'] < 0:
                raise ValueError(f"amount_cents debe ser entero no negativo: hpc_catalog_tariffs.seq={tariff['seq']}")
        for valid_from, valid_until in conn.execute("SELECT valid_from, valid_until FROM hpc_catalog_tariffs"):
            try:
                if date.fromisoformat(valid_from).isoformat() != valid_from:
                    raise ValueError()
                if valid_until is not None and date.fromisoformat(valid_until).isoformat() != valid_until:
                    raise ValueError()
            except (TypeError, ValueError):
                raise ValueError("Fecha declarada de arancel V1 inválida") from None
        unknown_end = conn.execute("SELECT count(*) FROM hpc_catalog_tariffs WHERE valid_until IS NULL").fetchone()[0]
    except sqlite3.Error as exc:
        raise ValueError("Estructura SQLite V1 inválida") from exc
    finally:
        conn.close()
    return {
        "cut_label": CUT,
        "source_version": str(source["source_version"]),
        "captured_at": source["catalog_captured_at"],
        "coverage": {"kind": "catalog_snapshot", "table_counts": counts,
                     "tariffs_without_end_date": unknown_end,
                     "external_current_database_exported": False},
        "metadata": {"source_project_id": source["source_project_id"],
                     "source_commit": source["source_commit"],
                     "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                     "applicability": "unverified", "currency": "unverified",
                     "economic_unit": "unverified"},
    }


def _register_file(conn: sqlite3.Connection, digest: str, byte_count: int, relative: str) -> None:
    prior = conn.execute("SELECT byte_count, relative_path FROM stored_files WHERE sha256 = ?", (digest,)).fetchone()
    if prior is None:
        conn.execute("INSERT INTO stored_files VALUES (?, ?, ?, ?)",
                     (digest, byte_count, relative, now_utc()))
    elif prior["byte_count"] != byte_count or prior["relative_path"] != relative:
        raise RuntimeError("Conflicto de metadatos de archivo almacenado")


def register_values(conn: sqlite3.Connection, root: Path, token_hash: str,
                    dataset_id: str, expected_version: int, content: bytes,
                    manifest_bytes: bytes, expected_sha256: str,
                    after_publish=None) -> tuple[dict, bool]:
    _, visible = authorized_dataset(conn, token_hash, dataset_id, "admin")
    check_version(visible, expected_version)
    try:
        details = validate_values(content, manifest_bytes, expected_sha256)
        source_file = publish_bytes(root, content)
        manifest_file = publish_bytes(root, manifest_bytes)
    except ValueError as exc:
        raise Problem(422, str(exc)) from exc
    if after_publish is not None:
        after_publish()
    with transaction(conn):
        user, current = authorized_dataset(conn, token_hash, dataset_id, "admin")
        check_version(current, expected_version)
        existing = conn.execute("SELECT id, cut_label, source_sha256, manifest_sha256 FROM source_registry "
                                "WHERE dataset_id = ? AND kind = 'values' AND source_sha256 = ?",
                                (dataset_id, source_file[0])).fetchone()
        if existing is not None:
            if existing["manifest_sha256"] != manifest_file[0]:
                raise Problem(409, "El mismo SQLite ya está registrado con otro manifiesto")
            return {"id": existing["id"], "cut_label": existing["cut_label"],
                    "source_sha256": existing["source_sha256"],
                    "dataset_version": expected_version}, False
        _register_file(conn, *source_file)
        _register_file(conn, *manifest_file)
        if conn.execute("SELECT 1 FROM source_registry WHERE dataset_id = ? AND kind = 'authorizations' "
                        "AND status = 'pending'", (dataset_id,)).fetchone() is None:
            pending_id = str(uuid4())
            conn.execute("INSERT INTO source_registry VALUES (?, ?, 'authorizations', 'pending', NULL, NULL, "
                         "NULL, NULL, NULL, NULL, ?, ?, ?, ?)",
                         (pending_id, dataset_id, json.dumps({"scope": "unknown", "extract": "not_received"}),
                          json.dumps({"schema": "unvalidated", "rn10_inclusion_evidence": "pending"}),
                          user["id"], now_utc()))
            event(conn, user["id"], "authorizations_pending", "source", pending_id)
        source_id = str(uuid4())
        conn.execute("INSERT INTO source_registry VALUES (?, ?, 'values', 'registered', ?, ?, 'sqlite-v1', "
                     "?, ?, ?, ?, ?, ?, ?)",
                     (source_id, dataset_id, source_file[0], manifest_file[0],
                      details["cut_label"], details["source_version"], details["captured_at"],
                      json.dumps(details["coverage"], separators=(",", ":")),
                      json.dumps(details["metadata"], separators=(",", ":")),
                      user["id"], now_utc()))
        conn.execute("UPDATE datasets SET version = version + 1 WHERE id = ?", (dataset_id,))
        conn.execute("UPDATE control_runs SET freshness = 'requires_update' WHERE revision_id IN (SELECT id FROM revisions WHERE state != 'cerrada') AND "
                     "dataset_id = ? AND freshness = 'current'", (dataset_id,))
        event(conn, user["id"], "values_source_registered", "source", source_id)
    return {"id": source_id, "cut_label": CUT, "source_sha256": source_file[0],
            "dataset_version": expected_version + 1}, True


def list_sources(conn: sqlite3.Connection, token_hash: str, dataset_id: str) -> list[dict]:
    authorized_dataset(conn, token_hash, dataset_id, "reviewer")
    rows = conn.execute("SELECT id, kind, status, source_sha256, manifest_sha256, format_label, "
                        "cut_label, source_version, captured_at, coverage_json, metadata_json, created_at "
                        "FROM source_registry WHERE dataset_id = ? ORDER BY created_at, id", (dataset_id,)).fetchall()
    return [{**{key: row[key] for key in row.keys() if key not in ("coverage_json", "metadata_json")},
             "coverage": json.loads(row["coverage_json"]),
             "metadata": json.loads(row["metadata_json"])} for row in rows]


def candidate_values(conn: sqlite3.Connection, root: Path, token_hash: str,
                     dataset_id: str, source_id: str, code: str,
                     performed_on: str | None, provider: str | None) -> dict:
    from .consistent_reads import consistent_read
    return consistent_read(conn, token_hash, dataset_id,
        lambda: _candidate_values(conn, root, token_hash, dataset_id, source_id, code, performed_on, provider))


def _candidate_values(conn: sqlite3.Connection, root: Path, token_hash: str,
                     dataset_id: str, source_id: str, code: str,
                     performed_on: str | None, provider: str | None) -> dict:
    authorized_dataset(conn, token_hash, dataset_id, "reviewer")
    row = conn.execute("SELECT * FROM source_registry WHERE id = ? AND dataset_id = ? AND "
                       "kind = 'values' AND status = 'registered'", (source_id, dataset_id)).fetchone()
    if row is None:
        raise Problem(404, "Fuente de valores inexistente")
    if not code or len(code) > 64 or code != code.strip():
        raise Problem(422, "Código completo inválido")
    if provider is not None and (not provider or len(provider) > 80 or provider != provider.strip()):
        raise Problem(422, "ID de prestador inválido")
    if performed_on is not None:
        try:
            if date.fromisoformat(performed_on).isoformat() != performed_on:
                raise ValueError()
        except ValueError:
            raise Problem(422, "Fecha de práctica inválida") from None
    source = source_db(read_verified(root, row["source_sha256"]))
    try:
        criteria = "WHERE code = ?" + (" AND provider = ?" if provider is not None else "")
        params = (code, provider) if provider is not None else (code,)
        code_total = source.execute("SELECT count(*) FROM hpc_catalog_codes " + criteria, params).fetchone()[0]
        tariff_total = source.execute("SELECT count(*) FROM hpc_catalog_tariffs " + criteria, params).fetchone()[0]
        codes = source.execute("SELECT seq, practice_seq, practice_id, code_seq, provider, code, kind, description "
                               "FROM hpc_catalog_codes " + criteria + " ORDER BY seq LIMIT ?",
                               (*params, MAX_CANDIDATES)).fetchall()
        tariffs = source.execute("SELECT seq, id, provider, code, practice_id, amount_cents, "
                                 "valid_from, valid_until, source_id, page, data_json "
                                 "FROM hpc_catalog_tariffs " + criteria + " ORDER BY seq LIMIT ?",
                                 (*params, MAX_CANDIDATES)).fetchall()
        providers = [dict(item) for item in source.execute("SELECT id, name FROM hpc_catalog_providers ORDER BY seq")]
        from .effective_hpc_values import EffectiveHpcValues
        resolver = EffectiveHpcValues(conn, root, dataset_id, source_id)
        tariff_candidates = []
        for item in tariffs:
            raw = json.loads(item["data_json"])
            relation = "not_evaluated"
            if performed_on is not None:
                if performed_on < item["valid_from"]:
                    relation = "before_declared_start"
                elif item["valid_until"] is None:
                    relation = "no_declared_end"
                elif performed_on > item["valid_until"]:
                    relation = "after_declared_end"
                else:
                    relation = "inside_declared_dates"
            tariff_candidates.append({**{key: item[key] for key in item.keys() if key != "data_json"},
                                      "effective_reference": resolver.resolve(dict(item), performed_on) if item["provider"] == "HPC" else None,
                                      "amount_cents": json_safe_catalog_amount(item["amount_cents"]),
                                      "amount_literal": catalog_amount_literal(item["amount_cents"]),
                                      "amount_status": "integer_cents" if type(item["amount_cents"]) is int and item["amount_cents"] >= 0 else "not_interpretable",
                                      "conditions": raw.get("conditions"), "notes": raw.get("notes"),
                                      "temporal_relation": relation,
                                      "source_locator": f"hpc_catalog_tariffs.seq={item['seq']}"})
        local_codes=[]
        if provider in (None,'HPC'):
            from .local_hpc import tariffs as local_tariffs
            for item in local_tariffs(conn,dataset_id,source_id):
                if item['code']!=code:continue
                local_codes.append({'seq':None,'local_id':item['local_id'],'code':item['code'],'provider':'HPC','kind':'local','description':item['description'],'source_locator':item['source_locator']})
                effective=resolver.resolve(item,performed_on)
                tariff_candidates.append({**{k:v for k,v in item.items() if k!='data_json'},'effective_reference':effective,
                    'amount_literal':None,'amount_status':'local_documented_version','conditions':None,'notes':None,
                    'temporal_relation':effective['status']})
            code_total+=len(local_codes);tariff_total+=len(local_codes)
        related = None
        calculated = None
        if provider == 'HPC' and not tariff_candidates:
            from .hpc_catalog_links import CatalogLinks
            from .agreement_declarations import ExploratoryResolver
            exploratory = ExploratoryResolver(resolver,row['source_sha256'])
            related = CatalogLinks(source, source_id, row['source_sha256']).suggestions(code, performed_on, exploratory)
        if provider == 'HPC' and not tariff_candidates and related and related['status'] in {'no_declared_hpc_link','no_linked_hpc_tariff'}:
            from .calculated_nomenclature import CalculatedNomenclature
            calculated=CalculatedNomenclature(source,source_id,row['source_sha256']).references(code,performed_on)
        return {"calculated_nomenclature_references":calculated,"related_hpc_references": related, "source_id": source_id, "cut_label": row["cut_label"],
                "source_sha256": row["source_sha256"], "code_exact": code,
                "provider_filter": provider, "performed_on": performed_on,
                "code_total": code_total, "tariff_total": tariff_total,
                "truncated": code_total > MAX_CANDIDATES or tariff_total > MAX_CANDIDATES,
                "code_candidates": [{**dict(item),
                                     "source_locator": f"hpc_catalog_codes.seq={item['seq']}"} for item in codes]+local_codes,
                "tariff_candidates": tariff_candidates, "providers": providers,
                "money_unit": "cents", "currency": "unverified",
                "economic_unit": "unverified", "applicability": "not_determined"}
    finally:
        source.close()

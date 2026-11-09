"""Compare migrated private data to the coherent pre-v9 backup, hashes only."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3

from app.controls import _run_summary


TABLES = ("datasets", "dataset_access", "stored_files", "batches", "revisions", "invoice_imports",
          "invoice_rows", "source_registry", "control_runs", "control_results", "alerts",
          "review_decisions", "decision_reuses", "work_changes", "work_fields", "proposal_versions",
          "economic_verifications", "evidence_documents", "batch_provider_scopes", "batch_provider_scope_history")


def read_only(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def table_digest(conn: sqlite3.Connection, table: str) -> tuple[int, str]:
    primary = [row["name"] for row in sorted(conn.execute(f"PRAGMA table_info({table})"), key=lambda r: r["pk"])
               if row["pk"]]
    order = ", ".join(f'"{name}"' for name in primary) or "rowid"
    count, digest = 0, hashlib.sha256()
    for row in conn.execute(f'SELECT * FROM "{table}" ORDER BY {order}'):
        digest.update(json.dumps(tuple(row), ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")
        count += 1
    return count, digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--backup", type=Path, required=True)
    args = parser.parse_args()
    current, backup = read_only(args.data_dir / "app.sqlite3"), read_only(args.backup / "app.sqlite3")
    try:
        if (backup.execute("PRAGMA user_version").fetchone()[0],
                current.execute("PRAGMA user_version").fetchone()[0]) != (8, 9):
            raise SystemExit("Esta comprobación requiere esquema 8 en respaldo y 9 actual")
        for table in TABLES:
            if table_digest(current, table) != table_digest(backup, table):
                raise SystemExit(f"Diferencia de contenido tras migración: {table}")
        if current.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise SystemExit("Integridad referencial inválida")
        runs = current.execute("SELECT id, dataset_id FROM control_runs ORDER BY created_at, rowid").fetchall()
        summaries = [_run_summary(current, run["dataset_id"], run["id"]) for run in runs]
        if not summaries or summaries[-1]["freshness"] != "current" or any(
                run["freshness"] != "requires_update" for run in summaries[:-1]):
            raise SystemExit("La vigencia efectiva no identifica las capturas anteriores y actual")
        print(f"Esquema 8 a 9: {len(TABLES)} tablas comparadas por cantidad y SHA-256, sin cambios de contenido; "
              f"{len(runs)} capturas preservadas, anteriores afectadas y última vigente; cero errores FK.")
    finally:
        current.close()
        backup.close()


if __name__ == "__main__":
    main()

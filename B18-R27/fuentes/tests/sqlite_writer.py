"""Minimal spawn target: acquire SQLite writer without importing the web/test app."""

from pathlib import Path

from app.db import connect


def hold_writer(root: str, ready, release) -> None:
    conn = connect(Path(root))
    try:
        conn.execute('BEGIN IMMEDIATE')
        ready.set()
        if not release.wait(20):
            raise RuntimeError('Contention test release timed out')
        conn.rollback()
    finally:
        conn.close()

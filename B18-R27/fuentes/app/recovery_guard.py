"""Fail closed on restored directories before opening a writable connection."""
import hashlib
import json
from pathlib import Path
import sqlite3


def recovery_status(root: Path) -> bool:
    """Return True for activated restores, whose workers remain disabled.

    Markers are operator-owned metadata, not an authentication boundary against
    somebody able to rewrite the database and its files.
    """
    root = Path(root).resolve()
    markers = ('RECOVERY_PENDING.json', 'RECOVERY_READY.json', 'RECOVERY_ACTIVATED.json')
    try:
        if not any((root / name).exists() for name in markers):
            manifest = root / 'manifest.json'
            if not manifest.exists():
                return False
            metadata = json.loads(manifest.read_text())
            if not isinstance(metadata, dict):
                raise ValueError('Invalid manifest')
            # Offline schema-upgrade backups also contain a manifest. Their
            # schema/objects format is not a recovery archive or activation.
            if (metadata.get('format') != 'TFG-recovery-v1' and
                    not (root / 'access.json').exists() and not (root / 'application.zip').exists()):
                return False
        ready = json.loads((root / 'RECOVERY_READY.json').read_text())
        receipt = json.loads((root / 'RECOVERY_ACTIVATED.json').read_text())
        manifest_sha = hashlib.sha256((root / 'manifest.json').read_bytes()).hexdigest()
        if (ready['format'] != 'TFG-recovery-v1' or ready['manifest_sha256'] != manifest_sha or
                receipt['manifest_sha256'] != manifest_sha or receipt['workers_enabled'] is not False or
                type(receipt['sessions_revoked']) is not int or receipt['sessions_revoked'] < 0):
            raise ValueError('Invalid recovery receipt')
        conn = sqlite3.connect((root / 'app.sqlite3').as_uri() + '?mode=ro', uri=True)
        try:
            event = conn.execute("SELECT 1 FROM audit_events WHERE action='recovery_sessions_revoked' "
                                 "AND entity_type='recovery' AND entity_id=? AND occurred_at=?",
                                 (manifest_sha, receipt['activated_at'])).fetchone()
            if event is None:
                raise ValueError('Activation was not committed')
        finally:
            conn.close()
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        raise RuntimeError('Directorio de recuperación sin activación segura verificada') from exc
    return True

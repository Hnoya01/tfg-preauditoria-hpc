"""TP session and password policy for individual accounts."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import hmac
import secrets
import sqlite3
from uuid import uuid4

from argon2 import PasswordHasher, Type
from argon2.exceptions import VerifyMismatchError, VerificationError

from .db import database_path, transaction


SESSION_HOURS = 8
IDLE_MINUTES = 20
LOCK_MINUTES = 15
PASSWORD_HASHER = PasswordHasher(time_cost=2, memory_cost=19 * 1024,
                                 parallelism=1, hash_len=32, salt_len=16, type=Type.ID)
DUMMY_HASH = PASSWORD_HASHER.hash("nonexistent-account-dummy-password")
COMMON = {line.strip().casefold() for line in
          (Path(__file__).parent / "common_passwords.txt").read_text(encoding="utf-8").splitlines()
          if line.strip() and not line.startswith("#")}


class AccountLocked(Exception):
    pass


def now() -> datetime:
    return datetime.now(timezone.utc)


def now_utc() -> str:
    return now().isoformat(timespec="seconds")


def validate_password(password: str) -> None:
    if not 15 <= len(password) <= 128 or password.casefold() in COMMON:
        raise ValueError("La contraseña debe tener entre 15 y 128 caracteres y no ser común")


def create_user(conn: sqlite3.Connection, username: str, password: str, role: str) -> str:
    username = username.strip()
    if not username or len(username) > 80:
        raise ValueError("Nombre de usuario inválido")
    validate_password(password)
    if role not in {"admin", "reviewer", "viewer"}:
        raise ValueError("Rol inválido")
    user_id = str(uuid4())
    with transaction(conn):
        conn.execute(
            "INSERT INTO users(id, username, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, username, PASSWORD_HASHER.hash(password), role, now_utc()),
        )
        conn.execute(
            "INSERT INTO audit_events VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid4()), user_id, "account_created", "user", user_id, now_utc()),
        )
    return user_id


def authenticate(conn: sqlite3.Connection, username: str, password: str, origin: str) -> sqlite3.Row | None:
    key = username.strip().casefold()
    cutoff = (now() - timedelta(minutes=LOCK_MINUTES)).isoformat(timespec="seconds")
    user_failures = conn.execute(
        "SELECT count(*) FROM login_failures WHERE username_key = ? AND failed_at > ?", (key, cutoff)
    ).fetchone()[0]
    origin_failures = conn.execute(
        "SELECT count(*) FROM login_failures WHERE origin_key = ? AND failed_at > ?", (origin, cutoff)
    ).fetchone()[0]
    if user_failures >= 5 or origin_failures >= 30:
        raise AccountLocked()
    user = conn.execute("SELECT * FROM users WHERE username = ? COLLATE NOCASE AND active = 1", (username,)).fetchone()
    try:
        valid = PASSWORD_HASHER.verify(user["password_hash"] if user else DUMMY_HASH, password)
    except (VerifyMismatchError, VerificationError):
        valid = False
    if user is None or not valid:
        with transaction(conn):
            conn.execute(
                "INSERT INTO login_failures VALUES (?, ?, ?, ?)", (str(uuid4()), key, origin, now_utc())
            )
            conn.execute(
                "INSERT INTO audit_events VALUES (?, NULL, 'login_denied', 'authentication', 'local', ?)",
                (str(uuid4()), now_utc()),
            )
        return None
    with transaction(conn):
        conn.execute("DELETE FROM login_failures WHERE username_key = ?", (key,))
        conn.execute("INSERT INTO audit_events VALUES (?, ?, 'login_success', 'user', ?, ?)",
                     (str(uuid4()), user["id"], user["id"], now_utc()))
    return user


def issue_session(conn: sqlite3.Connection, user_id: str) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    started = now()
    expires = (started + timedelta(hours=SESSION_HOURS)).isoformat(timespec="seconds")
    with transaction(conn):
        conn.execute(
            "INSERT INTO sessions(token_hash, user_id, csrf_token, created_at, last_active_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (token_hash, user_id, csrf, started.isoformat(timespec="seconds"),
             started.isoformat(timespec="seconds"), expires),
        )
    return token, csrf


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def current_session(conn: sqlite3.Connection, token_hash: str, *, touch: bool = False) -> sqlite3.Row | None:
    instant = now()
    cutoff = (instant - timedelta(minutes=IDLE_MINUTES)).isoformat(timespec="seconds")
    user = conn.execute(
        "SELECT u.id, u.username, u.role, s.csrf_token, s.expires_at FROM sessions s "
        "JOIN users u ON u.id = s.user_id "
        "WHERE s.token_hash = ? AND s.expires_at > ? AND s.last_active_at > ? AND u.active = 1",
        (token_hash, instant.isoformat(timespec="seconds"), cutoff),
    ).fetchone()
    if user is not None and touch:
        conn.execute("UPDATE sessions SET last_active_at = ? WHERE token_hash = ?",
                     (instant.isoformat(timespec="seconds"), token_hash))
    return user


def csrf_valid(session: sqlite3.Row, supplied: str | None) -> bool:
    return supplied is not None and hmac.compare_digest(session["csrf_token"], supplied)


def refresh_activity_if_available(data_root: Path, token_hash: str) -> bool:
    """Persist recent validated activity without waiting for SQLite's writer.

    This optional operation cannot extend a revoked/expired session, and a
    skipped refresh never makes an otherwise available read fail. Authentication
    still checks the persisted idle and absolute deadlines on every request.
    """
    instant = now()
    stamp = instant.isoformat(timespec="seconds")
    cutoff = (instant - timedelta(minutes=IDLE_MINUTES)).isoformat(timespec="seconds")
    throttle = (instant - timedelta(minutes=1)).isoformat(timespec="seconds")
    conn = None
    try:
        conn = sqlite3.connect(database_path(data_root), timeout=0, isolation_level=None)
        # Avoid acquiring a write lock at all if the session was refreshed recently.
        due = conn.execute("SELECT 1 FROM sessions s JOIN users u ON u.id = s.user_id "
                           "WHERE s.token_hash = ? AND s.last_active_at > ? AND s.last_active_at < ? "
                           "AND s.expires_at > ? AND u.active = 1", (token_hash, cutoff, throttle, stamp)).fetchone()
        if due is None:
            return False
        result = conn.execute("UPDATE sessions SET last_active_at = ? WHERE token_hash = ? "
                              "AND last_active_at > ? AND last_active_at < ? AND expires_at > ? "
                              "AND user_id IN (SELECT id FROM users WHERE active = 1)",
                              (stamp, token_hash, cutoff, throttle, stamp))
        return result.rowcount == 1
    except sqlite3.Error:
        return False
    finally:
        if conn is not None:
            conn.close()

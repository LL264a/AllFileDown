"""
Security helpers for Allfiledown.

Small, dependency-free primitives used by HTTP routes and the internal file
server: safe path joining, revocable opaque tokens, and structured audit logs.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.database import get_db


_PASSWORD_ALGORITHM = "pbkdf2_sha256"
_PASSWORD_ITERATIONS = 260_000


def hash_password(password: str) -> str:
    """Hash a web login password for storage using PBKDF2-HMAC-SHA256."""
    salt = secrets.token_urlsafe(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        _PASSWORD_ITERATIONS,
    ).hex()
    return f"{_PASSWORD_ALGORITHM}${_PASSWORD_ITERATIONS}${salt}${digest}"


def is_password_hash(stored_password: str) -> bool:
    """Return True when *stored_password* uses the supported hash envelope."""
    parts = stored_password.split("$", 3)
    return len(parts) == 4 and parts[0] == _PASSWORD_ALGORITHM


def verify_password(password: str, stored_password: str) -> bool:
    """Verify a plaintext password against a hashed or legacy plaintext value."""
    if not stored_password:
        return False
    if not is_password_hash(stored_password):
        return hmac.compare_digest(password, stored_password)

    try:
        algorithm, iterations_raw, salt, expected = stored_password.split("$", 3)
        if algorithm != _PASSWORD_ALGORITHM:
            return False
        iterations = int(iterations_raw)
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            iterations,
        ).hex()
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def needs_password_rehash(stored_password: str) -> bool:
    """Return True for legacy plaintext or lower-iteration password hashes."""
    if not is_password_hash(stored_password):
        return bool(stored_password)
    try:
        _, iterations_raw, _, _ = stored_password.split("$", 3)
        return int(iterations_raw) < _PASSWORD_ITERATIONS
    except (ValueError, TypeError):
        return True


class PathSecurityError(ValueError):
    """Raised when an untrusted path would escape an allowed root."""


def safe_join(root: str | Path, *parts: str | Path) -> Path:
    """Resolve *parts under *root* and reject absolute/traversal escapes."""
    root_path = Path(root).resolve()
    candidate = root_path
    for part in parts:
        part_path = Path(str(part))
        if part_path.is_absolute():
            raise PathSecurityError("absolute paths are not allowed")
        if any(segment == ".." for segment in part_path.parts):
            raise PathSecurityError("parent traversal is not allowed")
        candidate = candidate / part_path

    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root_path)
    except ValueError as exc:
        raise PathSecurityError("path escapes allowed root") from exc
    return resolved


def token_hash(token: str) -> str:
    """Return a stable SHA-256 hash for storing opaque bearer tokens."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _expires_iso(days: int) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


def _is_active_expiry(expires_at: str | None) -> bool:
    if not expires_at:
        return True
    try:
        return datetime.fromisoformat(expires_at) > datetime.now(UTC)
    except ValueError:
        return False


def create_web_session(user_id: str = "admin", *, expires_days: int = 30, db: Any | None = None) -> str:
    """Create a revocable web session and return the plaintext token once."""
    token = secrets.token_urlsafe(32)
    conn = db or get_db()
    conn.execute(
        "INSERT INTO web_sessions (token_hash, user_id, created_at, expires_at, revoked_at) VALUES (?, ?, ?, ?, NULL)",
        (token_hash(token), user_id, _utc_now_iso(), _expires_iso(expires_days)),
    )
    conn.commit()
    return token


def verify_web_session(token: str, *, db: Any | None = None) -> bool:
    """Return True when token maps to a non-revoked, non-expired session."""
    if not token:
        return False
    conn = db or get_db()
    row = conn.execute(
        "SELECT expires_at, revoked_at FROM web_sessions WHERE token_hash = ?",
        (token_hash(token),),
    ).fetchone()
    return bool(row and row["revoked_at"] is None and _is_active_expiry(row["expires_at"]))


def revoke_web_session(token: str, *, db: Any | None = None) -> bool:
    """Revoke a web session token."""
    if not token:
        return False
    conn = db or get_db()
    cur = conn.execute(
        "UPDATE web_sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
        (_utc_now_iso(), token_hash(token)),
    )
    conn.commit()
    return cur.rowcount > 0


def create_api_token(name: str = "default", *, revoke_existing: bool = True, db: Any | None = None) -> str:
    """Create a revocable API token; optionally revoke all active predecessors."""
    token = secrets.token_urlsafe(32)
    conn = db or get_db()
    now = _utc_now_iso()
    if revoke_existing:
        conn.execute("UPDATE api_tokens SET revoked_at = ? WHERE revoked_at IS NULL", (now,))
    conn.execute(
        "INSERT INTO api_tokens (name, token_hash, created_at, revoked_at) VALUES (?, ?, ?, NULL)",
        (name, token_hash(token), now),
    )
    conn.commit()
    return token


def verify_api_token(token: str, *, db: Any | None = None) -> bool:
    """Return True when token maps to a non-revoked API token."""
    if not token:
        return False
    conn = db or get_db()
    row = conn.execute(
        "SELECT revoked_at FROM api_tokens WHERE token_hash = ?",
        (token_hash(token),),
    ).fetchone()
    return bool(row and row["revoked_at"] is None)


def add_audit_log(
    action: str,
    *,
    actor: str = "system",
    target: str = "",
    payload: dict[str, Any] | None = None,
    ip: str = "",
    db: Any | None = None,
) -> None:
    """Insert a structured audit event."""
    conn = db or get_db()
    columns = {row[1] for row in conn.execute("PRAGMA table_info(audit_logs)").fetchall()}
    payload_json = json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)
    if "event_type" in columns:
        conn.execute(
            "INSERT INTO audit_logs (event_type, actor_node, target_node, payload, created_at) VALUES (?, ?, ?, ?, ?)",
            (action, actor, target, payload_json, _utc_now_iso()),
        )
    else:
        conn.execute(
            "INSERT INTO audit_logs (action, actor, target, payload, ip, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (action, actor, target, payload_json, ip, _utc_now_iso()),
        )
    conn.commit()

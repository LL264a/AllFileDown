from __future__ import annotations

from pathlib import Path

import pytest


def test_safe_join_allows_child_path(tmp_path: Path) -> None:
    from app.security import safe_join

    root = tmp_path / "downloads"
    root.mkdir()
    assert safe_join(root, "task-1", "file.txt") == root / "task-1" / "file.txt"


@pytest.mark.parametrize(
    "parts",
    [
        ("..", "secret.txt"),
        ("task", "..", "secret.txt"),
        ("/etc/passwd",),
    ],
)
def test_safe_join_rejects_escape(tmp_path: Path, parts: tuple[str, ...]) -> None:
    from app.security import PathSecurityError, safe_join

    root = tmp_path / "downloads"
    root.mkdir()
    with pytest.raises(PathSecurityError):
        safe_join(root, *parts)


def test_session_tokens_are_random_hashed_and_revocable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.database
    from app.database import get_db, init_db
    from app.security import create_web_session, revoke_web_session, verify_web_session

    monkeypatch.setattr(app.database, "DB_PATH", tmp_path / "test.db")
    app.database._local.conn = None
    init_db()

    token = create_web_session("admin", expires_days=1)
    assert len(token) >= 32
    assert verify_web_session(token) is True

    db = get_db()
    row = db.execute("SELECT token_hash FROM web_sessions").fetchone()
    assert row is not None
    assert row["token_hash"] != token

    assert revoke_web_session(token) is True
    assert verify_web_session(token) is False


def test_api_tokens_regenerate_revokes_previous(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.database
    from app.database import init_db
    from app.security import create_api_token, verify_api_token

    monkeypatch.setattr(app.database, "DB_PATH", tmp_path / "test.db")
    app.database._local.conn = None
    init_db()

    old = create_api_token("initial", revoke_existing=True)
    assert verify_api_token(old) is True
    new = create_api_token("rotated", revoke_existing=True)
    assert verify_api_token(new) is True
    assert verify_api_token(old) is False


def test_audit_log_records_structured_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.database
    from app.database import get_db, init_db
    from app.security import add_audit_log

    monkeypatch.setattr(app.database, "DB_PATH", tmp_path / "test.db")
    app.database._local.conn = None
    init_db()

    add_audit_log("auth.login", actor="admin", target="web", payload={"ok": True}, ip="127.0.0.1")
    row = get_db().execute("SELECT * FROM audit_logs WHERE action = ?", ("auth.login",)).fetchone()
    assert row is not None
    assert row["actor"] == "admin"
    assert row["target"] == "web"
    assert '"ok": true' in row["payload"]


def test_password_hash_verification_and_legacy_plaintext() -> None:
    from app.security import hash_password, is_password_hash, verify_password

    encoded = hash_password("secret-password")
    assert encoded.startswith("pbkdf2_sha256$")
    assert is_password_hash(encoded) is True
    assert encoded != "secret-password"
    assert verify_password("secret-password", encoded) is True
    assert verify_password("wrong", encoded) is False
    assert verify_password("legacy-password", "legacy-password") is True
    assert verify_password("wrong", "legacy-password") is False

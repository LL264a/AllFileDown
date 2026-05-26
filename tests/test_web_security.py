from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any

import pytest
from fastapi import Request
from starlette.datastructures import Headers


def _reset_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.database

    monkeypatch.setattr(app.database, "DB_PATH", tmp_path / "test.db")
    app.database._local.conn = None
    app.database.init_db()


def test_check_auth_accepts_session_and_rejects_revoked_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_db(tmp_path, monkeypatch)

    from app.security import create_web_session, revoke_web_session
    import app.web.routes as routes

    monkeypatch.setitem(routes.config, "web_password", "secret-password")
    token = create_web_session("admin")

    scope: dict[str, Any] = {"type": "http", "headers": Headers({"cookie": f"afd_token={token}"}).raw}
    assert routes._check_auth(Request(scope)) is True

    revoke_web_session(token)
    assert routes._check_auth(Request(scope)) is False


def test_api_key_regenerate_revokes_old_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_db(tmp_path, monkeypatch)

    from app.security import create_api_token
    import app.web.routes as routes

    monkeypatch.setitem(routes.config, "web_password", "secret-password")
    old = create_api_token("old", revoke_existing=True)
    new = create_api_token("new", revoke_existing=True)

    old_scope: dict[str, Any] = {"type": "http", "headers": Headers({"x-api-key": old}).raw}
    new_scope: dict[str, Any] = {"type": "http", "headers": Headers({"x-api-key": new}).raw}
    assert routes._check_auth(Request(old_scope)) is False
    assert routes._check_auth(Request(new_scope)) is True


def test_legacy_cookie_can_be_revoked_by_password_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_db(tmp_path, monkeypatch)

    import app.web.routes as routes

    monkeypatch.setitem(routes.config, "web_password", "secret-password")
    token = hashlib.sha256("secret-password_afd_session".encode()).hexdigest()
    scope: dict[str, Any] = {"type": "http", "headers": Headers({"cookie": f"afd_token={token}"}).raw}
    assert routes._check_auth(Request(scope)) is False


def test_safe_task_file_path_rejects_traversal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.web.routes as routes
    from app.security import PathSecurityError

    root = tmp_path / "downloads"
    root.mkdir()
    monkeypatch.setitem(routes.config, "download_dir", str(root))

    assert routes._safe_download_file_path("task1", "file.txt") == root / "task1" / "file.txt"
    with pytest.raises(PathSecurityError):
        routes._safe_download_file_path("..", "secret.txt")
    with pytest.raises(PathSecurityError):
        routes._safe_download_file_path("task1", "../secret.txt")


def test_change_password_stores_hash_revokes_sessions_and_removes_saved_auth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _reset_db(tmp_path, monkeypatch)

    import app.web.routes as routes
    from app.security import create_web_session, is_password_hash, verify_password

    saved: dict[str, Any] = {}

    def fake_save_config(cfg: dict[str, Any]) -> None:
        saved.update(cfg)

    monkeypatch.setitem(routes.config, "web_password", "old-secret")
    monkeypatch.setattr(routes, "save_config", fake_save_config)
    token = create_web_session("admin")

    scope: dict[str, Any] = {
        "type": "http",
        "method": "POST",
        "path": "/api/auth/change-password",
        "headers": Headers({"cookie": f"afd_token={token}", "content-type": "application/json"}).raw,
    }

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b'{"current_password":"old-secret","new_password":"new-secret"}'}

    result = asyncio.run(routes.api_auth_change_password(Request(scope, receive)))
    assert result == {"success": True, "clear_saved_auth": True}
    assert is_password_hash(saved["web_password"]) is True
    assert verify_password("new-secret", saved["web_password"]) is True
    assert routes._check_auth(Request({"type": "http", "headers": Headers({"cookie": f"afd_token={token}"}).raw})) is False


def test_login_upgrades_legacy_plaintext_password_to_hash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_db(tmp_path, monkeypatch)

    import app.web.routes as routes
    from app.security import is_password_hash, verify_password

    saved: dict[str, Any] = {}

    def fake_save_config(cfg: dict[str, Any]) -> None:
        saved.update(cfg)

    monkeypatch.setitem(routes.config, "web_password", "legacy-secret")
    monkeypatch.setattr(routes, "save_config", fake_save_config)

    scope: dict[str, Any] = {
        "type": "http",
        "method": "POST",
        "path": "/api/auth/login",
        "headers": Headers({"content-type": "application/json"}).raw,
    }

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b'{"username":"admin","password":"legacy-secret"}'}

    result = asyncio.run(routes.api_auth_login(Request(scope, receive)))
    assert result["authenticated"] is True
    assert is_password_hash(saved["web_password"]) is True
    assert verify_password("legacy-secret", saved["web_password"]) is True

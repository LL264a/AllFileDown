from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import RedirectResponse
from starlette.datastructures import Headers


def _json_request(payload: dict[str, Any]) -> Request:
    body = json.dumps(payload).encode()
    scope: dict[str, Any] = {
        "type": "http",
        "method": "POST",
        "path": "/api/setup",
        "headers": Headers({"content-type": "application/json"}).raw,
    }

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": body}

    return Request(scope, receive)


def test_initialized_detection_requires_flag_username_and_password(monkeypatch) -> None:
    import app.web.routes as routes

    monkeypatch.setattr(routes, "config", {"initialized": False, "web_username": "admin", "web_password": "hash"})
    assert routes._is_initialized() is False

    monkeypatch.setattr(routes, "config", {"initialized": True, "web_username": "", "web_password": "hash"})
    assert routes._is_initialized() is False

    monkeypatch.setattr(routes, "config", {"initialized": True, "web_username": "admin", "web_password": "hash"})
    assert routes._is_initialized() is True

    monkeypatch.setattr(routes, "config", {"web_username": "admin", "web_password": "legacy"})
    assert routes._is_initialized() is True


def test_normalize_public_base_adds_port_only_for_raw_host() -> None:
    import app.web.routes as routes

    assert routes._normalize_public_base("8.135.77.191", 18790) == "http://8.135.77.191:18790"
    assert routes._normalize_public_base("afd.example.com", 18790) == "http://afd.example.com:18790"
    assert routes._normalize_public_base("https://afd.example.com", 18790) == "https://afd.example.com"
    assert routes._normalize_public_base("http://afd.example.com/", 18790) == "http://afd.example.com"


def test_setup_redirects_protected_pages_when_uninitialized(monkeypatch) -> None:
    import app.web.routes as routes

    monkeypatch.setattr(routes, "config", {"initialized": False, "web_username": "", "web_password": ""})
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    response = routes._setup_redirect_if_needed(request)
    assert isinstance(response, RedirectResponse)
    assert response.headers["location"] == "/setup"


def test_api_setup_validates_required_fields(monkeypatch, tmp_path: Path) -> None:
    import app.web.routes as routes

    monkeypatch.setattr(routes, "config", {"initialized": False, "port": 18790})
    monkeypatch.setattr(routes, "save_config", lambda cfg: None)

    result = asyncio.run(routes.api_setup(_json_request({"username": "admin"})))
    assert result["success"] is False
    assert "密码" in result["error"] or "必填" in result["error"]

    result = asyncio.run(
        routes.api_setup(
            _json_request(
                {
                    "username": "admin",
                    "password": "secret1",
                    "password_confirm": "secret2",
                    "download_dir": str(tmp_path),
                    "node_id": "rr",
                    "node_name": "R.R.",
                    "public_host": "8.135.77.191",
                }
            )
        )
    )
    assert result == {"success": False, "error": "两次密码不一致"}


def test_api_setup_saves_initialized_config_with_hashed_password(monkeypatch, tmp_path: Path) -> None:
    import app.web.routes as routes
    from app.security import is_password_hash, verify_password

    saved: dict[str, Any] = {}

    def fake_save_config(cfg: dict[str, Any]) -> None:
        saved.update(cfg)

    download_dir = tmp_path / "downloads"
    monkeypatch.setattr(routes, "config", {"initialized": False, "port": 18790, "aria2": {"host": "127.0.0.1"}})
    monkeypatch.setattr(routes, "save_config", fake_save_config)
    monkeypatch.setattr(routes, "add_audit_log", lambda *args, **kwargs: None)

    result = asyncio.run(
        routes.api_setup(
            _json_request(
                {
                    "username": "root",
                    "password": "secret-password",
                    "password_confirm": "secret-password",
                    "download_dir": str(download_dir),
                    "node_id": "rr",
                    "node_name": "R.R.",
                    "public_host": "8.135.77.191",
                }
            )
        )
    )

    assert result == {"success": True, "redirect": "/login"}
    assert saved["initialized"] is True
    assert saved["web_username"] == "root"
    assert saved["node_id"] == "rr"
    assert saved["node_name"] == "R.R."
    assert saved["download_dir"] == str(download_dir)
    assert saved["public_base_url"] == "http://8.135.77.191:18790"
    assert saved["file_base_url"] == "http://8.135.77.191:18790/tasks"
    assert download_dir.is_dir()
    assert is_password_hash(saved["web_password"]) is True
    assert verify_password("secret-password", saved["web_password"]) is True


def test_api_setup_refuses_when_already_initialized(monkeypatch, tmp_path: Path) -> None:
    import app.web.routes as routes

    monkeypatch.setattr(routes, "config", {"initialized": True, "web_username": "admin", "web_password": "hash"})
    result = asyncio.run(routes.api_setup(_json_request({})))
    assert result == {"success": False, "error": "系统已初始化"}

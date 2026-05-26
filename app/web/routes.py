"""
Allfiledown — Web 页面路由
"""

from __future__ import annotations

import asyncio
import logging
import ssl
from pathlib import Path
from typing import Any

import aiohttp
import hashlib
import hmac
import secrets
from urllib.parse import urlparse
from fastapi import APIRouter, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import config, save_config
from app.database import get_db
from app.security import (
    PathSecurityError,
    add_audit_log,
    create_api_token,
    create_web_session,
    hash_password,
    needs_password_rehash,
    revoke_web_session,
    safe_join,
    verify_api_token,
    verify_password,
    verify_web_session,
)

logger = logging.getLogger("afd")

router: APIRouter = APIRouter()
templates: Jinja2Templates = Jinja2Templates(
    directory=str(Path(__file__).parent / "templates"),
)


# ── Auth helpers ──
_AUTH_COOKIE = "afd_session"


def _make_session_token() -> str:
    return secrets.token_hex(32)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _safe_download_file_path(task_id: str, filename: str) -> Path:
    return safe_join(config["download_dir"], task_id, filename)


def _auth_cookie_token(request: Request) -> str:
    return request.cookies.get(_AUTH_COOKIE, "") or request.cookies.get("afd_token", "")


def _verify_password(input_pw: str, stored_pw: str) -> bool:
    """验证 Web 登录密码；兼容旧版明文配置。"""
    return verify_password(input_pw, stored_pw)


def _upgrade_password_hash_if_needed(password: str, stored_pw: str) -> None:
    """登录成功后把旧明文密码自动升级为加密哈希。"""
    if not stored_pw or not needs_password_rehash(stored_pw):
        return
    config["web_password"] = hash_password(password)
    save_config(config)


def _check_auth(request: Request) -> bool:

    """检查是否已登录"""
    pw: str = str(config.get("web_password", ""))
    if not pw:
        return True  # 无密码时不验证
    # Revocable session cookie
    if verify_web_session(_auth_cookie_token(request)):
        return True
    # Header token remains password-derived for non-browser helpers, but is not persisted.
    body_token: str = request.headers.get("X-Auth-Token", "")
    if body_token and hmac.compare_digest(body_token, hashlib.sha256(pw.encode()).hexdigest()):
        return True
    # Revocable API token validation.
    key_from_header: str = request.headers.get("X-Api-Key", request.headers.get("apikey", ""))
    ckey: str = request.cookies.get("afd_apikey", "")
    if verify_api_token(key_from_header) or verify_api_token(ckey):
        return True
    return False


def _login_redirect() -> RedirectResponse:
    return RedirectResponse(url="/login", status_code=302)


def _is_initialized() -> bool:
    """Return True when the web UI has completed first-run setup."""
    username = str(config.get("web_username", "")).strip()
    password = str(config.get("web_password", "")).strip()
    if not username or not password:
        return False
    return bool(config.get("initialized", True))


def _setup_redirect_if_needed(request: Request) -> RedirectResponse | None:
    """Redirect protected browser pages to setup until first-run config exists."""
    if _is_initialized() or request.url.path == "/setup":
        return None
    return RedirectResponse(url="/setup", status_code=302)


def _normalize_public_base(public_host: str, port: int) -> str:
    """Normalize a raw host or absolute URL into a public base URL."""
    raw = public_host.strip().rstrip("/")
    if raw.startswith(("http://", "https://")):
        parsed = urlparse(raw)
        if not parsed.netloc:
            raise ValueError("公网地址格式错误")
        return raw
    if not raw or "://" in raw or "/" in raw:
        raise ValueError("公网地址格式错误")
    return f"http://{raw}:{port}"


def _validate_setup_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name}为必填")
    return text


async def _apply_setup_payload(data: dict[str, Any]) -> dict[str, Any]:
    username = _validate_setup_text(data.get("username"), "用户名")
    password = str(data.get("password", ""))
    password_confirm = str(data.get("password_confirm", ""))
    download_dir = _validate_setup_text(data.get("download_dir"), "下载路径")
    node_id = _validate_setup_text(data.get("node_id"), "节点 ID")
    node_name = _validate_setup_text(data.get("node_name"), "节点名称")
    public_host = _validate_setup_text(data.get("public_host"), "公网地址")

    if len(password) < 6:
        raise ValueError("密码至少 6 位")
    if password != password_confirm:
        raise ValueError("两次密码不一致")

    download_path = Path(download_dir).expanduser()
    if not download_path.is_absolute():
        raise ValueError("下载路径必须是绝对路径")
    download_path.mkdir(parents=True, exist_ok=True)

    port = int(config.get("port", 18790))
    public_base = _normalize_public_base(public_host, port)

    config.update(
        {
            "initialized": True,
            "web_username": username,
            "web_password": hash_password(password),
            "download_dir": str(download_path),
            "node_id": node_id,
            "node_name": node_name,
            "host": public_host,
            "peer_host": public_host,
            "public_base_url": public_base,
            "file_base_url": f"{public_base}/tasks",
        }
    )
    save_config(config)
    add_audit_log("setup.complete", actor=username, target="web", payload={"node_id": node_id})
    return {"success": True, "redirect": "/login"}


def _format_file_size(bytes_val: int | None) -> str:
    """格式化文件大小显示"""
    if not bytes_val or bytes_val == 0:
        return "未知"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    size = float(bytes_val)
    while size >= 1024 and i < len(units) - 1:
        size /= 1024
        i += 1
    return f"{size:.1f} {units[i]}"


def _resolve_public_host(host: str) -> str:
    """修复 0.0.0.0 和 localhost 为可访问的地址"""
    if host in ("0.0.0.0", "127.0.0.1", "localhost"):
        return str(config.get("peer_host", config.get("host", "localhost")))
    return host


# ---- 页面路由 ----


# ---- Auth 路由 ----


@router.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request) -> HTMLResponse:
    """首次初始化页面。"""
    if _is_initialized():
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse(
        request,
        "setup.html",
        {
            "default_username": str(config.get("web_username", "admin") or "admin"),
            "default_download_dir": str(config.get("download_dir", "/data/TrAr") or "/data/TrAr"),
            "default_node_id": str(config.get("node_id", "") or ""),
            "default_node_name": str(config.get("node_name", "") or ""),
            "default_public_host": str(config.get("public_base_url", config.get("host", "")) or ""),
        },
    )


@router.post("/api/setup")
async def api_setup(request: Request) -> dict[str, Any]:
    """保存首次初始化配置。"""
    if _is_initialized():
        return {"success": False, "error": "系统已初始化"}
    try:
        data: dict[str, Any] = await request.json()
        return await _apply_setup_payload(data)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    except OSError as exc:
        return {"success": False, "error": f"下载路径不可用：{exc}"}


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    """登录页"""
    setup_redirect = _setup_redirect_if_needed(request)
    if setup_redirect:
        return setup_redirect
    return templates.TemplateResponse(request, "login.html", {})


@router.post("/api/auth/login")
async def api_auth_login(request: Request) -> dict[str, Any]:
    """登录验证"""
    data: dict[str, Any] = await request.json()
    username: str = data.get("username", "admin")
    password: str = data.get("password", "")
    stored_pw: str = str(config.get("web_password", ""))

    if not stored_pw:
        add_audit_log("auth.login.disabled", actor=username, target="web", ip=_client_ip(request))
        return {"authenticated": True, "redirect": "/"}

    if _verify_password(password, stored_pw):
        _upgrade_password_hash_if_needed(password, stored_pw)
        add_audit_log("auth.login.success", actor=username, target="web", ip=_client_ip(request))
        return {"authenticated": True, "redirect": "/"}
    add_audit_log("auth.login.failure", actor=username, target="web", ip=_client_ip(request))
    return {"authenticated": False, "error": "用户名或密码错误"}


@router.post("/api/auth/verify")
async def api_auth_verify(request: Request) -> dict[str, Any]:
    """验证已保存的凭据（记住密码时使用）"""
    if _check_auth(request):
        return {"authenticated": True, "redirect": "/"}
    data: dict[str, Any] = await request.json()
    stored_pw: str = str(config.get("web_password", ""))
    pw: str = data.get("password", "")
    if stored_pw and _verify_password(pw, stored_pw):
        _upgrade_password_hash_if_needed(pw, stored_pw)
        return {"authenticated": True, "redirect": "/"}
    return {"authenticated": False}


@router.post("/api/auth/session")
async def api_auth_session(request: Request) -> dict[str, Any]:
    """登录后设置 session cookie（持久化登录状态）"""
    data: dict[str, Any] = await request.json()
    pw: str = data.get("password", "")
    stored_pw: str = str(config.get("web_password", ""))
    if stored_pw and _verify_password(pw, stored_pw):
        _upgrade_password_hash_if_needed(pw, stored_pw)
        token: str = create_web_session(str(data.get("username", "admin")))
        add_audit_log("auth.session.create", actor=str(data.get("username", "admin")), target="web", ip=_client_ip(request))
        return {"authenticated": True, "token": token}
    add_audit_log("auth.session.failure", actor=str(data.get("username", "admin")), target="web", ip=_client_ip(request))
    return {"authenticated": False}


@router.post("/api/auth/logout")
async def api_auth_logout(request: Request) -> dict[str, Any]:
    """撤销当前 session cookie。"""
    revoked = revoke_web_session(_auth_cookie_token(request))
    add_audit_log("auth.session.revoke", actor="admin", target="web", payload={"revoked": revoked}, ip=_client_ip(request))
    return {"success": True, "revoked": revoked}


@router.post("/api/auth/change-password")
async def api_auth_change_password(request: Request) -> dict[str, Any]:
    """修改密码"""
    if not _check_auth(request):
        return {"error": "未登录"}
    data: dict[str, Any] = await request.json()
    cur: str = data.get("current_password", "")
    new_pw: str = data.get("new_password", "")
    stored_pw: str = str(config.get("web_password", ""))
    if not _verify_password(cur, stored_pw):
        return {"error": "当前密码错误"}
    if len(new_pw) < 6:
        return {"error": "新密码至少 6 位"}
    if new_pw == cur:
        return {"error": "新密码不能与当前密码相同"}
    config["web_password"] = hash_password(new_pw)
    save_config(config)
    db = get_db()
    db.execute("UPDATE web_sessions SET revoked_at = datetime('now') WHERE revoked_at IS NULL")
    db.commit()
    add_audit_log("auth.password.change", actor="admin", target="web", ip=_client_ip(request))
    return {"success": True, "clear_saved_auth": True}


@router.post("/api/auth/api-key")
async def api_auth_api_key(request: Request) -> dict[str, Any]:
    """获取或重新生成 API 密钥"""
    if not _check_auth(request):
        return {"error": "未登录"}
    data: dict[str, Any] = await request.json()
    action: str = data.get("action", "get")
    if action == "regenerate":
        api_key: str = create_api_token("default", revoke_existing=True)
        config["api_key"] = ""  # plaintext API keys are now DB-backed and revocable
        save_config(config)
        add_audit_log("auth.api_key.regenerate", actor="admin", target="api", ip=_client_ip(request))
        return {"success": True, "api_key": api_key}
    return {"api_key": ""}


# ---- 受保护页面路由 ----


def _protect(request: Request) -> HTMLResponse | None:
    """检查初始化和登录，未满足时返回重定向。"""
    setup_redirect = _setup_redirect_if_needed(request)
    if setup_redirect:
        return setup_redirect
    pw: str = str(config.get("web_password", ""))
    if pw and not _check_auth(request):
        # 检查 sessionStorage/localStorage token 通过 header 传递
        auth_header: str = request.headers.get("X-Auth-Token", "")
        if auth_header:
            expected: str = hashlib.sha256(pw.encode()).hexdigest()
            if hmac.compare_digest(auth_header, expected):
                return None
        return _login_redirect()
    return None


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    r = _protect(request)
    if r:
        return r
    return templates.TemplateResponse(
        request,
        "files.html",
        {
            "node_id": str(config["node_id"]),
            "node_name": str(config["node_name"]),
        },
    )


@router.get("/test-ui", response_class=HTMLResponse)
@router.get("/test-ui/{full_path:path}", response_class=HTMLResponse)
async def test_ui_page(request: Request) -> HTMLResponse:
    """UI 优化测试页（直接输出，避免 Jinja2 处理 JS 模板字面量）"""
    tmpl_dir = Path(__file__).parent / "templates" / "test-ui"
    tmpl_file = tmpl_dir / "test.html"
    if tmpl_file.exists():
        content = tmpl_file.read_text(encoding="utf-8")
        return HTMLResponse(content=content)
    return HTMLResponse(content="<h1>404 - 测试页面未找到</h1>", status_code=404)


@router.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}












@router.get("/downloads", response_class=HTMLResponse)
async def downloads_page(request: Request) -> HTMLResponse:
    r = _protect(request)
    if r:
        return r
    return templates.TemplateResponse(
        request,
        "downloads.html",
        {
            "node_id": str(config["node_id"]),
            "node_name": str(config["node_name"]),
        },
    )


@router.get("/nodes", response_class=HTMLResponse)
async def nodes_page(request: Request) -> HTMLResponse:
    r = _protect(request)
    if r:
        return r
    return templates.TemplateResponse(
        request,
        "nodes.html",
        {
            "node_id": str(config["node_id"]),
            "node_name": str(config["node_name"]),
            "download_dir": str(config["download_dir"]),
        },
    )


@router.get("/stations", response_class=HTMLResponse)
async def stations_page(request: Request) -> HTMLResponse:
    r = _protect(request)
    if r:
        return r
    return templates.TemplateResponse(
        request,
        "stations.html",
        {
            "node_id": str(config["node_id"]),
            "node_name": str(config["node_name"]),
        },
    )


@router.get("/files", response_class=HTMLResponse)
async def files_page(request: Request) -> HTMLResponse:
    """文件库别名，保持一致"""
    return await index(request)


# ---- API 路由 ----


@router.post("/api/task/create")
async def create_task(request: Request) -> JSONResponse:
    """创建下载任务"""
    data: dict[str, Any] = await request.json()
    url: str = data.get("url", "")
    filename: str | None = data.get("filename")

    if not url:
        logger.warning("Task create failed: no URL provided, data=%s", data)
        return JSONResponse({"error": "URL is required"}, status_code=400)

    from app.agent.orchestrator import orchestrator

    if orchestrator is None:
        return JSONResponse({"error": "Orchestrator not available"}, status_code=503)

    logger.info("Creating task: url=%s... filename=%s", url[:80], filename)
    task_id: str = await orchestrator.create_task(url, filename)
    logger.info("Task created: %s", task_id)
    return JSONResponse({"task_id": task_id, "status": "created"})


@router.get("/api/task/list")
async def list_tasks() -> dict[str, Any]:
    """列出所有下载任务"""
    from app.agent.orchestrator import orchestrator

    if orchestrator is None:
        return {"tasks": []}
    tasks: list[dict[str, Any]] = await orchestrator.get_task_list()
    return {"tasks": tasks}


@router.get("/api/task/{task_id}")
async def task_detail(task_id: str) -> Any:
    """获取单个任务详情"""
    from app.agent.orchestrator import orchestrator

    if orchestrator is None:
        return JSONResponse({"error": "Orchestrator not available"}, status_code=503)
    detail: dict[str, Any] | None = await orchestrator.get_task_detail(task_id)
    if not detail:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return detail


@router.get("/api/task/{task_id}/overview")
async def task_nodes_overview(task_id: str) -> Any:
    """查询所有节点的任务状态（包括远程节点）"""
    from app.agent.orchestrator import orchestrator

    if orchestrator is None:
        return JSONResponse({"error": "Orchestrator not available"}, status_code=503)

    local: dict[str, Any] | None = await orchestrator.get_task_detail(task_id)
    if not local:
        return JSONResponse({"error": "Not found"}, status_code=404)

    node_map: dict[str, dict[str, Any]] = {}
    for n in local.get("nodes", []):
        node_map[n["node_id"]] = n

    peers: list[dict[str, Any]] = config.get("peers", [])
    local_node_id: str = config.get("node_id", "")

    async def fetch_peer(peer: dict[str, Any]) -> None:
        peer_id: str = peer.get("id", "")
        if peer_id == local_node_id:
            return
        host: str = peer.get("host", "")
        port: int = int(peer.get("port", 18790))
        url: str = f"http://{host}:{port}/api/task/{task_id}"
        try:
            async with (
                aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as session,
                session.get(url) as resp,
            ):
                if resp.status == 200:
                    data: dict[str, Any] = await resp.json()
                    for n in data.get("nodes", []):
                        nid: str = n["node_id"]
                        if nid not in node_map:
                            node_map[nid] = n
                        else:
                            node_map[nid].update(n)
        except Exception:
            node_map[peer_id] = {
                "node_id": peer_id,
                "node_name": peer.get("name", peer_id),
                "progress": 0,
                "download_speed": 0,
                "status": "offline",
                "gid": None,
            }

    await asyncio.gather(*[fetch_peer(p) for p in peers])

    merged: dict[str, Any] = dict(local)
    merged["nodes"] = list(node_map.values())
    return merged


@router.post("/api/node/add")
async def add_node(request: Request) -> Any:
    """添加新节点"""
    data: dict[str, Any] = await request.json()
    node_id: str = data.get("node_id", "")
    name: str = data.get("name", "")
    host: str = data.get("host", "")
    port: int = int(data.get("port", 18790))
    node_type: str = data.get("node_type", "full")
    auth_token: str = data.get("auth_token", "")

    if not node_id or not name or not host:
        return JSONResponse({"error": "Missing required fields"}, status_code=400)

    db = get_db()
    db.execute(
        "INSERT OR REPLACE INTO nodes (id, name, host, port, node_type, auth_token, status) "
        "VALUES (?, ?, ?, ?, ?, ?, 'unknown')",
        (node_id, name, host, port, node_type, auth_token),
    )
    db.commit()

    # 也更新到 config.peers
    peers: list[dict[str, Any]] = config.get("peers", [])
    peers = [p for p in peers if p.get("id") != node_id]
    peers.append(
        {
            "id": node_id,
            "name": name,
            "host": host,
            "port": port,
            "node_type": node_type,
            "auth_token": auth_token,
        }
    )
    config["peers"] = peers
    save_config(config)

    return {"status": "added", "node_id": node_id}


@router.post("/api/node/remove")
async def remove_node(request: Request) -> Any:
    """移除节点"""
    data: dict[str, Any] = await request.json()
    node_id: str = data.get("node_id", "")
    if not node_id:
        return JSONResponse({"error": "node_id required"}, status_code=400)

    db = get_db()
    db.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
    db.commit()

    config["peers"] = [p for p in config.get("peers", []) if p.get("id") != node_id]
    save_config(config)
    return {"status": "removed"}


@router.get("/api/files")
async def list_files() -> dict[str, Any]:
    """列出所有已完成的下载文件（含多节点下载源）"""
    db = get_db()
    rows = db.execute("""
        SELECT t.id, t.filename, t.url, t.total_size, t.status, t.created_at, t.updated_at,
               tn.local_path, tn.node_id, tn.internal_url
        FROM tasks t
        JOIN task_nodes tn ON tn.task_id = t.id
        WHERE t.status IN ('completed', 'all_completed', 'seeding')
        AND tn.local_path IS NOT NULL AND tn.local_path != ''
        ORDER BY t.updated_at DESC
    """).fetchall()

    file_map: dict[str, dict[str, Any]] = {}
    for row in rows:
        r: dict[str, Any] = dict(row)
        task_id: str = r["id"]
        path: str = r.get("local_path", "")
        size: int = r.get("total_size", 0)
        filename: str = r.get("filename") or (path.split("/")[-1] if path else "unknown")
        node_id: str = r.get("node_id", "")
        internal_url: str = r.get("internal_url", "")

        if task_id not in file_map:
            file_map[task_id] = {
                "task_id": task_id,
                "filename": filename,
                "url": r["url"],
                "size": size,
                "size_formatted": _format_file_size(size),
                "status": r["status"],
                "downloaded_at": r["updated_at"],
                "sources": [],
            }

        # 修复 0.0.0.0 的 URL
        if internal_url and internal_url.startswith("http://0.0.0.0"):
            internal_url = internal_url.replace(
                "http://0.0.0.0",
                f"http://{_resolve_public_host(config.get('host', 'localhost'))}",
            )

        local_download: str = f"/tasks/{task_id}/{filename}"

        node_row = db.execute("SELECT name FROM nodes WHERE id = ?", (node_id,)).fetchone()
        node_label: str = (
            node_row["name"]
            if node_row
            else (str(config.get("node_name", "")) if node_id == config.get("node_id", "") else node_id)
        )

        is_local: bool = node_id == config.get("node_id", "")
        download_url: str = local_download if is_local else (internal_url or local_download)

        source: dict[str, Any] = {
            "node_id": node_id,
            "node_label": node_label,
            "download_url": download_url,
            "is_local": is_local,
        }
        file_map[task_id]["sources"].append(source)

    files: list[dict[str, Any]] = list(file_map.values())
    for f in files:
        local_sources: list[dict[str, Any]] = [s for s in f["sources"] if s["is_local"]]
        remote_sources: list[dict[str, Any]] = [s for s in f["sources"] if not s["is_local"]]
        preferred: list[dict[str, Any]] = local_sources + remote_sources
        if preferred:
            f["download_url"] = preferred[0]["download_url"]
            f["from_node"] = preferred[0]["node_id"]
        else:
            f["download_url"] = ""
            f["from_node"] = ""
        f["multi_source"] = len(f["sources"]) > 1

    return {"files": files, "total": len(files)}


@router.post("/api/node/update")
async def update_node(request: Request) -> Any:
    """更新节点信息"""
    data: dict[str, Any] = await request.json()
    node_id: str = data.get("node_id", "")
    if not node_id:
        return JSONResponse({"error": "node_id required"}, status_code=400)

    db = get_db()
    existing = db.execute("SELECT id FROM nodes WHERE id = ?", (node_id,)).fetchone()
    if not existing:
        return JSONResponse({"error": "Node not found"}, status_code=404)

    updates: list[str] = []
    params: list[Any] = []
    field_map: dict[str, str] = {
        "name": "name",
        "host": "host",
        "port": "port",
        "node_type": "node_type",
        "auth_token": "auth_token",
        "save_path": "save_path",
    }
    for field, col in field_map.items():
        if field in data:
            updates.append(f"{col} = ?")
            params.append(data[field])

    if updates:
        params.append(node_id)
        db.execute(f"UPDATE nodes SET {', '.join(updates)} WHERE id = ?", params)
        db.commit()

    return {"status": "updated", "node_id": node_id}


@router.get("/api/browse")
async def browse_directory(path: str = "/") -> Any:
    """列出指定目录下的子目录"""
    try:
        p: Path = safe_join(config.get("browse_root", "/"), path.lstrip("/")) if path != "/" else Path(config.get("browse_root", "/")).resolve()
        if not p.is_dir():
            return JSONResponse({"error": "not a directory", "path": str(p)}, status_code=400)
        items: list[dict[str, Any]] = []
        for entry in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            if entry.is_dir():
                try:
                    sub: list[Any] = list(entry.iterdir())
                    item_count: int = len(sub)
                except PermissionError:
                    item_count = -1
                items.append(
                    {
                        "name": entry.name,
                        "path": str(entry),
                        "type": "dir",
                        "items": item_count,
                    }
                )
        parent: str | None = str(p.parent) if p.parent != p else None
        return {"path": str(p), "parent": parent, "items": items}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/api/browse/mkdir")
async def create_directory(request: Request) -> Any:
    """创建新目录"""
    data: dict[str, Any] = await request.json()
    dir_path: str = data.get("path", "")
    if not dir_path:
        return JSONResponse({"error": "path required"}, status_code=400)
    try:
        p: Path = safe_join(config.get("browse_root", "/"), dir_path.lstrip("/")) if dir_path != "/" else Path(config.get("browse_root", "/")).resolve()
        p.mkdir(parents=True, exist_ok=True)
        add_audit_log("file.mkdir", actor="admin", target=str(p), ip=_client_ip(request))
        return {"status": "created", "path": str(p)}
    except PathSecurityError:
        return JSONResponse({"error": "invalid path"}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/tasks/{task_id}/{filename}")
async def serve_local_file(task_id: str, filename: str) -> Any:
    """通过 Web 端口提供文件下载"""
    download_dir: Path = Path(config["download_dir"])
    try:
        file_path: Path = _safe_download_file_path(task_id, filename)
    except PathSecurityError:
        logger.warning("File download rejected: task=%s file=%s", task_id, filename)
        return JSONResponse({"error": "Invalid path"}, status_code=400)
    if not file_path.exists() or not file_path.is_file():
        logger.warning("File download 404: task=%s file=%s path=%s", task_id, filename, file_path)
        return JSONResponse({"error": "File not found"}, status_code=404)
    logger.info("File download: task=%s file=%s", task_id, filename)
    return FileResponse(str(file_path))


@router.post("/api/task/cancel")
async def cancel_task(request: Request) -> Any:
    """取消下载任务"""
    data: dict[str, Any] = await request.json()
    task_id: str = data.get("task_id", "")
    if not task_id:
        return JSONResponse({"error": "task_id required"}, status_code=400)
    from app.agent.orchestrator import orchestrator

    if orchestrator is None:
        return JSONResponse({"error": "Orchestrator not available"}, status_code=503)
    result: dict[str, Any] = await orchestrator.cancel_task(task_id)
    return result


@router.post("/api/task/delete")
async def delete_task(request: Request) -> Any:
    """删除任务"""
    data: dict[str, Any] = await request.json()
    task_id: str = data.get("task_id", "")
    if not task_id:
        return JSONResponse({"error": "task_id required"}, status_code=400)
    from app.agent.orchestrator import orchestrator

    if orchestrator is None:
        return JSONResponse({"error": "Orchestrator not available"}, status_code=503)
    result: dict[str, Any] = await orchestrator.delete_task(task_id)
    return result


@router.post("/api/task/clear-completed")
async def clear_completed() -> dict[str, Any]:
    """清理已完成任务"""
    from app.agent.orchestrator import orchestrator

    if orchestrator is None:
        return {"error": "Orchestrator not available"}
    result: dict[str, Any] = await orchestrator.clear_completed()
    return result


@router.post("/api/task/pause")
async def pause_task(request: Request) -> Any:
    """暂停任务"""
    data: dict[str, Any] = await request.json()
    task_id: str = data.get("task_id", "")
    if not task_id:
        return JSONResponse({"error": "task_id required"}, status_code=400)
    from app.agent.orchestrator import orchestrator

    if orchestrator is None:
        return JSONResponse({"error": "Orchestrator not available"}, status_code=503)
    result: dict[str, Any] = await orchestrator.pause_task(task_id)
    return result


@router.post("/api/task/resume")
async def resume_task(request: Request) -> Any:
    """恢复暂停的任务"""
    data: dict[str, Any] = await request.json()
    task_id: str = data.get("task_id", "")
    if not task_id:
        return JSONResponse({"error": "task_id required"}, status_code=400)
    from app.agent.orchestrator import orchestrator

    if orchestrator is None:
        return JSONResponse({"error": "Orchestrator not available"}, status_code=503)
    result: dict[str, Any] = await orchestrator.resume_task(task_id)
    return result


@router.post("/api/task/retry")
async def retry_task(request: Request) -> Any:
    """重新下载失败的任务"""
    data: dict[str, Any] = await request.json()
    task_id: str = data.get("task_id", "")
    if not task_id:
        return JSONResponse({"error": "task_id required"}, status_code=400)
    from app.agent.orchestrator import orchestrator

    if orchestrator is None:
        return JSONResponse({"error": "Orchestrator not available"}, status_code=503)
    result: dict[str, Any] = await orchestrator.retry_task(task_id)
    return result


@router.get("/api/preview/{task_id}/{filename}")
async def preview_file(task_id: str, filename: str) -> Any:
    """文件预览（文本/图片）"""
    download_dir: Path = Path(config["download_dir"])
    try:
        file_path: Path = _safe_download_file_path(task_id, filename)
    except PathSecurityError:
        return JSONResponse({"error": "Invalid path"}, status_code=400)
    if not file_path.exists() or not file_path.is_file():
        return JSONResponse({"error": "File not found"}, status_code=404)

    ext: str = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    text_exts: set[str] = {
        "txt",
        "md",
        "json",
        "yml",
        "yaml",
        "xml",
        "csv",
        "log",
        "cfg",
        "conf",
        "ini",
        "toml",
        "sh",
        "py",
        "js",
        "ts",
        "html",
        "css",
    }
    image_exts: set[str] = {"jpg", "jpeg", "png", "gif", "webp", "svg"}

    if ext in image_exts:
        return FileResponse(str(file_path))
    elif ext in text_exts:
        content: str = file_path.read_text(encoding="utf-8", errors="replace")
        escaped: str = content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        body_css: str = (
            "background:#111;color:#e8e8e8;font:14px/1.5 monospace;"
            "padding:20px;white-space:pre-wrap;word-break:break-all;"
        )
        html: str = (
            '<!DOCTYPE html>\n<html lang="zh-CN">'
            '<head><meta charset="UTF-8">'
            f"<style>{body_css}</style>"
            "</head><body><pre>" + escaped + "</pre></body></html>"
        )
        return HTMLResponse(html)
    else:
        return JSONResponse({"error": "Preview not available for this file type"}, status_code=400)


@router.post("/api/file/rename")
async def rename_file(request: Request) -> Any:
    """重命名文件"""
    data: dict[str, Any] = await request.json()
    task_id: str = data.get("task_id", "")
    new_name: str = data.get("new_name", "")
    if not task_id or not new_name:
        return JSONResponse({"error": "task_id and new_name required"}, status_code=400)

    db = get_db()
    row = db.execute(
        "SELECT local_path FROM task_nodes WHERE task_id = ? AND local_path IS NOT NULL",
        (task_id,),
    ).fetchone()
    if not row or not row["local_path"]:
        return JSONResponse({"error": "File not found on disk"}, status_code=404)

    old_path: Path = Path(row["local_path"]).resolve()
    try:
        new_path: Path = safe_join(old_path.parent, new_name)
    except PathSecurityError:
        return JSONResponse({"error": "Invalid filename"}, status_code=400)
    if new_path.exists():
        return JSONResponse({"error": "Target filename already exists"}, status_code=409)

    old_path.rename(new_path)
    db.execute(
        "UPDATE task_nodes SET local_path = ? WHERE task_id = ?",
        (str(new_path), task_id),
    )
    db.execute(
        "UPDATE tasks SET filename = ? WHERE id = ?",
        (new_name, task_id),
    )
    db.commit()
    add_audit_log("file.rename", actor="admin", target=task_id, payload={"old": str(old_path), "new": str(new_path)})
    return {"status": "renamed", "filename": new_name}


@router.get("/api/stations")
async def get_stations() -> dict[str, Any]:
    """获取所有节点（站点）的实时统计信息"""
    db = get_db()
    rows = db.execute("SELECT * FROM nodes ORDER BY name").fetchall()
    nodes: list[dict[str, Any]] = [dict(r) for r in rows]

    ssl_ctx: ssl.SSLContext = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    # 本地节点 — 从 aria2 获取实时速度
    local_node_id: str = config.get("node_id", "")
    local_speed_download: int = 0
    local_speed_upload: int = 0
    local_active: int = 0
    local_waiting: int = 0
    local_stopped: int = 0

    try:
        from app.agent.downloader import get_global_stat

        gs: dict[str, Any] | None = await get_global_stat()
        if gs:
            local_speed_download = int(gs.get("downloadSpeed", 0))
            local_speed_upload = int(gs.get("uploadSpeed", 0))
            local_active = int(gs.get("numActive", 0))
            local_waiting = int(gs.get("numWaiting", 0))
            local_stopped = int(gs.get("numStopped", 0))
    except Exception:
        logger.debug("Failed to get aria2 global stat", exc_info=True)

    # 健康检查
    async def check_node(n: dict[str, Any]) -> tuple[str, str]:
        nid: str = n["id"]
        host: str = str(n.get("host", ""))
        port: int = int(n.get("port", 18790))
        if nid == local_node_id:
            return (nid, "online")
        if not host:
            return (nid, "offline")
        try:
            async with (
                aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=3),
                ) as session,
                session.get(f"http://{host}:{port}/health", ssl=ssl_ctx) as resp,
            ):
                return (nid, "online" if resp.status == 200 else "offline")
        except Exception:
            return (nid, "offline")

    check_results: list[Any] = await asyncio.gather(
        *[check_node(n) for n in nodes],
        return_exceptions=True,
    )
    node_status_map: dict[str, str] = {}
    for r in check_results:
        if isinstance(r, tuple) and len(r) == 2:
            node_status_map[r[0]] = r[1]

    # 更新 DB
    for nid, status in node_status_map.items():
        db.execute("UPDATE nodes SET status = ? WHERE id = ?", (status, nid))
    db.commit()

    stations: list[dict[str, Any]] = []
    for n in nodes:
        node_id: str = n["id"]
        is_local: bool = node_id == local_node_id
        checked_status: str = node_status_map.get(node_id, str(n.get("status", "unknown")))

        # 对远程在线节点，拉取真实任务数据
        remote_tasks_data: dict[str, Any] | None = None
        if not is_local and checked_status == "online":
            host: str = str(n.get("host", ""))
            port: int = int(n.get("port", 18790))
            auth_token: str = str(n.get("auth_token", ""))
            try:
                async with aiohttp.ClientSession() as session:
                    headers: dict[str, str] = {"X-Auth-Token": auth_token} if auth_token else {}
                    async with session.get(
                        f"http://{host}:{port}/api/task/status",
                        ssl=ssl_ctx,
                        timeout=aiohttp.ClientTimeout(total=5),
                        headers=headers,
                    ) as resp:
                        if resp.status == 200:
                            remote_tasks_data = await resp.json()
            except Exception:
                pass

        # 任务统计
        status_map: dict[str, int] = {}
        active_tasks_raw: list[dict[str, Any]] = []

        if remote_tasks_data and isinstance(remote_tasks_data, dict) and "tasks" in remote_tasks_data:
            tasks_list: list[dict[str, Any]] = remote_tasks_data["tasks"]
            for t in tasks_list:
                st: str = t.get("status", "unknown")
                if st == "all_completed":
                    status_map["completed"] = status_map.get("completed", 0) + 1
                else:
                    status_map[st] = status_map.get(st, 0) + 1

                is_active: bool = st in ("downloading", "pending", "paused")
                if is_active or (st == "all_completed" and len(active_tasks_raw) < 5):
                    active_tasks_raw.append(
                        {
                            "id": t["id"],
                            "filename": t.get("filename") or t["url"].split("/")[-1] or t["id"],
                            "progress": (t.get("nodes") or [{}])[0].get("progress", 0) if t.get("nodes") else 0,
                            "status": st,
                            "gid": (t.get("nodes") or [{}])[0].get("gid", "") if t.get("nodes") else "",
                        }
                    )

            db.execute("UPDATE nodes SET last_seen = datetime('now') WHERE id = ?", (node_id,))
        else:
            task_counts = db.execute(
                """
                SELECT tn.status, COUNT(*) as cnt
                FROM task_nodes tn WHERE tn.node_id = ?
                GROUP BY tn.status
            """,
                (node_id,),
            ).fetchall()

            status_map = {r["status"]: r["cnt"] for r in task_counts}

            active_tasks_raw = [
                dict(r)
                for r in db.execute(
                    """
                    SELECT t.id, t.filename, t.url, tn.progress, tn.status, tn.gid
                    FROM task_nodes tn
                    JOIN tasks t ON tn.task_id = t.id
                    WHERE tn.node_id = ? AND tn.status IN ('downloading', 'pending', 'paused')
                    ORDER BY t.created_at DESC
                    LIMIT 20
                """,
                    (node_id,),
                ).fetchall()
            ]

        station: dict[str, Any] = {
            "id": node_id,
            "name": str(n.get("name", node_id)),
            "host": str(n.get("host", "")),
            "port": int(n.get("port", 0)),
            "node_type": str(n.get("node_type", "full")),
            "status": checked_status,
            "auth_token": str(n.get("auth_token", "")),
            "is_local": is_local,
            "stats": {
                "downloading": status_map.get("downloading", 0),
                "pending": status_map.get("pending", 0),
                "paused": status_map.get("paused", 0),
                "seeding": status_map.get("seeding", 0),
                "completed": status_map.get("completed", 0),
                "failed": status_map.get("failed", 0) + status_map.get("cancelled", 0),
                "total": sum(status_map.values()),
            },
            "speed": {
                "download": local_speed_download if is_local else 0,
                "upload": local_speed_upload if is_local else 0,
                "active": local_active if is_local else 0,
                "waiting": local_waiting if is_local else 0,
                "stopped": local_stopped if is_local else 0,
            }
            if is_local
            else None,
            "active_tasks": [
                {
                    "id": t["id"],
                    "filename": t.get("filename") or t.get("url", "").split("/")[-1] or t["id"],
                    "progress": t.get("progress") or 0,
                    "status": t.get("status"),
                    "gid": t.get("gid"),
                }
                for t in active_tasks_raw
            ],
        }
        stations.append(station)

    return {"stations": stations, "count": len(stations)}


@router.get("/api/nodes")
async def list_nodes() -> dict[str, Any]:
    """列出所有节点"""
    db = get_db()
    rows = db.execute("SELECT * FROM nodes ORDER BY name").fetchall()
    return {"nodes": [dict(r) for r in rows]}

"""
Allfiledown — 节点间 API（P2P 通信）
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.config import config
from app.database import get_db, get_events_since

router: APIRouter = APIRouter(prefix="/api")


def verify_token(request: Request) -> None:
    """验证节点间通信的 X-Auth-Token"""
    token: str = request.headers.get("X-Auth-Token", "")
    expected: str = config.get("auth_token", "")
    if expected and token != expected:
        raise HTTPException(status_code=403, detail="Invalid token")


@router.get("/ping")
async def ping() -> dict[str, Any]:
    return {"status": "ok", "node_id": config["node_id"], "node_name": config["node_name"]}


@router.post("/task/new")
async def receive_task(request: Request) -> dict[str, Any]:
    """接收其他节点广播的下载任务"""
    verify_token(request)
    data: dict[str, Any] = await request.json()
    task_id: str = data.get("task_id", "")
    url: str = data.get("url", "")
    filename: str | None = data.get("filename")
    if not task_id or not url:
        raise HTTPException(status_code=400, detail="Missing task_id or url")

    from app.agent.orchestrator import orchestrator

    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")

    result: dict[str, Any] = await orchestrator.receive_task(task_id, url, filename)
    return result


@router.post("/source/new")
async def receive_source(request: Request) -> dict[str, Any]:
    """接收其他节点共享的内部源"""
    verify_token(request)
    data: dict[str, Any] = await request.json()
    task_id: str = data.get("task_id", "")
    source_node: str = data.get("source_node", "")
    internal_url: str = data.get("internal_url", "")

    from app.agent.orchestrator import orchestrator

    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")

    result: dict[str, Any] = await orchestrator.receive_source(task_id, source_node, internal_url)
    return result


@router.get("/task/status")
async def task_status(task_id: str | None = None) -> dict[str, Any]:
    """查询任务状态（单个或所有）"""
    from app.agent.orchestrator import orchestrator

    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")

    if task_id:
        detail: dict[str, Any] | None = await orchestrator.get_task_detail(task_id)
        return detail or {"status": "not_found"}
    else:
        tasks: list[dict[str, Any]] = await orchestrator.get_task_list()
        return {"tasks": tasks}


@router.post("/node/register")
async def register_node(request: Request) -> dict[str, Any]:
    """注册一个新节点"""
    data: dict[str, Any] = await request.json()
    node_id: str = data.get("node_id", "")
    name: str = data.get("name", node_id)
    host: str = data.get("host", "")
    port: int = int(data.get("port", 18790))
    node_type: str = data.get("node_type", "full")
    auth_token: str = data.get("auth_token", "")

    if not node_id or not host:
        raise HTTPException(status_code=400, detail="Missing node_id or host")

    db = get_db()
    db.execute(
        "INSERT OR REPLACE INTO nodes (id, name, host, port, node_type, auth_token, status, last_seen) "
        "VALUES (?, ?, ?, ?, ?, ?, 'online', datetime('now'))",
        (node_id, name, host, port, node_type, auth_token),
    )
    db.commit()
    return {"status": "registered"}


@router.get("/nodes")
async def get_nodes() -> dict[str, Any]:
    """获取所有注册的节点"""
    db = get_db()
    rows = db.execute("SELECT * FROM nodes ORDER BY name").fetchall()
    return {"nodes": [dict(r) for r in rows]}


@router.get("/events")
async def get_events(since: int = 0) -> dict[str, Any]:
    """获取事件流"""
    events = get_events_since(since)
    return {"events": [dict(e) for e in events]}

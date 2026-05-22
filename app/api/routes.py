"""
Allfiledown — 节点间 API（P2P 通信）
"""
import json
from fastapi import APIRouter, Request, HTTPException
from app.database import get_db, add_event, get_events_since
from app.config import config

router = APIRouter(prefix="/api")


def verify_token(request: Request):
    token = request.headers.get("X-Auth-Token", "")
    expected = config.get("auth_token", "")
    if expected and token != expected:
        raise HTTPException(status_code=403, detail="Invalid token")


@router.get("/ping")
async def ping():
    return {"status": "ok", "node_id": config["node_id"], "node_name": config["node_name"]}


@router.post("/task/new")
async def receive_task(request: Request):
    verify_token(request)
    data = await request.json()
    task_id = data.get("task_id")
    url = data.get("url")
    filename = data.get("filename")
    if not task_id or not url:
        raise HTTPException(status_code=400, detail="Missing task_id or url")
    from app.agent.orchestrator import orchestrator
    result = await orchestrator.receive_task(task_id, url, filename)
    return result


@router.post("/source/new")
async def receive_source(request: Request):
    verify_token(request)
    data = await request.json()
    task_id = data.get("task_id")
    source_node = data.get("source_node")
    internal_url = data.get("internal_url")
    from app.agent.orchestrator import orchestrator
    result = await orchestrator.receive_source(task_id, source_node, internal_url)
    return result


@router.get("/task/status")
async def task_status(task_id: str = None):
    from app.agent.orchestrator import orchestrator
    if task_id:
        detail = await orchestrator.get_task_detail(task_id)
        return detail or {"status": "not_found"}
    else:
        tasks = await orchestrator.get_task_list()
        return {"tasks": tasks}


@router.post("/node/register")
async def register_node(request: Request):
    data = await request.json()
    node_id = data.get("node_id")
    name = data.get("name", node_id)
    host = data.get("host")
    port = data.get("port", 18790)
    node_type = data.get("node_type", "full")
    auth_token = data.get("auth_token", "")
    if not node_id or not host:
        raise HTTPException(status_code=400, detail="Missing node_id or host")
    db = get_db()
    db.execute(
        "INSERT OR REPLACE INTO nodes (id, name, host, port, node_type, auth_token, status, last_seen) "
        "VALUES (?, ?, ?, ?, ?, ?, 'online', datetime('now'))",
        (node_id, name, host, port, node_type, auth_token)
    )
    db.commit()
    return {"status": "registered"}


@router.get("/nodes")
async def get_nodes():
    db = get_db()
    rows = db.execute("SELECT * FROM nodes ORDER BY name").fetchall()
    return {"nodes": [dict(r) for r in rows]}


@router.get("/events")
async def get_events(since: int = 0):
    events = get_events_since(since)
    return {"events": [dict(e) for e in events]}

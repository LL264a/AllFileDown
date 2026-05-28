"""
Allfiledown — 节点间 API（P2P 通信）
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.agent.role import get_local_node_type
from app.config import config
from app.database import get_db, get_events_since

router: APIRouter = APIRouter()


def verify_token(request: Request) -> None:
    """验证节点间通信的 X-Auth-Token"""
    token: str = request.headers.get("X-Auth-Token", "")
    expected: str = config.get("auth_token", "")
    if expected and token != expected:
        raise HTTPException(status_code=403, detail="Invalid token")


@router.get("/ping")
async def ping() -> dict[str, Any]:
    return {"status": "ok", "node_id": config["node_id"], "node_name": config["node_name"], "node_type": get_local_node_type()}


@router.post("/task/new")
async def receive_task(request: Request) -> dict[str, Any]:
    """接收其他节点广播的下载任务"""
    verify_token(request)
    data: dict[str, Any] = await request.json()
    task_id: str = data.get("task_id", "")
    url: str = data.get("url", "")
    filename: str | None = data.get("filename")
    priority: int = int(data.get("priority", 5))
    if not task_id or not url:
        raise HTTPException(status_code=400, detail="Missing task_id or url")

    from app.agent.orchestrator import orchestrator

    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")

    result: dict[str, Any] = await orchestrator.receive_task(task_id, url, filename, priority)
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


@router.post("/api/node/register")
async def register_node(request: Request) -> dict[str, Any]:
    """注册一个新节点（心跳/发现用）"""
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
    
    # 也更新到 config.peers
    peers: list[dict[str, Any]] = config.get("peers", [])
    peers = [p for p in peers if p.get("id") != node_id]
    peers.append({
        "id": node_id,
        "name": name,
        "host": host,
        "port": port,
        "node_type": node_type,
        "auth_token": auth_token,
    })
    config["peers"] = peers
    from app.config import save_config
    save_config(config)
    
    logger.info("Node registered: %s (%s:%s) type=%s", node_id, host, port, node_type)
    return {"status": "registered", "node_id": node_id}


@router.get("/nodes")
async def get_nodes() -> dict[str, Any]:
    """获取所有注册的节点"""
    db = get_db()
    rows = db.execute("SELECT * FROM nodes ORDER BY name").fetchall()
    return {"nodes": [dict(r) for r in rows]}


@router.post("/task/batch/{action}")
async def batch_task_action(action: str, request: Request) -> dict[str, Any]:
    """批量操作任务：pause / resume / delete"""
    verify_token(request)
    data: dict[str, Any] = await request.json()
    task_ids: list[str] = data.get("task_ids", [])
    if not task_ids:
        raise HTTPException(status_code=400, detail="Missing task_ids")

    if action not in ("pause", "resume", "delete"):
        raise HTTPException(status_code=400, detail=f"Invalid action: {action}")

    from app.agent.orchestrator import orchestrator

    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")

    if action == "pause":
        result = await orchestrator.batch_pause_tasks(task_ids)
    elif action == "resume":
        result = await orchestrator.batch_resume_tasks(task_ids)
    else:
        result = await orchestrator.batch_delete_tasks(task_ids)

    return result


@router.get("/events")
async def get_events(since: int = 0) -> dict[str, Any]:
    """获取事件流"""
    events = get_events_since(since)
    return {"events": [dict(e) for e in events]}


# ---- 通知设置 API ----

@router.get("/notifications/settings")
async def get_notification_settings_api(request: Request) -> dict[str, Any]:
    """获取通知配置"""
    from app.agent.notifier import get_notification_settings
    settings = get_notification_settings()
    return {
        "webhook_url": settings.get("webhook_url", ""),
        "webhook_enabled": bool(settings.get("webhook_enabled", 0)),
        "push_enabled": bool(settings.get("push_enabled", 1)),
    }


@router.post("/notifications/settings")
async def save_notification_settings_api(request: Request) -> dict[str, Any]:
    """保存通知配置"""
    verify_token(request)
    data: dict[str, Any] = await request.json()
    
    from app.agent.notifier import save_notification_settings
    settings = save_notification_settings(
        webhook_url=data.get("webhook_url"),
        webhook_enabled=data.get("webhook_enabled"),
        push_enabled=data.get("push_enabled"),
    )
    return {"success": True, "settings": {
        "webhook_url": settings.get("webhook_url", ""),
        "webhook_enabled": bool(settings.get("webhook_enabled", 0)),
        "push_enabled": bool(settings.get("push_enabled", 1)),
    }}


@router.get("/notifications/history")
async def get_notification_history(request: Request, limit: int = 50) -> dict[str, Any]:
    """获取通知历史"""
    from app.agent.notifier import get_recent_notifications
    notifications = get_recent_notifications(limit=limit)
    return {"notifications": notifications}


@router.get("/notifications/stream")
async def notification_stream(request: Request) -> Any:
    """SSE 实时通知流（浏览器 Push）"""
    from fastapi.responses import StreamingResponse
    from app.agent.notifier import register_sse_client, unregister_sse_client
    
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
    register_sse_client(queue)
    
    async def event_generator():
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=30)
                    data = json.dumps(payload, ensure_ascii=False)
                    yield f"event: download_completed\ndata: {data}\n\n"
                except asyncio.TimeoutError:
                    yield ":heartbeat\n\n"
        except Exception:
            pass
        finally:
            unregister_sse_client(queue)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ============ 日志 API ============

@router.get("/logs")
async def list_logs() -> dict[str, Any]:
    """获取日志文件列表"""
    from app.agent.logviewer import get_log_files
    return {"logs": get_log_files()}


@router.get("/logs/{filename}")
async def read_log(filename: str, lines: int = 100, level: str | None = None, search: str | None = None) -> dict[str, Any]:
    """读取日志内容"""
    from app.agent.logviewer import read_log
    return read_log(filename, lines, level, search)


@router.get("/logs/{filename}/levels")
async def log_levels(filename: str) -> dict[str, Any]:
    """获取日志级别"""
    from app.agent.logviewer import get_log_levels
    return {"levels": get_log_levels(filename)}


@router.get("/audit")
async def audit_logs(limit: int = 100, event_type: str | None = None, task_id: str | None = None) -> dict[str, Any]:
    """获取审计日志"""
    from app.agent.logviewer import get_audit_logs
    return {"events": get_audit_logs(limit, event_type, task_id)}


@router.delete("/logs")
async def clear_logs(days: int = 7) -> dict[str, Any]:
    """清理旧日志"""
    from app.agent.logviewer import clear_old_logs
    return clear_old_logs(days)


# ============ 存储 API ============

@router.get("/storage")
async def storage_info() -> dict[str, Any]:
    """获取存储信息"""
    from app.agent.storage import get_storage_info
    return get_storage_info()


@router.get("/storage/tasks")
async def task_sizes(limit: int = 20) -> dict[str, Any]:
    """获取任务大小排行"""
    from app.agent.storage import get_task_sizes
    return {"tasks": get_task_sizes(limit)}


@router.post("/storage/check")
async def check_space(task_size: int = 0) -> dict[str, Any]:
    """检查空间是否足够"""
    from app.agent.storage import check_space
    return check_space(task_size)


@router.post("/storage/cleanup")
async def cleanup_tasks(delete_files: bool = False, older_than_days: int = 0, dry_run: bool = True) -> dict[str, Any]:
    """清理已完成任务"""
    from app.agent.storage import cleanup_completed
    return cleanup_completed(delete_files, older_than_days, dry_run)


@router.get("/storage/alert")
async def disk_alert() -> dict[str, Any]:
    """磁盘告警检查"""
    from app.agent.storage import get_disk_alert
    return get_disk_alert()


@router.post("/storage/alert")
async def set_alert_threshold(percent: int = 90) -> dict[str, Any]:
    """设置告警阈值"""
    from app.agent.storage import set_disk_alert_threshold
    return set_disk_alert_threshold(percent)


# ============ 标签 API ============

@router.get("/tags")
async def list_tags() -> dict[str, Any]:
    """获取所有标签"""
    from app.agent.tags import get_tags
    return {"tags": get_tags()}


@router.post("/tags")
async def create_tag(name: str, color: str = "#6b7280") -> dict[str, Any]:
    """创建标签"""
    from app.agent.tags import create_tag
    return create_tag(name, color)


@router.delete("/tags/{tag_id}")
async def delete_tag(tag_id: str) -> dict[str, Any]:
    """删除标签"""
    from app.agent.tags import delete_tag
    return delete_tag(tag_id)


@router.post("/tags/{tag_id}/tasks/{task_id}")
async def add_task_tag(tag_id: str, task_id: str) -> dict[str, Any]:
    """给任务添加标签"""
    from app.agent.tags import add_task_tag
    return add_task_tag(task_id, tag_id)


@router.delete("/tags/{tag_id}/tasks/{task_id}")
async def remove_task_tag(tag_id: str, task_id: str) -> dict[str, Any]:
    """移除任务标签"""
    from app.agent.tags import remove_task_tag
    return remove_task_tag(task_id, tag_id)


@router.get("/tasks/{task_id}/tags")
async def task_tags(task_id: str) -> dict[str, Any]:
    """获取任务的标签"""
    from app.agent.tags import get_task_tags
    return {"tags": get_task_tags(task_id)}


@router.get("/tags/{tag_id}/tasks")
async def tagged_tasks(tag_id: str) -> dict[str, Any]:
    """获取指定标签的任务"""
    from app.agent.tags import get_tasks_by_tag
    return {"tasks": get_tasks_by_tag(tag_id)}


# ============ 限速 API ============

@router.get("/throttle/status")
async def throttle_status() -> dict[str, Any]:
    """获取限速状态"""
    from app.agent.throttle import get_current_limits
    return await get_current_limits()


@router.post("/throttle/limit")
async def set_throttle_limit(download: int = 0, upload: int = 0) -> dict[str, Any]:
    """设置全局限速"""
    from app.agent.throttle import set_global_speed_limit
    return await set_global_speed_limit(download, upload)


# ============ 做种管理 API ============

@router.get("/seeding")
async def seeding_list() -> dict[str, Any]:
    """获取做种列表"""
    from app.agent.seeding import get_seeding_tasks
    return {"tasks": get_seeding_tasks()}


@router.get("/seeding/{task_id}/ratio")
async def seed_ratio(task_id: str) -> dict[str, Any]:
    """获取分享率"""
    from app.agent.seeding import get_seed_ratio
    return get_seed_ratio(task_id)


@router.post("/seeding/{task_id}/stop")
async def stop_seeding(task_id: str) -> dict[str, Any]:
    """停止做种"""
    from app.agent.seeding import stop_seeding
    return stop_seeding(task_id)

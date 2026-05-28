"""
Allfiledown — 下载完成通知模块

支持：
- Webhook POST 通知（可配置 URL）
- 浏览器 Push 通知（基于 SSE 事件流）
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

import aiohttp

from app.database import get_db

logger = logging.getLogger("afd")

# 内存中的 SSE 客户端队列
_sse_queues: set[asyncio.Queue[dict[str, Any]]] = set()


# ---- 数据库操作 ----


def get_notification_settings(db: Any = None) -> dict[str, Any]:
    """获取通知配置"""
    conn = db or get_db()
    row = conn.execute("SELECT * FROM notification_settings ORDER BY id LIMIT 1").fetchone()
    if not row:
        conn.execute(
            "INSERT INTO notification_settings (webhook_url, webhook_enabled, push_enabled) "
            "VALUES ('', 0, 1)"
        )
        conn.commit()
        row = conn.execute("SELECT * FROM notification_settings ORDER BY id LIMIT 1").fetchone()
    return dict(row) if row else {"webhook_url": "", "webhook_enabled": 0, "push_enabled": 1}


def save_notification_settings(
    webhook_url: str | None = None,
    webhook_enabled: bool | None = None,
    push_enabled: bool | None = None,
    db: Any = None,
) -> dict[str, Any]:
    """保存通知配置"""
    conn = db or get_db()
    settings = get_notification_settings(conn)
    
    updates: list[str] = []
    params: list[Any] = []
    
    if webhook_url is not None:
        updates.append("webhook_url = ?")
        params.append(webhook_url)
    if webhook_enabled is not None:
        updates.append("webhook_enabled = ?")
        params.append(1 if webhook_enabled else 0)
    if push_enabled is not None:
        updates.append("push_enabled = ?")
        params.append(1 if push_enabled else 0)
    
    if updates:
        updates.append("updated_at = datetime('now')")
        params.append(settings["id"])
        conn.execute(
            f"UPDATE notification_settings SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        conn.commit()
    
    return get_notification_settings(conn)


def record_notification(
    task_id: str,
    task_name: str,
    total_size: int,
    webhook_sent: bool = False,
    push_sent: bool = False,
    db: Any = None,
) -> None:
    """记录一条通知到数据库"""
    conn = db or get_db()
    conn.execute(
        "INSERT INTO notifications (task_id, task_name, total_size, webhook_sent, push_sent) "
        "VALUES (?, ?, ?, ?, ?)",
        (task_id, task_name, total_size, 1 if webhook_sent else 0, 1 if push_sent else 0),
    )
    conn.commit()


def get_recent_notifications(limit: int = 50, db: Any = None) -> list[dict[str, Any]]:
    """获取最近的通知记录"""
    conn = db or get_db()
    rows = conn.execute(
        "SELECT * FROM notifications ORDER BY completed_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


# ---- Webhook 通知 ----


async def send_webhook_notification(
    webhook_url: str,
    task_id: str,
    task_name: str,
    total_size: int,
    completed_at: str,
) -> bool:
    """发送 Webhook POST 通知"""
    if not webhook_url:
        return False
    
    payload: dict[str, Any] = {
        "event": "download_completed",
        "task_id": task_id,
        "task_name": task_name,
        "total_size": total_size,
        "total_size_formatted": _format_file_size(total_size),
        "completed_at": completed_at,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                webhook_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
                headers={"Content-Type": "application/json", "User-Agent": "Allfiledown/0.1.0"},
            ) as resp:
                success: bool = resp.status in (200, 201, 202, 204)
                if success:
                    logger.info("Webhook notification sent for task %s", task_id)
                else:
                    logger.warning(
                        "Webhook notification failed for task %s: HTTP %s", task_id, resp.status
                    )
                return success
    except Exception as e:
        logger.warning("Webhook notification error for task %s: %s", task_id, e)
        return False


# ---- 浏览器 Push (SSE) ----


async def broadcast_push_notification(
    task_id: str,
    task_name: str,
    total_size: int,
    completed_at: str,
) -> int:
    """广播 SSE Push 通知，返回送达的客户端数量"""
    if not _sse_queues:
        return 0
    
    payload: dict[str, Any] = {
        "event": "download_completed",
        "task_id": task_id,
        "task_name": task_name,
        "total_size": total_size,
        "total_size_formatted": _format_file_size(total_size),
        "completed_at": completed_at,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    
    dead_queues: set[asyncio.Queue[dict[str, Any]]] = set()
    delivered: int = 0
    
    for queue in _sse_queues:
        try:
            queue.put_nowait(payload)
            delivered += 1
        except asyncio.QueueFull:
            dead_queues.add(queue)
        except Exception:
            dead_queues.add(queue)
    
    # 清理失效队列
    for q in dead_queues:
        _sse_queues.discard(q)
    
    logger.info("Push notification broadcast to %d/%d clients for task %s", delivered, len(_sse_queues), task_id)
    return delivered


def register_sse_client(queue: asyncio.Queue[dict[str, Any]]) -> None:
    """注册 SSE 客户端队列"""
    _sse_queues.add(queue)
    logger.debug("SSE client registered, total clients: %d", len(_sse_queues))


def unregister_sse_client(queue: asyncio.Queue[dict[str, Any]]) -> None:
    """注销 SSE 客户端队列"""
    _sse_queues.discard(queue)
    logger.debug("SSE client unregistered, total clients: %d", len(_sse_queues))


# ---- 主入口：任务完成时调用 ----


async def notify_task_completed(
    task_id: str,
    task_name: str,
    total_size: int,
    local_path: str = "",
) -> dict[str, Any]:
    """
    任务完成时调用此函数发送通知。
    
    会同时触发：
    1. Webhook POST（如果已启用并配置了 URL）
    2. 浏览器 Push / SSE 广播（如果已启用且有客户端连接）
    """
    completed_at: str = datetime.now(UTC).isoformat()
    settings: dict[str, Any] = get_notification_settings()
    
    webhook_sent: bool = False
    push_sent: bool = False
    
    # 1. Webhook
    if settings.get("webhook_enabled") and settings.get("webhook_url"):
        webhook_sent = await send_webhook_notification(
            settings["webhook_url"],
            task_id,
            task_name,
            total_size,
            completed_at,
        )
    
    # 2. Push / SSE
    if settings.get("push_enabled"):
        delivered: int = await broadcast_push_notification(
            task_id,
            task_name,
            total_size,
            completed_at,
        )
        push_sent = delivered > 0
    
    # 记录到数据库
    record_notification(task_id, task_name, total_size, webhook_sent, push_sent)
    
    result: dict[str, Any] = {
        "task_id": task_id,
        "webhook_sent": webhook_sent,
        "push_sent": push_sent,
        "push_clients": len(_sse_queues),
    }
    logger.info("Notification result for task %s: %s", task_id, result)
    return result


# ---- 辅助函数 ----


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

"""
Allfiledown — 任务编排调度
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.agent.downloader import (
    add_download,
    add_source,
    get_status,
)
from app.agent.downloader import (
    pause as aria2_pause,
)
from app.agent.downloader import (
    remove as aria2_remove,
)
from app.agent.downloader import (
    unpause as aria2_unpause,
)
from app.agent.p2p import P2PClient
from app.agent.role import (
    can_download,
    can_upload,
    filter_peers_for_broadcast,
    filter_peers_for_source_notify,
    get_local_node_type,
)
from app.config import config
from app.database import add_event, get_db, init_db

logger = logging.getLogger("afd")

# Global instance (injected by main.py on startup)
orchestrator: Orchestrator | None = None  # type: ignore[name-defined]


class Orchestrator:
    """任务编排器 — 负责协调本地 aria2 + 远程节点"""

    def __init__(self) -> None:
        self.p2p: P2PClient = P2PClient(auth_token=str(config.get("auth_token", "")))
        self._running: bool = True

    async def start(self) -> Orchestrator:
        """启动后台协程"""
        init_db()
        asyncio.create_task(self._status_update_loop())
        asyncio.create_task(self._source_check_loop())
        
        # Upload-Only / Full 节点启动时扫描已有文件
        try:
            from app.agent.filescan import scan_and_register_all
            result = await scan_and_register_all()
            logger.info("Startup file scan: %s", result)
        except Exception as e:
            logger.warning("Startup file scan failed: %s", e)
        
        logger.info("Orchestrator background loops started")
        return self

    async def stop(self) -> None:
        self._running = False

    # ---- 任务生命周期 ----

    async def create_task(self, url: str, filename: str | None = None, priority: int = 5) -> str:
        """创建新下载任务（本地）"""
        # 优先级范围限制 1-10
        priority = max(1, min(10, priority))

        # Upload-Only 节点不接受新下载任务
        if not can_download():
            logger.warning("Rejecting task: node %s is %s, cannot download", config["node_id"], get_local_node_type())
            raise RuntimeError(f"Node {config['node_id']} is {get_local_node_type()}, cannot accept download tasks")

        task_id: str = str(uuid.uuid4())[:12]
        download_dir: Path = Path(config["download_dir"]) / task_id
        download_dir.mkdir(parents=True, exist_ok=True)

        logger.info("Creating task %s: %s filename=%s priority=%d", task_id, url, filename, priority)

        db = get_db()
        db.execute(
            "INSERT INTO tasks (id, url, filename, status, priority) VALUES (?, ?, ?, ?, ?)",
            (task_id, url, filename or "", "pending", priority),
        )
        db.execute(
            "INSERT INTO task_nodes (task_id, node_id, status) VALUES (?, ?, ?)",
            (task_id, config["node_id"], "pending"),
        )
        db.commit()

        # 尝试启动下载（受并发数限制）
        await self._try_start_pending()

        # 广播给对等节点（只发给 Full 和 Download 节点）
        peers: list[dict[str, Any]] = config.get("peers", [])
        target_peers = filter_peers_for_broadcast(peers)
        logger.info("Task %s: broadcasting to %d peers (filtered from %d)", task_id, len(target_peers), len(peers))
        for peer in target_peers:
            asyncio.create_task(self._broadcast_task(peer, task_id, url, filename))

        return task_id

    async def _broadcast_task(
        self,
        peer: dict[str, Any],
        task_id: str,
        url: str,
        filename: str | None,
    ) -> None:
        """向一个对等节点广播任务"""
        peer_id: str = peer.get("id", "unknown")
        logger.info(
            "Task %s: broadcasting to peer %s (%s:%s)",
            task_id,
            peer_id,
            peer.get("host", ""),
            peer.get("port", ""),
        )
        result: dict[str, Any] = await self.p2p.send_task(
            peer,
            {
                "task_id": task_id,
                "url": url,
                "filename": filename,
                "source_node": config["node_id"],
                "source_info": {
                    "host": config.get("host", ""),
                    "port": config.get("file_server_port", 18791),
                    "token": config.get("auth_token", ""),
                },
            },
        )
        db = get_db()
        if "error" in result:
            logger.warning("Task %s: broadcast to %s failed: %s", task_id, peer_id, result["error"])
            db.execute("UPDATE nodes SET status = ? WHERE id = ?", ("offline", peer.get("id", "")))
        else:
            logger.info("Task %s: broadcast to %s success", task_id, peer_id)
            db.execute("UPDATE nodes SET status = ? WHERE id = ?", ("online", peer.get("id", "")))
        db.commit()

    async def receive_task(self, task_id: str, url: str, filename: str | None, priority: int = 5) -> dict[str, Any]:
        """收到其他节点广播的任务"""
        # 优先级范围限制 1-10
        priority = max(1, min(10, priority))

        # Upload-Only 节点不接受新下载任务
        if not can_download():
            logger.info("Rejecting broadcast task %s: node %s is upload-only", task_id, config["node_id"])
            return {"status": "rejected", "reason": "upload-only node does not download"}

        db = get_db()
        existing = db.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if existing:
            return {"status": "already_exists"}

        download_dir: Path = Path(config["download_dir"]) / task_id
        download_dir.mkdir(parents=True, exist_ok=True)

        db.execute(
            "INSERT INTO tasks (id, url, filename, status, priority) VALUES (?, ?, ?, ?, ?)",
            (task_id, url, filename or "", "pending", priority),
        )
        db.execute(
            "INSERT INTO task_nodes (task_id, node_id, status) VALUES (?, ?, ?)",
            (task_id, config["node_id"], "pending"),
        )
        db.commit()

        # 尝试启动下载（受并发数限制）
        await self._try_start_pending()

        return {"status": "accepted", "task_id": task_id}

    async def receive_source(
        self,
        task_id: str,
        source_node_id: str,
        internal_url: str,
    ) -> dict[str, Any]:
        """收到内部源通知"""
        db = get_db()
        row = db.execute(
            "SELECT gid, status FROM task_nodes WHERE task_id = ? AND node_id = ?",
            (task_id, config["node_id"]),
        ).fetchone()

        if row and row["gid"] and row["status"] == "downloading":
            try:
                result: Any = await add_source(row["gid"], internal_url)
                add_event(
                    task_id,
                    config["node_id"],
                    "source_added",
                    json.dumps({"from": source_node_id, "url": internal_url}),
                )
                return {"status": "source_added", "result": str(result)}
            except Exception as e:
                return {"status": "error", "message": str(e)}

        db.execute(
            "UPDATE task_nodes SET internal_url = ? WHERE task_id = ? AND node_id = ?",
            (internal_url, task_id, source_node_id),
        )
        db.commit()
        return {"status": "recorded"}

    async def _try_start_pending(self) -> None:
        """尝试启动 pending 状态的下载任务，受并发数限制，高优先级优先"""
        db = get_db()
        max_concurrent: int = int(config.get("max_concurrent_downloads", 3))

        # 统计当前正在下载的任务数
        active_count = db.execute(
            "SELECT COUNT(*) FROM task_nodes WHERE node_id = ? AND status = 'downloading'",
            (config["node_id"],),
        ).fetchone()[0]

        available_slots = max_concurrent - active_count
        if available_slots <= 0:
            logger.debug("No download slots available (active=%d, max=%d)", active_count, max_concurrent)
            return

        # 获取 pending 任务，按优先级升序（1 最高）
        pending = db.execute(
            "SELECT t.id, t.url, t.filename, t.priority FROM tasks t "
            "JOIN task_nodes tn ON t.id = tn.task_id "
            "WHERE tn.node_id = ? AND t.status = 'pending' "
            "ORDER BY t.priority ASC, t.created_at ASC "
            "LIMIT ?",
            (config["node_id"], available_slots),
        ).fetchall()

        for row in pending:
            task_id: str = row["id"]
            url: str = row["url"]
            filename: str = row["filename"]
            priority: int = row["priority"]
            download_dir: Path = Path(config["download_dir"]) / task_id

            try:
                gid: str | None = await add_download(url, str(download_dir), filename=filename or None)
                logger.info("Task %s: started (priority=%d) gid=%s", task_id, priority, gid)
                db.execute(
                    "UPDATE task_nodes SET gid = ?, status = 'downloading' WHERE task_id = ? AND node_id = ?",
                    (gid, task_id, config["node_id"]),
                )
                db.execute(
                    "UPDATE tasks SET status = 'downloading', updated_at = ? WHERE id = ?",
                    (datetime.now(UTC).isoformat(), task_id),
                )
                db.commit()
                add_event(task_id, config["node_id"], "download_started", json.dumps({"url": url, "priority": priority}))
            except Exception as e:
                logger.warning("Task %s: start failed: %s", task_id, e)
                db.execute(
                    "UPDATE task_nodes SET status = ? WHERE task_id = ? AND node_id = ?",
                    (f"failed: {e}", task_id, config["node_id"]),
                )
                db.execute(
                    "UPDATE tasks SET status = 'failed', updated_at = ? WHERE id = ?",
                    (datetime.now(UTC).isoformat(), task_id),
                )
                db.commit()
                add_event(task_id, config["node_id"], "download_failed", str(e))

    # ---- 任务控制 ----

    async def cancel_task(self, task_id: str) -> dict[str, Any]:
        """取消下载任务"""
        db = get_db()
        rows = db.execute(
            "SELECT gid FROM task_nodes WHERE task_id = ? AND node_id = ? AND gid IS NOT NULL",
            (task_id, config["node_id"]),
        ).fetchall()
        for row in rows:
            try:
                await aria2_remove(row["gid"])
            except Exception as e:
                logger.warning("Cancel task %s: aria2 remove failed: %s", task_id, e)

        db.execute("UPDATE task_nodes SET status = ? WHERE task_id = ?", ("cancelled", task_id))
        db.execute(
            "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
            ("cancelled", datetime.now(UTC).isoformat(), task_id),
        )
        db.commit()

        # 取消后释放槽位，尝试启动更多 pending 任务
        await self._try_start_pending()

        return {"status": "cancelled"}

    async def delete_task(self, task_id: str) -> dict[str, Any]:
        """删除任务记录和本机下载文件。"""
        db = get_db()
        task = db.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
        rows = db.execute(
            "SELECT gid, node_id, local_path FROM task_nodes WHERE task_id = ?",
            (task_id,),
        ).fetchall()
        if task is None and not rows:
            return {"status": "not_found", "deleted": False}

        for row in rows:
            if row["gid"]:
                with suppress(Exception):
                    await aria2_remove(row["gid"])

        download_root = Path(config["download_dir"]).resolve()
        paths_to_remove: set[Path] = {download_root / task_id}
        for row in rows:
            local_path = row["local_path"]
            if row["node_id"] == config["node_id"] and local_path:
                paths_to_remove.add(Path(local_path))

        removed_paths: list[str] = []
        for path in paths_to_remove:
            with suppress(Exception):
                resolved = path.resolve(strict=False)
                resolved.relative_to(download_root)
                if resolved.is_dir():
                    shutil.rmtree(resolved)
                    removed_paths.append(str(resolved))
                elif resolved.exists():
                    resolved.unlink()
                    removed_paths.append(str(resolved))

        db.execute("DELETE FROM task_nodes WHERE task_id = ?", (task_id,))
        db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        db.commit()
        return {"status": "deleted", "deleted": True, "removed_paths": removed_paths}

    async def clear_completed(self) -> dict[str, Any]:
        """清理所有已完成的任务"""
        db = get_db()
        rows = db.execute(
            "SELECT id FROM tasks WHERE status IN ('completed', 'all_completed', 'failed', 'cancelled')",
        ).fetchall()
        for row in rows:
            db.execute("DELETE FROM task_nodes WHERE task_id = ?", (row["id"],))
        db.execute(
            "DELETE FROM tasks WHERE status IN ('completed', 'all_completed', 'failed', 'cancelled')",
        )
        db.commit()
        return {"status": "cleared"}

    async def pause_task(self, task_id: str) -> dict[str, Any]:
        """暂停任务"""
        db = get_db()
        row = db.execute(
            "SELECT gid FROM task_nodes WHERE task_id = ? AND node_id = ? AND gid IS NOT NULL",
            (task_id, config["node_id"]),
        ).fetchone()
        if row:
            try:
                await aria2_pause(row["gid"])
            except Exception as e:
                logger.warning("Pause task %s: %s", task_id, e)
        db.execute(
            "UPDATE task_nodes SET status = ? WHERE task_id = ? AND node_id = ?", ("paused", task_id, config["node_id"])
        )
        db.execute(
            "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
            ("paused", datetime.now(UTC).isoformat(), task_id),
        )
        db.commit()
        return {"status": "paused"}

    async def resume_task(self, task_id: str) -> dict[str, Any]:
        """恢复任务"""
        db = get_db()
        row = db.execute(
            "SELECT gid FROM task_nodes WHERE task_id = ? AND node_id = ? AND gid IS NOT NULL",
            (task_id, config["node_id"]),
        ).fetchone()
        if row:
            try:
                await aria2_unpause(row["gid"])
            except Exception as e:
                logger.warning("Resume task %s: %s", task_id, e)
        db.execute(
            "UPDATE task_nodes SET status = ? WHERE task_id = ? AND node_id = ?",
            ("downloading", task_id, config["node_id"]),
        )
        db.execute(
            "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
            ("downloading", datetime.now(UTC).isoformat(), task_id),
        )
        db.commit()

        # 恢复后尝试启动更多 pending 任务
        await self._try_start_pending()

        return {"status": "resumed"}

    async def retry_task(self, task_id: str) -> dict[str, Any]:
        """重新下载失败/取消的任务"""
        db = get_db()
        task = db.execute("SELECT id, url, filename, priority FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            return {"error": "Task not found"}
        url: str = task["url"]
        filename: str = task["filename"]
        priority: int = task["priority"]
        await self.delete_task(task_id)
        new_id: str = await self.create_task(url, filename or None, priority)
        return {"status": "retried", "task_id": new_id}

    # ---- 查询 ----

    async def get_task_list(self) -> list[dict[str, Any]]:
        """获取所有任务列表"""
        db = get_db()
        tasks = db.execute("SELECT * FROM tasks ORDER BY priority ASC, created_at DESC").fetchall()

        result: list[dict[str, Any]] = []
        for task in tasks:
            nodes = db.execute(
                "SELECT tn.*, n.name as node_name, n.node_type FROM task_nodes tn "
                "LEFT JOIN nodes n ON tn.node_id = n.id "
                "WHERE tn.task_id = ?",
                (task["id"],),
            ).fetchall()

            node_statuses: list[dict[str, Any]] = []
            for n in nodes:
                node_statuses.append(
                    {
                        "node_id": n["node_id"],
                        "node_name": n["node_name"] or n["node_id"],
                        "node_type": n["node_type"] or "full",
                        "progress": n["progress"],
                        "download_speed": n["download_speed"] if n["download_speed"] else 0,
                        "status": n["status"],
                        "internal_url": n["internal_url"],
                        "gid": n["gid"],
                    }
                )

            all_done: bool = (
                all(ns["status"] in ("seeding", "completed") for ns in node_statuses if ns["node_id"] != "virtual")
                if node_statuses
                else False
            )

            result.append(
                {
                    "id": task["id"],
                    "url": task["url"],
                    "filename": task["filename"],
                    "total_size": task["total_size"],
                    "downloaded_size": task["downloaded_size"],
                    "status": "all_completed" if all_done else task["status"],
                    "priority": task["priority"],
                    "created_at": task["created_at"],
                    "updated_at": task["updated_at"],
                    "nodes": node_statuses,
                }
            )

        return result

    async def get_task_detail(self, task_id: str) -> dict[str, Any] | None:
        """获取单个任务详情"""
        db = get_db()
        task = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            return None

        nodes = db.execute(
            "SELECT tn.*, n.name as node_name, n.node_type FROM task_nodes tn "
            "LEFT JOIN nodes n ON tn.node_id = n.id "
            "WHERE tn.task_id = ?",
            (task_id,),
        ).fetchall()

        node_statuses: list[dict[str, Any]] = [
            {
                "node_id": n["node_id"],
                "node_name": n["node_name"] or n["node_id"],
                "node_type": n["node_type"] or "full",
                "progress": n["progress"],
                "download_speed": n["download_speed"] if n["download_speed"] else 0,
                "status": n["status"],
                "internal_url": n["internal_url"],
                "local_path": n["local_path"],
                "gid": n["gid"],
            }
            for n in nodes
        ]

        return {
            "id": task["id"],
            "url": task["url"],
            "filename": task["filename"],
            "total_size": task["total_size"],
            "downloaded_size": task["downloaded_size"],
            "status": task["status"],
            "priority": task["priority"],
            "created_at": task["created_at"],
            "updated_at": task["updated_at"],
            "nodes": node_statuses,
        }

    async def batch_pause_tasks(self, task_ids: list[str]) -> dict[str, Any]:
        """批量暂停任务"""
        success = 0
        failed = 0
        errors: list[dict[str, Any]] = []
        for task_id in task_ids:
            try:
                await self.pause_task(task_id)
                success += 1
            except Exception as e:
                failed += 1
                errors.append({"task_id": task_id, "error": str(e)})
                logger.warning("Batch pause: task %s failed: %s", task_id, e)
        return {"success": success, "failed": failed, "errors": errors}

    async def batch_resume_tasks(self, task_ids: list[str]) -> dict[str, Any]:
        """批量恢复任务"""
        success = 0
        failed = 0
        errors: list[dict[str, Any]] = []
        for task_id in task_ids:
            try:
                await self.resume_task(task_id)
                success += 1
            except Exception as e:
                failed += 1
                errors.append({"task_id": task_id, "error": str(e)})
                logger.warning("Batch resume: task %s failed: %s", task_id, e)
        return {"success": success, "failed": failed, "errors": errors}

    async def batch_delete_tasks(self, task_ids: list[str]) -> dict[str, Any]:
        """批量删除任务"""
        success = 0
        failed = 0
        errors: list[dict[str, Any]] = []
        for task_id in task_ids:
            try:
                await self.delete_task(task_id)
                success += 1
            except Exception as e:
                failed += 1
                errors.append({"task_id": task_id, "error": str(e)})
                logger.warning("Batch delete: task %s failed: %s", task_id, e)
        return {"success": success, "failed": failed, "errors": errors}

    # ---- 后台循环 ----

    async def _status_update_loop(self) -> None:
        """定期轮询 aria2 更新本地任务进度"""
        while self._running:
            try:
                db = get_db()
                active_tasks = db.execute(
                    "SELECT tn.task_id, tn.gid FROM task_nodes tn "
                    "JOIN tasks t ON tn.task_id = t.id "
                    "WHERE tn.status NOT IN ('seeding', 'complete', 'failed') "
                    "AND tn.gid IS NOT NULL AND tn.node_id = ?",
                    (config["node_id"],),
                ).fetchall()

                if active_tasks:
                    logger.debug("Status poll: %d active tasks", len(active_tasks))

                for row in active_tasks:
                    try:
                        info: dict[str, Any] | None = await get_status(row["gid"])
                        if info:
                            speed: int = int(info.get("speed", 0))
                            progress: float = info["progress"] / 100
                            db.execute(
                                "UPDATE task_nodes SET progress = ?, status = ?, download_speed = ?, updated_at = ? "
                                "WHERE task_id = ? AND node_id = ?",
                                (
                                    progress,
                                    info["status"],
                                    speed,
                                    datetime.now(UTC).isoformat(),
                                    row["task_id"],
                                    config["node_id"],
                                ),
                            )
                            db.execute(
                                "UPDATE tasks SET downloaded_size = ?, total_size = ?, updated_at = ? WHERE id = ?",
                                (
                                    info["completed_size"],
                                    info["total_size"],
                                    datetime.now(UTC).isoformat(),
                                    row["task_id"],
                                ),
                            )

                            if info["status"] == "complete":
                                files: list[dict[str, Any]] = info.get("files", [])
                                local_path: str = files[0]["path"] if files else ""
                                db.execute(
                                    "UPDATE task_nodes SET status = 'seeding', local_path = ? "
                                    "WHERE task_id = ? AND node_id = ?",
                                    (local_path, row["task_id"], config["node_id"]),
                                )
                                db.execute(
                                    "UPDATE tasks SET status = 'completed' WHERE id = ?",
                                    (row["task_id"],),
                                )
                                db.commit()
                                logger.info("Task %s: download completed, path=%s", row["task_id"], local_path)
                                add_event(
                                    row["task_id"],
                                    config["node_id"],
                                    "download_completed",
                                    json.dumps({"path": local_path}),
                                )

                                # 发送完成通知
                                try:
                                    from app.agent.notifier import notify_task_completed
                                    task_row = db.execute(
                                        "SELECT filename, total_size FROM tasks WHERE id = ?", (row["task_id"],)
                                    ).fetchone()
                                    task_name: str = task_row["filename"] if task_row and task_row["filename"] else row["task_id"]
                                    task_total_size: int = task_row["total_size"] if task_row else info.get("total_size", 0)
                                    asyncio.create_task(notify_task_completed(
                                        row["task_id"],
                                        task_name,
                                        task_total_size,
                                        local_path,
                                    ))
                                except Exception as ne:
                                    logger.warning("Notification failed for task %s: %s", row["task_id"], ne)
                            db.commit()
                    except Exception as e:
                        err_msg: str = str(e)
                        if "aria2 RPC error" in err_msg or "not found" in err_msg.lower():
                            logger.info("GID %s no longer in aria2, marking as complete", row["gid"])
                            db.execute(
                                "UPDATE task_nodes SET status = 'complete', progress = 1.0 "
                                "WHERE task_id = ? AND node_id = ?",
                                (row["task_id"], config["node_id"]),
                            )
                            db.execute("UPDATE tasks SET status = 'completed' WHERE id = ?", (row["task_id"],))
                            db.commit()

                            # 发送完成通知（aria2 已移除但任务完成）
                            try:
                                from app.agent.notifier import notify_task_completed
                                task_row = db.execute(
                                    "SELECT filename, total_size FROM tasks WHERE id = ?", (row["task_id"],)
                                ).fetchone()
                                task_name: str = task_row["filename"] if task_row and task_row["filename"] else row["task_id"]
                                task_total_size: int = task_row["total_size"] if task_row else 0
                                asyncio.create_task(notify_task_completed(
                                    row["task_id"],
                                    task_name,
                                    task_total_size,
                                ))
                            except Exception as ne:
                                logger.warning("Notification failed for task %s: %s", row["task_id"], ne)
                        else:
                            logger.warning("Status poll error for gid=%s: %s", row["gid"], e)
            except Exception:
                logger.debug("Status poll loop error", exc_info=True)

            # 任务完成后尝试启动更多 pending 任务
            await self._try_start_pending()

            await asyncio.sleep(3)

    async def _source_check_loop(self) -> None:
        """检查本地新完成的任务需要分享给其他节点"""
        # Download-Only 节点不上传文件给其他节点
        if not can_upload():
            logger.info("Source check disabled: node %s is %s, cannot upload", config["node_id"], get_local_node_type())
            return

        while self._running:
            try:
                db = get_db()
                rows = db.execute(
                    "SELECT tn.task_id, tn.local_path FROM task_nodes tn "
                    "WHERE tn.status = 'seeding' AND tn.node_id = ? AND tn.internal_url IS NULL",
                    (config["node_id"],),
                ).fetchall()

                for row in rows:
                    if row["local_path"]:
                        local_path: Path = Path(row["local_path"])
                        filename: str = local_path.name
                        public_host: str = config.get("host", "localhost")
                        if public_host in ("0.0.0.0", "127.0.0.1", "localhost"):
                            public_host = str(config.get("peer_host", config.get("host")))

                        internal_url: str = (
                            f"http://{public_host}:{config.get('file_server_port', 18791)}"
                            f"/tasks/{row['task_id']}/{filename}"
                        )
                        db.execute(
                            "UPDATE task_nodes SET internal_url = ? WHERE task_id = ? AND node_id = ?",
                            (internal_url, row["task_id"], config["node_id"]),
                        )
                        db.commit()

                        # 通知其他节点：我有文件（只通知需要源的节点）
                        peers = config.get("peers", [])
                        target_peers = filter_peers_for_source_notify(peers)
                        for peer in target_peers:
                            if peer.get("id") != config.get("node_id"):
                                asyncio.create_task(self._notify_peer_source(peer, row["task_id"]))
            except Exception:
                logger.debug("Source check loop error", exc_info=True)

            await asyncio.sleep(10)

    async def _notify_peer_source(self, peer: dict[str, Any], task_id: str) -> None:
        """通知对等节点：我有可用源"""
        # Download-Only 节点不通知源（它自己不需要上传）
        if not can_upload():
            return

        public_host: str = str(config.get("host", "localhost"))
        if public_host in ("0.0.0.0", "127.0.0.1", "localhost"):
            public_host = str(config.get("peer_host", config.get("host")))

        internal_url: str = f"http://{public_host}:{config.get('file_server_port', 18791)}/tasks/{task_id}/{task_id}"
        result: dict[str, Any] = await self.p2p.send_source(
            peer,
            {
                "task_id": task_id,
                "source_node": config["node_id"],
                "internal_url": internal_url,
            },
        )
        if "error" in result:
            logger.warning("Source notification to %s failed: %s", peer.get("id"), result["error"])

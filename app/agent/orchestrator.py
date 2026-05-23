"""
Allfiledown — 任务编排调度
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
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
        logger.info("Orchestrator background loops started")
        return self

    async def stop(self) -> None:
        self._running = False

    # ---- 任务生命周期 ----

    async def create_task(self, url: str, filename: str | None = None) -> str:
        """创建新下载任务（本地）"""
        task_id: str = str(uuid.uuid4())[:12]
        download_dir: Path = Path(config["download_dir"]) / task_id
        download_dir.mkdir(parents=True, exist_ok=True)

        logger.info("Creating task %s: %s filename=%s", task_id, url, filename)

        db = get_db()
        db.execute(
            "INSERT INTO tasks (id, url, filename, status) VALUES (?, ?, ?, ?)",
            (task_id, url, filename or "", "downloading"),
        )
        db.execute(
            "INSERT INTO task_nodes (task_id, node_id, status) VALUES (?, ?, ?)",
            (task_id, config["node_id"], "downloading"),
        )
        db.commit()

        # 启动 aria2 下载
        try:
            gid: str | None = await add_download(url, str(download_dir), filename=filename)
            logger.info("Task %s: aria2 started gid=%s", task_id, gid)
            db.execute(
                "UPDATE task_nodes SET gid = ? WHERE task_id = ? AND node_id = ?",
                (gid, task_id, config["node_id"]),
            )
            db.execute(
                "UPDATE tasks SET updated_at = ? WHERE id = ?",
                (datetime.now(UTC).isoformat(), task_id),
            )
            db.commit()
            add_event(task_id, config["node_id"], "download_started", json.dumps({"url": url}))
        except Exception as e:
            logger.warning("Task %s: aria2 failed: %s", task_id, e)
            db.execute(
                "UPDATE task_nodes SET status = ? WHERE task_id = ? AND node_id = ?",
                (f"failed: {e}", task_id, config["node_id"]),
            )
            db.execute(
                "UPDATE tasks SET status = ? WHERE id = ?",
                ("failed", task_id),
            )
            db.commit()
            add_event(task_id, config["node_id"], "download_failed", str(e))

        # 广播给对等节点
        peers: list[dict[str, Any]] = config.get("peers", [])
        logger.info("Task %s: broadcasting to %d peers", task_id, len(peers))
        for peer in peers:
            if peer.get("node_type", "full") in ("full", "download"):
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

    async def receive_task(self, task_id: str, url: str, filename: str | None) -> dict[str, Any]:
        """收到其他节点广播的任务"""
        db = get_db()
        existing = db.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if existing:
            return {"status": "already_exists"}

        download_dir: Path = Path(config["download_dir"]) / task_id
        download_dir.mkdir(parents=True, exist_ok=True)

        db.execute(
            "INSERT INTO tasks (id, url, filename, status) VALUES (?, ?, ?, ?)",
            (task_id, url, filename or "", "downloading"),
        )
        db.execute(
            "INSERT INTO task_nodes (task_id, node_id, status) VALUES (?, ?, ?)",
            (task_id, config["node_id"], "downloading"),
        )
        db.commit()

        try:
            gid: str | None = await add_download(url, str(download_dir), filename=filename)
            db.execute(
                "UPDATE task_nodes SET gid = ? WHERE task_id = ? AND node_id = ?",
                (gid, task_id, config["node_id"]),
            )
            db.commit()
            add_event(task_id, config["node_id"], "download_started", json.dumps({"url": url}))
        except Exception as e:
            db.execute(
                "UPDATE task_nodes SET status = ? WHERE task_id = ? AND node_id = ?",
                (f"failed: {e}", task_id, config["node_id"]),
            )
            db.commit()
            add_event(task_id, config["node_id"], "download_failed", str(e))

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
        return {"status": "cancelled"}

    async def delete_task(self, task_id: str) -> dict[str, Any]:
        """删除任务记录"""
        db = get_db()
        rows = db.execute(
            "SELECT gid FROM task_nodes WHERE task_id = ? AND gid IS NOT NULL",
            (task_id,),
        ).fetchall()
        from contextlib import suppress

        for row in rows:
            with suppress(Exception):
                await aria2_remove(row["gid"])

        db.execute("DELETE FROM task_nodes WHERE task_id = ?", (task_id,))
        db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        db.commit()
        return {"status": "deleted"}

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
        return {"status": "resumed"}

    async def retry_task(self, task_id: str) -> dict[str, Any]:
        """重新下载失败/取消的任务"""
        db = get_db()
        task = db.execute("SELECT id, url, filename FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            return {"error": "Task not found"}
        url: str = task["url"]
        filename: str = task["filename"]
        await self.delete_task(task_id)
        new_id: str = await self.create_task(url, filename or None)
        return {"status": "retried", "task_id": new_id}

    # ---- 查询 ----

    async def get_task_list(self) -> list[dict[str, Any]]:
        """获取所有任务列表"""
        db = get_db()
        tasks = db.execute("SELECT * FROM tasks ORDER BY created_at DESC").fetchall()

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
            "created_at": task["created_at"],
            "updated_at": task["updated_at"],
            "nodes": node_statuses,
        }

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
                                logger.info("Task %s: download completed, path=%s", row["task_id"], local_path)
                                add_event(
                                    row["task_id"],
                                    config["node_id"],
                                    "download_completed",
                                    json.dumps({"path": local_path}),
                                )
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
                        else:
                            logger.warning("Status poll error for gid=%s: %s", row["gid"], e)
            except Exception:
                logger.debug("Status poll loop error", exc_info=True)

            await asyncio.sleep(3)

    async def _source_check_loop(self) -> None:
        """检查本地新完成的任务需要分享给其他节点"""
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

                        # 通知其他节点：我有文件
                        peers = config.get("peers", [])
                        for peer in peers:
                            if peer.get("id") != config.get("node_id"):
                                asyncio.create_task(self._notify_peer_source(peer, row["task_id"]))
            except Exception:
                logger.debug("Source check loop error", exc_info=True)

            await asyncio.sleep(10)

    async def _notify_peer_source(self, peer: dict[str, Any], task_id: str) -> None:
        """通知对等节点：我有可用源"""
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

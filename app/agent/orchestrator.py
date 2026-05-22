"""
Allfiledown — 任务编排调度
"""
import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.config import config
from app.database import get_db, add_event, init_db
from app.agent.downloader import (
    add_download, get_status, pause, unpause, remove, add_source, tell_active
)
from app.agent.p2p import P2PClient


# Global instance (injected by main.py on startup)
orchestrator = None


class Orchestrator:
    """任务编排器 — 负责协调本地 aria2 + 远程节点"""

    def __init__(self):
        self.p2p = P2PClient(auth_token=config.get("auth_token", ""))
        self._status_loop_running = False
        self._source_check_running = False
        self._running = True

    async def start(self):
        """启动后台协程"""
        init_db()
        self._status_loop_running = True
        self._source_check_running = True
        asyncio.create_task(self._status_update_loop())
        asyncio.create_task(self._source_check_loop())
        return self

    async def stop(self):
        self._running = False

    async def create_task(self, url, filename=None):
        """创建新下载任务（本地）"""
        task_id = str(uuid.uuid4())[:12]
        download_dir = Path(config["download_dir"]) / task_id
        download_dir.mkdir(parents=True, exist_ok=True)

        # 数据库记录
        db = get_db()
        db.execute(
            "INSERT INTO tasks (id, url, filename, status) VALUES (?, ?, ?, ?)",
            (task_id, url, filename or "", "downloading")
        )
        db.execute(
            "INSERT INTO task_nodes (task_id, node_id, status) VALUES (?, ?, ?)",
            (task_id, config["node_id"], "downloading")
        )
        db.commit()

        # 启动 aria2 下载
        try:
            gid = await add_download(
                url,
                str(download_dir),
                filename=filename
            )
            db.execute(
                "UPDATE task_nodes SET gid = ? WHERE task_id = ? AND node_id = ?",
                (gid, task_id, config["node_id"])
            )
            db.execute(
                "UPDATE tasks SET updated_at = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), task_id)
            )
            db.commit()
            add_event(task_id, config["node_id"], "download_started", json.dumps({"url": url}))
        except Exception as e:
            db.execute(
                "UPDATE task_nodes SET status = ? WHERE task_id = ? AND node_id = ?",
                (f"failed: {e}", task_id, config["node_id"])
            )
            db.execute(
                "UPDATE tasks SET status = ? WHERE id = ?",
                ("failed", task_id)
            )
            db.commit()
            add_event(task_id, config["node_id"], "download_failed", str(e))

        # 广播给对等节点
        peers = config.get("peers", [])
        for peer in peers:
            if peer.get("node_type", "full") in ("full", "download"):
                asyncio.create_task(self._broadcast_task(peer, task_id, url, filename))

        return task_id

    async def _broadcast_task(self, peer, task_id, url, filename):
        """向一个对等节点广播任务"""
        result = await self.p2p.send_task(peer, {
            "task_id": task_id,
            "url": url,
            "filename": filename,
            "source_node": config["node_id"],
            "source_info": {
                "host": config.get("host", ""),
                "port": config.get("file_server_port", 18791),
                "token": config.get("auth_token", "")
            }
        })
        if "error" in result:
            # 标记节点离线
            db = get_db()
            db.execute("UPDATE nodes SET status = ? WHERE id = ?", ("offline", peer.get("id", "unknown")))
            db.commit()

    async def receive_task(self, task_id, url, filename):
        """收到其他节点广播的任务"""
        db = get_db()
        existing = db.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if existing:
            return {"status": "already_exists"}

        download_dir = Path(config["download_dir"]) / task_id
        download_dir.mkdir(parents=True, exist_ok=True)

        db.execute(
            "INSERT INTO tasks (id, url, filename, status) VALUES (?, ?, ?, ?)",
            (task_id, url, filename or "", "downloading")
        )
        db.execute(
            "INSERT INTO task_nodes (task_id, node_id, status) VALUES (?, ?, ?)",
            (task_id, config["node_id"], "downloading")
        )
        db.commit()

        try:
            gid = await add_download(url, str(download_dir), filename=filename)
            db.execute(
                "UPDATE task_nodes SET gid = ? WHERE task_id = ? AND node_id = ?",
                (gid, task_id, config["node_id"])
            )
            db.commit()
            add_event(task_id, config["node_id"], "download_started", json.dumps({"url": url}))
        except Exception as e:
            db.execute(
                "UPDATE task_nodes SET status = ? WHERE task_id = ? AND node_id = ?",
                (f"failed: {e}", task_id, config["node_id"])
            )
            db.commit()
            add_event(task_id, config["node_id"], "download_failed", str(e))

        return {"status": "accepted", "task_id": task_id}

    async def receive_source(self, task_id, source_node_id, internal_url):
        """收到内部源通知"""
        db = get_db()
        row = db.execute(
            "SELECT gid, status FROM task_nodes WHERE task_id = ? AND node_id = ?",
            (task_id, config["node_id"])
        ).fetchone()

        if row and row["gid"] and row["status"] == "downloading":
            # 为现有下载添加新源
            try:
                result = await add_source(row["gid"], internal_url)
                add_event(task_id, config["node_id"], "source_added",
                          json.dumps({"from": source_node_id, "url": internal_url}))
                return {"status": "source_added", "result": result}
            except Exception as e:
                return {"status": "error", "message": str(e)}

        # 记录源信息（即使还没下载，以后用）
        db.execute(
            "UPDATE task_nodes SET internal_url = ? WHERE task_id = ? AND node_id = ?",
            (internal_url, task_id, source_node_id)
        )
        db.commit()
        return {"status": "recorded"}

    async def _status_update_loop(self):
        """定期轮询 aria2 更新本地任务进度"""
        while self._running:
            try:
                db = get_db()
                # 获取所有正在下载的任务
                rows = db.execute(
                    "SELECT tn.task_id, tn.gid FROM task_nodes tn "
                    "JOIN tasks t ON tn.task_id = t.id "
                    "WHERE tn.status NOT IN ('seeding', 'complete', 'failed') AND tn.gid IS NOT NULL AND tn.node_id = ?",
                    (config["node_id"],)
                ).fetchall()

                for row in rows:
                    try:
                        info = await get_status(row["gid"])
                        if info:
                            db.execute(
                                "UPDATE task_nodes SET progress = ?, status = ?, updated_at = ? WHERE task_id = ? AND node_id = ?",
                                (info["progress"] / 100, info["status"], 
                                 datetime.now(timezone.utc).isoformat(),
                                 row["task_id"], config["node_id"])
                            )
                            db.execute(
                                "UPDATE tasks SET downloaded_size = ?, total_size = ?, updated_at = ? WHERE id = ?",
                                (info["completed_size"], info["total_size"],
                                 datetime.now(timezone.utc).isoformat(), row["task_id"])
                            )

                            # 如果下载完成
                            if info["status"] == "complete":
                                files = info.get("files", [])
                                local_path = files[0]["path"] if files else ""
                                db.execute(
                                    "UPDATE task_nodes SET status = 'seeding', local_path = ? WHERE task_id = ? AND node_id = ?",
                                    (local_path, row["task_id"], config["node_id"])
                                )
                                db.execute(
                                    "UPDATE tasks SET status = 'completed' WHERE id = ?",
                                    (row["task_id"],)
                                )
                                db.commit()
                                add_event(row["task_id"], config["node_id"], "download_completed",
                                          json.dumps({"path": local_path}))

                            db.commit()
                    except Exception:
                        pass

            except Exception:
                pass

            await asyncio.sleep(3)  # 每 3 秒轮询一次

    async def _source_check_loop(self):
        """检查本地是否新完成的任务需要分享给其他节点"""
        while self._running:
            try:
                db = get_db()
                # 找到刚完成但还没广播的任务
                rows = db.execute(
                    "SELECT tn.task_id, tn.local_path FROM task_nodes tn "
                    "WHERE tn.status = 'seeding' AND tn.node_id = ? AND tn.internal_url IS NULL",
                    (config["node_id"],)
                ).fetchall()

                for row in rows:
                    if row["local_path"]:
                        local_path = Path(row["local_path"])
                        filename = local_path.name
                        public_host = config.get('host', 'localhost')
                        # avoid binding to 0.0.0.0 or localhost in URLs
                        if public_host in ('0.0.0.0', '127.0.0.1', 'localhost'):
                            public_host = 'localhost'
                        internal_url = f"http://{public_host}:{config.get('file_server_port', 18791)}/tasks/{row['task_id']}/{filename}"
                        if config.get("auth_token"):
                            internal_url += f"?token={config['auth_token']}"

                        db.execute(
                            "UPDATE task_nodes SET internal_url = ? WHERE task_id = ? AND node_id = ?",
                            (internal_url, row["task_id"], config["node_id"])
                        )
                        db.commit()

                        # 广播给所有节点
                        peers = config.get("peers", [])
                        for peer in peers:
                            if peer.get("node_type", "full") in ("full", "download"):
                                asyncio.create_task(self._broadcast_source(peer, row["task_id"], internal_url))

            except Exception:
                pass

            await asyncio.sleep(5)

    async def _broadcast_source(self, peer, task_id, internal_url):
        """广播内部源信息"""
        await self.p2p.send_source(peer, {
            "task_id": task_id,
            "source_node": config["node_id"],
            "internal_url": internal_url
        })

    async def delete_task(self, task_id):
        """彻底删除任务（文件和记录）"""
        db = get_db()

        # 取消 aria2 下载（如果有 gid）
        rows = db.execute(
            "SELECT gid FROM task_nodes WHERE task_id = ? AND gid IS NOT NULL",
            (task_id,)
        ).fetchall()
        for row in rows:
            try:
                await remove(row["gid"])
            except Exception:
                pass

        # 删除本地文件
        task_dir = Path(config["download_dir"]) / task_id
        if task_dir.exists():
            import shutil
            shutil.rmtree(task_dir, ignore_errors=True)

        # 删除数据库记录
        db.execute("DELETE FROM events WHERE task_id = ?", (task_id,))
        db.execute("DELETE FROM task_nodes WHERE task_id = ?", (task_id,))
        db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        db.commit()
        return {"status": "deleted"}

    async def cancel_task(self, task_id):
        """取消下载任务（保留记录）"""
        db = get_db()

        # 取消 aria2 下载
        rows = db.execute(
            "SELECT gid FROM task_nodes WHERE task_id = ? AND gid IS NOT NULL",
            (task_id,)
        ).fetchall()
        for row in rows:
            try:
                await remove(row["gid"])
            except Exception:
                pass

        db.execute(
            "UPDATE task_nodes SET status = 'cancelled' WHERE task_id = ?",
            (task_id,)
        )
        db.execute(
            "UPDATE tasks SET status = 'cancelled', updated_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), task_id)
        )
        db.commit()
        add_event(task_id, config["node_id"], "cancelled", "{}")
        return {"status": "cancelled"}

    async def clear_completed(self):
        """清除所有已完成/失败的下载任务"""
        db = get_db()
        rows = db.execute("SELECT id FROM tasks WHERE status IN ('completed', 'all_completed', 'failed', 'cancelled')").fetchall()
        task_ids = [r["id"] for r in rows]
        for tid in task_ids:
            await self.delete_task(tid)
        return {"status": "cleared", "count": len(task_ids)}

    async def pause_task(self, task_id):
        """暂停下载"""
        db = get_db()
        rows = db.execute(
            "SELECT gid FROM task_nodes WHERE task_id = ? AND gid IS NOT NULL",
            (task_id,)
        ).fetchall()
        for row in rows:
            try:
                await pause(row["gid"])
            except Exception:
                pass
        db.execute(
            "UPDATE task_nodes SET status = 'paused' WHERE task_id = ? AND status = 'downloading'",
            (task_id,)
        )
        db.execute(
            "UPDATE tasks SET status = 'paused', updated_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), task_id)
        )
        db.commit()
        return {"status": "paused"}

    async def resume_task(self, task_id):
        """继续下载"""
        db = get_db()
        rows = db.execute(
            "SELECT gid FROM task_nodes WHERE task_id = ? AND gid IS NOT NULL",
            (task_id,)
        ).fetchall()
        for row in rows:
            try:
                await unpause(row["gid"])
            except Exception:
                pass
        db.execute(
            "UPDATE task_nodes SET status = 'downloading' WHERE task_id = ? AND status = 'paused'",
            (task_id,)
        )
        db.execute(
            "UPDATE tasks SET status = 'downloading', updated_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), task_id)
        )
        db.commit()
        return {"status": "resumed"}

    async def retry_task(self, task_id):
        """重新下载失败/取消的任务"""
        db = get_db()
        task = db.execute("SELECT id, url, filename FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            return {"error": "Task not found"}
        url = task["url"]
        filename = task["filename"]
        # 删除旧任务
        await self.delete_task(task_id)
        # 重新创建
        new_id = await self.create_task(url, filename or None)
        return {"status": "retried", "task_id": new_id}

    async def get_task_list(self):
        """获取所有任务列表"""
        db = get_db()
        tasks = db.execute(
            "SELECT * FROM tasks ORDER BY created_at DESC"
        ).fetchall()

        result = []
        for task in tasks:
            # 获取各节点状态
            nodes = db.execute(
                "SELECT tn.*, n.name as node_name, n.node_type FROM task_nodes tn "
                "LEFT JOIN nodes n ON tn.node_id = n.id "
                "WHERE tn.task_id = ?",
                (task["id"],)
            ).fetchall()

            node_statuses = []
            for n in nodes:
                node_statuses.append({
                    "node_id": n["node_id"],
                    "node_name": n["node_name"] or n["node_id"],
                    "node_type": n["node_type"] or "full",
                    "progress": n["progress"],
                    "status": n["status"],
                    "internal_url": n["internal_url"],
                    "gid": n["gid"]
                })

            # 检查是否所有节点都完成了
            all_done = all(
                ns["status"] in ("seeding", "completed") 
                for ns in node_statuses if ns["node_id"] != "virtual"
            ) if node_statuses else False

            result.append({
                "id": task["id"],
                "url": task["url"],
                "filename": task["filename"],
                "total_size": task["total_size"],
                "downloaded_size": task["downloaded_size"],
                "status": "all_completed" if all_done else task["status"],
                "created_at": task["created_at"],
                "updated_at": task["updated_at"],
                "nodes": node_statuses
            })

        return result

    async def get_task_detail(self, task_id):
        """获取单个任务详情"""
        db = get_db()
        task = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            return None

        nodes = db.execute(
            "SELECT tn.*, n.name as node_name, n.node_type FROM task_nodes tn "
            "LEFT JOIN nodes n ON tn.node_id = n.id "
            "WHERE tn.task_id = ?",
            (task_id,)
        ).fetchall()

        node_statuses = [{
            "node_id": n["node_id"],
            "node_name": n["node_name"] or n["node_id"],
            "node_type": n["node_type"] or "full",
            "progress": n["progress"],
            "status": n["status"],
            "internal_url": n["internal_url"],
            "local_path": n["local_path"],
            "gid": n["gid"]
        } for n in nodes]

        return {
            "id": task["id"],
            "url": task["url"],
            "filename": task["filename"],
            "total_size": task["total_size"],
            "downloaded_size": task["downloaded_size"],
            "status": task["status"],
            "created_at": task["created_at"],
            "updated_at": task["updated_at"],
            "nodes": node_statuses
        }

"""
Allfiledown — 断点续传跨节点同步

功能：
1. 节点上线后从其他节点拉取任务列表
2. 根据角色决定是否参与下载
3. 任务状态变更广播给所有节点
4. 定期同步缺失的任务

场景：
- 节点重启后自动恢复之前的任务
- 新节点加入集群时同步现有任务
- 网络断开后重新连接，补全缺失任务
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.agent.p2p import P2PClient
from app.agent.role import can_download, get_local_node_type
from app.config import config
from app.database import get_db

logger = logging.getLogger("afd.sync")

SYNC_INTERVAL = 60  # 定期同步间隔（秒）


class TaskSyncManager:
    """任务同步管理器 — 保持节点间任务一致性"""

    def __init__(self) -> None:
        self.p2p = P2PClient(auth_token=str(config.get("auth_token", "")))
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """启动同步管理"""
        self._running = True
        # 立即执行一次全量同步
        asyncio.create_task(self._initial_sync())
        # 启动定期同步
        self._task = asyncio.create_task(self._sync_loop())
        logger.info("Task sync manager started")

    async def stop(self) -> None:
        """停止同步"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Task sync manager stopped")

    async def _initial_sync(self) -> None:
        """启动时从所有在线节点同步任务"""
        logger.info("Starting initial task sync...")
        peers = config.get("peers", [])
        if not peers:
            logger.info("No peers configured, skipping initial sync")
            return

        for peer in peers:
            try:
                await self._sync_from_peer(peer)
            except Exception as e:
                logger.warning("Initial sync from %s failed: %s", peer.get("id"), e)

        logger.info("Initial task sync complete")

    async def _sync_from_peer(self, peer: dict[str, Any]) -> dict[str, Any]:
        """从指定节点同步任务"""
        peer_id = peer.get("id", "unknown")
        logger.debug("Syncing tasks from %s", peer_id)

        # 获取对方任务列表
        result = await self.p2p.query_status(peer)
        if "error" in result:
            logger.warning("Failed to get tasks from %s: %s", peer_id, result["error"])
            return {"synced": 0, "skipped": 0, "error": result["error"]}

        remote_tasks = result.get("tasks", [])
        if not remote_tasks:
            logger.debug("No tasks from %s", peer_id)
            return {"synced": 0, "skipped": 0}

        db = get_db()
        my_node_id = config["node_id"]
        synced = 0
        skipped = 0

        for task in remote_tasks:
            task_id = task.get("id")
            if not task_id:
                continue

            # 检查本地是否已有此任务
            existing = db.execute(
                "SELECT id FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()

            if existing:
                # 已有任务，只同步状态（如果对方已完成，标记为可下载源）
                await self._sync_task_status(task, peer)
                skipped += 1
                continue

            # 新任务，根据角色决定是否接受
            if not can_download():
                logger.debug("Skipping task %s: node is %s", task_id, get_local_node_type())
                skipped += 1
                continue

            # 创建任务记录（不立即下载，等待手动触发或自动下载）
            url = task.get("url", "")
            filename = task.get("filename", "")
            status = task.get("status", "pending")
            total_size = task.get("total_size", 0)

            db.execute(
                "INSERT INTO tasks (id, url, filename, total_size, status) VALUES (?, ?, ?, ?, ?)",
                (task_id, url, filename, total_size, status),
            )
            db.execute(
                "INSERT INTO task_nodes (task_id, node_id, status) VALUES (?, ?, ?)",
                (task_id, my_node_id, "pending"),
            )
            db.commit()

            logger.info("Synced new task from %s: %s (%s)", peer_id, task_id, filename or url)
            synced += 1

        return {"synced": synced, "skipped": skipped}

    async def _sync_task_status(self, task: dict[str, Any], source_peer: dict[str, Any]) -> None:
        """同步已有任务的状态（特别是 completed 任务的内部源）"""
        task_id = task.get("id")
        if not task_id:
            return

        nodes = task.get("nodes", [])
        for node in nodes:
            if node.get("status") in ("seeding", "completed") and node.get("internal_url"):
                # 对方已完成，记录其内部源
                db = get_db()
                existing = db.execute(
                    "SELECT internal_url FROM task_nodes WHERE task_id = ? AND node_id = ?",
                    (task_id, node["node_id"]),
                ).fetchone()

                if not existing or not existing["internal_url"]:
                    db.execute(
                        "INSERT OR REPLACE INTO task_nodes (task_id, node_id, status, internal_url, progress) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (task_id, node["node_id"], "seeding", node["internal_url"], 1.0),
                    )
                    db.commit()
                    logger.info(
                        "Synced source for task %s from %s: %s",
                        task_id, node["node_id"], node["internal_url"],
                    )

    async def _sync_loop(self) -> None:
        """定期同步循环"""
        while self._running:
            try:
                await asyncio.sleep(SYNC_INTERVAL)
                if not self._running:
                    break

                peers = config.get("peers", [])
                for peer in peers:
                    try:
                        await self._sync_from_peer(peer)
                    except Exception as e:
                        logger.debug("Sync from %s failed: %s", peer.get("id"), e)

            except asyncio.CancelledError:
                break
            except Exception:
                logger.debug("Sync loop error", exc_info=True)

    async def broadcast_task_update(self, task_id: str, event_type: str, payload: dict[str, Any] | None = None) -> None:
        """广播任务状态变更给所有节点（可选）"""
        # 目前通过 _source_check_loop 和心跳机制间接实现
        # 未来可以扩展为主动推送
        pass


# 全局实例
task_sync_manager: TaskSyncManager | None = None


async def start_task_sync() -> TaskSyncManager:
    """启动任务同步"""
    global task_sync_manager
    task_sync_manager = TaskSyncManager()
    await task_sync_manager.start()
    return task_sync_manager


async def stop_task_sync() -> None:
    """停止任务同步"""
    global task_sync_manager
    if task_sync_manager:
        await task_sync_manager.stop()
        task_sync_manager = None

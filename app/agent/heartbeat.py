"""
Allfiledown — 节点心跳与自动发现

功能：
1. 节点启动时向所有已知节点注册自己
2. 定期心跳（ping）维持在线状态
3. 发现新节点（从对方获取节点列表并合并）
4. 离线节点自动标记，重新上线后恢复
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from app.agent.p2p import P2PClient
from app.agent.role import get_local_node_type
from app.config import config
from app.database import get_db

logger = logging.getLogger("afd.heartbeat")

HEARTBEAT_INTERVAL = 30  # 心跳间隔（秒）
OFFLINE_THRESHOLD = 90   # 超过此秒数未心跳视为离线


class HeartbeatManager:
    """心跳管理器 — 维护节点在线状态"""

    def __init__(self) -> None:
        self.p2p = P2PClient(auth_token=str(config.get("auth_token", "")))
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """启动心跳管理"""
        self._running = True
        # 立即执行一次注册
        asyncio.create_task(self._initial_register())
        # 启动定期心跳
        self._task = asyncio.create_task(self._heartbeat_loop())
        logger.info("Heartbeat manager started")

    async def stop(self) -> None:
        """停止心跳"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Heartbeat manager stopped")

    async def _initial_register(self) -> None:
        """启动时向所有已知节点注册自己"""
        my_info = {
            "node_id": config["node_id"],
            "name": config.get("node_name", config["node_id"]),
            "host": config.get("peer_host", config.get("host", "localhost")),
            "port": int(config.get("port", 18790)),
            "node_type": get_local_node_type(),
            "auth_token": config.get("auth_token", ""),
        }

        peers = config.get("peers", [])
        logger.info("Registering self to %d known peers", len(peers))

        for peer in peers:
            try:
                result = await self.p2p.register_node(peer, my_info)
                if "error" in result:
                    logger.warning("Register to %s failed: %s", peer.get("id"), result["error"])
                else:
                    logger.info("Registered to %s", peer.get("id"))
                    # 从对方获取节点列表，发现新节点
                    await self._discover_from_peer(peer)
            except Exception as e:
                logger.warning("Register to %s error: %s", peer.get("id"), e)

    async def _discover_from_peer(self, peer: dict[str, Any]) -> None:
        """从对等节点获取节点列表，合并到本地"""
        try:
            result = await self.p2p.get_peers(peer)
            if "error" in result:
                return

            remote_nodes = result.get("nodes", [])
            db = get_db()
            local_peers = config.get("peers", [])
            added = 0

            for node in remote_nodes:
                node_id = node.get("id")
                if not node_id or node_id == config["node_id"]:
                    continue

                # 检查是否已存在
                existing = db.execute("SELECT id FROM nodes WHERE id = ?", (node_id,)).fetchone()
                if not existing:
                    # 新节点，加入数据库
                    db.execute(
                        "INSERT INTO nodes (id, name, host, port, node_type, auth_token, status) "
                        "VALUES (?, ?, ?, ?, ?, ?, 'online')",
                        (
                            node_id,
                            node.get("name", node_id),
                            node.get("host", ""),
                            int(node.get("port", 18790)),
                            node.get("node_type", "full"),
                            node.get("auth_token", ""),
                        ),
                    )
                    db.commit()

                    # 加入 config.peers
                    local_peers.append({
                        "id": node_id,
                        "name": node.get("name", node_id),
                        "host": node.get("host", ""),
                        "port": int(node.get("port", 18790)),
                        "node_type": node.get("node_type", "full"),
                        "auth_token": node.get("auth_token", ""),
                    })
                    added += 1
                    logger.info("Discovered new node: %s (%s:%s)", node_id, node.get("host"), node.get("port"))

            if added > 0:
                config["peers"] = local_peers
                from app.config import save_config
                save_config(config)
                logger.info("Added %d new nodes from peer %s", added, peer.get("id"))

        except Exception as e:
            logger.debug("Discover from %s failed: %s", peer.get("id"), e)

    async def _heartbeat_loop(self) -> None:
        """定期心跳循环"""
        while self._running:
            try:
                await self._do_heartbeat_round()
                await self._mark_offline_nodes()
            except Exception:
                logger.debug("Heartbeat round error", exc_info=True)

            await asyncio.sleep(HEARTBEAT_INTERVAL)

    async def _do_heartbeat_round(self) -> None:
        """执行一轮心跳"""
        peers = config.get("peers", [])
        if not peers:
            return

        db = get_db()
        my_id = config["node_id"]

        async def ping_peer(peer: dict[str, Any]) -> None:
            peer_id = peer.get("id", "unknown")
            try:
                is_online = await self.p2p.ping(peer)
                status = "online" if is_online else "offline"
                db.execute(
                    "UPDATE nodes SET status = ?, last_seen = datetime('now') WHERE id = ?",
                    (status, peer_id),
                )
                if is_online:
                    logger.debug("Heartbeat: %s is online", peer_id)
                else:
                    logger.warning("Heartbeat: %s is offline", peer_id)
            except Exception as e:
                logger.debug("Heartbeat ping to %s failed: %s", peer_id, e)
                db.execute(
                    "UPDATE nodes SET status = 'offline' WHERE id = ?",
                    (peer_id,),
                )

        # 并发 ping 所有节点
        await asyncio.gather(*[ping_peer(p) for p in peers], return_exceptions=True)
        db.commit()

    async def _mark_offline_nodes(self) -> None:
        """标记长时间未心跳的节点为离线"""
        db = get_db()
        try:
            db.execute(
                "UPDATE nodes SET status = 'offline' "
                "WHERE status = 'online' "
                "AND last_seen < datetime('now', '-{} seconds')".format(OFFLINE_THRESHOLD)
            )
            db.commit()
        except Exception:
            pass


# 全局实例
heartbeat_manager: HeartbeatManager | None = None


async def start_heartbeat() -> HeartbeatManager:
    """启动心跳管理"""
    global heartbeat_manager
    heartbeat_manager = HeartbeatManager()
    await heartbeat_manager.start()
    return heartbeat_manager


async def stop_heartbeat() -> None:
    """停止心跳"""
    global heartbeat_manager
    if heartbeat_manager:
        await heartbeat_manager.stop()
        heartbeat_manager = None

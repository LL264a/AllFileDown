"""
Allfiledown — 节点角色控制

根据 node_type 限制节点行为：
- full: 全部功能（下载+上传+Web UI）
- download: 只下载，不上传，无 Web UI 管理
- upload: 只提供已有文件作为源，不下载新任务
"""

from __future__ import annotations

from typing import Any

from app.config import config


NODE_TYPE_FULL = "full"
NODE_TYPE_DOWNLOAD = "download"
NODE_TYPE_UPLOAD = "upload"
VALID_NODE_TYPES = {NODE_TYPE_FULL, NODE_TYPE_DOWNLOAD, NODE_TYPE_UPLOAD}


def get_local_node_type() -> str:
    """获取本机节点类型"""
    nt: str = str(config.get("node_type", NODE_TYPE_FULL)).lower().strip()
    return nt if nt in VALID_NODE_TYPES else NODE_TYPE_FULL


def is_full_node() -> bool:
    return get_local_node_type() == NODE_TYPE_FULL


def is_download_only() -> bool:
    return get_local_node_type() == NODE_TYPE_DOWNLOAD


def is_upload_only() -> bool:
    return get_local_node_type() == NODE_TYPE_UPLOAD


def can_download() -> bool:
    """是否可以接受新下载任务"""
    nt = get_local_node_type()
    return nt in (NODE_TYPE_FULL, NODE_TYPE_DOWNLOAD)


def can_upload() -> bool:
    """是否可以作为源提供文件给其他节点"""
    nt = get_local_node_type()
    return nt in (NODE_TYPE_FULL, NODE_TYPE_UPLOAD)


def can_serve_web_ui() -> bool:
    """是否提供 Web UI 管理界面"""
    return is_full_node()


def can_manage_nodes() -> bool:
    """是否可以管理集群节点（增删改）"""
    return is_full_node()


def should_accept_task_broadcast(peer_node_type: str) -> bool:
    """收到任务广播时，根据对方角色判断是否接受"""
    # 只有 Full 和 Download 节点会发任务广播
    return peer_node_type in (NODE_TYPE_FULL, NODE_TYPE_DOWNLOAD)


def filter_peers_for_broadcast(peers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """过滤出应该接收任务广播的节点"""
    return [
        p for p in peers
        if str(p.get("node_type", NODE_TYPE_FULL)).lower() in (NODE_TYPE_FULL, NODE_TYPE_DOWNLOAD)
    ]


def filter_peers_for_source_notify(peers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """过滤出应该接收源通知的节点（Full 和 Download 需要源）"""
    return [
        p for p in peers
        if str(p.get("node_type", NODE_TYPE_FULL)).lower() in (NODE_TYPE_FULL, NODE_TYPE_DOWNLOAD)
    ]

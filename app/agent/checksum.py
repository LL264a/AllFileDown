"""
Allfiledown — 文件完整性校验模块
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from app.config import config
from app.database import add_event, get_db

logger = logging.getLogger("afd")

CHUNK_SIZE: int = 8192  # 8KB 分块读取，避免大文件内存溢出


def calculate_checksum(file_path: str | Path, algorithm: str = "md5") -> str:
    """计算文件校验和，大文件分块读取

    Args:
        file_path: 文件路径
        algorithm: 校验算法，支持 "md5" 和 "sha256"

    Returns:
        十六进制校验和字符串

    Raises:
        ValueError: 不支持的算法
        FileNotFoundError: 文件不存在
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    if algorithm == "md5":
        hasher = hashlib.md5()
    elif algorithm == "sha256":
        hasher = hashlib.sha256()
    else:
        raise ValueError(f"Unsupported algorithm: {algorithm}. Use 'md5' or 'sha256'.")

    with path.open("rb") as f:
        while chunk := f.read(CHUNK_SIZE):
            hasher.update(chunk)

    return hasher.hexdigest()


def verify_checksum(file_path: str | Path, expected_checksum: str, algorithm: str = "md5") -> bool:
    """验证文件校验和是否匹配

    Args:
        file_path: 文件路径
        expected_checksum: 期望的校验和
        algorithm: 校验算法

    Returns:
        True 如果校验和匹配，否则 False
    """
    try:
        actual = calculate_checksum(file_path, algorithm)
        return actual.lower() == expected_checksum.lower()
    except (FileNotFoundError, ValueError) as e:
        logger.warning("Checksum verification failed for %s: %s", file_path, e)
        return False


def get_task_checksums(task_id: str, db: sqlite3.Connection | None = None) -> dict[str, Any]:
    """获取任务在所有节点上的校验和

    Args:
        task_id: 任务 ID
        db: 可选的数据库连接

    Returns:
        {
            "task_id": str,
            "checksums": {
                "md5": str,
                "sha256": str,
            },
            "nodes": [
                {
                    "node_id": str,
                    "node_name": str,
                    "checksum_md5": str,
                    "checksum_sha256": str,
                    "local_path": str,
                    "status": str,
                }
            ]
        }
    """
    import sqlite3

    conn = db or get_db()
    task = conn.execute(
        "SELECT checksum_md5, checksum_sha256 FROM tasks WHERE id = ?", (task_id,)
    ).fetchone()

    if not task:
        return {"task_id": task_id, "checksums": {}, "nodes": []}

    rows = conn.execute(
        "SELECT tn.node_id, tn.checksum_md5, tn.checksum_sha256, "
        "tn.local_path, tn.status, n.name as node_name "
        "FROM task_nodes tn "
        "LEFT JOIN nodes n ON tn.node_id = n.id "
        "WHERE tn.task_id = ?",
        (task_id,),
    ).fetchall()

    nodes: list[dict[str, Any]] = []
    for row in rows:
        nodes.append(
            {
                "node_id": row["node_id"],
                "node_name": row["node_name"] or row["node_id"],
                "checksum_md5": row["checksum_md5"] or "",
                "checksum_sha256": row["checksum_sha256"] or "",
                "local_path": row["local_path"] or "",
                "status": row["status"],
            }
        )

    return {
        "task_id": task_id,
        "checksums": {
            "md5": task["checksum_md5"] or "",
            "sha256": task["checksum_sha256"] or "",
        },
        "nodes": nodes,
    }


def compare_checksums(task_id: str, db: sqlite3.Connection | None = None) -> dict[str, Any]:
    """比对多节点校验和是否一致

    检查所有已完成节点的 MD5 和 SHA256 校验和是否一致。
    如果存在不一致，标记任务状态为 failed。

    Args:
        task_id: 任务 ID
        db: 可选的数据库连接

    Returns:
        {
            "task_id": str,
            "consistent": bool,
            "reference_md5": str,
            "reference_sha256": str,
            "mismatched_nodes": [str],
            "missing_nodes": [str],
        }
    """
    import sqlite3

    conn = db or get_db()
    data = get_task_checksums(task_id, conn)
    nodes = data["nodes"]

    # 只比较已完成且有校验和的节点
    completed_nodes = [
        n for n in nodes
        if n["status"] in ("seeding", "completed", "complete")
        and (n["checksum_md5"] or n["checksum_sha256"])
    ]

    if not completed_nodes:
        return {
            "task_id": task_id,
            "consistent": True,  # 没有可比较的节点，视为一致
            "reference_md5": "",
            "reference_sha256": "",
            "mismatched_nodes": [],
            "missing_nodes": [
                n["node_id"]
                for n in nodes
                if n["status"] in ("seeding", "completed", "complete")
                and not (n["checksum_md5"] or n["checksum_sha256"])
            ],
        }

    # 以第一个完成节点作为参考
    ref = completed_nodes[0]
    ref_md5 = ref["checksum_md5"]
    ref_sha256 = ref["checksum_sha256"]

    mismatched: list[str] = []
    missing: list[str] = []

    for n in completed_nodes:
        if n["checksum_md5"] and ref_md5 and n["checksum_md5"] != ref_md5:
            mismatched.append(n["node_id"])
        elif n["checksum_sha256"] and ref_sha256 and n["checksum_sha256"] != ref_sha256:
            mismatched.append(n["node_id"])
        elif not n["checksum_md5"] and not n["checksum_sha256"]:
            missing.append(n["node_id"])

    consistent = len(mismatched) == 0

    # 校验和不一致时标记任务失败
    if not consistent:
        conn.execute(
            "UPDATE tasks SET status = 'failed' WHERE id = ?",
            (task_id,),
        )
        conn.commit()
        add_event(
            task_id,
            config["node_id"],
            "checksum_mismatch",
            json.dumps(
                {
                    "reference_node": ref["node_id"],
                    "reference_md5": ref_md5,
                    "reference_sha256": ref_sha256,
                    "mismatched_nodes": mismatched,
                }
            ),
        )
        logger.error(
            "Task %s: checksum mismatch detected! Reference node=%s, mismatched=%s",
            task_id,
            ref["node_id"],
            mismatched,
        )

    return {
        "task_id": task_id,
        "consistent": consistent,
        "reference_md5": ref_md5,
        "reference_sha256": ref_sha256,
        "mismatched_nodes": mismatched,
        "missing_nodes": missing,
    }


def update_task_checksum(
    task_id: str,
    node_id: str,
    md5_checksum: str | None = None,
    sha256_checksum: str | None = None,
    db: sqlite3.Connection | None = None,
) -> None:
    """更新任务节点的校验和记录

    Args:
        task_id: 任务 ID
        node_id: 节点 ID
        md5_checksum: MD5 校验和（可选）
        sha256_checksum: SHA256 校验和（可选）
        db: 可选的数据库连接
    """
    import sqlite3

    conn = db or get_db()
    updates: list[str] = []
    params: list[Any] = []

    if md5_checksum is not None:
        updates.append("checksum_md5 = ?")
        params.append(md5_checksum)
    if sha256_checksum is not None:
        updates.append("checksum_sha256 = ?")
        params.append(sha256_checksum)

    if not updates:
        return

    sql = (
        "UPDATE task_nodes SET " + ", ".join(updates) + " WHERE task_id = ? AND node_id = ?"
    )
    params.extend([task_id, node_id])
    conn.execute(sql, params)
    conn.commit()


def update_task_master_checksum(
    task_id: str,
    md5_checksum: str | None = None,
    sha256_checksum: str | None = None,
    db: sqlite3.Connection | None = None,
) -> None:
    """更新任务主记录的校验和（通常由源节点设置）

    Args:
        task_id: 任务 ID
        md5_checksum: MD5 校验和（可选）
        sha256_checksum: SHA256 校验和（可选）
        db: 可选的数据库连接
    """
    import sqlite3

    conn = db or get_db()
    updates: list[str] = []
    params: list[Any] = []

    if md5_checksum is not None:
        updates.append("checksum_md5 = ?")
        params.append(md5_checksum)
    if sha256_checksum is not None:
        updates.append("checksum_sha256 = ?")
        params.append(sha256_checksum)

    if not updates:
        return

    sql = "UPDATE tasks SET " + ", ".join(updates) + " WHERE id = ?"
    params.append(task_id)
    conn.execute(sql, params)
    conn.commit()


async def broadcast_checksum(
    task_id: str,
    md5_checksum: str,
    sha256_checksum: str,
    local_path: str,
) -> None:
    """向其他节点广播本节点的校验和

    Args:
        task_id: 任务 ID
        md5_checksum: MD5 校验和
        sha256_checksum: SHA256 校验和
        local_path: 本地文件路径
    """
    from app.agent.p2p import P2PClient

    peers: list[dict[str, Any]] = config.get("peers", [])
    if not peers:
        return

    p2p = P2PClient(auth_token=str(config.get("auth_token", "")))
    payload: dict[str, Any] = {
        "task_id": task_id,
        "node_id": config["node_id"],
        "checksum_md5": md5_checksum,
        "checksum_sha256": sha256_checksum,
        "local_path": local_path,
    }

    for peer in peers:
        if peer.get("id") == config["node_id"]:
            continue
        try:
            url: str = f"http://{peer['host']}:{peer['port']}/api/checksum/report"
            result: dict[str, Any] = await p2p._request(
                "POST",
                url,
                payload,
                timeout=10,
                auth_token=p2p._auth(peer, p2p.auth_token),
            )
            if "error" in result:
                logger.warning(
                    "Checksum broadcast to %s failed: %s", peer.get("id"), result["error"]
                )
            else:
                logger.info("Checksum broadcast to %s success", peer.get("id"))
        except Exception as e:
            logger.warning("Checksum broadcast to %s error: %s", peer.get("id"), e)

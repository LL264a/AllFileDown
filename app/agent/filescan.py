"""
Allfiledown — Upload-Only 节点文件扫描

功能：
1. 启动时扫描 download_dir 下的历史文件
2. 识别已完成的任务目录结构
3. 自动注册到 task_nodes 表作为可用内部源
4. 通知其他节点这些文件可用

目录结构预期：
    download_dir/
        task_id_1/
            filename.ext
        task_id_2/
            filename.ext
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

from app.agent.role import can_upload, get_local_node_type
from app.config import config
from app.database import get_db

logger = logging.getLogger("afd.filescan")


def scan_existing_files() -> list[dict[str, Any]]:
    """扫描下载目录，返回发现的文件列表"""
    download_dir = Path(config["download_dir"])
    if not download_dir.exists():
        logger.warning("Download dir does not exist: %s", download_dir)
        return []

    discovered: list[dict[str, Any]] = []

    # 遍历 download_dir 下的所有子目录（每个子目录对应一个任务）
    for task_dir in download_dir.iterdir():
        if not task_dir.is_dir():
            continue

        task_id = task_dir.name

        # 检查这个 task_id 是否已经在数据库中
        db = get_db()
        existing = db.execute(
            "SELECT task_id FROM task_nodes WHERE task_id = ? AND node_id = ?",
            (task_id, config["node_id"]),
        ).fetchone()

        if existing:
            logger.debug("Task %s already registered, skipping", task_id)
            continue

        # 查找目录下的文件
        files = [f for f in task_dir.iterdir() if f.is_file()]
        if not files:
            logger.debug("Task %s has no files, skipping", task_id)
            continue

        # 取第一个文件作为主文件（通常每个任务只有一个文件）
        main_file = files[0]
        filename = main_file.name
        file_size = main_file.stat().st_size

        discovered.append({
            "task_id": task_id,
            "filename": filename,
            "local_path": str(main_file),
            "size": file_size,
        })
        logger.info("Discovered file: task=%s file=%s size=%d", task_id, filename, file_size)

    return discovered


def register_as_source(task_id: str, filename: str, local_path: str, file_size: int) -> bool:
    """将一个已发现的文件注册为内部源"""
    db = get_db()

    # 检查 tasks 表中是否已有此任务
    task = db.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()

    if not task:
        # 创建任务记录（没有原始 URL，标记为 imported）
        db.execute(
            "INSERT INTO tasks (id, url, filename, total_size, status) VALUES (?, ?, ?, ?, ?)",
            (task_id, f"internal://{task_id}", filename, file_size, "completed"),
        )
        logger.info("Created task record for imported file: %s", task_id)

    # 创建 task_nodes 记录（标记为 seeding，表示可作为源）
    db.execute(
        "INSERT OR REPLACE INTO task_nodes (task_id, node_id, status, local_path, progress) VALUES (?, ?, ?, ?, ?)",
        (task_id, config["node_id"], "seeding", local_path, 1.0),
    )
    db.commit()

    logger.info("Registered source: task=%s path=%s", task_id, local_path)
    return True


def build_internal_url(task_id: str, filename: str) -> str:
    """构建内部源 URL"""
    public_host = config.get("peer_host") or config.get("host", "localhost")
    if public_host in ("0.0.0.0", "127.0.0.1", "localhost"):
        public_host = "localhost"

    return f"http://{public_host}:{config.get('file_server_port', 18791)}/tasks/{task_id}/{filename}"


async def scan_and_register_all() -> dict[str, Any]:
    """扫描并注册所有发现的文件，返回统计"""
    if not can_upload():
        logger.info("File scan skipped: node %s is %s, cannot upload", config["node_id"], get_local_node_type())
        return {"scanned": 0, "registered": 0, "skipped": 0}

    logger.info("Starting file scan in: %s", config["download_dir"])
    discovered = scan_existing_files()

    registered = 0
    skipped = 0

    for item in discovered:
        try:
            success = register_as_source(
                item["task_id"],
                item["filename"],
                item["local_path"],
                item["size"],
            )
            if success:
                registered += 1
            else:
                skipped += 1
        except Exception as e:
            logger.warning("Failed to register %s: %s", item["task_id"], e)
            skipped += 1

    logger.info("File scan complete: discovered=%d registered=%d skipped=%d", len(discovered), registered, skipped)
    return {
        "scanned": len(discovered),
        "registered": registered,
        "skipped": skipped,
    }

"""
Allfiledown — 存储配额管理
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from app.config import config


def get_storage_info() -> dict[str, Any]:
    """获取存储信息"""
    download_dir = Path(config.get("download_dir", "/data/new/allfiledown"))
    
    # 磁盘信息
    stat = shutil.disk_usage(download_dir)
    
    total = stat.total
    used = stat.used
    free = stat.free
    percent = round(used / total * 100, 1) if total > 0 else 0
    
    # 任务目录大小
    task_size = 0
    task_count = 0
    
    if download_dir.exists():
        tasks_dir = download_dir / "tasks"
        if tasks_dir.exists():
            for item in tasks_dir.iterdir():
                if item.is_dir():
                    task_count += 1
                    task_size += get_dir_size(item)
    
    return {
        "disk": {
            "total": total,
            "used": used,
            "free": free,
            "percent": percent,
            "mount_point": str(download_dir)
        },
        "tasks": {
            "count": task_count,
            "size": task_size,
            "size_formatted": format_size(task_size)
        }
    }


def get_dir_size(path: Path) -> int:
    """递归计算目录大小"""
    total = 0
    try:
        for item in path.rglob("*"):
            if item.is_file():
                try:
                    total += item.stat().st_size
                except:
                    pass
    except:
        pass
    return total


def format_size(size: int) -> str:
    """格式化文件大小"""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def check_space(task_size: int = 0) -> dict[str, Any]:
    """检查空间是否足够"""
    download_dir = Path(config.get("download_dir", "/data/new/allfiledown"))
    stat = shutil.disk_usage(download_dir)
    
    # 预留空间（1GB）
    reserved = 1024 * 1024 * 1024
    available = stat.free - reserved
    
    sufficient = available >= task_size
    
    return {
        "sufficient": sufficient,
        "available": available,
        "requested": task_size,
        "reserved": reserved,
        "percent_remaining": round(available / stat.total * 100, 1) if stat.total > 0 else 0
    }


def get_task_sizes(limit: int = 20) -> list[dict[str, Any]]:
    """获取任务大小排行"""
    download_dir = Path(config.get("download_dir", "/data/new/allfiledown"))
    tasks_dir = download_dir / "tasks"
    
    if not tasks_dir.exists():
        return []
    
    task_sizes = []
    
    for task_dir in tasks_dir.iterdir():
        if task_dir.is_dir():
            size = get_dir_size(task_dir)
            task_sizes.append({
                "task_id": task_dir.name,
                "size": size,
                "size_formatted": format_size(size),
                "file_count": sum(1 for _ in task_dir.rglob("*") if _.is_file())
            })
    
    # 按大小排序
    task_sizes.sort(key=lambda x: x["size"], reverse=True)
    
    return task_sizes[:limit]


def cleanup_completed(
    delete_files: bool = False,
    older_than_days: int = 0,
    dry_run: bool = True
) -> dict[str, Any]:
    """清理已完成任务"""
    from app.database import get_db
    import time
    
    db = get_db()
    
    # 查找已完成任务
    query = "SELECT id, filename FROM tasks WHERE status IN ('completed', 'all_completed', 'seeding')"
    params = []
    
    if older_than_days > 0:
        cutoff = time.time() - (older_than_days * 86400)
        query += " AND updated_at < datetime(?, 'unixepoch')"
        params.append(int(cutoff))
    
    tasks = db.execute(query, params).fetchall()
    
    download_dir = Path(config.get("download_dir", "/data/new/allfiledown"))
    deleted_files = []
    freed_space = 0
    
    for task in tasks:
        task_dir = download_dir / "tasks" / task["id"]
        
        if task_dir.exists():
            size = get_dir_size(task_dir)
            
            if not dry_run and delete_files:
                shutil.rmtree(task_dir)
            
            deleted_files.append({
                "task_id": task["id"],
                "filename": task["filename"],
                "size": size,
                "size_formatted": format_size(size)
            })
            freed_space += size
    
    return {
        "dry_run": dry_run,
        "tasks_found": len(tasks),
        "tasks_to_delete": len(deleted_files),
        "freed_space": freed_space,
        "freed_space_formatted": format_size(freed_space),
        "deleted": deleted_files
    }


def set_disk_alert_threshold(percent: int = 90) -> dict[str, Any]:
    """设置磁盘告警阈值"""
    from app.config import config, save_config
    
    config["disk_alert_threshold"] = percent
    save_config(config)
    
    return {"status": "ok", "threshold": percent}


def get_disk_alert() -> dict[str, Any]:
    """检查磁盘告警"""
    info = get_storage_info()
    threshold = config.get("disk_alert_threshold", 90)
    percent = info["disk"]["percent"]
    
    return {
        "alert": percent >= threshold,
        "percent": percent,
        "threshold": threshold,
        "message": f"磁盘使用率 {percent}%{' ⚠️ 超过阈值' if percent >= threshold else ''}"
    }
"""
Allfiledown — 日志管理
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import config

LOG_DIR = Path(config.get("download_dir", "/data/new/allfiledown")).parent / "logs"


def get_log_files() -> list[dict[str, Any]]:
    """获取日志文件列表"""
    if not LOG_DIR.exists():
        return []
    
    files = []
    for f in LOG_DIR.iterdir():
        if f.is_file() and f.suffix in [".log", ".txt"]:
            stat = f.stat()
            files.append({
                "name": f.name,
                "path": str(f),
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
            })
    
    return sorted(files, key=lambda x: x["modified"], reverse=True)


def read_log(
    filename: str,
    lines: int = 100,
    level: str | None = None,
    search: str | None = None,
) -> dict[str, Any]:
    """读取日志内容"""
    log_path = LOG_DIR / filename
    
    if not log_path.exists():
        return {"error": "File not found", "filename": filename}
    
    # 读取最后 N 行
    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            all_lines = f.readlines()
        
        # 过滤
        filtered = all_lines
        if level:
            level_pattern = re.compile(rf"\b{level.upper()}\b", re.IGNORECASE)
            filtered = [l for l in filtered if level_pattern.search(l)]
        
        if search:
            search_pattern = re.compile(search, re.IGNORECASE)
            filtered = [l for l in filtered if search_pattern.search(l)]
        
        # 取最后 N 行
        tail = filtered[-lines:] if len(filtered) > lines else filtered
        
        return {
            "filename": filename,
            "total_lines": len(filtered),
            "returned_lines": len(tail),
            "lines": [l.rstrip() for l in tail]
        }
    except Exception as e:
        return {"error": str(e), "filename": filename}


def get_log_levels(filename: str) -> list[str]:
    """获取日志中包含的级别"""
    log_path = LOG_DIR / filename
    
    if not log_path.exists():
        return []
    
    levels = set()
    level_pattern = re.compile(r"\b(DEBUG|INFO|WARN|WARNING|ERROR|CRITICAL|FATAL)\b")
    
    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                match = level_pattern.search(line)
                if match:
                    levels.add(match.group(1).upper())
    except Exception:
        pass
    
    return sorted(list(levels))


def get_audit_logs(
    limit: int = 100,
    event_type: str | None = None,
    task_id: str | None = None,
) -> list[dict[str, Any]]:
    """获取审计日志（从数据库 events 表）"""
    from app.database import get_db
    db = get_db()
    
    query = "SELECT * FROM events"
    params = []
    conditions = []
    
    if event_type:
        conditions.append("event_type = ?")
        params.append(event_type)
    
    if task_id:
        conditions.append("task_id = ?")
        params.append(task_id)
    
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    
    query += f" ORDER BY created_at DESC LIMIT {limit}"
    
    rows = db.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def clear_old_logs(days: int = 7) -> dict[str, Any]:
    """清理旧日志文件"""
    if not LOG_DIR.exists():
        return {"deleted": 0, "freed": 0}
    
    import time
    cutoff = time.time() - (days * 24 * 3600)
    
    deleted = 0
    freed = 0
    
    for f in LOG_DIR.iterdir():
        if f.is_file():
            if f.stat().st_mtime < cutoff:
                size = f.stat().st_size
                f.unlink()
                deleted += 1
                freed += size
    
    return {"deleted": deleted, "freed": freed, "days": days}
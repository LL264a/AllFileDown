"""
Allfiledown — BT 做种管理
"""

from __future__ import annotations

from typing import Any

from app.database import get_db


def get_seeding_tasks() -> list[dict[str, Any]]:
    """获取正在做种的任务"""
    db = get_db()
    
    rows = db.execute("""
        SELECT t.id, t.filename, t.total_size, tn.uploaded_size, tn.progress
        FROM tasks t
        JOIN task_nodes tn ON t.id = tn.task_id
        WHERE tn.status = 'seeding'
        ORDER BY tn.progress DESC
    """).fetchall()
    
    return [dict(r) for r in rows]


def get_seed_ratio(task_id: str) -> dict[str, Any]:
    """获取任务分享率"""
    db = get_db()
    
    row = db.execute("""
        SELECT t.total_size, tn.uploaded_size
        FROM tasks t
        JOIN task_nodes tn ON t.id = tn.task_id
        WHERE t.id = ?
    """, (task_id,)).fetchone()
    
    if not row:
        return {"error": "Task not found"}
    
    downloaded = row.get("total_size") or 0
    uploaded = row.get("uploaded_size") or 0
    
    ratio = round(uploaded / downloaded, 2) if downloaded > 0 else 0.0
    
    return {
        "task_id": task_id,
        "downloaded": downloaded,
        "uploaded": uploaded,
        "ratio": ratio
    }


def get_seed_stats() -> dict[str, Any]:
    """获取做种统计"""
    db = get_db()
    
    # 总做种数
    total = db.execute(
        "SELECT COUNT(*) as c FROM task_nodes WHERE status = 'seeding'"
    ).fetchone()
    total_seeding = total["c"] if total else 0
    
    # 总上传量
    result = db.execute(
        "SELECT SUM(uploaded_size) as total FROM task_nodes WHERE status = 'seeding'"
    ).fetchone()
    total_uploaded = result["total"] if result and result["total"] else 0
    
    # 总下载量
    result2 = db.execute("""
        SELECT SUM(t.total_size) as total 
        FROM tasks t 
        JOIN task_nodes tn ON t.id = tn.task_id 
        WHERE tn.status = 'seeding'
    """).fetchone()
    total_downloaded = result2["total"] if result2 and result2["total"] else 0
    
    return {
        "total_seeding": total_seeding,
        "total_uploaded": total_uploaded,
        "total_downloaded": total_downloaded,
        "overall_ratio": round(total_uploaded / total_downloaded, 2) if total_downloaded > 0 else 0.0
    }


def stop_seeding(task_id: str) -> dict[str, Any]:
    """停止做种（保留文件）"""
    db = get_db()
    db.execute(
        "UPDATE task_nodes SET status = 'completed' WHERE task_id = ? AND status = 'seeding'",
        (task_id,)
    )
    db.commit()
    return {"status": "ok", "task_id": task_id}


def is_torrent_task(url: str) -> bool:
    """判断是否为 BT/磁力任务"""
    return url.startswith("magnet:") or url.endswith(".torrent")
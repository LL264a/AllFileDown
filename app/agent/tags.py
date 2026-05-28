"""
Allfiledown — 任务标签/分类
"""

from __future__ import annotations

from typing import Any

from app.database import get_db


def create_tag(name: str, color: str = "#6b7280") -> dict[str, Any]:
    """创建标签"""
    import uuid
    db = get_db()
    
    tag_id = str(uuid.uuid4())[:8]
    
    try:
        db.execute(
            "INSERT INTO tags (id, name, color) VALUES (?, ?, ?)",
            (tag_id, name, color)
        )
        db.commit()
        return {"status": "ok", "id": tag_id, "name": name, "color": color}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def get_tags() -> list[dict[str, Any]]:
    """获取所有标签"""
    db = get_db()
    rows = db.execute("SELECT * FROM tags ORDER BY name").fetchall()
    return [dict(r) for r in rows]


def delete_tag(tag_id: str) -> dict[str, Any]:
    """删除标签"""
    db = get_db()
    db.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
    db.execute("DELETE FROM task_tags WHERE tag_id = ?", (tag_id,))
    db.commit()
    return {"status": "ok"}


def add_task_tag(task_id: str, tag_id: str) -> dict[str, Any]:
    """给任务添加标签"""
    db = get_db()
    
    try:
        db.execute(
            "INSERT OR IGNORE INTO task_tags (task_id, tag_id) VALUES (?, ?)",
            (task_id, tag_id)
        )
        db.commit()
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def remove_task_tag(task_id: str, tag_id: str) -> dict[str, Any]:
    """移除任务标签"""
    db = get_db()
    db.execute(
        "DELETE FROM task_tags WHERE task_id = ? AND tag_id = ?",
        (task_id, tag_id)
    )
    db.commit()
    return {"status": "ok"}


def get_task_tags(task_id: str) -> list[dict[str, Any]]:
    """获取任务的所有标签"""
    db = get_db()
    rows = db.execute("""
        SELECT t.*
        FROM tags t
        JOIN task_tags tt ON t.id = tt.tag_id
        WHERE tt.task_id = ?
    """, (task_id,)).fetchall()
    return [dict(r) for r in rows]


def get_tasks_by_tag(tag_id: str) -> list[dict[str, Any]]:
    """获取指定标签的所有任务"""
    db = get_db()
    rows = db.execute("""
        SELECT t.*
        FROM tasks t
        JOIN task_tags tt ON t.id = tt.task_id
        WHERE tt.tag_id = ?
        ORDER BY t.created_at DESC
    """, (tag_id,)).fetchall()
    return [dict(r) for r in rows]


def auto_tag_task(task_id: str, url: str) -> list[str]:
    """根据 URL 自动打标签"""
    db = get_db()
    added_tags = []
    
    # 预定义规则
    rules = [
        ("video", ["mp4", "mkv", "avi", "mov", "wmv", "flv", "webm", "magnet:", ".torrent"]),
        ("audio", ["mp3", "flac", "wav", "aac", "ogg", "m4a"]),
        ("image", ["jpg", "jpeg", "png", "gif", "bmp", "webp", "svg"]),
        ("archive", ["zip", "rar", "7z", "tar", "gz", "bz2"]),
        ("document", ["pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt"]),
        ("software", ["exe", "msi", "deb", "rpm", "apk", "dmg"]),
    ]
    
    url_lower = url.lower()
    
    for tag_name, patterns in rules:
        for pattern in patterns:
            if pattern in url_lower:
                # 查找或创建标签
                tag = db.execute("SELECT id FROM tags WHERE name = ?", (tag_name,)).fetchone()
                
                if not tag:
                    # 自动创建
                    import uuid
                    tag_id = str(uuid.uuid4())[:8]
                    color = {
                        "video": "#ef4444",
                        "audio": "#8b5cf6",
                        "image": "#10b981",
                        "archive": "#f59e0b",
                        "document": "#3b82f6",
                        "software": "#6366f1"
                    }.get(tag_name, "#6b7280")
                    
                    db.execute(
                        "INSERT INTO tags (id, name, color) VALUES (?, ?, ?)",
                        (tag_id, tag_name, color)
                    )
                    tag = {"id": tag_id}
                
                # 添加关联
                try:
                    db.execute(
                        "INSERT OR IGNORE INTO task_tags (task_id, tag_id) VALUES (?, ?)",
                        (task_id, tag["id"])
                    )
                    added_tags.append(tag_name)
                except Exception:
                    pass
                
                break
    
    db.commit()
    return added_tags


def migrate_tags_table():
    """创建标签相关表"""
    db = get_db()
    
    db.executescript("""
        CREATE TABLE IF NOT EXISTS tags (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            color TEXT DEFAULT '#6b7280',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS task_tags (
            task_id TEXT NOT NULL,
            tag_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (task_id, tag_id),
            FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
            FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
        );
    """)
    db.commit()


# 初始化表
migrate_tags_table()
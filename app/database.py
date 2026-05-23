"""
Allfiledown — SQLite 数据库
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

DB_PATH: Path = Path(__file__).resolve().parent.parent / "data" / "allfiledown.db"

_local: threading.local = threading.local()


def get_db() -> sqlite3.Connection:
    """获取当前线程的数据库连接（线程局部单例）"""
    if not hasattr(_local, "conn") or _local.conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _local.conn = sqlite3.connect(str(DB_PATH))
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn


def _migrate(conn: sqlite3.Connection) -> None:
    """执行增量 schema 迁移"""
    migrations = [
        ("ALTER TABLE nodes ADD COLUMN save_path TEXT DEFAULT ''", "duplicate column"),
        ("ALTER TABLE task_nodes ADD COLUMN download_speed INTEGER DEFAULT 0", "duplicate column"),
    ]
    for sql, ignore_msg in migrations:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError as e:
            if ignore_msg not in str(e).lower():
                raise


def init_db() -> sqlite3.Connection:
    """初始化数据库表结构并执行迁移"""
    conn = get_db()

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS nodes (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            host TEXT NOT NULL,
            port INTEGER NOT NULL DEFAULT 18790,
            node_type TEXT NOT NULL DEFAULT 'full',
            auth_token TEXT DEFAULT '',
            status TEXT DEFAULT 'offline',
            last_seen TIMESTAMP,
            save_path TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            url TEXT NOT NULL,
            filename TEXT,
            total_size INTEGER DEFAULT 0,
            downloaded_size INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS task_nodes (
            task_id TEXT NOT NULL,
            node_id TEXT NOT NULL,
            progress REAL DEFAULT 0.0,
            download_speed INTEGER DEFAULT 0,
            status TEXT DEFAULT 'waiting',
            local_path TEXT,
            internal_url TEXT,
            gid TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (task_id, node_id)
        );

        CREATE TABLE IF NOT EXISTS passkey_credentials (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL DEFAULT 'admin',
            credential_id BLOB NOT NULL,
            public_key BLOB NOT NULL,
            sign_count INTEGER DEFAULT 0,
            name TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT,
            node_id TEXT,
            event_type TEXT NOT NULL,
            payload TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    _migrate(conn)
    return conn


def add_event(
    task_id: str,
    node_id: str,
    event_type: str,
    payload: str | None = None,
    db: sqlite3.Connection | None = None,
) -> None:
    """记录一条事件到 events 表"""
    conn = db or get_db()
    conn.execute(
        "INSERT INTO events (task_id, node_id, event_type, payload) VALUES (?, ?, ?, ?)",
        (task_id, node_id, event_type, payload),
    )
    conn.commit()


def get_events_since(since_id: int, db: sqlite3.Connection | None = None) -> list[sqlite3.Row]:
    """获取指定 ID 之后的所有事件"""
    conn = db or get_db()
    return list(
        conn.execute(
            "SELECT * FROM events WHERE id > ? ORDER BY id",
            (since_id,),
        ).fetchall()
    )

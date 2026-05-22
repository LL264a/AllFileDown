"""
Allfiledown — SQLite 数据库
"""
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "allfiledown.db"

_local = threading.local()


def get_db():
    if not hasattr(_local, "conn") or _local.conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _local.conn = sqlite3.connect(str(DB_PATH))
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn


def init_db():
    conn = get_db()
    # 迁移：确保 save_path 列存在
    try:
        conn.execute("ALTER TABLE nodes ADD COLUMN save_path TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # 列已存在
    # 迁移：确保 download_speed 列存在
    try:
        conn.execute("ALTER TABLE task_nodes ADD COLUMN download_speed INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # 列已存在

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


def add_event(task_id, node_id, event_type, payload=None):
    conn = get_db()
    conn.execute(
        "INSERT INTO events (task_id, node_id, event_type, payload) VALUES (?, ?, ?, ?)",
        (task_id, node_id, event_type, payload)
    )
    conn.commit()


def get_events_since(since_id):
    conn = get_db()
    return conn.execute(
        "SELECT * FROM events WHERE id > ? ORDER BY id",
        (since_id,)
    ).fetchall()

"""
Allfiledown — 数据库单元测试
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def _temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """用临时数据库路径替换默认路径"""
    import app.database

    new_path = tmp_path / "test.db"
    monkeypatch.setattr(app.database, "DB_PATH", new_path)


class TestDatabase:
    """数据库基本操作测试"""

    def test_init_db_creates_tables(self, _temp_db: None) -> None:
        """初始化数据库应创建必需表"""
        from app.database import get_db, init_db

        init_db()
        db = get_db()
        tables: list[Any] = db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        table_names: list[str] = [row["name"] for row in tables]
        assert "nodes" in table_names
        assert "tasks" in table_names
        assert "task_nodes" in table_names
        assert "events" in table_names

    def test_insert_node(self, _temp_db: None) -> None:
        """插入节点"""
        from app.database import get_db, init_db

        init_db()
        db = get_db()
        db.execute(
            "INSERT INTO nodes (id, name, host, port, node_type) VALUES (?, ?, ?, ?, ?)",
            ("node1", "Node 1", "192.168.1.1", 18790, "full"),
        )
        db.commit()
        row = db.execute("SELECT * FROM nodes WHERE id = ?", ("node1",)).fetchone()
        assert row is not None
        assert row["name"] == "Node 1"

    def test_insert_task(self, _temp_db: None) -> None:
        """插入任务"""
        from app.database import get_db, init_db

        init_db()
        db = get_db()
        db.execute(
            "INSERT INTO tasks (id, url, filename, status) VALUES (?, ?, ?, ?)",
            ("task1", "http://example.com/file.zip", "file.zip", "downloading"),
        )
        db.commit()
        row = db.execute("SELECT * FROM tasks WHERE id = ?", ("task1",)).fetchone()
        assert row is not None
        assert row["status"] == "downloading"

    def test_task_node_relation(self, _temp_db: None) -> None:
        """任务-节点关联"""
        from app.database import get_db, init_db

        init_db()
        db = get_db()
        db.execute(
            "INSERT INTO tasks (id, url, status) VALUES (?, ?, ?)", ("t1", "http://example.com/f.zip", "downloading")
        )
        db.execute(
            "INSERT INTO nodes (id, name, host, port, node_type) VALUES (?, ?, ?, ?, ?)",
            ("n1", "N1", "10.0.0.1", 18790, "full"),
        )
        db.execute("INSERT INTO task_nodes (task_id, node_id, status) VALUES (?, ?, ?)", ("t1", "n1", "downloading"))
        db.commit()
        rows = db.execute(
            "SELECT tn.*, t.url FROM task_nodes tn JOIN tasks t ON tn.task_id = t.id WHERE tn.task_id = ?", ("t1",)
        ).fetchall()
        assert len(rows) == 1

    def test_add_and_query_event(self, _temp_db: None) -> None:
        """事件 CRUD"""
        from app.database import add_event, get_events_since, init_db

        init_db()
        add_event("t1", "n1", "started", '{"url":"a"}')
        add_event("t1", "n1", "completed", "")

        events = get_events_since(0)
        assert len(events) >= 2
        event_types = [e["event_type"] for e in events]
        assert "started" in event_types
        assert "completed" in event_types

        last_id: int = events[-1]["id"]
        add_event("t2", "n1", "test", "")
        new_events = get_events_since(last_id)
        assert len(new_events) == 1
        assert new_events[0]["event_type"] == "test"


class TestDatabaseEdgeCases:
    """边界测试"""

    def test_duplicate_task_id_raises(self, _temp_db: None) -> None:
        """重复任务 ID 应异常"""
        from app.database import get_db, init_db

        init_db()
        db = get_db()
        db.execute("INSERT INTO tasks (id, url, status) VALUES (?, ?, ?)", ("dup", "http://a.com", "pending"))
        db.commit()
        with pytest.raises(Exception):  # noqa: B017
            db.execute("INSERT INTO tasks (id, url, status) VALUES (?, ?, ?)", ("dup", "http://b.com", "pending"))
            db.commit()

    def test_nonexistent_task(self, _temp_db: None) -> None:
        """查询不存在的任务"""
        from app.database import get_db, init_db

        init_db()
        db = get_db()
        row = db.execute("SELECT * FROM tasks WHERE id = ?", ("nonexist",)).fetchone()
        assert row is None

    def test_event_without_task(self, _temp_db: None) -> None:
        """事件可以不关联已有任务"""
        from app.database import add_event, get_events_since, init_db

        init_db()
        add_event("ghost", "n1", "test", "")
        events = get_events_since(0)
        assert any(e["task_id"] == "ghost" for e in events)

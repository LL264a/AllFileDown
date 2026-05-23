"""
Allfiledown — 配置文件单元测试
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

# 模拟 DEFAULT_CONFIG 用于对比
DEFAULT_CONFIG: dict[str, Any] = {
    "node_id": "default-node",
    "node_name": "Default",
    "host": "0.0.0.0",
    "port": 18790,
    "download_dir": "/data/allfiledown/downloads",
    "auth_token": "",
    "aria2": {"host": "127.0.0.1", "port": 6800, "secret": ""},
    "file_server_port": 18791,
    "peers": [],
}


@pytest.fixture
def _mock_config_path(tmp_path: Path) -> Path:
    """创建临时配置文件路径"""
    path = tmp_path / "config.json"
    # 清理 app.config 的模块级缓存
    return path


class TestConfig:
    """配置管理测试"""

    def test_default_structure(self) -> None:
        """验证默认配置结构"""
        c: dict[str, Any] = DEFAULT_CONFIG
        assert "node_id" in c
        assert "node_name" in c
        assert "host" in c
        assert "port" in c
        assert "download_dir" in c
        assert "auth_token" in c
        assert "aria2" in c
        assert "peers" in c
        assert isinstance(c["aria2"], dict)
        assert "host" in c["aria2"]
        assert "port" in c["aria2"]
        assert "secret" in c["aria2"]

    def test_load_and_save_roundtrip(self, tmp_path: Path) -> None:
        """保存并重新加载配置应一致"""
        import app.config

        config_path = tmp_path / "config.json"
        # 用 monkeypatch 改模块变量
        orig_path = app.config.CONFIG_PATH
        app.config.CONFIG_PATH = config_path

        try:
            cfg: dict[str, Any] = {
                "node_id": "test-node",
                "node_name": "Test",
                "host": "127.0.0.1",
                "port": 18790,
                "download_dir": str(tmp_path / "downloads"),
                "auth_token": "test-token",
                "aria2": {"host": "127.0.0.1", "port": 6800, "secret": "test"},
                "file_server_port": 18791,
                "peers": [],
            }
            app.config.save_config(cfg)
            loaded: dict[str, Any] = app.config.load_config()
            assert loaded == cfg
            assert loaded["node_id"] == "test-node"
        finally:
            app.config.CONFIG_PATH = orig_path

    def test_save_creates_parent_dir(self, tmp_path: Path) -> None:
        """保存配置应自动创建父目录"""
        import app.config

        config_path = tmp_path / "sub" / "deep" / "config.json"
        orig_path = app.config.CONFIG_PATH
        app.config.CONFIG_PATH = config_path

        try:
            app.config.save_config(DEFAULT_CONFIG)
            assert config_path.exists()
            loaded: dict[str, Any] = app.config.load_config()
            assert loaded["node_id"] == DEFAULT_CONFIG["node_id"]
        finally:
            app.config.CONFIG_PATH = orig_path

    def test_load_nonexistent_returns_default(self, tmp_path: Path) -> None:
        """不存在文件应返回默认"""
        import app.config

        config_path = tmp_path / "nope" / "config.json"
        orig_path = app.config.CONFIG_PATH
        app.config.CONFIG_PATH = config_path

        try:
            result: dict[str, Any] = app.config.load_config()
            assert isinstance(result, dict)
            assert "node_id" in result
        finally:
            app.config.CONFIG_PATH = orig_path

    def test_module_config_is_dict(self) -> None:
        """模块级 config 变量应为 dict"""
        from app.config import config

        assert isinstance(config, dict)
        assert "node_id" in config


class TestConfigEdgeCases:
    """异常场景测试"""

    def test_corrupted_json_returns_default(self, tmp_path: Path) -> None:
        """损坏 JSON 应返回默认"""
        import app.config

        config_path = tmp_path / "bad.json"
        config_path.write_text("{invalid json!!!}")

        orig_path = app.config.CONFIG_PATH
        app.config.CONFIG_PATH = config_path

        try:
            result: dict[str, Any] = app.config.load_config()
            assert isinstance(result, dict)
            assert "node_id" in result
        finally:
            app.config.CONFIG_PATH = orig_path

    def test_empty_file_returns_default(self, tmp_path: Path) -> None:
        """空文件应返回默认"""
        import app.config

        config_path = tmp_path / "empty.json"
        config_path.touch()

        orig_path = app.config.CONFIG_PATH
        app.config.CONFIG_PATH = config_path

        try:
            result = app.config.load_config()
            assert isinstance(result, dict)
        finally:
            app.config.CONFIG_PATH = orig_path

    def test_save_writes_content(self, tmp_path: Path) -> None:
        """保存后文件内容应包含预期字段"""
        import app.config

        config_path = tmp_path / "config.json"
        orig_path = app.config.CONFIG_PATH
        app.config.CONFIG_PATH = config_path

        try:
            app.config.save_config(DEFAULT_CONFIG)
            content: str = config_path.read_text(encoding="utf-8")
            assert '"node_id"' in content
            assert '"download_dir"' in content
        finally:
            app.config.CONFIG_PATH = orig_path

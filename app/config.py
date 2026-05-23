"""
Allfiledown — 配置管理
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

BASE_DIR: Path = Path(__file__).resolve().parent.parent
CONFIG_PATH: Path = BASE_DIR / "config.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "web_password": "",  # 网页登录密码，空=无密码
    "web_username": "admin",  # 网页登录用户名
    "node_id": "sk",
    "node_name": "S.K. (本机)",
    "host": "0.0.0.0",
    "port": 18790,
    "bind_host": None,
    "download_dir": "/data/new/allfiledown/tasks",
    "file_server_port": 18791,
    "aria2": {
        "host": "127.0.0.1",
        "port": 1068,
        "secret": "Lr145ar",
        "tls": True,
    },
    "auth_token": "allfiledown-default-token",
    "api_key": "",  # API 密钥（密码管理器、header 认证）
    "peers": [],
}


def load_config() -> dict[str, Any]:
    """加载配置文件，不存在或损坏时返回默认配置"""
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError, OSError):
            return dict(DEFAULT_CONFIG)
    return dict(DEFAULT_CONFIG)


def save_config(cfg: dict[str, Any]) -> None:
    """保存配置到文件"""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


config: dict[str, Any] = load_config()

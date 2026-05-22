"""
Allfiledown — 配置管理
"""
import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.json"

DEFAULT_CONFIG = {
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
        "tls": True
    },
    "auth_token": "allfiledown-default-token",
    "peers": []
}


def load_config():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
        return cfg
    return dict(DEFAULT_CONFIG)


def save_config(cfg):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


config = load_config()

"""
Allfiledown — FastAPI 应用
"""

from __future__ import annotations

import asyncio
import logging
import logging.handlers
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import router as api_router
from app.config import config
from app.database import init_db
from app.web.routes import router as web_router

# === 日志初始化 ===
_log_dir = Path(config.get("download_dir", "/data/new/allfiledown"))
_log_file = str((_log_dir.parent / "logs" / "afd.log").resolve())
Path(_log_file).parent.mkdir(parents=True, exist_ok=True)
_log_handler = logging.handlers.RotatingFileHandler(
    _log_file,
    maxBytes=10 * 1024 * 1024,
    backupCount=3,
    encoding="utf-8",
)
_log_handler.setFormatter(
    logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
)

# 清理默认 handler 避免控制台重复日志
for h in list(logging.getLogger().handlers):
    logging.getLogger().removeHandler(h)

# Root logger
_log_root = logging.getLogger()
_log_root.setLevel(logging.INFO)
_log_root.addHandler(_log_handler)

# Uvicorn loggers
for name in ("uvicorn", "uvicorn.access"):
    lg = logging.getLogger(name)
    lg.addHandler(_log_handler)

# AFD logger
logger = logging.getLogger("afd")
logger.info("=" * 50)
logger.info("🚀 AFD starting...")

# === FastAPI 应用 ===
app: FastAPI = FastAPI(title="Allfiledown", version="0.1.0")

# 静态文件
_static_dir = Path(__file__).parent / "web" / "static"
_static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

# 注册路由
app.include_router(web_router)
app.include_router(api_router)

# 下载目录
_download_dir = Path(config["download_dir"])
_download_dir.mkdir(parents=True, exist_ok=True)


@app.on_event("startup")
async def startup() -> None:
    """应用启动时的初始化"""
    init_db()

    # 启动文件服务器（内部源文件下载，端口 18791）
    try:
        from aiohttp import web

        from app.agent.fileserver import create_file_server

        fs_app: web.Application = create_file_server(config["download_dir"])
        fs_app["node_id"] = config.get("node_id", "sk")
        fs_app["file_token"] = config.get("file_token", "")

        async def _run_fileserver() -> None:
            runner = web.AppRunner(fs_app)
            await runner.setup()
            site = web.TCPSite(runner, "0.0.0.0", 18791)
            await site.start()
            logger.info("File server running on :18791")
            while True:
                await asyncio.sleep(3600)

        asyncio.create_task(_run_fileserver())
        logger.info("File server started on port 18791")
    except Exception as e:
        logger.warning("File server startup failed: %s", e)

    # 启动任务编排器
    import app.agent.orchestrator as orch_mod
    from app.agent.orchestrator import Orchestrator

    orch: Orchestrator = Orchestrator()
    await orch.start()
    orch_mod.orchestrator = orch
    logger.info("Orchestrator started")


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "node": config["node_id"]}

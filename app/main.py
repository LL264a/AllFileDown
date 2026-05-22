"""
Allfiledown — FastAPI 应用
"""
import asyncio
import logging
import logging.handlers
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.database import init_db
from app.config import config
from app.web.routes import router as web_router
from app.api.routes import router as api_router

# === 日志 ===
log_dir = Path(config.get("download_dir", "/data/new/allfiledown") )
log_file = str((log_dir.parent / "logs" / "afd.log").resolve())
Path(log_file).parent.mkdir(parents=True, exist_ok=True)
log_handler = logging.handlers.RotatingFileHandler(
    log_file, maxBytes=10*1024*1024, backupCount=3, encoding="utf-8"
)
log_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
))

# Remove default handlers to avoid duplicate console logs
for h in logging.getLogger().handlers:
    logging.getLogger().removeHandler(h)

# Root logger
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(log_handler)

# Uvicorn loggers
uvicorn_logger = logging.getLogger("uvicorn")
uvicorn_logger.addHandler(log_handler)
uvicorn_access = logging.getLogger("uvicorn.access")
uvicorn_access.addHandler(log_handler)

# AFD-specific loggers
logger = logging.getLogger("afd")

logging.info("=" * 50)
logging.info("🚀 AFD starting...")

app = FastAPI(title="Allfiledown", version="0.1.0")

# 静态文件
static_dir = Path(__file__).parent / "web" / "static"
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# 注册路由
app.include_router(web_router)
app.include_router(api_router)

# 数据目录
download_dir = Path(config["download_dir"])
download_dir.mkdir(parents=True, exist_ok=True)


@app.on_event("startup")
async def startup():
    init_db()
    from app.agent.orchestrator import Orchestrator
    import app.agent.orchestrator as orch_mod
    orch = Orchestrator()
    await orch.start()
    orch_mod.orchestrator = orch


@app.get("/health")
async def health():
    return {"status": "ok", "node": config["node_id"]}

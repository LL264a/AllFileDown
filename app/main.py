"""
Allfiledown — FastAPI 应用
"""
import asyncio
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.database import init_db
from app.config import config
from app.web.routes import router as web_router
from app.api.routes import router as api_router

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

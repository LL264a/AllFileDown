"""
Allfiledown — 入口
"""

from __future__ import annotations

import uvicorn

from app.config import config

if __name__ == "__main__":
    bind_host: str = str(config.get("bind_host") or config.get("host", "0.0.0.0"))
    uvicorn.run(
        "app.main:app",
        host=bind_host,
        port=int(config.get("port", 18790)),
        reload=False,
        log_level="info",
    )

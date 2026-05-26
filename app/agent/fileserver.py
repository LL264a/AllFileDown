"""
Allfiledown — HTTP 文件共享服务（内部源）
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aiohttp import web

from app.security import PathSecurityError, safe_join


def create_file_server(
    download_dir: str,
    routes: list[Any] | None = None,  # noqa: ARG001
    file_token: str | None = None,
    node_id: str | None = None,
) -> web.Application:
    """创建文件共享 HTTP 服务

    Args:
        download_dir: 下载根目录
        routes: 额外路由（保留参数）
        file_token: 文件访问 token（可选）
        node_id: 当前节点 ID（可选）
    """
    app: web.Application = web.Application()

    # 注入配置
    if file_token:
        app["file_token"] = file_token
    if node_id:
        app["node_id"] = node_id

    async def serve_file(request: web.Request) -> web.FileResponse | web.Response:
        """提供文件下载"""
        task_id: str = request.match_info.get("task_id", "")
        filename: str = request.match_info.get("filename", "")
        token: str = request.query.get("token", "")

        # 简单的 token 验证（防止公网随便拉）
        expected_token: str = request.app.get("file_token", "")
        if expected_token and token != expected_token:
            return web.Response(status=403, text="Forbidden: invalid token")

        try:
            file_path: Path = safe_join(download_dir, task_id, filename)
        except PathSecurityError:
            return web.Response(status=400, text="Invalid path")
        if not file_path.exists():
            return web.Response(status=404, text="File not found")
        if not file_path.is_file():
            return web.Response(status=400, text="Not a file")

        return web.FileResponse(file_path)

    async def list_files(request: web.Request) -> web.Response:
        """列出任务目录下的文件"""
        task_id: str = request.match_info.get("task_id", "")
        try:
            task_dir: Path = safe_join(download_dir, task_id)
        except PathSecurityError:
            return web.Response(status=400, text="Invalid path")
        if not task_dir.exists():
            return web.json_response({"files": []})
        files: list[dict[str, Any]] = []
        for f in task_dir.iterdir():
            if f.is_file():
                files.append(
                    {
                        "name": f.name,
                        "size": f.stat().st_size,
                    }
                )
        return web.json_response({"files": files})

    async def health(request: web.Request) -> web.Response:
        """健康检查"""
        return web.json_response(
            {
                "status": "ok",
                "node": request.app.get("node_id", "unknown"),
            }
        )

    app.router.add_get("/tasks/{task_id}/files", list_files)
    app.router.add_get("/tasks/{task_id}/{filename}", serve_file)
    app.router.add_get("/health", health)

    return app

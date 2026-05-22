"""
Allfiledown — HTTP 文件共享服务（内部源）
"""
import os
from pathlib import Path

from aiohttp import web


def create_file_server(download_dir, routes=None):
    """创建文件共享 HTTP 服务"""
    app = web.Application()

    # 文件下载路由
    async def serve_file(request):
        task_id = request.match_info.get("task_id")
        filename = request.match_info.get("filename")
        token = request.query.get("token", "")

        # 简单的 token 验证（防止公网随便拉）
        expected_token = request.app.get("file_token", "")
        if expected_token and token != expected_token:
            return web.Response(status=403, text="Forbidden: invalid token")

        file_path = Path(download_dir) / task_id / filename
        if not file_path.exists():
            return web.Response(status=404, text="File not found")
        if not file_path.is_file():
            return web.Response(status=400, text="Not a file")

        return web.FileResponse(file_path)

    # 文件列表路由
    async def list_files(request):
        task_id = request.match_info.get("task_id")
        task_dir = Path(download_dir) / task_id
        if not task_dir.exists():
            return web.json_response({"files": []})
        files = []
        for f in task_dir.iterdir():
            if f.is_file():
                files.append({
                    "name": f.name,
                    "size": f.stat().st_size
                })
        return web.json_response({"files": files})

    # 节点健康检查
    async def health(request):
        return web.json_response({"status": "ok", "node": request.app.get("node_id", "unknown")})

    app.router.add_get("/tasks/{task_id}/files", list_files)
    app.router.add_get("/tasks/{task_id}/{filename}", serve_file)
    app.router.add_get("/health", health)

    return app

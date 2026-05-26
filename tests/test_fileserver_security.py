from __future__ import annotations

from pathlib import Path

import pytest
from aiohttp.test_utils import make_mocked_request


@pytest.mark.asyncio
async def test_fileserver_rejects_traversal(tmp_path: Path) -> None:
    from app.agent.fileserver import create_file_server

    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    root = tmp_path / "downloads"
    root.mkdir()

    app = create_file_server(str(root))
    handler = next(route for route in app.router.routes() if route.resource.canonical == "/tasks/{task_id}/{filename}").handler
    request = make_mocked_request("GET", "/tasks/../secret.txt/x", app=app, match_info={"task_id": "..", "filename": "secret.txt"})

    response = await handler(request)
    assert response.status == 400


@pytest.mark.asyncio
async def test_fileserver_serves_file_inside_root(tmp_path: Path) -> None:
    from app.agent.fileserver import create_file_server

    root = tmp_path / "downloads"
    file_dir = root / "task1"
    file_dir.mkdir(parents=True)
    (file_dir / "file.txt").write_text("ok", encoding="utf-8")

    app = create_file_server(str(root))
    handler = next(route for route in app.router.routes() if route.resource.canonical == "/tasks/{task_id}/{filename}").handler
    request = make_mocked_request("GET", "/tasks/task1/file.txt", app=app, match_info={"task_id": "task1", "filename": "file.txt"})

    response = await handler(request)
    assert response.status == 200

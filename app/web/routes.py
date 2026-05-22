"""
Allfiledown — Web 页面路由
"""
import os
import ssl
import asyncio
import logging
from pathlib import Path

logger = logging.getLogger("afd")
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from app.config import config, save_config
from app.database import get_db

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "files.html", {
        "node_id": str(config["node_id"]),
        "node_name": str(config["node_name"]),
    })


@router.get("/health")
async def health_check():
    return {"status": "ok"}


@router.get("/downloads", response_class=HTMLResponse)
async def downloads_page(request: Request):
    return templates.TemplateResponse(request, "downloads.html", {
        "node_id": str(config["node_id"]),
        "node_name": str(config["node_name"]),
    })


@router.get("/nodes", response_class=HTMLResponse)
async def nodes_page(request: Request):
    from app.config import config as cfg
    return templates.TemplateResponse(request, "nodes.html", {
        "node_id": str(cfg["node_id"]),
        "node_name": str(cfg["node_name"]),
        "download_dir": str(cfg["download_dir"]),
    })


@router.get("/stations", response_class=HTMLResponse)
async def stations_page(request: Request):
    from app.config import config as cfg
    return templates.TemplateResponse(request, "stations.html", {
        "node_id": str(cfg["node_id"]),
        "node_name": str(cfg["node_name"]),
    })


@router.post("/api/task/create")
async def create_task(request: Request):
    data = await request.json()
    url = data.get("url")
    filename = data.get("filename")
    if not url:
        logger.warning(f"Task create failed: no URL provided, data={data}")
        return JSONResponse({"error": "URL is required"}, status_code=400)
    from app.agent.orchestrator import orchestrator
    logger.info(f"Creating task: url={url[:80]}... filename={filename}")
    task_id = await orchestrator.create_task(url, filename)
    logger.info(f"Task created: {task_id}")
    return {"task_id": task_id, "status": "created"}


@router.get("/api/task/list")
async def list_tasks():
    from app.agent.orchestrator import orchestrator
    tasks = await orchestrator.get_task_list()
    return {"tasks": tasks}


@router.get("/api/task/{task_id}")
async def task_detail(task_id: str):
    from app.agent.orchestrator import orchestrator
    detail = await orchestrator.get_task_detail(task_id)
    if not detail:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return detail


@router.get("/api/task/{task_id}/overview")
async def task_nodes_overview(task_id: str):
    """查询所有节点的任务状态（包括远程节点）"""
    from app.agent.orchestrator import orchestrator
    import aiohttp

    local = await orchestrator.get_task_detail(task_id)
    if not local:
        return JSONResponse({"error": "Not found"}, status_code=404)

    node_map = {}
    for n in local.get("nodes", []):
        node_map[n["node_id"]] = n

    # 查询远程节点
    peers = config.get("peers", [])
    local_node_id = config.get("node_id", "")

    async def fetch_peer(peer):
        peer_id = peer.get("id", "")
        if peer_id == local_node_id:
            return
        host = peer.get("host", "")
        port = peer.get("port", 18790)
        url = f"http://{host}:{port}/api/task/{task_id}"
        timeout = aiohttp.ClientTimeout(total=5)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for n in data.get("nodes", []):
                            if n["node_id"] not in node_map:
                                node_map[n["node_id"]] = n
                            else:
                                # 合并远程数据
                                node_map[n["node_id"]].update(n)
        except Exception:
            node_map[peer_id] = {
                "node_id": peer_id,
                "node_name": peer.get("name", peer_id),
                "progress": 0,
                "download_speed": 0,
                "status": "offline",
                "gid": None
            }

    tasks = [fetch_peer(p) for p in peers]
    await asyncio.gather(*tasks)

    merged = dict(local)
    merged["nodes"] = list(node_map.values())
    return merged


@router.post("/api/node/add")
async def add_node(request: Request):
    data = await request.json()
    node_id = data.get("node_id")
    name = data.get("name")
    host = data.get("host")
    port = data.get("port", 18790)
    node_type = data.get("node_type", "full")
    auth_token = data.get("auth_token", "")

    if not node_id or not name or not host:
        return JSONResponse({"error": "Missing required fields"}, status_code=400)

    db = get_db()
    db.execute(
        "INSERT OR REPLACE INTO nodes (id, name, host, port, node_type, auth_token, status) "
        "VALUES (?, ?, ?, ?, ?, ?, 'unknown')",
        (node_id, name, host, port, node_type, auth_token)
    )
    db.commit()

    # 也更新到 config.peers
    peers = config.get("peers", [])
    # 避免重复
    peers = [p for p in peers if p.get("id") != node_id]
    peers.append({
        "id": node_id, "name": name, "host": host,
        "port": port, "node_type": node_type, "auth_token": auth_token
    })
    config["peers"] = peers
    save_config(config)

    return {"status": "added", "node_id": node_id}


@router.post("/api/node/remove")
async def remove_node(request: Request):
    data = await request.json()
    node_id = data.get("node_id")
    if not node_id:
        return JSONResponse({"error": "node_id required"}, status_code=400)

    db = get_db()
    db.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
    db.commit()

    config["peers"] = [p for p in config.get("peers", []) if p.get("id") != node_id]
    save_config(config)
    return {"status": "removed"}

@router.get("/files", response_class=HTMLResponse)
async def files_page(request: Request):
    # 文件库别名，保持一致
    return await index(request)


@router.get("/api/files")
async def list_files(request: Request):
    """列出所有已完成的下载文件（含多节点下载源）"""
    db = get_db()
    rows = db.execute("""
        SELECT t.id, t.filename, t.url, t.total_size, t.status, t.created_at, t.updated_at,
               tn.local_path, tn.node_id, tn.internal_url
        FROM tasks t
        JOIN task_nodes tn ON tn.task_id = t.id
        WHERE t.status IN ('completed', 'all_completed', 'seeding')
        AND tn.local_path IS NOT NULL AND tn.local_path != ''
        ORDER BY t.updated_at DESC
    """).fetchall()

    # 按 task_id 分组，收集所有节点
    file_map = {}
    for row in rows:
        r = dict(row)
        task_id = r["id"]
        path = r.get("local_path", "")
        size = r.get("total_size", 0)
        filename = r.get("filename") or (path.split("/")[-1] if path else "unknown")
        node_id = r.get("node_id", "")
        internal_url = r.get("internal_url", "")

        if task_id not in file_map:
            file_map[task_id] = {
                "task_id": task_id,
                "filename": filename,
                "url": r["url"],
                "size": size,
                "size_formatted": format_file_size(size),
                "status": r["status"],
                "downloaded_at": r["updated_at"],
                "sources": []
            }

        # 修复 0.0.0.0 的 URL
        if internal_url and internal_url.startswith("http://0.0.0.0"):
            internal_url = internal_url.replace("http://0.0.0.0", f"http://{config.get('host', 'localhost')}")

        # 通过文件服务器的本地路径（相对路径，走域名反代）
        token = config.get("auth_token", "")
        local_download = f"/tasks/{task_id}/{filename}"
        if token:
            local_download += f"?token={token}"

        # 查节点名称
        node_row = db.execute("SELECT name FROM nodes WHERE id = ?", (node_id,)).fetchone()
        node_label = node_row["name"] if node_row else (config.get("node_name", "") if node_id == config.get("node_id", "") else node_id)

        # 本地节点用相对路径（走 nginx 反代），远程节点用绝对 URL
        is_local = node_id == config.get("node_id", "")
        download_url = local_download if is_local else (internal_url or local_download)

        source = {
            "node_id": node_id,
            "node_label": node_label,
            "download_url": download_url,
            "is_local": is_local,
        }
        file_map[task_id]["sources"].append(source)

    files = list(file_map.values())
    for f in files:
        # 主下载链接默认为当前节点
        local_sources = [s for s in f["sources"] if s["is_local"]]
        remote_sources = [s for s in f["sources"] if not s["is_local"]]
        preferred = local_sources + remote_sources
        if preferred:
            f["download_url"] = preferred[0]["download_url"]
            f["from_node"] = preferred[0]["node_id"]
        else:
            f["download_url"] = ""
            f["from_node"] = ""
        # 标记是否多源
        f["multi_source"] = len(f["sources"]) > 1

    return {"files": files, "total": len(files)}

@router.post("/api/node/update")
async def update_node(request: Request):
    data = await request.json()
    node_id = data.get("node_id")
    if not node_id:
        return JSONResponse({"error": "node_id required"}, status_code=400)

    db = get_db()
    existing = db.execute("SELECT id FROM nodes WHERE id = ?", (node_id,)).fetchone()
    if not existing:
        return JSONResponse({"error": "Node not found"}, status_code=404)

    updates = []
    params = []
    fields = {"name": "name", "host": "host", "port": "port", "node_type": "node_type", "auth_token": "auth_token", "save_path": "save_path"}
    for field, col in fields.items():
        if field in data:
            updates.append(f"{col} = ?")
            params.append(data[field])

    if updates:
        params.append(node_id)
        db.execute(f"UPDATE nodes SET {', '.join(updates)} WHERE id = ?", params)
        db.commit()

    return {"status": "updated", "node_id": node_id}


@router.get("/api/browse")
async def browse_directory(path: str = "/"):
    """列出指定目录下的子目录"""
    try:
        p = Path(path).resolve()
        if not p.is_dir():
            return {"error": "not a directory", "path": str(p)}
        items = []
        for entry in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            if entry.is_dir():
                try:
                    sub = list(entry.iterdir())
                    item_count = len(sub)
                except PermissionError:
                    item_count = -1
                items.append({
                    "name": entry.name,
                    "path": str(entry),
                    "type": "dir",
                    "items": item_count
                })
        parent = str(p.parent) if p.parent != p else None
        return {"path": str(p), "parent": parent, "items": items}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/api/browse/mkdir")
async def create_directory(request: Request):
    """创建新目录"""
    data = await request.json()
    dir_path = data.get("path", "")
    if not dir_path:
        return JSONResponse({"error": "path required"}, status_code=400)
    try:
        p = Path(dir_path).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return {"status": "created", "path": str(p)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/tasks/{task_id}/{filename}")
async def serve_local_file(task_id: str, filename: str, request: Request):
    """通过 Web 端口直接提供文件下载（不走文件服务器）"""
    from fastapi.responses import FileResponse
    download_dir = Path(config["download_dir"])
    file_path = download_dir / task_id / filename
    if not file_path.exists() or not file_path.is_file():
        logger.warning(f"File download 404: task={task_id} file={filename} path={file_path}")
        return JSONResponse({"error": "File not found"}, status_code=404)
    logger.info(f"File download: task={task_id} file={filename}")
    return FileResponse(str(file_path))


@router.post("/api/task/cancel")
async def cancel_task(request: Request):
    data = await request.json()
    task_id = data.get("task_id")
    if not task_id:
        return JSONResponse({"error": "task_id required"}, status_code=400)
    from app.agent.orchestrator import orchestrator
    result = await orchestrator.cancel_task(task_id)
    return result


@router.post("/api/task/delete")
async def delete_task(request: Request):
    data = await request.json()
    task_id = data.get("task_id")
    if not task_id:
        return JSONResponse({"error": "task_id required"}, status_code=400)
    from app.agent.orchestrator import orchestrator
    result = await orchestrator.delete_task(task_id)
    return result


@router.post("/api/task/clear-completed")
async def clear_completed(request: Request):
    from app.agent.orchestrator import orchestrator
    result = await orchestrator.clear_completed()
    return result


@router.post("/api/task/pause")
async def pause_task(request: Request):
    data = await request.json()
    task_id = data.get("task_id")
    if not task_id:
        return JSONResponse({"error": "task_id required"}, status_code=400)
    from app.agent.orchestrator import orchestrator
    result = await orchestrator.pause_task(task_id)
    return result


@router.post("/api/task/resume")
async def resume_task(request: Request):
    data = await request.json()
    task_id = data.get("task_id")
    if not task_id:
        return JSONResponse({"error": "task_id required"}, status_code=400)
    from app.agent.orchestrator import orchestrator
    result = await orchestrator.resume_task(task_id)
    return result


@router.post("/api/task/retry")
async def retry_task(request: Request):
    data = await request.json()
    task_id = data.get("task_id")
    if not task_id:
        return JSONResponse({"error": "task_id required"}, status_code=400)
    from app.agent.orchestrator import orchestrator
    result = await orchestrator.retry_task(task_id)
    return result


@router.get("/api/preview/{task_id}/{filename}")
async def preview_file(task_id: str, filename: str):
    """文件预览（文本/图片）"""
    from fastapi.responses import FileResponse, HTMLResponse, Response
    download_dir = Path(config["download_dir"])
    file_path = download_dir / task_id / filename
    if not file_path.exists() or not file_path.is_file():
        return JSONResponse({"error": "File not found"}, status_code=404)

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    text_exts = {"txt", "md", "json", "yml", "yaml", "xml", "csv", "log", "cfg", "conf", "ini", "toml", "sh", "py", "js", "ts", "html", "css"}
    image_exts = {"jpg", "jpeg", "png", "gif", "webp", "svg"}

    if ext in image_exts:
        return FileResponse(str(file_path))
    elif ext in text_exts:
        content = file_path.read_text(encoding="utf-8", errors="replace")
        escaped = content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<style>body{{background:#111;color:#e8e8e8;font:14px/1.5 monospace;padding:20px;white-space:pre-wrap;word-break:break-all;}}</style>
</head><body><pre>{escaped}</pre></body></html>"""
        return HTMLResponse(html)
    else:
        return JSONResponse({"error": "Preview not available for this file type"}, status_code=400)


@router.post("/api/file/rename")
async def rename_file(request: Request):
    data = await request.json()
    task_id = data.get("task_id")
    new_name = data.get("new_name")
    if not task_id or not new_name:
        return JSONResponse({"error": "task_id and new_name required"}, status_code=400)
    
    db = get_db()
    row = db.execute(
        "SELECT local_path FROM task_nodes WHERE task_id = ? AND local_path IS NOT NULL",
        (task_id,)
    ).fetchone()
    if not row or not row["local_path"]:
        return JSONResponse({"error": "File not found on disk"}, status_code=404)
    
    old_path = Path(row["local_path"])
    new_path = old_path.parent / new_name
    if new_path.exists():
        return JSONResponse({"error": "Target filename already exists"}, status_code=409)
    
    old_path.rename(new_path)
    db.execute(
        "UPDATE task_nodes SET local_path = ? WHERE task_id = ?",
        (str(new_path), task_id)
    )
    db.execute(
        "UPDATE tasks SET filename = ? WHERE id = ?",
        (new_name, task_id)
    )
    db.commit()
    return {"status": "renamed", "filename": new_name}


@router.get("/api/stations")
async def get_stations():
    """获取所有节点（站点）的实时统计信息"""
    import asyncio
    from urllib.parse import urlparse
    db = get_db()
    rows = db.execute("SELECT * FROM nodes ORDER BY name").fetchall()
    nodes = [dict(r) for r in rows]

    import aiohttp
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    # 本地节点 — 从 aria2 获取实时速度
    local_node_id = config.get("node_id", "")
    try:
        from app.agent.downloader import get_global_stat
        gs = await get_global_stat()
        if gs:
            local_speed_download = int(gs.get("downloadSpeed", 0))
            local_speed_upload = int(gs.get("uploadSpeed", 0))
            local_active = int(gs.get("numActive", 0))
            local_waiting = int(gs.get("numWaiting", 0))
            local_stopped = int(gs.get("numStopped", 0))
        else:
            local_speed_download = 0
            local_speed_upload = 0
            local_active = 0
            local_waiting = 0
            local_stopped = 0
    except Exception:
        local_speed_download = 0
        local_speed_upload = 0
        local_active = 0
        local_waiting = 0
        local_stopped = 0

    # 健康检查 — 并发 ping 所有节点
    async def check_node(n):
        node_id = n["id"]
        host = n.get("host", "")
        port = n.get("port", 18790)
        if node_id == local_node_id:
            return (node_id, "online")
        if not host:
            return (node_id, "offline")
        try:
            timeout = aiohttp.ClientTimeout(total=3)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(f"http://{host}:{port}/health", ssl=ssl_ctx) as resp:
                    if resp.status == 200:
                        return (node_id, "online")
                    return (node_id, "offline")
        except Exception:
            return (node_id, "offline")

    check_results = await asyncio.gather(*[check_node(n) for n in nodes], return_exceptions=True)
    node_status_map = {}
    for r in check_results:
        if isinstance(r, tuple) and len(r) == 2:
            node_status_map[r[0]] = r[1]

    # 更新 DB
    for node_id, status in node_status_map.items():
        db.execute("UPDATE nodes SET status = ? WHERE id = ?", (status, node_id))
    db.commit()

    stations = []
    for n in nodes:
        node_id = n["id"]
        is_local = node_id == local_node_id

        # 任务统计
        task_counts = db.execute("""
            SELECT tn.status, COUNT(*) as cnt
            FROM task_nodes tn WHERE tn.node_id = ?
            GROUP BY tn.status
        """, (node_id,)).fetchall()

        status_map = {}
        for r in task_counts:
            status_map[r["status"]] = r["cnt"]

        active_tasks = db.execute("""
            SELECT t.id, t.filename, t.url, tn.progress, tn.status, tn.gid
            FROM task_nodes tn
            JOIN tasks t ON tn.task_id = t.id
            WHERE tn.node_id = ? AND tn.status IN ('downloading', 'pending', 'paused')
            ORDER BY t.created_at DESC
            LIMIT 20
        """, (node_id,)).fetchall()

        checked_status = node_status_map.get(node_id, n.get("status", "unknown"))
        station = {
            "id": node_id,
            "name": n.get("name", node_id),
            "host": n.get("host", ""),
            "port": n.get("port", 0),
            "node_type": n.get("node_type", "full"),
            "status": checked_status,
            "auth_token": n.get("auth_token", ""),
            "is_local": is_local,
            "stats": {
                "downloading": status_map.get("downloading", 0),
                "pending": status_map.get("pending", 0),
                "paused": status_map.get("paused", 0),
                "seeding": status_map.get("seeding", 0),
                "completed": status_map.get("completed", 0) + status_map.get("all_completed", 0),
                "failed": status_map.get("failed", 0) + status_map.get("cancelled", 0),
                "total": sum(status_map.values()),
            },
            "speed": {
                "download": local_speed_download if is_local else 0,
                "upload": local_speed_upload if is_local else 0,
                "active": local_active if is_local else 0,
                "waiting": local_waiting if is_local else 0,
                "stopped": local_stopped if is_local else 0,
            } if is_local else None,
            "active_tasks": [{
                "id": t["id"],
                "filename": t["filename"] or t["url"].split("/")[-1] or t["id"],
                "progress": t["progress"] or 0,
                "status": t["status"],
                "gid": t["gid"],
            } for t in active_tasks],
        }
        stations.append(station)

    return {"stations": stations, "count": len(stations)}


@router.get("/api/nodes")
async def list_nodes():
    db = get_db()
    rows = db.execute("SELECT * FROM nodes ORDER BY name").fetchall()
    return {"nodes": [dict(r) for r in rows]}


def format_file_size(bytes):
    if not bytes or bytes == 0:
        return "未知"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    size = float(bytes)
    while size >= 1024 and i < len(units) - 1:
        size /= 1024
        i += 1
    return f"{size:.1f} {units[i]}"

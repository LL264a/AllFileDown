"""
Allfiledown — aria2 RPC 控制
"""

from __future__ import annotations

import ssl
import uuid
from typing import Any

import aiohttp

from app.config import config


def _rpc_url() -> str:
    """构建 aria2 RPC URL"""
    a: dict[str, Any] = config["aria2"]
    scheme: str = "https" if a.get("tls") else "http"
    return f"{scheme}://{a['host']}:{a['port']}/jsonrpc"


def _rpc_auth() -> str:
    """构建 RPC 认证字符串"""
    return f"token:{config['aria2']['secret']}"


def _ssl_ctx() -> ssl.SSLContext:
    """创建宽松的 SSL 上下文（允许自签名证书）"""
    ctx: ssl.SSLContext = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


async def rpc_call(method: str, params: list[Any] | None = None) -> Any:
    """调用 aria2 RPC 方法"""
    if params is None:
        params = []
    payload: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4())[:8],
        "method": method,
        "params": [_rpc_auth()] + params,
    }

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                _rpc_url(),
                json=payload,
                ssl=_ssl_ctx(),
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                data: dict[str, Any] = await resp.json()
                if "error" in data:
                    raise RuntimeError(f"aria2 RPC error: {data['error']}")
                return data.get("result")
        except Exception as e:
            raise RuntimeError(f"aria2 connection failed: {e}") from e


async def add_download(url: str, download_dir: str, filename: str | None = None) -> str:
    """添加下载任务到 aria2，返回 GID"""
    options: dict[str, Any] = {
        "dir": download_dir,
        "max-connection-per-server": "16",
        "split": "16",
        "continue": "true",
    }
    if filename:
        options["out"] = filename

    result: str = await rpc_call("aria2.addUri", [[url], options])
    return result


async def add_download_with_sources(
    urls: list[str],
    download_dir: str,
    filename: str | None = None,
) -> str:
    """多源下载 — 传入多个 URL（官方源 + 内部源），智能选择最快源"""
    options: dict[str, Any] = {
        "dir": download_dir,
        "max-connection-per-server": "16",
        "split": "16",
        "continue": "true",
        "uri-selector": "feedback",
    }
    if filename:
        options["out"] = filename

    result: str = await rpc_call("aria2.addUri", [urls, options])
    return result


async def add_torrent(torrent_path: str, download_dir: str) -> str:
    """添加 BT 种子下载"""
    options: dict[str, Any] = {
        "dir": download_dir,
        "max-connection-per-server": "16",
        "split": "16",
        "seed-ratio": "0.0",
    }
    result: str = await rpc_call("aria2.addTorrent", [torrent_path, [], options])
    return result


async def get_status(gid: str) -> dict[str, Any] | None:
    """查询下载状态"""
    result: dict[str, Any] | None = await rpc_call("aria2.tellStatus", [gid])
    if not result:
        return None
    total: int = int(result.get("totalLength", 0))
    completed: int = int(result.get("completedLength", 0))
    status: str = result.get("status", "unknown")
    download_speed: int = int(result.get("downloadSpeed", 0))

    return {
        "gid": gid,
        "status": status,
        "total_size": total,
        "completed_size": completed,
        "progress": (completed / total * 100) if total > 0 else 0,
        "speed": download_speed,
        "dir": result.get("dir", ""),
        "files": result.get("files", []),
        "connections": result.get("connections", "0"),
        "followed_by": result.get("followedBy", []),
        "bittorrent": result.get("bittorrent", {}),
    }


async def pause(gid: str) -> Any:
    """暂停下载"""
    try:
        return await rpc_call("aria2.pause", [gid])
    except Exception:
        return None


async def unpause(gid: str) -> Any:
    """恢复下载"""
    try:
        return await rpc_call("aria2.unpause", [gid])
    except Exception:
        return None


async def remove(gid: str) -> Any:
    """移除下载"""
    try:
        return await rpc_call("aria2.remove", [gid])
    except Exception:
        return None


async def get_global_stat() -> dict[str, Any] | None:
    """获取 aria2 全局统计"""
    result: dict[str, Any] | None = await rpc_call("aria2.getGlobalStat")
    return result


async def add_source(gid: str, source_url: str) -> Any:
    """为已有下载添加新源"""
    try:
        return await rpc_call("aria2.changeUri", [gid, 0, [source_url], []])
    except Exception as e:
        return {"error": str(e)}


async def tell_active() -> Any:
    """获取活动中的下载列表"""
    return await rpc_call("aria2.tellActive")


async def tell_waiting(offset: int = 0, num: int = 50) -> Any:
    """获取等待中的下载列表"""
    return await rpc_call("aria2.tellWaiting", [offset, num])


async def tell_stopped(offset: int = 0, num: int = 50) -> Any:
    """获取已完成的下载列表"""
    return await rpc_call("aria2.tellStopped", [offset, num])


async def get_uris(gid: str) -> Any:
    """获取下载的所有 URI 及其状态"""
    return await rpc_call("aria2.getUris", [gid])

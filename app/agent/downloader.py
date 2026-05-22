"""
Allfiledown — aria2 RPC 控制
"""
import json
import ssl
import uuid
import aiohttp
from app.config import config


def _rpc_url():
    a = config["aria2"]
    scheme = "https" if a.get("tls") else "http"
    return f"{scheme}://{a['host']}:{a['port']}/jsonrpc"


def _rpc_auth():
    return f"token:{config['aria2']['secret']}"


async def rpc_call(method, params=None):
    """调用 aria2 RPC"""
    if params is None:
        params = []
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4())[:8],
        "method": method,
        "params": [_rpc_auth()] + params
    }
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                _rpc_url(),
                json=payload,
                ssl=ssl_ctx,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                data = await resp.json()
                if "error" in data:
                    raise Exception(f"aria2 RPC error: {data['error']}")
                return data.get("result")
        except Exception as e:
            raise Exception(f"aria2 connection failed: {e}")


async def add_download(url, download_dir, filename=None):
    """添加下载任务到 aria2"""
    options = {
        "dir": download_dir,
        "max-connection-per-server": "16",
        "split": "16",
        "continue": "true"
    }
    if filename:
        options["out"] = filename

    result = await rpc_call("aria2.addUri", [[url], options])
    return result  # gid


async def add_download_with_sources(urls, download_dir, filename=None):
    """多源下载 — 传入多个 URL（官方源 + 内部源）"""
    options = {
        "dir": download_dir,
        "max-connection-per-server": "16",
        "split": "16",
        "continue": "true",
        "uri-selector": "feedback"  # 智能选择最快的源
    }
    if filename:
        options["out"] = filename

    result = await rpc_call("aria2.addUri", [urls, options])
    return result


async def add_torrent(torrent_path, download_dir):
    """添加 BT 种子下载"""
    options = {
        "dir": download_dir,
        "max-connection-per-server": "16",
        "split": "16",
        "seed-ratio": "0.0"  # 不限分享率
    }
    result = await rpc_call("aria2.addTorrent", [torrent_path, [], options])
    return result


async def get_status(gid):
    """查询下载状态"""
    result = await rpc_call("aria2.tellStatus", [gid])
    if not result:
        return None
    total = int(result.get("totalLength", 0))
    completed = int(result.get("completedLength", 0))
    status = result.get("status", "unknown")
    download_speed = int(result.get("downloadSpeed", 0))
    info = {
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
        "bittorrent": result.get("bittorrent", {})
    }
    return info


async def change_option(gid, options):
    """修改下载选项"""
    return await rpc_call("aria2.changeOption", [gid, options])


async def pause(gid):
    """暂停下载"""
    try:
        return await rpc_call("aria2.pause", [gid])
    except Exception:
        return None


async def unpause(gid):
    """恢复下载"""
    try:
        return await rpc_call("aria2.unpause", [gid])
    except Exception:
        return None


async def remove(gid):
    """移除下载"""
    try:
        return await rpc_call("aria2.remove", [gid])
    except Exception:
        return None


async def get_global_stat():
    """获取全局统计"""
    result = await rpc_call("aria2.getGlobalStat")
    return result


async def add_source(gid, source_url):
    """为已有下载添加新源"""
    try:
        # aria2.changeUri 可以添加新的 URI 到已有下载
        return await rpc_call("aria2.changeUri", [gid, 0, [source_url], []])
    except Exception as e:
        return {"error": str(e)}


async def tell_active():
    """获取活动中的下载列表"""
    result = await rpc_call("aria2.tellActive")
    return result


async def tell_waiting(offset=0, num=50):
    """获取等待中的下载列表"""
    result = await rpc_call("aria2.tellWaiting", [offset, num])
    return result


async def tell_stopped(offset=0, num=50):
    """获取已完成的下载列表"""
    result = await rpc_call("aria2.tellStopped", [offset, num])
    return result


async def get_uris(gid):
    """获取下载的所有 URI 及其状态"""
    result = await rpc_call("aria2.getUris", [gid])
    return result

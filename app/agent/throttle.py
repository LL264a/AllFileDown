"""
Allfiledown — 下载限速 / 带宽控制模块
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from app.agent.downloader import rpc_call
from app.config import config

logger = logging.getLogger("afd")

# aria2 限速选项名
_ARIA2_GLOBAL_DL = "max-overall-download-limit"
_ARIA2_GLOBAL_UL = "max-overall-upload-limit"
_ARIA2_TASK_DL = "max-download-limit"

# 内部状态缓存
_current_limits: dict[str, int] = {
    "global_download": 0,
    "global_upload": 0,
}

_schedule_task: asyncio.Task[Any] | None = None


def _kb_to_bytes(kb: int) -> str:
    """KB/s → aria2 所需的 bytes/s 字符串（0 表示不限速）"""
    if kb <= 0:
        return "0"
    return str(kb * 1024)


def _bytes_to_kb(value: str) -> int:
    """aria2 返回的 bytes/s → KB/s"""
    try:
        b = int(value)
        return b // 1024
    except (ValueError, TypeError):
        return 0


async def set_global_speed_limit(download_limit_kb: int = 0, upload_limit_kb: int = 0) -> dict[str, Any]:
    """设置 aria2 全局下载/上传限速（KB/s，0=不限速）"""
    options: dict[str, str] = {
        _ARIA2_GLOBAL_DL: _kb_to_bytes(download_limit_kb),
        _ARIA2_GLOBAL_UL: _kb_to_bytes(upload_limit_kb),
    }
    try:
        result: Any = await rpc_call("aria2.changeGlobalOption", [options])
        _current_limits["global_download"] = max(0, download_limit_kb)
        _current_limits["global_upload"] = max(0, upload_limit_kb)
        logger.info(
            "Global speed limit set: download=%s KB/s, upload=%s KB/s",
            download_limit_kb or "unlimited",
            upload_limit_kb or "unlimited",
        )
        return {"success": True, "download_limit": download_limit_kb, "upload_limit": upload_limit_kb, "result": result}
    except Exception as e:
        logger.warning("Failed to set global speed limit: %s", e)
        return {"success": False, "error": str(e)}


async def set_task_speed_limit(gid: str, download_limit_kb: int = 0) -> dict[str, Any]:
    """设置单个任务的下载限速（KB/s，0=不限速）"""
    options: dict[str, str] = {
        _ARIA2_TASK_DL: _kb_to_bytes(download_limit_kb),
    }
    try:
        result: Any = await rpc_call("aria2.changeOption", [gid, options])
        logger.info(
            "Task %s speed limit set: download=%s KB/s",
            gid,
            download_limit_kb or "unlimited",
        )
        return {"success": True, "gid": gid, "download_limit": download_limit_kb, "result": result}
    except Exception as e:
        logger.warning("Failed to set task speed limit for %s: %s", gid, e)
        return {"success": False, "gid": gid, "error": str(e)}


async def get_current_limits() -> dict[str, Any]:
    """获取当前 aria2 全局限速值（KB/s）"""
    try:
        result: dict[str, Any] | None = await rpc_call("aria2.getGlobalOption")
        if not result:
            return {
                "global_download": _current_limits["global_download"],
                "global_upload": _current_limits["global_upload"],
            }
        return {
            "global_download": _bytes_to_kb(result.get(_ARIA2_GLOBAL_DL, "0")),
            "global_upload": _bytes_to_kb(result.get(_ARIA2_GLOBAL_UL, "0")),
        }
    except Exception as e:
        logger.warning("Failed to get current limits: %s", e)
        return {
            "global_download": _current_limits["global_download"],
            "global_upload": _current_limits["global_upload"],
            "error": str(e),
        }


def get_throttle_config() -> dict[str, Any]:
    """从 config 读取 throttle 配置"""
    throttle: dict[str, Any] = config.get("throttle", {})
    return {
        "global_download_limit": throttle.get("global_download_limit", 0),
        "global_upload_limit": throttle.get("global_upload_limit", 0),
        "schedule": throttle.get("schedule", {}),
    }


def save_throttle_config(
    global_download_limit: int | None = None,
    global_upload_limit: int | None = None,
    schedule: dict[str, dict[str, int]] | None = None,
) -> dict[str, Any]:
    """保存 throttle 配置到 config.json"""
    if "throttle" not in config:
        config["throttle"] = {}

    if global_download_limit is not None:
        config["throttle"]["global_download_limit"] = max(0, global_download_limit)
    if global_upload_limit is not None:
        config["throttle"]["global_upload_limit"] = max(0, global_upload_limit)
    if schedule is not None:
        config["throttle"]["schedule"] = schedule

    from app.config import save_config
    save_config(config)
    return get_throttle_config()


def _parse_time(hhmm: str) -> int:
    """将 HH:MM 转为当天分钟数 0-1439"""
    parts = hhmm.strip().split(":")
    return int(parts[0]) * 60 + int(parts[1])


def _match_schedule(schedule: dict[str, dict[str, int]]) -> dict[str, int] | None:
    """根据当前时间匹配适用的时段规则"""
    now = datetime.now()
    now_minutes = now.hour * 60 + now.minute

    for time_range, limits in schedule.items():
        try:
            start_str, end_str = time_range.split("-")
            start = _parse_time(start_str)
            end = _parse_time(end_str)

            # 支持跨午夜，如 22:00-08:00
            if start <= end:
                if start <= now_minutes < end:
                    return {
                        "download": limits.get("download", 0),
                        "upload": limits.get("upload", 0),
                    }
            else:
                if now_minutes >= start or now_minutes < end:
                    return {
                        "download": limits.get("download", 0),
                        "upload": limits.get("upload", 0),
                    }
        except (ValueError, KeyError):
            logger.warning("Invalid schedule rule: %s", time_range)
            continue

    return None


async def apply_schedule_limits() -> dict[str, Any]:
    """根据当前时间自动应用时段限速规则"""
    cfg = get_throttle_config()
    schedule: dict[str, dict[str, int]] = cfg.get("schedule", {})

    if not schedule:
        # 没有时段规则，应用全局配置
        download = cfg.get("global_download_limit", 0)
        upload = cfg.get("global_upload_limit", 0)
        result = await set_global_speed_limit(download, upload)
        return {
            "source": "global",
            "download_limit": download,
            "upload_limit": upload,
            **result,
        }

    matched = _match_schedule(schedule)
    if matched:
        download = matched.get("download", 0)
        upload = matched.get("upload", 0)
        result = await set_global_speed_limit(download, upload)
        return {
            "source": "schedule",
            "time_range": next(
                (k for k, v in schedule.items() if v.get("download") == download and v.get("upload") == upload),
                "unknown",
            ),
            "download_limit": download,
            "upload_limit": upload,
            **result,
        }

    # 没有匹配到任何时段，保持当前限速不变
    current = await get_current_limits()
    return {
        "source": "none",
        "download_limit": current.get("global_download", 0),
        "upload_limit": current.get("global_upload", 0),
        "success": True,
    }


async def _schedule_loop() -> None:
    """后台循环：每分钟检查一次时段规则并应用"""
    while True:
        try:
            result = await apply_schedule_limits()
            if result.get("source") == "schedule":
                logger.info("Schedule limit applied: %s", result)
        except Exception:
            logger.debug("Schedule loop error", exc_info=True)
        await asyncio.sleep(60)


def start_schedule_monitor() -> None:
    """启动时段限速监控后台任务"""
    global _schedule_task
    if _schedule_task is None or _schedule_task.done():
        _schedule_task = asyncio.create_task(_schedule_loop())
        logger.info("Schedule monitor started")


def stop_schedule_monitor() -> None:
    """停止时段限速监控后台任务"""
    global _schedule_task
    if _schedule_task and not _schedule_task.done():
        _schedule_task.cancel()
        logger.info("Schedule monitor stopped")

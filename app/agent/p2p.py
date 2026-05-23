"""
Allfiledown — 节点间通信（P2P 客户端）
"""

from __future__ import annotations

import ssl
from typing import Any

import aiohttp


class P2PClient:
    """P2P 客户端 — 向其他节点发送 API 请求"""

    def __init__(self, auth_token: str = "") -> None:
        self.auth_token: str = auth_token
        self.ssl_ctx: ssl.SSLContext = ssl.create_default_context()
        self.ssl_ctx.check_hostname = False
        self.ssl_ctx.verify_mode = ssl.CERT_NONE

    @staticmethod
    def _auth(node: dict[str, Any], default_token: str) -> str:
        """从节点信息中提取认证 token"""
        return str(node.get("auth_token", default_token))

    async def _request(
        self,
        method: str,
        url: str,
        data: dict[str, Any] | None = None,
        timeout: int = 10,
        auth_token: str | None = None,
    ) -> dict[str, Any]:
        """发送 HTTP 请求到目标节点"""
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "X-Auth-Token": auth_token or self.auth_token,
        }
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                kwargs: dict[str, Any] = {
                    "ssl": self.ssl_ctx,
                    "timeout": aiohttp.ClientTimeout(total=timeout),
                }
                if data is not None:
                    kwargs["json"] = data
                async with session.request(method, url, **kwargs) as resp:
                    if resp.status != 200:
                        text: str = await resp.text()
                        return {"error": f"HTTP {resp.status}: {text[:200]}"}
                    result: dict[str, Any] = await resp.json()
                    return result
        except Exception as e:
            return {"error": str(e)}

    async def ping(self, node: dict[str, Any]) -> bool:
        """检查节点是否在线"""
        url: str = f"http://{node['host']}:{node['port']}/api/ping"
        result: dict[str, Any] = await self._request(
            "GET",
            url,
            timeout=5,
            auth_token=self._auth(node, self.auth_token),
        )
        return result.get("status") == "ok"

    async def send_task(self, node: dict[str, Any], task_data: dict[str, Any]) -> dict[str, Any]:
        """发送下载任务到节点"""
        url: str = f"http://{node['host']}:{node['port']}/api/task/new"
        return await self._request(
            "POST",
            url,
            task_data,
            timeout=10,
            auth_token=self._auth(node, self.auth_token),
        )

    async def send_source(self, node: dict[str, Any], source_data: dict[str, Any]) -> dict[str, Any]:
        """通知节点：我有新内部源"""
        url: str = f"http://{node['host']}:{node['port']}/api/source/new"
        return await self._request(
            "POST",
            url,
            source_data,
            timeout=10,
            auth_token=self._auth(node, self.auth_token),
        )

    async def query_status(
        self,
        node: dict[str, Any],
        task_id: str | None = None,
    ) -> dict[str, Any]:
        """查询节点状态"""
        url: str = f"http://{node['host']}:{node['port']}/api/task/status"
        if task_id:
            url += f"?task_id={task_id}"
        return await self._request(
            "GET",
            url,
            timeout=10,
            auth_token=self._auth(node, self.auth_token),
        )

    async def register_node(
        self,
        node: dict[str, Any],
        my_info: dict[str, Any],
    ) -> dict[str, Any]:
        """向一个节点注册自己"""
        url: str = f"http://{node['host']}:{node['port']}/api/node/register"
        return await self._request(
            "POST",
            url,
            my_info,
            timeout=10,
            auth_token=self._auth(node, self.auth_token),
        )

    async def get_peers(self, node: dict[str, Any]) -> dict[str, Any]:
        """获取节点的已知节点列表"""
        url: str = f"http://{node['host']}:{node['port']}/api/nodes"
        return await self._request(
            "GET",
            url,
            timeout=10,
            auth_token=self._auth(node, self.auth_token),
        )

    async def get_events(self, node: dict[str, Any], since_id: int = 0) -> dict[str, Any]:
        """拉取事件同步"""
        url: str = f"http://{node['host']}:{node['port']}/api/events?since={since_id}"
        return await self._request(
            "GET",
            url,
            timeout=10,
            auth_token=self._auth(node, self.auth_token),
        )

"""
Allfiledown — 节点间通信（P2P 客户端）
"""
import json
import ssl
import aiohttp
import asyncio


class P2PClient:
    """向其他节点发送 API 请求"""

    def __init__(self, auth_token=""):
        self.auth_token = auth_token
        self.ssl_ctx = ssl.create_default_context()
        self.ssl_ctx.check_hostname = False
        self.ssl_ctx.verify_mode = ssl.CERT_NONE

    async def _request(self, method, url, data=None, timeout=10, auth_token=None):
        headers = {
            "Content-Type": "application/json",
            "X-Auth-Token": auth_token or self.auth_token
        }
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                kwargs = {"ssl": self.ssl_ctx, "timeout": aiohttp.ClientTimeout(total=timeout)}
                if data is not None:
                    kwargs["json"] = data
                async with session.request(method, url, **kwargs) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        return {"error": f"HTTP {resp.status}: {text[:200]}"}
                    return await resp.json()
        except asyncio.TimeoutError:
            return {"error": "timeout"}
        except Exception as e:
            return {"error": str(e)}

    def _auth(self, node):
        """从节点信息中提取认证 token"""
        return node.get("auth_token", self.auth_token)

    async def ping(self, node):
        """检查节点是否在线"""
        url = f"http://{node['host']}:{node['port']}/api/ping"
        result = await self._request("GET", url, timeout=5, auth_token=self._auth(node))
        return result.get("status") == "ok"

    async def send_task(self, node, task_data):
        """发送下载任务到节点"""
        url = f"http://{node['host']}:{node['port']}/api/task/new"
        return await self._request("POST", url, task_data, timeout=10, auth_token=self._auth(node))

    async def send_source(self, node, source_data):
        """通知节点：我有新内部源"""
        url = f"http://{node['host']}:{node['port']}/api/source/new"
        return await self._request("POST", url, source_data, timeout=10, auth_token=self._auth(node))

    async def query_status(self, node, task_id=None):
        """查询节点状态"""
        url = f"http://{node['host']}:{node['port']}/api/task/status"
        if task_id:
            url += f"?task_id={task_id}"
        return await self._request("GET", url, timeout=10, auth_token=self._auth(node))

    async def register_node(self, node, my_info):
        """向一个节点注册自己"""
        url = f"http://{node['host']}:{node['port']}/api/node/register"
        return await self._request("POST", url, my_info, timeout=10, auth_token=self._auth(node))

    async def get_peers(self, node):
        """获取节点的已知节点列表"""
        url = f"http://{node['host']}:{node['port']}/api/nodes"
        return await self._request("GET", url, timeout=10, auth_token=self._auth(node))

    async def get_events(self, node, since_id=0):
        """拉取事件同步"""
        url = f"http://{node['host']}:{node['port']}/api/events?since={since_id}"
        return await self._request("GET", url, timeout=10, auth_token=self._auth(node))

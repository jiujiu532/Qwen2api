"""
browser_engine.py — 浏览器引擎桩（Stub）
提供与 HttpxEngine 相同的接口，内部委托给 curl_cffi 直连。
如需真正的 Camoufox 无头浏览器，请安装 camoufox 并替换此实现。
"""

import asyncio
import logging

log = logging.getLogger("qwen2api.browser_engine")


class BrowserEngine:
    """Browser engine stub — same interface as HttpxEngine."""

    def __init__(self, pool_size: int = 2):
        self.pool_size = pool_size
        self._started = False
        self._queue = 0

    async def start(self):
        self._started = True
        log.info(f"[BrowserEngine] 已启动（Stub 模式，pool_size={self.pool_size}）")

    async def stop(self):
        self._started = False
        log.info("[BrowserEngine] 已停止")

    async def api_call(self, method: str, path: str, token: str, body: dict = None) -> dict:
        """Delegate to httpx for API calls."""
        from backend.core.httpx_engine import HttpxEngine
        engine = HttpxEngine()
        return await engine.api_call(method, path, token, body)

    async def fetch_chat(self, token: str, chat_id: str, payload: dict, buffered: bool = False):
        """Delegate to httpx for streaming chat."""
        from backend.core.httpx_engine import HttpxEngine
        engine = HttpxEngine()
        async for chunk in engine.fetch_chat(token, chat_id, payload, buffered):
            yield chunk

"""
hybrid_engine.py — 混合引擎
api_call 优先走 httpx（快），fetch_chat 优先走 browser（指纹安全），失败回退。
"""

import logging

log = logging.getLogger("qwen2api.hybrid_engine")


class HybridEngine:
    """Hybrid: api_call → httpx first, fetch_chat → browser first."""

    def __init__(self, browser_engine, httpx_engine):
        self.browser_engine = browser_engine
        self.httpx_engine = httpx_engine

    async def start(self):
        await self.browser_engine.start()
        await self.httpx_engine.start()
        log.info("[HybridEngine] 已启动（混合模式）")

    async def stop(self):
        await self.browser_engine.stop()
        await self.httpx_engine.stop()
        log.info("[HybridEngine] 已停止")

    async def api_call(self, method: str, path: str, token: str, body: dict = None) -> dict:
        """API 调用优先 httpx（更快），失败回退 browser。"""
        r = await self.httpx_engine.api_call(method, path, token, body)
        status = r.get("status", 0)
        body_text = (r.get("body") or "").lower()
        should_fallback = (
            status == 0
            or status in (401, 403)
            or "waf" in body_text
            or "<!doctype" in body_text
        )
        if should_fallback:
            log.warning(f"[HybridEngine] api_call httpx 失败 (status={status}), 回退 browser")
            r = await self.browser_engine.api_call(method, path, token, body)
        return r

    async def fetch_chat(self, token: str, chat_id: str, payload: dict, buffered: bool = False):
        """流式聊天：直接走 httpx（curl_cffi Chrome 指纹）。"""
        async for chunk in self.httpx_engine.fetch_chat(token, chat_id, payload, buffered):
            yield chunk

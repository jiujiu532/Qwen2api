"""
httpx_engine.py -- 用 curl_cffi 直连 Qwen API（Chrome TLS 指纹）
优点：TLS 指纹与真实 Chrome 一致，连接池复用，流式即时透传
"""

import asyncio
import json
import logging

log = logging.getLogger("qwen2api.httpx_engine")

BASE_URL = "https://chat.qwen.ai"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://chat.qwen.ai/",
    "Origin": "https://chat.qwen.ai",
    "source": "web",
    "version": "0.2.46",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
}

_IMPERSONATE = "chrome124"


class HttpxEngine:
    """Direct curl_cffi engine -- Chrome TLS fingerprint, connection pool reuse."""

    def __init__(self, pool_size: int = 3, base_url: str = BASE_URL):
        self.base_url = base_url
        self._started = False
        self._ready = asyncio.Event()
        self._session = None

    async def start(self):
        self._started = True
        self._ready.set()
        log.info("[HttpxEngine] 已启动（curl_cffi Chrome指纹直连模式）")

    async def stop(self):
        self._started = False
        if self._session:
            await self._session.close()
            self._session = None
        log.info("[HttpxEngine] 已停止")

    def _auth_headers(self, token: str) -> dict:
        return {**_HEADERS, "Authorization": f"Bearer {token}"}

    async def api_call(self, method: str, path: str, token: str, body: dict = None) -> dict:
        from curl_cffi.requests import AsyncSession
        url = self.base_url + path
        headers = {**self._auth_headers(token), "Content-Type": "application/json"}
        data = json.dumps(body, ensure_ascii=False).encode() if body else None
        try:
            async with AsyncSession(impersonate=_IMPERSONATE, timeout=30) as client:
                resp = await client.request(method, url, headers=headers, data=data)
            return {"status": resp.status_code, "body": resp.text}
        except Exception as e:
            log.error(f"[HttpxEngine] api_call error: {e}")
            return {"status": 0, "body": str(e)}

    async def fetch_chat(self, token: str, chat_id: str, payload: dict, buffered: bool = False):
        """Stream Qwen SSE -- 使用标准 httpx 实现真正的流式读取。"""
        import httpx as _httpx
        url = self.base_url + f"/api/v2/chat/completions?chat_id={chat_id}"
        headers = {
            **self._auth_headers(token),
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Accept-Encoding": "identity",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Origin": "https://chat.qwen.ai",
            "Referer": "https://chat.qwen.ai/",
        }
        body_str = json.dumps(payload, ensure_ascii=False)

        try:
            async with _httpx.AsyncClient(timeout=_httpx.Timeout(120, connect=15)) as client:
                async with client.stream("POST", url, headers=headers, content=body_str.encode()) as resp:
                    if resp.status_code != 200:
                        body_text = (await resp.aread()).decode(errors="replace")[:2000]
                        yield {"status": resp.status_code, "body": body_text}
                        return

                    # 使用 aiter_bytes 逐 chunk 读取（最底层，无缓冲）
                    buffer = b""
                    async for raw in resp.aiter_bytes():
                        if not raw:
                            continue
                        buffer += raw
                        while b"\n" in buffer:
                            line_bytes, buffer = buffer.split(b"\n", 1)
                            line = line_bytes.decode("utf-8", errors="replace").strip()
                            if not line:
                                continue
                            yield {"status": "streamed", "chunk": line + "\n"}
                    if buffer.strip():
                        yield {"status": "streamed", "chunk": buffer.decode("utf-8", errors="replace").strip() + "\n"}

        except Exception as e:
            log.error(f"[HttpxEngine] fetch_chat error: {e}")
            yield {"status": 0, "body": str(e)}

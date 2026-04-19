"""
request_cache.py — LRU 响应缓存

对相同 (model + prompt + temperature + max_tokens) 的非流式请求进行缓存，
避免重复消耗账号 RPM/TPM 配额。
"""

import hashlib
import json
import time
import logging
from collections import OrderedDict
from typing import Optional, Any

log = logging.getLogger("qwen2api.cache")


class RequestCache:
    """线程安全的 LRU 响应缓存。"""

    def __init__(self, max_size: int = 500, ttl: int = 60):
        self.max_size = max_size
        self.ttl = ttl
        self._cache: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    @staticmethod
    def _make_key(model: str, prompt: str, temperature: float = 1.0,
                  max_tokens: int = 0, **kwargs) -> str:
        raw = json.dumps({
            "model": model, "prompt": prompt,
            "temperature": temperature, "max_tokens": max_tokens,
        }, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    def get(self, model: str, prompt: str, **kwargs) -> Optional[Any]:
        key = self._make_key(model, prompt, **kwargs)
        entry = self._cache.get(key)
        if entry is None:
            return None
        ts, data = entry
        if time.time() - ts > self.ttl:
            del self._cache[key]
            return None
        # Move to end (most recently used)
        self._cache.move_to_end(key)
        log.debug(f"[Cache] HIT: {key[:12]}...")
        return data

    def put(self, model: str, prompt: str, data: Any, **kwargs):
        key = self._make_key(model, prompt, **kwargs)
        self._cache[key] = (time.time(), data)
        self._cache.move_to_end(key)
        # Evict oldest if over capacity
        while len(self._cache) > self.max_size:
            self._cache.popitem(last=False)

    def clear(self):
        self._cache.clear()

    def stats(self) -> dict:
        now = time.time()
        valid = sum(1 for ts, _ in self._cache.values() if now - ts <= self.ttl)
        return {"size": len(self._cache), "valid": valid, "max_size": self.max_size, "ttl": self.ttl}

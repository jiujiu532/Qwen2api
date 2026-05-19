"""
image_proxy.py -- 图片代理服务
下载上游图片到内存缓存，通过本地 URL 分发，避免暴露上游 CDN 地址。
"""

import hashlib
import time
import logging
from typing import Optional

log = logging.getLogger("qwen2api.image_proxy")

# 内存缓存：{image_id: {"data": bytes, "content_type": str, "created": float}}
_cache: dict[str, dict] = {}
_MAX_CACHE_SIZE = 200  # 最多缓存 200 张图片
_CACHE_TTL = 3600  # 1 小时过期


def generate_image_id(url: str) -> str:
    """根据 URL 生成唯一 ID"""
    return hashlib.md5(url.encode()).hexdigest()[:16]


async def download_and_cache(url: str) -> Optional[str]:
    """下载图片并缓存，返回 image_id。失败返回 None。"""
    import httpx

    image_id = generate_image_id(url)

    # 已缓存则直接返回
    if image_id in _cache:
        return image_id

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                log.warning(f"[ImageProxy] 下载失败: {url} -> {resp.status_code}")
                return None
            content_type = resp.headers.get("content-type", "image/png")
            data = resp.content

        # 清理过期缓存
        _cleanup()

        _cache[image_id] = {
            "data": data,
            "content_type": content_type,
            "created": time.time(),
        }
        log.info(f"[ImageProxy] 已缓存: {image_id} ({len(data)} bytes)")
        return image_id
    except Exception as e:
        log.warning(f"[ImageProxy] 下载异常: {url} -> {e}")
        return None


def get_cached_image(image_id: str) -> Optional[dict]:
    """获取缓存的图片数据。返回 {"data": bytes, "content_type": str} 或 None。"""
    entry = _cache.get(image_id)
    if not entry:
        return None
    # 检查过期
    if time.time() - entry["created"] > _CACHE_TTL:
        del _cache[image_id]
        return None
    return entry


def _cleanup():
    """清理过期和超量缓存"""
    now = time.time()
    expired = [k for k, v in _cache.items() if now - v["created"] > _CACHE_TTL]
    for k in expired:
        del _cache[k]
    # 超量时删除最旧的
    while len(_cache) >= _MAX_CACHE_SIZE:
        oldest = min(_cache, key=lambda k: _cache[k]["created"])
        del _cache[oldest]


async def proxy_image_urls(text: str, app_url: str) -> str:
    """将文本中的上游图片 URL 替换为本地代理 URL。
    
    只处理 markdown 图片格式: ![alt](url)
    """
    import re

    if not app_url:
        return text  # 未配置 app_url，不做代理

    app_url = app_url.rstrip("/")

    async def replace_url(match):
        alt = match.group(1)
        url = match.group(2)
        image_id = await download_and_cache(url)
        if image_id:
            return f"![{alt}]({app_url}/proxy/image/{image_id})"
        return match.group(0)  # 下载失败，保留原 URL

    # 找到所有 markdown 图片
    pattern = re.compile(r'!\[([^\]]*)\]\((https?://[^\s\)]+)\)')
    matches = list(pattern.finditer(text))

    if not matches:
        return text

    # 逐个替换（需要 await）
    result = text
    for m in reversed(matches):  # 从后往前替换避免偏移
        alt = m.group(1)
        url = m.group(2)
        image_id = await download_and_cache(url)
        if image_id:
            new_str = f"![{alt}]({app_url}/proxy/image/{image_id})"
            result = result[:m.start()] + new_str + result[m.end():]

    return result

"""
图片生成接口 — 兼容 OpenAI /v1/images/generations 规范。

底层通过千问网页当前真实的“生成图像”模式触发，而不是写死 wanx 模型名。
页面实测结果显示：UI 仍显示 `Qwen3.6-Plus`，并通过“生成图像”模式完成图片生成。
"""
import re
import time
import asyncio
import logging
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from backend.services.qwen_client import QwenClient
from backend.services.token_calc import count_tokens

log = logging.getLogger("qwen2api.images")
router = APIRouter()

# 默认图片生成模型：网页实测仍显示为 Qwen3.6-Plus
DEFAULT_IMAGE_MODEL = "qwen3.6-plus"

# 受支持的图片模型别名 -> 网页真实可用的基础模型
IMAGE_MODEL_MAP = {
    "dall-e-3": "qwen3.6-plus",
    "dall-e-2": "qwen3.6-plus",
    "qwen-image": "qwen3.6-plus",
    "qwen-image-plus": "qwen3.6-plus",
    "qwen-image-turbo": "qwen3.6-plus",
    "qwen3.6-plus": "qwen3.6-plus",
}


def _extract_image_urls(text: str) -> list[str]:
    """从模型输出中提取图片 URL（支持 Markdown、JSON 字段、裸 URL 三种格式）"""
    urls: list[str] = []

    # 1. Markdown 图片语法: ![...](url)
    for u in re.findall(r'!\[.*?\]\((https?://[^\s\)]+)\)', text):
        urls.append(u.rstrip(").,;"))

    # 2. JSON 字段: "url":"...", "image":"...", "src":"..."
    if not urls:
        for u in re.findall(r'"(?:url|image|src|imageUrl|image_url)"\s*:\s*"(https?://[^"]+)"', text):
            urls.append(u)

    # 3. 裸 URL（以常见图片扩展名结尾，或来自已知 CDN）
    if not urls:
        cdn_pattern = r'https?://(?:cdn\.qwenlm\.ai|wanx\.alicdn\.com|img\.alicdn\.com|[^\s"<>]+\.(?:jpg|jpeg|png|webp|gif))[^\s"<>]*'
        for u in re.findall(cdn_pattern, text, re.IGNORECASE):
            urls.append(u.rstrip(".,;)\"'>"))

    # 去重并保留顺序
    seen: set[str] = set()
    result: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            result.append(u)
    return result


def _resolve_image_model(requested: str | None) -> str:
    if not requested:
        return DEFAULT_IMAGE_MODEL
    return IMAGE_MODEL_MAP.get(requested, DEFAULT_IMAGE_MODEL)


def _get_token(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return request.headers.get("x-api-key", "").strip()


@router.post("/v1/images/generations")
@router.post("/images/generations")
async def create_image(request: Request):
    """
    OpenAI 兼容的图片生成接口。

    请求体示例:
    ```json
    {
      "prompt": "一只赛博朋克风格的猫",
      "model": "dall-e-3",
      "n": 1,
      "size": "1024x1024",
      "response_format": "url"
    }
    ```
    """
    from backend.core.config import API_KEYS, settings
    client: QwenClient = request.app.state.qwen_client

    # 鉴权
    token = _get_token(request)
    if API_KEYS:
        if token != settings.ADMIN_KEY and token not in API_KEYS:
            raise HTTPException(status_code=401, detail="Invalid API Key")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    prompt: str = body.get("prompt", "").strip()
    if not prompt:
        raise HTTPException(400, "prompt is required")

    n: int = min(max(int(body.get("n", 1)), 1), 4)  # 最多 4 张
    model = _resolve_image_model(body.get("model"))
    size: str = body.get("size", "1024x1024")
    size_to_ratio: dict[str, str] = {
        "1024x1024": "1:1",
        "1024x576":  "16:9",
        "576x1024":  "9:16",
        "1024x768":  "4:3",
        "768x1024":  "3:4",
    }
    aspect_ratio = size_to_ratio.get(size, "1:1")

    log.info(f"[T2I] model={model}, n={n}, size={size}({aspect_ratio}), prompt={prompt[:120]!r}")
    t0 = time.time()

    try:
        # 收集错误信息用于前端展示
        error_messages: list[str] = []

        # 单次生成辅助函数
        async def _generate_one(label: str) -> list[str]:
            """单次生成，返回提取到的 URL 列表"""
            try:
                answer_text, acc, chat_id = await client.image_generate_with_retry(
                    model, prompt, aspect_ratio=aspect_ratio
                )
                asyncio.create_task(client.delete_chat(acc.token, chat_id))
                urls = _extract_image_urls(answer_text)
                log.info(f"[T2I] {label}: 提取到 {len(urls)} 张 URL")
                return urls
            except Exception as e:
                err_str = str(e)
                log.warning(f"[T2I] {label} failed: {err_str}")
                # 提取用户可读的错误信息
                if any(kw in err_str.lower() for kw in ("ratelimit", "rate_limit", "daily", "usage limit", "使用上限")):
                    error_messages.append("账号达到每日使用上限")
                elif "no available accounts" in err_str.lower():
                    error_messages.append("所有账号均不可用（限流/冷却中）")
                elif any(kw in err_str.lower() for kw in ("unauthorized", "auth", "token")):
                    error_messages.append("账号认证失败")
                elif any(kw in err_str.lower() for kw in ("banned", "封禁")):
                    error_messages.append("账号已被封禁")
                else:
                    error_messages.append(f"生成失败: {err_str[:100]}")
                return []

        collected_urls: list[str] = []
        max_attempts = n * 3  # 最多尝试 3n 次，确保能凑满 n 张
        attempt_count = 0

        # 并发批次执行，直到凑满 n 张或超过最大重试次数
        while len(collected_urls) < n and attempt_count < max_attempts:
            remaining = n - len(collected_urls)
            batch = min(remaining, n)
            tasks = [_generate_one(f"attempt#{attempt_count + i}") for i in range(batch)]
            batch_results = await asyncio.gather(*tasks)
            for url_list in batch_results:
                collected_urls.extend(url_list)
            attempt_count += batch
            log.info(f"[T2I] 已收集 {len(collected_urls)}/{n} 张，已用 {attempt_count}/{max_attempts} 次尝试")
            if len(collected_urls) >= n:
                break

        log.info(f"[T2I] 最终收集到 {len(collected_urls)} 张图片 URL")

        if not collected_urls:
            # 对错误去重并生成可读的错误信息
            unique_errors = list(dict.fromkeys(error_messages))  # 保留顺序去重
            is_exhausted = any("使用上限" in e or "不可用" in e for e in unique_errors)
            if unique_errors:
                detail = "图片生成失败: " + "; ".join(unique_errors)
            else:
                detail = "图片生成失败: 未能从模型响应中提取到图片 URL，请稍后重试"
            # 如果是全部账号限流/耗尽，异步触发应急补号
            if is_exhausted:
                pool = request.app.state.account_pool
                pool.trigger_emergency_replenish()
                detail += "。系统已触发应急补号，新账号注册完成后可重试"
            raise HTTPException(status_code=500, detail=detail)

        data = [{"url": url, "revised_prompt": prompt} for url in collected_urls[:n]]
        # 记录使用统计：每张图片计 1 次，prompt token 均摊，图片固定 1000 token
        try:
            um = request.app.state.usage_manager
            _prompt_toks = count_tokens(prompt)
            _duration = int((time.time() - t0) * 1000)
            for _ in range(len(collected_urls[:n])):
                asyncio.create_task(um.log("t2i", model, _prompt_toks, 1000, duration_ms=_duration))
        except Exception:
            pass
        return JSONResponse({"created": int(time.time()), "data": data})


    except HTTPException:
        raise
    except Exception as e:
        err_str = str(e)
        log.error(f"[T2I] 生成失败: {err_str}")
        # 转换为用户可读的中文错误
        err_lower = err_str.lower()
        if any(kw in err_lower for kw in ("ratelimit", "rate_limit", "daily", "usage limit", "使用上限")):
            detail = "图片生成失败: 所有账号已达到每日使用上限，请稍后再试"
        elif "no available accounts" in err_lower:
            detail = "图片生成失败: 所有账号均不可用（限流/冷却中），请稍后再试"
        elif any(kw in err_lower for kw in ("unauthorized", "auth")):
            detail = "图片生成失败: 账号认证异常，系统正在自动修复"
        else:
            detail = f"图片生成失败: {err_str[:200]}"
        raise HTTPException(status_code=500, detail=detail)

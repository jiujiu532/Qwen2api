"""
chat.py -- OpenAI Chat Completions 路由（薄路由层）
业务逻辑已提取到 backend/engine/completion.py
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
import asyncio as aio
import json
import logging
import uuid
import time
import re
from typing import Optional

from backend.services.qwen_client import QwenClient
from backend.services.token_calc import calculate_usage
from backend.services.prompt_builder import messages_to_prompt
from backend.core.config import resolve_model, resolve_model_thinking, settings, IMAGE_MODEL_DEFAULT
from backend.engine.completion import completions

log = logging.getLogger("qwen2api.chat")
router = APIRouter()

# 兼容性 re-export（anthropic.py / gemini.py 依赖这些）
from backend.engine.completion import (
    _stream_items_with_keepalive,
    _extract_blocked_tool_names,
    _has_recent_unchanged_read_result,
)


# ============================================================================
# T2I 辅助函数（暂留路由层，Phase 1 不动）
# ============================================================================

def _t2i_user_error(err_str: str) -> str:
    """将原始异常转为用户可读的中文错误信息"""
    err_lower = err_str.lower()
    if any(kw in err_lower for kw in ("ratelimit", "rate_limit", "daily", "usage limit", "使用上限")):
        return "图片生成失败: 所有账号已达到每日使用上限，请稍后再试"
    if "no available accounts" in err_lower:
        return "图片生成失败: 所有账号均不可用（限流/冷却中），请稍后再试"
    if any(kw in err_lower for kw in ("unauthorized", "auth")):
        return "图片生成失败: 账号认证异常，系统正在自动修复"
    return f"图片生成失败: {err_str[:200]}"


_T2I_PATTERN = re.compile(
    r'(生成图片|画(一|个|张)?图|draw|generate\s+image|create\s+image|make\s+image|图片生成|文生图|生成一张|画一张)',
    re.IGNORECASE
)
_T2V_PATTERN = re.compile(
    r'(生成视频|make\s+video|generate\s+video|create\s+video|视频生成|文生视频)',
    re.IGNORECASE
)


def _detect_media_intent(messages: list) -> str:
    """Return 't2i', 't2v', or 't2t' based on last user message."""
    for msg in reversed(messages):
        if not isinstance(msg, dict):
            continue
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, list):
                text = " ".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
            else:
                text = str(content)
            if _T2V_PATTERN.search(text):
                return "t2v"
            if _T2I_PATTERN.search(text):
                return "t2i"
            break
    return "t2t"


def _extract_last_user_text(messages: list) -> str:
    for msg in reversed(messages):
        if not isinstance(msg, dict):
            continue
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, list):
                return " ".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
            return str(content)
    return ""


def _extract_image_urls(text: str) -> list[str]:
    urls: list[str] = []
    for u in re.findall(r'!\[.*?\]\((https?://[^\s\)]+)\)', text):
        urls.append(u.rstrip(").,;"))
    if not urls:
        for u in re.findall(r'"(?:url|image|src|imageUrl|image_url)"\s*:\s*"(https?://[^"]+)"', text):
            urls.append(u)
    if not urls:
        cdn_pattern = r'https?://(?:wanx\.alicdn\.com|img\.alicdn\.com|[^\s"<>]+\.(?:jpg|jpeg|png|webp|gif))[^\s"<>]*'
        for u in re.findall(cdn_pattern, text, re.IGNORECASE):
            urls.append(u.rstrip(".,;)\"'>"))
    seen: set[str] = set()
    result: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            result.append(u)
    return result


# ============================================================================
# 主路由
# ============================================================================

@router.post("/completions")
@router.post("/chat/completions")
@router.post("/v1/chat/completions")
async def chat_completions(request: Request):
    app = request.app
    users_db = app.state.users_db
    client: QwenClient = app.state.qwen_client

    # 鉴权
    from backend.core.auth import verify_api_key
    token = verify_api_key(request)

    # 配额检查
    users = await users_db.get()
    user = next((u for u in users if u["id"] == token), None)
    if user and user.get("quota", 0) <= user.get("used_tokens", 0):
        raise HTTPException(status_code=402, detail="Quota Exceeded")

    # 解析请求
    try:
        req_data = await request.json()
    except Exception:
        raise HTTPException(400, {"error": {"message": "Invalid JSON body", "type": "invalid_request_error"}})

    model_name = req_data.get("model", "gpt-3.5-turbo")
    qwen_model = resolve_model(model_name)
    stream = req_data.get("stream", False)

    # 思考模式
    req_thinking = resolve_model_thinking(model_name)
    if "thinking" in req_data:
        req_thinking = bool(req_data["thinking"])
    elif "reasoning_effort" in req_data:
        effort = req_data["reasoning_effort"]
        if effort in ("high", "max"):
            req_thinking = True
        elif effort in ("low", "none", "off"):
            req_thinking = False

    # 构建 prompt
    prompt, tools = messages_to_prompt(req_data)
    history_messages = req_data.get("messages", [])
    log.info(f"[OAI] model={qwen_model}, stream={stream}, tools={[t.get('name') for t in tools]}, thinking={req_thinking}, prompt_len={len(prompt)}")

    # T2I 路由（暂留）
    media_intent = _detect_media_intent(history_messages)
    if media_intent == "t2v":
        log.warning("[OAI] t2v intent detected but not yet validated; falling back to t2t")
        media_intent = "t2t"

    if media_intent == "t2i":
        return await _handle_t2i(request, client, history_messages, model_name, stream)

    # 调用统一执行器
    result = await completions(
        client=client,
        model=qwen_model,
        prompt=prompt,
        tools=tools,
        stream=stream,
        thinking=req_thinking,
        history_messages=history_messages,
        model_name=model_name,
    )

    if isinstance(result, dict):
        # 非流式：记录使用统计 + 配额
        try:
            um = app.state.usage_manager
            usage = result.get("usage", {})
            aio.create_task(um.log("chat", model_name, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)))
        except Exception:
            pass
        # 更新用户配额
        try:
            users = await users_db.get()
            for u in users:
                if u["id"] == token:
                    u["used_tokens"] += result.get("usage", {}).get("total_tokens", 0)
                    break
            await users_db.save(users)
        except Exception:
            pass
        return JSONResponse(result)
    else:
        # 流式：包装为 StreamingResponse
        # 使用统计在流结束后由客户端侧处理（或后续优化）
        async def _wrap_stream():
            total_len = 0
            async for chunk in result:
                yield chunk
                total_len += len(chunk)
            # 流结束后记录统计
            try:
                um = app.state.usage_manager
                _u = calculate_usage(prompt, "x" * (total_len // 10))
                aio.create_task(um.log("chat", model_name, _u["prompt_tokens"], _u["completion_tokens"]))
            except Exception:
                pass
            # 更新配额
            try:
                users = await users_db.get()
                for u in users:
                    if u["id"] == token:
                        u["used_tokens"] += total_len + len(prompt)
                        break
                await users_db.save(users)
            except Exception:
                pass

        return StreamingResponse(
            _wrap_stream(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        )


# ============================================================================
# T2I 处理（暂留路由层）
# ============================================================================

async def _handle_t2i(request: Request, client: QwenClient, history_messages: list, model_name: str, stream: bool):
    """处理图片生成请求（T2I 路由）。"""
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())
    image_prompt = _extract_last_user_text(history_messages)
    log.info(f"[OAI-T2I] Routing to image generation, model={IMAGE_MODEL_DEFAULT}, prompt={image_prompt[:80]!r}")

    if stream:
        async def generate_image_stream():
            mk = lambda delta, finish=None: json.dumps({
                "id": completion_id, "object": "chat.completion.chunk",
                "created": created, "model": model_name,
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]
            }, ensure_ascii=False)
            try:
                answer_text, acc, chat_id = await client.image_generate_with_retry(IMAGE_MODEL_DEFAULT, image_prompt)
                client.account_pool.release(acc)
                aio.create_task(client.delete_chat(acc.token, chat_id))
                image_urls = _extract_image_urls(answer_text)
                content = "\n".join(f"![generated]({u})" for u in image_urls) if image_urls else answer_text
                yield f"data: {mk({'role': 'assistant'})}\n\n"
                yield f"data: {mk({'content': content})}\n\n"
                yield f"data: {mk({}, 'stop')}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as e:
                err_str = str(e)
                log.error(f"[OAI-T2I] 生成失败: {err_str}")
                user_msg = _t2i_user_error(err_str)
                yield f"data: {json.dumps({'error': {'message': user_msg, 'type': 'server_error'}}, ensure_ascii=False)}\n\n"
        return StreamingResponse(generate_image_stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    else:
        try:
            answer_text, acc, chat_id = await client.image_generate_with_retry(IMAGE_MODEL_DEFAULT, image_prompt)
            client.account_pool.release(acc)
            aio.create_task(client.delete_chat(acc.token, chat_id))
            image_urls = _extract_image_urls(answer_text)
            content = "\n".join(f"![generated]({u})" for u in image_urls) if image_urls else answer_text
            # 记录使用统计
            try:
                um = request.app.state.usage_manager
                _u = calculate_usage(image_prompt, content)
                aio.create_task(um.log("t2i", model_name, _u["prompt_tokens"], _u["completion_tokens"]))
            except Exception:
                pass
            return JSONResponse({
                "id": completion_id, "object": "chat.completion", "created": created, "model": model_name,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
                "images": image_urls,
                "usage": {"prompt_tokens": len(image_prompt), "completion_tokens": len(content),
                          "total_tokens": len(image_prompt) + len(content)}
            })
        except Exception as e:
            err_str = str(e)
            log.error(f"[OAI-T2I] 生成失败: {err_str}")
            user_msg = _t2i_user_error(err_str)
            raise HTTPException(status_code=500, detail={"error": {"message": user_msg, "type": "server_error"}})


# NOTE: /v1/images/generations 路由已移至 backend/api/images.py

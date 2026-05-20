"""
anthropic.py -- Claude/Anthropic 兼容 API（薄路由层）
格式转换 + 调用 completions_raw() + 格式化 Anthropic 响应。
"""

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
import asyncio as aio
import json
import logging
import uuid
import time

from backend.services.qwen_client import QwenClient
from backend.services.prompt_builder import messages_to_prompt
from backend.core.config import resolve_model, resolve_model_thinking
from backend.engine.completion import completions_raw

log = logging.getLogger("qwen2api.anthropic")
router = APIRouter()


# ============================================================================
# 格式转换函数
# ============================================================================

def _anthropic_tools_to_oai(tools: list) -> list:
    """将 Anthropic tool 定义格式转为 OpenAI tools 格式。"""
    oai = []
    for t in tools:
        oai.append({
            "type": "function",
            "function": {
                "name": t.get("name", ""),
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {}),
            }
        })
    return oai


def _convert_messages_to_oai(messages: list) -> list:
    """将 Anthropic messages 格式转为 OpenAI messages 格式。"""
    oai_msgs = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if isinstance(content, str):
            oai_msgs.append({"role": role, "content": content})
            continue

        if isinstance(content, list):
            text_parts = []
            tool_calls = []
            tool_results = []

            for block in content:
                btype = block.get("type", "")
                if btype == "text":
                    text_parts.append(block.get("text", ""))
                elif btype == "tool_use":
                    tool_calls.append({
                        "id": block.get("id", f"toolu_{uuid.uuid4().hex[:12]}"),
                        "type": "function",
                        "function": {
                            "name": block.get("name", ""),
                            "arguments": json.dumps(block.get("input", {}), ensure_ascii=False),
                        }
                    })
                elif btype == "tool_result":
                    inner = block.get("content", "")
                    if isinstance(inner, list):
                        inner = "\n".join(p.get("text", "") for p in inner if isinstance(p, dict))
                    tool_results.append({
                        "role": "tool",
                        "tool_call_id": block.get("tool_use_id", ""),
                        "name": "",
                        "content": str(inner),
                    })

            if tool_results:
                if text_parts:
                    oai_msgs.append({"role": role, "content": "\n".join(text_parts)})
                oai_msgs.extend(tool_results)
            elif tool_calls:
                oai_msgs.append({
                    "role": "assistant",
                    "content": " ".join(text_parts) or None,
                    "tool_calls": tool_calls,
                })
            else:
                oai_msgs.append({"role": role, "content": "\n".join(text_parts)})
    return oai_msgs


# ============================================================================
# 路由
# ============================================================================

@router.post("/anthropic/v1/messages")
@router.post("/v1/messages")
async def anthropic_messages(request: Request):
    """Anthropic /v1/messages 兼容端点，支持流式和工具调用。"""
    app = request.app
    client: QwenClient = app.state.qwen_client

    # 鉴权
    from backend.core.auth import verify_api_key
    verify_api_key(request)

    try:
        req = await request.json()
    except Exception:
        raise HTTPException(400, {"type": "invalid_request_error", "message": "Invalid JSON"})

    model_name = req.get("model", "claude-3-5-sonnet-latest")
    qwen_model = resolve_model(model_name)
    req_thinking = resolve_model_thinking(model_name)
    stream = req.get("stream", False)

    # 转换消息格式
    messages = _convert_messages_to_oai(req.get("messages", []))
    system_text = req.get("system", "")
    if system_text:
        messages.insert(0, {"role": "system", "content": system_text})

    # 工具转换
    raw_tools = req.get("tools", [])
    oai_tools = _anthropic_tools_to_oai(raw_tools)

    # 构建 prompt
    oai_req = {"messages": messages, "tools": oai_tools}
    prompt, tool_defs = messages_to_prompt(oai_req)

    completion_id = f"msg_{uuid.uuid4().hex[:24]}"
    log.info(f"[Anthropic] model={qwen_model} stream={stream} tools={[t['name'] for t in tool_defs]}")

    # 多模态文件上传（用原始 Anthropic messages 提取，因为转换后 image block 会丢失）
    uploaded_files = None
    from backend.services.file_uploader import extract_files_from_messages, upload_files_concurrent
    raw_messages = req.get("messages", [])
    # 将 Anthropic 格式的 image block 转为 OpenAI 格式以便 extract_files_from_messages 处理
    _oai_for_extract = []
    for msg in raw_messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, list):
            blocks = []
            for block in content:
                btype = block.get("type", "")
                if btype == "image":
                    # Anthropic: {"type":"image","source":{"type":"base64","media_type":"image/png","data":"..."}}
                    source = block.get("source", {})
                    if source.get("type") == "base64":
                        data_uri = f"data:{source.get('media_type','image/png')};base64,{source.get('data','')}"
                        blocks.append({"type": "image_url", "image_url": {"url": data_uri}})
                    elif source.get("type") == "url":
                        blocks.append({"type": "image_url", "image_url": {"url": source.get("url", "")}})
                elif btype == "text":
                    blocks.append(block)
            if blocks:
                _oai_for_extract.append({"role": role, "content": blocks})
        else:
            _oai_for_extract.append({"role": role, "content": content})
    try:
        file_data = await extract_files_from_messages(_oai_for_extract)
        if file_data:
            _acc = await client.account_pool.acquire_wait(timeout=30)
            if _acc:
                try:
                    uploaded = await upload_files_concurrent(_acc.token, file_data)
                    uploaded_files = [f.to_payload() for f in uploaded]
                finally:
                    client.account_pool.release(_acc)
    except Exception as e:
        log.warning(f"[Anthropic] multimodal upload failed: {e}")

    # 调用统一执行器
    result = await completions_raw(
        client=client,
        model=qwen_model,
        prompt=prompt,
        tools=tool_defs,
        thinking=req_thinking,
        history_messages=messages,
        files=uploaded_files,
    )

    # 记录使用统计
    try:
        _um = app.state.usage_manager
        aio.create_task(_um.log("chat", model_name, result.usage.get("prompt_tokens", 0), result.usage.get("completion_tokens", 0)))
    except Exception:
        pass

    # 格式化 Anthropic 响应
    has_tc = result.stop == "tool_use"
    if has_tc:
        tc_list = [b for b in result.tool_blocks if b["type"] == "tool_use"]
        content = [{"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc["input"]} for tc in tc_list]
        stop_reason = "tool_use"
    else:
        content = [{"type": "text", "text": result.answer_text}]
        stop_reason = "end_turn"

    response_body = {
        "id": completion_id,
        "type": "message",
        "role": "assistant",
        "model": model_name,
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": result.usage.get("prompt_tokens", 0),
            "output_tokens": result.usage.get("completion_tokens", 0),
        },
    }

    if stream:
        # 伪流式：一次性输出所有 Anthropic SSE 事件
        async def generate():
            # message_start
            yield f"event: message_start\ndata: {json.dumps({'type': 'message_start', 'message': {'id': completion_id, 'type': 'message', 'role': 'assistant', 'model': model_name, 'content': [], 'stop_reason': None, 'usage': {'input_tokens': result.usage.get('prompt_tokens', 0), 'output_tokens': 0}}}, ensure_ascii=False)}\n\n"
            yield "event: ping\ndata: {\"type\": \"ping\"}\n\n"

            if has_tc:
                # 先输出空 text block
                yield f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}})}\n\n"
                if result.answer_text:
                    yield f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': result.answer_text}}, ensure_ascii=False)}\n\n"
                yield f"event: content_block_stop\ndata: {{\"type\": \"content_block_stop\", \"index\": 0}}\n\n"
                # tool_use blocks
                tc_list = [b for b in result.tool_blocks if b["type"] == "tool_use"]
                for idx, tc in enumerate(tc_list):
                    tu_block = {"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc["input"]}
                    yield f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': idx+1, 'content_block': tu_block}, ensure_ascii=False)}\n\n"
                    yield f"event: content_block_stop\ndata: {{\"type\": \"content_block_stop\", \"index\": {idx+1}}}\n\n"
                yield f"event: message_delta\ndata: {json.dumps({'type': 'message_delta', 'delta': {'stop_reason': 'tool_use', 'stop_sequence': None}, 'usage': {'output_tokens': result.usage.get('completion_tokens', 0)}}, ensure_ascii=False)}\n\n"
            else:
                # text block
                yield f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}})}\n\n"
                if result.answer_text:
                    yield f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': result.answer_text}}, ensure_ascii=False)}\n\n"
                yield f"event: content_block_stop\ndata: {{\"type\": \"content_block_stop\", \"index\": 0}}\n\n"
                yield f"event: message_delta\ndata: {json.dumps({'type': 'message_delta', 'delta': {'stop_reason': 'end_turn', 'stop_sequence': None}, 'usage': {'output_tokens': result.usage.get('completion_tokens', 0)}}, ensure_ascii=False)}\n\n"

            yield "event: message_stop\ndata: {\"type\": \"message_stop\"}\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    else:
        return JSONResponse(response_body)

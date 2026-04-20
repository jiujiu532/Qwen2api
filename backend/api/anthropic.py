"""
anthropic.py — Claude/Anthropic 兼容 API
将 Anthropic /v1/messages 格式的请求转换为内部 Qwen 调用，输出 Anthropic 格式响应。
支持流式（text_delta SSE）和非流式，以及工具调用（tool_use 块）。
"""

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
import asyncio as aio
import json
import logging
import uuid
import time
from typing import Optional
from backend.core.account_pool import Account
from backend.services.qwen_client import QwenClient
from backend.services.prompt_builder import messages_to_prompt
from backend.services.tool_parser import parse_tool_calls, build_tool_blocks_from_native_chunks, inject_format_reminder, should_block_tool_call
from backend.core.config import resolve_model, settings

log = logging.getLogger("qwen2api.anthropic")
router = APIRouter()


def _anthropic_tools_to_oai(tools: list) -> list:
    """将 Anthropic tool 定义格式转为 OpenAI tools 格式（供 prompt_builder 使用）。"""
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
    """将 Anthropic messages 格式转为 OpenAI messages 格式供 prompt_builder 使用。"""
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
                    # assistant 调用工具
                    tool_calls.append({
                        "id": block.get("id", f"toolu_{uuid.uuid4().hex[:12]}"),
                        "type": "function",
                        "function": {
                            "name": block.get("name", ""),
                            "arguments": json.dumps(block.get("input", {}), ensure_ascii=False),
                        }
                    })
                elif btype == "tool_result":
                    # user 提交工具结果
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


@router.post("/anthropic/v1/messages")
@router.post("/v1/messages")
async def anthropic_messages(request: Request):
    """Anthropic /v1/messages 兼容端点，支持流式和工具调用。"""
    app = request.app
    client: QwenClient = app.state.qwen_client

    # 鉴权
    auth = request.headers.get("x-api-key", "") or request.headers.get("Authorization", "")[7:]
    if not auth:
        raise HTTPException(status_code=401, detail={"type": "authentication_error", "message": "Missing API key"})

    try:
        req = await request.json()
    except Exception:
        raise HTTPException(400, {"type": "invalid_request_error", "message": "Invalid JSON"})

    model_name = req.get("model", "claude-3-5-sonnet-latest")
    qwen_model = resolve_model(model_name)
    stream = req.get("stream", False)
    max_tokens = req.get("max_tokens", 4096)

    # 转换消息格式
    messages = _convert_messages_to_oai(req.get("messages", []))
    system_text = req.get("system", "")
    if system_text:
        messages.insert(0, {"role": "system", "content": system_text})

    # 工具转换
    raw_tools = req.get("tools", [])
    oai_tools = _anthropic_tools_to_oai(raw_tools)

    # 使用 OAI prompt_builder 构建 prompt
    oai_req = {"messages": messages, "tools": oai_tools}
    prompt, tool_defs = messages_to_prompt(oai_req)

    completion_id = f"msg_{uuid.uuid4().hex[:24]}"
    created = int(time.time())
    force_xml_mode = bool(tool_defs)

    log.info(f"[Anthropic] model={qwen_model} stream={stream} tools={[t['name'] for t in tool_defs]}")

    if stream:
        async def generate():
            current_prompt = prompt
            excluded = set()
            max_attempts = settings.TOOL_MAX_RETRIES if tool_defs else settings.MAX_RETRIES
            fxm = force_xml_mode

            # message_start
            yield f"event: message_start\ndata: {json.dumps({'type': 'message_start', 'message': {'id': completion_id, 'type': 'message', 'role': 'assistant', 'model': model_name, 'content': [], 'stop_reason': None, 'usage': {'input_tokens': 0, 'output_tokens': 0}}}, ensure_ascii=False)}\n\n"
            yield f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}})}\n\n"
            yield "event: ping\ndata: {\"type\": \"ping\"}\n\n"

            for attempt in range(max_attempts):
                try:
                    from backend.api.chat import _stream_items_with_keepalive
                    events = []
                    chat_id = None
                    acc = None

                    async for item in _stream_items_with_keepalive(client, qwen_model, current_prompt, has_custom_tools=bool(tool_defs), xml_mode=fxm, exclude_accounts=excluded):
                        if item["type"] == "keepalive":
                            yield ": keepalive\n\n"
                            continue
                        if item["type"] == "meta":
                            chat_id = item["chat_id"]
                            if isinstance(item["acc"], Account):
                                acc = item["acc"]
                            continue
                        if item["type"] == "event":
                            events.append(item["event"])

                    answer_text = ""
                    native_tc_chunks: dict = {}
                    for evt in events:
                        if evt["type"] != "delta":
                            continue
                        ph = evt.get("phase", "")
                        ct = evt.get("content", "")
                        if ph == "answer" and ct:
                            answer_text += ct
                        elif ph == "tool_call" and ct:
                            tc_id = evt.get("extra", {}).get("tool_call_id", "tc_0")
                            if tc_id not in native_tc_chunks:
                                native_tc_chunks[tc_id] = {"name": "", "args": ""}
                            try:
                                chunk = json.loads(ct)
                                if "name" in chunk:
                                    native_tc_chunks[tc_id]["name"] = chunk["name"]
                                if "arguments" in chunk:
                                    native_tc_chunks[tc_id]["args"] += chunk["arguments"]
                            except Exception:
                                native_tc_chunks[tc_id]["args"] += ct

                    tool_blocks, stop = build_tool_blocks_from_native_chunks(native_tc_chunks, tool_defs) if tool_defs else ([], "end_turn")
                    if not tool_blocks:
                        tool_blocks, stop = parse_tool_calls(answer_text, tool_defs)
                    has_tc = stop == "tool_use"

                    # NativeBlock detection
                    from backend.api.chat import _extract_blocked_tool_names
                    blocked = _extract_blocked_tool_names(answer_text)
                    if blocked and tool_defs and not has_tc and attempt < max_attempts - 1:
                        fxm = True
                        current_prompt = inject_format_reminder(current_prompt, blocked[0])
                        if acc:
                            client.account_pool.release(acc)
                            if chat_id:
                                aio.create_task(client.delete_chat(acc.token, chat_id))
                            excluded.add(acc.email)
                        await aio.sleep(0.15)
                        continue

                    if has_tc:
                        tc_list = [b for b in tool_blocks if b["type"] == "tool_use"]
                        for idx, tc in enumerate(tc_list):
                            yield f"event: content_block_stop\ndata: {{\"type\": \"content_block_stop\", \"index\": {idx}}}\n\n"
                            tu_block = {"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc["input"]}
                            yield f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': idx+1, 'content_block': tu_block}, ensure_ascii=False)}\n\n"
                            yield f"event: content_block_stop\ndata: {{\"type\": \"content_block_stop\", \"index\": {idx+1}}}\n\n"
                        yield f"event: message_delta\ndata: {json.dumps({'type': 'message_delta', 'delta': {'stop_reason': 'tool_use', 'stop_sequence': None}, 'usage': {'output_tokens': len(answer_text)}}, ensure_ascii=False)}\n\n"
                    else:
                        # stream text
                        if answer_text:
                            yield f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': answer_text}}, ensure_ascii=False)}\n\n"
                        yield f"event: content_block_stop\ndata: {{\"type\": \"content_block_stop\", \"index\": 0}}\n\n"
                        yield f"event: message_delta\ndata: {json.dumps({'type': 'message_delta', 'delta': {'stop_reason': 'end_turn', 'stop_sequence': None}, 'usage': {'output_tokens': len(answer_text)}}, ensure_ascii=False)}\n\n"

                    yield "event: message_stop\ndata: {\"type\": \"message_stop\"}\n\n"
                    # 记录使用统计
                    try:
                        from backend.services.token_calc import calculate_usage
                        _um = request.app.state.usage_manager
                        _u = calculate_usage(current_prompt, answer_text)
                        aio.create_task(_um.log("chat", model_name, _u["prompt_tokens"], _u["completion_tokens"]))
                    except Exception:
                        pass
                    if acc:
                        client.account_pool.release(acc)
                        if chat_id:
                            aio.create_task(client.delete_chat(acc.token, chat_id))
                    return

                except Exception as e:
                    if acc and acc.inflight > 0:
                        client.account_pool.release(acc)
                    log.error(f"[Anthropic-Stream] error: {e}")
                    yield f"event: error\ndata: {json.dumps({'type': 'error', 'error': {'type': 'api_error', 'message': str(e)}})}\n\n"
                    return

            yield "event: message_stop\ndata: {\"type\": \"message_stop\"}\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    else:
        # Non-streaming
        current_prompt = prompt
        excluded = set()
        fxm = force_xml_mode
        max_attempts = settings.TOOL_MAX_RETRIES if tool_defs else settings.MAX_RETRIES

        for attempt in range(max_attempts):
            try:
                events = []
                chat_id = None
                acc = None
                async for item in client.chat_stream_events_with_retry(qwen_model, current_prompt, has_custom_tools=bool(tool_defs), xml_mode=fxm, exclude_accounts=excluded):
                    if item["type"] == "meta":
                        chat_id = item["chat_id"]
                        acc = item["acc"]
                    elif item["type"] == "event":
                        events.append(item["event"])

                answer_text = ""
                native_tc_chunks: dict = {}
                for evt in events:
                    if evt["type"] != "delta":
                        continue
                    ph = evt.get("phase", "")
                    ct = evt.get("content", "")
                    if ph == "answer" and ct:
                        answer_text += ct
                    elif ph == "tool_call" and ct:
                        tc_id = evt.get("extra", {}).get("tool_call_id", "tc_0")
                        if tc_id not in native_tc_chunks:
                            native_tc_chunks[tc_id] = {"name": "", "args": ""}
                        try:
                            chunk = json.loads(ct)
                            if "name" in chunk:
                                native_tc_chunks[tc_id]["name"] = chunk["name"]
                            if "arguments" in chunk:
                                native_tc_chunks[tc_id]["args"] += chunk["arguments"]
                        except Exception:
                            native_tc_chunks[tc_id]["args"] += ct

                tool_blocks, stop = build_tool_blocks_from_native_chunks(native_tc_chunks, tool_defs) if tool_defs else ([], "end_turn")
                if not tool_blocks:
                    tool_blocks, stop = parse_tool_calls(answer_text, tool_defs)
                has_tc = stop == "tool_use"

                from backend.api.chat import _extract_blocked_tool_names
                blocked = _extract_blocked_tool_names(answer_text)
                if blocked and tool_defs and not has_tc and attempt < max_attempts - 1:
                    fxm = True
                    current_prompt = inject_format_reminder(current_prompt, blocked[0])
                    if acc:
                        client.account_pool.release(acc)
                        if chat_id:
                            aio.create_task(client.delete_chat(acc.token, chat_id))
                        excluded.add(acc.email)
                    await aio.sleep(0.15)
                    continue

                if acc:
                    client.account_pool.release(acc)
                    if chat_id:
                        aio.create_task(client.delete_chat(acc.token, chat_id))

                if has_tc:
                    tc_list = [b for b in tool_blocks if b["type"] == "tool_use"]
                    content = [{"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc["input"]} for tc in tc_list]
                    stop_reason = "tool_use"
                else:
                    content = [{"type": "text", "text": answer_text}]
                    stop_reason = "end_turn"

                # 记录使用统计
                try:
                    from backend.services.token_calc import calculate_usage
                    _um = request.app.state.usage_manager
                    _u = calculate_usage(current_prompt, answer_text)
                    aio.create_task(_um.log("chat", model_name, _u["prompt_tokens"], _u["completion_tokens"]))
                except Exception:
                    pass
                return JSONResponse({
                    "id": completion_id,
                    "type": "message",
                    "role": "assistant",
                    "model": model_name,
                    "content": content,
                    "stop_reason": stop_reason,
                    "stop_sequence": None,
                    "usage": {"input_tokens": len(prompt)//4, "output_tokens": len(answer_text)//4},
                })

            except Exception as e:
                if acc and acc.inflight > 0:
                    client.account_pool.release(acc)
                if attempt == max_attempts - 1:
                    raise HTTPException(500, {"type": "api_error", "message": str(e)})
                await aio.sleep(1)

        raise HTTPException(500, {"type": "api_error", "message": "All retries exhausted"})

"""
responses.py — OpenAI Responses API 兼容端点
实现 POST /v1/responses（OpenAI 新版 Responses API，Codex/Agents 使用）。
支持工具调用（function_call）、流式（response.output_text.delta 事件）。
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
from backend.services.tool_parser import parse_tool_calls, build_tool_blocks_from_native_chunks, inject_format_reminder
from backend.core.config import resolve_model, settings

log = logging.getLogger("qwen2api.responses")
router = APIRouter()


def _responses_input_to_messages(input_data) -> list:
    """将 Responses API input 字段转为 OAI messages。

    Responses API input 可以包含：
    1. 普通消息：{"role": "user", "content": "..."}
    2. 直接输出项（无 role）：{"type": "function_call", "name": "...", "arguments": "..."}
    3. 直接工具结果（无 role）：{"type": "function_call_output", "call_id": "...", "output": "..."}
    """
    if isinstance(input_data, str):
        return [{"role": "user", "content": input_data}]
    if not isinstance(input_data, list):
        return []

    messages = []
    # 暂存连续的 assistant function_call 追加到一个 assistant 消息
    pending_tool_calls: list = []

    def _flush_tool_calls():
        if pending_tool_calls:
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": list(pending_tool_calls),
            })
            pending_tool_calls.clear()

    for item in input_data:
        if isinstance(item, str):
            _flush_tool_calls()
            messages.append({"role": "user", "content": item})
            continue

        item_type = item.get("type", "")
        role = item.get("role", "")

        # ── 平底 function_call 项（来自上轮 Responses API 输出）──────────
        if item_type == "function_call":
            pending_tool_calls.append({
                "id": item.get("id", item.get("call_id", f"call_{uuid.uuid4().hex[:12]}")),
                "type": "function",
                "function": {
                    "name": item.get("name", ""),
                    "arguments": item.get("arguments", "{}"),
                }
            })
            continue

        # ── 平底 function_call_output 项（工具执行结果）──────────────────
        if item_type == "function_call_output":
            _flush_tool_calls()
            messages.append({
                "role": "tool",
                "tool_call_id": item.get("call_id", item.get("id", "")),
                "name": item.get("name", ""),
                "content": str(item.get("output", item.get("content", ""))),
            })
            continue

        # ── 普通消息（有 role 字段）──────────────────────────────────────
        _flush_tool_calls()
        if not role:
            role = "user"
        content = item.get("content", "")

        if isinstance(content, list):
            texts = []
            tool_calls = []
            tool_results = []
            for block in content:
                btype = block.get("type", "")
                if btype in ("text", "input_text", "output_text"):
                    texts.append(block.get("text", ""))
                elif btype in ("tool_use", "function_call"):
                    tool_calls.append({
                        "id": block.get("id", block.get("call_id", f"call_{uuid.uuid4().hex[:12]}")),
                        "type": "function",
                        "function": {
                            "name": block.get("name", ""),
                            "arguments": block.get("arguments", json.dumps(block.get("input", {})))
                        }
                    })
                elif btype in ("tool_result", "function_call_output"):
                    tool_results.append({
                        "role": "tool",
                        "tool_call_id": block.get("call_id", block.get("tool_use_id", "")),
                        "name": block.get("name", ""),
                        "content": str(block.get("output", block.get("content", ""))),
                    })

            if tool_results:
                messages.extend(tool_results)
            elif tool_calls:
                messages.append({
                    "role": "assistant",
                    "content": " ".join(texts) or None,
                    "tool_calls": tool_calls,
                })
            else:
                messages.append({"role": role, "content": "\n".join(texts)})
        else:
            messages.append({"role": role, "content": str(content)})

    _flush_tool_calls()
    return messages


def _oai_tools_passthrough(tools: list) -> list:
    """Responses API tools 转为 Chat Completions 嵌套格式供 prompt_builder 使用。

    Responses API 发送平底格式:
        {"type": "function", "name": "...", "description": "...", "parameters": {...}}
    Chat Completions 居嵌格式（prompt_builder 所需）:
        {"type": "function", "function": {"name": "...", "description": "...", "parameters": {...}}}
    """
    result = []
    for t in tools:
        ttype = t.get("type", "")
        if ttype == "function":
            if "function" in t:
                result.append(t)  # 已经是嵌套格式
            else:
                # Responses API 平底格式 → 转换为嵌套格式
                result.append({
                    "type": "function",
                    "function": {
                        "name": t.get("name", ""),
                        "description": t.get("description", ""),
                        "parameters": t.get("parameters", t.get("input_schema", {})),
                    }
                })
        elif "name" in t:
            result.append({"type": "function", "function": {
                "name": t.get("name", ""),
                "description": t.get("description", ""),
                "parameters": t.get("parameters", t.get("input_schema", {})),
            }})
    return result


@router.post("/v1/responses")
async def openai_responses(request: Request):
    """OpenAI Responses API 兼容端点，支持工具调用和流式输出。"""
    app = request.app
    client: QwenClient = app.state.qwen_client

    auth = request.headers.get("Authorization", "")
    token = auth[7:].strip() if auth.startswith("Bearer ") else auth
    if not token:
        token = request.headers.get("x-api-key", "")

    try:
        req = await request.json()
    except Exception:
        raise HTTPException(400, {"error": {"message": "Invalid JSON", "type": "invalid_request_error"}})

    model_name = req.get("model", "gpt-4o")
    qwen_model = resolve_model(model_name)
    stream = req.get("stream", False)

    # Build messages
    messages = _responses_input_to_messages(req.get("input", []))

    # System instruction
    instructions = req.get("instructions", "")
    if instructions:
        messages.insert(0, {"role": "system", "content": instructions})

    # Tools
    raw_tools = req.get("tools", [])
    oai_tools = _oai_tools_passthrough(raw_tools)

    oai_req = {"messages": messages, "tools": oai_tools}
    prompt, tool_defs = messages_to_prompt(oai_req)
    force_xml_mode = bool(tool_defs)

    response_id = f"resp_{uuid.uuid4().hex[:24]}"
    created = int(time.time())

    log.info(f"[Responses] model={qwen_model} stream={stream} tools={[t['name'] for t in tool_defs]}")

    async def _run():
        current_prompt = prompt
        excluded = set()
        fxm = force_xml_mode
        max_attempts = settings.TOOL_MAX_RETRIES if tool_defs else settings.MAX_RETRIES

        for attempt in range(max_attempts):
            events = []
            chat_id = None
            acc = None
            try:
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

                from backend.api.v1_chat import _extract_blocked_tool_names
                blocked = _extract_blocked_tool_names(answer_text)
                if blocked and tool_defs and stop != "tool_use" and attempt < max_attempts - 1:
                    fxm = True
                    current_prompt = inject_format_reminder(current_prompt, blocked[0])
                    if acc:
                        client.account_pool.release(acc)
                        if chat_id:
                            aio.create_task(client.delete_chat(acc.token, chat_id))
                        excluded.add(acc.email)
                    await aio.sleep(0.15)
                    continue

                return answer_text, tool_blocks, stop, acc, chat_id

            except Exception as e:
                if acc and acc.inflight > 0:
                    client.account_pool.release(acc)
                if attempt == max_attempts - 1:
                    raise
                await aio.sleep(1)

        return "", [], "end_turn", None, None

    if stream:
        async def generate():
            try:
                resp_id = response_id
                msg_id = f"msg_{uuid.uuid4().hex[:24]}"

                # 1. response.created
                yield f"data: {json.dumps({'type': 'response.created', 'response': {'id': resp_id, 'object': 'response', 'created_at': created, 'status': 'in_progress', 'model': model_name, 'output': []}}, ensure_ascii=False)}\n\n"

                answer_text, tool_blocks, stop, acc, chat_id = await _run()
                has_tc = stop == "tool_use"

                if has_tc:
                    tc_list = [b for b in tool_blocks if b["type"] == "tool_use"]
                    output_items = []
                    for idx, tc in enumerate(tc_list):
                        call_id = f"call_{uuid.uuid4().hex[:20]}"
                        fc_id = f"fc_{uuid.uuid4().hex[:20]}"
                        args_str = json.dumps(tc["input"], ensure_ascii=False)
                        item = {"type": "function_call", "id": fc_id, "call_id": call_id, "name": tc["name"], "arguments": args_str, "status": "completed"}
                        output_items.append(item)
                        yield f"data: {json.dumps({'type': 'response.output_item.added', 'output_index': idx, 'item': {**item, 'arguments': ''}}, ensure_ascii=False)}\n\n"
                        yield f"data: {json.dumps({'type': 'response.function_call_arguments.delta', 'item_id': fc_id, 'output_index': idx, 'delta': args_str}, ensure_ascii=False)}\n\n"
                        yield f"data: {json.dumps({'type': 'response.function_call_arguments.done', 'item_id': fc_id, 'output_index': idx, 'arguments': args_str}, ensure_ascii=False)}\n\n"
                        yield f"data: {json.dumps({'type': 'response.output_item.done', 'output_index': idx, 'item': item}, ensure_ascii=False)}\n\n"
                else:
                    # text message
                    text_item = {"type": "message", "id": msg_id, "status": "in_progress", "role": "assistant", "content": []}
                    yield f"data: {json.dumps({'type': 'response.output_item.added', 'output_index': 0, 'item': text_item}, ensure_ascii=False)}\n\n"
                    yield f"data: {json.dumps({'type': 'response.content_part.added', 'item_id': msg_id, 'output_index': 0, 'content_index': 0, 'part': {'type': 'output_text', 'text': ''}}, ensure_ascii=False)}\n\n"
                    if answer_text:
                        yield f"data: {json.dumps({'type': 'response.output_text.delta', 'item_id': msg_id, 'output_index': 0, 'content_index': 0, 'delta': answer_text}, ensure_ascii=False)}\n\n"
                    yield f"data: {json.dumps({'type': 'response.output_text.done', 'item_id': msg_id, 'output_index': 0, 'content_index': 0, 'text': answer_text}, ensure_ascii=False)}\n\n"
                    done_item = {"type": "message", "id": msg_id, "status": "completed", "role": "assistant", "content": [{"type": "output_text", "text": answer_text, "annotations": []}]}
                    yield f"data: {json.dumps({'type': 'response.content_part.done', 'item_id': msg_id, 'output_index': 0, 'content_index': 0, 'part': {'type': 'output_text', 'text': answer_text}}, ensure_ascii=False)}\n\n"
                    yield f"data: {json.dumps({'type': 'response.output_item.done', 'output_index': 0, 'item': done_item}, ensure_ascii=False)}\n\n"
                    output_items = [done_item]

                # response.completed
                usage = {"input_tokens": len(prompt)//4, "output_tokens": len(answer_text)//4, "total_tokens": (len(prompt)+len(answer_text))//4}
                yield f"data: {json.dumps({'type': 'response.completed', 'response': {'id': resp_id, 'object': 'response', 'created_at': created, 'status': 'completed', 'model': model_name, 'output': output_items, 'usage': usage}}, ensure_ascii=False)}\n\n"

                # 记录使用统计
                try:
                    from backend.services.token_calc import calculate_usage
                    _um = request.app.state.usage_manager
                    _u = calculate_usage(prompt, answer_text)
                    aio.create_task(_um.log("chat", model_name, _u["prompt_tokens"], _u["completion_tokens"]))
                except Exception:
                    pass
                if acc:
                    client.account_pool.release(acc)
                    if chat_id:
                        aio.create_task(client.delete_chat(acc.token, chat_id))

            except Exception as e:
                log.error(f"[Responses-Stream] error: {e}")
                yield f"data: {json.dumps({'type': 'error', 'error': {'message': str(e)}})}\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    else:
        answer_text, tool_blocks, stop, acc, chat_id = await _run()
        # 记录使用统计
        try:
            from backend.services.token_calc import calculate_usage
            _um = request.app.state.usage_manager
            _u = calculate_usage(prompt, answer_text)
            aio.create_task(_um.log("chat", model_name, _u["prompt_tokens"], _u["completion_tokens"]))
        except Exception:
            pass
        if acc:
            client.account_pool.release(acc)
            if chat_id:
                aio.create_task(client.delete_chat(acc.token, chat_id))

        has_tc = stop == "tool_use"
        if has_tc:
            tc_list = [b for b in tool_blocks if b["type"] == "tool_use"]
            output = [{
                "type": "function_call",
                "id": f"call_{uuid.uuid4().hex[:20]}",
                "call_id": f"call_{uuid.uuid4().hex[:20]}",
                "name": tc["name"],
                "arguments": json.dumps(tc["input"], ensure_ascii=False),
            } for tc in tc_list]
            finish = "tool_calls"
        else:
            output = [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": answer_text}]}]
            finish = "stop"

        return JSONResponse({
            "id": response_id,
            "object": "response",
            "created_at": created,
            "model": model_name,
            "status": "completed",
            "output": output,
            "usage": {
                "input_tokens": len(prompt) // 4,
                "output_tokens": len(answer_text) // 4,
                "total_tokens": (len(prompt) + len(answer_text)) // 4,
            }
        })

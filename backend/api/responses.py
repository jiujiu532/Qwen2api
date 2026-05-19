"""
responses.py -- OpenAI Responses API 兼容端点（薄路由层）
格式转换 + 调用 completions_raw() + 格式化 Responses API 响应。
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

log = logging.getLogger("qwen2api.responses")
router = APIRouter()


# ============================================================================
# 格式转换函数
# ============================================================================

def _responses_input_to_messages(input_data) -> list:
    """将 Responses API input 字段转为 OAI messages。"""
    if isinstance(input_data, str):
        return [{"role": "user", "content": input_data}]
    if not isinstance(input_data, list):
        return []

    messages = []
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

        if item_type == "function_call_output":
            _flush_tool_calls()
            messages.append({
                "role": "tool",
                "tool_call_id": item.get("call_id", item.get("id", "")),
                "name": item.get("name", ""),
                "content": str(item.get("output", item.get("content", ""))),
            })
            continue

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
                messages.append({"role": "assistant", "content": " ".join(texts) or None, "tool_calls": tool_calls})
            else:
                messages.append({"role": role, "content": "\n".join(texts)})
        else:
            messages.append({"role": role, "content": str(content)})

    _flush_tool_calls()
    return messages


def _oai_tools_passthrough(tools: list) -> list:
    """Responses API tools 转为 Chat Completions 嵌套格式。"""
    result = []
    for t in tools:
        ttype = t.get("type", "")
        if ttype == "function":
            if "function" in t:
                result.append(t)
            else:
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


# ============================================================================
# 路由
# ============================================================================

@router.post("/v1/responses")
async def openai_responses(request: Request):
    """OpenAI Responses API 兼容端点。"""
    app = request.app
    client: QwenClient = app.state.qwen_client

    # 鉴权
    from backend.core.auth import verify_api_key
    verify_api_key(request)

    try:
        req = await request.json()
    except Exception:
        raise HTTPException(400, {"error": {"message": "Invalid JSON", "type": "invalid_request_error"}})

    model_name = req.get("model", "gpt-4o")
    qwen_model = resolve_model(model_name)
    req_thinking = resolve_model_thinking(model_name)
    stream = req.get("stream", False)

    # 构建 messages
    messages = _responses_input_to_messages(req.get("input", []))
    instructions = req.get("instructions", "")
    if instructions:
        messages.insert(0, {"role": "system", "content": instructions})

    # 工具
    raw_tools = req.get("tools", [])
    oai_tools = _oai_tools_passthrough(raw_tools)

    oai_req = {"messages": messages, "tools": oai_tools}
    prompt, tool_defs = messages_to_prompt(oai_req)

    response_id = f"resp_{uuid.uuid4().hex[:24]}"
    created = int(time.time())
    log.info(f"[Responses] model={qwen_model} stream={stream} tools={[t['name'] for t in tool_defs]}")

    # 调用统一执行器
    result = await completions_raw(
        client=client,
        model=qwen_model,
        prompt=prompt,
        tools=tool_defs,
        thinking=req_thinking,
        history_messages=messages,
    )

    # 记录使用统计
    try:
        _um = app.state.usage_manager
        aio.create_task(_um.log("chat", model_name, result.usage.get("prompt_tokens", 0), result.usage.get("completion_tokens", 0)))
    except Exception:
        pass

    # 格式化响应
    has_tc = result.stop == "tool_use"
    usage = {
        "input_tokens": result.usage.get("prompt_tokens", 0),
        "output_tokens": result.usage.get("completion_tokens", 0),
        "total_tokens": result.usage.get("total_tokens", 0),
    }

    if has_tc:
        tc_list = [b for b in result.tool_blocks if b["type"] == "tool_use"]
        output = [{
            "type": "function_call",
            "id": f"fc_{uuid.uuid4().hex[:20]}",
            "call_id": tc["id"],
            "name": tc["name"],
            "arguments": json.dumps(tc["input"], ensure_ascii=False),
            "status": "completed",
        } for tc in tc_list]
    else:
        msg_id = f"msg_{uuid.uuid4().hex[:24]}"
        output = [{
            "type": "message",
            "id": msg_id,
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": result.answer_text, "annotations": []}],
        }]

    response_body = {
        "id": response_id,
        "object": "response",
        "created_at": created,
        "model": model_name,
        "status": "completed",
        "output": output,
        "usage": usage,
    }

    if stream:
        async def generate():
            # response.created
            yield f"data: {json.dumps({'type': 'response.created', 'response': {'id': response_id, 'object': 'response', 'created_at': created, 'status': 'in_progress', 'model': model_name, 'output': []}}, ensure_ascii=False)}\n\n"

            if has_tc:
                for idx, item in enumerate(output):
                    args_str = item["arguments"]
                    fc_id = item["id"]
                    yield f"data: {json.dumps({'type': 'response.output_item.added', 'output_index': idx, 'item': {**item, 'arguments': ''}}, ensure_ascii=False)}\n\n"
                    yield f"data: {json.dumps({'type': 'response.function_call_arguments.delta', 'item_id': fc_id, 'output_index': idx, 'delta': args_str}, ensure_ascii=False)}\n\n"
                    yield f"data: {json.dumps({'type': 'response.function_call_arguments.done', 'item_id': fc_id, 'output_index': idx, 'arguments': args_str}, ensure_ascii=False)}\n\n"
                    yield f"data: {json.dumps({'type': 'response.output_item.done', 'output_index': idx, 'item': item}, ensure_ascii=False)}\n\n"
            else:
                msg_item = output[0]
                msg_id = msg_item["id"]
                yield f"data: {json.dumps({'type': 'response.output_item.added', 'output_index': 0, 'item': {**msg_item, 'content': [], 'status': 'in_progress'}}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'response.content_part.added', 'item_id': msg_id, 'output_index': 0, 'content_index': 0, 'part': {'type': 'output_text', 'text': ''}}, ensure_ascii=False)}\n\n"
                if result.answer_text:
                    yield f"data: {json.dumps({'type': 'response.output_text.delta', 'item_id': msg_id, 'output_index': 0, 'content_index': 0, 'delta': result.answer_text}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'response.output_text.done', 'item_id': msg_id, 'output_index': 0, 'content_index': 0, 'text': result.answer_text}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'response.content_part.done', 'item_id': msg_id, 'output_index': 0, 'content_index': 0, 'part': {'type': 'output_text', 'text': result.answer_text}}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'response.output_item.done', 'output_index': 0, 'item': msg_item}, ensure_ascii=False)}\n\n"

            # response.completed
            yield f"data: {json.dumps({'type': 'response.completed', 'response': response_body}, ensure_ascii=False)}\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    else:
        return JSONResponse(response_body)

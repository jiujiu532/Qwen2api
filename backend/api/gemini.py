"""
gemini.py — Google Gemini 兼容 API
将 Gemini /v1beta/models/{model}:generateContent 格式转换为 Qwen 调用。
支持 functionDeclarations（工具）、流式、非流式。
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

log = logging.getLogger("qwen2api.gemini")
router = APIRouter()


def _gemini_contents_to_oai(contents: list, system_instruction: str = "") -> list:
    """将 Gemini contents 转为 OpenAI messages。"""
    oai = []
    if system_instruction:
        oai.append({"role": "system", "content": system_instruction})

    for item in contents:
        role = item.get("role", "user")
        oai_role = "assistant" if role == "model" else "user"
        parts = item.get("parts", [])
        tool_calls = []
        tool_results = []
        texts = []

        for part in parts:
            if "text" in part:
                texts.append(part["text"])
            elif "functionCall" in part:
                fc = part["functionCall"]
                tool_calls.append({
                    "id": f"toolu_{uuid.uuid4().hex[:12]}",
                    "type": "function",
                    "function": {
                        "name": fc.get("name", ""),
                        "arguments": json.dumps(fc.get("args", {}), ensure_ascii=False),
                    }
                })
            elif "functionResponse" in part:
                fr = part["functionResponse"]
                tool_results.append({
                    "role": "tool",
                    "tool_call_id": "",
                    "name": fr.get("name", ""),
                    "content": json.dumps(fr.get("response", {}), ensure_ascii=False),
                })

        if tool_results:
            oai.extend(tool_results)
        elif tool_calls:
            oai.append({
                "role": "assistant",
                "content": " ".join(texts) or None,
                "tool_calls": tool_calls,
            })
        else:
            oai.append({"role": oai_role, "content": "\n".join(texts)})

    return oai


def _gemini_tools_to_oai(tools: list) -> list:
    """将 Gemini tools (functionDeclarations) 转为 OAI tools。"""
    oai = []
    for t in tools:
        for fd in t.get("functionDeclarations", []):
            oai.append({
                "type": "function",
                "function": {
                    "name": fd.get("name", ""),
                    "description": fd.get("description", ""),
                    "parameters": fd.get("parameters", {}),
                }
            })
    return oai


def _build_gemini_response(model_name: str, answer_text: str, tool_blocks: list, stop: str) -> dict:
    """构建 Gemini generateContent 响应。"""
    if tool_blocks and stop == "tool_use":
        tc_list = [b for b in tool_blocks if b["type"] == "tool_use"]
        parts = [{"functionCall": {"name": tc["name"], "args": tc["input"]}} for tc in tc_list]
        finish = "STOP"
    else:
        parts = [{"text": answer_text}]
        finish = "STOP"

    return {
        "candidates": [{
            "content": {"role": "model", "parts": parts},
            "finishReason": finish,
            "index": 0,
        }],
        "usageMetadata": {
            "promptTokenCount": 0,
            "candidatesTokenCount": len(answer_text) // 4,
            "totalTokenCount": len(answer_text) // 4,
        },
        "modelVersion": model_name,
    }


@router.post("/v1beta/models/{model}:generateContent")
@router.post("/v1beta/models/{model}:streamGenerateContent")
@router.post("/v1/models/{model}:generateContent")
@router.post("/v1/models/{model}:streamGenerateContent")
async def gemini_generate(model: str, request: Request):
    """Google Gemini generateContent / streamGenerateContent 兼容端点。"""
    app = request.app
    client: QwenClient = app.state.qwen_client
    stream = "stream" in request.url.path or request.query_params.get("alt") == "sse"

    try:
        req = await request.json()
    except Exception:
        raise HTTPException(400, {"error": {"code": 400, "message": "Invalid JSON"}})

    # 模型名映射（gemini-2.5-pro → qwen3.6-plus）
    clean_model = model.split("/")[-1]
    qwen_model = resolve_model(clean_model)

    system_parts = req.get("systemInstruction", {}).get("parts", [])
    system_text = " ".join(p.get("text", "") for p in system_parts if "text" in p)

    contents = req.get("contents", [])
    oai_tools = _gemini_tools_to_oai(req.get("tools", []))
    messages = _gemini_contents_to_oai(contents, system_text)

    oai_req = {"messages": messages, "tools": oai_tools}
    prompt, tool_defs = messages_to_prompt(oai_req)
    force_xml_mode = bool(tool_defs)

    log.info(f"[Gemini] model={qwen_model} stream={stream} tools={[t['name'] for t in tool_defs]}")

    async def _run_inference():
        """Shared non-streaming logic. Returns (answer_text, tool_blocks, stop, acc, chat_id)."""
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
                answer_text, tool_blocks, stop, acc, chat_id = await _run_inference()
                resp = _build_gemini_response(clean_model, answer_text, tool_blocks, stop)
                yield f"data: {json.dumps(resp, ensure_ascii=False)}\n\n"
                # 记录使用统计
                try:
                    from backend.services.token_calc import calculate_usage
                    _um = request.app.state.usage_manager
                    _u = calculate_usage(prompt, answer_text)
                    aio.create_task(_um.log("chat", clean_model, _u["prompt_tokens"], _u["completion_tokens"]))
                except Exception:
                    pass
                if acc:
                    client.account_pool.release(acc)
                    if chat_id:
                        aio.create_task(client.delete_chat(acc.token, chat_id))
            except Exception as e:
                yield f"data: {json.dumps({'error': {'code': 500, 'message': str(e)}})}\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    else:
        answer_text, tool_blocks, stop, acc, chat_id = await _run_inference()
        # 记录使用统计
        try:
            from backend.services.token_calc import calculate_usage
            _um = request.app.state.usage_manager
            _u = calculate_usage(prompt, answer_text)
            aio.create_task(_um.log("chat", clean_model, _u["prompt_tokens"], _u["completion_tokens"]))
        except Exception:
            pass
        if acc:
            client.account_pool.release(acc)
            if chat_id:
                aio.create_task(client.delete_chat(acc.token, chat_id))
        return JSONResponse(_build_gemini_response(clean_model, answer_text, tool_blocks, stop))

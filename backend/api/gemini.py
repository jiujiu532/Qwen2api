"""
gemini.py -- Google Gemini 兼容 API（薄路由层）
格式转换 + 调用 completions_raw() + 格式化 Gemini 响应。
"""

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
import asyncio as aio
import json
import logging
import uuid

from backend.services.qwen_client import QwenClient
from backend.services.prompt_builder import messages_to_prompt
from backend.services.token_calc import calculate_usage
from backend.core.config import resolve_model, resolve_model_thinking
from backend.engine.completion import completions_raw

log = logging.getLogger("qwen2api.gemini")
router = APIRouter()


# ============================================================================
# 格式转换函数
# ============================================================================

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
    else:
        parts = [{"text": answer_text}]

    return {
        "candidates": [{
            "content": {"role": "model", "parts": parts},
            "finishReason": "STOP",
            "index": 0,
        }],
        "usageMetadata": {
            "promptTokenCount": 0,
            "candidatesTokenCount": len(answer_text) // 4,
            "totalTokenCount": len(answer_text) // 4,
        },
        "modelVersion": model_name,
    }


# ============================================================================
# 路由
# ============================================================================

@router.post("/v1beta/models/{model}:generateContent")
@router.post("/v1beta/models/{model}:streamGenerateContent")
@router.post("/v1/models/{model}:generateContent")
@router.post("/v1/models/{model}:streamGenerateContent")
async def gemini_generate(model: str, request: Request):
    """Google Gemini generateContent / streamGenerateContent 兼容端点。"""
    app = request.app
    client: QwenClient = app.state.qwen_client
    stream = "stream" in request.url.path or request.query_params.get("alt") == "sse"

    # 鉴权
    from backend.core.auth import verify_api_key
    verify_api_key(request)

    try:
        req = await request.json()
    except Exception:
        raise HTTPException(400, {"error": {"code": 400, "message": "Invalid JSON"}})

    # 模型名映射
    clean_model = model.split("/")[-1]
    qwen_model = resolve_model(clean_model)
    req_thinking = resolve_model_thinking(clean_model)

    # 解析请求
    system_parts = req.get("systemInstruction", {}).get("parts", [])
    system_text = " ".join(p.get("text", "") for p in system_parts if "text" in p)
    contents = req.get("contents", [])
    oai_tools = _gemini_tools_to_oai(req.get("tools", []))
    messages = _gemini_contents_to_oai(contents, system_text)

    # 构建 prompt
    oai_req = {"messages": messages, "tools": oai_tools}
    prompt, tool_defs = messages_to_prompt(oai_req)

    log.info(f"[Gemini] model={qwen_model} stream={stream} tools={[t['name'] for t in tool_defs]}")

    # 调用统一执行器
    result = await completions_raw(
        client=client,
        model=qwen_model,
        prompt=prompt,
        tools=tool_defs,
        thinking=req_thinking,
        history_messages=messages,
    )

    # 格式化 Gemini 响应
    resp = _build_gemini_response(clean_model, result.answer_text, result.tool_blocks, result.stop)

    # 记录使用统计
    try:
        _um = app.state.usage_manager
        aio.create_task(_um.log("chat", clean_model, result.usage.get("prompt_tokens", 0), result.usage.get("completion_tokens", 0)))
    except Exception:
        pass

    if stream:
        async def generate():
            yield f"data: {json.dumps(resp, ensure_ascii=False)}\n\n"
        return StreamingResponse(generate(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    else:
        return JSONResponse(resp)

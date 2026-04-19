"""
prompt_builder.py — 消息格式转换
将 OpenAI / Anthropic 格式的 messages 转换为 Qwen 可用的 prompt 字符串。
支持工具调用（通过 [TOOL_CALL] 括号格式注入，避免 Qwen 平台拦截 <tool_call> XML）。
"""

import json
from typing import Any


_TOOL_SYSTEM_PREFIX = """\
# Tool Calling Instructions
You have access to tools. Follow these rules STRICTLY:

**HOW TO CALL A TOOL** — Use ONLY this exact format:
[TOOL_CALL]
{"name": "tool_name", "arguments": {...}}
[/TOOL_CALL]

**WORKFLOW**:
1. If you need information from a tool to answer the question, call ONE tool.
2. Wait for the tool result (it will appear as a Human message with <tool_result>).
3. After receiving the tool result, USE THAT INFORMATION to write your final answer in plain text.
4. Do NOT call the same tool again if you already have a result from it.
5. Do NOT call multiple tools in one reply — one at a time only.

**CRITICAL**: If tool results are already present in the conversation history (shown as <tool_result>), you MUST write your final answer immediately. Do NOT call any more tools.

**STOP CALLING TOOLS WHEN**: The question can now be answered using the results you have received.

## Available Tools
"""


def _content_to_str(content: Any) -> str:
    """将各种 content 格式（str / list）统一转为文本。"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                t = part.get("type", "")
                if t == "text":
                    parts.append(part.get("text", ""))
                elif t == "tool_result":
                    inner = part.get("content", "")
                    if isinstance(inner, str):
                        parts.append(inner)
                    elif isinstance(inner, list):
                        for p in inner:
                            if isinstance(p, dict) and p.get("type") == "text":
                                parts.append(p.get("text", ""))
        return "\n".join(p for p in parts if p)
    return str(content)


def messages_to_prompt(req_data: dict) -> tuple[str, list[dict]]:
    """
    将请求中的 messages + tools 转换为单一 prompt 字符串。

    Returns:
        (prompt_str, tools_list)
    """
    messages: list[dict] = req_data.get("messages", [])
    raw_tools: list[dict] = req_data.get("tools", [])
    tool_defs: list[dict] = []

    # 提取工具定义（OpenAI 格式）
    for t in raw_tools:
        if t.get("type") == "function":
            func = t.get("function", {})
            tool_defs.append({
                "name": func.get("name", ""),
                "description": func.get("description", ""),
                "parameters": func.get("parameters", {}),
            })
        elif "name" in t:
            # Anthropic 格式（直接是 {name, description, input_schema}）
            tool_defs.append({
                "name": t.get("name", ""),
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", t.get("parameters", {})),
            })

    # 构建工具说明字符串
    tool_system_injection = ""
    if tool_defs:
        tool_list_str = json.dumps(tool_defs, ensure_ascii=False, indent=2)
        tool_system_injection = _TOOL_SYSTEM_PREFIX + tool_list_str + "\n"

    parts: list[str] = []

    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role", "user")

        # ── System 消息：合并工具说明 ──────────────────────────────────────
        if role == "system":
            sys_text = _content_to_str(msg.get("content", ""))
            if tool_system_injection:
                # 工具说明注入到系统提示词末尾
                combined = sys_text.rstrip() + "\n\n" + tool_system_injection if sys_text else tool_system_injection
                parts.append(f"System: {combined}")
                tool_system_injection = ""  # 已注入，不再重复
            else:
                parts.append(f"System: {sys_text}")
            continue

        # ── Assistant 消息（可能含 tool_calls）───────────────────────────
        if role == "assistant":
            tool_calls = msg.get("tool_calls", [])
            if tool_calls:
                tc_parts = []
                for tc in tool_calls:
                    func = tc.get("function", {})
                    name = func.get("name", "")
                    raw_args = func.get("arguments", "{}")
                    # 规范化为 dict
                    if isinstance(raw_args, str):
                        try:
                            args = json.loads(raw_args)
                        except (json.JSONDecodeError, ValueError):
                            args = {"raw": raw_args}
                    else:
                        args = raw_args or {}
                    tc_parts.append(
                        f'[TOOL_CALL]\n{{"name": {json.dumps(name)}, "arguments": {json.dumps(args, ensure_ascii=False)}}}\n[/TOOL_CALL]'
                    )
                text_content = _content_to_str(msg.get("content", ""))
                content_str = (text_content + "\n" if text_content else "") + "\n".join(tc_parts)
                parts.append(f"Assistant: {content_str}")
            else:
                content_str = _content_to_str(msg.get("content", ""))
                parts.append(f"Assistant: {content_str}")
            continue

        # ── Tool 结果消息 ───────────────────────────────────────────────
        if role == "tool":
            tool_call_id = msg.get("tool_call_id", "")
            name = msg.get("name", "")
            content_str = _content_to_str(msg.get("content", ""))
            # 格式化为 XML 工具结果，模型能识别这个格式
            result_xml = f'<tool_result id="{tool_call_id}">\n{content_str}\n</tool_result>'
            parts.append(f"Human: [Tool: {name}]\n{result_xml}")
            continue

        # ── User 消息 ───────────────────────────────────────────────────
        if role == "user":
            content_str = _content_to_str(msg.get("content", ""))
            parts.append(f"Human: {content_str}")
            continue

        # ── 其他角色 ────────────────────────────────────────────────────
        content_str = _content_to_str(msg.get("content", ""))
        parts.append(f"{role.capitalize()}: {content_str}")

    # 如果没有 system 消息但有工具，单独添加工具说明块
    if tool_system_injection:
        parts.insert(0, f"System: {tool_system_injection}")

    prompt = "\n\n".join(p for p in parts if p)
    if not prompt.rstrip().endswith("Assistant:"):
        prompt += "\n\nAssistant:"

    return prompt, tool_defs

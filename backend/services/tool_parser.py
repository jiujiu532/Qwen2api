"""
tool_parser.py — 工具调用解析
从模型输出中解析工具调用（[TOOL_CALL] 括号格式和原生 tool_call SSE 事件）。
"""

import json
import re
import uuid
import logging
from typing import Any

log = logging.getLogger("qwen2api.tool_parser")

# 匹配 [TOOL_CALL]...{...}...[/TOOL_CALL]
# 捕获 delimiters 之间的完整内容（不能用 {.*?} 因为 lazy match 停在第一个 } 导致嵌套 JSON 截断）
_TOOL_CALL_PATTERN = re.compile(
    r'\[TOOL_CALL\](.*?)\[/TOOL_CALL\]',
    re.DOTALL
)

# 兼容旧的 <tool_call> 格式（历史消息中可能存在）
_TOOL_CALL_PATTERN_LEGACY = re.compile(
    r'<tool_call>(.*?)</tool_call>',
    re.DOTALL
)


def parse_tool_calls(text: str, tools: list[dict]) -> tuple[list[dict], str]:
    """
    从模型输出文本中解析工具调用。

    Returns:
        (content_blocks, stop_reason)
        stop_reason: "tool_use" 如果有工具调用，否则 "end_turn"
    """
    if not tools or not text:
        return [], "end_turn"

    tool_names = {t.get("name", "") for t in tools}
    blocks: list[dict] = []

    # 优先匹配新格式 [TOOL_CALL]...{...}...[/TOOL_CALL]
    for pattern in (_TOOL_CALL_PATTERN, _TOOL_CALL_PATTERN_LEGACY):
        for match in pattern.finditer(text):
            try:
                raw = match.group(1).strip()
                data = json.loads(raw)
                name = data.get("name", "")
                inp = data.get("arguments", data.get("input", data.get("params", {})))

                if name and (name in tool_names or not tool_names):
                    blocks.append({
                        "type": "tool_use",
                        "id": f"toolu_{uuid.uuid4().hex[:12]}",
                        "name": name,
                        "input": inp if isinstance(inp, dict) else {},
                    })
            except (json.JSONDecodeError, ValueError) as e:
                log.debug(f"[ToolParser] JSON 解析失败: {e} | raw={match.group(1)[:80]}")
                continue
        if blocks:
            break  # 优先使用新格式的结果，找到就不再找旧格式

    if blocks:
        # 提取工具调用之前的文本作为 text block
        first_match = _TOOL_CALL_PATTERN.search(text) or _TOOL_CALL_PATTERN_LEGACY.search(text)
        prefix = text[:first_match.start()].strip() if first_match else ""
        result = []
        if prefix:
            result.append({"type": "text", "text": prefix})
        result.extend(blocks)
        return result, "tool_use"

    return [], "end_turn"


def build_tool_blocks_from_native_chunks(
    native_tc_chunks: dict, tools: list[dict]
) -> tuple[list[dict], str]:
    """
    从 Qwen 原生 tool_call SSE 事件分片中构建工具块。
    """
    if not native_tc_chunks:
        return [], "end_turn"

    tool_names = {t.get("name", "") for t in tools} if tools else set()
    blocks: list[dict] = []

    for tc_id, tc in native_tc_chunks.items():
        name = tc.get("name", "")
        args_str = tc.get("args", "")

        if not name:
            continue

        if tool_names and name not in tool_names:
            continue

        try:
            inp = json.loads(args_str) if args_str else {}
        except (json.JSONDecodeError, ValueError):
            inp = {"raw": args_str}

        blocks.append({
            "type": "tool_use",
            "id": f"toolu_{uuid.uuid4().hex[:12]}",
            "name": name,
            "input": inp if isinstance(inp, dict) else {},
        })

    if blocks:
        return blocks, "tool_use"
    return [], "end_turn"


def inject_format_reminder(prompt: str, blocked_name: str) -> str:
    """
    当工具调用格式不正确时，注入格式纠正提示。
    """
    reminder = (
        f"\n\n[FORMAT CORRECTION]: Please use the correct format to call tool '{blocked_name}':\n"
        f'[TOOL_CALL]{{"name": "{blocked_name}", "arguments": {{...}}}}\n'
        f'[/TOOL_CALL]\n'
        f"Do NOT use <tool_call> XML format. Use [TOOL_CALL] brackets as shown above.\n"
    )

    if prompt.rstrip().endswith("Assistant:"):
        prompt = prompt.rstrip()[:-len("Assistant:")] + reminder + "\nAssistant:"
    else:
        prompt += reminder + "\nAssistant:"

    return prompt


def should_block_tool_call(
    history_messages: list, tool_name: str, tool_input: dict
) -> tuple[bool, str]:
    """
    检测是否存在重复的工具调用（防止工具循环）。
    """
    if not history_messages:
        return False, ""

    recent_calls: list[dict] = []
    checked = 0
    for msg in reversed(history_messages):
        if not isinstance(msg, dict):
            continue
        checked += 1
        if checked > 10:
            break

        tool_calls = msg.get("tool_calls", [])
        for tc in tool_calls:
            func = tc.get("function", {})
            recent_calls.append({
                "name": func.get("name", ""),
                "arguments": func.get("arguments", ""),
            })

    current_args = json.dumps(tool_input, sort_keys=True, ensure_ascii=False)
    duplicate_count = 0
    for rc in recent_calls:
        if rc["name"] == tool_name:
            try:
                rc_args = json.dumps(json.loads(rc["arguments"]), sort_keys=True, ensure_ascii=False)
                if rc_args == current_args:
                    duplicate_count += 1
            except (json.JSONDecodeError, ValueError):
                if rc["arguments"] == current_args:
                    duplicate_count += 1

    if duplicate_count >= 2:
        return True, f"Tool '{tool_name}' called {duplicate_count + 1} times with identical arguments"

    return False, ""

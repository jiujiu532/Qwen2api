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

# ── JSON 修复 ────────────────────────────────────────────────────────────────

# 匹配无引号 key:  {name: "foo"} → {"name": "foo"}
_UNQUOTED_KEY = re.compile(r'([{,]\s*)([a-zA-Z_][a-zA-Z0-9_]*)\s*:')
# 匹配尾随逗号:  {"a": 1,} → {"a": 1}
_TRAILING_COMMA = re.compile(r',\s*([}\]])')


def repair_json(raw: str) -> str:
    """
    尝试修复模型输出中常见的 JSON 格式错误。
    参考 ds2api 的 RepairLooseJSON。
    """
    s = raw.strip()
    if not s:
        return s
    # 1) 单引号 → 双引号（仅对简单情况）
    if "'" in s and '"' not in s:
        s = s.replace("'", '"')
    # 2) 无引号 key → 加双引号
    s = _UNQUOTED_KEY.sub(r'\1"\2":', s)
    # 3) 尾随逗号
    s = _TRAILING_COMMA.sub(r'\1', s)
    # 4) 非法反斜杠: 只保留合法的 JSON 转义序列
    result = []
    i = 0
    while i < len(s):
        if s[i] == '\\' and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt in ('"', '\\', '/', 'b', 'f', 'n', 'r', 't'):
                result.append(s[i:i+2])
                i += 2
                continue
            elif nxt == 'u' and i + 5 < len(s) and all(c in '0123456789abcdefABCDEF' for c in s[i+2:i+6]):
                result.append(s[i:i+6])
                i += 6
                continue
            else:
                result.append('\\\\')
                i += 1
                continue
        result.append(s[i])
        i += 1
    return ''.join(result)


def _safe_json_loads(raw: str) -> dict | None:
    """先直接解析，失败后修复重试。"""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        pass
    try:
        return json.loads(repair_json(raw))
    except (json.JSONDecodeError, ValueError):
        return None


# ── 工具调用匹配 ─────────────────────────────────────────────────────────────

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

# 代码围栏检测：跳过 ``` 代码块内的内容
_CODE_FENCE = re.compile(r'```[\s\S]*?```')


def _strip_code_fences(text: str) -> str:
    """移除代码围栏内容，避免误匹配其中的 [TOOL_CALL]。"""
    return _CODE_FENCE.sub('', text)


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

    # 代码围栏保护：在去除代码块后的文本上做匹配
    safe_text = _strip_code_fences(text)

    # 优先匹配新格式 [TOOL_CALL]...{...}...[/TOOL_CALL]
    for pattern in (_TOOL_CALL_PATTERN, _TOOL_CALL_PATTERN_LEGACY):
        for match in pattern.finditer(safe_text):
            try:
                raw = match.group(1).strip()
                data = _safe_json_loads(raw)
                if data is None:
                    log.debug(f"[ToolParser] JSON 解析+修复均失败 | raw={raw[:80]}")
                    continue
                name = data.get("name", "")
                inp = data.get("arguments", data.get("input", data.get("params", {})))

                if name and (name in tool_names or not tool_names):
                    blocks.append({
                        "type": "tool_use",
                        "id": f"toolu_{uuid.uuid4().hex[:12]}",
                        "name": name,
                        "input": inp if isinstance(inp, dict) else {},
                    })
            except Exception as e:
                log.debug(f"[ToolParser] 解析异常: {e} | raw={match.group(1)[:80]}")
                continue
        if blocks:
            break  # 优先使用新格式的结果，找到就不再找旧格式

    if blocks:
        # 提取工具调用之前的文本作为 text block
        first_match = _TOOL_CALL_PATTERN.search(safe_text) or _TOOL_CALL_PATTERN_LEGACY.search(safe_text)
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

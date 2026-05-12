"""
prompt_builder.py -- 消息格式转换与工具调用 Prompt 注入
将 OpenAI / Anthropic 格式的 messages 转换为 Qwen 可用的 prompt 字符串。

工具调用策略：
- Native-first: 优先使用 Qwen 原生 function_calling
- XML Fallback: 被平台拦截时切换到 XML prompt 注入模式
- 格式设计参考 ds2api 的 DSML 思路，但使用 [TOOL_CALL] 括号格式避免 Qwen 平台拦截
"""

import json
from typing import Any


# ============================================================================
# 工具调用指令模板 -- 注意力优化结构：规则 -> 错误示例 -> 正确示例 -> 锚点
# ============================================================================

_TOOL_INSTRUCTIONS_HEADER = """\
# Tool Calling Protocol

You have access to the tools listed below. When you need to use a tool, output a tool call block in the EXACT format specified.

## FORMAT SPECIFICATION

```
[TOOL_CALL]
{"name": "TOOL_NAME", "arguments": {PARAMETERS}}
[/TOOL_CALL]
```

## RULES (FOLLOW EXACTLY):

1) Use the `[TOOL_CALL]...[/TOOL_CALL]` wrapper format. This is the ONLY accepted format.
2) The content between the tags MUST be a single valid JSON object with exactly two keys: "name" and "arguments".
3) "name" must be one of the available tool names listed below.
4) "arguments" must be a JSON object matching the tool's parameter schema. All keys and string values must use double quotes.
5) You may call multiple tools in one response using separate `[TOOL_CALL]...[/TOOL_CALL]` blocks.
6) Do NOT wrap tool calls inside markdown code fences (``` ```). Output them directly.
7) Do NOT use XML tags like `<tool_call>`, `<function_call>`, or `<invoke>`. They will be rejected.
8) Do NOT output explanations, apologies, or commentary AFTER a tool call block. The tool call must be the last content.
9) Fill parameters with actual values required for this call. Do NOT emit placeholder, blank, or empty-string parameters.
10) If a required parameter value is unknown, ask the user instead of outputting an empty tool call.
11) For shell/command tools (Bash, execute_command, exec_command), the command MUST be inside the "command" parameter. Never call them with an empty command.
12) If tool results are already in the conversation history, use them directly. Do NOT call the same tool with the same arguments again.
13) When you decide to call a tool, the `[TOOL_CALL]` block must appear as the LAST content in your response. No text after it.
"""

_TOOL_WRONG_EXAMPLES = """
## WRONG -- Do NOT do these:

Wrong 1 -- XML tags (REJECTED by system):
  <tool_call>{"name": "read_file", "arguments": {"path": "foo.py"}}</tool_call>

Wrong 2 -- Inside code fence (NOT detected):
  ```
  [TOOL_CALL]
  {"name": "read_file", "arguments": {"path": "foo.py"}}
  [/TOOL_CALL]
  ```

Wrong 3 -- Missing or malformed JSON:
  [TOOL_CALL]
  {name: read_file, arguments: {path: foo.py}}
  [/TOOL_CALL]

Wrong 4 -- Empty parameters:
  [TOOL_CALL]
  {"name": "Bash", "arguments": {"command": ""}}
  [/TOOL_CALL]

Wrong 5 -- Text after tool call:
  [TOOL_CALL]
  {"name": "read_file", "arguments": {"path": "foo.py"}}
  [/TOOL_CALL]
  I hope this helps!
"""

_TOOL_ANCHOR = """
Remember: The ONLY valid way to call tools is the `[TOOL_CALL]...[/TOOL_CALL]` block. When you need to use a tool, output the block and STOP.
"""


def _build_tool_examples(tool_defs: list[dict]) -> str:
    """根据实际可用工具名动态生成正确示例。"""
    names = [t.get("name", "") for t in tool_defs if t.get("name")]
    if not names:
        return ""

    examples = []

    # Example A: 单工具调用 -- 选择最合适的工具
    single = _pick_single_example(names, tool_defs)
    if single:
        examples.append(f"Example A -- Single tool call:\n{single}")

    # Example B: 并行调用 -- 如果有多个工具
    if len(names) >= 2:
        parallel = _pick_parallel_example(names, tool_defs)
        if parallel:
            examples.append(f"Example B -- Two parallel calls:\n{parallel}")

    # Example C: 复杂参数 -- 嵌套对象/数组
    nested = _pick_nested_example(names, tool_defs)
    if nested:
        examples.append(f"Example C -- Tool with complex parameters:\n{nested}")

    # Example D: 长文本参数 -- 代码/脚本
    script = _pick_script_example(names, tool_defs)
    if script:
        examples.append(f"Example D -- Tool with long text content:\n{script}")

    if not examples:
        # 兜底：用第一个工具生成通用示例
        name = names[0]
        params = _generate_example_params(name, tool_defs)
        examples.append(
            f"Example A -- Single tool call:\n"
            f"[TOOL_CALL]\n"
            f'{{"name": "{name}", "arguments": {params}}}\n'
            f"[/TOOL_CALL]"
        )

    return "## CORRECT EXAMPLES:\n\n" + "\n\n".join(examples) + "\n"


def _pick_single_example(names: list[str], tool_defs: list[dict]) -> str:
    """选择一个简单工具生成单调用示例。"""
    # 优先选择常见的简单工具
    priority = ["Read", "read_file", "Glob", "list_files", "search_files",
                "Bash", "execute_command", "exec_command", "Write", "write_to_file"]
    for p in priority:
        if p in names:
            params = _generate_example_params(p, tool_defs)
            return f'[TOOL_CALL]\n{{"name": "{p}", "arguments": {params}}}\n[/TOOL_CALL]'
    # 用第一个工具
    name = names[0]
    params = _generate_example_params(name, tool_defs)
    return f'[TOOL_CALL]\n{{"name": "{name}", "arguments": {params}}}\n[/TOOL_CALL]'


def _pick_parallel_example(names: list[str], tool_defs: list[dict]) -> str:
    """生成并行调用示例。"""
    picked = names[:2]
    blocks = []
    for name in picked:
        params = _generate_example_params(name, tool_defs)
        blocks.append(f'[TOOL_CALL]\n{{"name": "{name}", "arguments": {params}}}\n[/TOOL_CALL]')
    return "\n".join(blocks)


def _pick_nested_example(names: list[str], tool_defs: list[dict]) -> str:
    """选择有复杂参数的工具生成示例。"""
    # 查找有 object/array 类型参数的工具
    for td in tool_defs:
        name = td.get("name", "")
        if name not in names:
            continue
        params_schema = td.get("parameters", {})
        properties = params_schema.get("properties", {})
        for prop_name, prop_schema in properties.items():
            prop_type = prop_schema.get("type", "")
            if prop_type in ("object", "array"):
                params = _generate_example_params(name, tool_defs)
                return f'[TOOL_CALL]\n{{"name": "{name}", "arguments": {params}}}\n[/TOOL_CALL]'
    return ""


def _pick_script_example(names: list[str], tool_defs: list[dict]) -> str:
    """选择命令/脚本类工具生成长文本示例。"""
    script_tools = ["Bash", "execute_command", "exec_command", "Write", "write_to_file"]
    for st in script_tools:
        if st in names:
            if st in ("Bash", "execute_command"):
                return (
                    f'[TOOL_CALL]\n'
                    f'{{"name": "{st}", "arguments": {{"command": "find . -name \\"*.py\\" | head -20"}}}}\n'
                    f'[/TOOL_CALL]'
                )
            elif st == "exec_command":
                return (
                    f'[TOOL_CALL]\n'
                    f'{{"name": "{st}", "arguments": {{"cmd": "ls -la src/"}}}}\n'
                    f'[/TOOL_CALL]'
                )
            elif st in ("Write", "write_to_file"):
                return (
                    f'[TOOL_CALL]\n'
                    f'{{"name": "{st}", "arguments": {{"file_path": "hello.py", "content": "#!/usr/bin/env python3\\nprint(\'Hello, world!\')\\n"}}}}\n'
                    f'[/TOOL_CALL]'
                )
    return ""


def _generate_example_params(name: str, tool_defs: list[dict]) -> str:
    """根据工具名和 schema 生成示例参数 JSON。"""
    # 常见工具的硬编码示例
    examples_map = {
        "Read": '{"file_path": "README.md"}',
        "read_file": '{"path": "src/main.py"}',
        "Glob": '{"pattern": "**/*.py", "path": "."}',
        "list_files": '{"path": "."}',
        "search_files": '{"query": "function main", "path": "."}',
        "Bash": '{"command": "pwd"}',
        "execute_command": '{"command": "ls -la"}',
        "exec_command": '{"cmd": "pwd"}',
        "Write": '{"file_path": "notes.txt", "content": "Hello world"}',
        "write_to_file": '{"path": "notes.txt", "content": "Hello world"}',
        "Edit": '{"file_path": "README.md", "old_string": "foo", "new_string": "bar"}',
        "MultiEdit": '{"file_path": "README.md", "edits": [{"old_string": "foo", "new_string": "bar"}]}',
        "Task": '{"description": "Investigate the bug", "prompt": "Find and fix the issue"}',
        "ask_followup_question": '{"question": "Which approach do you prefer?"}',
    }
    if name in examples_map:
        return examples_map[name]

    # 从 schema 生成
    for td in tool_defs:
        if td.get("name") != name:
            continue
        params_schema = td.get("parameters", {})
        properties = params_schema.get("properties", {})
        required = params_schema.get("required", [])
        if not properties:
            return "{}"
        example = {}
        for prop_name, prop_schema in properties.items():
            if prop_name not in required and len(example) >= 2:
                continue  # 只展示必填参数 + 最多2个可选
            prop_type = prop_schema.get("type", "string")
            if prop_type == "string":
                example[prop_name] = f"example_{prop_name}"
            elif prop_type == "number" or prop_type == "integer":
                example[prop_name] = 1
            elif prop_type == "boolean":
                example[prop_name] = True
            elif prop_type == "array":
                example[prop_name] = ["item1"]
            elif prop_type == "object":
                example[prop_name] = {"key": "value"}
            else:
                example[prop_name] = f"example_{prop_name}"
        return json.dumps(example, ensure_ascii=False)

    return "{}"


def _build_read_tool_guard(tool_defs: list[dict]) -> str:
    """如果有 Read 类工具，添加缓存防护指令。"""
    read_names = {"Read", "read_file", "ReadFile", "readFile"}
    has_read = any(t.get("name", "") in read_names for t in tool_defs)
    if not has_read:
        return ""
    return (
        "\n## Read Tool Cache Guard\n"
        "If a Read/read_file tool result says the file is unchanged, already available in history, "
        "or provides no file body, treat that result as cached. Do NOT repeatedly call the same "
        "read request. Use the content from conversation history, or ask the user to provide it again.\n"
    )


def _build_tool_choice_instruction(tool_choice: Any) -> str:
    """根据 tool_choice 参数生成额外指令。"""
    if not tool_choice:
        return ""
    if isinstance(tool_choice, str):
        if tool_choice == "required":
            return "\n## MANDATORY: You MUST call at least one tool in this response. Do not answer with text only.\n"
        elif tool_choice == "none":
            return "\n## RESTRICTION: Do NOT call any tools in this response. Answer with text only.\n"
    elif isinstance(tool_choice, dict):
        # {"type": "function", "function": {"name": "specific_tool"}}
        func = tool_choice.get("function", {})
        forced_name = func.get("name", "")
        if forced_name:
            return f"\n## MANDATORY: You MUST call exactly this tool: `{forced_name}`. Do not call any other tool.\n"
    return ""


# ============================================================================
# 主入口
# ============================================================================

def _content_to_str(content: Any) -> str:
    """将各种 content 格式（str / list）统一转为文本。支持多模态消息。"""
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
                elif t == "image_url":
                    # OpenAI 多模态格式：{"type": "image_url", "image_url": {"url": "..."}}
                    url_obj = part.get("image_url", {})
                    url = url_obj.get("url", "") if isinstance(url_obj, dict) else str(url_obj)
                    if url:
                        parts.append(f"[Image: {url}]")
                elif t == "image":
                    # Anthropic 格式
                    source = part.get("source", {})
                    if source.get("type") == "url":
                        parts.append(f"[Image: {source.get('url', '')}]")
                    elif source.get("type") == "base64":
                        parts.append("[Image: base64 data attached]")
                elif t == "file":
                    # 文件引用
                    file_id = part.get("file_id", part.get("id", ""))
                    parts.append(f"[File: {file_id}]")
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


def extract_image_urls(messages: list[dict]) -> list[str]:
    """从消息中提取所有图片 URL（用于多模态请求）。"""
    urls = []
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "image_url":
                        url_obj = part.get("image_url", {})
                        url = url_obj.get("url", "") if isinstance(url_obj, dict) else str(url_obj)
                        if url and not url.startswith("data:"):
                            urls.append(url)
                    elif part.get("type") == "image":
                        source = part.get("source", {})
                        if source.get("type") == "url":
                            urls.append(source.get("url", ""))
    return urls


def messages_to_prompt(req_data: dict) -> tuple[str, list[dict]]:
    """
    将请求中的 messages + tools 转换为单一 prompt 字符串。

    Returns:
        (prompt_str, tools_list)
    """
    messages: list[dict] = req_data.get("messages", [])
    raw_tools: list[dict] = req_data.get("tools", [])
    tool_choice = req_data.get("tool_choice", None)
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
        tool_system_injection = _build_full_tool_prompt(tool_defs, tool_choice)

    parts: list[str] = []

    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role", "user")

        # -- System 消息：合并工具说明
        if role == "system":
            sys_text = _content_to_str(msg.get("content", ""))
            if tool_system_injection:
                combined = sys_text.rstrip() + "\n\n" + tool_system_injection if sys_text else tool_system_injection
                parts.append(f"System: {combined}")
                tool_system_injection = ""  # 已注入
            else:
                parts.append(f"System: {sys_text}")
            continue

        # -- Assistant 消息（可能含 tool_calls）
        if role == "assistant":
            tool_calls = msg.get("tool_calls", [])
            if tool_calls:
                tc_parts = []
                for tc in tool_calls:
                    func = tc.get("function", {})
                    name = func.get("name", "")
                    raw_args = func.get("arguments", "{}")
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

        # -- Tool 结果消息
        if role == "tool":
            tool_call_id = msg.get("tool_call_id", "")
            name = msg.get("name", "")
            content_str = _content_to_str(msg.get("content", ""))
            result_block = f'[TOOL_RESULT name="{name}" id="{tool_call_id}"]\n{content_str}\n[/TOOL_RESULT]'
            parts.append(f"Human: {result_block}")
            continue

        # -- User 消息
        if role == "user":
            content_str = _content_to_str(msg.get("content", ""))
            parts.append(f"Human: {content_str}")
            continue

        # -- 其他角色
        content_str = _content_to_str(msg.get("content", ""))
        parts.append(f"{role.capitalize()}: {content_str}")

    # 如果没有 system 消息但有工具，单独添加工具说明块
    if tool_system_injection:
        parts.insert(0, f"System: {tool_system_injection}")

    prompt = "\n\n".join(p for p in parts if p)
    if not prompt.rstrip().endswith("Assistant:"):
        prompt += "\n\nAssistant:"

    return prompt, tool_defs


def _build_full_tool_prompt(tool_defs: list[dict], tool_choice: Any = None) -> str:
    """构建完整的工具调用 prompt 注入块。"""
    sections = []

    # 1. 指令头
    sections.append(_TOOL_INSTRUCTIONS_HEADER)

    # 2. 错误示例
    sections.append(_TOOL_WRONG_EXAMPLES)

    # 3. 动态正确示例
    examples = _build_tool_examples(tool_defs)
    if examples:
        sections.append(examples)

    # 4. 参数形状说明
    sections.append(_build_parameter_shapes_guide(tool_defs))

    # 5. Read 工具防护
    guard = _build_read_tool_guard(tool_defs)
    if guard:
        sections.append(guard)

    # 6. tool_choice 指令
    choice_inst = _build_tool_choice_instruction(tool_choice)
    if choice_inst:
        sections.append(choice_inst)

    # 7. 锚点
    sections.append(_TOOL_ANCHOR)

    # 8. 工具列表
    sections.append("## Available Tools\n")
    for td in tool_defs:
        name = td.get("name", "")
        desc = td.get("description", "No description")
        params = td.get("parameters", {})
        sections.append(f"### {name}\n{desc}\nParameters: {json.dumps(params, ensure_ascii=False)}\n")

    return "\n".join(sections)


def _build_parameter_shapes_guide(tool_defs: list[dict]) -> str:
    """生成参数形状指南，帮助模型理解如何构造参数。"""
    return """## PARAMETER SHAPES:

- string: `"key": "value"` (always double-quoted)
- number: `"key": 123` or `"key": 3.14`
- boolean: `"key": true` or `"key": false`
- null: `"key": null`
- array: `"key": ["item1", "item2"]`
- object: `"key": {"nested_key": "nested_value"}`
- Multi-line strings: Use `\\n` for newlines inside JSON strings. Example: `"content": "line1\\nline2\\nline3"`
"""

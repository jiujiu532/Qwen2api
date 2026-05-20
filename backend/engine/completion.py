"""
completion.py -- 统一 Completion 执行器
从 chat.py 提取的核心业务逻辑，所有协议共用。
参考 grok2api 的 products/openai/chat.py 的 completions() 模式。
"""

import asyncio as aio
import json
import logging
import uuid
import time
import re
from typing import Optional, AsyncGenerator

from backend.core.account_pool import Account
from backend.services.qwen_client import QwenClient
from backend.services.token_calc import calculate_usage
from backend.services.tool_parser import (
    parse_tool_calls,
    inject_format_reminder,
    build_tool_blocks_from_native_chunks,
    should_block_tool_call,
)
from backend.core.config import settings

log = logging.getLogger("qwen2api.engine")


# ── 统一入口 ──────────────────────────────────────────────────────────────────

async def completions(
    *,
    client: QwenClient,
    model: str,
    prompt: str,
    tools: list[dict],
    stream: bool,
    thinking: Optional[bool],
    history_messages: list,
    model_name: str = "",
    completion_id: str = "",
    created: int = 0,
):
    """统一 completion 执行器。

    stream=True  -> AsyncGenerator，yield OpenAI SSE 格式行
    stream=False -> dict，完整 OpenAI chat.completion 响应

    参数：
        client          QwenClient 实例
        model           Qwen 真实模型名（已 resolve）
        prompt          已构建好的 prompt 字符串
        tools           工具定义列表（空列表=无工具）
        stream          是否流式
        thinking        True=强制思考 / False=关闭 / None=自动
        history_messages 原始 messages（工具循环检测用）
        model_name      原始模型名（响应中的 model 字段）
        completion_id   响应 ID（不传则自动生成）
        created         时间戳（不传则自动生成）
    """
    if not completion_id:
        completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    if not created:
        created = int(time.time())
    if not model_name:
        model_name = model

    max_attempts = settings.TOOL_MAX_RETRIES if tools else settings.MAX_RETRIES

    if stream:
        if tools:
            return _stream_with_tools(
                client=client,
                qwen_model=model,
                prompt=prompt,
                tools=tools,
                thinking=thinking,
                history_messages=history_messages,
                completion_id=completion_id,
                created=created,
                model_name=model_name,
                max_attempts=max_attempts,
            )
        else:
            return _stream_no_tools(
                client=client,
                qwen_model=model,
                prompt=prompt,
                thinking=thinking,
                completion_id=completion_id,
                created=created,
                model_name=model_name,
                max_attempts=max_attempts,
            )
    else:
        return await _batch(
            client=client,
            qwen_model=model,
            prompt=prompt,
            tools=tools,
            thinking=thinking,
            history_messages=history_messages,
            completion_id=completion_id,
            created=created,
            model_name=model_name,
            max_attempts=max_attempts,
        )


# ============================================================================
# 辅助函数（从 chat.py 搬入）
# ============================================================================

async def _stream_items_with_keepalive(client, model: str, prompt: str,
                                       has_custom_tools: bool, xml_mode: bool = False,
                                       exclude_accounts=None, thinking: bool = None,
                                       files: list[dict] = None):
    """包装上游流式事件，添加 keepalive 心跳防止连接超时。"""
    queue: aio.Queue = aio.Queue()

    async def _producer():
        try:
            async for item in client.chat_stream_events_with_retry(
                model, prompt, has_custom_tools=has_custom_tools,
                xml_mode=xml_mode, exclude_accounts=exclude_accounts,
                thinking=thinking, files=files
            ):
                await queue.put(("item", item))
        except Exception as e:
            await queue.put(("error", e))
        finally:
            await queue.put(("done", None))

    producer_task = aio.create_task(_producer())
    try:
        while True:
            try:
                kind, payload = await aio.wait_for(
                    queue.get(), timeout=max(1, settings.STREAM_KEEPALIVE_INTERVAL)
                )
            except aio.TimeoutError:
                yield {"type": "keepalive"}
                continue

            if kind == "item":
                yield payload
            elif kind == "error":
                raise payload
            elif kind == "done":
                break
    finally:
        if not producer_task.done():
            producer_task.cancel()
            try:
                await producer_task
            except aio.CancelledError:
                pass


def _extract_blocked_tool_names(text: str) -> list[str]:
    """检测上游是否拦截了工具名（返回 'Tool xxx does not exist' 错误）。"""
    if not text:
        return []
    return re.findall(r"Tool\s+([A-Za-z0-9_.:-]+)\s+does not exists?\.?", text)


def _parse_events_to_text(events: list[dict]) -> tuple[str, str, dict, list[str]]:
    """从事件列表中解析出 answer_text, reasoning_text, native_tc_chunks, image_urls。
    
    支持 image_edit_tool phase（图生图场景）。
    Returns: (answer_text, reasoning_text, native_tc_chunks, image_urls)
    """
    answer_text = ""
    reasoning_text = ""
    native_tc_chunks: dict = {}
    image_urls: list[str] = []

    for evt in events:
        if evt.get("type") != "delta":
            continue
        phase = evt.get("phase", "")
        content = evt.get("content", "")
        extra = evt.get("extra", {}) or {}

        # 从 extra 中提取图片 URL（image_edit_tool 完成后图片可能在这里）
        if isinstance(extra, dict):
            for key in ("image_url", "imageUrl", "url", "image"):
                val = extra.get(key, "")
                if isinstance(val, str) and val.startswith("http"):
                    image_urls.append(val)
            tool_result = extra.get("tool_result")
            if isinstance(tool_result, list):
                for item in tool_result:
                    if isinstance(item, dict):
                        for k in ("image", "url", "image_url", "src"):
                            v = item.get(k, "")
                            if isinstance(v, str) and v.startswith("http"):
                                image_urls.append(v)
                    elif isinstance(item, str) and item.startswith("http"):
                        image_urls.append(item)

        if phase in ("think", "thinking_summary") and content:
            reasoning_text += content
        elif phase == "answer" and content:
            answer_text += content
        elif phase == "image_edit_tool" and content:
            # image_edit_tool 的 content 可能包含图片信息或文本描述
            answer_text += content
        elif phase == "tool_call" and content:
            tc_id = extra.get("tool_call_id", "tc_0")
            if tc_id not in native_tc_chunks:
                native_tc_chunks[tc_id] = {"name": "", "args": ""}
            try:
                chunk = json.loads(content)
                if "name" in chunk:
                    native_tc_chunks[tc_id]["name"] = chunk["name"]
                if "arguments" in chunk:
                    native_tc_chunks[tc_id]["args"] += chunk["arguments"]
            except (json.JSONDecodeError, ValueError):
                native_tc_chunks[tc_id]["args"] += content
        if evt.get("status") == "finished" and phase == "answer":
            break

    # 如果从事件中提取到了图片 URL，附加到 answer_text
    if image_urls:
        # 去重
        seen = set()
        unique_urls = []
        for u in image_urls:
            if u not in seen and u not in answer_text:
                seen.add(u)
                unique_urls.append(u)
        for url in unique_urls:
            answer_text += f"\n![image]({url})"

    return answer_text, reasoning_text, native_tc_chunks, image_urls


def _has_recent_unchanged_read_result(messages) -> bool:
    """检查最近消息中是否有 'Unchanged since last read' 结果。"""
    checked = 0
    for msg in reversed(messages or []):
        if not isinstance(msg, dict):
            continue
        checked += 1
        content = msg.get("content", "")
        texts = []
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    t = part.get("type")
                    if t == "text":
                        texts.append(part.get("text", ""))
                    elif t == "tool_result":
                        inner = part.get("content", "")
                        if isinstance(inner, str):
                            texts.append(inner)
                        elif isinstance(inner, list):
                            for p in inner:
                                if isinstance(p, dict) and p.get("type") == "text":
                                    texts.append(p.get("text", ""))
                elif isinstance(part, str):
                    texts.append(part)
        merged = "\n".join(t for t in texts if t)
        if "Unchanged since last read" in merged:
            return True
        if checked >= 10:
            break
    return False


# ============================================================================
# 核心执行器入口
# ============================================================================

async def completions(
    *,
    client: QwenClient,
    model: str,
    prompt: str,
    tools: list[dict],
    stream: bool,
    thinking: Optional[bool],
    history_messages: list,
    model_name: str = "",
    files: list[dict] = None,
) -> "dict | AsyncGenerator[str, None]":
    """统一 completion 执行器。

    stream=True  -> AsyncGenerator[str, None]，yield OpenAI SSE 格式行
    stream=False -> dict，完整 OpenAI chat.completion 响应

    内部处理：重试循环、NativeBlock fallback、工具循环检测、空响应重试、账号管理。
    """
    if stream:
        if tools:
            return _stream_with_tools(
                client=client, model=model, prompt=prompt, tools=tools,
                thinking=thinking, history_messages=history_messages,
                model_name=model_name, files=files,
            )
        else:
            return _stream_no_tools(
                client=client, model=model, prompt=prompt,
                thinking=thinking, model_name=model_name, files=files,
            )
    else:
        return await _batch(
            client=client, model=model, prompt=prompt, tools=tools,
            thinking=thinking, history_messages=history_messages,
            model_name=model_name, files=files,
        )


# ============================================================================
# 流式路径：无工具（真流式，逐事件转发）
# ============================================================================

async def _stream_no_tools(
    *, client: QwenClient, model: str, prompt: str,
    thinking: Optional[bool], model_name: str, files: list[dict] = None,
) -> AsyncGenerator[str, None]:
    """无工具流式：事件到来立即转发给客户端。"""
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())
    max_attempts = settings.MAX_RETRIES
    current_prompt = prompt
    excluded_accounts: set = set()

    for attempt in range(max_attempts):
        chat_id: Optional[str] = None
        acc: Optional[Account] = None
        try:
            sent_role = False
            streamed_len = 0
            thought_sent = False  # 标记是否已发过 thought 内容
            reasoning_sent_len = 0  # 已发送的 reasoning 字符数（用于去重累积式推送）
            upstream_usage = None  # 上游真实 usage（从 SSE 事件中提取）

            async for item in _stream_items_with_keepalive(
                client, model, current_prompt, has_custom_tools=False,
                xml_mode=False, exclude_accounts=excluded_accounts, thinking=thinking,
                files=files
            ):
                if item["type"] == "keepalive":
                    yield ": keepalive\n\n"
                    continue
                if item["type"] == "meta":
                    chat_id = item["chat_id"]
                    meta_acc = item["acc"]
                    if isinstance(meta_acc, Account):
                        acc = meta_acc
                    yield ": upstream-connected\n\n"
                    continue
                if item["type"] != "event":
                    continue
                evt = item["event"]
                if evt.get("type") != "delta":
                    continue

                # 提取上游真实 usage（取最后一个非空 usage，即最终统计）
                if evt.get("usage"):
                    upstream_usage = evt["usage"]

                phase = evt.get("phase", "")
                content = evt.get("content", "")
                reasoning = evt.get("reasoning_content", "")
                extra = evt.get("extra", {}) or {}

                # 从 extra 中提取图片 URL（图生图场景）
                if isinstance(extra, dict):
                    for _ek in ("image_url", "imageUrl", "url"):
                        _ev = extra.get(_ek, "")
                        if isinstance(_ev, str) and _ev.startswith("http") and not content:
                            content = f"![image]({_ev})"
                    _tr = extra.get("tool_result")
                    if isinstance(_tr, list):
                        for _ti in _tr:
                            if isinstance(_ti, dict):
                                for _tk in ("image", "url", "image_url"):
                                    _tv = _ti.get(_tk, "")
                                    if isinstance(_tv, str) and _tv.startswith("http") and not content:
                                        content = f"![image]({_tv})"

                # 思考内容透传（thought 实时流 + thinking_summary 摘要都透传）
                if (phase == "thought" or phase == "thinking_summary" or reasoning) and not content:
                    # 如果已发过 thought 实时流，跳过 thinking_summary 避免重复
                    if phase == "thinking_summary" and thought_sent:
                        continue
                    if phase == "thought":
                        thought_sent = True
                    # 去重：如果上游发的是累积全文，只取增量部分
                    full_reasoning = reasoning or content
                    if len(full_reasoning) > reasoning_sent_len:
                        delta_reasoning = full_reasoning[reasoning_sent_len:]
                        reasoning_sent_len = len(full_reasoning)
                    else:
                        continue  # 没有新内容，跳过
                    yield f"data: {json.dumps({'id': completion_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model_name, 'choices': [{'index': 0, 'delta': {'reasoning_content': delta_reasoning}, 'finish_reason': None}]}, ensure_ascii=False)}\n\n"
                    streamed_len += len(delta_reasoning)
                    continue

                # 正文内容 — 打字机效果（也处理 image_edit_tool phase 的内容输出）
                if (phase in ("answer", "image_edit_tool") or content) and content:
                    if not sent_role:
                        yield f"data: {json.dumps({'id': completion_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model_name, 'choices': [{'index': 0, 'delta': {'role': 'assistant'}, 'finish_reason': None}]}, ensure_ascii=False)}\n\n"
                        sent_role = True
                    streamed_len += len(content)
                    # 打字机模式：逐字符/小批量输出
                    chunk_delay = settings.STREAM_CHUNK_DELAY_MS / 1000.0
                    max_size = settings.STREAM_MAX_CHUNK_SIZE
                    if chunk_delay > 0 and max_size > 0 and len(content) > max_size:
                        pos = 0
                        while pos < len(content):
                            batch = content[pos:pos + max_size]
                            pos += max_size
                            yield f"data: {json.dumps({'id': completion_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model_name, 'choices': [{'index': 0, 'delta': {'content': batch}, 'finish_reason': None}]}, ensure_ascii=False)}\n\n"
                            if pos < len(content):
                                await aio.sleep(chunk_delay)
                    else:
                        yield f"data: {json.dumps({'id': completion_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model_name, 'choices': [{'index': 0, 'delta': {'content': content}, 'finish_reason': None}]}, ensure_ascii=False)}\n\n"

            # 空响应重试
            if streamed_len == 0 and attempt < min(settings.EMPTY_RESPONSE_RETRIES, max_attempts - 1):
                if acc is not None:
                    client.account_pool.release(acc)
                    if chat_id:
                        aio.create_task(client.delete_chat(acc.token, chat_id))
                    excluded_accounts.add(acc.email)
                log.warning(f"[Engine] 空响应，重试 (attempt {attempt+1}/{max_attempts})")
                await aio.sleep(0.3)
                continue

            # 正常结束
            if not sent_role:
                yield f"data: {json.dumps({'id': completion_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model_name, 'choices': [{'index': 0, 'delta': {'role': 'assistant'}, 'finish_reason': None}]}, ensure_ascii=False)}\n\n"
            # 最终 chunk 附带 usage（从上游真实数据提取，若无则用本地估算）
            final_chunk = {'id': completion_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model_name, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]}
            if upstream_usage:
                final_chunk['usage'] = {
                    'prompt_tokens': upstream_usage.get('input_tokens', 0),
                    'completion_tokens': upstream_usage.get('output_tokens', 0),
                    'total_tokens': upstream_usage.get('total_tokens', 0) or (upstream_usage.get('input_tokens', 0) + upstream_usage.get('output_tokens', 0)),
                }
            yield f"data: {json.dumps(final_chunk, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

            # 释放账号
            if acc is not None:
                client.account_pool.release(acc)
                if chat_id:
                    aio.create_task(client.delete_chat(acc.token, chat_id))
            return

        except Exception as e:
            if acc and acc.inflight > 0:
                client.account_pool.release(acc)
                if chat_id:
                    aio.create_task(client.delete_chat(acc.token, chat_id))
            yield f"data: {json.dumps({'error': {'message': str(e), 'type': 'server_error'}})}\n\n"
            return

    # 所有重试耗尽
    yield f"data: {json.dumps({'error': {'message': 'All retries exhausted', 'type': 'server_error'}})}\n\n"
    yield "data: [DONE]\n\n"


# ============================================================================
# 流式路径：有工具（缓冲后输出）
# ============================================================================

async def _stream_with_tools(
    *, client: QwenClient, model: str, prompt: str, tools: list[dict],
    thinking: Optional[bool], history_messages: list, model_name: str,
    files: list[dict] = None,
) -> AsyncGenerator[str, None]:
    """有工具流式：缓冲所有事件，检测工具调用后一次性输出。"""
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())
    max_attempts = settings.TOOL_MAX_RETRIES
    current_prompt = prompt
    excluded_accounts: set = set()
    force_xml_mode = True  # 有工具时默认用 XML 模式

    for attempt in range(max_attempts):
        chat_id: Optional[str] = None
        acc: Optional[Account] = None
        try:
            answer_text = ""
            reasoning_text = ""
            native_tc_chunks: dict = {}

            # 收集所有事件
            async for item in _stream_items_with_keepalive(
                client, model, current_prompt, has_custom_tools=True,
                xml_mode=force_xml_mode, exclude_accounts=excluded_accounts,
                thinking=thinking, files=files
            ):
                if item["type"] == "keepalive":
                    yield ": keepalive\n\n"
                    continue
                if item["type"] == "meta":
                    chat_id = item["chat_id"]
                    meta_acc = item["acc"]
                    if isinstance(meta_acc, Account):
                        acc = meta_acc
                    yield ": upstream-connected\n\n"
                    continue
                if item["type"] != "event":
                    continue
                evt = item["event"]
                if evt.get("type") != "delta":
                    continue

                phase = evt.get("phase", "")
                content = evt.get("content", "")

                if phase in ("think", "thinking_summary") and content:
                    reasoning_text += content
                elif phase == "answer" and content:
                    answer_text += content
                elif phase == "tool_call" and content:
                    tc_id = evt.get("extra", {}).get("tool_call_id", "tc_0")
                    if tc_id not in native_tc_chunks:
                        native_tc_chunks[tc_id] = {"name": "", "args": ""}
                    try:
                        chunk = json.loads(content)
                        if "name" in chunk:
                            native_tc_chunks[tc_id]["name"] = chunk["name"]
                        if "arguments" in chunk:
                            native_tc_chunks[tc_id]["args"] += chunk["arguments"]
                    except (json.JSONDecodeError, ValueError):
                        native_tc_chunks[tc_id]["args"] += content
                if evt.get("status") == "finished" and phase == "answer":
                    break

            # 诊断日志
            log.info(
                f"[Engine] attempt={attempt+1}/{max_attempts} answer_len={len(answer_text)} "
                f"reasoning_len={len(reasoning_text)} native_tc={len(native_tc_chunks)}"
            )

            # 尝试原生 FC
            if native_tc_chunks and not answer_text:
                log.info(f"[Engine] 检测到原生 tool_call 事件: {list(native_tc_chunks.keys())}")
            tool_blocks, stop = build_tool_blocks_from_native_chunks(native_tc_chunks, tools)
            if tool_blocks and stop == "tool_use":
                log.info(f"[Engine] 使用原生工具调用分片 count={len(tool_blocks)}")
            else:
                tool_blocks, stop = parse_tool_calls(answer_text, tools)
            has_tool_call = stop == "tool_use"

            # NativeBlock 检测 → 切 XML 模式重试
            blocked_names = _extract_blocked_tool_names(answer_text.strip())
            if blocked_names and not has_tool_call and attempt < max_attempts - 1:
                if acc is not None:
                    client.account_pool.release(acc)
                    if chat_id:
                        aio.create_task(client.delete_chat(acc.token, chat_id))
                    excluded_accounts.add(acc.email)
                force_xml_mode = True
                current_prompt = inject_format_reminder(current_prompt, blocked_names[0])
                log.warning(f"[Engine] NativeBlock '{blocked_names[0]}'，切 XML 重试 (attempt {attempt+1})")
                await aio.sleep(0.15)
                continue

            # 工具循环检测
            if has_tool_call:
                first_tool = next((b for b in tool_blocks if b.get("type") == "tool_use"), None)
                if first_tool:
                    blocked_tc, blocked_reason = should_block_tool_call(
                        history_messages, first_tool.get("name", ""), first_tool.get("input", {})
                    )
                    if blocked_tc and attempt < max_attempts - 1:
                        if acc:
                            client.account_pool.release(acc)
                            if chat_id:
                                aio.create_task(client.delete_chat(acc.token, chat_id))
                        current_prompt = _inject_force_text(current_prompt, blocked_reason)
                        log.warning(f"[Engine] 阻止重复工具调用: {first_tool.get('name')} (attempt {attempt+1})")
                        await aio.sleep(0.15)
                        continue

                    # Unchanged Read 检测
                    if (first_tool.get("name") == "Read"
                            and _has_recent_unchanged_read_result(history_messages)
                            and attempt < max_attempts - 1):
                        if acc:
                            client.account_pool.release(acc)
                            if chat_id:
                                aio.create_task(client.delete_chat(acc.token, chat_id))
                        force_text = (
                            "[MANDATORY NEXT STEP]: You just received 'Unchanged since last read'. "
                            "Do NOT call Read again on the same target. Choose another tool now."
                        )
                        current_prompt = _inject_force_text(current_prompt, force_text)
                        log.warning(f"[Engine] 阻止重复 Read (attempt {attempt+1})")
                        await aio.sleep(0.15)
                        continue

            # 输出结果
            mk = lambda delta, finish=None: json.dumps({
                "id": completion_id, "object": "chat.completion.chunk",
                "created": created, "model": model_name,
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]
            }, ensure_ascii=False)

            yield f"data: {mk({'role': 'assistant'})}\n\n"

            if has_tool_call:
                tc_list = [b for b in tool_blocks if b["type"] == "tool_use"]
                for idx, tc in enumerate(tc_list):
                    yield f"data: {mk({'tool_calls': [{'index': idx, 'id': tc['id'], 'type': 'function', 'function': {'name': tc['name'], 'arguments': ''}}]})}\n\n"
                    yield f"data: {mk({'tool_calls': [{'index': idx, 'function': {'arguments': json.dumps(tc.get('input', {}), ensure_ascii=False)}}]})}\n\n"
                yield f"data: {mk({}, 'tool_calls')}\n\n"
            else:
                if reasoning_text:
                    yield f"data: {mk({'reasoning_content': reasoning_text})}\n\n"
                if answer_text:
                    yield f"data: {mk({'content': answer_text})}\n\n"
                yield f"data: {mk({}, 'stop')}\n\n"

            yield "data: [DONE]\n\n"

            # 释放账号
            if acc:
                client.account_pool.release(acc)
                if chat_id:
                    aio.create_task(client.delete_chat(acc.token, chat_id))
            return

        except Exception as e:
            if acc and acc.inflight > 0:
                client.account_pool.release(acc)
                if chat_id:
                    aio.create_task(client.delete_chat(acc.token, chat_id))
            yield f"data: {json.dumps({'error': {'message': str(e), 'type': 'server_error'}})}\n\n"
            return

    # 所有重试耗尽
    yield f"data: {json.dumps({'error': {'message': 'All retries exhausted', 'type': 'server_error'}})}\n\n"
    yield "data: [DONE]\n\n"


# ============================================================================
# 非流式路径
# ============================================================================

async def _batch(
    *, client: QwenClient, model: str, prompt: str, tools: list[dict],
    thinking: Optional[bool], history_messages: list, model_name: str,
    files: list[dict] = None,
) -> dict:
    """非流式：收集所有事件，返回完整 OpenAI chat.completion 响应。"""
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())
    max_attempts = settings.TOOL_MAX_RETRIES if tools else settings.MAX_RETRIES
    current_prompt = prompt
    excluded_accounts: set = set()
    force_xml_mode = bool(tools)

    for attempt in range(max_attempts):
        chat_id: Optional[str] = None
        acc: Optional[Account] = None
        try:
            events = []
            upstream_usage = None  # 上游真实 usage
            async for item in client.chat_stream_events_with_retry(
                model, current_prompt, has_custom_tools=bool(tools),
                xml_mode=force_xml_mode, exclude_accounts=excluded_accounts,
                thinking=thinking, files=files
            ):
                if item["type"] == "meta":
                    chat_id = item["chat_id"]
                    acc = item["acc"]
                    continue
                if item["type"] == "event":
                    events.append(item["event"])
                    # 提取上游 usage（取最后一个非空值）
                    if item["event"].get("usage"):
                        upstream_usage = item["event"]["usage"]

            # 解析事件（支持 image_edit_tool 图生图场景）
            answer_text, reasoning_text, native_tc_chunks, _ = _parse_events_to_text(events)

            # 原生 TC 转为 answer_text（兼容后续解析）
            if native_tc_chunks and not answer_text:
                tc_parts = []
                for tc_id, tc in native_tc_chunks.items():
                    name = tc["name"]
                    try:
                        inp = json.loads(tc["args"]) if tc["args"] else {}
                    except (json.JSONDecodeError, ValueError):
                        inp = {"raw": tc["args"]}
                    tc_parts.append(
                        f'<tool_call>{{"name": {json.dumps(name)}, "input": {json.dumps(inp, ensure_ascii=False)}}}</tool_call>'
                    )
                answer_text = "\n".join(tc_parts)

            # NativeBlock 检测
            blocked_names = _extract_blocked_tool_names(answer_text.strip())
            if blocked_names and tools and attempt < max_attempts - 1:
                if acc:
                    client.account_pool.release(acc)
                    if chat_id:
                        aio.create_task(client.delete_chat(acc.token, chat_id))
                force_xml_mode = True
                current_prompt = inject_format_reminder(current_prompt, blocked_names[0])
                log.warning(f"[Engine-Batch] NativeBlock '{blocked_names[0]}'，切 XML 重试")
                await aio.sleep(0.15)
                continue

            # 工具调用解析
            tool_blocks, stop = parse_tool_calls(answer_text, tools)
            has_tool_call = stop == "tool_use"

            # 工具循环检测
            if has_tool_call:
                first_tool = next((b for b in tool_blocks if b.get("type") == "tool_use"), None)
                if first_tool:
                    blocked_tc, blocked_reason = should_block_tool_call(
                        history_messages, first_tool.get("name", ""), first_tool.get("input", {})
                    )
                    if blocked_tc and attempt < max_attempts - 1:
                        if acc:
                            client.account_pool.release(acc)
                            if chat_id:
                                aio.create_task(client.delete_chat(acc.token, chat_id))
                        current_prompt = _inject_force_text(current_prompt, blocked_reason)
                        log.warning(f"[Engine-Batch] 阻止重复工具调用: {first_tool.get('name')}")
                        await aio.sleep(0.15)
                        continue

                    if (first_tool.get("name") == "Read"
                            and _has_recent_unchanged_read_result(history_messages)
                            and attempt < max_attempts - 1):
                        if acc:
                            client.account_pool.release(acc)
                            if chat_id:
                                aio.create_task(client.delete_chat(acc.token, chat_id))
                        force_text = (
                            "[MANDATORY NEXT STEP]: You just received 'Unchanged since last read'. "
                            "Do NOT call Read again on the same target. Choose another tool now."
                        )
                        current_prompt = _inject_force_text(current_prompt, force_text)
                        log.warning(f"[Engine-Batch] 阻止重复 Read")
                        await aio.sleep(0.15)
                        continue

            # 构建响应
            if has_tool_call:
                tc_list = [b for b in tool_blocks if b["type"] == "tool_use"]
                oai_tool_calls = [{
                    "id": tc["id"], "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc.get("input", {}), ensure_ascii=False)
                    }
                } for tc in tc_list]
                msg = {"role": "assistant", "content": None, "tool_calls": oai_tool_calls}
                finish_reason = "tool_calls"
            else:
                msg = {"role": "assistant", "content": answer_text}
                if reasoning_text:
                    msg["reasoning_content"] = reasoning_text
                finish_reason = "stop"

            # 释放账号
            if acc:
                client.account_pool.release(acc)
                if chat_id:
                    aio.create_task(client.delete_chat(acc.token, chat_id))

            # 计算 usage — 优先使用上游真实数据
            if upstream_usage:
                usage = {
                    "prompt_tokens": upstream_usage.get("input_tokens", 0),
                    "completion_tokens": upstream_usage.get("output_tokens", 0),
                    "total_tokens": upstream_usage.get("total_tokens", 0) or (upstream_usage.get("input_tokens", 0) + upstream_usage.get("output_tokens", 0)),
                }
            else:
                usage = calculate_usage(prompt, answer_text)

            return {
                "id": completion_id, "object": "chat.completion",
                "created": created, "model": model_name,
                "choices": [{"index": 0, "message": msg, "finish_reason": finish_reason}],
                "usage": usage,
            }

        except Exception as e:
            if acc and acc.inflight > 0:
                client.account_pool.release(acc)
                if chat_id:
                    aio.create_task(client.delete_chat(acc.token, chat_id))
            if attempt == max_attempts - 1:
                raise
            await aio.sleep(1)

    # 不应到达这里，但安全兜底
    raise Exception("All retries exhausted without response")


# ============================================================================
# 内部辅助
# ============================================================================

def _inject_force_text(prompt: str, reason: str) -> str:
    """在 prompt 末尾注入强制指令，阻止模型重复调用工具。"""
    prompt = prompt.rstrip()
    force_text = (
        f"[MANDATORY NEXT STEP]: {reason}. "
        f"Do NOT call the same tool with the same arguments again. "
        f"Choose another tool or provide final answer."
    )
    if prompt.endswith("Assistant:"):
        return prompt[:-len("Assistant:")] + force_text + "\nAssistant:"
    else:
        return prompt + "\n\n" + force_text + "\nAssistant:"


# ============================================================================
# 协议无关的结构化结果（Phase 2 新增）
# ============================================================================

from dataclasses import dataclass, field


@dataclass
class CompletionResult:
    """协议无关的 completion 结果，供各协议路由层格式化。"""
    answer_text: str = ""
    reasoning_text: str = ""
    tool_blocks: list = field(default_factory=list)
    stop: str = "end_turn"  # "end_turn" | "tool_use"
    usage: dict = field(default_factory=dict)


async def completions_raw(
    *,
    client: QwenClient,
    model: str,
    prompt: str,
    tools: list[dict],
    thinking: Optional[bool],
    history_messages: list,
    files: list[dict] = None,
) -> CompletionResult:
    """协议无关的 completion 执行器（非流式）。

    内部处理重试/NativeBlock/工具循环，返回结构化结果。
    各协议路由层负责格式化为自己的响应格式。
    """
    max_attempts = settings.TOOL_MAX_RETRIES if tools else settings.MAX_RETRIES
    current_prompt = prompt
    excluded_accounts: set = set()
    force_xml_mode = bool(tools)

    for attempt in range(max_attempts):
        chat_id: Optional[str] = None
        acc: Optional[Account] = None
        try:
            events = []
            upstream_usage = None  # 上游真实 usage
            async for item in client.chat_stream_events_with_retry(
                model, current_prompt, has_custom_tools=bool(tools),
                xml_mode=force_xml_mode, exclude_accounts=excluded_accounts,
                thinking=thinking, files=files
            ):
                if item["type"] == "meta":
                    chat_id = item["chat_id"]
                    acc = item["acc"]
                    continue
                if item["type"] == "event":
                    events.append(item["event"])
                    if item["event"].get("usage"):
                        upstream_usage = item["event"]["usage"]

            # 解析事件（支持 image_edit_tool 图生图场景）
            answer_text, reasoning_text, native_tc_chunks, _ = _parse_events_to_text(events)

            # 原生 TC 转为 answer_text
            if native_tc_chunks and not answer_text:
                tc_parts = []
                for tc_id, tc in native_tc_chunks.items():
                    name = tc["name"]
                    try:
                        inp = json.loads(tc["args"]) if tc["args"] else {}
                    except (json.JSONDecodeError, ValueError):
                        inp = {"raw": tc["args"]}
                    tc_parts.append(
                        f'<tool_call>{{"name": {json.dumps(name)}, "input": {json.dumps(inp, ensure_ascii=False)}}}</tool_call>'
                    )
                answer_text = "\n".join(tc_parts)

            # NativeBlock 检测
            blocked_names = _extract_blocked_tool_names(answer_text.strip())
            if blocked_names and tools and attempt < max_attempts - 1:
                if acc:
                    client.account_pool.release(acc)
                    if chat_id:
                        aio.create_task(client.delete_chat(acc.token, chat_id))
                force_xml_mode = True
                current_prompt = inject_format_reminder(current_prompt, blocked_names[0])
                log.warning(f"[Engine-Raw] NativeBlock '{blocked_names[0]}'，切 XML 重试")
                await aio.sleep(0.15)
                continue

            # 工具调用解析
            tool_blocks, stop = parse_tool_calls(answer_text, tools)
            has_tool_call = stop == "tool_use"

            # 工具循环检测
            if has_tool_call:
                first_tool = next((b for b in tool_blocks if b.get("type") == "tool_use"), None)
                if first_tool:
                    blocked_tc, blocked_reason = should_block_tool_call(
                        history_messages, first_tool.get("name", ""), first_tool.get("input", {})
                    )
                    if blocked_tc and attempt < max_attempts - 1:
                        if acc:
                            client.account_pool.release(acc)
                            if chat_id:
                                aio.create_task(client.delete_chat(acc.token, chat_id))
                        current_prompt = _inject_force_text(current_prompt, blocked_reason)
                        await aio.sleep(0.15)
                        continue

            # 释放账号
            if acc:
                client.account_pool.release(acc)
                if chat_id:
                    aio.create_task(client.delete_chat(acc.token, chat_id))

            # 计算 usage — 优先使用上游真实数据
            if upstream_usage:
                usage = {
                    "prompt_tokens": upstream_usage.get("input_tokens", 0),
                    "completion_tokens": upstream_usage.get("output_tokens", 0),
                    "total_tokens": upstream_usage.get("total_tokens", 0) or (upstream_usage.get("input_tokens", 0) + upstream_usage.get("output_tokens", 0)),
                }
            else:
                usage = calculate_usage(prompt, answer_text)

            return CompletionResult(
                answer_text=answer_text,
                reasoning_text=reasoning_text,
                tool_blocks=tool_blocks,
                stop=stop,
                usage=usage,
            )

        except Exception as e:
            if acc and acc.inflight > 0:
                client.account_pool.release(acc)
                if chat_id:
                    aio.create_task(client.delete_chat(acc.token, chat_id))
            if attempt == max_attempts - 1:
                raise
            await aio.sleep(1)

    raise Exception("All retries exhausted without response")

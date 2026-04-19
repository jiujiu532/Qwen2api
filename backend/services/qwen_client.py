import asyncio
import json
import logging
import random
import time
import uuid
from typing import Optional, Any
from backend.core.account_pool import AccountPool, Account
from backend.core.config import settings
from backend.services.auth_resolver import AuthResolver

log = logging.getLogger("qwen2api.client")

AUTH_FAIL_KEYWORDS = ("token", "unauthorized", "expired", "forbidden", "401", "403", "invalid", "login", "activation", "pending activation", "not activated")
PENDING_ACTIVATION_KEYWORDS = ("pending activation", "please check your email", "not activated")
BANNED_KEYWORDS = ("banned", "suspended", "blocked", "disabled", "risk control", "violat", "forbidden by policy")

def _is_auth_error(error_msg: str) -> bool:
    msg = error_msg.lower()
    return any(keyword in msg for keyword in AUTH_FAIL_KEYWORDS)

def _is_pending_activation_error(error_msg: str) -> bool:
    msg = error_msg.lower()
    return any(keyword in msg for keyword in PENDING_ACTIVATION_KEYWORDS)

def _is_banned_error(error_msg: str) -> bool:
    msg = error_msg.lower()
    return any(keyword in msg for keyword in BANNED_KEYWORDS)

class QwenClient:
    def __init__(self, engine: Any, account_pool: AccountPool):
        self.engine = engine
        self.account_pool = account_pool
        self.auth_resolver = AuthResolver(account_pool)
        self.active_chat_ids: set[str] = set()  # 正在使用中的 chat_id，GC 不得焚烧

    @staticmethod
    def _extract_urls_from_extra(extra: Any) -> list[str]:
        """从 SSE delta.extra 字段中提取图片 URL。
        Qwen T2I 响应的 extra 字段可能包含:
          - {"wanx": {"image_list": [{"url": "..."}]}}
          - {"images": [{"url": "..."}]}
          - {"image_url": "..."}
          - 顶层 url/image 字符串字段
        """
        urls: list[str] = []
        if not extra or not isinstance(extra, dict):
            return urls
        # wanx 格式
        wanx = extra.get("wanx") or {}
        if isinstance(wanx, dict):
            for item in wanx.get("image_list", []):
                u = item.get("url") or item.get("image_url") or ""
                if u and u.startswith("http"):
                    urls.append(u)
        # images 列表格式
        for item in extra.get("images", []):
            u = (item.get("url") or item.get("image_url") or "") if isinstance(item, dict) else ""
            if u and u.startswith("http"):
                urls.append(u)
        # 顶层直接字段
        for key in ("image_url", "imageUrl", "url", "image"):
            v = extra.get(key, "")
            if isinstance(v, str) and v.startswith("http"):
                urls.append(v)
        return urls

    async def create_chat(self, token: str, model: str, chat_type: str = "t2t") -> str:
        ts = int(time.time())
        body = {"title": f"api_{ts}", "models": [model], "chat_mode": "normal",
                "chat_type": chat_type, "timestamp": ts}

        # chat 生命周期接口也优先走浏览器，更贴近真人使用路径
        if hasattr(self.engine, "browser_engine") and getattr(self.engine, "browser_engine") is not None:
            r = await self.engine.browser_engine.api_call("POST", "/api/v2/chats/new", token, body)
            status = r.get("status")
            body_text = (r.get("body") or "").lower()
            should_fallback = (
                status == 0
                or status in (401, 403, 429)
                or "waf" in body_text
                or "<!doctype" in body_text
                or "forbidden" in body_text
                or "unauthorized" in body_text
            )
            if should_fallback:
                preview = (r.get("body") or "")[:160].replace("\n", "\\n")
                log.warning(f"[QwenClient] create_chat 浏览器失败，回退到默认引擎 status={status} body_preview={preview!r}")
                r = await self.engine.api_call("POST", "/api/v2/chats/new", token, body)
        else:
            r = await self.engine.api_call("POST", "/api/v2/chats/new", token, body)
        if r["status"] == 429:
            raise Exception("429 Too Many Requests (Engine Queue Full)")

        body_text = r.get("body", "")
        if r["status"] != 200:
            body_lower = body_text.lower()
            if (r["status"] in (401, 403)
                    or "unauthorized" in body_lower or "forbidden" in body_lower
                    or "token" in body_lower or "login" in body_lower
                    or "401" in body_text or "403" in body_text):
                raise Exception(f"unauthorized: create_chat HTTP {r['status']}: {body_text[:100]}")
            raise Exception(f"create_chat HTTP {r['status']}: {body_text[:100]}")

        try:
            data = json.loads(body_text)
            if not data.get("success") or "id" not in data.get("data", {}):
                raise Exception("Qwen API returned error or missing id")
            return data["data"]["id"]
        except Exception as e:
            body_lower = body_text.lower()
            if any(kw in body_lower for kw in ("html", "login", "unauthorized", "activation",
                                                "pending", "forbidden", "token", "expired", "invalid")):
                raise Exception(f"unauthorized: account issue: {body_text[:200]}")
            raise Exception(f"create_chat parse error: {e}, body={body_text[:200]}")

    async def delete_chat(self, token: str, chat_id: str):
        if hasattr(self.engine, "browser_engine") and getattr(self.engine, "browser_engine") is not None:
            r = await self.engine.browser_engine.api_call("DELETE", f"/api/v2/chats/{chat_id}", token)
            status = r.get("status")
            body_text = (r.get("body") or "").lower()
            should_fallback = (
                status == 0
                or status in (401, 403, 429)
                or "waf" in body_text
                or "<!doctype" in body_text
                or "forbidden" in body_text
                or "unauthorized" in body_text
            )
            if should_fallback:
                preview = (r.get("body") or "")[:160].replace("\n", "\\n")
                log.warning(f"[QwenClient] delete_chat 浏览器失败，回退到默认引擎 chat_id={chat_id} status={status} body_preview={preview!r}")
                await self.engine.api_call("DELETE", f"/api/v2/chats/{chat_id}", token)
            return
        await self.engine.api_call("DELETE", f"/api/v2/chats/{chat_id}", token)

    async def verify_token(self, token: str) -> bool:
        """Verify token validity via direct HTTP (no browser page needed)."""
        if not token:
            return False

        try:
            import httpx
            from backend.services.auth_resolver import BASE_URL

            # 伪造浏览器指纹，避免被 Aliyun WAF 拦截
            headers = {
                "Authorization": f"Bearer {token}",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Referer": "https://chat.qwen.ai/",
                "Origin": "https://chat.qwen.ai",
                "Connection": "keep-alive"
            }

            async with httpx.AsyncClient(timeout=15) as hc:
                resp = await hc.get(
                    f"{BASE_URL}/api/v1/auths/",
                    headers=headers,
                )
            if resp.status_code != 200:
                return False

            # 增加对空响应/非 JSON 响应的容错，防止 GFW 拦截或代理返回假 200 OK 导致崩溃
            try:
                data = resp.json()
                return data.get("role") == "user"
            except Exception as e:
                log.warning(f"[verify_token] JSON parse error (可能是被拦截或代理异常): {e}, status={resp.status_code}, text={resp.text[:100]}")
                # 如果遇到阿里云 WAF 拦截，通常是因为 httpx 直接请求被墙，或者 token 本身就是正常的。
                # 由于这是为了快速验证，如果被 WAF 拦截 (HTML)，我们姑且假定它是活着的，交给后面的浏览器引擎去真实处理
                if "aliyun_waf" in resp.text.lower() or "<!doctype" in resp.text.lower():
                    log.info(f"[verify_token] 遇到 WAF 拦截页面，放行交给底层无头浏览器引擎处理。")
                    return True
                return False
        except Exception as e:
            log.warning(f"[verify_token] HTTP error: {e}")
            return False

    async def list_models(self, token: str) -> list:
        try:
            import httpx
            from backend.services.auth_resolver import BASE_URL

            headers = {
                "Authorization": f"Bearer {token}",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://chat.qwen.ai/",
                "Origin": "https://chat.qwen.ai",
                "Connection": "keep-alive"
            }

            async with httpx.AsyncClient(timeout=10) as hc:
                resp = await hc.get(
                    f"{BASE_URL}/api/models",
                    headers=headers,
                )
            if resp.status_code != 200:
                return []
            try:
                return resp.json().get("data", [])
            except Exception as e:
                log.warning(f"[list_models] JSON parse error: {e}, status={resp.status_code}, text={resp.text[:100]}")
                return []
        except Exception:
            return []

    def _build_payload(self, chat_id: str, model: str, content: str,
                        has_custom_tools: bool = False,
                        enable_native_fc: Optional[bool] = None) -> dict:
        ts = int(time.time())
        # has_custom_tools=True: 关闭思考/搜索/插件（适用于任何工具调用模式）
        # enable_native_fc: 独立控制是否开启 Qwen 平台原生 function_calling
        #   None → 默认沿用旧逻辑（has_custom_tools and NATIVE_TOOL_PASSTHROUGH）
        #   False → 强制关闭（XML模式）
        if enable_native_fc is None:
            enable_native_fc = bool(has_custom_tools and settings.NATIVE_TOOL_PASSTHROUGH)
        feature_config = {
            "thinking_enabled": not has_custom_tools,
            "output_schema": "phase",
            "research_mode": "normal",
            "auto_thinking": not has_custom_tools,
            "thinking_mode": "off" if has_custom_tools else "Auto",
            "thinking_format": "summary",
            "auto_search": not has_custom_tools,
            "code_interpreter": not has_custom_tools,
            "function_calling": enable_native_fc,
            "plugins_enabled": False if has_custom_tools else True,
        }
        return {
            "stream": True, "version": "2.1", "incremental_output": True,
            "chat_id": chat_id, "chat_mode": "normal", "model": model, "parent_id": None,
            "messages": [{
                "fid": str(uuid.uuid4()), "parentId": None, "childrenIds": [str(uuid.uuid4())],
                "role": "user", "content": content, "user_action": "chat", "files": [],
                "timestamp": ts, "models": [model], "chat_type": "t2t",
                "feature_config": feature_config,
                "extra": {"meta": {"subChatType": "t2t"}}, "sub_chat_type": "t2t", "parent_id": None,
            }],
            "timestamp": ts,
        }

    def _build_image_payload(self, chat_id: str, model: str, prompt: str, aspect_ratio: str = "1:1") -> dict:
        ts = int(time.time())
        # Map ratio → pixel dimensions (Wanx / Flux common sizes)
        ratio_to_size: dict[str, str] = {
            "1:1":  "1024*1024",
            "16:9": "1280*720",
            "9:16": "720*1280",
            "4:3":  "1024*768",
            "3:4":  "768*1024",
        }
        px = ratio_to_size.get(aspect_ratio, "1024*1024")  # e.g. "1280*720"
        px_x = px.replace("*", "x")                         # e.g. "1280x720"
        w, h = px.split("*")                                 # e.g. ("1280", "720")
        feature_config = {
            "thinking_enabled": False,
            "output_schema": "phase",
            "auto_thinking": False,
            "thinking_mode": "off",
            "auto_search": False,
            "code_interpreter": False,
            "function_calling": False,
            "plugins_enabled": True,
            "image_generation": True,
            "default_aspect_ratio": aspect_ratio,
            "image_size": px,
            "t2i_size": px,
        }
        return {
            "stream": True,
            "version": "2.1",
            "incremental_output": True,
            "chat_id": chat_id,
            "chat_mode": "normal",
            "model": model,
            "parent_id": None,
            "messages": [{
                "fid": str(uuid.uuid4()),
                "parentId": None,
                "childrenIds": [str(uuid.uuid4())],
                "role": "user",
                "content": f"生成图片：{prompt}",
                "user_action": "chat",
                "files": [],
                "timestamp": ts,
                "models": [model],
                "chat_type": "t2i",
                "feature_config": feature_config,
                "extra": {"meta": {
                    "subChatType": "t2i",
                    "mode": "image_generation",
                    "aspectRatio": aspect_ratio,   # "16:9"
                    "imageSize": px,               # "1280*720" (Wanx format)
                    "size": px_x,                  # "1280x720"
                    "width": int(w),
                    "height": int(h),
                    "image_generation_enabled": True,
                }},
                "sub_chat_type": "t2i",
                "parent_id": None,
            }],
            "timestamp": ts,
        }

    def parse_sse_chunk(self, chunk: str) -> list[dict]:
        events = []
        for line in chunk.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            try:
                obj = json.loads(data)
                events.append(obj)
            except Exception:
                continue

        parsed = []
        for evt in events:
            if evt.get("choices"):
                delta = evt["choices"][0].get("delta", {})
                finish_reason = evt["choices"][0].get("finish_reason", "")
                # 提取 tool_call_id (Qwen 原生 tool_call 事件)
                extra = delta.get("extra", {})
                # 有些版本 tool_call_id 在 delta 顶层
                tc_id = (extra.get("tool_call_id")
                         or delta.get("tool_call_id")
                         or evt.get("tool_call_id")
                         or "tc_0")
                parsed.append({
                    "type": "delta",
                    "phase": delta.get("phase", "answer"),
                    "content": delta.get("content", ""),
                    "reasoning_content": delta.get("thought", "") or delta.get("reasoning_content", ""),
                    "status": delta.get("status", "") or finish_reason,
                    "extra": {**extra, "tool_call_id": tc_id},
                })
            elif evt.get("phase"):
                extra = evt.get("extra", {})
                tc_id = (extra.get("tool_call_id")
                         or evt.get("tool_call_id")
                         or "tc_0")
                parsed.append({
                    "type": "delta",
                    "phase": evt.get("phase", "answer"),
                    "content": evt.get("content", "") or evt.get("text", "") or "",
                    "reasoning_content": evt.get("thought", "") or evt.get("reasoning_content", ""),
                    "status": evt.get("status", ""),
                    "extra": {**extra, "tool_call_id": tc_id},
                })
        return parsed

    async def chat_stream_events_with_retry(self, model: str, content: str,
                                              has_custom_tools: bool = False,
                                              xml_mode: bool = False,
                                              exclude_accounts: Optional[set[str]] = None):
        """无感容灾重试逻辑：上游挂了自动换号"""
        exclude = set(exclude_accounts or set())
        # xml_mode: 有工具但不用 Qwen 原生 FC，用 XML prompt 注入
        # 此时仍需 has_custom_tools=True 以关闭思考/搜索/插件
        effective_has_tools = has_custom_tools or xml_mode
        enable_native_fc = False if xml_mode else None  # None = 走默认逻辑
        for attempt in range(settings.MAX_RETRIES):
            acc = await self.account_pool.acquire_wait(timeout=60, exclude=exclude)
            if not acc:
                pool_status = self.account_pool.status()
                raise Exception(
                    "No available accounts in pool "
                    f"(total={pool_status['total']}, valid={pool_status['valid']}, "
                    f"invalid={pool_status['invalid']}, activation_pending={pool_status.get('activation_pending', 0)}, "
                    f"rate_limited={pool_status['rate_limited']}, in_use={pool_status['in_use']}, waiting={pool_status['waiting']})"
                )

            chat_id: Optional[str] = None
            try:
                log.info(f"[重试 {attempt+1}/{settings.MAX_RETRIES}] 获取账号：account={acc.email} model={model} tools={has_custom_tools} xml_mode={xml_mode} exclude={sorted(exclude)}")
                # 本地节流：同账号两次上游请求之间保持最小间隔，降低自动化痕迹
                min_interval = max(0, settings.ACCOUNT_MIN_INTERVAL_MS) / 1000.0
                now = time.time()
                wait_s = max(0.0, (acc.last_request_started + min_interval) - now)
                # 请求指纹 jitter：随机 50-200ms 额外延迟，防止模式检测
                jitter_ms = random.randint(settings.REQUEST_JITTER_MIN_MS, settings.REQUEST_JITTER_MAX_MS)
                wait_s += jitter_ms / 1000.0
                if wait_s > 0:
                    log.debug(f"[节流] 账号冷却等待：account={acc.email} wait={wait_s:.2f}s (含 jitter {jitter_ms}ms)")
                    await asyncio.sleep(wait_s)
                chat_id = await self.create_chat(acc.token, model)
                self.active_chat_ids.add(chat_id)
                payload = self._build_payload(chat_id, model, content, effective_has_tools, enable_native_fc)
                log.info(
                    f"[重试 {attempt+1}/{settings.MAX_RETRIES}] 已创建会话：account={acc.email} chat_id={chat_id} "
                    f"engine={self.engine.__class__.__name__} function_calling={payload['messages'][0]['feature_config'].get('function_calling')} "
                    f"thinking_enabled={payload['messages'][0]['feature_config'].get('thinking_enabled')}"
                )

                # First yield the chat_id and account to the consumer
                yield {"type": "meta", "chat_id": chat_id, "acc": acc}

                buffer = ""
                # 始终用流式模式：可实时发现 NativeBlock 并早期中止，不用等 3 分钟
                async for chunk_result in self.engine.fetch_chat(acc.token, chat_id, payload, buffered=False):
                    if chunk_result.get("status") == 429:
                        log.warning(f"[本地背压 {attempt+1}/{settings.MAX_RETRIES}] 引擎队列已满：account={acc.email} chat_id={chat_id}")
                        raise Exception("local_backpressure: engine queue full")
                    if chunk_result.get("status") != 200 and chunk_result.get("status") != "streamed":
                        body_preview = (chunk_result.get("body", "")[:120]).replace("\n", "\\n")
                        log.warning(
                            f"[重试 {attempt+1}/{settings.MAX_RETRIES}] 上游分片异常：account={acc.email} chat_id={chat_id} "
                            f"status={chunk_result.get('status')} body_preview={body_preview!r}"
                        )
                        raise Exception(f"HTTP {chunk_result['status']}: {chunk_result.get('body', '')[:100]}")

                    if "chunk" in chunk_result:
                        buffer += chunk_result["chunk"]
                        while "\n" in buffer:
                            # If we see a line starting with data:, try to parse it even without \n\n
                            # Standard SSE is \n\n, but we want maximum reactivity
                            line, buffer = buffer.split("\n", 1)
                            if line.strip().startswith("data:"):
                                events = self.parse_sse_chunk(line)
                                for evt in events:
                                    yield {"type": "event", "event": evt}
                    elif "body" in chunk_result and chunk_result["body"] and chunk_result["body"] != "streamed":
                        buffer += chunk_result["body"]
                
                if buffer:
                    events = self.parse_sse_chunk(buffer)
                    for evt in events:
                        yield {"type": "event", "event": evt}
                log.info(f"[重试 {attempt+1}/{settings.MAX_RETRIES}] 流式完成：account={acc.email} chat_id={chat_id} buffered_chars={len(buffer)}")
                self.active_chat_ids.discard(chat_id)
                # v2: 标记成功，粗估 tokens
                self.account_pool.mark_success(acc)
                self.account_pool.release(acc, tokens_used=max(len(buffer) // 4, 100))
                return

            except Exception as e:
                if chat_id:
                    self.active_chat_ids.discard(chat_id)  # type: ignore[arg-type]
                err_msg = str(e).lower()
                should_save = False
                if "local_backpressure" in err_msg or "engine queue full" in err_msg:
                    acc.last_error = str(e)
                    log.warning(f"[重试 {attempt+1}/{settings.MAX_RETRIES}] 本地背压：account={acc.email} error={e}")
                elif "429" in err_msg or "rate limit" in err_msg or "too many" in err_msg:
                    self.account_pool.mark_error(acc, "rate_limit", str(e))
                    exclude.add(acc.email)
                    log.warning(f"[重试 {attempt+1}/{settings.MAX_RETRIES}] 标记为限流：account={acc.email} error={e}")
                elif _is_pending_activation_error(err_msg):
                    self.account_pool.mark_error(acc, "auth", str(e))
                    exclude.add(acc.email)
                    acc.activation_pending = True
                    should_save = True
                    log.warning(f"[重试 {attempt+1}/{settings.MAX_RETRIES}] 标记为待激活：account={acc.email} error={e}")
                    asyncio.create_task(self.auth_resolver.auto_heal_account(acc))
                elif _is_banned_error(err_msg):
                    self.account_pool.mark_banned(acc, str(e))
                    exclude.add(acc.email)
                    log.warning(f"[重试 {attempt+1}/{settings.MAX_RETRIES}] 标记为封禁：account={acc.email} error={e}")
                elif _is_auth_error(err_msg):
                    self.account_pool.mark_error(acc, "auth", str(e))
                    exclude.add(acc.email)
                    log.warning(f"[重试 {attempt+1}/{settings.MAX_RETRIES}] 标记为鉴权失败：account={acc.email} error={e}")
                    asyncio.create_task(self.auth_resolver.auto_heal_account(acc))
                else:
                    self.account_pool.mark_error(acc, "transient", str(e))
                    log.warning(f"[重试 {attempt+1}/{settings.MAX_RETRIES}] 瞬态错误：account={acc.email} error={e}")

                if should_save:
                    await self.account_pool.save()

                self.account_pool.release(acc)
                log.warning(f"[重试 {attempt+1}/{settings.MAX_RETRIES}] 账号失败，准备重试：account={acc.email} error={e}")
                
        raise Exception(f"All {settings.MAX_RETRIES} attempts failed. Please check upstream accounts.")

    def _extract_urls_from_extra(self, extra: dict) -> list[str]:
        """从 SSE event 的 extra 字段提取图片 URL。

        已知格式：
        - extra.tool_result[0].image  (image_gen_tool finished 事件，最主要路径)
        - extra.image_url / extra.wanx_image_url / extra.imageUrl
        - extra.image_urls / extra.images / extra.imageUrls (列表)
        """
        urls = []
        if not extra or not isinstance(extra, dict):
            return urls

        # ① image_gen_tool 完成事件：extra.tool_result[].image
        tool_result = extra.get("tool_result")
        if isinstance(tool_result, list):
            for item in tool_result:
                if isinstance(item, dict):
                    for key in ("image", "url", "src", "imageUrl", "image_url"):
                        val = item.get(key)
                        if isinstance(val, str) and val.startswith("http"):
                            urls.append(val)
                elif isinstance(item, str) and item.startswith("http"):
                    urls.append(item)

        # ② 平铺字段
        for key in ("image_url", "wanx_image_url", "imageUrl"):
            val = extra.get(key)
            if isinstance(val, str) and val.startswith("http"):
                urls.append(val)

        # ③ 列表字段
        for key in ("image_urls", "images", "imageUrls"):
            val = extra.get(key)
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, str) and item.startswith("http"):
                        urls.append(item)
                    elif isinstance(item, dict):
                        for sub_key in ("url", "src", "image", "imageUrl"):
                            sub_val = item.get(sub_key)
                            if isinstance(sub_val, str) and sub_val.startswith("http"):
                                urls.append(sub_val)
        return urls

    async def image_generate_with_retry(self, model: str, prompt: str, aspect_ratio: str = "1:1", exclude_accounts: Optional[set[str]] = None) -> tuple[str, "Account", str]:
        """调用千问 T2I 生成图片，返回 (原始响应文本, 使用的账号, chat_id)
        
        轮询策略：
        - 每次失败自动将账号加入排除列表，保证下次重试使用不同账号
        - RateLimited / 每日上限 → 标记限流，冷却 30 分钟
        - 认证错误 → 触发自动修复
        - 其他错误 → 软错误计数，5 次后断路
        """
        exclude = set(exclude_accounts or set())
        last_error: Optional[Exception] = None

        for attempt in range(settings.MAX_RETRIES):
            acc = await self.account_pool.acquire_wait(timeout=60, exclude=exclude)
            if not acc:
                pool_status = self.account_pool.status()
                raise Exception(
                    f"No available accounts in pool "
                    f"(valid={pool_status['valid']}, rate_limited={pool_status['rate_limited']}, "
                    f"excluded={len(exclude)})"
                )

            log.info(f"[T2I] 尝试 {attempt+1}/{settings.MAX_RETRIES}，使用账号 {acc.email}")
            chat_id: Optional[str] = None
            try:
                chat_id = await self.create_chat(acc.token, model, chat_type="t2t")
                self.active_chat_ids.add(chat_id)
                payload = self._build_image_payload(chat_id, model, prompt, aspect_ratio)

                raw_body_parts: list[str] = []  # 保存原始 SSE body 用于 debug
                answer_text = ""
                extra_urls: list[str] = []
                buffer = ""

                async for chunk_result in self.engine.fetch_chat(acc.token, chat_id, payload):
                    if chunk_result.get("status") == 429:
                        raise Exception("Engine Queue Full (429)")
                    if chunk_result.get("status") not in (200, "streamed"):
                        raise Exception(f"HTTP {chunk_result['status']}: {chunk_result.get('body', '')[:200]}")

                    # 把原始文本拼进 buffer
                    raw = ""
                    if "chunk" in chunk_result:
                        raw = chunk_result["chunk"]
                    elif "body" in chunk_result:
                        raw = chunk_result.get("body", "") or ""
                    if not raw:
                        continue

                    raw_body_parts.append(raw)
                    buffer += raw

                # 处理整个 buffer（不论流式还是一次性返回）
                raw_body = "".join(raw_body_parts)
                log.info(f"[T2I] 原始 SSE body 前 1000 字符: {raw_body[:1000]!r}")

                # ── 检测响应中的错误信号 ──
                raw_lower = raw_body.lower()
                is_rate_limited = (
                    "ratelimited" in raw_lower
                    or "rate_limited" in raw_lower
                    or "daily usage limit" in raw_lower
                    or "reached the da" in raw_lower       # "reached the daily usage limit"
                    or "请求过于频繁" in raw_body
                    or "使用上限" in raw_body
                    or "频率限制" in raw_body
                )
                is_api_error = (
                    '"success":false' in raw_body
                    or '"success": false' in raw_body
                )

                if is_rate_limited:
                    raise Exception(f"Qwen T2I RateLimit (daily): {raw_body[:300]}")
                if is_api_error and not extra_urls:
                    raise Exception(f"Qwen T2I API error: {raw_body[:300]}")

                for line in raw_body.splitlines():
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if not data_str or data_str == "[DONE]":
                        continue
                    try:
                        obj = json.loads(data_str)
                    except Exception:
                        continue

                    # 打印每个 SSE 事件用于诊断
                    log.info(f"[T2I-SSE] 事件: {json.dumps(obj, ensure_ascii=False)[:400]}")

                    # 从 choices[0].delta 提取
                    if obj.get("choices"):
                        delta = obj["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                        phase = delta.get("phase", "answer")
                        extra = delta.get("extra", {})
                        log.info(f"[T2I-SSE] phase={phase!r} content_len={len(content)} content_preview={content[:100]!r}")
                        # 捕获所有文本内容
                        answer_text += content
                        # 捕获 extra 字段里的图片 URL
                        extra_urls.extend(self._extract_urls_from_extra(extra))
                    elif obj.get("phase"):
                        # 直接顶层 phase 格式
                        content = obj.get("content", "") or obj.get("text", "") or ""
                        phase = obj.get("phase", "")
                        extra = obj.get("extra", {})
                        log.info(f"[T2I-SSE] 顶层 phase={phase!r} content_len={len(content)} content_preview={content[:100]!r}")
                        answer_text += content
                        extra_urls.extend(self._extract_urls_from_extra(extra))

                # 如果 extra 里找到了图片 URL，把它们拼成 Markdown 图片格式追加进 answer_text
                if extra_urls:
                    log.info(f"[T2I] 从 extra 字段提取到 {len(extra_urls)} 个图片 URL: {extra_urls}")
                    for url in extra_urls:
                        answer_text += f"\n![image]({url})"

                # 如果 answer_text 为空就用原始 body 作为保底
                if not answer_text:
                    answer_text = raw_body

                self.active_chat_ids.discard(chat_id)
                log.info(f"[T2I] ✅ 生成成功，账号={acc.email}，响应长度={len(answer_text)}: {answer_text[:200]!r}")
                self.account_pool.mark_success(acc)
                self.account_pool.release(acc, tokens_used=max(len(answer_text) // 4, 200))
                return answer_text, acc, chat_id

            except Exception as e:
                if chat_id:
                    self.active_chat_ids.discard(chat_id)  # type: ignore[arg-type]
                
                err_msg = str(e)
                err_lower = err_msg.lower()
                last_error = e

                # ── 分类错误并标记账号 ──
                if any(kw in err_lower for kw in ("ratelimit", "rate_limit", "rate limit", "daily", "usage limit", "429", "too many", "使用上限", "频率限制")):
                    self.account_pool.mark_error(acc, "rate_limit", err_msg)
                    log.warning(f"[T2I] ⚠️ 账号 {acc.email} 已达限流上限，标记为限流并切换下一个账号")
                elif _is_pending_activation_error(err_lower):
                    self.account_pool.mark_error(acc, "auth", err_msg)
                    asyncio.create_task(self.auth_resolver.auto_heal_account(acc))
                    log.warning(f"[T2I] ⚠️ 账号 {acc.email} 需要激活，触发自动修复")
                elif _is_banned_error(err_lower):
                    self.account_pool.mark_banned(acc, err_msg)
                    log.warning(f"[T2I] 🚫 账号 {acc.email} 已被封禁")
                elif _is_auth_error(err_lower):
                    self.account_pool.mark_error(acc, "auth", err_msg)
                    asyncio.create_task(self.auth_resolver.auto_heal_account(acc))
                    log.warning(f"[T2I] ⚠️ 账号 {acc.email} 认证失败，触发自动修复")
                else:
                    self.account_pool.mark_error(acc, "transient", err_msg)
                    log.warning(f"[T2I] ⚠️ 账号 {acc.email} 临时错误: {err_msg[:150]}")

                self.account_pool.release(acc)
                # 将失败账号加入排除列表，确保下轮不会再选到它
                exclude.add(acc.email)
                log.info(f"[T2I] 重试 {attempt+1}/{settings.MAX_RETRIES}，排除列表: {exclude}")

        raise Exception(f"All {settings.MAX_RETRIES} T2I attempts failed. Last error: {last_error}")

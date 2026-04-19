"""
admin.py — 管理后台 API
提供账号管理、密钥管理、设置、日志等后台 API。
"""

import asyncio
import json
import logging
import os
import threading
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from backend.core.config import settings, API_KEYS, save_api_keys, load_api_keys, MODEL_MAP, DATA_DIR, save_runtime_settings

log = logging.getLogger("qwen2api.admin")
router = APIRouter()

# 手动注册停止标志（仅影响用户手动触发的批量注册，不影响自动补号/应急补号）
_manual_stop_flag = threading.Event()


def _require_admin(request: Request):
    auth = request.headers.get("Authorization", "")
    token = auth.replace("Bearer ", "").strip() if auth.startswith("Bearer ") else ""
    if not token:
        token = request.headers.get("x-api-key", "").strip()
    if not token:
        # SSE EventSource 不支持自定义 header，允许 query param
        token = request.query_params.get("key", "").strip()
    if token != settings.ADMIN_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return token


# ─── 状态 ───────────────────────────────────────────

@router.get("/system-info")
async def get_system_info(_=Depends(_require_admin)):
    """
    检测服务器硬件并推荐最优并发线程数。
    新策略：遇到验证码直接丢弃，IP 轮换由代理池决定。
    CPU/RAM 是真正的并发瓶颈，无 WAF 硬限制。
    """
    import psutil
    cpu_count = psutil.cpu_count(logical=False) or psutil.cpu_count() or 2
    ram_gb = psutil.virtual_memory().total / (1024 ** 3)
    ram_available_gb = psutil.virtual_memory().available / (1024 ** 3)

    # 每个浏览器 ~150MB RAM + 0.5 核 CPU
    # 新策略：遇验证码立刻退出，内存释放快，可以跑更高并发
    by_ram = max(1, int(ram_available_gb * 0.7 / 0.15))
    by_cpu = max(1, cpu_count * 3)
    recommended = min(by_ram, by_cpu, 20)  # 上限 20，代理池决定 IP 是否干净
    recommended = max(1, recommended)

    return {
        "cpu_cores": cpu_count,
        "ram_total_gb": round(ram_gb, 1),
        "ram_available_gb": round(ram_available_gb, 1),
        "recommended_threads": recommended,
        "limits": {
            "by_ram": min(by_ram, 20),
            "by_cpu": min(by_cpu, 20),
        },
        "warning": "每个浏览器约占 150MB RAM。遇到验证码立刻丢弃，IP 干净率由代理池决定。推荐并发 = min(CPU, RAM)。"
    }


@router.get("/status")
async def get_status(request: Request, _=Depends(_require_admin)):
    app = request.app
    pool = app.state.account_pool
    pool_status = pool.status()

    browser_info = {"pool_size": 0, "queue": 0}
    engine = app.state.gateway_engine
    if hasattr(engine, "pool_size"):
        browser_info["pool_size"] = engine.pool_size
    elif hasattr(engine, "browser_engine") and hasattr(engine.browser_engine, "pool_size"):
        browser_info["pool_size"] = engine.browser_engine.pool_size

    return {
        "accounts": pool_status,
        "browser_engine": browser_info,
        "engine_mode": settings.ENGINE_MODE,
        "version": "2.0.0",
    }


# ─── 账号管理 ────────────────────────────────────────

@router.get("/accounts")
async def list_accounts(request: Request, _=Depends(_require_admin)):
    pool = request.app.state.account_pool
    accounts = [acc.to_dict() for acc in pool.all_accounts()]
    return {"accounts": accounts}


@router.post("/accounts")
async def add_account(request: Request, _=Depends(_require_admin)):
    pool = request.app.state.account_pool
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON")

    email = body.get("email", "")
    password = body.get("password", "")
    token = body.get("token", "")

    if not token:
        return JSONResponse({"ok": False, "error": "Token is required"})

    acc = await pool.add_account(email, password, token)
    return {"ok": True, "email": acc.email}


@router.delete("/accounts/{email}")
async def delete_account(email: str, request: Request, _=Depends(_require_admin)):
    pool = request.app.state.account_pool
    removed = await pool.remove_account(email, manual=True)  # 手动删除不触发补号
    if not removed:
        raise HTTPException(404, "Account not found")
    return {"ok": True}


@router.post("/accounts/{email}/verify")
async def verify_account(email: str, request: Request, _=Depends(_require_admin)):
    pool = request.app.state.account_pool
    client = request.app.state.qwen_client
    acc = pool.get_account_by_email(email)
    if not acc:
        raise HTTPException(404, "Account not found")

    valid = await client.verify_token(acc.token)
    if valid:
        pool.mark_valid(acc)
    else:
        pool.mark_error(acc, "auth", "Token verification failed")
    await pool.save()

    return {"valid": valid, "email": email, "status": acc.status}


@router.post("/accounts/{email}/activate")
async def activate_account(email: str, request: Request, _=Depends(_require_admin)):
    pool = request.app.state.account_pool
    client = request.app.state.qwen_client
    acc = pool.get_account_by_email(email)
    if not acc:
        raise HTTPException(404, "Account not found")

    if hasattr(client, "auth_resolver"):
        asyncio.create_task(client.auth_resolver.auto_heal_account(acc))
        return {"ok": True, "pending": True, "message": "激活任务已提交"}
    return {"ok": False, "error": "AuthResolver not available"}


# ─── 原始 JSON 编辑 ──────────────────────────────────

@router.get("/accounts/raw")
async def get_raw_accounts(request: Request, _=Depends(_require_admin)):
    pool = request.app.state.account_pool
    accounts = [acc.to_dict() for acc in pool.all_accounts()]
    content = json.dumps(accounts, ensure_ascii=False, indent=2)
    return {"content": content}


@router.post("/accounts/raw")
async def save_raw_accounts(request: Request, _=Depends(_require_admin)):
    try:
        body = await request.json()
        content = body.get("content", "")
        data = json.loads(content)
        if not isinstance(data, list):
            return JSONResponse({"ok": False, "detail": "Must be a JSON array"}, status_code=400)

        pool = request.app.state.account_pool
        db = request.app.state.accounts_db
        await db.save(data)
        await pool.load()
        return {"ok": True}
    except json.JSONDecodeError as e:
        return JSONResponse({"ok": False, "detail": f"Invalid JSON: {e}"}, status_code=400)
    except Exception as e:
        return JSONResponse({"ok": False, "detail": str(e)}, status_code=500)


# ─── 全量巡检 ────────────────────────────────────────

@router.post("/verify")
async def verify_all(request: Request, _=Depends(_require_admin)):
    pool = request.app.state.account_pool
    client = request.app.state.qwen_client
    accounts = pool.all_accounts()

    async def _verify(acc):
        try:
            valid = await client.verify_token(acc.token)
            if valid:
                pool.mark_valid(acc)
            else:
                pool.mark_error(acc, "auth", "Batch verify failed")
        except Exception as e:
            pool.mark_error(acc, "auth", str(e))

    tasks = [_verify(acc) for acc in accounts]
    await asyncio.gather(*tasks, return_exceptions=True)
    await pool.save()

    return {"ok": True, "verified": len(tasks), "status": pool.status()}


# ─── 批量注册 ────────────────────────────────────────

@router.post("/accounts/batch-register")
async def batch_register(request: Request, _=Depends(_require_admin)):
    from backend.services.register import perform_batch_registration

    try:
        body = await request.json()
    except Exception:
        body = {}

    count = body.get("count", 10)
    threads = body.get("threads", 4)
    provider = body.get("provider", "default")
    max_retries = int(body.get("max_retries", 0))  # 0 = 自动（count*5）

    pool = request.app.state.account_pool

    log.info(f"[Admin] 批量注册请求: count={count} threads={threads} provider={provider} max_retries={max_retries or 'auto'}")

    # 清除之前的停止标志
    _manual_stop_flag.clear()

    # 启动异步后台任务
    asyncio.create_task(
        perform_batch_registration(
            account_pool=pool,
            count=count,
            threads=threads,
            provider=provider,
            moemail_domain=settings.MOEMAIL_DOMAIN,
            moemail_key=settings.MOEMAIL_KEY,
            tempmail_domain=getattr(settings, "TEMPMAIL_DOMAIN", ""),
            tempmail_key=getattr(settings, "TEMPMAIL_KEY", ""),
            stop_flag=_manual_stop_flag,
            max_retries=max_retries,
        )
    )

    return {"ok": True, "message": f"批量注册已启动: {count} 个账号, {threads} 并发, 渠道={provider}"}


@router.post("/accounts/stop-register")
async def stop_register(_=Depends(_require_admin)):
    """停止用户手动触发的批量注册（不影响自动补号和应急补号）"""
    _manual_stop_flag.set()
    log.info("[Admin] 用户请求停止手动注册任务")
    return {"ok": True, "message": "停止信号已发送，已提交的任务将继续完成"}


# ─── API 密钥管理 ─────────────────────────────────────

@router.get("/keys")
async def list_keys(_=Depends(_require_admin)):
    keys = load_api_keys()
    return {"keys": sorted(keys)}


@router.post("/keys")
async def generate_key(_=Depends(_require_admin)):
    global API_KEYS
    new_key = f"sk-{uuid.uuid4().hex}"
    keys = load_api_keys()
    keys.add(new_key)
    save_api_keys(keys)
    # 更新内存中的 API_KEYS
    API_KEYS.clear()
    API_KEYS.update(keys)
    return {"ok": True, "key": new_key}


@router.delete("/keys/{key}")
async def delete_key(key: str, _=Depends(_require_admin)):
    global API_KEYS
    keys = load_api_keys()
    keys.discard(key)
    save_api_keys(keys)
    API_KEYS.clear()
    API_KEYS.update(keys)
    return {"ok": True}


# ─── 设置 ─────────────────────────────────────────────

@router.get("/settings")
async def get_settings(_=Depends(_require_admin)):
    return {
        "max_inflight_per_account": settings.MAX_INFLIGHT_PER_ACCOUNT,
        "engine_mode": settings.ENGINE_MODE,
        "model_aliases": MODEL_MAP,
        "moemail_domain": settings.MOEMAIL_DOMAIN,
        "moemail_key": settings.MOEMAIL_KEY,
        "tempmail_domain": settings.TEMPMAIL_DOMAIN,
        "tempmail_key": settings.TEMPMAIL_KEY,
        # v2 新增
        "auto_replenish": settings.AUTO_REPLENISH,
        "replenish_target": settings.REPLENISH_TARGET,
        "replenish_concurrency": settings.REPLENISH_CONCURRENCY,
        "max_rpm_per_account": settings.MAX_RPM_PER_ACCOUNT,
        "max_tpm_per_account": settings.MAX_TPM_PER_ACCOUNT,
        "cache_ttl_seconds": settings.CACHE_TTL_SECONDS,
        "racing_enabled": settings.RACING_ENABLED,
        # 限流应急补号
        "auto_replenish_on_exhaust": settings.AUTO_REPLENISH_ON_EXHAUST,
        "replenish_exhaust_count": settings.REPLENISH_EXHAUST_COUNT,
        "replenish_exhaust_concurrency": settings.REPLENISH_EXHAUST_CONCURRENCY,
        # 代理池
        "proxy_enabled":  getattr(settings, "PROXY_ENABLED", False),
        "proxy_url":      getattr(settings, "PROXY_URL", ""),
        "proxy_username": getattr(settings, "PROXY_USERNAME", ""),
        "proxy_password": getattr(settings, "PROXY_PASSWORD", ""),
    }


@router.put("/settings")
async def update_settings(request: Request, _=Depends(_require_admin)):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON")

    if "max_inflight_per_account" in body:
        settings.MAX_INFLIGHT_PER_ACCOUNT = int(body["max_inflight_per_account"])
    if "engine_mode" in body:
        settings.ENGINE_MODE = body["engine_mode"]
    if "model_aliases" in body and isinstance(body["model_aliases"], dict):
        MODEL_MAP.update(body["model_aliases"])
    if "moemail_domain" in body:
        settings.MOEMAIL_DOMAIN = body["moemail_domain"]
    if "moemail_key" in body:
        settings.MOEMAIL_KEY = body["moemail_key"]
    if "tempmail_domain" in body:
        settings.TEMPMAIL_DOMAIN = body["tempmail_domain"]
    if "tempmail_key" in body:
        settings.TEMPMAIL_KEY = body["tempmail_key"]
    # v2 新增
    if "auto_replenish" in body:
        settings.AUTO_REPLENISH = bool(body["auto_replenish"])
    if "replenish_target" in body:
        settings.REPLENISH_TARGET = int(body["replenish_target"])
    if "replenish_concurrency" in body:
        settings.REPLENISH_CONCURRENCY = int(body["replenish_concurrency"])
    if "max_rpm_per_account" in body:
        settings.MAX_RPM_PER_ACCOUNT = int(body["max_rpm_per_account"])
    if "max_tpm_per_account" in body:
        settings.MAX_TPM_PER_ACCOUNT = int(body["max_tpm_per_account"])
    if "cache_ttl_seconds" in body:
        settings.CACHE_TTL_SECONDS = int(body["cache_ttl_seconds"])
    if "racing_enabled" in body:
        settings.RACING_ENABLED = bool(body["racing_enabled"])
    # 限流应急补号
    if "auto_replenish_on_exhaust" in body:
        settings.AUTO_REPLENISH_ON_EXHAUST = bool(body["auto_replenish_on_exhaust"])
    if "replenish_exhaust_count" in body:
        settings.REPLENISH_EXHAUST_COUNT = max(1, int(body["replenish_exhaust_count"]))
    if "replenish_exhaust_concurrency" in body:
        settings.REPLENISH_EXHAUST_CONCURRENCY = max(1, int(body["replenish_exhaust_concurrency"]))
    # 代理池
    if "proxy_enabled" in body:
        settings.PROXY_ENABLED = bool(body["proxy_enabled"])
    if "proxy_url" in body:
        settings.PROXY_URL = str(body["proxy_url"]).strip()
    if "proxy_username" in body:
        settings.PROXY_USERNAME = str(body["proxy_username"]).strip()
    if "proxy_password" in body:
        settings.PROXY_PASSWORD = str(body["proxy_password"]).strip()

    # 持久化到 runtime_settings.json
    save_runtime_settings()

    return {"ok": True}


# ─── Pool 实时统计 ──────────────────────────────────────

@router.get("/pool-stats")
async def get_pool_stats(request: Request, _=Depends(_require_admin)):
    pool = request.app.state.account_pool
    import math

    def _sanitize(obj):
        if isinstance(obj, float):
            if math.isinf(obj) or math.isnan(obj):
                return 0.0
            return round(obj, 4)
        if isinstance(obj, dict):
            return {k: _sanitize(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_sanitize(v) for v in obj]
        return obj

    return _sanitize({"accounts": pool.pool_stats(), "summary": pool.status(), "health_history": getattr(request.app.state, "health_snapshot", None) and request.app.state.health_snapshot.history() or []})


# ─── SSE 事件流 ────────────────────────────────────────

@router.get("/events")
async def sse_events(request: Request, _=Depends(_require_admin)):
    pool = request.app.state.account_pool

    async def event_generator():
        while True:
            if await request.is_disconnected():
                break
            event = await pool.get_sse_event(timeout=30)
            if event:
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            else:
                yield f": keepalive\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


# ─── 日志 ──────────────────────────────────────────────

@router.get("/logs")
async def get_logs(_=Depends(_require_admin)):
    from backend.services.log_manager import get_logs
    return {"logs": get_logs()}



# ─── 使用统计 ──────────────────────────────────────────

@router.get("/stats/usage")
async def get_usage_stats(request: Request, start: float = None, end: float = None, _=Depends(_require_admin)):
    """获取使用统计数据，支持按时间段查询"""
    um = request.app.state.usage_manager
    return await um.query(start=start, end=end)


# ─── 代理连通性测试 ──────────────────────────────────────

@router.post("/proxy-test")
async def proxy_test(request: Request, _=Depends(_require_admin)):
    """
    启动无头浏览器，通过代理访问 ipify.org，返回直连 IP 与代理 IP 对比。
    支持 body 传入 {proxy_url, proxy_username, proxy_password}（测试当前表单值，无需先保存）。
    """
    import httpx
    from urllib.parse import urlparse, urlunparse
    from playwright.async_api import async_playwright

    # ── 读取参数：body 优先，fallback 到已保存配置 ──
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    raw_url  = body.get("proxy_url",      "").strip() or getattr(settings, "PROXY_URL", "")
    username = body.get("proxy_username", "").strip() or getattr(settings, "PROXY_USERNAME", "")
    password = body.get("proxy_password", "").strip() or getattr(settings, "PROXY_PASSWORD", "")

    # ── 解析 URL 内联认证 http://user:pass@host:port ──
    if raw_url:
        parsed = urlparse(raw_url)
        if parsed.username and not username:
            username = parsed.username
        if parsed.password and not password:
            password = parsed.password
        # 去掉 URL 里的用户名密码，Playwright 通过独立字段传入
        clean = parsed._replace(netloc=parsed.hostname + (f":{parsed.port}" if parsed.port else ""))
        server_url = urlunparse(clean)
    else:
        server_url = raw_url

    result = {
        "direct_ip": None,
        "proxy_ip":  None,
        "proxy_url": raw_url,
        "ok":        False,
        "error":     None,
    }

    if not server_url:
        result["error"] = "代理地址为空，请先填写代理地址"
        return result

    # 1. 直连 IP（服务器侧）
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get("https://api.ipify.org?format=json")
            result["direct_ip"] = r.json().get("ip")
    except Exception as e:
        result["direct_ip"] = f"获取失败: {e}"

    # 2. 代理 IP（Playwright 浏览器）
    proxy_cfg: dict = {"server": server_url}
    if username:
        proxy_cfg["username"] = username
    if password:
        proxy_cfg["password"] = password

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                proxy=proxy_cfg,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            ctx = await browser.new_context(proxy=proxy_cfg)
            page = await ctx.new_page()
            import re as _re
            proxy_ip = None
            for ip_url in ["http://api.ipify.org", "http://checkip.amazonaws.com", "http://ifconfig.me/ip"]:
                try:
                    await page.goto(ip_url, timeout=15000)
                    # page.content() 返回完整 HTML，覆盖所有格式
                    raw = await page.content()
                    m = _re.search(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', raw)
                    if m:
                        proxy_ip = m.group(1)
                        break
                except Exception:
                    continue
            result["proxy_ip"] = proxy_ip or "获取失败（代理已连接但无法访问外网）"
            await browser.close()

        if result["proxy_ip"] == result["direct_ip"]:
            result["error"] = "代理 IP 与直连 IP 相同，代理可能未生效（检查地址/认证是否正确）"
        else:
            result["ok"] = True
    except Exception as e:
        result["error"] = str(e)

    return result

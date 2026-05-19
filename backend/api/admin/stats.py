"""
stats.py -- 统计与监控端点
"""

import json
import math
import logging
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from backend.core.config import settings
from . import _require_admin

log = logging.getLogger("qwen2api.admin")
router = APIRouter()


@router.get("/system-info")
async def get_system_info(_=Depends(_require_admin)):
    import psutil
    cpu_count = psutil.cpu_count(logical=False) or psutil.cpu_count() or 2
    ram_gb = psutil.virtual_memory().total / (1024 ** 3)
    ram_available_gb = psutil.virtual_memory().available / (1024 ** 3)
    by_ram = max(1, int(ram_available_gb * 0.7 / 0.15))
    by_cpu = max(1, cpu_count * 3)
    recommended = min(by_ram, by_cpu, 20)
    return {
        "cpu_cores": cpu_count,
        "ram_total_gb": round(ram_gb, 1),
        "ram_available_gb": round(ram_available_gb, 1),
        "recommended_threads": max(1, recommended),
        "limits": {"by_ram": min(by_ram, 20), "by_cpu": min(by_cpu, 20)},
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


@router.get("/pool-stats")
async def get_pool_stats(request: Request, _=Depends(_require_admin)):
    pool = request.app.state.account_pool

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

    return _sanitize({
        "accounts": pool.pool_stats(),
        "summary": pool.status(),
        "health_history": getattr(request.app.state, "health_snapshot", None) and request.app.state.health_snapshot.history() or []
    })


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
                yield ": keepalive\n\n"

    return StreamingResponse(
        event_generator(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get("/logs")
async def get_logs(_=Depends(_require_admin)):
    from backend.services.log_manager import get_logs
    return {"logs": get_logs()}


@router.get("/stats/usage")
async def get_usage_stats(request: Request, start: float = None, end: float = None, _=Depends(_require_admin)):
    um = request.app.state.usage_manager
    return await um.query(start=start, end=end)


@router.post("/proxy-test")
async def proxy_test(request: Request, _=Depends(_require_admin)):
    """代理连通性测试。"""
    import httpx
    from urllib.parse import urlparse, urlunparse

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    raw_url = body.get("proxy_url", "").strip() or getattr(settings, "PROXY_URL", "")
    username = body.get("proxy_username", "").strip() or getattr(settings, "PROXY_USERNAME", "")
    password = body.get("proxy_password", "").strip() or getattr(settings, "PROXY_PASSWORD", "")

    if raw_url:
        parsed = urlparse(raw_url)
        if parsed.username and not username:
            username = parsed.username
        if parsed.password and not password:
            password = parsed.password
        clean = parsed._replace(netloc=parsed.hostname + (f":{parsed.port}" if parsed.port else ""))
        server_url = urlunparse(clean)
    else:
        server_url = raw_url

    result = {"direct_ip": None, "proxy_ip": None, "proxy_url": raw_url, "ok": False, "error": None}

    if not server_url:
        result["error"] = "代理地址为空"
        return result

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get("https://api.ipify.org?format=json")
            result["direct_ip"] = r.json().get("ip")
    except Exception as e:
        result["direct_ip"] = f"获取失败: {e}"

    proxy_cfg = {"server": server_url}
    if username:
        proxy_cfg["username"] = username
    if password:
        proxy_cfg["password"] = password

    try:
        from playwright.async_api import async_playwright
        import re as _re
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True, proxy=proxy_cfg, args=["--no-sandbox", "--disable-dev-shm-usage"])
            ctx = await browser.new_context(proxy=proxy_cfg)
            page = await ctx.new_page()
            proxy_ip = None
            for ip_url in ["http://api.ipify.org", "http://checkip.amazonaws.com", "http://ifconfig.me/ip"]:
                try:
                    await page.goto(ip_url, timeout=15000)
                    raw = await page.content()
                    m = _re.search(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', raw)
                    if m:
                        proxy_ip = m.group(1)
                        break
                except Exception:
                    continue
            result["proxy_ip"] = proxy_ip or "获取失败"
            await browser.close()
        if result["proxy_ip"] == result["direct_ip"]:
            result["error"] = "代理 IP 与直连 IP 相同，代理可能未生效"
        else:
            result["ok"] = True
    except Exception as e:
        result["error"] = str(e)

    return result

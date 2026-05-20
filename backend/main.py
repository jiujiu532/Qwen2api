import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

# Windows UTF-8 输出修复
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 将项目根目录加入到 sys.path，解决直接运行 main.py 时找不到 backend 模块的问题
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.core.config import settings
from backend.core.database import AsyncJsonDB
from backend.core.usage import UsageManager
from backend.core.browser_engine import BrowserEngine
from backend.core.httpx_engine import HttpxEngine
from backend.core.hybrid_engine import HybridEngine
from backend.core.account_pool import AccountPool
from backend.core.health_snapshot import HealthSnapshotManager
from backend.services.qwen_client import QwenClient
from backend.api import admin, chat, probes, anthropic, embeddings, images, responses
from backend.services.garbage_collector import garbage_collect_chats
from backend.services.log_manager import setup_log_capturing

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("qwen2api")

# 启动时安全校验
from backend.core.config import validate_security_config
validate_security_config()

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting qwen2API v2.0 Enterprise Gateway...")
    setup_log_capturing()

    app.state.accounts_db = AsyncJsonDB(settings.ACCOUNTS_FILE, default_data=[])
    app.state.users_db = AsyncJsonDB(settings.USERS_FILE, default_data=[])
    app.state.captures_db = AsyncJsonDB(settings.CAPTURES_FILE, default_data=[])

    browser_engine = BrowserEngine(pool_size=settings.BROWSER_POOL_SIZE)
    httpx_engine = HttpxEngine(base_url="https://chat.qwen.ai")

    if settings.ENGINE_MODE == "httpx":
        engine = httpx_engine
        log.info("引擎模式: httpx 直连")
    elif settings.ENGINE_MODE == "hybrid":
        engine = HybridEngine(browser_engine, httpx_engine)
        log.info("引擎模式: Hybrid (api_call=httpx优先, fetch_chat=browser)")
    else:
        engine = browser_engine
        log.info("引擎模式: Camoufox 浏览器")

    app.state.browser_engine = browser_engine
    app.state.httpx_engine = httpx_engine
    app.state.gateway_engine = engine
    app.state.account_pool = AccountPool(app.state.accounts_db, settings=settings)
    app.state.qwen_client = QwenClient(engine, app.state.account_pool)

    await app.state.account_pool.load()
    app.state.account_pool.start_background_tasks()
    await engine.start()

    # 使用统计追踪
    app.state.usage_manager = UsageManager()
    await app.state.usage_manager.start()

    # 健康快照追踪
    from backend.core.config import DATA_DIR
    app.state.health_snapshot = HealthSnapshotManager(app.state.account_pool, DATA_DIR)
    await app.state.health_snapshot.start()

    asyncio.create_task(garbage_collect_chats(app.state.qwen_client))

    # 启动自动补号守护循环
    from backend.services.register import perform_batch_registration
    from backend.core.config import settings as _settings

    async def _register_func(count: int, concurrency: int) -> int:
        """适配 perform_batch_registration 的返回值，供补号循环使用"""
        # 每次调用时重新检测设置，确保运行时修改即时生效
        moemail_domain = (_settings.MOEMAIL_DOMAIN or "").strip()
        moemail_key = (_settings.MOEMAIL_KEY or "").strip()
        tempmail_domain = getattr(_settings, "TEMPMAIL_DOMAIN", "") or ""
        tempmail_domain = tempmail_domain.strip()
        tempmail_key = getattr(_settings, "TEMPMAIL_KEY", "") or ""
        tempmail_key = tempmail_key.strip()

        # 必须有配置的邮箱渠道才能自动补号
        provider = getattr(_settings, "REPLENISH_PROVIDER", "").strip()
        if not provider:
            log.warning("[AutoReplenish] 未配置补号渠道，跳过自动补号")
            return 0

        log.info(f"[AutoReplenish] 使用邮箱渠道: {provider} "
                 f"(moemail={'✓' if moemail_domain else '✗'}, "
                 f"tempmail={'✓' if tempmail_domain else '✗'})")

        result = await perform_batch_registration(
            app.state.account_pool,
            count=count,
            threads=concurrency,
            provider=provider,
            moemail_domain=moemail_domain,
            moemail_key=moemail_key,
            tempmail_domain=tempmail_domain,
            tempmail_key=tempmail_key,
        )
        return result.get("success", 0)

    asyncio.create_task(app.state.account_pool.start_replenishment_loop(_register_func))

    yield

    log.info("Shutting down gateway...")
    await app.state.health_snapshot.stop()
    await app.state.usage_manager.stop()
    await app.state.gateway_engine.stop()

app = FastAPI(title="qwen2API Enterprise Gateway", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载路由
app.include_router(chat.router, tags=["OpenAI Compatible"])
app.include_router(responses.router, tags=["OpenAI Responses API"])
app.include_router(images.router, tags=["Image Generation"])
app.include_router(anthropic.router, tags=["Claude Compatible"])
app.include_router(embeddings.router, tags=["Embeddings"])
app.include_router(probes.router, tags=["Probes"])
app.include_router(admin.router, prefix="/api/admin", tags=["Dashboard Admin"])

# ── 静态管理面板（纯 HTML，仿 grok2api）──────────────────────────────────────
from fastapi.responses import FileResponse
from pathlib import Path

STATICS_DIR = Path(__file__).resolve().parent.parent / "statics"

@app.get("/admin/login", include_in_schema=False)
async def admin_login_page():
    return FileResponse(STATICS_DIR / "login.html")

@app.get("/admin/accounts", include_in_schema=False)
async def admin_accounts_page():
    return FileResponse(STATICS_DIR / "accounts.html")

@app.get("/admin/config", include_in_schema=False)
async def admin_config_page():
    return FileResponse(STATICS_DIR / "config.html")

@app.get("/admin/register", include_in_schema=False)
async def admin_register_page():
    return FileResponse(STATICS_DIR / "register.html")

@app.get("/admin/cache", include_in_schema=False)
async def admin_cache_page():
    return FileResponse(STATICS_DIR / "cache.html")

@app.get("/admin", include_in_schema=False)
async def admin_root():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/admin/login")

@app.get("/", include_in_schema=False)
async def site_root():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/admin/login")

# ── WebUI 路由 ──────────────────────────────────────────────────────────────
WEBUI_DIR = STATICS_DIR / "webui"

@app.get("/webui", include_in_schema=False)
async def webui_root():
    from fastapi.responses import RedirectResponse
    if not settings.WEBUI_ENABLED:
        raise HTTPException(status_code=404, detail="Not Found")
    return RedirectResponse("/webui/login")

@app.get("/webui/login", include_in_schema=False)
async def webui_login_page():
    if not settings.WEBUI_ENABLED:
        raise HTTPException(status_code=404, detail="Not Found")
    return FileResponse(WEBUI_DIR / "login.html")

@app.get("/webui/chat", include_in_schema=False)
async def webui_chat_page():
    if not settings.WEBUI_ENABLED:
        raise HTTPException(status_code=404, detail="Not Found")
    return FileResponse(WEBUI_DIR / "chat.html")

if STATICS_DIR.exists():
    app.mount("/statics", StaticFiles(directory=str(STATICS_DIR)), name="statics")

@app.get("/api", tags=["System"])
async def root():
    return {
        "status": "qwen2API Enterprise Gateway is running",
        "docs": "/docs",
        "version": "2.0.0"
    }

# ── 图片代理路由 ──────────────────────────────────────────────────────────────
from fastapi.responses import Response
from backend.services.image_proxy import get_image_path, get_image_mime

@app.get("/v1/files/image", include_in_schema=False)
async def serve_image(id: str = ""):
    """返回本地缓存的图片"""
    import re
    if not id or not re.fullmatch(r"[0-9a-f]{16,36}", id):
        raise HTTPException(status_code=400, detail="Invalid file ID")
    path = get_image_path(id)
    if not path:
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(path, media_type=get_image_mime(path),
                        headers={"Cache-Control": "public, max-age=86400"})

@app.get("/proxy/image/{image_id}", include_in_schema=False)
async def proxy_image_legacy(image_id: str):
    """兼容旧的代理 URL 格式"""
    path = get_image_path(image_id)
    if not path:
        raise HTTPException(status_code=404, detail="Image not found or expired")
    return FileResponse(path, media_type=get_image_mime(path),
                        headers={"Cache-Control": "public, max-age=86400"})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=settings.PORT, workers=1)

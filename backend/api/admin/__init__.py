"""
admin/ -- 管理后台 API（拆分为多个子模块）
路由聚合 + 共享鉴权依赖。
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from backend.core.config import settings

router = APIRouter()


def _require_admin(request: Request):
    """共享的管理员鉴权依赖。"""
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


# 挂载子模块路由
from .accounts import router as accounts_router
from .keys import router as keys_router
from .settings import router as settings_router
from .stats import router as stats_router

router.include_router(accounts_router)
router.include_router(keys_router)
router.include_router(settings_router)
router.include_router(stats_router)

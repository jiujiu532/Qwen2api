"""
auth.py -- 统一鉴权模块
所有 API 端点共用此逻辑，避免鉴权不一致或绕过。
"""

import logging
from fastapi import Request, HTTPException
from backend.core.config import settings, API_KEYS

log = logging.getLogger("qwen2api.auth")


def extract_token(request: Request) -> str:
    """从请求中提取 API Key（支持多种传递方式）。"""
    # 1. Authorization: Bearer <token>
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        if token:
            return token

    # 2. x-api-key header (Anthropic 风格)
    xkey = request.headers.get("x-api-key", "").strip()
    if xkey:
        return xkey

    # 3. query param: key 或 api_key (Gemini 风格)
    token = request.query_params.get("key", "").strip()
    if token:
        return token
    token = request.query_params.get("api_key", "").strip()
    if token:
        return token

    return ""


def verify_api_key(request: Request) -> str:
    """验证请求携带的 API Key，返回有效 token。无效则抛出 401。

    鉴权规则：
    - 如果 API_KEYS 集合非空：token 必须是 ADMIN_KEY 或在 API_KEYS 中
    - 如果 API_KEYS 集合为空：token 必须等于 ADMIN_KEY（不允许无密钥访问）
    """
    token = extract_token(request)

    if not token:
        raise HTTPException(
            status_code=401,
            detail={"error": {"message": "Missing API key", "type": "authentication_error"}}
        )

    admin_k = settings.ADMIN_KEY

    if API_KEYS:
        # 有配置的 key 列表：admin key 或列表中的 key 均可
        if token == admin_k or token in API_KEYS:
            return token
    else:
        # 未配置 key 列表：仅 admin key 可用
        if token == admin_k:
            return token

    raise HTTPException(
        status_code=401,
        detail={"error": {"message": "Invalid API key", "type": "authentication_error"}}
    )

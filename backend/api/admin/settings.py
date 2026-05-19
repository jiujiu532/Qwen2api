"""
settings.py -- 设置管理端点
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from backend.core.config import settings, MODEL_MAP, save_runtime_settings, DEFAULT_MODEL_ALIASES
from . import _require_admin

log = logging.getLogger("qwen2api.admin")
router = APIRouter()


@router.get("/settings")
async def get_settings(_=Depends(_require_admin)):
    merged_aliases = dict(DEFAULT_MODEL_ALIASES)
    merged_aliases.update(MODEL_MAP)
    return {
        "admin_key": settings.ADMIN_KEY,
        "max_inflight_per_account": settings.MAX_INFLIGHT_PER_ACCOUNT,
        "engine_mode": settings.ENGINE_MODE,
        "model_aliases": merged_aliases,
        "moemail_domain": settings.MOEMAIL_DOMAIN,
        "moemail_key": settings.MOEMAIL_KEY,
        "tempmail_domain": settings.TEMPMAIL_DOMAIN,
        "tempmail_key": settings.TEMPMAIL_KEY,
        "auto_replenish": settings.AUTO_REPLENISH,
        "replenish_target": settings.REPLENISH_TARGET,
        "replenish_concurrency": settings.REPLENISH_CONCURRENCY,
        "max_rpm_per_account": settings.MAX_RPM_PER_ACCOUNT,
        "max_tpm_per_account": settings.MAX_TPM_PER_ACCOUNT,
        "cache_ttl_seconds": settings.CACHE_TTL_SECONDS,
        "racing_enabled": settings.RACING_ENABLED,
        "auto_replenish_on_exhaust": settings.AUTO_REPLENISH_ON_EXHAUST,
        "replenish_exhaust_count": settings.REPLENISH_EXHAUST_COUNT,
        "replenish_exhaust_concurrency": settings.REPLENISH_EXHAUST_CONCURRENCY,
        "proxy_enabled": getattr(settings, "PROXY_ENABLED", False),
        "proxy_url": getattr(settings, "PROXY_URL", ""),
        "proxy_username": getattr(settings, "PROXY_USERNAME", ""),
        "proxy_password": getattr(settings, "PROXY_PASSWORD", ""),
        "default_stream": getattr(settings, "DEFAULT_STREAM", True),
        "log_level": getattr(settings, "LOG_LEVEL", "INFO"),
        "log_max_days": getattr(settings, "LOG_MAX_DAYS", 7),
    }


@router.get("/settings/defaults")
async def get_default_settings(_=Depends(_require_admin)):
    """返回所有配置项的默认值"""
    return {
        "admin_key": "123456",
        "max_inflight_per_account": 1,
        "engine_mode": "hybrid",
        "model_aliases": dict(DEFAULT_MODEL_ALIASES),
        "moemail_domain": "",
        "moemail_key": "",
        "tempmail_domain": "",
        "tempmail_key": "",
        "auto_replenish": False,
        "replenish_target": 30,
        "replenish_concurrency": 3,
        "max_rpm_per_account": 50,
        "max_tpm_per_account": 500000,
        "cache_ttl_seconds": 60,
        "racing_enabled": False,
        "auto_replenish_on_exhaust": True,
        "replenish_exhaust_count": 10,
        "replenish_exhaust_concurrency": 3,
        "proxy_enabled": False,
        "proxy_url": "",
        "proxy_username": "",
        "proxy_password": "",
        "default_stream": True,
        "log_level": "INFO",
        "log_max_days": 7,
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
    if "admin_key" in body:
        new_key = str(body["admin_key"]).strip()
        if new_key:
            settings.ADMIN_KEY = new_key
            log.info("[Admin] ADMIN_KEY 已更新")
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
    if "auto_replenish_on_exhaust" in body:
        settings.AUTO_REPLENISH_ON_EXHAUST = bool(body["auto_replenish_on_exhaust"])
    if "replenish_exhaust_count" in body:
        settings.REPLENISH_EXHAUST_COUNT = max(1, int(body["replenish_exhaust_count"]))
    if "replenish_exhaust_concurrency" in body:
        settings.REPLENISH_EXHAUST_CONCURRENCY = max(1, int(body["replenish_exhaust_concurrency"]))
    if "proxy_enabled" in body:
        settings.PROXY_ENABLED = bool(body["proxy_enabled"])
    if "proxy_url" in body:
        settings.PROXY_URL = str(body["proxy_url"]).strip()
    if "proxy_username" in body:
        settings.PROXY_USERNAME = str(body["proxy_username"]).strip()
    if "proxy_password" in body:
        settings.PROXY_PASSWORD = str(body["proxy_password"]).strip()
    if "default_stream" in body:
        settings.DEFAULT_STREAM = bool(body["default_stream"])
    if "log_level" in body:
        settings.LOG_LEVEL = str(body["log_level"]).upper()
    if "log_max_days" in body:
        settings.LOG_MAX_DAYS = max(1, int(body["log_max_days"]))

    save_runtime_settings()
    return {"ok": True}

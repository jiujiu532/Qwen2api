import os
import json
import logging
from pathlib import Path
from pydantic_settings import BaseSettings
from typing import Dict, Set

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"

class Settings(BaseSettings):
    # 服务配置
    PORT: int = int(os.getenv("PORT", 7860))
    WORKERS: int = int(os.getenv("WORKERS", 3))
    ADMIN_KEY: str = os.getenv("ADMIN_KEY", "123456")
    REGISTER_SECRET: str = os.getenv("REGISTER_SECRET", "")
    
    # MoeMail 自建配置
    MOEMAIL_DOMAIN: str = os.getenv("MOEMAIL_DOMAIN", "")
    MOEMAIL_KEY: str = os.getenv("MOEMAIL_KEY", "")

    # TempMail (awsl.uk) 自建配置
    TEMPMAIL_DOMAIN: str = os.getenv("TEMPMAIL_DOMAIN", "")
    TEMPMAIL_KEY: str = os.getenv("TEMPMAIL_KEY", "")

    # 引擎模式：httpx（快速直连）、browser（浏览器指纹，防封）或 hybrid（混合）
    ENGINE_MODE: str = os.getenv("ENGINE_MODE", "hybrid")
    NATIVE_TOOL_PASSTHROUGH: bool = os.getenv("NATIVE_TOOL_PASSTHROUGH", "true").lower() in ("1", "true", "yes", "on")
    # 浏览器引擎配置
    BROWSER_POOL_SIZE: int = int(os.getenv("BROWSER_POOL_SIZE", 2))
    MAX_INFLIGHT_PER_ACCOUNT: int = int(os.getenv("MAX_INFLIGHT", 1))
    STREAM_KEEPALIVE_INTERVAL: int = int(os.getenv("STREAM_KEEPALIVE_INTERVAL", 5))

    # 容灾与限流
    MAX_RETRIES: int = 2
    TOOL_MAX_RETRIES: int = 3
    EMPTY_RESPONSE_RETRIES: int = 1
    ACCOUNT_MIN_INTERVAL_MS: int = int(os.getenv("ACCOUNT_MIN_INTERVAL_MS", 1200))
    REQUEST_JITTER_MIN_MS: int = int(os.getenv("REQUEST_JITTER_MIN_MS", 120))
    REQUEST_JITTER_MAX_MS: int = int(os.getenv("REQUEST_JITTER_MAX_MS", 360))
    RATE_LIMIT_BASE_COOLDOWN: int = int(os.getenv("RATE_LIMIT_BASE_COOLDOWN", 600))
    RATE_LIMIT_MAX_COOLDOWN: int = int(os.getenv("RATE_LIMIT_MAX_COOLDOWN", 3600))
    RATE_LIMIT_COOLDOWN: int = RATE_LIMIT_BASE_COOLDOWN

    # AccountPool v2 — 高并发调度
    MAX_RPM_PER_ACCOUNT: int = int(os.getenv("MAX_RPM_PER_ACCOUNT", 50))
    MAX_TPM_PER_ACCOUNT: int = int(os.getenv("MAX_TPM_PER_ACCOUNT", 500000))
    CIRCUIT_BREAKER_THRESHOLD: int = int(os.getenv("CIRCUIT_BREAKER_THRESHOLD", 5))
    ACCOUNT_WARMUP_MINUTES: int = int(os.getenv("ACCOUNT_WARMUP_MINUTES", 120))

    # 自动补号
    AUTO_REPLENISH: bool = os.getenv("AUTO_REPLENISH", "false").lower() in ("1", "true", "yes", "on")
    REPLENISH_TARGET: int = int(os.getenv("REPLENISH_TARGET", 30))
    REPLENISH_CONCURRENCY: int = int(os.getenv("REPLENISH_CONCURRENCY", 3))

    # 限流应急补号
    AUTO_REPLENISH_ON_EXHAUST: bool = os.getenv("AUTO_REPLENISH_ON_EXHAUST", "true").lower() in ("1", "true", "yes", "on")
    REPLENISH_EXHAUST_COUNT: int = int(os.getenv("REPLENISH_EXHAUST_COUNT", 10))
    REPLENISH_EXHAUST_CONCURRENCY: int = int(os.getenv("REPLENISH_EXHAUST_CONCURRENCY", 3))

    # 响应缓存
    CACHE_TTL_SECONDS: int = int(os.getenv("CACHE_TTL_SECONDS", 60))
    CACHE_MAX_SIZE: int = int(os.getenv("CACHE_MAX_SIZE", 500))

    # 竞速模式
    RACING_ENABLED: bool = os.getenv("RACING_ENABLED", "false").lower() in ("1", "true", "yes", "on")

    # 注册代理池（用于绕过 WAF 频率限制）
    PROXY_ENABLED: bool = os.getenv("PROXY_ENABLED", "false").lower() in ("1", "true", "yes", "on")
    PROXY_URL: str = os.getenv("PROXY_URL", "")              # e.g. http://host:port  socks5://host:port
    PROXY_USERNAME: str = os.getenv("PROXY_USERNAME", "")   # 为空则无需认证
    PROXY_PASSWORD: str = os.getenv("PROXY_PASSWORD", "")   # 为空则无需认证


    # 数据文件路径
    ACCOUNTS_FILE: str = os.getenv("ACCOUNTS_FILE", str(DATA_DIR / "accounts.json"))
    USERS_FILE: str = os.getenv("USERS_FILE", str(DATA_DIR / "users.json"))
    CAPTURES_FILE: str = os.getenv("CAPTURES_FILE", str(DATA_DIR / "captures.json"))
    CONFIG_FILE: str = os.getenv("CONFIG_FILE", str(DATA_DIR / "config.json"))

    class Config:
        env_file = ".env"

API_KEYS_FILE = DATA_DIR / "api_keys.json"

def load_api_keys() -> set:
    if API_KEYS_FILE.exists():
        try:
            with open(API_KEYS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data.get("keys", []))
        except Exception:
            pass
    return set()

def save_api_keys(keys: set):
    API_KEYS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(API_KEYS_FILE, "w", encoding="utf-8") as f:
        json.dump({"keys": list(keys)}, f, indent=2)

# 在内存中存储管理的 API Keys
API_KEYS = load_api_keys()

VERSION = "2.0.0"

settings = Settings()

# ── 运行时设置持久化（UI 层修改的设置保存到 config.json）──
_RUNTIME_CONFIG_FILE = DATA_DIR / "runtime_settings.json"
_PERSIST_KEYS = [
    "AUTO_REPLENISH", "REPLENISH_TARGET", "REPLENISH_CONCURRENCY",
    "AUTO_REPLENISH_ON_EXHAUST", "REPLENISH_EXHAUST_COUNT", "REPLENISH_EXHAUST_CONCURRENCY",
    "MAX_INFLIGHT_PER_ACCOUNT", "MAX_RPM_PER_ACCOUNT", "MAX_TPM_PER_ACCOUNT",
    "CACHE_TTL_SECONDS", "RACING_ENABLED", "ENGINE_MODE",
    "MOEMAIL_DOMAIN", "MOEMAIL_KEY", "TEMPMAIL_DOMAIN", "TEMPMAIL_KEY",
    "PROXY_ENABLED", "PROXY_URL", "PROXY_USERNAME", "PROXY_PASSWORD",
]

def save_runtime_settings():
    """将 UI 修改的运行时设置持久化到文件"""
    data = {}
    for key in _PERSIST_KEYS:
        val = getattr(settings, key, None)
        if val is not None:
            data[key] = val
    try:
        _RUNTIME_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_RUNTIME_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logging.getLogger("qwen2api").warning(f"保存运行时设置失败: {e}")

def _load_runtime_settings():
    """启动时从文件恢复 UI 修改的运行时设置"""
    if not _RUNTIME_CONFIG_FILE.exists():
        return
    try:
        with open(_RUNTIME_CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        for key, val in data.items():
            if key in _PERSIST_KEYS and hasattr(settings, key):
                expected_type = type(getattr(settings, key))
                try:
                    setattr(settings, key, expected_type(val))
                except (ValueError, TypeError):
                    pass
        logging.getLogger("qwen2api").info(f"[Config] 已从 runtime_settings.json 恢复 {len(data)} 项运行时设置")
    except Exception as e:
        logging.getLogger("qwen2api").warning(f"加载运行时设置失败: {e}")

_load_runtime_settings()

# 全局映射
MODEL_MAP = {
    # OpenAI
    "gpt-4o":            "qwen3.6-plus",
    "gpt-4o-mini":       "qwen3.6-plus",
    "gpt-4-turbo":       "qwen3.6-plus",
    "gpt-4":             "qwen3.6-plus",
    "gpt-4.1":           "qwen3.6-plus",
    "gpt-4.1-mini":      "qwen3.6-plus",
    "gpt-3.5-turbo":     "qwen3.6-plus",
    "gpt-5":             "qwen3.6-plus",
    "o1":                "qwen3.6-plus",
    "o1-mini":           "qwen3.6-plus",
    "o3":                "qwen3.6-plus",
    "o3-mini":           "qwen3.6-plus",
    # Anthropic
    "claude-opus-4-6":           "qwen3.6-plus",
    "claude-sonnet-4-6":         "qwen3.6-plus",
    "claude-sonnet-4-5":         "qwen3.6-plus",
    "claude-3-opus":             "qwen3.6-plus",
    "claude-3-5-sonnet":         "qwen3.6-plus",
    "claude-3-5-sonnet-latest":  "qwen3.6-plus",
    "claude-3-sonnet":           "qwen3.6-plus",
    "claude-3-haiku":            "qwen3.6-plus",
    "claude-3-5-haiku":          "qwen3.6-plus",
    "claude-3-5-haiku-latest":   "qwen3.6-plus",
    "claude-haiku-4-5":          "qwen3.6-plus",
    # Gemini
    "gemini-2.5-pro":    "qwen3.6-plus",
    "gemini-2.5-flash":  "qwen3.6-plus",
    "gemini-1.5-pro":    "qwen3.6-plus",
    "gemini-1.5-flash":  "qwen3.6-plus",
    # Qwen aliases
    "qwen":              "qwen3.6-plus",
    "qwen-max":          "qwen3.6-plus",
    "qwen-plus":         "qwen3.6-plus",
    "qwen-turbo":        "qwen3.6-plus",
    # DeepSeek
    "deepseek-chat":     "qwen3.6-plus",
    "deepseek-reasoner": "qwen3.6-plus",
}

# 图片生成沿用网页当前真实可用的基础模型，不再写死 wanx 模型名
IMAGE_MODEL_DEFAULT = "qwen3.6-plus"

def resolve_model(name: str) -> str:
    return MODEL_MAP.get(name, name)

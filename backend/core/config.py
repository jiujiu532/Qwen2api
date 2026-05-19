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
    ADMIN_KEY: str = os.getenv("ADMIN_KEY", "123456")  # 默认管理密钥
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
    # 默认流式回复：True=默认流式，False=看客户端 stream 字段
    DEFAULT_STREAM: bool = os.getenv("DEFAULT_STREAM", "true").lower() in ("1", "true", "yes", "on")

    # 容灾与限流
    MAX_RETRIES: int = 3
    TOOL_MAX_RETRIES: int = 4
    EMPTY_RESPONSE_RETRIES: int = 1
    # 思考模式：True=默认开启（慢但质量高），False=默认关闭（快但可能质量略低）
    DEFAULT_THINKING_ENABLED: bool = os.getenv("DEFAULT_THINKING_ENABLED", "false").lower() in ("1", "true", "yes", "on")
    ACCOUNT_MIN_INTERVAL_MS: int = int(os.getenv("ACCOUNT_MIN_INTERVAL_MS", 300))
    REQUEST_JITTER_MIN_MS: int = int(os.getenv("REQUEST_JITTER_MIN_MS", 30))
    REQUEST_JITTER_MAX_MS: int = int(os.getenv("REQUEST_JITTER_MAX_MS", 100))
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

    # 日志配置
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_MAX_DAYS: int = int(os.getenv("LOG_MAX_DAYS", 7))


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
    "ADMIN_KEY",
    "AUTO_REPLENISH", "REPLENISH_TARGET", "REPLENISH_CONCURRENCY",
    "AUTO_REPLENISH_ON_EXHAUST", "REPLENISH_EXHAUST_COUNT", "REPLENISH_EXHAUST_CONCURRENCY",
    "MAX_INFLIGHT_PER_ACCOUNT", "MAX_RPM_PER_ACCOUNT", "MAX_TPM_PER_ACCOUNT",
    "CACHE_TTL_SECONDS", "RACING_ENABLED", "ENGINE_MODE", "DEFAULT_STREAM",
    "MOEMAIL_DOMAIN", "MOEMAIL_KEY", "TEMPMAIL_DOMAIN", "TEMPMAIL_KEY",
    "PROXY_ENABLED", "PROXY_URL", "PROXY_USERNAME", "PROXY_PASSWORD",
    "LOG_LEVEL", "LOG_MAX_DAYS",
]

def save_runtime_settings():
    """将 UI 修改的运行时设置持久化到文件"""
    data = {}
    for key in _PERSIST_KEYS:
        val = getattr(settings, key, None)
        if val is not None:
            data[key] = val
    # MODEL_MAP 单独持久化
    data["MODEL_MAP"] = dict(MODEL_MAP)
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
            if key == "MODEL_MAP" and isinstance(val, dict):
                MODEL_MAP.clear()
                MODEL_MAP.update(val)
                continue
            if key in _PERSIST_KEYS and hasattr(settings, key):
                expected_type = type(getattr(settings, key))
                try:
                    setattr(settings, key, expected_type(val))
                except (ValueError, TypeError):
                    pass
        logging.getLogger("qwen2api").info(f"[Config] 已从 runtime_settings.json 恢复 {len(data)} 项运行时设置")
    except Exception as e:
        logging.getLogger("qwen2api").warning(f"加载运行时设置失败: {e}")

# ── Qwen 官网内置可用模型 ──────────────────────────────────────────────────────
BUILTIN_MODELS = [
    "qwen3.6-plus",
    "qwen3.6-plus-thinking",
    "qwen3.6-plus-nothinking",
    "qwen3.6-max-preview",
    "qwen3.6-max-preview-thinking",
    "qwen3.6-max-preview-nothinking",
    "qwen3.6-27b",
    "qwen3.6-27b-thinking",
    "qwen3.6-27b-nothinking",
    # Qwen 3.7 系列（仅支持思考模式，真实 ID 是 invite-beta 格式）
    "qwen3.7-max-preview",
    "qwen3.7-plus-preview",
]

# 默认模型（未知模型名的 fallback）
DEFAULT_MODEL = "qwen3.6-plus"

# 思考模式后缀
NOTHINKING_SUFFIX = "-nothinking"
THINKING_SUFFIX = "-thinking"

# ── 默认别名映射（常见 OpenAI/Claude/Gemini 模型名 -> Qwen 模型）──────────────
DEFAULT_MODEL_ALIASES: dict[str, str] = {
    # OpenAI 系列
    "gpt-4o": "qwen3.6-plus",
    "gpt-4o-mini": "qwen3.6-27b",
    "gpt-4-turbo": "qwen3.6-plus",
    "gpt-4": "qwen3.6-plus",
    "gpt-4.1": "qwen3.6-plus",
    "gpt-4.1-mini": "qwen3.6-27b",
    "gpt-4.1-nano": "qwen3.6-27b",
    "gpt-3.5-turbo": "qwen3.6-27b",
    "gpt-3.5": "qwen3.6-27b",
    "o1": "qwen3.6-max-preview",
    "o1-mini": "qwen3.6-plus",
    "o1-preview": "qwen3.6-max-preview",
    "o3": "qwen3.6-max-preview",
    "o3-mini": "qwen3.6-plus",
    "o4-mini": "qwen3.6-plus",
    # Claude 系列
    "claude-3-5-sonnet-latest": "qwen3.6-max-preview",
    "claude-3-5-sonnet-20241022": "qwen3.6-max-preview",
    "claude-3-5-haiku-latest": "qwen3.6-plus",
    "claude-3-opus-latest": "qwen3.6-max-preview",
    "claude-3-sonnet-20240229": "qwen3.6-plus",
    "claude-3-haiku-20240307": "qwen3.6-27b",
    "claude-sonnet-4-20250514": "qwen3.6-max-preview",
    "claude-haiku-4-20250514": "qwen3.6-plus",
    # Gemini 系列
    "gemini-2.5-pro": "qwen3.6-max-preview",
    "gemini-2.5-flash": "qwen3.6-plus",
    "gemini-2.0-flash": "qwen3.6-plus",
    "gemini-1.5-pro": "qwen3.6-plus",
    "gemini-1.5-flash": "qwen3.6-27b",
    "gemini-pro": "qwen3.6-plus",
    # DeepSeek 系列
    "deepseek-chat": "qwen3.6-plus",
    "deepseek-reasoner": "qwen3.6-max-preview",
    "deepseek-coder": "qwen3.6-plus",
    # Qwen 旧名/别名
    "qwen-plus": "qwen3.6-plus",
    "qwen-max": "qwen3.6-max-preview",
    "qwen-turbo": "qwen3.6-27b",
    "qwen-long": "qwen3.6-plus",
    "qwen-coder-plus": "qwen3.6-plus",
    "qwq-plus": "qwen3.6-max-preview",
    "qwq-max": "qwen3.6-max-preview",
}

# 用户自定义映射（管理后台配置，优先级最高）
MODEL_MAP: dict = {}

# 启动时从持久化文件恢复（包括 MODEL_MAP）
_load_runtime_settings()

# 图片生成沿用网页当前真实可用的基础模型
IMAGE_MODEL_DEFAULT = "qwen3.6-plus"


def resolve_model(name: str) -> str:
    """解析模型名，返回 Qwen 真实模型名。
    
    -nothinking / -thinking 后缀会被剥离，真实模型名传给 Qwen。
    思考模式由 resolve_model_thinking() 单独判断。
    """
    # 1. 用户自定义映射（最高优先级）
    if name in MODEL_MAP:
        resolved = MODEL_MAP[name]
        if resolved.endswith(NOTHINKING_SUFFIX):
            return resolved[:-len(NOTHINKING_SUFFIX)]
        if resolved.endswith(THINKING_SUFFIX):
            return resolved[:-len(THINKING_SUFFIX)]
        return resolved
    # 2. 剥离后缀再查
    base_name = name
    if name.endswith(NOTHINKING_SUFFIX):
        base_name = name[:-len(NOTHINKING_SUFFIX)]
    elif name.endswith(THINKING_SUFFIX):
        base_name = name[:-len(THINKING_SUFFIX)]
    # 3. 默认别名映射
    if base_name in DEFAULT_MODEL_ALIASES:
        return DEFAULT_MODEL_ALIASES[base_name]
    # 4. 如果本身就是内置真实模型名
    real_models = {"qwen3.6-plus", "qwen3.6-max-preview", "qwen3.6-27b", "qwen3.7-max-preview", "qwen3.7-plus-preview"}
    if base_name in real_models:
        # Qwen 3.7 系列的真实 ID 是 invite-beta 格式
        qwen37_map = {
            "qwen3.7-max-preview": "qwen-latest-series-invite-beta-v24",
            "qwen3.7-plus-preview": "qwen-latest-series-invite-beta-v16",
        }
        return qwen37_map.get(base_name, base_name)
    # 5. 都不认识，用默认模型
    return DEFAULT_MODEL


def resolve_model_thinking(name: str) -> bool | None:
    """根据模型名判断思考模式。
    
    -nothinking 后缀 = False（快速模式，关闭思考）
    -thinking 后缀 = True（强制思考模式）
    无后缀 = None（自动模式，由 Qwen 决定）
    Qwen 3.7 系列 = 始终 True（仅支持思考模式）
    """
    if name in MODEL_MAP:
        resolved = MODEL_MAP[name]
        if resolved.endswith(NOTHINKING_SUFFIX):
            return False
        if resolved.endswith(THINKING_SUFFIX):
            return True
    if name.endswith(NOTHINKING_SUFFIX):
        return False
    if name.endswith(THINKING_SUFFIX):
        return True
    # Qwen 3.7 系列仅支持思考模式
    if "qwen3.7" in name:
        return True
    return None  # 自动模式


def get_all_available_models() -> list[str]:
    """获取所有可用模型名（内置 + 默认别名 + 用户自定义）。"""
    all_names = set(BUILTIN_MODELS)
    all_names.update(DEFAULT_MODEL_ALIASES.keys())
    all_names.update(MODEL_MAP.keys())
    all_names.update(MODEL_MAP.values())
    return sorted(all_names)


def validate_security_config():
    """启动时校验安全相关配置。"""
    _log = logging.getLogger("qwen2api.config")
    if not settings.ADMIN_KEY:
        _log.warning("[Security] ADMIN_KEY 未配置，使用默认值 123456")
        settings.ADMIN_KEY = "123456"

"""
token_calc.py — 精确 Token 计算 (tiktoken cl100k_base)
使用 OpenAI tiktoken 库的 cl100k_base 编码，与 Qwen 使用的 BPE 词表高度一致。
"""

import logging

log = logging.getLogger("qwen2api.token_calc")

# ── 缓存编码器（单例，线程安全）─────────────────────────────
_encoder = None


def _get_encoder():
    global _encoder
    if _encoder is None:
        try:
            import tiktoken
            _encoder = tiktoken.get_encoding("cl100k_base")
            log.info("[TokenCalc] 使用 tiktoken cl100k_base 精确计算 Token")
        except Exception as e:
            log.warning(f"[TokenCalc] tiktoken 不可用，回退到字符估算: {e}")
            _encoder = "fallback"
    return _encoder


def count_tokens(text: str) -> int:
    """精确计算文本的 token 数量"""
    if not text:
        return 0
    enc = _get_encoder()
    if enc == "fallback":
        # 中文 ≈ 1char/1token, 英文 ≈ 4chars/1token，混合取折中
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_chars = len(text) - chinese_chars
        return max(1, chinese_chars + other_chars // 4)
    try:
        return len(enc.encode(text, disallowed_special=()))
    except Exception:
        return max(1, len(text) // 3)


def calculate_usage(prompt: str, completion: str) -> dict:
    """
    精确计算 token 用量。
    使用 tiktoken cl100k_base BPE 编码器（与 Qwen/GPT-4 词表高度一致）。
    """
    prompt_tokens = count_tokens(prompt)
    completion_tokens = count_tokens(completion)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }

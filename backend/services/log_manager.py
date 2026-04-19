"""
log_manager.py — 日志捕获管理
提供内存环形缓冲区，供前端扩容中心的实时控制台使用。
"""

import logging
from collections import deque

# 全局日志缓冲区（最近 500 条）
_log_buffer: deque[str] = deque(maxlen=500)


class BufferHandler(logging.Handler):
    """将日志写入内存环形缓冲区。"""

    def emit(self, record):
        try:
            msg = self.format(record)
            _log_buffer.append(msg)
        except Exception:
            pass


def setup_log_capturing():
    """安装日志捕获 handler 到根 logger。"""
    handler = BufferHandler()
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logging.getLogger().addHandler(handler)


def get_logs() -> list[str]:
    """返回当前缓冲区中的所有日志。"""
    return list(_log_buffer)


def clear_logs():
    """清空日志缓冲区。"""
    _log_buffer.clear()

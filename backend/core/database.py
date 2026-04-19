"""
database.py — 异步 JSON 文件数据库
提供简易的 JSON 文件读写封装，支持并发安全。
"""

import asyncio
import json
import logging
import os
from typing import Any

log = logging.getLogger("qwen2api.database")


class AsyncJsonDB:
    """简易异步 JSON 持久化存储。"""

    def __init__(self, filepath: str, default_data: Any = None):
        self.filepath = filepath
        self.default_data = default_data if default_data is not None else []
        self._lock = asyncio.Lock()
        self._data: Any = None

        # 确保数据目录存在
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)

    async def _load(self) -> Any:
        if not os.path.exists(self.filepath):
            return self.default_data

        try:
            loop = asyncio.get_event_loop()
            text = await loop.run_in_executor(None, self._read_file)
            if not text.strip():
                return self.default_data
            return json.loads(text)
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"[AsyncJsonDB] 读取 {self.filepath} 失败: {e}")
            return self.default_data

    def _read_file(self) -> str:
        with open(self.filepath, "r", encoding="utf-8") as f:
            return f.read()

    def _write_file(self, data: Any):
        tmp = self.filepath + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.filepath)

    async def get(self) -> Any:
        async with self._lock:
            if self._data is None:
                self._data = await self._load()
            return self._data

    async def save(self, data: Any = None):
        async with self._lock:
            if data is not None:
                self._data = data
            if self._data is None:
                return
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self._write_file, self._data)
            except Exception as e:
                log.error(f"[AsyncJsonDB] 写入 {self.filepath} 失败: {e}")

    async def reload(self):
        async with self._lock:
            self._data = await self._load()

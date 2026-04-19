"""
usage.py — 使用统计追踪器
记录每次 API 请求的 token 消耗和调用信息，支持时间段聚合查询。
"""

import asyncio
import json
import logging
import os
import time
from collections import defaultdict
from typing import Any, Optional

log = logging.getLogger("qwen2api.usage")

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data")


class UsageRecord:
    """单次请求记录"""
    __slots__ = ("timestamp", "feature", "model", "prompt_tokens", "completion_tokens", "total_tokens", "success", "duration_ms")

    def __init__(self, feature: str, model: str, prompt_tokens: int, completion_tokens: int,
                 success: bool = True, duration_ms: int = 0):
        self.timestamp = time.time()
        self.feature = feature          # "chat" | "t2i"
        self.model = model
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = prompt_tokens + completion_tokens
        self.success = success
        self.duration_ms = duration_ms

    def to_dict(self) -> dict:
        return {
            "ts": self.timestamp,
            "f": self.feature,
            "m": self.model,
            "pt": self.prompt_tokens,
            "ct": self.completion_tokens,
            "tt": self.total_tokens,
            "ok": self.success,
            "ms": self.duration_ms,
        }


class UsageManager:
    """
    轻量级使用统计管理器。
    - 内存中维护最近记录的环形缓冲
    - 定期持久化到 JSON 文件
    - 提供聚合查询接口
    """

    def __init__(self, filepath: Optional[str] = None, max_memory: int = 50000, flush_interval: int = 60):
        self.filepath = filepath or os.path.join(DATA_DIR, "usage_stats.json")
        self.max_memory = max_memory
        self.flush_interval = flush_interval
        self._records: list[dict] = []
        self._lock = asyncio.Lock()
        self._dirty = False
        self._flush_task: Optional[asyncio.Task] = None

        os.makedirs(os.path.dirname(self.filepath) or ".", exist_ok=True)

    async def start(self):
        """启动：加载历史数据并开始定时落盘"""
        await self._load()
        self._flush_task = asyncio.create_task(self._periodic_flush())
        log.info(f"[UsageManager] 已启动，加载 {len(self._records)} 条历史记录")

    async def stop(self):
        """停止：立即落盘"""
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        await self._flush()

    async def log(self, feature: str, model: str, prompt_tokens: int, completion_tokens: int,
                  success: bool = True, duration_ms: int = 0):
        """记录一条使用数据"""
        record = UsageRecord(feature, model, prompt_tokens, completion_tokens, success, duration_ms)
        async with self._lock:
            self._records.append(record.to_dict())
            # 环形缓冲：超出上限时截断旧记录
            if len(self._records) > self.max_memory:
                self._records = self._records[-self.max_memory:]
            self._dirty = True

    async def query(self, start: Optional[float] = None, end: Optional[float] = None) -> dict[str, Any]:
        """
        聚合查询。返回指定时间范围内的统计数据。
        start/end: Unix timestamp (秒)
        """
        async with self._lock:
            records = self._records

        # 时间过滤
        if start is not None:
            records = [r for r in records if r["ts"] >= start]
        if end is not None:
            records = [r for r in records if r["ts"] <= end]

        if not records:
            return self._empty_result()

        # ── 基础聚合 ──
        total_requests = len(records)
        total_tokens = sum(r["tt"] for r in records)
        total_prompt = sum(r["pt"] for r in records)
        total_completion = sum(r["ct"] for r in records)
        success_count = sum(1 for r in records if r["ok"])

        # ── 按功能分组 ──
        by_feature: dict[str, dict] = defaultdict(lambda: {"requests": 0, "tokens": 0})
        for r in records:
            by_feature[r["f"]]["requests"] += 1
            by_feature[r["f"]]["tokens"] += r["tt"]

        # ── RPM/TPM 计算 ──
        ts_list = sorted(r["ts"] for r in records)
        time_span_minutes = max((ts_list[-1] - ts_list[0]) / 60, 1) if len(ts_list) > 1 else 1
        rpm = round(total_requests / time_span_minutes, 3)
        tpm = round(total_tokens / time_span_minutes, 3)

        # ── 时序数据 (按小时聚合，用于 Sparkline) ──
        import datetime
        hourly: dict[str, dict] = defaultdict(lambda: {"requests": 0, "tokens": 0})
        for r in records:
            hour_key = datetime.datetime.fromtimestamp(r["ts"]).strftime("%Y-%m-%d %H:00")
            hourly[hour_key]["requests"] += 1
            hourly[hour_key]["tokens"] += r["tt"]

        # 补全查询范围内所有小时（无数据时填 0，保证 Sparkline 展示完整时间跨度）
        if start is not None:
            range_start = datetime.datetime.fromtimestamp(start).replace(minute=0, second=0, microsecond=0)
        else:
            range_start = datetime.datetime.fromtimestamp(ts_list[0]).replace(minute=0, second=0, microsecond=0)
        range_end = datetime.datetime.now().replace(minute=0, second=0, microsecond=0)
        cur = range_start
        while cur <= range_end:
            key = cur.strftime("%Y-%m-%d %H:00")
            if key not in hourly:
                hourly[key] = {"requests": 0, "tokens": 0}
            cur += datetime.timedelta(hours=1)

        timeline = [
            {"time": k, "requests": v["requests"], "tokens": v["tokens"]}
            for k, v in sorted(hourly.items())
        ]

        # ── 按模型分组 ──
        by_model: dict[str, dict] = defaultdict(lambda: {"requests": 0, "tokens": 0})
        for r in records:
            by_model[r["m"]]["requests"] += 1
            by_model[r["m"]]["tokens"] += r["tt"]

        return {
            "total_requests": total_requests,
            "total_tokens": total_tokens,
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_completion,
            "success_count": success_count,
            "error_count": total_requests - success_count,
            "rpm": rpm,
            "tpm": tpm,
            "by_feature": dict(by_feature),
            "by_model": dict(by_model),
            "timeline": timeline[-168:],  # 最多返回 7 天 * 24 小时的数据点
        }

    def _empty_result(self) -> dict:
        return {
            "total_requests": 0, "total_tokens": 0,
            "total_prompt_tokens": 0, "total_completion_tokens": 0,
            "success_count": 0, "error_count": 0,
            "rpm": 0, "tpm": 0,
            "by_feature": {}, "by_model": {},
            "timeline": [],
        }

    async def _load(self):
        """从 JSON 文件加载历史记录"""
        if not os.path.exists(self.filepath):
            return
        try:
            loop = asyncio.get_event_loop()
            text = await loop.run_in_executor(None, self._read_file)
            if text.strip():
                data = json.loads(text)
                if isinstance(data, list):
                    self._records = data[-self.max_memory:]
        except Exception as e:
            log.warning(f"[UsageManager] 加载 {self.filepath} 失败: {e}")

    async def _flush(self):
        """落盘"""
        async with self._lock:
            if not self._dirty:
                return
            data = list(self._records)
            self._dirty = False
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._write_file, data)
        except Exception as e:
            log.error(f"[UsageManager] 写入 {self.filepath} 失败: {e}")

    async def _periodic_flush(self):
        """定时落盘"""
        while True:
            await asyncio.sleep(self.flush_interval)
            await self._flush()

    def _read_file(self) -> str:
        with open(self.filepath, "r", encoding="utf-8") as f:
            return f.read()

    def _write_file(self, data: list):
        tmp = self.filepath + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, self.filepath)

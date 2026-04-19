"""
health_snapshot.py — 健康历史快照管理

每 30 秒对账号池状态做一次快照，保存最近 60 个数据点（30 分钟历史）。
数据持久化到 data/health_history.json，重启后仍可加载历史。
"""

import asyncio
import json
import logging
import os
import time

log = logging.getLogger("qwen2api.health")

MAX_SNAPSHOTS = 60          # 60 × 30s = 30 分钟
SNAPSHOT_INTERVAL = 30      # 秒

# 状态字符串（与 account_pool.py 中的常量保持一致）
_VALID  = "VALID"
_SOFT   = ("RATE_LIMITED", "SOFT_ERROR", "HALF_OPEN", "PENDING_REFRESH")
_DOWN   = ("BANNED", "CIRCUIT_OPEN")


class HealthSnapshotManager:
    """定期对账号池做快照，保存可用率历史供前端画时间线。"""

    def __init__(self, pool, data_dir: str):
        self._pool = pool
        self._history: list[dict] = []
        self._task: asyncio.Task | None = None
        self._file = os.path.join(data_dir, "health_history.json")

    # ── 生命周期 ────────────────────────────────────────────

    async def start(self):
        self._load()
        self._task = asyncio.create_task(self._loop(), name="health_snapshot")
        log.info("[HealthSnapshot] 已启动，加载 %d 条历史快照", len(self._history))

    async def stop(self):
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._save()
        log.info("[HealthSnapshot] 已停止，保存 %d 条快照", len(self._history))

    # ── 查询 ────────────────────────────────────────────────

    def history(self) -> list[dict]:
        """返回快照列表，每项 {ts, valid_pct, seg}"""
        return list(self._history)

    # ── 内部 ────────────────────────────────────────────────

    async def _loop(self):
        while True:
            await asyncio.sleep(SNAPSHOT_INTERVAL)
            try:
                self._snapshot()
                self._save()
            except Exception as e:
                log.warning("[HealthSnapshot] 快照失败: %s", e)

    def _snapshot(self):
        accounts = self._pool._accounts
        total = len(accounts)
        if total == 0:
            valid_pct = 0.0
            valid = 0
        else:
            valid = sum(1 for a in accounts if a.status == _VALID)
            soft  = sum(1 for a in accounts if a.status in _SOFT)
            valid_pct = (valid + soft * 0.5) / total * 100.0

        if valid_pct >= 80:
            seg = "green"
        elif valid_pct >= 50:
            seg = "amber"
        else:
            seg = "red"

        self._history.append({
            "ts": int(time.time()),
            "valid_pct": round(valid_pct, 1),
            "seg": seg,
            "valid": valid,
            "total": total,
        })
        # 保持环形缓冲区大小
        if len(self._history) > MAX_SNAPSHOTS:
            self._history = self._history[-MAX_SNAPSHOTS:]

    def _load(self):
        if not os.path.exists(self._file):
            return
        try:
            with open(self._file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                self._history = data[-MAX_SNAPSHOTS:]
        except Exception as e:
            log.warning("[HealthSnapshot] 历史加载失败: %s", e)

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self._file), exist_ok=True)
            tmp = self._file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._history, f)
            os.replace(tmp, self._file)
        except Exception as e:
            log.warning("[HealthSnapshot] 历史保存失败: %s", e)

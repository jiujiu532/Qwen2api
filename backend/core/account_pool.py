"""
account_pool.py v2 — 高并发账号调度引擎

Min-Heap 调度 + 6 态生命周期 + 断路器 + 自适应限流 + 冷启动升温 + 自动补号
"""

import asyncio
import heapq
import hashlib
import json
import logging
import random
import time
from collections import deque
from typing import Optional, Any

log = logging.getLogger("qwen2api.account_pool")

# ─── 状态常量 ──────────────────────────────────────────
STATUS_VALID = "VALID"
STATUS_RATE_LIMITED = "RATE_LIMITED"
STATUS_SOFT_ERROR = "SOFT_ERROR"
STATUS_CIRCUIT_OPEN = "CIRCUIT_OPEN"
STATUS_HALF_OPEN = "HALF_OPEN"
STATUS_BANNED = "BANNED"
STATUS_PENDING_REFRESH = "PENDING_REFRESH"

BANNED_KEYWORDS = (
    "account has been banned", "account suspended", "account disabled",
    "violates our terms", "risk control", "permanently restricted",
    "forbidden by policy",
)

TRANSIENT_KEYWORDS = ("timeout", "connection reset", "connection refused",
                      "eof", "broken pipe", "temporary failure", "dns")


class Account:
    """代表一个上游 Qwen 账号。"""

    __slots__ = (
        "email", "password", "token", "username",
        "status", "inflight",
        "rate_limited_until", "rate_limit_count",
        "consecutive_failures", "circuit_open_count", "circuit_open_until",
        "activation_pending", "last_error", "last_request_started",
        "rpm_window", "tpm_window",
        "learned_max_rpm", "learned_max_tpm",
        "created_at", "warmup_until",
        "_score", "_heap_idx",
    )

    def __init__(self, email: str, password: str = "", token: str = "",
                 username: str = "", status: str = STATUS_VALID):
        self.email = email
        self.password = password
        self.token = token
        self.username = username or email.split("@")[0]
        self.status = status
        self.inflight = 0
        self.rate_limited_until = 0.0
        self.rate_limit_count = 0
        self.consecutive_failures = 0
        self.circuit_open_count = 0
        self.circuit_open_until = 0.0
        self.activation_pending = False
        self.last_error = ""
        self.last_request_started = 0.0
        # 滑动窗口
        self.rpm_window: deque = deque()       # timestamps
        self.tpm_window: deque = deque()       # (timestamp, token_count)
        # 自适应学习
        self.learned_max_rpm: int = 50
        self.learned_max_tpm: int = 500_000
        # 冷启动
        self.created_at: float = time.time()
        self.warmup_until: float = time.time() + 7200  # 默认 2h 升温
        # 堆调度
        self._score: float = 0.0
        self._heap_idx: int = 0

    # ── 滑动窗口 ─────────────────────────────
    def _clean_windows(self):
        now = time.time()
        cutoff = now - 60
        while self.rpm_window and self.rpm_window[0] < cutoff:
            self.rpm_window.popleft()
        while self.tpm_window and self.tpm_window[0][0] < cutoff:
            self.tpm_window.popleft()

    @property
    def rpm_1min(self) -> int:
        self._clean_windows()
        return len(self.rpm_window)

    @property
    def tpm_1min(self) -> int:
        self._clean_windows()
        return sum(t[1] for t in self.tpm_window)

    def record_request(self):
        self.rpm_window.append(time.time())

    def record_tokens(self, tokens: int):
        if tokens > 0:
            self.tpm_window.append((time.time(), tokens))

    # ── 冷启动限流 ────────────────────────────
    @property
    def effective_max_rpm(self) -> int:
        now = time.time()
        if now < self.warmup_until:
            elapsed = now - self.created_at
            if elapsed < 1800:       # 前 30 min
                return max(5, self.learned_max_rpm // 10)
            elif elapsed < 3600:     # 30-60 min
                return max(10, self.learned_max_rpm // 5)
            elif elapsed < 7200:     # 1-2h
                return max(20, self.learned_max_rpm // 2)
        return self.learned_max_rpm

    @property
    def effective_max_inflight(self) -> int:
        now = time.time()
        if now < self.warmup_until:
            elapsed = now - self.created_at
            if elapsed < 1800:
                return 1
            elif elapsed < 7200:
                return 2
        return 3  # 全速

    # ── Score 计算 ────────────────────────────
    def compute_score(self) -> float:
        if self.status not in (STATUS_VALID, STATUS_SOFT_ERROR, STATUS_HALF_OPEN):
            return float("inf")
        score = (
            self.inflight * 50
            + self.rpm_1min * 2
            + self.tpm_1min / 10000
            + self.consecutive_failures * 20
            + self.rate_limit_count * 10
        )
        if self.status == STATUS_SOFT_ERROR:
            score += 200
        if self.status == STATUS_HALF_OPEN:
            score += 100  # 半开探针优先级低于 VALID
        return score

    # ── 序列化 ────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "email": self.email, "password": self.password,
            "token": self.token, "username": self.username,
            "status": self.status, "inflight": self.inflight,
            "rate_limited_until": self.rate_limited_until,
            "rate_limit_count": self.rate_limit_count,
            "consecutive_failures": self.consecutive_failures,
            "circuit_open_count": self.circuit_open_count,
            "activation_pending": self.activation_pending,
            "last_error": self.last_error,
            "learned_max_rpm": self.learned_max_rpm,
            "learned_max_tpm": self.learned_max_tpm,
            "created_at": self.created_at,
            "warmup_until": self.warmup_until,
            "rpm_1min": self.rpm_1min,
            "tpm_1min": self.tpm_1min,
            # 兼容旧代码
            "valid": self.status not in (STATUS_BANNED,),
            "status_code": self.status,
            "status_text": self.last_error,
        }

    @staticmethod
    def from_dict(d: dict) -> "Account":
        # 兼容 v1 格式
        status = d.get("status", None)
        if status is None:
            status = STATUS_VALID if d.get("valid", True) else STATUS_SOFT_ERROR
        acc = Account(
            email=d.get("email", ""),
            password=d.get("password", ""),
            token=d.get("token", ""),
            username=d.get("username", ""),
            status=status,
        )
        acc.activation_pending = d.get("activation_pending", False)
        acc.last_error = d.get("last_error", "") or d.get("status_text", "")
        acc.rate_limit_count = d.get("rate_limit_count", 0)
        acc.consecutive_failures = d.get("consecutive_failures", 0)
        acc.circuit_open_count = d.get("circuit_open_count", 0)
        acc.learned_max_rpm = d.get("learned_max_rpm", 50)
        acc.learned_max_tpm = d.get("learned_max_tpm", 500_000)
        acc.created_at = d.get("created_at", time.time())
        acc.warmup_until = d.get("warmup_until", 0)
        return acc


# ─── Heap Entry ─────────────────────────────────────
class _HeapEntry:
    """Wrapper for heap comparison."""
    __slots__ = ("score", "counter", "acc")

    _counter = 0

    def __init__(self, acc: Account):
        _HeapEntry._counter += 1
        self.counter = _HeapEntry._counter
        self.acc = acc
        self.score = acc.compute_score()

    def __lt__(self, other):
        if self.score == other.score:
            return self.counter < other.counter
        return self.score < other.score


# ─── AccountPool v2 ─────────────────────────────────
class AccountPool:
    """Min-Heap 调度 + 6 态生命周期管理。"""

    def __init__(self, accounts_db, settings=None):
        self.accounts_db = accounts_db
        self._settings = settings
        self._accounts: list[Account] = []
        self._heap: list[_HeapEntry] = []
        self._lock = asyncio.Lock()
        self._event = asyncio.Event()
        # 粘性映射 conversation_id -> (email, chat_id, last_access_time)
        self._sticky_map: dict[str, tuple[str, str, float]] = {}
        # SSE 事件队列
        self._sse_events: asyncio.Queue = asyncio.Queue(maxsize=1000)
        # 补号状态
        self._replenish_retry_count = 0
        self._replenish_failing_since: float = 0
        self._emergency_replenish_running = False
        self._register_func = None  # 注册函数引用，由 start_replenishment_loop 注入
        # 后台任务
        self._bg_tasks: list[asyncio.Task] = []

    # ── 初始化与持久化 ────────────────────────
    async def load(self):
        data = await self.accounts_db.get()
        async with self._lock:
            self._accounts = []
            for item in (data or []):
                if isinstance(item, dict) and item.get("token"):
                    self._accounts.append(Account.from_dict(item))
            self._rebuild_heap()
            log.info(f"[AccountPool] 已加载 {len(self._accounts)} 个账号")
            self._event.set()

    async def save(self):
        async with self._lock:
            data = [acc.to_dict() for acc in self._accounts]
        await self.accounts_db.save(data)

    def _rebuild_heap(self):
        self._heap = [_HeapEntry(acc) for acc in self._accounts]
        heapq.heapify(self._heap)

    def start_background_tasks(self):
        """启动后台守护任务（在 app startup 时调用）。"""
        self._bg_tasks.append(asyncio.create_task(self._circuit_recovery_loop()))
        self._bg_tasks.append(asyncio.create_task(self._sticky_cleanup_loop()))
        log.info("[AccountPool] 后台任务已启动")

    # ── 调度核心 ─────────────────────────────
    def _is_available(self, acc: Account, exclude: set[str] | None = None) -> bool:
        if exclude and acc.email in exclude:
            return False
        if acc.status not in (STATUS_VALID, STATUS_SOFT_ERROR, STATUS_HALF_OPEN):
            return False
        if acc.activation_pending:
            return False
        if acc.status == STATUS_HALF_OPEN and acc.inflight > 0:
            return False  # HALF_OPEN 只允许 1 个探针
        if acc.inflight >= acc.effective_max_inflight:
            return False
        if acc.rpm_1min >= acc.effective_max_rpm:
            return False
        now = time.time()
        if acc.rate_limited_until > now:
            return False
        if not acc.token:
            return False
        return True

    async def acquire(self, exclude: set[str] | None = None,
                      sticky_email: str | None = None) -> Optional[Account]:
        """获取负载最低的可用账号。支持粘性优先。"""
        async with self._lock:
            # 1. 粘性优先
            if sticky_email:
                for acc in self._accounts:
                    if acc.email == sticky_email and self._is_available(acc, exclude):
                        acc.inflight += 1
                        acc.last_request_started = time.time()
                        acc.record_request()
                        return acc

            # 2. Min-Heap 调度
            # 重建堆找最优（heap 中的 score 可能过时，需重新评估）
            candidates = []
            for acc in self._accounts:
                if self._is_available(acc, exclude):
                    candidates.append(acc)

            if not candidates:
                return None

            # 按 score 排序取最低
            best = min(candidates, key=lambda a: a.compute_score())
            best.inflight += 1
            best.last_request_started = time.time()
            best.record_request()
            return best

    async def acquire_wait(self, timeout: float = 60,
                           exclude: set[str] | None = None,
                           sticky_email: str | None = None) -> Optional[Account]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            acc = await self.acquire(exclude, sticky_email)
            if acc:
                return acc
            try:
                remaining = deadline - time.time()
                await asyncio.wait_for(self._event.wait(), timeout=min(2.0, remaining))
            except asyncio.TimeoutError:
                pass
            self._event.clear()
        return None

    def release(self, acc: Account, tokens_used: int = 0):
        """释放账号并更新统计窗口。"""
        if acc.inflight > 0:
            acc.inflight -= 1
        if tokens_used > 0:
            acc.record_tokens(tokens_used)
        self._event.set()

    # ── 粘性会话管理 ──────────────────────────
    def set_sticky(self, conversation_id: str, email: str, chat_id: str):
        self._sticky_map[conversation_id] = (email, chat_id, time.time())

    def get_sticky(self, conversation_id: str) -> Optional[tuple[str, str]]:
        entry = self._sticky_map.get(conversation_id)
        if entry:
            email, chat_id, ts = entry
            if time.time() - ts < 1800:  # TTL 30min
                self._sticky_map[conversation_id] = (email, chat_id, time.time())
                return email, chat_id
            else:
                del self._sticky_map[conversation_id]
        return None

    def remove_sticky(self, conversation_id: str):
        self._sticky_map.pop(conversation_id, None)

    async def _sticky_cleanup_loop(self):
        while True:
            await asyncio.sleep(300)
            now = time.time()
            expired = [k for k, (_, _, ts) in self._sticky_map.items() if now - ts > 1800]
            for k in expired:
                del self._sticky_map[k]
            # LRU cap
            if len(self._sticky_map) > 10000:
                sorted_keys = sorted(self._sticky_map, key=lambda k: self._sticky_map[k][2])
                for k in sorted_keys[:len(self._sticky_map) - 10000]:
                    del self._sticky_map[k]

    # ── 统一错误处理 ─────────────────────────
    def mark_error(self, acc: Account, error_type: str, msg: str = ""):
        """统一错误入口。error_type: transient|rate_limit|auth|soft|ban"""
        msg_lower = msg.lower()

        # 瞬态错误 — 不计入账号错误
        if error_type == "transient" or any(kw in msg_lower for kw in TRANSIENT_KEYWORDS):
            log.debug(f"[Pool] 瞬态错误，不惩罚 {acc.email}: {msg[:100]}")
            return

        # 429 限流
        if error_type == "rate_limit" or "429" in msg or "too many" in msg_lower:
            self._mark_rate_limited(acc, msg)
            return

        # 封禁检测
        if error_type == "ban" or any(kw in msg_lower for kw in BANNED_KEYWORDS):
            self.mark_banned(acc, msg)
            return

        # 401 认证
        if error_type == "auth" or "401" in msg or "unauthorized" in msg_lower:
            acc.status = STATUS_PENDING_REFRESH
            acc.last_error = msg[:200]
            log.warning(f"[Pool] 认证失败，需刷新 token: {acc.email}")
            self._event.set()
            return

        # 软错误
        acc.consecutive_failures += 1
        acc.last_error = msg[:200]

        if acc.consecutive_failures >= 5:
            self._open_circuit(acc)
        else:
            acc.status = STATUS_SOFT_ERROR
            log.warning(f"[Pool] 软错误 #{acc.consecutive_failures}: {acc.email} — {msg[:100]}")

        self._event.set()

    def mark_success(self, acc: Account):
        """请求成功，重置错误计数。"""
        if acc.status == STATUS_HALF_OPEN:
            log.info(f"[Pool] 探针成功，断路器恢复: {acc.email}")
            acc.circuit_open_count = 0
        acc.consecutive_failures = 0
        acc.status = STATUS_VALID
        acc.last_error = ""

    def _mark_rate_limited(self, acc: Account, msg: str = ""):
        acc.rate_limit_count += 1
        msg_lower = msg.lower()

        # 判断是否为每日上限（需要更长的冷却时间）
        is_daily_limit = any(kw in msg_lower for kw in (
            "daily", "usage limit", "使用上限", "每日",
        ))

        if is_daily_limit:
            # 每日上限 → 冷却 1 小时
            cooldown = 3600
            log.warning(f"[Pool] 每日上限 {acc.email}，冷却 {cooldown}s (1小时)")
        else:
            # 普通限流 → 指数退避：60 → 120 → 300 → 600 → 1800（上限 30min）
            cooldowns = [60, 120, 300, 600, 1800]
            idx = min(acc.rate_limit_count - 1, len(cooldowns) - 1)
            cooldown = cooldowns[idx]

        acc.rate_limited_until = time.time() + cooldown
        acc.status = STATUS_RATE_LIMITED
        acc.last_error = msg[:200]

        # 自适应学习：下调 RPM 上限
        current_rpm = acc.rpm_1min
        if current_rpm < acc.learned_max_rpm:
            acc.learned_max_rpm = max(5, int(current_rpm * 0.8))
            log.info(f"[Pool] 自适应调低 RPM: {acc.email} → {acc.learned_max_rpm}")

        log.warning(f"[Pool] 限流 {acc.email}，冷却 {cooldown}s (第 {acc.rate_limit_count} 次)")
        self._event.set()

    def _open_circuit(self, acc: Account):
        acc.circuit_open_count += 1
        # 指数退避：60 → 120 → 240 → 480 → 960 → 1800（上限 30min）
        cooldown = min(60 * (2 ** (acc.circuit_open_count - 1)), 1800)
        acc.circuit_open_until = time.time() + cooldown
        acc.status = STATUS_CIRCUIT_OPEN
        log.warning(f"[Pool] 断路器开启: {acc.email}，冷却 {cooldown}s (第 {acc.circuit_open_count} 次)")
        self._event.set()

    def mark_banned(self, acc: Account, msg: str = ""):
        acc.status = STATUS_BANNED
        acc.last_error = msg[:200]
        log.error(f"[Pool] 账号封禁: {acc.email} — {msg[:100]}")
        # 推送 SSE 事件通知前端
        self._push_event("account_banned", f"账号 {acc.email} 已被封禁")
        self._event.set()

    def mark_valid(self, acc: Account):
        acc.status = STATUS_VALID
        acc.consecutive_failures = 0
        acc.circuit_open_count = 0
        acc.activation_pending = False
        acc.rate_limited_until = 0
        acc.last_error = ""
        self._event.set()

    # ── 断路器恢复 ────────────────────────────
    async def _circuit_recovery_loop(self):
        while True:
            await asyncio.sleep(30)
            now = time.time()
            for acc in self._accounts:
                # CIRCUIT_OPEN → HALF_OPEN
                if acc.status == STATUS_CIRCUIT_OPEN and now >= acc.circuit_open_until:
                    acc.status = STATUS_HALF_OPEN
                    log.info(f"[Pool] 断路器半开: {acc.email}")
                    self._event.set()
                # RATE_LIMITED 自动恢复
                if acc.status == STATUS_RATE_LIMITED and now >= acc.rate_limited_until:
                    acc.status = STATUS_VALID
                    log.info(f"[Pool] 限流恢复: {acc.email}")
                    self._event.set()
                # 自适应上探（无 429 超过 1h 缓慢恢复）
                if acc.status == STATUS_VALID and acc.rate_limit_count > 0:
                    if now - acc.rate_limited_until > 3600:
                        old = acc.learned_max_rpm
                        acc.learned_max_rpm = min(acc.learned_max_rpm + 5, 200)
                        if acc.learned_max_rpm != old:
                            log.debug(f"[Pool] 自适应上探 RPM: {acc.email} {old} → {acc.learned_max_rpm}")

    # ── SSE 事件推送 ──────────────────────────
    def _push_event(self, event_type: str, message: str, **extra):
        event = {"type": event_type, "message": message, "timestamp": time.time(), **extra}
        try:
            self._sse_events.put_nowait(event)
        except asyncio.QueueFull:
            pass  # 丢弃最旧

    async def get_sse_event(self, timeout: float = 30) -> Optional[dict]:
        try:
            return await asyncio.wait_for(self._sse_events.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    # ── 补号 ─────────────────────────────────
    def count_valid(self) -> int:
        return sum(1 for a in self._accounts
                   if a.status in (STATUS_VALID, STATUS_SOFT_ERROR, STATUS_HALF_OPEN,
                                   STATUS_RATE_LIMITED, STATUS_PENDING_REFRESH))

    def count_banned(self) -> int:
        return sum(1 for a in self._accounts if a.status == STATUS_BANNED)

    async def start_replenishment_loop(self, register_func):
        """启动补号守护进程。register_func = async def(count, concurrency) -> int(成功数)"""
        self._register_func = register_func  # 保存引用，供应急补号使用
        while True:
            # 分段睡眠，每 10s 检查一次 AUTO_REPLENISH，实现快速响应关闭开关
            for _ in range(6):
                await asyncio.sleep(10)
                from backend.core.config import settings as _cfg
                if not getattr(_cfg, "AUTO_REPLENISH", False):
                    break  # 已关闭，不等满 60s 直接进入 tick（tick 会立即 return）
            try:
                await self._replenishment_tick(register_func)
            except Exception as e:
                log.error(f"[Replenish] 未知错误: {e}")


    def trigger_emergency_replenish(self):
        """当所有账号限流/耗尽时触发应急补号（后台异步，不阻塞请求）"""
        from backend.core.config import settings
        if not getattr(settings, "AUTO_REPLENISH_ON_EXHAUST", False):
            log.info("[EmergencyReplenish] 应急补号功能未开启，跳过")
            return
        if self._register_func is None:
            log.warning("[EmergencyReplenish] register_func 未注入，无法触发应急补号")
            return
        if self._emergency_replenish_running:
            log.info("[EmergencyReplenish] 已有应急补号任务运行中，跳过重复触发")
            return

        count = getattr(settings, "REPLENISH_EXHAUST_COUNT", 10)
        concurrency = getattr(settings, "REPLENISH_EXHAUST_CONCURRENCY", 3)
        log.warning(f"[EmergencyReplenish] 所有账号耗尽，触发应急补号 {count} 个")
        self._push_event("replenish_started", f"所有账号已达限流上限，系统正在应急注册 {count} 个新账号...")

        async def _do_emergency():
            self._emergency_replenish_running = True
            try:
                registered = await self._register_func(count, concurrency)
                if registered > 0:
                    log.info(f"[EmergencyReplenish] ✅ 应急补号成功，注册了 {registered} 个账号")
                    self._push_event("replenish_success", f"应急补号成功：注册了 {registered} 个新账号，可重新尝试生图")
                    await self.load()
                else:
                    log.warning("[EmergencyReplenish] 应急补号完成但注册数量为 0")
                    self._push_event("replenish_error", "应急补号完成但未能注册新账号，请检查邮箱服务配置")
            except Exception as e:
                log.error(f"[EmergencyReplenish] 应急补号失败: {e}")
                self._push_event("replenish_error", f"应急补号失败: {str(e)[:150]}")
            finally:
                self._emergency_replenish_running = False

        asyncio.create_task(_do_emergency())

    async def _replenishment_tick(self, register_func):
        from backend.core.config import settings
        if not getattr(settings, "AUTO_REPLENISH", False):
            self._replenish_retry_count = 0
            return

        valid = self.count_valid()
        target = getattr(settings, "REPLENISH_TARGET", 30)
        if valid >= target:
            self._replenish_retry_count = 0
            self._replenish_failing_since = 0
            return

        needed = target - valid
        concurrency = getattr(settings, "REPLENISH_CONCURRENCY", 3)
        log.info(f"[Replenish] 需要补充 {needed} 个账号 (当前 {valid}/{target})")

        try:
            registered = await register_func(needed, concurrency)
            if registered > 0:
                log.info(f"[Replenish] 成功注册 {registered} 个账号")
                self._push_event("replenish_success", f"自动补号成功：注册了 {registered} 个账号")
                self._replenish_retry_count = 0
                self._replenish_failing_since = 0
                await self.load()  # 重新加载账号
        except Exception as e:
            self._replenish_retry_count += 1
            if self._replenish_failing_since == 0:
                self._replenish_failing_since = time.time()

            elapsed = time.time() - self._replenish_failing_since
            error_msg = str(e)[:200]
            log.error(f"[Replenish] 注册失败 (第 {self._replenish_retry_count} 次): {error_msg}")

            if elapsed < 1800:  # 30 分钟内持续重试
                retry_in = 300  # 5 分钟后重试
                attempts_left = max(0, 6 - self._replenish_retry_count)
                self._push_event("replenish_error", f"自动补号失败：{error_msg}",
                                 retry_in=retry_in, attempts_left=attempts_left)
            else:
                # 30 分钟后自动停止
                settings.AUTO_REPLENISH = False
                self._replenish_retry_count = 0
                self._replenish_failing_since = 0
                self._push_event("replenish_stopped",
                                 "自动补号已停止（30分钟内注册持续失败，请检查邮箱服务配置）")
                log.error("[Replenish] 30分钟重试用尽，自动补号已停止")

    # ── 账号管理 ─────────────────────────────
    async def add_account(self, email: str, password: str = "", token: str = "") -> Account:
        async with self._lock:
            for existing in self._accounts:
                if existing.email == email:
                    existing.token = token or existing.token
                    existing.password = password or existing.password
                    existing.status = STATUS_VALID
                    existing.consecutive_failures = 0
                    return existing
            acc = Account(email=email, password=password, token=token)
            self._accounts.append(acc)
        await self.save()
        self._event.set()
        return acc

    async def remove_account(self, email: str, manual: bool = True) -> bool:
        """删除账号。manual=True 表示用户手动操作，不触发补号。"""
        async with self._lock:
            before = len(self._accounts)
            self._accounts = [a for a in self._accounts if a.email != email]
            removed = len(self._accounts) < before
        if removed:
            await self.save()
            if not manual:
                self._push_event("account_removed", f"账号 {email} 已自动移除")
        return removed

    def get_account_by_email(self, email: str) -> Optional[Account]:
        for acc in self._accounts:
            if acc.email == email:
                return acc
        return None

    def all_accounts(self) -> list[Account]:
        return list(self._accounts)

    # ── 背压信号 ─────────────────────────────
    def pressure(self) -> float:
        """返回 0.0 ~ 1.0 的系统压力值。"""
        total = len(self._accounts)
        if total == 0:
            return 1.0
        valid = sum(1 for a in self._accounts if a.status in (STATUS_VALID, STATUS_SOFT_ERROR))
        if valid == 0:
            return 1.0
        busy = sum(1 for a in self._accounts
                   if a.status in (STATUS_VALID, STATUS_SOFT_ERROR) and a.inflight > 0)
        return busy / valid

    # ── 状态摘要 ─────────────────────────────
    def status(self) -> dict:
        now = time.time()
        total = len(self._accounts)
        valid = sum(1 for a in self._accounts if a.status == STATUS_VALID)
        soft_error = sum(1 for a in self._accounts if a.status == STATUS_SOFT_ERROR)
        rate_limited = sum(1 for a in self._accounts if a.status == STATUS_RATE_LIMITED)
        circuit_open = sum(1 for a in self._accounts if a.status in (STATUS_CIRCUIT_OPEN, STATUS_HALF_OPEN))
        banned = sum(1 for a in self._accounts if a.status == STATUS_BANNED)
        pending = sum(1 for a in self._accounts if a.status == STATUS_PENDING_REFRESH)
        in_use = sum(1 for a in self._accounts if a.inflight > 0)
        waiting = sum(a.inflight for a in self._accounts)
        activation_pending = sum(1 for a in self._accounts if a.activation_pending)
        return {
            "total": total, "valid": valid, "soft_error": soft_error,
            "rate_limited": rate_limited, "circuit_open": circuit_open,
            "banned": banned, "pending_refresh": pending,
            "in_use": in_use, "waiting": waiting,
            "activation_pending": activation_pending,
            "pressure": round(self.pressure(), 2),
            # 兼容 v1
            "invalid": banned + circuit_open,
        }

    def pool_stats(self) -> list[dict]:
        """返回每账号的实时 RPM/TPM/状态信息。"""
        return [
            {
                "email": acc.email,
                "status": acc.status,
                "inflight": acc.inflight,
                "rpm_1min": acc.rpm_1min,
                "tpm_1min": acc.tpm_1min,
                "learned_max_rpm": acc.learned_max_rpm,
                "consecutive_failures": acc.consecutive_failures,
                "rate_limit_count": acc.rate_limit_count,
                "score": round(acc.compute_score(), 1),
                "last_error": acc.last_error,
            }
            for acc in self._accounts
        ]

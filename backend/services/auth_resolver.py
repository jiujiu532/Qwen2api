"""
auth_resolver.py — 账号自动恢复
当账号鉴权失败或待激活时，尝试自动重新登录获取新 token。
"""

import asyncio
import logging

log = logging.getLogger("qwen2api.auth_resolver")

BASE_URL = "https://chat.qwen.ai"


class AuthResolver:
    """尝试自动恢复失效账号的 token。"""

    def __init__(self, account_pool):
        self.account_pool = account_pool
        self._healing: set[str] = set()  # 正在恢复中的邮箱

    async def auto_heal_account(self, acc):
        """后台尝试重新登录并刷新 token。"""
        if acc.email in self._healing:
            log.info(f"[AuthResolver] {acc.email} 已在恢复队列中，跳过")
            return
        self._healing.add(acc.email)
        try:
            log.info(f"[AuthResolver] 开始恢复账号: {acc.email}")

            if not acc.password:
                log.warning(f"[AuthResolver] {acc.email} 无密码，无法自动恢复")
                return

            new_token = await self._try_login(acc.email, acc.password)
            if new_token:
                acc.token = new_token
                self.account_pool.mark_valid(acc)
                await self.account_pool.save()
                log.info(f"[AuthResolver] {acc.email} 恢复成功")
            else:
                log.warning(f"[AuthResolver] {acc.email} 恢复失败")
        except Exception as e:
            log.error(f"[AuthResolver] {acc.email} 恢复异常: {e}")
        finally:
            self._healing.discard(acc.email)

    async def _try_login(self, email: str, password: str) -> str | None:
        """尝试通过 Qwen 登录 API 获取新 token。"""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{BASE_URL}/api/v1/auths/signin",
                    json={"email": email, "password": password},
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        "Content-Type": "application/json",
                        "Referer": f"{BASE_URL}/",
                        "Origin": BASE_URL,
                    }
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("token") or data.get("access_token")
                log.warning(f"[AuthResolver] 登录失败 HTTP {resp.status_code}: {resp.text[:100]}")
                return None
        except Exception as e:
            log.error(f"[AuthResolver] 登录请求异常: {e}")
            return None

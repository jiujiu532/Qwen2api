"""
mail_service.py — 自建邮箱服务适配器
支持 MoeMail（docs.moemail.app/api.html）与 TempMail（awsl.uk CF Workers 协议）两种自建方案。
"""

import asyncio
import logging
import random
import re
import string
import httpx

log = logging.getLogger("qwen2api.mail_service")


def _random_name(length: int = 10) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


class MoeMailClient:
    """
    MoeMail 自建邮箱服务客户端。
    API 文档: https://docs.moemail.app/api.html#openapi
    认证: Header X-API-Key
    ─────────────────────────────────────────────────────
    创建邮箱: POST /api/emails/generate
              body: {name, expiryTime(ms), domain}
              返回: {id: "email-uuid", email: "xxx@domain.com"}

    查询邮件: GET /api/emails/{emailId}
              返回: {messages: [{id, from_address, subject, received_at}]}

    邮件详情: GET /api/emails/{emailId}/{messageId}
              返回: {message: {id, html, content, ...}}
    """

    def __init__(self, domain: str, api_key: str):
        self.domain = domain.rstrip("/")
        self.api_key = api_key
        self._headers = {"X-API-Key": api_key, "Content-Type": "application/json"}

    def get_available_domain(self) -> str:
        """从 /api/config 获取第一个可用邮箱域名（同步，供线程池调用）"""
        try:
            with httpx.Client(timeout=10) as client:
                resp = client.get(
                    f"{self.domain}/api/config",
                    headers={"X-API-Key": self.api_key},
                )
                if resp.status_code == 200:
                    domains_str = resp.json().get("emailDomains", "")
                    if domains_str:
                        domains = [d.strip() for d in domains_str.split(",") if d.strip()]
                        if domains:
                            chosen = random.choice(domains)
                            log.info(f"[MoeMail] 可用域名: {domains}, 随机选择: {chosen}")
                            return chosen
        except Exception as e:
            log.warning(f"[MoeMail] 获取域名列表失败: {e}")
        return ""

    def create_address_sync(self, name: str | None = None, mail_domain: str = "") -> dict:
        """同步创建临时邮箱（供线程池使用），返回 {id, address}"""
        name = name or _random_name()
        if not mail_domain:
            mail_domain = self.get_available_domain()
        if not mail_domain:
            raise ValueError("[MoeMail] 无法获取可用邮箱域名，请检查 API Key 或服务配置")
        with httpx.Client(timeout=15) as client:
            resp = client.post(
                f"{self.domain}/api/emails/generate",
                json={"name": name, "expiryTime": 3600000, "domain": mail_domain},
                headers=self._headers,
            )
            resp.raise_for_status()
            data = resp.json()
            email_id = data.get("id", "")
            email_addr = data.get("email", f"{name}@{mail_domain}")
            log.info(f"[MoeMail] 邮箱创建成功: {email_addr} (id={email_id})")
            return {"id": email_id, "address": email_addr}

    def poll_for_activation_link(self, email_id: str, max_polls: int = 24, interval: int = 5) -> str | None:
        """同步轮询邮件，提取 Qwen 激活链接。max_polls 次 × interval 秒 = 最大等待时长"""
        import time as _time
        log.debug(f"[MoeMail] 开始轮询 (id={email_id}, 最多 {max_polls} 次, 间隔 {interval}s)")
        for poll in range(max_polls):
            try:
                with httpx.Client(timeout=10) as client:
                    resp = client.get(
                        f"{self.domain}/api/emails/{email_id}",
                        headers=self._headers,
                    )
                    if resp.status_code == 200:
                        msgs = resp.json().get("messages", [])
                        for msg in msgs:
                            msg_resp = client.get(
                                f"{self.domain}/api/emails/{email_id}/{msg['id']}",
                                headers=self._headers,
                            )
                            if msg_resp.status_code == 200:
                                message = msg_resp.json().get("message", {})
                                html = message.get("html", "") or message.get("content", "")
                                m = re.search(
                                    r"href=[\"']([^\"']*https://chat\.qwen\.ai/api/v1/auths/activate[^\"']*)[\"']",
                                    html, re.IGNORECASE
                                )
                                if m:
                                    link = m.group(1).strip()
                                    log.info(f"[MoeMail] 验证码链接匹配成功: {link}")
                                    return link
            except Exception as e:
                log.warning(f"[MoeMail] 轮询异常 [{poll + 1}/{max_polls}]: {e}")
            _time.sleep(interval)
        log.warning(f"[MoeMail] 邮件查询已达 {max_polls} 次，放弃 (id={email_id})")
        return None


class GuerrillaMailClient:
    """
    GuerrillaMail 官方 API 客户端。
    API 文档: https://www.guerrillamail.com/GuerrillaMailAPI.html
    端点: http(s)://api.guerrillamail.com/ajax.php
    ─────────────────────────────────────────────────────
    get_email_address → 获取随机邮箱（维护 PHPSESSID）
    check_email(seq)  → 检查新邮件列表
    fetch_email(id)   → 获取邮件正文（mail_body）
    """

    API_URL = "https://api.guerrillamail.com/ajax.php"

    def __init__(self):
        self._session_id = None

    def _call(self, client: httpx.Client, func: str, params: dict | None = None) -> dict:
        """统一调用 GuerrillaMail API"""
        p = {"f": func, "ip": "127.0.0.1", "agent": "Mozilla/5.0"}
        if params:
            p.update(params)
        cookies = {}
        if self._session_id:
            cookies["PHPSESSID"] = self._session_id
        resp = client.get(self.API_URL, params=p, cookies=cookies)
        resp.raise_for_status()
        # 更新 session
        new_sid = resp.cookies.get("PHPSESSID")
        if new_sid:
            self._session_id = new_sid
        return resp.json()

    def create_address_sync(self) -> dict:
        """同步获取一个随机 GuerrillaMail 邮箱（供线程池使用）"""
        with httpx.Client(timeout=15) as client:
            data = self._call(client, "get_email_address", {"lang": "en"})
            email_addr = data.get("email_addr", "")
            log.info(f"[GuerrillaMail] 邮箱获取成功: {email_addr}")
            return {"address": email_addr, "sid_token": data.get("sid_token", "")}

    def poll_for_activation_link(self, max_polls: int = 24, interval: int = 5) -> str | None:
        """同步轮询 GuerrillaMail，提取 Qwen 激活链接。max_polls 次 × interval 秒"""
        import time as _time
        log.debug(f"[GuerrillaMail] 开始轮询 (最多 {max_polls} 次, 间隔 {interval}s)")
        with httpx.Client(timeout=15) as client:
            for poll in range(max_polls):
                try:
                    data = self._call(client, "check_email", {"seq": "0"})
                    mail_list = data.get("list", [])
                    for mail in mail_list:
                        mail_id = mail.get("mail_id")
                        if not mail_id:
                            continue
                        detail = self._call(client, "fetch_email", {"email_id": str(mail_id)})
                        body = detail.get("mail_body", "")
                        if not body:
                            continue
                        m = re.search(
                            r"href=[\"']([^\"']*https://chat\.qwen\.ai/api/v1/auths/activate[^\"']*)[\"']",
                            body, re.IGNORECASE
                        )
                        if m:
                            link = m.group(1).strip()
                            log.info(f"[GuerrillaMail] 验证码链接匹配成功: {link}")
                            return link
                except Exception as e:
                    log.warning(f"[GuerrillaMail] 轮询异常 [{poll + 1}/{max_polls}]: {e}")
                _time.sleep(interval)
        log.warning(f"[GuerrillaMail] 邮件查询已达 {max_polls} 次，放弃")
        return None



class TempMailClient:
    """
    TempMail (CloudFlare Workers) 自建邮箱服务客户端。
    API 文档: https://temp-mail-docs.awsl.uk/zh/guide/feature/new-address-api.html
    创建地址: POST /admin/new_address  (x-admin-auth: <密钥>)
    收件查询: GET  /api/mails?limit=5  (Authorization: Bearer <jwt>)
    """

    def __init__(self, domain: str, admin_key: str):
        self.domain = domain.rstrip("/")
        self.admin_key = admin_key

    def create_address_sync(self, name: str | None = None) -> dict:
        """同步创建临时邮箱（供线程池使用）"""
        name = name or _random_name()
        with httpx.Client(timeout=15) as client:
            resp = client.post(
                f"{self.domain}/admin/new_address",
                json={"enablePrefix": False, "name": name, "domain": ""},
                headers={"x-admin-auth": self.admin_key, "Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "address": data.get("address", f"{name}@unknown"),
                "jwt": data.get("jwt", ""),
                "address_id": data.get("address_id"),
                "provider": "tempmail",
                "meta": data,
            }

    def poll_for_activation_link(self, jwt: str, max_polls: int = 12, interval: int = 5) -> str | None:
        """同步轮询邮件，提取 Qwen 激活链接。max_polls 次 × interval 秒"""
        import time as _time
        log.debug(f"[TempMail] 开始轮询 (最多 {max_polls} 次, 间隔 {interval}s)")
        for poll in range(max_polls):
            try:
                with httpx.Client(timeout=10) as client:
                    resp = client.get(
                        f"{self.domain}/api/mails?limit=5",
                        headers={"Authorization": f"Bearer {jwt}"},
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        msgs = data if isinstance(data, list) else data.get("results", [])
                        for msg in msgs:
                            html = msg.get("html", "") or msg.get("content", "") or msg.get("body", "")
                            m = re.search(
                                r"href=[\"']([^\"']*https://chat\.qwen\.ai/api/v1/auths/activate[^\"']*)[\"']",
                                html, re.IGNORECASE
                            )
                            if m:
                                link = m.group(1).strip()
                                log.info(f"[TempMail] 验证码链接匹配成功: {link}")
                                return link
            except Exception as e:
                log.warning(f"[TempMail] 轮询异常 [{poll + 1}/{max_polls}]: {e}")
            _time.sleep(interval)
        log.warning(f"[TempMail] 邮件查询已达 {max_polls} 次，放弃")
        return None

    async def create_address(self, name: str | None = None) -> dict:
        """异步版本（保留兼容性）"""
        name = name or _random_name()
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self.domain}/admin/new_address",
                json={"enablePrefix": False, "name": name, "domain": ""},
                headers={"x-admin-auth": self.admin_key, "Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "address": data.get("address", f"{name}@unknown"),
                "jwt": data.get("jwt", ""),
                "address_id": data.get("address_id"),
                "provider": "tempmail",
                "meta": data,
            }

    async def poll_inbox(self, jwt: str, timeout: int = 60, interval: int = 3) -> list[dict]:
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self.domain}/api/mails?limit=5",
                    headers={"Authorization": f"Bearer {jwt}"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    msgs = data if isinstance(data, list) else data.get("results", [])
                    if msgs:
                        return msgs
            await asyncio.sleep(interval)
        return []


def get_mail_client(provider: str, settings):
    """
    根据 provider 字符串和 settings 返回对应的邮箱客户端实例。
    provider: 'moemail' | 'tempmail' | 'gptmail' | 'vipmail' | 'guerrilla'
    """
    if provider == "moemail":
        domain = settings.MOEMAIL_DOMAIN
        key = settings.MOEMAIL_KEY
        if not domain or not key:
            raise ValueError("MoeMail 配置缺失：请在系统设置中填写域名和 API 密钥。")
        return MoeMailClient(domain, key)
    elif provider == "tempmail":
        domain = settings.TEMPMAIL_DOMAIN
        key = settings.TEMPMAIL_KEY
        if not domain or not key:
            raise ValueError("TempMail 配置缺失：请在系统设置中填写域名和管理密钥。")
        return TempMailClient(domain, key)
    elif provider == "gptmail":
        key = getattr(settings, "SMARTMAIL_KEY", "")
        return GPTMailClient(api_key=key)
    elif provider == "vipmail":
        key = getattr(settings, "VIPMAIL_KEY", "")
        if not key:
            raise ValueError("VipMail 配置缺失：请在系统设置中填写 API Key。")
        return VipMailClient(api_key=key)
    elif provider == "guerrilla":
        return GuerrillaMailClient()
    else:
        raise ValueError(f"未知邮箱服务渠道: {provider}")


# ============================================================================
# GPTMail 公共邮箱服务客户端（mail.chatgpt.org.uk）
# 自动获取每日更新的公共 API Key
# ============================================================================

class GPTMailClient:
    """
    GPTMail (mail.chatgpt.org.uk) 公共临时邮箱服务客户端。
    
    特点：
    - 公共 API Key 每日 08:00 (北京时间) 自动重置
    - 每日 20 万次免费额度
    - 自动获取最新 key，无需手动配置
    
    API:
    - 生成邮箱: GET/POST /api/generate-email
    - 查询邮件: GET /api/emails?email=xxx
    - 读取邮件: GET /api/email/{id}
    """

    BASE_URL = "https://mail.chatgpt.org.uk"
    _cached_key: str = ""
    _key_fetched_at: float = 0

    def __init__(self, api_key: str = ""):
        """如果传入 api_key 则使用固定 key，否则自动获取公共 key。"""
        self._fixed_key = api_key

    @classmethod
    def _fetch_public_key(cls) -> str:
        """从 GPTMail 获取当日公共 API Key。每天北京时间 08:00 自动刷新。"""
        import time as _time
        from datetime import datetime, timezone, timedelta

        # 检查是否需要刷新：如果已过北京时间 08:00 且 key 是昨天获取的，则刷新
        bj_tz = timezone(timedelta(hours=8))
        now_bj = datetime.now(bj_tz)
        today_reset = now_bj.replace(hour=8, minute=0, second=0, microsecond=0)
        if now_bj < today_reset:
            today_reset = today_reset - timedelta(days=1)

        # 如果有缓存且是今天 08:00 之后获取的，直接用
        if cls._cached_key and cls._key_fetched_at > today_reset.timestamp():
            return cls._cached_key

        try:
            with httpx.Client(timeout=10) as client:
                resp = client.get(
                    f"{cls.BASE_URL}/api/public-key-status",
                    params={"reveal": "1"},
                    headers={"X-Public-Key-Reveal": "click"},
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("success") and data.get("data", {}).get("key"):
                    cls._cached_key = data["data"]["key"]
                    cls._key_fetched_at = _time.time()
                    remaining = data["data"].get("remaining_today", "?")
                    log.info(f"[GPTMail] 公共 Key 获取成功: {cls._cached_key}，今日剩余额度: {remaining}")
                    return cls._cached_key
        except Exception as e:
            log.warning(f"[GPTMail] 获取公共 Key 失败: {e}")
        return cls._cached_key or ""

    @property
    def api_key(self) -> str:
        """获取当前可用的 API Key。"""
        if self._fixed_key:
            return self._fixed_key
        return self._fetch_public_key()

    def create_address_sync(self, prefix: str = "") -> dict:
        """同步生成临时邮箱。"""
        key = self.api_key
        if not key:
            raise Exception("[GPTMail] 无法获取 API Key")
        headers = {"X-API-Key": key}
        with httpx.Client(timeout=15) as client:
            if prefix:
                resp = client.post(
                    f"{self.BASE_URL}/api/generate-email",
                    json={"prefix": prefix},
                    headers={**headers, "Content-Type": "application/json"},
                )
            else:
                resp = client.get(f"{self.BASE_URL}/api/generate-email", headers=headers)
            resp.raise_for_status()
            data = resp.json()
            if not data.get("success"):
                error = data.get("error", "Unknown error")
                # 如果是 key 过期/额度用完，清除缓存强制重新获取
                if "expired" in str(error).lower() or "limit" in str(error).lower():
                    GPTMailClient._cached_key = ""
                    GPTMailClient._key_fetched_at = 0
                raise Exception(f"[GPTMail] 生成邮箱失败: {error}")
            email_addr = data["data"].get("email", "")
            return {"address": email_addr, "provider": "gptmail"}

    def poll_for_activation_link(self, email: str, max_polls: int = 24, interval: int = 5) -> str | None:
        """同步轮询 GPTMail 收件箱，提取 Qwen 激活链接。"""
        import time as _time
        key = self.api_key
        if not key:
            log.error("[GPTMail] 无法获取 API Key，无法查询邮件")
            return None
        headers = {"X-API-Key": key}
        log.debug(f"[GPTMail] 开始轮询 (email={email}, 最多 {max_polls} 次, 间隔 {interval}s)")
        with httpx.Client(timeout=15) as client:
            for poll in range(max_polls):
                try:
                    resp = client.get(
                        f"{self.BASE_URL}/api/emails",
                        params={"email": email},
                        headers=headers,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        msgs = data.get("data", []) if data.get("success") else []
                        for msg in msgs:
                            # 获取邮件详情
                            mail_id = msg.get("id", "")
                            if not mail_id:
                                continue
                            detail_resp = client.get(
                                f"{self.BASE_URL}/api/email/{mail_id}",
                                headers=headers,
                            )
                            if detail_resp.status_code != 200:
                                continue
                            detail = detail_resp.json()
                            if not detail.get("success"):
                                continue
                            mail_data = detail.get("data", {})
                            # 在 HTML 或文本中查找激活链接
                            body = mail_data.get("html", "") or mail_data.get("text", "") or ""
                            m = re.search(
                                r"href=[\"']([^\"']*https://chat\.qwen\.ai/api/v1/auths/activate[^\"']*)[\"']",
                                body, re.IGNORECASE
                            )
                            if m:
                                link = m.group(1).strip()
                                log.info(f"[GPTMail] 激活链接匹配成功: {link}")
                                return link
                            # 也尝试纯文本匹配
                            m2 = re.search(
                                r"(https://chat\.qwen\.ai/api/v1/auths/activate[^\s<\"']+)",
                                body, re.IGNORECASE
                            )
                            if m2:
                                link = m2.group(1).strip()
                                log.info(f"[GPTMail] 激活链接匹配成功(文本): {link}")
                                return link
                except Exception as e:
                    log.warning(f"[GPTMail] 轮询异常 [{poll + 1}/{max_polls}]: {e}")
                _time.sleep(interval)
        log.warning(f"[GPTMail] 邮件查询已达 {max_polls} 次，放弃 (email={email})")
        return None


# ============================================================================
# VipMail (YYDS Mail - vip.215.im) 临时邮箱服务客户端
# ============================================================================

class VipMailClient:
    """
    YYDS Mail (vip.215.im / maliapi.215.im) 临时邮箱服务客户端。
    
    API:
    - 创建邮箱: POST /v1/accounts
    - 获取邮件: GET /v1/messages?address=xxx
    - 读取邮件: GET /v1/messages/{id}?address=xxx
    """

    BASE_URL = "https://maliapi.215.im/v1"

    def __init__(self, api_key: str):
        self._api_key = api_key

    def create_address_sync(self, prefix: str = "") -> dict:
        """同步创建临时邮箱。"""
        headers = {"X-API-Key": self._api_key, "Content-Type": "application/json"}
        body = {}
        if prefix:
            body["localPart"] = prefix
        with httpx.Client(timeout=15) as client:
            resp = client.post(f"{self.BASE_URL}/accounts", json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            if not data.get("success"):
                raise Exception(f"[VipMail] 创建邮箱失败: {data.get('error', 'Unknown')}")
            account = data.get("data", {})
            return {
                "address": account.get("address", ""),
                "token": account.get("token", ""),
                "provider": "vipmail",
            }

    def poll_for_activation_link(self, email: str, token: str = "", max_polls: int = 24, interval: int = 5) -> str | None:
        """同步轮询 VipMail 收件箱，提取 Qwen 激活链接。"""
        import time as _time
        # 使用 API Key 鉴权
        headers = {"X-API-Key": self._api_key}
        log.debug(f"[VipMail] 开始轮询 (email={email}, 最多 {max_polls} 次, 间隔 {interval}s)")
        with httpx.Client(timeout=15) as client:
            for poll in range(max_polls):
                try:
                    resp = client.get(
                        f"{self.BASE_URL}/messages",
                        params={"address": email},
                        headers=headers,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        msgs = data.get("data", {}).get("messages", [])
                        for msg in msgs:
                            mail_id = msg.get("id", "")
                            if not mail_id:
                                continue
                            # 获取邮件详情
                            detail_resp = client.get(
                                f"{self.BASE_URL}/messages/{mail_id}",
                                params={"address": email},
                                headers=headers,
                            )
                            if detail_resp.status_code != 200:
                                continue
                            detail = detail_resp.json()
                            if not detail.get("success"):
                                continue
                            mail_data = detail.get("data", {})
                            body_text = mail_data.get("text", "") or ""
                            body_html = ""
                            html_field = mail_data.get("html", "")
                            if isinstance(html_field, list):
                                body_html = " ".join(html_field)
                            elif isinstance(html_field, str):
                                body_html = html_field
                            full_body = body_html or body_text
                            # 查找激活链接
                            m = re.search(
                                r"href=[\"']([^\"']*https://chat\.qwen\.ai/api/v1/auths/activate[^\"']*)[\"']",
                                full_body, re.IGNORECASE
                            )
                            if m:
                                link = m.group(1).strip()
                                log.info(f"[VipMail] 激活链接匹配成功: {link}")
                                return link
                            m2 = re.search(
                                r"(https://chat\.qwen\.ai/api/v1/auths/activate[^\s<\"']+)",
                                full_body, re.IGNORECASE
                            )
                            if m2:
                                link = m2.group(1).strip()
                                log.info(f"[VipMail] 激活链接匹配成功(文本): {link}")
                                return link
                except Exception as e:
                    log.warning(f"[VipMail] 轮询异常 [{poll + 1}/{max_polls}]: {e}")
                _time.sleep(interval)
        log.warning(f"[VipMail] 邮件查询已达 {max_polls} 次，放弃 (email={email})")
        return None

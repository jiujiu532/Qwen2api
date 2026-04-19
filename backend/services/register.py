"""
register.py — 批量注册服务
将根目录 main.py 的注册逻辑封装为异步函数，供 admin API 调用。
"""

import asyncio
import base64
import hashlib
import json
import logging
import os
import secrets
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

log = logging.getLogger("qwen2api.register")

# Qwen 注册端点
SIGNUP_URL = "https://chat.qwen.ai/api/v1/auths/signup"

# 注册用的默认配置
DEFAULT_PASSWORD_HASH = "3e44fb4816bed138eb46440954b79b3518d6cde7a58248d770410cb6be563c89"
DEFAULT_PROFILE_IMAGE = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAGQAAABkCAYAAABw4pVUAAAAAXNSR0IArs4c6QAAAlxJREFUeF7tmbFKHGEURu+4O3FX0AdICq2NETWddgERQQSx3ULfIYVFHiBFXk/fQDsLsZSQsFokCopX5o5n4Ww99/7fnjPfDMs2p5PrP+EHQ6BRCMbFfRCFsHwoBOZDIQqhEYDl8R2iEBgBWBwbohAYAVgcG6IQGAFYHBuiEBgBWBwbohAYAVgcWyIQGAFYHBuiEBgBWBwbohAYAVgcG6IQGAFYHBuiEBgBWBwbohAYAVgcWyIQmAFYHBuiEBgBWBwbohAYAVgcG6IQGAFYHBuiEBgBWBwbohAYAVgcWyIQmAFYHBuiEBgBWBwbopDuCIxGTezujeJb7nwsLc1F00RcXf6OH2c33R3S86aZa8jHToPY2GpjbbWN5ZVhjBeaR8gU0uMddHg0joHDcfzxUoX0KOSY+P7BWPYOFNIj8peP2tz6EJtf25wbJO+RL+tttO3Do8uGvLOu7Z35mJwsxFSMQt5ZxvR4hQAk/B9BIQopJTBzv0Oe0rAhpfdHfrlC8sxKJxRSije/XCF5ZqUTCinFm1+ukDyz0gmFlOLNL1dInlnphEJK8eaXKyTPrHRCIaV488sVkmdWOqGQUrz55QrJMyudUEgp3vxyheSZlU4opBRvfrlC8sw6mfh+firn9s277o4v4tfP2/fPN/X4Mz8hauQvm6JV56jkFeC8rJuCczMI6vbr83dphCYG4UoBEYAFseGKARGABbHhigERgAWx4YoBEYAFseGKARGABbHhigERgAWx4YoBEYAFseGKARGABbHhigERgAWx4YoBEYAFseGKARGABbHhigERgAWx4YoBEYAFseGKARGABbHhigERgAWx4YoBEYAFucv1Ia+eKkOMMMAAAAASUVORK5CYII="

# MailService 提供者配置
MAIL_PROVIDERS = {
    "default": {"api_url": "https://mail.chatgpt.org.uk"},
    "guerrilla": {"api_url": None},  # 使用官方 GuerrillaMail API
    "moemail": {"api_url": None},    # 从 settings 获取
}


def _generate_pkce():
    code_verifier = (
        base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    )
    code_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    return code_verifier, code_challenge


def _cookies_to_header(cookies):
    if hasattr(cookies, "get_dict"):
        cookie_dict = cookies.get_dict()
    else:
        try:
            cookie_dict = dict(cookies)
        except Exception:
            return str(cookies)
    return "; ".join([f"{k}={v}" for k, v in cookie_dict.items()])


def _oauth_device_flow(session, email, cookie_header=""):
    """执行 OAuth 设备流以获取 access_token。"""
    client_id = "f0304373b74a44d2b584a3fb70ca9e56"
    scope = "openid profile email model.completion"
    code_verifier, code_challenge = _generate_pkce()

    device_resp = session.post(
        "https://chat.qwen.ai/api/v1/oauth2/device/code",
        data={
            "client_id": client_id,
            "scope": scope,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if device_resp.status_code != 200:
        raise RuntimeError(
            f"Device code request failed [{device_resp.status_code}]: {device_resp.text[:200]}"
        )

    device_data = device_resp.json()
    device_code = device_data["device_code"]
    user_code = device_data.get("user_code", "")

    if user_code and cookie_header:
        auth_headers = {"Content-Type": "application/json", "Cookie": cookie_header}
        auth_resp = session.post(
            "https://chat.qwen.ai/api/v2/oauth2/authorize",
            json={"approved": True, "user_code": user_code},
            headers=auth_headers,
        )
        if auth_resp.status_code != 200:
            log.warning(f"[Register] OAuth 授权失败 [{auth_resp.status_code}]")
        else:
            log.info(f"[Register] OAuth 授权成功: {email}")

    grant_type = "urn:ietf:params:oauth:grant-type:device_code"
    for attempt in range(60):
        time.sleep(5)
        token_resp = session.post(
            "https://chat.qwen.ai/api/v1/oauth2/token",
            data={
                "grant_type": grant_type,
                "client_id": client_id,
                "device_code": device_code,
                "code_verifier": code_verifier,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if token_resp.status_code == 200:
            oauth_data = token_resp.json()
            log.info(f"[Register] Token 获取成功: {email} (第{attempt + 1}轮)")
            return oauth_data

        try:
            err_data = token_resp.json()
            err_code = err_data.get("error", "")
        except Exception:
            err_code = ""

        if err_code == "authorization_pending":
            continue
        if err_code == "slow_down":
            time.sleep(5)
            continue
        if err_code in ("expired_token", "access_denied"):
            log.warning(f"[Register] OAuth 令牌被拒绝: {err_code}")
            break

        log.warning(f"[Register] Token 轮询异常 [{token_resp.status_code}]")
        break

    return None


def _register_single_account(provider: str = "default", moemail_domain: str = "", moemail_key: str = "",
                              tempmail_domain: str = "", tempmail_key: str = "",
                              mail_poll_times: int = 24) -> Optional[dict]:
    """
    注册单个 Qwen 账号，返回账号字典或 None。
    同步函数，设计为在线程池中运行。
    """
    from curl_cffi import requests as curl_requests
    from backend.services.mail_service import MoeMailClient, TempMailClient, GuerrillaMailClient

    # 1. 获取临时邮箱
    log.info("[Register] 正在获取临时邮箱...")
    verify_url_fetcher = None   # callable() -> str | None

    if provider == "moemail" and moemail_domain and moemail_key:
        # 自建 MoeMail
        moe = MoeMailClient(moemail_domain, moemail_key)
        try:
            addr_info = moe.create_address_sync()
        except Exception as e:
            log.error(f"[Register] MoeMail 邮箱创建失败: {e}")
            return None
        email_addr = addr_info["address"]
        email_id = addr_info["id"]
        log.info(f"[Register] MoeMail 邮箱获取成功: {email_addr}")
        verify_url_fetcher = lambda: moe.poll_for_activation_link(email_id, max_polls=mail_poll_times)

    elif provider == "tempmail" and tempmail_domain and tempmail_key:
        # 自建 TempMail
        tmp = TempMailClient(tempmail_domain, tempmail_key)
        try:
            addr_info = tmp.create_address_sync()
        except Exception as e:
            log.error(f"[Register] TempMail 邮箱创建失败: {e}")
            return None
        email_addr = addr_info["address"]
        jwt = addr_info["jwt"]
        log.info(f"[Register] TempMail 邮箱获取成功: {email_addr}")
        verify_url_fetcher = lambda: tmp.poll_for_activation_link(jwt, max_polls=mail_poll_times)

    elif provider == "guerrilla":
        # 官方 GuerrillaMail API
        gm = GuerrillaMailClient()
        try:
            addr_info = gm.create_address_sync()
        except Exception as e:
            log.error(f"[Register] GuerrillaMail 邮箱获取失败: {e}")
            return None
        email_addr = addr_info["address"]
        log.info(f"[Register] GuerrillaMail 邮箱获取成功: {email_addr}")
        verify_url_fetcher = lambda: gm.poll_for_activation_link(max_polls=mail_poll_times)

    else:
        # 默认渠道：GuerrillaMail / ChatGPT.org.uk
        try:
            root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
            if root_dir not in sys.path:
                sys.path.insert(0, root_dir)
            from mail_service import MailService
        except ImportError:
            log.error("[Register] 无法导入 mail_service，请检查根目录下的 mail_service.py")
            return None
        provider_cfg = MAIL_PROVIDERS.get(provider, MAIL_PROVIDERS["default"])
        api_url = provider_cfg.get("api_url") or "https://mail.chatgpt.org.uk"
        mail_svc = MailService(api_url=api_url)
        email_result = mail_svc.request_email()
        if not email_result.success:
            log.error(f"[Register] 邮箱获取失败: {email_result.error}")
            return None
        email_addr = email_result.email or ""
        log.info(f"[Register] 邮箱获取成功: {email_addr}")
        verify_url_fetcher = lambda: mail_svc.poll_code(email_addr)

    # 2. 无头浏览器提交注册表单
    from backend.services.browser_register import browser_signup_sync

    signup_result = browser_signup_sync(email_addr, DEFAULT_PASSWORD_HASH)
    if not signup_result or not signup_result.get("success"):
        log.error(f"[Register] [{email_addr}] 表单提交失败")
        return None

    browser_cookies = signup_result.get("cookies", {})
    log.info(f"[Register] [{email_addr}] 表单已提交，查询激活邮件（最多 {mail_poll_times} 次·每5s一次）")

    # 3. 等待验证邮件并点击激活链接
    token_data = None
    cookie_header = ""

    try:
        from curl_cffi import requests as curl_requests
        with curl_requests.Session(impersonate="chrome119") as session:
            # 注入浏览器获取的 cookies
            for k, v in browser_cookies.items():
                session.cookies.set(k, v, domain=".chat.qwen.ai")

            verify_url = verify_url_fetcher()
            if not verify_url:
                log.error(f"[Register] {email_addr} 验证邮件超时")
                return None

            log.info(f"[Register] 获取到激活链接，正在激活 {email_addr}...")
            session.get(url=verify_url)
            cookie_header = _cookies_to_header(session.cookies)

            # 4. OAuth 设备流获取 token
            log.info(f"[Register] 开始获取令牌: {email_addr}...")
            try:
                token_data = _oauth_device_flow(session, email_addr, cookie_header=cookie_header)
            except Exception as e:
                log.warning(f"[Register] 令牌获取失败: {email_addr}")
                token_data = None

            jwt_token_from_cookie = session.cookies.get("token")

    except Exception as e:
        log.error(f"[Register] 注册过程异常 {email_addr}: {e}")
        return None


    if not token_data:
        log.error(f"[Register] {email_addr} 未获取到 token")
        return None

    # 提取 JWT Token
    jwt_token = jwt_token_from_cookie or token_data.get("access_token", "")
    if not jwt_token:
        jwt_token = token_data.get("access_token", "")

    if not jwt_token:
        log.error(f"[Register] {email_addr} token 为空")
        return None

    account_data = {
        "email": email_addr,
        "password": "AlIlzHZkJ4zG6J",
        "token": jwt_token,
        "cookies": cookie_header,
        "username": email_addr.split("@")[0],
        "activation_pending": False,
        "status_code": "valid",
        "last_error": "",
        "valid": True,
    }

    log.info(f"[Register] ✅ 注册成功: {email_addr}")
    return account_data


async def perform_batch_registration(
    account_pool,
    count: int = 1,
    threads: int = 4,
    provider: str = "default",
    moemail_domain: str = "",
    moemail_key: str = "",
    tempmail_domain: str = "",
    tempmail_key: str = "",
    stop_flag: "threading.Event | None" = None,
    max_retries: int = 24,  # 每5秒查一次激活邮件，最多查几次
):
    """
    批量注册入口。

    - count:       总共尝试的账号槽数（成功+失败合计 = count）
    - max_retries: 每槽激活邮件最多查询次数（每5s一次），超时则此槽失败
    - threads:     同时运行的并发槽数
    - stop_flag:   用户手动停止信号
    """
    mail_poll_times = max(1, max_retries) if max_retries > 0 else 24
    max_workers = max(1, min(threads, 32))
    loop = asyncio.get_event_loop()
    success_count = 0
    fail_count = 0
    sem = asyncio.Semaphore(max_workers)

    log.info(
        f"[Register] 批量注册开始: 总槽数={count}, 并发={threads}, 邮件查询次数={mail_poll_times}(即{mail_poll_times * 5}s超时), 渠道={provider}"
    )

    async def _run_slot(slot_num: int):
        """运行单个账号槽，只跑一次，超时则失败。"""
        nonlocal success_count, fail_count
        async with sem:
            if stop_flag and stop_flag.is_set():
                log.info(f"[Register] 第{slot_num}/{count}槽 收到停止信号，退出")
                return

            result = await loop.run_in_executor(
                None,
                _register_single_account,
                provider,
                moemail_domain,
                moemail_key,
                tempmail_domain,
                tempmail_key,
                mail_poll_times,
            )

            if result and result.get("token"):
                await account_pool.add_account(
                    email=result["email"],
                    password=result.get("password", ""),
                    token=result["token"],
                )
                success_count += 1
                log.info(
                    f"[Register] 第{slot_num}/{count}槽 ✅ 注册成功，已入池 (总成功 {success_count})"
                )
            else:
                fail_count += 1
                log.warning(f"[Register] 第{slot_num}/{count}槽 ❌ 注册失败")

    # 一次性创建所有槽的任务，并发由信号量控制
    all_tasks = [asyncio.create_task(_run_slot(i + 1)) for i in range(count)]
    await asyncio.gather(*all_tasks, return_exceptions=True)

    stopped = stop_flag and stop_flag.is_set()
    status = "手动停止" if stopped else "完成"
    log.info(
        f"[Register] 批量注册{status}: "
        f"成功={success_count}, 失败={fail_count}, 共{count}槽"
    )
    return {"success": success_count, "failed": fail_count, "stopped": bool(stopped)}


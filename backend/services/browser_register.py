"""
browser_register.py — 无头浏览器注册（无验证码直通策略）

策略：
  - 通过代理池轮换 IP，争取"无验证码"的干净 IP 注册
  - 点击「创建账号」后等待 5s：
      • 无验证码出现 → 直接成功，返回 cookies
      • 出现验证码   → 立刻丢弃（不尝试解题），返回 None
  - 速度：~7s/次  |  内存：无 cv2/numpy

调用方（register.py）负责并发重试，代理轮换由 rotating proxy URL 自动完成。
"""

import asyncio
import logging
import random
from typing import Optional

log = logging.getLogger("qwen2api.browser_register")


def _translate_err(e: Exception) -> str:
    """将 Playwright 异常信息翻译成中文，方便用户理解。"""
    msg = str(e)
    if "Locator.fill" in msg and "Timeout" in msg:
        return "表单填写超时（注册页面加载过慢或元素未出现）"
    if "Locator.click" in msg and "Timeout" in msg:
        return "按钮点击超时（页面未完全加载）"
    if "Timeout" in msg and ("goto" in msg or "navigate" in msg or "networkidle" in msg):
        return "页面加载超时（网络慢或代理不稳定）"
    if "net::ERR_" in msg:
        code = msg.split("net::ERR_")[-1].split()[0].rstrip(")")
        return f"网络错误（ERR_{code}，请检查代理连接）"
    if "Browser" in msg and ("closed" in msg or "crash" in msg):
        return "浏览器意外关闭"
    if "Timeout" in msg:
        return f"操作超时（{msg[:60]}）"
    return msg[:120]


# ────────────────────────────────────────────────────────────────
# 核心：无头浏览器注册（无验证码直通）
# ────────────────────────────────────────────────────────────────

async def browser_signup(
    email: str,
    password_hash: str,
    password_plain: str = "AlIlzHZkJ4zG6J",
) -> Optional[dict]:
    """
    使用 Playwright 完成 Qwen 注册表单提交。

    - 代理池配置从 settings 热读取（支持 rotating proxy）
    - 遇到验证码立刻返回 None，由上层并发重试
    - 成功返回 {"success": True, "cookies": {...}}
    """
    from playwright.async_api import async_playwright
    from backend.core.config import settings as _cfg  # 热更新

    log.info(f"[Register] [{email}] 开始注册")

    # ── 代理池配置（支持 inline auth: http://user:pass@host:port）──
    _proxy: dict | None = None
    if getattr(_cfg, "PROXY_ENABLED", False) and getattr(_cfg, "PROXY_URL", ""):
        from urllib.parse import urlparse, urlunparse
        raw = _cfg.PROXY_URL
        parsed = urlparse(raw)
        username = getattr(_cfg, "PROXY_USERNAME", "") or parsed.username or ""
        password = getattr(_cfg, "PROXY_PASSWORD", "") or parsed.password or ""
        # 清理 URL 内嵌 auth（Playwright 要求 username/password 分离传入）
        clean = parsed._replace(netloc=parsed.hostname + (f":{parsed.port}" if parsed.port else ""))
        server = urlunparse(clean)
        _proxy = {"server": server}
        if username:
            _proxy["username"] = username
        if password:
            _proxy["password"] = password
        log.info(f"[Register] [{email}] 使用代理: {server}")
    else:
        log.info(f"[Register] [{email}] 直连模式（未启用代理）")

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                proxy=_proxy,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )
            ctx_kwargs = dict(
                viewport={"width": 1280, "height": 800},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                locale="zh-CN",
            )
            if _proxy:
                ctx_kwargs["proxy"] = _proxy
            context = await browser.new_context(**ctx_kwargs)

            # 反 webdriver 检测
            await context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
            )
            page = await context.new_page()

            # ── 1. 打开注册页面 ──
            log.info(f"[Register] [{email}] 打开注册页面...")
            try:
                await page.goto(
                    "https://chat.qwen.ai/auth?mode=register",
                    wait_until="networkidle",
                    timeout=30000,
                )
            except Exception:
                await page.goto(
                    "https://chat.qwen.ai/auth?mode=register",
                    wait_until="domcontentloaded",
                    timeout=30000,
                )
            await page.wait_for_timeout(random.randint(800, 1200))

            # ── 2. 填写表单 ──
            log.info(f"[Register] [{email}] 填写注册表单...")
            random_name = f"user{''.join([str(random.randint(0, 9)) for _ in range(6)])}"
            try:
                await page.locator('input[placeholder*="名称"]').fill(random_name)
            except Exception:
                pass
            await page.wait_for_timeout(random.randint(200, 400))

            await page.locator('input[placeholder*="邮箱"]').fill(email)
            await page.wait_for_timeout(random.randint(200, 400))

            password_inputs = page.locator('input[type="password"]')
            count = await password_inputs.count()
            if count >= 2:
                await password_inputs.nth(0).fill(password_plain)
                await page.wait_for_timeout(random.randint(150, 300))
                await password_inputs.nth(1).fill(password_plain)
            elif count == 1:
                await password_inputs.nth(0).fill(password_plain)
            await page.wait_for_timeout(random.randint(200, 350))

            checkbox = page.locator('input[type="checkbox"]')
            if await checkbox.count() > 0:
                await checkbox.first.click()
                await page.wait_for_timeout(200)

            # ── 3. 点击创建账号 ──
            log.info(f"[Register] [{email}] 点击创建账号...")
            await page.locator('button:has-text("创建账号")').click()

            # ── 4. 等待 5s，判断结果 ──
            # 验证码选择器（阿里云 WAF 拼图）
            CAPTCHA_SELS = [
                "#waf_nc_block",
                "#WAF_NC_WRAPPER",
                ".waf-nc-wrapper",
                "#aliyunCaptcha-sliding-slider",
                '[class*="nc-wrapper"]',
                '[class*="captcha"]',
            ]
            captcha_loc = page.locator(", ".join(CAPTCHA_SELS))

            # 等最多 5s 看验证码是否出现
            captcha_appeared = False
            try:
                await captcha_loc.first.wait_for(state="visible", timeout=5000)
                captcha_appeared = True
            except Exception:
                pass  # 超时 → 没出现验证码 → 好事

            if captcha_appeared:
                log.warning(f"[Register] [{email}] ⚠️ 需打码，此邮箱丢弃")
                await browser.close()
                return None

            # 无验证码 → 注册直接成功
            log.info(f"[Register] [{email}] ✅ 无需打码，等待激活邮件中")
            await page.wait_for_timeout(2000)  # 等待服务端处理

            cookies_list = await context.cookies()
            cookies_dict = {c["name"]: c["value"] for c in cookies_list}
            log.info(f"[Register] [{email}] 获取到 {len(cookies_dict)} 个 cookies")
            await browser.close()
            return {"success": True, "cookies": cookies_dict}

    except Exception as e:
        log.error(f"[Register] [{email}] 注册过程异常: {_translate_err(e)}")
        return None


def browser_signup_sync(
    email: str,
    password_hash: str,
    password_plain: str = "AlIlzHZkJ4zG6J",
) -> Optional[dict]:
    """
    同步包装器，在线程池中调用。
    从新的事件循环中运行 async browser_signup。
    """
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(browser_signup(email, password_hash, password_plain))
        loop.close()
        return result
    except Exception as e:
        log.error(f"[BrowserRegister] 同步包装异常: {e}")
        return None

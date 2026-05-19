"""
accounts.py -- 账号管理端点
"""

import asyncio
import json
import logging
import threading
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from backend.core.config import settings
from . import _require_admin

log = logging.getLogger("qwen2api.admin")
router = APIRouter()

# 手动注册停止标志
_manual_stop_flag = threading.Event()


@router.get("/accounts")
async def list_accounts(request: Request, _=Depends(_require_admin)):
    pool = request.app.state.account_pool
    accounts = [acc.to_dict() for acc in pool.all_accounts()]
    return {"accounts": accounts}


@router.post("/accounts")
async def add_account(request: Request, _=Depends(_require_admin)):
    pool = request.app.state.account_pool
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON")

    email = body.get("email", "")
    password = body.get("password", "")
    token = body.get("token", "")

    if not token and not password:
        return JSONResponse({"ok": False, "error": "Token or password is required"})

    if not email:
        email = f"manual_{int(__import__('time').time())}@qwen"

    acc = await pool.add_account(email, password, token)
    return {"ok": True, "email": acc.email}


@router.post("/accounts/batch")
async def batch_import_accounts(request: Request, _=Depends(_require_admin)):
    """批量导入账号。支持多种格式。"""
    pool = request.app.state.account_pool
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON")

    imported = 0
    errors = []

    if "accounts" in body:
        accounts_data = body["accounts"]
        if isinstance(accounts_data, str):
            try:
                accounts_data = json.loads(accounts_data)
            except json.JSONDecodeError:
                return JSONResponse({"ok": False, "error": "accounts field is not valid JSON"}, status_code=400)
        while isinstance(accounts_data, list) and len(accounts_data) == 1 and isinstance(accounts_data[0], list):
            accounts_data = accounts_data[0]
        if not isinstance(accounts_data, list):
            return JSONResponse({"ok": False, "error": "accounts must be an array"}, status_code=400)

        for i, item in enumerate(accounts_data):
            if not isinstance(item, dict):
                errors.append(f"Item {i}: not an object")
                continue
            token = item.get("token", "")
            email = item.get("email", "") or f"batch_{int(__import__('time').time())}_{i}@qwen"
            password = item.get("password", "")
            if not token and not password:
                errors.append(f"Item {i} ({email}): no token or password")
                continue
            try:
                await pool.add_account(email, password, token)
                imported += 1
            except Exception as e:
                errors.append(f"Item {i} ({email}): {e}")

    elif "tokens" in body:
        tokens_raw = body["tokens"]
        if isinstance(tokens_raw, list):
            token_list = tokens_raw
        else:
            token_list = [t.strip() for t in str(tokens_raw).splitlines() if t.strip()]
        for i, token in enumerate(token_list):
            if not token or len(token) < 10:
                errors.append(f"Line {i+1}: token too short")
                continue
            email = f"token_{int(__import__('time').time())}_{i}@qwen"
            try:
                await pool.add_account(email, "", token)
                imported += 1
            except Exception as e:
                errors.append(f"Line {i+1}: {e}")

    elif "lines" in body:
        lines_raw = body["lines"]
        lines = [l.strip() for l in str(lines_raw).splitlines() if l.strip()]
        for i, line in enumerate(lines):
            parts = line.split(":", 2)
            if len(parts) == 3:
                email, password, token = parts[0].strip(), parts[1].strip(), parts[2].strip()
            elif len(parts) == 2:
                first, second = parts[0].strip(), parts[1].strip()
                if len(second) > 50:
                    email, password, token = first, "", second
                else:
                    email, password, token = first, second, ""
            elif len(parts) == 1:
                token = parts[0].strip()
                email = f"line_{int(__import__('time').time())}_{i}@qwen"
                password = ""
            else:
                errors.append(f"Line {i+1}: cannot parse")
                continue
            if not token and not password:
                errors.append(f"Line {i+1}: no token or password")
                continue
            if not email:
                email = f"line_{int(__import__('time').time())}_{i}@qwen"
            try:
                await pool.add_account(email, password, token)
                imported += 1
            except Exception as e:
                errors.append(f"Line {i+1}: {e}")
    else:
        return JSONResponse({"ok": False, "error": "请提供 accounts、tokens 或 lines 字段"}, status_code=400)

    return {"ok": imported > 0, "imported": imported, "errors": errors[:20], "total_in_pool": len(pool.all_accounts())}


@router.delete("/accounts/{email}")
async def delete_account(email: str, request: Request, _=Depends(_require_admin)):
    pool = request.app.state.account_pool
    removed = await pool.remove_account(email, manual=True)
    if not removed:
        raise HTTPException(404, "Account not found")
    return {"ok": True}


@router.post("/accounts/{email}/verify")
async def verify_account(email: str, request: Request, _=Depends(_require_admin)):
    pool = request.app.state.account_pool
    client = request.app.state.qwen_client
    acc = pool.get_account_by_email(email)
    if not acc:
        raise HTTPException(404, "Account not found")
    valid = await client.verify_token(acc.token)
    if valid:
        pool.mark_valid(acc)
    else:
        pool.mark_error(acc, "auth", "Token verification failed")
    await pool.save()
    return {"valid": valid, "email": email, "status": acc.status}


@router.put("/accounts/{email}")
async def update_account(email: str, request: Request, _=Depends(_require_admin)):
    """更新账户的 Token"""
    pool = request.app.state.account_pool
    acc = pool.get_account_by_email(email)
    if not acc:
        raise HTTPException(404, "Account not found")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON")
    new_token = body.get("token", "").strip()
    if not new_token:
        return JSONResponse({"ok": False, "error": "Token cannot be empty"}, status_code=400)
    acc.token = new_token
    acc.status = "VALID"
    acc.consecutive_failures = 0
    await pool.save()
    return {"ok": True, "email": email}


@router.post("/accounts/{email}/activate")
async def activate_account(email: str, request: Request, _=Depends(_require_admin)):
    pool = request.app.state.account_pool
    client = request.app.state.qwen_client
    acc = pool.get_account_by_email(email)
    if not acc:
        raise HTTPException(404, "Account not found")
    if hasattr(client, "auth_resolver"):
        asyncio.create_task(client.auth_resolver.auto_heal_account(acc))
        return {"ok": True, "pending": True, "message": "激活任务已提交"}
    return {"ok": False, "error": "AuthResolver not available"}


@router.post("/accounts/{email}/disable")
async def disable_account(email: str, request: Request, _=Depends(_require_admin)):
    """禁用账户"""
    pool = request.app.state.account_pool
    acc = pool.get_account_by_email(email)
    if not acc:
        raise HTTPException(404, "Account not found")
    acc.status = "DISABLED"
    await pool.save()
    return {"ok": True, "email": email}


@router.get("/accounts/raw")
async def get_raw_accounts(request: Request, _=Depends(_require_admin)):
    pool = request.app.state.account_pool
    accounts = [acc.to_dict() for acc in pool.all_accounts()]
    content = json.dumps(accounts, ensure_ascii=False, indent=2)
    return {"content": content}


@router.post("/accounts/raw")
async def save_raw_accounts(request: Request, _=Depends(_require_admin)):
    try:
        body = await request.json()
        content = body.get("content", "")
        data = json.loads(content)
        while isinstance(data, list) and len(data) == 1 and isinstance(data[0], list):
            data = data[0]
        if not isinstance(data, list):
            return JSONResponse({"ok": False, "detail": "Must be a JSON array"}, status_code=400)
        valid_items = []
        skipped = 0
        for item in data:
            if not isinstance(item, dict):
                skipped += 1
                continue
            if not item.get("token") and not item.get("password"):
                skipped += 1
                continue
            valid_items.append(item)
        pool = request.app.state.account_pool
        db = request.app.state.accounts_db
        await db.save(valid_items)
        await pool.load()
        msg = f"已加载 {len(valid_items)} 个账号"
        if skipped:
            msg += f"（跳过 {skipped} 个无效条目）"
        return {"ok": True, "message": msg, "loaded": len(valid_items), "skipped": skipped}
    except json.JSONDecodeError as e:
        return JSONResponse({"ok": False, "detail": f"Invalid JSON: {e}"}, status_code=400)
    except Exception as e:
        return JSONResponse({"ok": False, "detail": str(e)}, status_code=500)


@router.post("/verify")
async def verify_all(request: Request, _=Depends(_require_admin)):
    pool = request.app.state.account_pool
    client = request.app.state.qwen_client
    accounts = pool.all_accounts()

    async def _verify(acc):
        try:
            valid = await client.verify_token(acc.token)
            if valid:
                pool.mark_valid(acc)
            else:
                pool.mark_error(acc, "auth", "Batch verify failed")
        except Exception as e:
            pool.mark_error(acc, "auth", str(e))

    tasks = [_verify(acc) for acc in accounts]
    await asyncio.gather(*tasks, return_exceptions=True)
    await pool.save()
    return {"ok": True, "verified": len(tasks), "status": pool.status()}


@router.post("/accounts/batch-register")
async def batch_register(request: Request, _=Depends(_require_admin)):
    from backend.services.register import perform_batch_registration
    try:
        body = await request.json()
    except Exception:
        body = {}
    count = body.get("count", 10)
    threads = body.get("threads", 4)
    provider = body.get("provider", "default")
    max_retries = int(body.get("max_retries", 0))
    pool = request.app.state.account_pool
    log.info(f"[Admin] 批量注册请求: count={count} threads={threads} provider={provider}")
    _manual_stop_flag.clear()
    asyncio.create_task(
        perform_batch_registration(
            account_pool=pool, count=count, threads=threads, provider=provider,
            moemail_domain=settings.MOEMAIL_DOMAIN, moemail_key=settings.MOEMAIL_KEY,
            tempmail_domain=getattr(settings, "TEMPMAIL_DOMAIN", ""),
            tempmail_key=getattr(settings, "TEMPMAIL_KEY", ""),
            stop_flag=_manual_stop_flag, max_retries=max_retries,
        )
    )
    return {"ok": True, "message": f"批量注册已启动: {count} 个账号, {threads} 并发, 渠道={provider}"}


@router.post("/accounts/stop-register")
async def stop_register(_=Depends(_require_admin)):
    _manual_stop_flag.set()
    log.info("[Admin] 用户请求停止手动注册任务")
    return {"ok": True, "message": "停止信号已发送"}


@router.post("/accounts/disable-memory")
async def disable_memory_all(request: Request, _=Depends(_require_admin)):
    """批量关闭所有账号的记忆功能"""
    import httpx
    pool = request.app.state.account_pool
    accounts = pool.all_accounts()
    success = 0
    failed = 0

    async def _disable_one(acc):
        nonlocal success, failed
        if not acc.token:
            failed += 1
            return
        try:
            headers = {
                "Authorization": f"Bearer {acc.token}",
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Origin": "https://chat.qwen.ai",
            }
            # 1. 关闭 4 个记忆开关
            body = {
                "memory": {"enable_memory": False, "enable_history_memory": False},
                "tools_enabled": {
                    "history_retriever": False,
                    "bio": False,
                }
            }
            async with httpx.AsyncClient(timeout=10) as hc:
                resp = await hc.post("https://chat.qwen.ai/api/v2/users/user/settings/update", headers=headers, json=body)
                if resp.status_code != 200:
                    failed += 1
                    return
                # 2. 获取并删除已有记忆
                mem_resp = await hc.get("https://chat.qwen.ai/api/v2/memories/?page_size=50&page_num=1", headers=headers)
                if mem_resp.status_code == 200:
                    import json as _json
                    mem_data = mem_resp.json()
                    nodes = mem_data.get("data", {}).get("memory_nodes", [])
                    for node in nodes:
                        node_id = node.get("id", "")
                        if node_id:
                            await hc.delete(f"https://chat.qwen.ai/api/v2/memories/{node_id}", headers=headers)
            success += 1
        except Exception:
            failed += 1

    # 并发执行（限制 20 并发）
    sem = asyncio.Semaphore(20)
    async def _with_sem(acc):
        async with sem:
            await _disable_one(acc)

    tasks = [_with_sem(acc) for acc in accounts]
    await asyncio.gather(*tasks)
    log.info(f"[Admin] 批量关闭记忆完成: success={success} failed={failed}")
    return {"ok": True, "success": success, "failed": failed, "total": len(accounts)}

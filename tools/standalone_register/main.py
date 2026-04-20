from mail_service import MailService
from curl_cffi import requests as curl_requests
import base64
import hashlib
import json
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# 全局锁和批次时间
FILE_LOCK = threading.Lock()
BATCH_TIME = datetime.now().strftime("%Y%m%d_%H%M%S")

print("\n" + "="*40)
print("      Qwen 批量注册工具 v1.0")
print("="*40)
print("\n[请选择工作模式]")
print("  1 > qwen2api (单账号模式)")
print("  2 > qwen2api (多账号聚合)")
print("  3 > CPA 模式 (原始数据格式)")
print("\n" + "-"*40)
reg_mode = input("输入模式编号 (1/2/3): ").strip()

print("\n[配置参数]")
num = input(" 注册总个数: ")
threads = input(" 并发线程数(默认4): ").strip()
threads = int(threads) if threads else 4
print("-"*40 + "\n")

url = "https://chat.qwen.ai/api/v1/auths/signup"

payload = json.dumps(
    {
        "name": "1asdaw",
        # 后续自动补充
        "email": "",
        # AlIlzHZkJ4zG6J
        "password": "3e44fb4816bed138eb46440954b79b3518d6cde7a58248d770410cb6be563c89",
        "agree": True,
        "profile_image_url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAGQAAABkCAYAAABw4pVUAAAAAXNSR0IArs4c6QAAAlxJREFUeF7tmbFKHGEURu+4O3FX0AdICq2NETWddgERQQSx3ULfIYVFHiBFXk/fQDsLsZSQsFokCopX5o5n4Ww99/7fnjPfDMs2p5PrP+EHQ6BRCMbFfRCFsHwoBOZDIQqhEYDl8R2iEBgBWBwbohAYAVgcG6IQGAFYHBuiEBgBWBwbohAYAVgcG6IQGAFYHBuiEBgBWBwbohAYAVgcG6IQGAFYHBuiEBgBWBwbohAYAVgcG6IQGAFYHBuiEBgBWBwbohAYAVgcG6KQ7giMRk3s7o3i2+58LC3NRdNEXF3+jh9nN90d0vOmmWvIx0+D2NhqY22tjeWVYYwXmkfIFNLjHXR4NI6Dw3EMh88fqpAehRwdj2P/QCE9In/5qM2tD7H5tY25wb/rpu+RL+tttO3Do8uGvLOu7Z35mJwsxFSMQt5ZxvR4hQAk/B9BIQopJTBzv0Oe0rAhpfdHfrlC8sxKJxRSije/XCF5ZqUTCinFm1+ukDyz0gmFlOLNL1dInlnphEJK8eaXKyTPrHRCIaV488sVkmdWOqGQUrz55QrJMyudUEgp3vxyheSZlU4opBRvfrlC8sw6mfh+thirn9s377o4v4tfP2/fPN/X4Mz8hauQvm6JV56jkFeC8rJuCczMI6vbr83dphCYG4UoBEYAFseGKARGABbHhigERgAWx4YoBEYAFseGKARGABbHhigERgAWx4YoBEYAFseGKARGABbHhigERgAWx4YoBEYAFseGKARGABbHhigERgAWx4YoBEYAFseGKARGABbHhigERgAWx4YoBEYAFucv1Ia+eKkOMMMAAAAASUVORK5CYII=",
        "oauth_sub": "",
        "oauth_token": "",
        "module": "chat",
    }
)
headers = {"Content-Type": "application/json"}


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


def oauth_device_flow(session, email, cookie_header=""):
    token_data = None
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
    verification_uri = device_data.get("verification_uri_complete") or device_data.get(
        "verification_uri", ""
    )

    if verification_uri:
        print(f"[INFO] verification_uri: {verification_uri}")
    else:
        print("[WARN] 未返回 verification_uri，请检查响应")

    if user_code and cookie_header:
        auth_headers = {"Content-Type": "application/json", "Cookie": cookie_header}
        auth_resp = session.post(
            "https://chat.qwen.ai/api/v2/oauth2/authorize",
            json={"approved": True, "user_code": user_code},
            headers=auth_headers,
        )
        if auth_resp.status_code != 200:
            print(
                f"[WARN] authorize failed [{auth_resp.status_code}]: {auth_resp.text[:200]}"
            )
        else:
            print("[INFO] authorize ok")
    else:
        print("[WARN] 缺少 user_code 或 Cookie，未执行 authorize")

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
            print(f"[INFO] OAuth token obtained (attempt {attempt + 1})")
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
            print(f"[WARN] OAuth token denied: {err_code}")
            break

        print(
            f"[WARN] Token poll unexpected [{token_resp.status_code}]: {token_resp.text[:200]}"
        )
        break

    return None


def _cookies_to_header(cookies):
    if hasattr(cookies, "get_dict"):
        cookie_dict = cookies.get_dict()
    else:
        try:
            cookie_dict = dict(cookies)
        except Exception:
            return str(cookies)
    return "; ".join([f"{k}={v}" for k, v in cookie_dict.items()])


def save_account(email_addr, token_data, cookie_header, _payload, mode, jwt_token_from_cookie):
    """根据模式保存账号数据"""
    if not token_data:
        return

    # 获取 JWT Token (优先从 cookie 提取)
    jwt_token = jwt_token_from_cookie or token_data.get("access_token", "")
    
    # 兜底使用 access_token
    if not jwt_token:
        jwt_token = token_data.get("access_token", "")

    # 准备 JWT 格式数据 (模式 1 & 2)
    jwt_format_data = [
        {
            "email": email_addr,
            "password": "AlIlzHZkJ4zG6J",
            "token": jwt_token,
            "cookies": cookie_header,
            "username": _payload.get("name", ""),
            "activation_pending": False,
            "status_code": "valid",
            "last_error": "",
            "last_request_started": 0.0,
            "last_request_finished": 0.0,
            "consecutive_failures": 0,
            "rate_limit_strikes": 0
        }
    ]

    # 准备原始格式数据 (模式 3)
    original_format_data = {
        "type": "qwen",
        "email": email_addr,
        "expired": datetime.now(timezone(timedelta(hours=8))).isoformat(), # 简化处理
        "access_token": token_data.get("access_token", ""),
        "last_refresh": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "resource_url": "portal.qwen.ai",
        "refresh_token": token_data.get("refresh_token", "")
    }

    if mode == "1":
        # 模式 1: qwen2api 单账号
        # 存入总目录
        total_dir = os.path.join("qwen2api", "总json")
        os.makedirs(total_dir, exist_ok=True)
        with open(os.path.join(total_dir, f"{email_addr}.json"), "w", encoding="utf-8") as f:
            json.dump(jwt_format_data, f, ensure_ascii=False, indent=2)
        
        # 存入批次目录
        batch_dir = os.path.join("qwen2api", "批json", BATCH_TIME)
        os.makedirs(batch_dir, exist_ok=True)
        with open(os.path.join(batch_dir, f"{email_addr}.json"), "w", encoding="utf-8") as f:
            json.dump(jwt_format_data, f, ensure_ascii=False, indent=2)
        print(f"[INFO] 模式1保存成功: {email_addr}")

    elif mode == "2":
        # 模式 2: qwen2api 多账号汇总
        target_file = "qwen2api总json.json"
        with FILE_LOCK:
            existing_data = []
            if os.path.exists(target_file):
                try:
                    with open(target_file, "r", encoding="utf-8") as f:
                        existing_data = json.load(f)
                except:
                    existing_data = []
            
            # 将新账号合并入列表 (jwt_format_data 本身就是个带一个元素的列表，所以用 extend)
            existing_data.extend(jwt_format_data)
            
            with open(target_file, "w", encoding="utf-8") as f:
                json.dump(existing_data, f, ensure_ascii=False, indent=2)
        print(f"[INFO] 模式2汇总保存成功: {email_addr}")

    elif mode == "3":
        # 模式 3: CPA 原始模式
        # 存入总目录
        total_dir = os.path.join("cpa", "总json")
        os.makedirs(total_dir, exist_ok=True)
        with open(os.path.join(total_dir, f"{email_addr}.json"), "w", encoding="utf-8") as f:
            json.dump(original_format_data, f, ensure_ascii=False, indent=2)
        
        # 存入批次目录
        batch_dir = os.path.join("cpa", "批json", BATCH_TIME)
        os.makedirs(batch_dir, exist_ok=True)
        with open(os.path.join(batch_dir, f"{email_addr}.json"), "w", encoding="utf-8") as f:
            json.dump(original_format_data, f, ensure_ascii=False, indent=2)
        print(f"[INFO] 模式3保存成功: {email_addr}")


def regup(mode):
    email_addr = ""
    print("[SRART]正在获取邮箱")

    s = MailService()
    email = s.request_email()
    if email.success != True:
        print("[ERROR] 邮箱获取失败：" + email.error)
        return
    else:
        email_addr = email.email or ""
        print("[INFO]邮箱获取成功：" + email_addr)
    _payload = json.loads(payload)
    _payload["email"] = email_addr

    token_data = None
    cookie_header = ""

    with curl_requests.Session(impersonate="chrome119") as session:
        n = session.post(url, json=_payload)
        cookie = n.cookies
        session.cookies.update(cookie)
        vurl = s.poll_code(email_addr)
        session.get(url=vurl, cookies=cookie)

        cookie_header = _cookies_to_header(session.cookies)

        try:
            token_data = oauth_device_flow(
                session, email_addr, cookie_header=cookie_header
            )
        except Exception as e:
            print(f"[WARN] Token extraction failed: {e}")
            token_data = None
            
        jwt_token_from_cookie = session.cookies.get("token")
        save_account(email_addr, token_data, cookie_header, _payload, mode, jwt_token_from_cookie)


def main():
    total = int(num)
    if total <= 0:
        return

    max_workers = max(1, min(threads, total))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(regup, reg_mode) for _ in range(total)]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                print(f"[ERROR] 线程任务异常: {e}")


if __name__ == "__main__":
    main()

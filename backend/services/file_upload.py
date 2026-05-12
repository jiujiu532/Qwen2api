"""
file_upload.py -- Qwen 文件上传服务
实现 OpenAI 兼容的文件上传，底层通过 Qwen OSS 预签名 URL 上传。

流程：
1. POST /api/v2/files/getstsToken 获取预签名上传 URL
2. PUT 文件到 OSS 预签名 URL
3. POST /api/v2/files/parse 触发文件解析
4. 轮询 /api/v2/files/parse/status 等待解析完成
5. 返回 file_id 供 chat completions 使用
"""

import asyncio
import logging
import time
from typing import Optional

log = logging.getLogger("qwen2api.file_upload")

# 文件类型映射
MIME_TO_FILETYPE = {
    "image/png": "image",
    "image/jpeg": "image",
    "image/jpg": "image",
    "image/gif": "image",
    "image/webp": "image",
    "image/svg+xml": "image",
    "application/pdf": "document",
    "text/plain": "document",
    "text/markdown": "document",
    "text/csv": "document",
    "application/json": "document",
    "application/msword": "document",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "document",
    "application/vnd.ms-excel": "document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "document",
    "application/vnd.ms-powerpoint": "document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "document",
    "video/mp4": "video",
    "video/webm": "video",
    "audio/mpeg": "audio",
    "audio/wav": "audio",
    "audio/ogg": "audio",
}


def detect_filetype(filename: str, mime_type: str = "") -> str:
    """检测文件类型（image/document/video/audio）。"""
    if mime_type and mime_type in MIME_TO_FILETYPE:
        return MIME_TO_FILETYPE[mime_type]
    # 根据扩展名判断
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    ext_map = {
        "png": "image", "jpg": "image", "jpeg": "image", "gif": "image",
        "webp": "image", "svg": "image", "bmp": "image",
        "pdf": "document", "txt": "document", "md": "document",
        "csv": "document", "json": "document", "xml": "document",
        "doc": "document", "docx": "document", "xls": "document",
        "xlsx": "document", "ppt": "document", "pptx": "document",
        "mp4": "video", "webm": "video", "avi": "video",
        "mp3": "audio", "wav": "audio", "ogg": "audio",
    }
    return ext_map.get(ext, "document")


async def upload_file_to_qwen(
    token: str,
    filename: str,
    file_content: bytes,
    mime_type: str = "",
    engine=None,
) -> dict:
    """
    上传文件到 Qwen，返回文件信息。
    
    Returns:
        {
            "file_id": "xxx",
            "file_path": "user_id/file_id_filename",
            "filename": "original_name.txt",
            "filetype": "document",
            "size": 1234,
        }
    """
    import httpx
    
    filetype = detect_filetype(filename, mime_type)
    filesize = len(file_content)
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://chat.qwen.ai/",
        "Origin": "https://chat.qwen.ai",
        "source": "web",
        "version": "0.2.46",
    }
    
    async with httpx.AsyncClient(timeout=60) as client:
        # Step 1: 获取 STS Token 和预签名 URL
        log.info(f"[FileUpload] 获取上传凭证: filename={filename} size={filesize} type={filetype}")
        sts_resp = await client.post(
            "https://chat.qwen.ai/api/v2/files/getstsToken",
            headers=headers,
            json={"filename": filename, "filesize": filesize, "filetype": filetype}
        )
        if sts_resp.status_code != 200:
            raise Exception(f"获取上传凭证失败: HTTP {sts_resp.status_code}")
        
        sts_data = sts_resp.json()
        if not sts_data.get("success"):
            raise Exception(f"获取上传凭证失败: {sts_data.get('data', {}).get('details', 'unknown error')}")
        
        oss_info = sts_data["data"]
        file_url = oss_info["file_url"]
        file_path = oss_info["file_path"]
        file_id = oss_info["file_id"]
        
        log.info(f"[FileUpload] 上传到 OSS: file_id={file_id} path={file_path}")
        
        # Step 2: 用 STS 凭证上传到 OSS
        # Qwen 返回的是 STS 临时凭证，需要用 OSS 标准方式上传
        access_key_id = oss_info["access_key_id"]
        access_key_secret = oss_info["access_key_secret"]
        security_token = oss_info["security_token"]
        bucket_name = oss_info["bucketname"]
        region = oss_info["region"]
        endpoint = oss_info.get("endpoint", "oss-accelerate.aliyuncs.com")
        
        # 使用 httpx 直接 PUT 到 OSS（带 STS 签名）
        oss_url = f"https://{bucket_name}.{endpoint}/{file_path}"
        
        # OSS V4 签名太复杂，改用简单方式：直接用 file_url 中的预签名参数构造上传 URL
        # 实际上 Qwen 的 file_url 是下载链接，上传需要用 OSS SDK
        # 简化方案：用 oss2 库上传
        try:
            import oss2
            auth = oss2.StsAuth(access_key_id, access_key_secret, security_token)
            bucket = oss2.Bucket(auth, f"https://{endpoint}", bucket_name)
            result = bucket.put_object(file_path, file_content)
            if result.status != 200:
                raise Exception(f"OSS put_object failed: HTTP {result.status}")
            log.info(f"[FileUpload] OSS 上传成功 (oss2): file_id={file_id}")
        except ImportError:
            # 没有 oss2 库，尝试用 httpx + 简单签名
            # 用预签名 URL 的方式：修改 file_url 为 PUT 方法
            # 实际上预签名 URL 只支持 GET，需要重新生成 PUT 签名
            # 最简单的方案：直接用 STS token 作为 header 认证
            oss_headers = {
                "x-oss-security-token": security_token,
                "Content-Type": mime_type or "application/octet-stream",
            }
            # 使用 V1 签名（简单）
            import hashlib, hmac, base64
            from datetime import datetime
            date_str = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")
            string_to_sign = f"PUT\n\n{mime_type or 'application/octet-stream'}\n{date_str}\nx-oss-security-token:{security_token}\n/{bucket_name}/{file_path}"
            signature = base64.b64encode(
                hmac.new(access_key_secret.encode(), string_to_sign.encode(), hashlib.sha1).digest()
            ).decode()
            oss_headers["Date"] = date_str
            oss_headers["Authorization"] = f"OSS {access_key_id}:{signature}"
            
            upload_resp = await client.put(oss_url, content=file_content, headers=oss_headers)
            if upload_resp.status_code not in (200, 201, 204):
                raise Exception(f"OSS 上传失败: HTTP {upload_resp.status_code} {upload_resp.text[:200]}")
            log.info(f"[FileUpload] OSS 上传成功 (httpx): file_id={file_id}")
        
        # Step 3: 通知 Qwen 解析文件
        parse_resp = await client.post(
            "https://chat.qwen.ai/api/v2/files/parse",
            headers=headers,
            json={"file_id": file_id, "file_path": file_path, "filetype": filetype}
        )
        if parse_resp.status_code == 200:
            parse_data = parse_resp.json()
            if parse_data.get("success"):
                log.info(f"[FileUpload] 文件解析已触发: file_id={file_id}")
            else:
                log.warning(f"[FileUpload] 文件解析触发失败: {parse_data}")
        
        # Step 4: 轮询解析状态（最多等 30 秒）
        parsed = False
        for _ in range(15):
            await asyncio.sleep(2)
            status_resp = await client.post(
                "https://chat.qwen.ai/api/v2/files/parse/status",
                headers=headers,
                json={"file_id": file_id}
            )
            if status_resp.status_code == 200:
                status_data = status_resp.json()
                if status_data.get("success"):
                    status_info = status_data.get("data", {})
                    if status_info.get("status") in ("success", "completed", "done"):
                        parsed = True
                        break
                    elif status_info.get("status") in ("failed", "error"):
                        log.warning(f"[FileUpload] 文件解析失败: {status_info}")
                        break
        
        if not parsed:
            log.warning(f"[FileUpload] 文件解析超时或失败，但文件已上传: file_id={file_id}")
        
        return {
            "file_id": file_id,
            "file_path": file_path,
            "filename": filename,
            "filetype": filetype,
            "size": filesize,
            "parsed": parsed,
        }


def build_file_reference(file_info: dict) -> dict:
    """构建 Qwen chat completions 中的文件引用格式。"""
    return {
        "id": file_info["file_id"],
        "name": file_info["filename"],
        "size": file_info["size"],
        "type": file_info["filetype"],
        "file_path": file_info["file_path"],
        "status": "uploaded",
    }

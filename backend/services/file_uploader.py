"""
file_uploader.py -- Qwen 多模态文件上传服务
负责将客户端提供的文件数据上传到 Qwen OSS 并完成解析。

流程：
1. 获取 STS 临时凭证 (getstsToken)
2. PUT 文件到阿里云 OSS
3. 通知 Qwen 解析文件 (files/parse)
4. 轮询解析状态 (files/parse/status)
5. 返回文件引用对象（用于 chat payload 的 files 数组）
"""

import asyncio
import base64
import hashlib
import logging
import time
import uuid
from typing import Optional
from dataclasses import dataclass

import httpx

log = logging.getLogger("qwen2api.file_uploader")

BASE_URL = "https://chat.qwen.ai"

# 支持的 MIME 类型分类
_IMAGE_MIMES = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml", "image/bmp", "image/tiff"}
_DOC_MIMES = {
    "application/pdf", "text/plain", "text/markdown", "text/html", "text/css",
    "text/x-python", "text/javascript", "text/x-java-source", "text/x-c", "text/x-c++src",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword", "text/csv",
}
_AUDIO_MIMES = {"audio/mpeg", "audio/wav", "audio/ogg", "audio/flac", "audio/aac", "audio/x-m4a"}
_VIDEO_MIMES = {"video/mp4", "video/webm", "video/quicktime", "video/x-matroska"}

ALL_SUPPORTED_MIMES = _IMAGE_MIMES | _DOC_MIMES | _AUDIO_MIMES | _VIDEO_MIMES


@dataclass
class UploadedFile:
    """上传完成后的文件引用，用于构建 chat payload"""
    file_id: str
    filename: str
    url: str
    mime_type: str
    size: int

    def to_payload(self) -> dict:
        """转换为 Qwen chat payload 中 files 数组的元素格式"""
        file_class = _get_file_class(self.mime_type)
        return {
            "type": "file",
            "file": {
                "id": self.file_id,
                "filename": self.filename,
                "meta": {
                    "name": self.filename,
                    "size": self.size,
                    "content_type": self.mime_type,
                    "parse_meta": {"parse_status": "success"},
                },
            },
            "id": self.file_id,
            "url": self.url,
            "name": self.filename,
            "file_type": self.mime_type,
            "file_class": file_class,
            "status": "uploaded",
        }


def _get_file_class(mime: str) -> str:
    """根据 MIME 类型返回 Qwen 的 file_class 分类"""
    if mime in _IMAGE_MIMES:
        return "image"
    if mime in _AUDIO_MIMES:
        return "audio"
    if mime in _VIDEO_MIMES:
        return "video"
    return "document"


def _get_filetype_param(mime: str) -> str:
    """根据 MIME 类型返回 getstsToken 的 filetype 参数"""
    if mime in _IMAGE_MIMES:
        return "image"
    if mime in _AUDIO_MIMES:
        return "audio"
    if mime in _VIDEO_MIMES:
        return "video"
    return "file"


def _guess_extension(mime: str) -> str:
    """根据 MIME 类型猜测文件扩展名"""
    ext_map = {
        "image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif",
        "image/webp": ".webp", "image/svg+xml": ".svg",
        "application/pdf": ".pdf", "text/plain": ".txt", "text/markdown": ".md",
        "audio/mpeg": ".mp3", "audio/wav": ".wav",
        "video/mp4": ".mp4", "video/webm": ".webm",
    }
    return ext_map.get(mime, ".bin")


async def _get_sts_token(token: str, filename: str, filesize: int, filetype: str) -> dict:
    """Step 1: 获取 STS 临时凭证"""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Origin": "https://chat.qwen.ai",
        "Referer": "https://chat.qwen.ai/",
    }
    body = {"filename": filename, "filesize": filesize, "filetype": filetype}

    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{BASE_URL}/api/v2/files/getstsToken",
                    headers=headers,
                    json=body,
                )
            if resp.status_code == 401 or resp.status_code == 403:
                raise Exception(f"unauthorized: getstsToken HTTP {resp.status_code}")
            if resp.status_code == 429:
                raise Exception(f"429: getstsToken rate limited")
            if resp.status_code != 200:
                if attempt < 2:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                raise Exception(f"getstsToken HTTP {resp.status_code}: {resp.text[:200]}")
            data = resp.json()
            if not data.get("success"):
                raise Exception(f"getstsToken failed: {resp.text[:200]}")
            return data["data"]
        except httpx.TimeoutException:
            if attempt < 2:
                await asyncio.sleep(0.5)
                continue
            raise Exception("getstsToken timeout after 3 attempts")


async def _upload_to_oss(sts_data: dict, file_bytes: bytes, mime_type: str) -> None:
    """Step 2: PUT 文件到 OSS（使用 STS Token 认证）
    
    官网实际使用的是 STS Token header 认证方式（非预签名 URL）。
    构建简单路径 URL + x-oss-security-token header。
    """
    bucket = sts_data.get("bucketname", "qwen-webui-prod")
    endpoint = sts_data.get("endpoint", "oss-accelerate.aliyuncs.com")
    file_path = sts_data.get("file_path", "")
    security_token = sts_data.get("security_token", "")

    # 构建上传 URL（不带签名参数）
    upload_url = f"https://{bucket}.{endpoint}/{file_path}"

    headers = {
        "x-oss-security-token": security_token,
        "Content-Type": mime_type,
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.put(upload_url, headers=headers, content=file_bytes)
        if resp.status_code in (200, 201, 204):
            return
        # STS 方式失败，尝试预签名 URL 方式
        file_url = sts_data.get("file_url", "")
        if file_url:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.put(file_url, content=file_bytes)
            if resp.status_code in (200, 201, 204):
                return
        raise Exception(f"OSS upload failed: HTTP {resp.status_code} {resp.text[:200]}")
    except httpx.TimeoutException:
        raise Exception("OSS upload timeout")
    except Exception as e:
        if "OSS upload failed" in str(e):
            raise
        raise Exception(f"OSS upload error: {e}")


async def _trigger_parse(token: str, file_id: str) -> None:
    """Step 3: 通知 Qwen 解析文件"""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Origin": "https://chat.qwen.ai",
        "Referer": "https://chat.qwen.ai/",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{BASE_URL}/api/v2/files/parse",
            headers=headers,
            json={"file_id": file_id},
        )
    if resp.status_code != 200:
        log.warning(f"[FileUploader] parse trigger failed: {resp.status_code} {resp.text[:100]}")


async def _wait_parse(token: str, file_id: str, timeout_s: float = 60) -> bool:
    """Step 4: 轮询解析状态，返回是否成功"""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Origin": "https://chat.qwen.ai",
        "Referer": "https://chat.qwen.ai/",
    }
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{BASE_URL}/api/v2/files/parse/status",
                    headers=headers,
                    json={"file_id": file_id},
                )
            if resp.status_code == 200:
                data = resp.json()
                status = data.get("data", {}).get("status", "") or data.get("status", "")
                if status == "success" or not status:
                    return True
                if status == "failed":
                    log.warning(f"[FileUploader] parse failed for {file_id}")
                    return False
        except Exception:
            pass
        await asyncio.sleep(0.5)
    log.warning(f"[FileUploader] parse timeout for {file_id}")
    return True  # 超时也放行，让 Qwen 自己处理


async def upload_file(token: str, file_bytes: bytes, filename: str, mime_type: str) -> UploadedFile:
    """完整的文件上传流程：STS → OSS → Parse → 返回引用

    Args:
        token: Qwen 账号 token
        file_bytes: 文件原始字节
        filename: 文件名
        mime_type: MIME 类型

    Returns:
        UploadedFile 对象，可通过 .to_payload() 转为 chat payload 格式
    """
    filesize = len(file_bytes)
    filetype = _get_filetype_param(mime_type)

    # Step 1: 获取 STS Token
    sts_data = await _get_sts_token(token, filename, filesize, filetype)
    file_id = sts_data["file_id"]
    file_url = sts_data["file_url"]

    log.info(f"[FileUploader] STS obtained: file_id={file_id} filename={filename} size={filesize}")

    # Step 2: 上传到 OSS
    await _upload_to_oss(sts_data, file_bytes, mime_type)
    log.info(f"[FileUploader] OSS upload done: file_id={file_id}")

    # Step 3: 触发解析
    await _trigger_parse(token, file_id)

    # Step 4: 等待解析完成
    await _wait_parse(token, file_id, timeout_s=30)

    return UploadedFile(
        file_id=file_id,
        filename=filename,
        url=file_url.split("?")[0],  # 去掉签名参数，保留基础 URL
        mime_type=mime_type,
        size=filesize,
    )


async def upload_files_concurrent(
    token: str,
    files: list[tuple[bytes, str, str]],
    max_concurrent: int = 5,
) -> list[UploadedFile]:
    """并发上传多个文件

    Args:
        token: Qwen 账号 token
        files: [(file_bytes, filename, mime_type), ...]
        max_concurrent: 最大并发数

    Returns:
        UploadedFile 列表
    """
    sem = asyncio.Semaphore(max_concurrent)

    async def _upload_one(file_bytes: bytes, filename: str, mime_type: str) -> UploadedFile:
        async with sem:
            return await upload_file(token, file_bytes, filename, mime_type)

    tasks = [_upload_one(fb, fn, mt) for fb, fn, mt in files]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    uploaded = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            log.error(f"[FileUploader] file {i} upload failed: {r}")
            raise Exception(f"File upload failed ({files[i][1]}): {r}")
        uploaded.append(r)
    return uploaded


# ============================================================================
# 内容提取：从 OpenAI 多模态格式中提取文件数据
# ============================================================================

async def extract_files_from_messages(messages: list) -> list[tuple[bytes, str, str]]:
    """从 OpenAI 格式的 messages 中提取所有文件数据

    支持格式：
    - {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
    - {"type": "image_url", "image_url": {"url": "https://..."}}

    Returns:
        [(file_bytes, filename, mime_type), ...]
    """
    files = []
    for msg in messages:
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type", "")

            if btype == "image_url":
                url = (block.get("image_url") or {}).get("url", "")
                if not url:
                    continue
                fb, fn, mt = await _resolve_image_url(url)
                if fb:
                    files.append((fb, fn, mt))

            elif btype == "image":
                # Anthropic 格式兼容
                source = block.get("source", {})
                if source.get("type") == "base64":
                    data = source.get("data", "")
                    mime = source.get("media_type", "image/png")
                    fb = base64.b64decode(data)
                    fn = f"image_{uuid.uuid4().hex[:8]}{_guess_extension(mime)}"
                    files.append((fb, fn, mime))

    return files


async def _resolve_image_url(url: str) -> tuple[Optional[bytes], str, str]:
    """解析 image_url，支持 base64 data URI 和 HTTP URL"""
    if url.startswith("data:"):
        # data:image/png;base64,iVBOR...
        try:
            header, data = url.split(",", 1)
            mime = header.split(":")[1].split(";")[0]
            file_bytes = base64.b64decode(data)
            filename = f"image_{uuid.uuid4().hex[:8]}{_guess_extension(mime)}"
            return file_bytes, filename, mime
        except Exception as e:
            log.warning(f"[FileUploader] base64 decode failed: {e}")
            return None, "", ""

    if url.startswith("http://") or url.startswith("https://"):
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.get(url)
            if resp.status_code != 200:
                log.warning(f"[FileUploader] download failed: {url} -> {resp.status_code}")
                return None, "", ""
            mime = resp.headers.get("content-type", "image/png").split(";")[0].strip()
            file_bytes = resp.content
            # 从 URL 提取文件名
            path = url.split("?")[0].split("/")[-1]
            filename = path if "." in path else f"file_{uuid.uuid4().hex[:8]}{_guess_extension(mime)}"
            return file_bytes, filename, mime
        except Exception as e:
            log.warning(f"[FileUploader] download error: {url} -> {e}")
            return None, "", ""

    return None, "", ""

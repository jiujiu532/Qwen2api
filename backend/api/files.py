"""
files.py -- OpenAI 兼容的文件上传 API
支持上传图片/文档/音频/视频，底层通过 Qwen OSS 实现。
兼容 OpenAI /v1/files 接口格式。
"""

import logging
import time
import uuid
from fastapi import APIRouter, Request, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse
from backend.core.auth import verify_api_key
from backend.services.file_upload import upload_file_to_qwen, detect_filetype

log = logging.getLogger("qwen2api.files")
router = APIRouter()

# 内存中缓存已上传的文件信息（file_id -> metadata）
_uploaded_files: dict[str, dict] = {}


@router.post("/v1/files")
@router.post("/files")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    purpose: str = Form(default="assistants"),
):
    """
    OpenAI 兼容的文件上传接口。
    
    上传后返回 file object，可在 chat completions 的 messages 中通过 file_id 引用。
    
    支持的文件类型：图片、PDF、文本、Office 文档等。
    """
    verify_api_key(request)
    
    pool = request.app.state.account_pool
    
    # 获取一个可用账号的 token
    acc = await pool.acquire_wait(timeout=30)
    if not acc:
        raise HTTPException(503, "No available accounts for file upload")
    
    try:
        content = await file.read()
        filename = file.filename or f"upload_{int(time.time())}"
        mime_type = file.content_type or ""
        
        if len(content) > 50 * 1024 * 1024:  # 50MB 限制
            raise HTTPException(413, "File too large (max 50MB)")
        
        # 上传到 Qwen
        result = await upload_file_to_qwen(
            token=acc.token,
            filename=filename,
            file_content=content,
            mime_type=mime_type,
        )
        
        # 缓存文件信息
        file_obj = {
            "id": f"file-{result['file_id']}",
            "object": "file",
            "bytes": result["size"],
            "created_at": int(time.time()),
            "filename": result["filename"],
            "purpose": purpose,
            # 内部使用
            "_qwen_file_id": result["file_id"],
            "_qwen_file_path": result["file_path"],
            "_qwen_filetype": result["filetype"],
            "_qwen_parsed": result["parsed"],
            "_account_email": acc.email,
        }
        _uploaded_files[file_obj["id"]] = file_obj
        
        log.info(f"[Files] 上传成功: {file_obj['id']} ({filename}, {result['size']} bytes)")
        
        # 返回 OpenAI 格式
        return {
            "id": file_obj["id"],
            "object": "file",
            "bytes": file_obj["bytes"],
            "created_at": file_obj["created_at"],
            "filename": file_obj["filename"],
            "purpose": file_obj["purpose"],
        }
    
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"[Files] 上传失败: {e}")
        raise HTTPException(500, f"File upload failed: {str(e)[:200]}")
    finally:
        pool.release(acc)


@router.get("/v1/files")
@router.get("/files")
async def list_files(request: Request):
    """列出已上传的文件。"""
    verify_api_key(request)
    data = [
        {
            "id": f["id"],
            "object": "file",
            "bytes": f["bytes"],
            "created_at": f["created_at"],
            "filename": f["filename"],
            "purpose": f["purpose"],
        }
        for f in _uploaded_files.values()
    ]
    return {"object": "list", "data": data}


@router.get("/v1/files/{file_id}")
@router.get("/files/{file_id}")
async def get_file(file_id: str, request: Request):
    """获取文件信息。"""
    verify_api_key(request)
    if file_id not in _uploaded_files:
        raise HTTPException(404, "File not found")
    f = _uploaded_files[file_id]
    return {
        "id": f["id"],
        "object": "file",
        "bytes": f["bytes"],
        "created_at": f["created_at"],
        "filename": f["filename"],
        "purpose": f["purpose"],
    }


@router.delete("/v1/files/{file_id}")
@router.delete("/files/{file_id}")
async def delete_file(file_id: str, request: Request):
    """删除文件。"""
    verify_api_key(request)
    if file_id in _uploaded_files:
        del _uploaded_files[file_id]
    return {"id": file_id, "object": "file", "deleted": True}


def get_qwen_file_info(file_id: str) -> dict | None:
    """获取文件的 Qwen 内部信息（供 chat completions 使用）。"""
    return _uploaded_files.get(file_id)

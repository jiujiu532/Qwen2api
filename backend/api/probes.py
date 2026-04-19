"""
probes.py — 健康检查与模型列表
"""

import time
from fastapi import APIRouter, Request
from backend.core.config import MODEL_MAP, VERSION

router = APIRouter()


@router.get("/health")
@router.get("/healthz")
async def health():
    return {"status": "ok", "version": VERSION}


@router.get("/v1/models")
@router.get("/models")
async def list_models():
    """返回兼容 OpenAI /v1/models 格式的模型列表。"""
    models = set(MODEL_MAP.values())
    # 也包含所有别名
    all_names = set(MODEL_MAP.keys()) | models
    data = []
    for name in sorted(all_names):
        data.append({
            "id": name,
            "object": "model",
            "created": int(time.time()),
            "owned_by": "qwen2api",
        })
    return {"object": "list", "data": data}

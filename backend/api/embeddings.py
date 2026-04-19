"""
embeddings.py — Embeddings 兼容 API（桩）
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()


@router.post("/v1/embeddings")
@router.post("/embeddings")
async def create_embedding(request: Request):
    """OpenAI /v1/embeddings 兼容端点（桩实现）。"""
    # TODO: 完整的 Embeddings 实现
    return JSONResponse(
        status_code=501,
        content={"error": {"type": "not_implemented", "message": "Embeddings endpoint is not yet implemented."}}
    )

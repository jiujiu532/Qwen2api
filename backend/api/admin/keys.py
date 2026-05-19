"""
keys.py -- API 密钥管理端点
"""

import uuid
from fastapi import APIRouter, Depends
from backend.core.config import API_KEYS, save_api_keys, load_api_keys
from . import _require_admin

router = APIRouter()


@router.get("/keys")
async def list_keys(_=Depends(_require_admin)):
    keys = load_api_keys()
    return {"keys": sorted(keys)}


@router.post("/keys")
async def generate_key(_=Depends(_require_admin)):
    new_key = f"sk-{uuid.uuid4().hex}"
    keys = load_api_keys()
    keys.add(new_key)
    save_api_keys(keys)
    API_KEYS.clear()
    API_KEYS.update(keys)
    return {"ok": True, "key": new_key}


@router.delete("/keys/{key}")
async def delete_key(key: str, _=Depends(_require_admin)):
    keys = load_api_keys()
    keys.discard(key)
    save_api_keys(keys)
    API_KEYS.clear()
    API_KEYS.update(keys)
    return {"ok": True}

"""
系统全局设置 API

GET  /api/system/settings          — 读取所有设置
POST /api/system/settings          — 批量更新设置（只更新提交的 key）
GET  /api/system/settings/{key}    — 读取单个值
"""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Dict, Optional

from database import db
from utils import now_iso

router = APIRouter(prefix="/api/system", tags=["system"])

# 默认值（首次读取时若 DB 无记录则返回此值）
_DEFAULTS: Dict[str, str] = {
    "projects_default_dir": r"F:\ADS_Projects",
    "github_default_org":   "AiDS-Projects",
}


async def get_setting(key: str) -> str:
    """读取单个设置值，不存在时返回默认值"""
    row = await db.fetch_one(
        "SELECT value FROM system_settings WHERE key = ?", (key,)
    )
    if row:
        return row["value"]
    return _DEFAULTS.get(key, "")


async def get_all_settings() -> Dict[str, str]:
    """读取所有设置，合并默认值"""
    rows = await db.fetch_all("SELECT key, value FROM system_settings")
    result = dict(_DEFAULTS)   # 先填默认值
    for r in rows:
        result[r["key"]] = r["value"]   # DB 值覆盖默认
    return result


@router.get("/settings")
async def read_all_settings():
    return {"settings": await get_all_settings()}


@router.get("/settings/{key}")
async def read_setting(key: str):
    value = await get_setting(key)
    return {"key": key, "value": value}


class SettingsUpdate(BaseModel):
    settings: Dict[str, str]


@router.post("/settings")
async def update_settings(body: SettingsUpdate):
    now = now_iso()
    for key, value in body.settings.items():
        await db.execute(
            "INSERT INTO system_settings (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=?, updated_at=?",
            (key, value, now, value, now),
        )
    return {"updated": list(body.settings.keys())}

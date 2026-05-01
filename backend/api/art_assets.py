"""美术资产库 API"""
import json
from fastapi import APIRouter, Query
from typing import Optional
from database import db

router = APIRouter(prefix="/api/art-assets", tags=["art-assets"])


@router.get("")
async def search_art_assets(
    q: Optional[str] = Query(None, description="关键词"),
    type: Optional[str] = Query(None, description="类型: icon/illustration/photo/sprite"),
    style: Optional[str] = Query(None, description="风格: flat/outline/filled"),
    source: Optional[str] = Query(None, description="来源: iconify/kenney/pexels"),
    format: Optional[str] = Query(None, description="格式: svg/png/jpg"),
    limit: int = Query(20, le=100),
    offset: int = Query(0),
):
    """搜索美术资产库"""
    conditions = []
    params = []

    if q:
        conditions.append("(name LIKE ? OR tags LIKE ? OR description LIKE ?)")
        params += [f"%{q}%", f"%{q}%", f"%{q}%"]
    if type:
        conditions.append("type = ?")
        params.append(type)
    if style:
        conditions.append("style = ?")
        params.append(style)
    if source:
        conditions.append("source = ?")
        params.append(source)
    if format:
        conditions.append("format = ?")
        params.append(format)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = await db.fetch_all(
        f"SELECT * FROM art_assets {where} ORDER BY used_count DESC, added_at DESC LIMIT ? OFFSET ?",
        tuple(params) + (limit, offset),
    )

    total_row = await db.fetch_one(
        f"SELECT COUNT(*) as cnt FROM art_assets {where}",
        tuple(params),
    )
    total = total_row["cnt"] if total_row else 0

    assets = []
    for r in rows:
        d = dict(r)
        try:
            d["tags"] = json.loads(d.get("tags") or "[]")
        except Exception:
            d["tags"] = []
        assets.append(d)

    return {"assets": assets, "total": total, "offset": offset, "limit": limit}


@router.get("/stats")
async def art_assets_stats():
    """资产库统计"""
    total = await db.fetch_one("SELECT COUNT(*) as cnt FROM art_assets")
    by_type = await db.fetch_all(
        "SELECT type, COUNT(*) as cnt FROM art_assets GROUP BY type ORDER BY cnt DESC"
    )
    by_source = await db.fetch_all(
        "SELECT source, COUNT(*) as cnt FROM art_assets GROUP BY source ORDER BY cnt DESC"
    )
    top_used = await db.fetch_all(
        "SELECT id, name, type, used_count FROM art_assets WHERE used_count > 0 ORDER BY used_count DESC LIMIT 10"
    )
    return {
        "total": total["cnt"] if total else 0,
        "by_type": [dict(r) for r in by_type],
        "by_source": [dict(r) for r in by_source],
        "top_used": [dict(r) for r in top_used],
    }


@router.get("/{asset_id}")
async def get_art_asset(asset_id: str):
    """获取单个资产详情"""
    from fastapi import HTTPException
    row = await db.fetch_one("SELECT * FROM art_assets WHERE id = ?", (asset_id,))
    if not row:
        raise HTTPException(404, "资产不存在")
    d = dict(row)
    try:
        d["tags"] = json.loads(d.get("tags") or "[]")
    except Exception:
        d["tags"] = []
    return d


@router.post("/{asset_id}/use")
async def mark_asset_used(asset_id: str):
    """标记资产被使用（used_count +1）"""
    from utils import now_iso
    await db.execute(
        "UPDATE art_assets SET used_count = used_count + 1, last_used_at = ? WHERE id = ?",
        (now_iso(), asset_id),
    )
    return {"ok": True}

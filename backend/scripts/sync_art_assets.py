"""
sync_art_assets.py — 从 G_ArtRes/manifest.json 同步到 art_assets 表

启动时调用，增量同步（只新增/更新，不删除）。
"""
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger("sync_art_assets")


async def sync_art_assets_from_manifest(local_path: str) -> int:
    """从 manifest.json 同步到 art_assets 表，返回新增/更新数量"""
    from database import db
    from utils import now_iso

    manifest_path = Path(local_path) / "manifest.json"
    if not manifest_path.exists():
        logger.warning("G_ArtRes/manifest.json 不存在: %s", manifest_path)
        return 0

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error("读取 manifest.json 失败: %s", e)
        return 0

    assets = manifest.get("assets", [])
    if not assets:
        return 0

    # 获取已有记录的 ID 集合（用于判断增量）
    existing = await db.fetch_all("SELECT id FROM art_assets")
    existing_ids = {r["id"] for r in existing}

    inserted = 0
    updated = 0
    now = now_iso()

    for asset in assets:
        aid = asset.get("id", "")
        if not aid:
            continue

        tags = asset.get("tags", [])
        tags_json = json.dumps(tags, ensure_ascii=False)

        record = {
            "id": aid,
            "name": asset.get("name", ""),
            "description": asset.get("description", ""),
            "tags": tags_json,
            "type": asset.get("type", "icon"),
            "style": asset.get("style", ""),
            "format": asset.get("format", "svg"),
            "width": asset.get("width"),
            "height": asset.get("height"),
            "file_path": asset.get("path", ""),
            "source": asset.get("source", ""),
            "source_ref": asset.get("source_ref", ""),
            "source_url": asset.get("source_url", ""),
            "project_scope": asset.get("project_scope", "global"),
            "used_count": asset.get("used_count", 0),
            "last_used_at": asset.get("last_used_at"),
            "added_at": asset.get("added_at", now),
        }

        if aid in existing_ids:
            # 只更新变化的字段
            await db.execute("""
                UPDATE art_assets SET
                    name=?, tags=?, type=?, style=?, format=?,
                    width=?, height=?, file_path=?, source=?,
                    source_ref=?, source_url=?, used_count=?
                WHERE id=?
            """, (
                record["name"], record["tags"], record["type"], record["style"],
                record["format"], record["width"], record["height"],
                record["file_path"], record["source"], record["source_ref"],
                record["source_url"], record["used_count"], aid,
            ))
            updated += 1
        else:
            await db.execute("""
                INSERT INTO art_assets
                (id, name, description, tags, type, style, format, width, height,
                 file_path, source, source_ref, source_url, project_scope,
                 used_count, last_used_at, added_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                record["id"], record["name"], record["description"],
                record["tags"], record["type"], record["style"], record["format"],
                record["width"], record["height"], record["file_path"],
                record["source"], record["source_ref"], record["source_url"],
                record["project_scope"], record["used_count"],
                record["last_used_at"], record["added_at"],
            ))
            inserted += 1

    logger.info("美术资产库同步完成: 新增 %d，更新 %d，共 %d 条", inserted, updated, len(assets))
    return inserted + updated

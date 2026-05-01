"""
art_asset_searcher.py — 网络资产搜索与入库

支持来源：
  Pexels   — 高质量摄影图片（需 API Key）
  unDraw   — SVG 插画（无需 Key，公开 CDN）
  Poly Haven — 3D 材质 / HDRI（无需 Key）

搜索结果自动：
  1. 下载文件到 G_ArtRes 对应目录
  2. 写入 art_assets 表（search-then-store 模式）
  3. 更新 G_ArtRes/manifest.json
"""
import hashlib
import json
import logging
import ssl
import urllib.request
import urllib.error
from pathlib import Path
from typing import List, Optional

from config import settings
from database import db
from utils import generate_id, now_iso

logger = logging.getLogger("art_asset_searcher")

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


# ─── 公共工具 ─────────────────────────────────────────────

def _http_get(url: str, headers: dict = None, timeout: int = 15) -> Optional[bytes]:
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "ArtAssetSearcher/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as r:
            return r.read()
    except Exception as e:
        logger.warning("HTTP GET 失败 %s: %s", url, e)
        return None


def _save_to_art_repo(data: bytes, rel_path: str) -> Optional[str]:
    """保存文件到 G_ArtRes，返回相对路径"""
    base = Path(settings.ART_ASSETS_LOCAL_PATH)
    if not base.exists():
        return None
    full = base / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    try:
        full.write_bytes(data)
        return rel_path
    except Exception as e:
        logger.warning("写入 G_ArtRes 失败 %s: %s", rel_path, e)
        return None


async def _upsert_art_asset(asset_id: str, name: str, tags: list, asset_type: str,
                             style: str, fmt: str, width: int, height: int,
                             file_path: str, source: str, source_ref: str = "",
                             source_url: str = "", description: str = "") -> bool:
    """写入 art_assets 表"""
    try:
        await db.execute("""
            INSERT INTO art_assets
            (id, name, description, tags, type, style, format, width, height,
             file_path, source, source_ref, source_url, project_scope, used_count, added_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'global',0,?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name, tags=excluded.tags, file_path=excluded.file_path
        """, (asset_id, name, description,
              json.dumps(tags, ensure_ascii=False),
              asset_type, style, fmt, width, height,
              file_path, source, source_ref, source_url, now_iso()))
        return True
    except Exception as e:
        logger.warning("art_assets 写入失败: %s", e)
        return False


def _update_manifest(asset: dict) -> None:
    """追加资产到 G_ArtRes/manifest.json"""
    base = Path(settings.ART_ASSETS_LOCAL_PATH)
    mf = base / "manifest.json"
    if not mf.exists():
        return
    try:
        data = json.loads(mf.read_text(encoding="utf-8"))
        assets = data.get("assets", [])
        # 去重（按 id）
        existing_ids = {a["id"] for a in assets}
        if asset["id"] not in existing_ids:
            assets.append(asset)
            data["assets"] = assets
            data["updated_at"] = now_iso()
            mf.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning("manifest.json 更新失败: %s", e)


# ─── Pexels ───────────────────────────────────────────────

async def search_pexels(query: str, per_page: int = 5) -> List[dict]:
    """搜索 Pexels 图片并入库，返回已入库的资产 ID 列表"""
    if not settings.PEXELS_API_KEY:
        logger.debug("PEXELS_API_KEY 未配置，跳过")
        return []

    url = f"https://api.pexels.com/v1/search?query={urllib.parse.quote(query)}&per_page={per_page}&orientation=landscape"
    raw = _http_get(url, headers={"Authorization": settings.PEXELS_API_KEY})
    if not raw:
        return []

    try:
        data = json.loads(raw)
    except Exception:
        return []

    results = []
    for photo in data.get("photos", []):
        pid = str(photo.get("id", ""))
        asset_id = f"AST-pexels-{pid}"
        filename = f"photos/pexels/{pid}.jpg"
        src_url = photo.get("src", {}).get("large", "")
        if not src_url:
            continue

        # 下载图片
        img_data = _http_get(src_url)
        if not img_data:
            continue
        saved = _save_to_art_repo(img_data, filename)
        if not saved:
            continue

        tags = [query, "photo", "pexels"] + (photo.get("alt", "").lower().split()[:3])
        await _upsert_art_asset(
            asset_id, photo.get("alt", query)[:80], tags,
            "photo", "realistic", "jpg",
            photo.get("width", 0), photo.get("height", 0),
            filename, "pexels", f"pexels:{pid}", src_url,
            description=photo.get("alt", ""),
        )
        _update_manifest({
            "id": asset_id, "name": photo.get("alt", query)[:80],
            "path": filename, "type": "photo", "style": "realistic",
            "format": "jpg", "width": photo.get("width", 0),
            "height": photo.get("height", 0),
            "tags": tags, "source": "pexels",
            "source_ref": f"pexels:{pid}", "source_url": src_url,
            "added_at": now_iso(), "used_count": 0,
        })
        results.append(asset_id)
        logger.info("Pexels 入库: %s → %s", query, filename)

    return results


# ─── unDraw ───────────────────────────────────────────────

# unDraw 颜色和关键词映射（部分常用 slug）
_UNDRAW_SLUGS = {
    "empty": "empty_re_opql",
    "empty-state": "empty_re_opql",
    "no-data": "no_data_re_kwbl",
    "success": "completed_tasks_vs6q",
    "error": "server_down_s4lk",
    "404": "page_not_found_su7k",
    "loading": "loading_re_5axr",
    "welcome": "welcome_cats_thqn",
    "onboarding": "adventure_map_hnin",
    "dashboard": "dashboard_re_3b76",
    "settings": "settings_re_b08x",
}


async def fetch_undraw(keyword: str, color: str = "6366f1") -> Optional[str]:
    """从 unDraw CDN 获取 SVG 插画并入库，返回资产 ID"""
    slug = _UNDRAW_SLUGS.get(keyword.lower().replace(" ", "-"),
                              _UNDRAW_SLUGS.get(keyword.lower()))
    if not slug:
        # 尝试直接用关键词猜 slug
        slug = keyword.lower().replace(" ", "_").replace("-", "_")

    url = f"https://undraw.co/api/illustrations/{slug}?color=%23{color.lstrip('#')}"
    raw = _http_get(url, timeout=10)
    if not raw or not raw.startswith(b"<svg"):
        # 降级：直接用 CDN URL
        url = f"https://undraw.co/illustrations/{slug}.svg"
        raw = _http_get(url, timeout=10)
        if not raw or not raw.startswith(b"<svg"):
            logger.debug("unDraw 未找到: %s", keyword)
            return None

    asset_id = f"AST-undraw-{hashlib.md5(slug.encode()).hexdigest()[:8]}"
    filename = f"illustrations/undraw/{slug}.svg"
    saved = _save_to_art_repo(raw, filename)
    if not saved:
        return None

    tags = [keyword, "illustration", "undraw", "svg"]
    await _upsert_art_asset(
        asset_id, keyword, tags,
        "illustration", "flat", "svg", 800, 600,
        filename, "undraw", f"undraw:{slug}",
        f"https://undraw.co/illustrations/{slug}.svg",
    )
    _update_manifest({
        "id": asset_id, "name": keyword,
        "path": filename, "type": "illustration", "style": "flat",
        "format": "svg", "width": 800, "height": 600,
        "tags": tags, "source": "undraw",
        "source_ref": f"undraw:{slug}",
        "source_url": f"https://undraw.co/illustrations/{slug}.svg",
        "added_at": now_iso(), "used_count": 0,
    })
    logger.info("unDraw 入库: %s → %s", keyword, filename)
    return asset_id


# ─── Poly Haven ───────────────────────────────────────────

async def fetch_polyhaven_texture(asset_id_ph: str, resolution: str = "1k") -> Optional[str]:
    """从 Poly Haven 下载 PBR 材质包并入库"""
    # 获取文件列表
    url = f"https://api.polyhaven.com/files/{asset_id_ph}"
    raw = _http_get(url)
    if not raw:
        return None

    try:
        files = json.loads(raw)
    except Exception:
        return None

    # 优先取 PNG albedo
    try:
        dl_url = files["Diffuse"]["png"][resolution]["url"]
    except (KeyError, TypeError):
        try:
            dl_url = list(list(files.values())[0].values())[0][resolution]["url"]
        except Exception:
            return None

    img_data = _http_get(dl_url)
    if not img_data:
        return None

    ext = dl_url.split(".")[-1].lower()
    asset_id = f"AST-ph-{asset_id_ph}-{resolution}"
    filename = f"3d/textures/{asset_id_ph}_{resolution}.{ext}"
    saved = _save_to_art_repo(img_data, filename)
    if not saved:
        return None

    tags = [asset_id_ph, "texture", "pbr", "polyhaven", "3d"]
    await _upsert_art_asset(
        asset_id, asset_id_ph, tags,
        "texture", "realistic", ext, 0, 0,
        filename, "polyhaven", f"polyhaven:{asset_id_ph}",
        f"https://polyhaven.com/a/{asset_id_ph}",
    )
    logger.info("Poly Haven 入库: %s → %s", asset_id_ph, filename)
    return asset_id


# ─── 统一搜索入口 ─────────────────────────────────────────

async def search_and_store(query: str, asset_type: str = "photo",
                            limit: int = 3) -> List[str]:
    """
    统一搜索入口，按资产类型路由到对应来源。
    返回已入库的资产 ID 列表。
    """
    if asset_type == "photo":
        return await search_pexels(query, per_page=limit)
    elif asset_type == "illustration":
        aid = await fetch_undraw(query)
        return [aid] if aid else []
    elif asset_type in ("texture", "hdri"):
        # Poly Haven 按资产 ID 精确获取，不支持关键词搜索
        aid = await fetch_polyhaven_texture(query)
        return [aid] if aid else []
    else:
        logger.debug("不支持的搜索类型: %s", asset_type)
        return []


# fix missing import
import urllib.parse

"""GenerateAssetsAction — ArtistAgent 的核心 Action

消费 ArtAgent 产出的 asset_manifest.yaml，把 `status: pending` 的条目逐个落地：

  1. 检索本地资产库（art_assets 表，33000+ 条）→ 命中则登记为 sourced
  2. 未命中 → 生成占位图（PIL）→ 登记为 placeholder
  3. 回写 asset_manifest.yaml（状态 + 实际路径）

不做 AI 图像生成 —— 系统当前没有接入图像模型，硬写一个"假装生成"的分支
只会产出空文件并让下游误以为资产已就绪。需要真实 AIGC 时在
`_resolve_one` 里加一个来源分支即可。

写入：
  {docs_prefix}asset_manifest.yaml   （覆盖，带落地状态）
  {docs_prefix}assets/placeholder/*.png
  {docs_prefix}资产落地报告.md
"""
from __future__ import annotations

import io
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from actions.base import ActionBase, ActionResult

logger = logging.getLogger("action.generate_assets")

# manifest 里的 type → art_assets.type 的候选值（库里实际只有这几种）
#
# 不做跨类型回退：实测 sprite 回退到 icon 后，「爆炸序列帧 64x64 8帧」
# 匹配到了一个 343 字节的 material-symbols/explosion.svg —— 格式不兼容
# （Phaser 加载 spritesheet 要 PNG，SVG 用不了），语义也不同（单帧静态图 ≠ 8 帧动画）。
# 拿一个不能用的资产比给占位图更糟：占位图至少在报告里明确标了"需替换"。
_TYPE_ALIAS: Dict[str, List[str]] = {
    "icon":         ["icon"],
    "sprite":       ["sprite"],
    "tileset":      ["tileset"],
    "texture":      ["tileset"],
    "illustration": ["illustration"],
    "ui_element":   ["icon"],        # UI 元素确实常用图标，保留
    "model":        ["model"],
    "animation":    ["animation"],
    "hdri":         ["hdri"],
}

# 各 manifest 类型可接受的文件扩展名。空集合 = 不限制。
# 关键约束：精灵图/图集必须是位图，SVG 无法作为 spritesheet 被游戏引擎加载。
_TYPE_ALLOWED_EXT: Dict[str, set] = {
    "sprite":    {".png", ".jpg", ".jpeg", ".webp", ".bmp"},
    "tileset":   {".png", ".jpg", ".jpeg", ".webp", ".bmp"},
    "texture":   {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tga", ".exr"},
    "animation": {".png", ".gif", ".webp", ".json", ".atlas"},
    "hdri":      {".hdr", ".exr"},
    # icon / ui_element / illustration 允许 svg
}

# 描述里出现这些信号 = 需要多帧动画序列，图标库不可能满足，直接走占位图
_MULTIFRAME_RE = __import__("re").compile(
    r"(\d+\s*帧|\b\d+\s*frames?\b|序列帧|spritesheet|sprite\s*sheet|逐帧|动画序列)",
    __import__("re").IGNORECASE,
)

# 占位图默认尺寸（按类型粗分）
_PLACEHOLDER_SIZE: Dict[str, Tuple[int, int]] = {
    "icon":         (64, 64),
    "ui_element":   (128, 64),
    "sprite":       (128, 128),
    "illustration": (256, 256),
    "tileset":      (256, 256),
    "texture":      (256, 256),
}

# 不做图像化处理的类型（音频等）—— 只登记待办，不产出占位文件
_NON_IMAGE_TYPES = {"audio", "sound", "sfx", "bgm", "music", "video", "font"}

_STOPWORDS = {
    "的", "了", "和", "与", "或", "个", "这", "那", "一个",
    "the", "a", "an", "of", "for", "and", "or", "to", "in", "on", "with",
    "px", "icon", "图标", "音效", "贴图",
}


class GenerateAssetsAction(ActionBase):

    available_for_traits = {"any_of": ["category:game"]}

    @property
    def name(self) -> str:
        return "generate_assets"

    @property
    def description(self) -> str:
        return "按 asset_manifest 检索资产库并补齐占位图，产出可用资产清单"

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        docs_prefix = context.get("docs_prefix", "docs/")
        ticket_id = context.get("ticket_id", "")
        ticket_title = context.get("ticket_title", "")
        sop_cfg = context.get("sop_config") or {}
        allow_placeholder = bool(sop_cfg.get("fallback_to_placeholder", True))
        wanted_types = sop_cfg.get("asset_types") or []

        manifest_items = await self._load_manifest(context)
        if not manifest_items:
            logger.info("🎨 无资产清单条目，ArtistAgent 跳过（ticket=%s）", ticket_id[:12])
            return ActionResult(
                success=True,
                data={"assets_total": 0, "sourced": 0, "placeholder": 0, "skipped": 0,
                      "detail": "上游未产出 asset_manifest 或清单为空"},
                message="无待处理资产，跳过",
            )

        # SOP 声明了 asset_types 时按其过滤（manifest 可能含音频等本阶段不管的类型）
        if wanted_types:
            allow = set(wanted_types)
            manifest_items = [
                it for it in manifest_items
                if it.get("type") in allow or it.get("type") in _NON_IMAGE_TYPES
            ] or manifest_items

        sourced: List[Dict] = []
        placeholders: List[Dict] = []
        skipped: List[Dict] = []
        files: Dict[str, str] = {}
        media: Dict[str, bytes] = {}

        for item in manifest_items:
            kind, payload = await self._resolve_one(item, allow_placeholder, docs_prefix)
            if kind == "sourced":
                sourced.append(payload)
            elif kind == "placeholder":
                placeholders.append(payload)
                if payload.get("_bytes"):
                    media[payload["path"]] = payload.pop("_bytes")
            else:
                skipped.append(payload)

        resolved = sourced + placeholders + skipped
        files[f"{docs_prefix}asset_manifest.yaml"] = _render_manifest(resolved, ticket_title)
        files[f"{docs_prefix}资产落地报告.md"] = _render_report(
            ticket_title, sourced, placeholders, skipped,
        )

        logger.info(
            "🎨 资产落地完成: %d 命中库 / %d 占位 / %d 跳过（ticket=%s）",
            len(sourced), len(placeholders), len(skipped), ticket_id[:12],
        )

        return ActionResult(
            success=True,
            data={
                "assets_total": len(resolved),
                "sourced": len(sourced),
                "placeholder": len(placeholders),
                "skipped": len(skipped),
                "sourced_assets": [
                    {k: v for k, v in a.items() if k != "_bytes"} for a in sourced[:20]
                ],
                # 二进制走 orchestrator 的 _media_files 通道（不进 JSON）
                "_media_files": media,
            },
            files=files,
            message=(
                f"资产落地：{len(sourced)} 个命中资产库，"
                f"{len(placeholders)} 个生成占位图，{len(skipped)} 个待人工处理"
            ),
        )

    # ── 清单读取 ───────────────────────────────────────────────

    async def _load_manifest(self, context: Dict[str, Any]) -> List[Dict]:
        """优先读磁盘上 ArtAgent 刚写的 asset_manifest.yaml，回退到 artifacts 表。"""
        docs_prefix = context.get("docs_prefix", "docs/")
        project_id = context.get("project_id", "")

        raw = ""
        if project_id:
            try:
                from git_manager import git_manager
                p = Path(str(git_manager._repo_path(project_id))) / docs_prefix / "asset_manifest.yaml"
                if p.is_file():
                    raw = p.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                logger.debug("读 asset_manifest.yaml 失败: %s", e)

        if not raw:
            # 回退：ArtAgent 的 artifact 里存了原始条目文本
            try:
                from database import db
                row = await db.fetch_one(
                    "SELECT content FROM artifacts WHERE ticket_id = ? AND type = 'art_design' "
                    "ORDER BY created_at DESC LIMIT 1",
                    (context.get("ticket_id", ""),),
                )
                raw = (row or {}).get("content") or ""
            except Exception as e:
                logger.debug("读 art_design artifact 失败: %s", e)

        return _parse_manifest(raw) if raw else []

    # ── 单条资产落地 ───────────────────────────────────────────

    async def _resolve_one(
        self, item: Dict, allow_placeholder: bool, docs_prefix: str,
    ) -> Tuple[str, Dict]:
        aid = item.get("id") or "asset"
        atype = (item.get("type") or "icon").lower()
        desc = item.get("description") or ""

        # 音频/字体等非图像资产：本 Action 不处理，如实标记
        if atype in _NON_IMAGE_TYPES:
            return "skipped", {
                **item, "status": "manual_required",
                "note": f"{atype} 类资产需人工提供或接入对应素材源",
            }

        # 多帧动画序列：图标/单图资产库不可能满足，别浪费一次检索去捡个错的
        needs_frames = bool(_MULTIFRAME_RE.search(desc))
        hit = None if needs_frames else await self._search_library(aid, desc, atype)
        if hit:
            return "sourced", {
                **item,
                "status": "sourced",
                "path": hit["file_path"],
                "matched_name": hit["name"],
                "asset_db_id": hit["id"],
                "match_score": hit.get("_score"),
            }

        if not allow_placeholder:
            _why = ("需多帧动画序列，资产库无法满足" if needs_frames
                    else "资产库未命中")
            return "skipped", {**item, "status": "not_found",
                               "note": f"{_why}，且 SOP 关闭了占位图降级"}

        png = _make_placeholder(aid, atype, desc)
        if png is None:
            return "skipped", {**item, "status": "not_found",
                               "note": "资产库未命中，占位图生成失败（PIL 不可用）"}

        rel = f"{docs_prefix}assets/placeholder/{_safe_name(aid)}.png"
        out = {**item, "status": "placeholder", "path": rel, "_bytes": png}
        if needs_frames:
            out["note"] = "需多帧动画序列，须由美术制作"
        return "placeholder", out

    async def _search_library(
        self, aid: str, desc: str, atype: str,
    ) -> Optional[Dict]:
        """在 art_assets 表里检索最匹配的资产，无把握则返回 None。

        不能"逐个关键词试、命中即用" —— 库里 33000 条，单个词的 LIKE 几乎
        必然命中无关资产。实测 `arrow_up` 会匹配到 `a-arrow-down`（方向相反），
        `stamina_bolt` 会因为 `bolt` 撞上任意螺栓图标。

        改为：召回候选 → 按匹配质量打分 → 低于阈值宁可不用（走占位图）。
        """
        from database import db

        id_tokens = _id_tokens(aid)
        keywords = _keywords(aid, desc)
        if not keywords:
            return None
        type_candidates = _TYPE_ALIAS.get(atype, [atype])

        # 召回：任一关键词命中即入候选池
        kw_cond = " OR ".join(["(name LIKE ? OR tags LIKE ?)"] * len(keywords))
        kw_params: List[str] = []
        for kw in keywords:
            kw_params += [f"%{kw}%", f"%{kw}%"]
        type_cond = " OR ".join(["type = ?"] * len(type_candidates))

        try:
            rows = await db.fetch_all(
                f"""SELECT id, name, type, file_path, description, tags
                    FROM art_assets
                    WHERE ({kw_cond}) AND ({type_cond})
                      AND file_path IS NOT NULL AND file_path != ''
                    ORDER BY used_count DESC
                    LIMIT 60""",
                (*kw_params, *type_candidates),
            )
        except Exception as e:
            logger.warning("检索资产库失败（id=%s）: %s", aid, e)
            return None

        if not rows:
            return None

        # 格式过滤：sprite/tileset 等必须是位图，SVG 无法作为 spritesheet 加载
        allowed_ext = _TYPE_ALLOWED_EXT.get(atype)
        if allowed_ext:
            rows = [r for r in rows if _ext_of(r["file_path"]) in allowed_ext]
            if not rows:
                logger.debug("资产 %s 召回项格式均不匹配（需 %s）", aid, sorted(allowed_ext))
                return None

        best, best_score = None, 0.0
        for r in rows:
            s = _score_candidate(dict(r), id_tokens, keywords)
            if s > best_score:
                best, best_score = dict(r), s

        if best is None or best_score < _MATCH_THRESHOLD:
            logger.debug("资产 %s 无可信匹配（最高分 %.2f < %.2f）",
                         aid, best_score, _MATCH_THRESHOLD)
            return None
        best["_score"] = round(best_score, 2)
        return best


# ── 纯函数工具 ─────────────────────────────────────────────────

# 匹配可信度阈值。低于此值视为"没找到"，走占位图而不是硬塞一个像是的资产。
# 0.6 = 至少要覆盖 id 里的主要词（实测 arrow_up vs a-arrow-down 得 0.5，被挡住）
_MATCH_THRESHOLD = 0.6

# 方向/状态类反义词 —— 命中相反语义直接判为不匹配，
# 否则「向上箭头」会拿到「向下箭头」，比没有资产更糟
_ANTONYMS = {
    "up": "down", "down": "up",
    "left": "right", "right": "left",
    "on": "off", "off": "on",
    "open": "close", "close": "open",
    "in": "out", "out": "in",
    "start": "stop", "stop": "start",
    "plus": "minus", "minus": "plus",
    "add": "remove", "remove": "add",
    "show": "hide", "hide": "show",
}


def _id_tokens(aid: str) -> List[str]:
    """id 拆词（去停用词），这些是"必须体现"的语义。"""
    return [
        p for p in re.split(r"[_\-\s]+", aid.lower())
        if len(p) > 1 and p not in _STOPWORDS
    ]


def _score_candidate(row: Dict, id_tokens: List[str], keywords: List[str]) -> float:
    """给候选资产打分（0~1）。

    评分逻辑：
      - 命中反义词 → 0（方向相反的图标比没有更糟）
      - name 恰好由 id 词组成 → 1.0（完全命中）
      - name 恰好等于某个 id 词 → 0.85（该资产"就是"这个东西）
        例：id=settings_gear，库里的 `settings` 图标就是要的东西 ——
        gear 只是同义描述词，不该因为它没出现就否掉
      - 否则按 id 词覆盖率(70%) + 其余关键词覆盖率(30%) 加权
    """
    name = (row.get("name") or "").lower()
    tags = (row.get("tags") or "").lower()
    haystack = f"{name} {tags}"

    name_tokens = {t for t in re.split(r"[^a-z0-9]+", name) if t}

    # 反义词否决：候选含某 id 词的反义词，而 id 词本身不在候选里
    for t in id_tokens:
        anto = _ANTONYMS.get(t)
        if anto and anto in name_tokens and t not in name_tokens:
            return 0.0

    if not id_tokens:
        return 0.0

    if name_tokens == set(id_tokens):
        return 1.0
    # 资产名整体就是某个 id 词（无额外修饰）→ 该资产"就是"这个东西。
    # 但必须覆盖 id 语义的一半以上，否则 4 词 id 里蹭中 1 个词也会被误判：
    # 例 zzz_nonexistent_thing_xyz 里的 `zzz` 恰好是个真实图标名。
    if (len(name_tokens) == 1
            and next(iter(name_tokens)) in id_tokens
            and len(id_tokens) <= 2):
        return 0.85

    id_hit = sum(1 for t in id_tokens if t in haystack) / len(id_tokens)

    other = [k for k in keywords if k not in id_tokens]
    other_hit = (sum(1 for k in other if k in haystack) / len(other)) if other else 0.0

    return id_hit * 0.7 + other_hit * 0.3


def _ext_of(path: str) -> str:
    """取小写扩展名（含点）。空路径返回空串。"""
    if not path:
        return ""
    i = str(path).rfind(".")
    return str(path)[i:].lower() if i >= 0 else ""


def _safe_name(s: str) -> str:
    return re.sub(r"[^0-9a-zA-Z_\-]", "_", s)[:48] or "asset"


def _keywords(aid: str, desc: str) -> List[str]:
    """从 id + 描述里抽检索词，按可信度排序（id 拆词优先于描述）。"""
    out: List[str] = []

    # snake_case / kebab-case 的 id 拆词，例：stamina_bolt → [stamina, bolt]
    parts = [p for p in re.split(r"[_\-\s]+", aid.lower()) if len(p) > 1]
    out.extend(parts)

    # 描述里的英文单词
    out.extend(w for w in re.findall(r"[a-zA-Z]{3,}", desc.lower()))

    seen, result = set(), []
    for w in out:
        if w in _STOPWORDS or w in seen:
            continue
        seen.add(w)
        result.append(w)
    return result[:6]


def _make_placeholder(aid: str, atype: str, desc: str) -> Optional[bytes]:
    """生成带标注的占位图 —— 故意做成醒目的洋红斜纹，
    避免占位图被误当成正式资产混进交付物。"""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None

    w, h = _PLACEHOLDER_SIZE.get(atype, (128, 128))
    try:
        img = Image.new("RGBA", (w, h), (255, 0, 255, 255))   # magenta = 缺失资产惯例色
        d = ImageDraw.Draw(img)
        # 斜纹，一眼可辨
        for x in range(-h, w, 16):
            d.line([(x, h), (x + h, 0)], fill=(40, 40, 40, 255), width=4)
        d.rectangle([0, 0, w - 1, h - 1], outline=(0, 0, 0, 255), width=2)
        label = aid[:14]
        try:
            d.text((4, h - 14), label, fill=(255, 255, 255, 255))
            d.text((4, 3), "PLACEHOLDER"[:max(1, w // 7)], fill=(255, 255, 255, 255))
        except Exception:
            pass
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception as e:
        logger.warning("占位图生成失败 %s: %s", aid, e)
        return None


def _parse_manifest(raw: str) -> List[Dict]:
    """解析 asset_manifest.yaml。优先 PyYAML，失败则按 `- id:` 块行解析。"""
    try:
        import yaml
        data = yaml.safe_load(raw)
        if isinstance(data, dict) and isinstance(data.get("assets"), list):
            return [a for a in data["assets"] if isinstance(a, dict) and a.get("id")]
    except Exception as e:
        logger.debug("YAML 解析 manifest 失败，转行解析: %s", e)

    items: List[Dict] = []
    cur: Optional[Dict] = None
    for line in raw.splitlines():
        s = line.strip()
        m = re.match(r"^-\s+id:\s*(.+)$", s)
        if m:
            if cur and cur.get("id"):
                items.append(cur)
            cur = {"id": m.group(1).strip()}
            continue
        if cur is not None:
            m2 = re.match(r"^(type|description|source_hint|status):\s*(.*)$", s)
            if m2:
                cur[m2.group(1)] = m2.group(2).strip()
    if cur and cur.get("id"):
        items.append(cur)
    return items


def _render_manifest(items: List[Dict], title: str) -> str:
    lines = [
        f"# asset_manifest.yaml — {title}",
        "# 由 ArtistAgent 落地更新",
        "# status: sourced=命中资产库 / placeholder=占位图待替换 / "
        "manual_required=需人工提供 / not_found=未命中",
        "assets:",
    ]
    for a in items:
        lines.append(f"  - id: {a.get('id', '')}")
        lines.append(f"    type: {a.get('type', '')}")
        if a.get("description"):
            lines.append(f"    description: {a['description']}")
        lines.append(f"    status: {a.get('status', 'pending')}")
        if a.get("path"):
            lines.append(f"    path: {a['path']}")
        if a.get("matched_name"):
            lines.append(f"    matched_name: {a['matched_name']}")
        if a.get("asset_db_id"):
            lines.append(f"    asset_db_id: {a['asset_db_id']}")
        if a.get("match_score") is not None:
            lines.append(f"    match_score: {a['match_score']}")
        if a.get("note"):
            lines.append(f"    note: {a['note']}")
    return "\n".join(lines) + "\n"


def _render_report(
    title: str, sourced: List[Dict], placeholders: List[Dict], skipped: List[Dict],
) -> str:
    total = len(sourced) + len(placeholders) + len(skipped)
    md = [
        f"# 资产落地报告 — {title}", "",
        f"共 {total} 项：命中资产库 {len(sourced)}，占位图 {len(placeholders)}，"
        f"待人工处理 {len(skipped)}", "",
    ]
    if sourced:
        md += ["## 命中资产库", "", "| id | 类型 | 匹配资产 | 匹配度 | 路径 |",
               "|---|---|---|---|---|"]
        md += [f"| {a.get('id')} | {a.get('type')} | {a.get('matched_name', '')} "
               f"| {a.get('match_score', '')} | `{a.get('path', '')}` |" for a in sourced]
        md.append("")
    if placeholders:
        md += ["## 占位图（需美术替换）", "",
               "> 洋红斜纹图，仅用于打通流程，**不可用于交付**。", "",
               "| id | 类型 | 路径 |", "|---|---|---|"]
        md += [f"| {a.get('id')} | {a.get('type')} | `{a.get('path', '')}` |"
               for a in placeholders]
        md.append("")
    if skipped:
        md += ["## 待人工处理", "", "| id | 类型 | 原因 |", "|---|---|---|"]
        md += [f"| {a.get('id')} | {a.get('type')} | {a.get('note', '')} |" for a in skipped]
        md.append("")
    return "\n".join(md)

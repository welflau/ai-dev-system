"""SearchArtAssetsAction — 搜索美术资产库（33000+ 条）"""
import logging
from typing import Any, Dict
from actions.base import ActionBase, ActionResult

logger = logging.getLogger("actions.chat.search_art_assets")


class SearchArtAssetsAction(ActionBase):

    @property
    def name(self) -> str:
        return "search_art_assets"

    @property
    def description(self) -> str:
        return "搜索美术资产库（贴图/模型/特效等，33000+ 条）"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "搜索系统美术资产库，查找可用的贴图、模型、特效等资产。\n"
                "支持按名称、类型、风格搜索，返回资产路径和基本信息。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词（资产名称/描述/标签）"},
                    "asset_type": {
                        "type": "string",
                        "description": "资产类型过滤（如 texture / mesh / effect / material 等）",
                    },
                    "style": {"type": "string", "description": "风格过滤（如 pixel / realistic 等）"},
                    "limit": {"type": "integer", "description": "返回数量，默认 10"},
                },
                "required": ["query"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        query = (context.get("query") or "").strip()
        asset_type = (context.get("asset_type") or "").strip()
        style = (context.get("style") or "").strip()
        limit = min(int(context.get("limit") or 10), 30)

        if not query:
            return ActionResult(success=False, error="query 不能为空")

        try:
            from database import db

            conditions = ["(name LIKE ? OR description LIKE ? OR tags LIKE ?)"]
            params: list = [f"%{query}%", f"%{query}%", f"%{query}%"]

            if asset_type:
                conditions.append("type LIKE ?")
                params.append(f"%{asset_type}%")
            if style:
                conditions.append("style LIKE ?")
                params.append(f"%{style}%")

            rows = await db.fetch_all(
                f"""SELECT name, description, type, style, format,
                           width, height, file_path, tags, source_url
                    FROM art_assets
                    WHERE {' AND '.join(conditions)}
                    ORDER BY used_count DESC, added_at DESC
                    LIMIT ?""",
                tuple(params) + (limit,),
            )

            if not rows:
                return ActionResult(success=True, message=f"没有找到关于「{query}」的美术资产",
                                    data={"type": "art_assets", "assets": [], "total": 0})

            lines = [f"找到 {len(rows)} 个美术资产：\n"]
            assets = []
            for r in rows:
                size = f"{r['width']}×{r['height']}" if r.get("width") and r.get("height") else ""
                type_info = " | ".join(filter(None, [r.get("type"), r.get("style"), r.get("format"), size]))
                lines.append(f"• **{r['name']}** ({type_info})")
                if r.get("description"):
                    lines.append(f"  {r['description'][:80]}")
                if r.get("file_path"):
                    lines.append(f"  路径：`{r['file_path']}`")
                assets.append({k: v for k, v in dict(r).items() if v})

            return ActionResult(success=True, message="\n".join(lines),
                                data={"type": "art_assets", "assets": assets, "total": len(assets)})
        except Exception as e:
            logger.error("search_art_assets 失败: %s", e)
            return ActionResult(success=False, error=str(e))

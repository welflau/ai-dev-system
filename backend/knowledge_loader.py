"""
KnowledgeLoader — 按 Agent 类型差异化加载知识库内容

三层知识：
  Layer 1（project）：knowledge_index，按 agent_scope 过滤，项目私有
  Layer 2（domain）：planning_knowledge / ux_knowledge / engineering_knowledge / design_knowledge
  Layer 3（spec）：G_DesignKnowledge 下的固定规范文件，始终注入
"""
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from database import db
from utils import now_iso

logger = logging.getLogger("knowledge_loader")

# 加载配置
_CONFIG: Dict = {}
_CONFIG_PATH = Path(__file__).parent / "knowledge_config.yaml"


def _load_config() -> Dict:
    global _CONFIG
    if _CONFIG_PATH.exists():
        try:
            _CONFIG = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8")) or {}
        except Exception as e:
            logger.warning("knowledge_config.yaml 加载失败: %s", e)
            _CONFIG = {}
    return _CONFIG


_load_config()


class KnowledgeLoader:
    """按 Agent 类型和项目 traits 加载对应的知识库内容"""

    def __init__(self, agent_name: str, project_id: str, traits: List[str]):
        self.agent_name = agent_name
        self.project_id = project_id
        self.traits = set(traits)
        cfg = _CONFIG.get("agents", {})
        self.sources = cfg.get(agent_name, {}).get("knowledge_sources", [])

    async def load(self) -> Dict[str, str]:
        """返回各类知识内容，key 为类型标签，value 为拼接文本"""
        result: Dict[str, str] = {}

        for source in self.sources:
            src_type = source.get("type")
            try:
                if src_type == "project":
                    content = await self._load_project(source)
                    if content:
                        result["project_knowledge"] = content

                elif src_type == "domain":
                    content = await self._load_domain(source)
                    if content:
                        existing = result.get("domain_knowledge", "")
                        result["domain_knowledge"] = (existing + "\n\n" + content).strip()

                elif src_type == "spec":
                    content = self._load_spec(source)
                    if content:
                        result["agent_spec"] = content

                elif src_type == "insight":
                    pass  # 由 orchestrator._fetch_prior_insights 单独处理

            except Exception as e:
                logger.warning("KnowledgeLoader [%s] %s 失败: %s", self.agent_name, src_type, e)

        return result

    async def _load_project(self, source: Dict) -> str:
        """从 knowledge_index 加载项目知识，按 agent_scope 过滤"""
        scope = source.get("scope")
        char_limit = source.get("char_limit", 3000)

        try:
            if scope:
                rows = await db.fetch_all(
                    """SELECT ki.filename, substr(ki.content, 1, 800) AS preview
                       FROM knowledge_index ki
                       WHERE (ki.project_id = ? OR ki.project_id IS NULL)
                         AND (ki.agent_scope IS NULL OR ki.agent_scope = 'ALL'
                              OR ki.agent_scope = ?)
                       ORDER BY ki.updated_at DESC LIMIT 8""",
                    (self.project_id, scope),
                )
            else:
                rows = await db.fetch_all(
                    """SELECT ki.filename, substr(ki.content, 1, 800) AS preview
                       FROM knowledge_index ki
                       WHERE (ki.project_id = ? OR ki.project_id IS NULL)
                       ORDER BY ki.updated_at DESC LIMIT 8""",
                    (self.project_id,),
                )
        except Exception as e:
            logger.warning("project knowledge 查询失败: %s", e)
            return ""

        if not rows:
            return ""

        parts, total = [], 0
        for r in rows:
            entry = f"### {r['filename']}\n{r['preview']}"
            if total + len(entry) > char_limit:
                break
            parts.append(entry)
            total += len(entry)

        return "\n\n".join(parts)

    async def _load_domain(self, source: Dict) -> str:
        """从领域知识表加载，支持 path_filter_by_traits 路由"""
        table = source.get("table")
        if not table:
            return ""

        char_limit = source.get("char_limit", 2000)
        result_count = source.get("result_count", 3)
        path_filter = self._resolve_path_filter(source)

        try:
            if path_filter:
                rows = await db.fetch_all(
                    f"""SELECT title, substr(content, 1, 600) AS preview
                        FROM {table}
                        WHERE filename LIKE ?
                        ORDER BY updated_at DESC LIMIT ?""",
                    (f"{path_filter}%", result_count),
                )
            else:
                rows = await db.fetch_all(
                    f"""SELECT title, substr(content, 1, 600) AS preview
                        FROM {table}
                        ORDER BY updated_at DESC LIMIT ?""",
                    (result_count,),
                )
        except Exception as e:
            logger.warning("domain knowledge [%s] 查询失败: %s", table, e)
            return ""

        if not rows:
            return ""

        parts = [f"### {r['title']}\n{r['preview']}" for r in rows]
        return "\n\n".join(parts)[:char_limit]

    def _resolve_path_filter(self, source: Dict) -> Optional[str]:
        """按项目 traits 确定领域知识的子目录过滤"""
        if "path_filter" in source:
            return source["path_filter"]

        path_map = source.get("path_filter_by_traits", {})
        if not path_map:
            return None

        for trait_combo, path in path_map.items():
            if trait_combo == "default":
                continue
            required = {t.strip() for t in trait_combo.split(",")}
            if required.issubset(self.traits):
                return path

        return path_map.get("default")

    def _load_spec(self, source: Dict) -> str:
        """加载 Agent 专属规范文件（来自 G_DesignKnowledge）"""
        from config import settings
        kb_path_str = getattr(settings, "GLOBAL_KNOWLEDGE_LOCAL_PATH", "")
        if not kb_path_str:
            return ""

        kb_path = Path(kb_path_str)
        if not kb_path.exists():
            return ""

        parts = []
        for filename in source.get("files", []):
            fpath = kb_path / filename
            if fpath.exists():
                try:
                    content = fpath.read_text(encoding="utf-8", errors="replace")
                    parts.append(f"### {fpath.name}\n{content[:1500]}")
                except Exception:
                    pass

        return "\n\n".join(parts)

"""
sync_design_knowledge.py — 从 G_DesignKnowledge/ 同步到各领域知识表

目录映射：
  planning/  → planning_knowledge
  design/ux/ → ux_knowledge
  design/art/→ design_knowledge
  engineering/ → engineering_knowledge

增量同步，不删除已有记录。
"""
import hashlib
import json
import logging
from pathlib import Path

logger = logging.getLogger("sync_design_knowledge")

_DIR_TABLE_MAP = {
    "planning":    "planning_knowledge",
    "design":      "design_knowledge",
    "engineering": "engineering_knowledge",
}

# design/ux/ 单独映射到 ux_knowledge
_UX_SUBDIR = "design/ux"


async def sync_design_knowledge(local_path: str) -> int:
    """从 G_DesignKnowledge/ 目录同步到各知识表，返回处理文件数"""
    from database import db
    from utils import now_iso

    kb_root = Path(local_path)
    if not kb_root.exists():
        logger.warning("G_DesignKnowledge 路径不存在: %s", kb_root)
        return 0

    total = 0

    for md_file in kb_root.rglob("*.md"):
        rel = md_file.relative_to(kb_root)
        parts = rel.parts  # e.g. ('planning', 'games', 'rpg', '战斗系统.md')
        if not parts:
            continue

        top_dir = parts[0]

        # 确定目标表
        if str(rel).startswith(_UX_SUBDIR + "/") or str(rel).startswith(_UX_SUBDIR.replace("/", "\\")):
            table = "ux_knowledge"
        elif top_dir in _DIR_TABLE_MAP:
            table = _DIR_TABLE_MAP[top_dir]
        else:
            continue  # 不属于已知分类，跳过

        try:
            content = md_file.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            logger.warning("读取失败 %s: %s", md_file, e)
            continue

        # 从路径推断 category/subcategory
        rel_str = str(rel).replace("\\", "/")
        category    = parts[1] if len(parts) > 2 else top_dir
        subcategory = parts[2] if len(parts) > 3 else (parts[1] if len(parts) > 1 else "")
        title = md_file.stem

        # 生成稳定 ID（基于相对路径 hash）
        asset_id = "DKB-" + hashlib.md5(rel_str.encode()).hexdigest()[:8]

        # 生成 tags（从路径和文件名）
        tag_parts = list(parts[:-1]) + [title]
        tags_json = json.dumps([t for t in tag_parts if t], ensure_ascii=False)

        # 摘要（前 200 字符）
        summary = content.replace("#", "").strip()[:200]

        try:
            await db.execute(f"""
                INSERT INTO {table}
                (id, filename, title, category, subcategory, tags, content, summary, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(filename) DO UPDATE SET
                    content=excluded.content,
                    summary=excluded.summary,
                    updated_at=excluded.updated_at
            """, (asset_id, rel_str, title, category, subcategory,
                  tags_json, content, summary, now_iso()))
            total += 1
        except Exception as e:
            logger.warning("写入 %s 失败: %s", rel_str, e)

    logger.info("G_DesignKnowledge 同步完成: %d 篇（路径: %s）", total, local_path)
    return total

"""
Failure Library — 失败案例库（跨工单反思学习）

对标 MagicAI 对比分析（docs/20260418_01_MagicAI对比分析.md）⭐⭐⭐ 第三项。
Reflexion 已实现单工单反思，这里补上**跨工单检索**：DevAgent 在新工单重试前，
检索历史相似失败 → 注入 ReflectionAction 的 prompt → 避免重复踩坑。

## 写入路径
orchestrator 写 ticket_logs(action='reflection') 后，同步调 record()
→ failure_cases 一行

## 解决标记
ticket 成功转 acceptance_passed → mark_resolved(ticket_id)
→ UPDATE resolved=1

## 检索路径
DevAgent._enrich_retry_context → search_similar(agent, module, failure_type, description)
→ 命中按 resolved DESC / confidence DESC / created_at DESC 排序，取前 N
→ ReflectionAction 渲染成「历史相似失败」段落注入 prompt

检索策略：module + agent_type + failure_type 硬过滤 + keywords LIKE 软匹配。
SQLite 的 LIKE 天然支持中文 UTF-8，无需额外处理。

详见 docs/20260420_02_失败案例库实现方案.md
"""
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("failure_library")

# --------------------------------------------------------------------------
# 停用词表（~60 项，涵盖中英文常见虚词/动词）
# --------------------------------------------------------------------------
_STOPWORDS = {
    # 中文
    "的", "了", "是", "在", "和", "与", "或", "也", "就", "都", "而", "但",
    "这", "那", "有", "没", "不", "很", "会", "要", "能", "可", "以", "为",
    "把", "给", "让", "对", "到", "从", "向", "并", "及", "其", "之", "个",
    "一个", "一些", "一下", "一种", "一样", "自己", "我们", "你们", "他们",
    "时候", "可能", "应该", "需要", "如果", "因为", "所以",
    # 英文
    "a", "an", "the", "and", "or", "but", "if", "in", "on", "at", "to", "of",
    "for", "from", "by", "with", "as", "is", "are", "was", "were", "be", "been",
    "this", "that", "these", "those", "it", "its", "we", "you", "they", "he",
    "she", "do", "does", "did", "has", "have", "had", "not", "no", "yes",
}

_CN_RE = re.compile(r"[\u4e00-\u9fff]{2,}")        # 中文 2+ 字片段
_EN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-]{2,}")  # 英文 3+ 字（含下划线连字符）


def _extract_keywords(text: str, max_keywords: int = 30) -> str:
    """从文本抽关键词，返回空格分隔的字符串（供 LIKE 检索）。
    策略：中文 2+ 字 + 英文 3+ 字，过停用词、去重、截断。"""
    if not text:
        return ""
    raw = text.lower()
    tokens: List[str] = []
    seen = set()

    # 中文片段（保留原大小写，中文无此概念）
    for m in _CN_RE.finditer(text):
        w = m.group()
        if w in _STOPWORDS or w in seen:
            continue
        seen.add(w)
        tokens.append(w)

    # 英文词
    for m in _EN_RE.finditer(raw):
        w = m.group()
        if w in _STOPWORDS or w in seen:
            continue
        seen.add(w)
        tokens.append(w)

    return " ".join(tokens[:max_keywords])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _truncate(s: str, n: int) -> str:
    if not s:
        return ""
    s = str(s)
    return s if len(s) <= n else s[:n] + "..."


class FailureLibrary:
    """失败案例库单例（模块底部导出 failure_library）"""

    async def record(
        self,
        *,
        agent_type: str,
        failure_type: str,
        reflection: Dict[str, Any],
        project_id: Optional[str] = None,
        requirement_id: Optional[str] = None,
        ticket_id: Optional[str] = None,
        module: Optional[str] = None,
        ticket_title: str = "",
        ticket_description: str = "",
    ) -> Optional[str]:
        """写一条失败案例。幂等性不保证——同一次反思调两次会写两行，
        由 orchestrator 确保只在写反思日志时调一次。
        Returns: 新写入行的 id；异常时返回 None（降级，不阻塞主流程）。"""
        from database import db

        root_cause = (reflection.get("root_cause") or "").strip()
        if not root_cause:
            logger.debug("跳过 record：reflection.root_cause 为空")
            return None

        missed = reflection.get("missed_requirements") or []
        changes = reflection.get("specific_changes") or []
        strategy = reflection.get("strategy_change") or ""
        confidence = reflection.get("confidence", 0.5)
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.5

        # 关键词：工单描述 + 根因 + 漏点
        kw_source = "\n".join([
            ticket_description or "",
            root_cause,
            " ".join(str(m) for m in missed),
        ])
        keywords = _extract_keywords(kw_source)

        case_id = str(uuid.uuid4())
        now = _now_iso()
        try:
            await db.execute(
                """INSERT INTO failure_cases (
                    id, project_id, requirement_id, ticket_id,
                    agent_type, module, failure_type,
                    ticket_title, ticket_description,
                    root_cause, missed_requirements, strategy_change, specific_changes,
                    confidence, keywords,
                    resolved, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
                (
                    case_id, project_id, requirement_id, ticket_id,
                    agent_type, module, failure_type,
                    ticket_title, ticket_description,
                    root_cause,
                    json.dumps(missed, ensure_ascii=False),
                    strategy,
                    json.dumps(changes, ensure_ascii=False),
                    confidence, keywords,
                    now, now,
                ),
            )
            logger.info(
                "📘 FailureLibrary: 收录案例 %s (agent=%s module=%s type=%s kw=%d字符)",
                case_id[:8], agent_type, module, failure_type, len(keywords),
            )
            return case_id
        except Exception as e:
            logger.warning("FailureLibrary.record 写入失败: %s", e)
            return None

    async def search_similar(
        self,
        *,
        agent_type: str,
        failure_type: str,
        ticket_description: str = "",
        module: Optional[str] = None,
        project_id: Optional[str] = None,
        current_ticket_id: Optional[str] = None,
        limit: int = 3,
    ) -> List[Dict[str, Any]]:
        """按 module + agent_type + failure_type 硬过滤 + keywords LIKE 软匹配。
        返回裁剪后的字段：root_cause / strategy_change / specific_changes /
        resolved / ticket_title / confidence。每字段最多 200 字。
        无匹配或异常 → 空列表（不阻塞主流程）。"""
        from database import db

        # 从当前工单描述抽关键词做软匹配
        query_keywords = _extract_keywords(ticket_description).split()
        if not query_keywords:
            return []
        # 控制 LIKE OR 数量，避免 SQL 超长
        query_keywords = query_keywords[:8]

        where_parts = [
            "agent_type = ?",
            "failure_type = ?",
        ]
        params: List[Any] = [agent_type, failure_type]

        if module:
            where_parts.append("module = ?")
            params.append(module)

        if project_id:
            # 项目作用域：本项目或全局（NULL）
            where_parts.append("(project_id = ? OR project_id IS NULL)")
            params.append(project_id)

        if current_ticket_id:
            where_parts.append("(ticket_id IS NULL OR ticket_id != ?)")
            params.append(current_ticket_id)

        # 至少命中一个关键词
        kw_clause = " OR ".join(["keywords LIKE ?"] * len(query_keywords))
        where_parts.append(f"({kw_clause})")
        params.extend(f"%{k}%" for k in query_keywords)

        sql = f"""
            SELECT ticket_title, root_cause, strategy_change, specific_changes,
                   resolved, confidence, module, failure_type, created_at
            FROM failure_cases
            WHERE {' AND '.join(where_parts)}
            ORDER BY resolved DESC, confidence DESC, created_at DESC
            LIMIT ?
        """
        params.append(limit)

        try:
            rows = await db.fetch_all(sql, tuple(params))
        except Exception as e:
            logger.warning("FailureLibrary.search_similar 查询失败: %s", e)
            return []

        results: List[Dict[str, Any]] = []
        for r in rows:
            try:
                changes = json.loads(r.get("specific_changes") or "[]")
            except Exception:
                changes = []
            results.append({
                "ticket_title": _truncate(r.get("ticket_title", ""), 100),
                "root_cause": _truncate(r.get("root_cause", ""), 200),
                "strategy_change": _truncate(r.get("strategy_change", ""), 200),
                "specific_changes": [_truncate(str(c), 200) for c in changes[:3]],
                "resolved": bool(r.get("resolved", 0)),
                "confidence": r.get("confidence", 0.0),
                "module": r.get("module"),
                "failure_type": r.get("failure_type"),
            })
        logger.info("🔎 FailureLibrary: 查到 %d 条相似案例 (agent=%s module=%s)",
                    len(results), agent_type, module)
        return results

    async def mark_resolved(self, ticket_id: str) -> int:
        """把某工单的所有 failure_cases 标记为已解决。
        典型场景：ticket 验收通过（acceptance_passed）。
        Returns: 受影响行数。"""
        from database import db

        if not ticket_id:
            return 0
        now = _now_iso()
        try:
            cursor = await db.execute(
                """UPDATE failure_cases
                      SET resolved = 1, resolved_at = ?, updated_at = ?
                    WHERE ticket_id = ? AND resolved = 0""",
                (now, now, ticket_id),
            )
            rows = cursor.rowcount if cursor else 0
            if rows > 0:
                logger.info("✅ FailureLibrary: ticket %s 的 %d 条案例标记为已解决",
                            ticket_id[:8], rows)
            return rows
        except Exception as e:
            logger.warning("FailureLibrary.mark_resolved 失败: %s", e)
            return 0

    async def backfill_from_ticket_logs(self) -> int:
        """一次性回灌：扫描现有 ticket_logs(action='reflection') → 写 failure_cases。
        幂等性：按 (ticket_id, root_cause) 去重。
        Returns: 新写入的行数。"""
        from database import db

        # 已存在的 (ticket_id, root_cause) 组合
        existing = await db.fetch_all(
            "SELECT ticket_id, root_cause FROM failure_cases"
        )
        existing_set = {(r["ticket_id"], r["root_cause"]) for r in existing}

        # 所有历史反思日志
        logs = await db.fetch_all(
            """SELECT tl.id AS log_id, tl.ticket_id, tl.requirement_id, tl.project_id,
                      tl.agent_type, tl.detail, tl.action, tl.created_at,
                      t.title, t.description, t.module
                 FROM ticket_logs tl
            LEFT JOIN tickets t ON t.id = tl.ticket_id
                WHERE tl.action = 'reflection'
                ORDER BY tl.created_at ASC"""
        )

        written = 0
        for log in logs:
            try:
                detail = json.loads(log["detail"]) if log["detail"] else {}
            except Exception:
                continue
            reflection = detail.get("reflection") if isinstance(detail, dict) else None
            if not isinstance(reflection, dict):
                continue
            root_cause = (reflection.get("root_cause") or "").strip()
            if not root_cause:
                continue
            key = (log["ticket_id"], root_cause)
            if key in existing_set:
                continue
            existing_set.add(key)

            # failure_type：从 action 推不出，取默认（回灌时我们只能从反思内容猜）
            # orchestrator 侧 rework→acceptance_rejected、fix_issues→testing_failed，
            # 但反思日志没区分。保守默认 acceptance_rejected（DevAgent 主要失败模式）。
            failure_type = "acceptance_rejected"

            await self.record(
                agent_type=log.get("agent_type") or "DevAgent",
                failure_type=failure_type,
                reflection=reflection,
                project_id=log.get("project_id"),
                requirement_id=log.get("requirement_id"),
                ticket_id=log.get("ticket_id"),
                module=log.get("module"),
                ticket_title=log.get("title") or "",
                ticket_description=log.get("description") or "",
            )
            written += 1

        logger.info("📦 FailureLibrary.backfill: 回灌 %d 条历史反思", written)
        return written


# 单例
failure_library = FailureLibrary()

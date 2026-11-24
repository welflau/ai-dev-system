"""Agent 执行上下文的几块原料：打回原因，历史经验，知识库文档，仓库里已有的代码。

这些函数由 `orch._build_context` 调用。`_build_context` 本身还留在 `orchestrator.py`：它在函数里
导入 L3 的 `actions.ue_editor_control`，搬进这个包会让分层守卫多出新的违规项。

约定（`orchestration` 包里按职责拆出的模块都一样）：

- 函数体从 `TicketOrchestrator` 的同名方法原样搬来，函数名去掉了前导下划线。改动只有
  `self` 写成 `orch`，以及下面单独列出的几处。
- `TicketOrchestrator` 上保留同名方法，只做转发。这里的函数互相调用、调用别的模块里的
  逻辑都走 `orch.xxx`，测试给实例打的桩才会生效。
- `db` 由转发方法在调用时传入，这里不导入它。测试用
  `monkeypatch.setattr(orchestrator, "db", test_db)` 换库，函数必须拿到同一个对象。
- 状态都放在 `orch` 上，这个模块自己不存状态。
- 函数内的延迟导入保持原样，测试的打桩打在这些源模块上。
"""
import json
import logging
from pathlib import Path
from typing import Dict

from git_manager import git_manager

logger = logging.getLogger("orchestrator")


async def inject_rejection_context(orch, db, context: Dict, ticket: Dict) -> None:
    """把「本轮被打回的真实原因」注入 context，供 ReflectionAction 使用。

    断链背景：actions/reflection.py:170-171 与 agents/dev.py:696,711,809 都读
    context["rejection_reason"] / ["test_issues"]，但此前全仓库没有任何运行时
    代码给这两个键赋值（只在 _test_reflection*.py 里手工塞过）。结果验收打回的
    真实原因（tickets.result.review.issues / reject 日志 message）进不了反思
    prompt，反思只看到空信号，下一轮重复同样的错误（TK-20261110-48b6af
    20:30:00 的 reject 里明明写着「package.json 未声明 three 依赖」，
    却因断链始终没传给 DevAgent）。

    双源提取，兼容新旧数据结构：
    - tickets.result：review.issues / issues / degrade_reason
    - 最近一条 reject 日志 detail：issues / reason / message
    仅在本轮结果确实是「被打回」类状态时注入，避免把历史成功结果带进新工单。
    """
    try:
        raw_result = ticket.get("result")
        result_obj = (json.loads(raw_result) if isinstance(raw_result, str) and raw_result
                      else (raw_result or {}))
        if not isinstance(result_obj, dict):
            result_obj = {}
        result_status = str(result_obj.get("status") or "")

        review = result_obj.get("review") or {}
        issues = [str(i) for i in (review.get("issues") or result_obj.get("issues") or []) if i]
        reason = str(result_obj.get("degrade_reason") or "")

        reject_row = await db.fetch_one(
            """SELECT detail FROM ticket_logs
                   WHERE ticket_id = ? AND action = 'reject'
                   ORDER BY created_at DESC LIMIT 1""",
            (ticket["id"],),
        )
        if reject_row and reject_row.get("detail"):
            try:
                det = json.loads(reject_row["detail"])
            except (ValueError, TypeError):
                det = {}
            if not isinstance(det, dict):
                det = {}
            if not issues:
                issues = [str(i) for i in (det.get("issues") or []) if i]
            if not reason:
                reason = str(det.get("reason") or det.get("message") or "")

        if result_status in ("acceptance_rejected", "testing_failed",
                             "development_failed", "error"):
            context["rejection_reason"] = "; ".join(issues[:10]) or reason[:500]
            context["test_issues"] = issues[:10]
        else:
            context["rejection_reason"] = ""
            context["test_issues"] = []
    except Exception as e:
        logger.debug("注入返工失败信号失败（非致命）: %s", e)
        context.setdefault("rejection_reason", "")
        context.setdefault("test_issues", [])


async def fetch_prior_insights(orch, db, ticket_title: str, project_id: str) -> str:
    """编码前主动检索相关历史经验，注入 prior_insights 供 DevAgent 参考。

    来源1：knowledge_fts（知识库文档 + dev-notes）
    来源2：tickets_fts（已完成工单的 Reflexion 根因分析）
    """
    if not ticket_title or not ticket_title.strip():
        return ""

    # FTS5 安全化：去掉特殊字符，整体用双引号包裹短语搜索
    clean = ticket_title.replace('"', ' ').strip()
    import re as _re
    fts_query = f'"{clean}"' if _re.search(r'[.\-+*():!]', clean) else clean

    parts = []

    # --- 1. 知识库命中（含置信度标注）---
    try:
        rows = await db.fetch_all("""
                SELECT ki.filename, ki.confidence, ki.used_count,
                       snippet(knowledge_fts, 0, '', '', '...', 40) AS snippet
                FROM knowledge_fts
                JOIN knowledge_index ki ON knowledge_fts.rowid = ki.id
                WHERE knowledge_fts MATCH ?
                  AND (ki.project_id = ? OR ki.project_id IS NULL)
                ORDER BY rank
                LIMIT 5
            """, (fts_query, project_id))
        if rows:
            high_conf, others = [], []
            for r in rows:
                conf = r.get("confidence") or "medium"
                label = "⭐ [高置信，建议直接应用]" if conf == "high" else ""
                line = f"- [{r['filename']}] {r['snippet']} {label}"
                if conf == "high":
                    high_conf.append(line)
                else:
                    others.append(line)
            # 高置信度排前面，自动应用
            all_lines = high_conf + others
            parts.append("## 相关知识库条目\n" + "\n".join(all_lines[:4]))
            # 更新 used_count
            for r in rows[:4]:
                await db.execute(
                    "UPDATE knowledge_index SET used_count = used_count + 1 WHERE id = ?",
                    (r["id"],)
                )
    except Exception as e:
        logger.debug("prior_insights 知识库查询失败: %s", e)

    # --- 2. 历史工单 Reflexion 根因 ---
    try:
        rows = await db.fetch_all("""
                SELECT t.title,
                       snippet(tickets_fts, 0, '', '', '...', 30) AS snippet,
                       (SELECT tl.detail FROM ticket_logs tl
                        WHERE tl.ticket_id = tf.ticket_id AND tl.action = 'reflection'
                        ORDER BY tl.created_at DESC LIMIT 1) AS reflection_detail
                FROM tickets_fts tf
                JOIN tickets t ON tf.ticket_id = t.id
                WHERE tickets_fts MATCH ?
                  AND tf.project_id = ?
                  AND t.status IN ('acceptance_passed','testing_done','deployed')
                ORDER BY rank
                LIMIT 3
            """, (fts_query, project_id))
        if rows:
            lines = []
            for r in rows:
                entry = f"- [{r['title']}] {r['snippet']}"
                if r["reflection_detail"]:
                    try:
                        rd = json.loads(r["reflection_detail"])
                        if rd.get("root_cause"):
                            entry += f"\n  曾经根因: {rd['root_cause']}"
                        if rd.get("strategy_change"):
                            entry += f"\n  修复策略: {rd['strategy_change']}"
                    except Exception:
                        pass
                lines.append(entry)
            parts.append("## 相关历史工单经验\n" + "\n".join(lines))
    except Exception as e:
        logger.debug("prior_insights 历史工单查询失败: %s", e)

    if not parts:
        return ""

    return (
        "# 历史经验（编码前参考，避免重复踩坑）\n\n"
        + "\n\n".join(parts)
    )


def load_knowledge_docs(orch, project_id: str, global_limit: int = 2000, project_limit: int = 3000) -> str:
    """读取全局知识库 + 项目知识库文档，返回拼接文本"""
    from config import BASE_DIR
    parts = []

    def _read_docs(docs_dir: Path, label: str, char_limit: int):
        if not docs_dir.exists():
            return
        files = sorted(docs_dir.glob("*.md"), key=lambda f: f.name)
        total = 0
        section_parts = []
        for f in files:
            if total >= char_limit:
                break
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
                remaining = char_limit - total
                if len(text) > remaining:
                    text = text[:remaining] + "\n...(truncated)"
                section_parts.append(f"### {f.name}\n{text}")
                total += len(text)
            except Exception:
                pass
        if section_parts:
            parts.append(f"## {label}\n" + "\n\n".join(section_parts))

    _read_docs(BASE_DIR / "docs", "全局规范", global_limit)
    _read_docs(BASE_DIR / "projects" / project_id / "docs", "项目文档", project_limit)

    return "\n\n".join(parts)


async def collect_existing_code(orch, project_id: str) -> Dict:
    """收集仓库中已有的代码文件（用于增量开发上下文）"""
    if not git_manager.repo_exists(project_id):
        return {"file_list": [], "code": {}}

    tree = await git_manager.get_file_tree(project_id)
    children = tree.get("children", [])

    # 扁平化文件列表
    file_list = []
    def _flatten(nodes, prefix=""):
        for n in nodes:
            path = f"{prefix}{n['name']}" if not prefix else f"{prefix}/{n['name']}"
            if n["type"] == "file":
                file_list.append(path)
            elif n.get("children"):
                _flatten(n["children"], path)
    _flatten(children)

    # 读取关键文件内容（入口/配置文件 + src/ 与 scripts/ 下的代码文件）
    code = {}
    ENTRY_FILES = {"index.html", "main.py", "app.py", "package.json", "tsconfig.json", "vite.config.ts", "vite.config.js"}
    CODE_EXTS = {".html", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".py", ".css", ".json"}
    total_chars = 0
    MAX_TOTAL = 15000
    MAX_PER_FILE = 3000

    for fp in file_list:
        if total_chars >= MAX_TOTAL:
            break
        fname = fp.split("/")[-1]
        _, ext = (fname.rsplit(".", 1) if "." in fname else (fname, ""))
        ext = f".{ext}" if ext else ""

        # 优先读入口/配置文件，其次 src/ 或 scripts/ 下的代码文件
        should_read = fname in ENTRY_FILES or (fp.startswith(("src/", "scripts/")) and ext in CODE_EXTS)
        if not should_read:
            continue

        content = await git_manager.get_file_content(project_id, fp)
        if content:
            truncated = content[:MAX_PER_FILE]
            if len(content) > MAX_PER_FILE:
                truncated += f"\n... (truncated, total {len(content)} chars)"
            code[fp] = truncated
            total_chars += len(truncated)

    return {"file_list": file_list, "code": code}


def agent_to_owner(orch, agent_name: str) -> str:
    """Agent 名称转持有者角色"""
    mapping = {
        "ProductAgent": "product",
        "ArchitectAgent": "architect",
        "DevAgent": "developer",
        "TestAgent": "tester",
        "ReviewAgent": "reviewer",
        "DeployAgent": "deployer",
    }
    return mapping.get(agent_name, "unknown")

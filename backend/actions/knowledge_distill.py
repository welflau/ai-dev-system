"""
KnowledgeDistillAction — 工单完成后自动蒸馏知识到项目知识库

触发条件：工单验收通过（acceptance_passed）且有过失败-修复循环（reject/error/reflection >= 1）
原则（借鉴 Hermes CLASS-FIRST）：
  - 识别通用错误类型，不记录单次具体实例
  - 优先追加（append）已有文档，不随意新建
  - 无通用价值则跳过（skip=true）

存储目录：project_docs_dir / 已知问题/ 或 FAQ/ 或 规范/
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict

from actions.base import ActionBase, ActionResult
from database import db
from utils import now_iso

logger = logging.getLogger("action.knowledge_distill")

# 允许写入的子目录（安全限制）
_ALLOWED_SUBDIRS = {"已知问题", "FAQ", "规范"}
_MAX_CONTENT_CHARS = 600
_MAX_EVENTS = 15


def _format_events(logs: list) -> str:
    """将 ticket_logs 格式化为 LLM 可读的事件摘要"""
    lines = []
    for log in logs:
        action = log.get("action", "?")
        msg = log.get("message", "")
        detail_raw = log.get("detail_data") or log.get("detail") or ""
        detail: dict = {}
        if detail_raw:
            try:
                detail = json.loads(detail_raw) if isinstance(detail_raw, str) else detail_raw
            except Exception:
                pass

        if action == "reflection":
            ref = detail.get("reflection", {})
            root_cause = ref.get("root_cause", "")
            strategy = ref.get("strategy_change", "")
            line = f"[反思] 根因：{root_cause}"
            if strategy:
                line += f"；策略：{strategy}"
        elif action in ("reject", "error"):
            errors = detail.get("errors") or detail.get("compile_errors") or []
            issues = detail.get("issues") or detail.get("ue_blocking_issues") or []
            combined = errors + issues
            excerpt = "；".join(str(e)[:80] for e in combined[:3]) if combined else msg[:120]
            line = f"[失败/{action}] {excerpt}"
        elif action == "accept":
            line = f"[验收通过] {msg[:80]}"
        elif action == "complete":
            line = f"[测试通过] {msg[:80]}"
        else:
            continue  # 跳过其他 action
        lines.append(line)

    return "\n".join(lines) if lines else "（无关键事件）"


class KnowledgeDistillAction(ActionBase):

    @property
    def name(self) -> str:
        return "knowledge_distill"

    @property
    def description(self) -> str:
        return "工单完成后蒸馏知识到项目知识库"

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        ticket_id = context.get("ticket_id", "")
        project_id = context.get("project_id", "")

        if not ticket_id or not project_id:
            return ActionResult(status="fail", data={"error": "ticket_id / project_id 不能为空"})

        # 读工单基本信息
        ticket = await db.fetch_one(
            "SELECT title, type, module FROM tickets WHERE id = ?", (ticket_id,)
        )
        if not ticket:
            return ActionResult(status="fail", data={"error": f"工单 {ticket_id} 不存在"})

        # 读关键事件日志（最近 _MAX_EVENTS 条，过滤有价值的 action）
        logs = await db.fetch_all("""
            SELECT action, message, detail as detail_data, created_at
            FROM ticket_logs
            WHERE ticket_id = ?
              AND action IN ('reject', 'error', 'reflection', 'accept', 'complete')
            ORDER BY created_at DESC
            LIMIT ?
        """, (ticket_id, _MAX_EVENTS))

        if not logs:
            return ActionResult(status="success", data={"skipped": True, "reason": "无关键事件日志"})

        events_text = _format_events(list(logs))

        ticket_type = ticket.get("type") or "unknown"
        ticket_module = ticket.get("module") or "unknown"

        # 读现有知识库文件列表（给 LLM 参考，优先追加已有文件）
        from api.knowledge import _get_docs_dir
        docs_dir = _get_docs_dir(project_id)
        existing_files = [f.name for f in docs_dir.rglob("*.md")]
        existing_hint = "现有文档：" + "、".join(existing_files[:10]) if existing_files else "（无已有文档）"

        system_prompt = (
            "你是一个知识管理助手，负责将工单修复经验沉淀到项目知识库。\n"
            "原则：\n"
            "1. CLASS-FIRST：记录通用错误类型，不记录'工单T-042第22行'这种具体实例\n"
            "2. 只有'下次遇到同类问题能直接参考'的内容才值得记录\n"
            "3. 优先追加（action=append）到已有文档，不随意新建\n"
            "4. 无通用价值则 skip=true\n"
            "5. content 必须简洁，不超过 600 字\n"
            "返回纯 JSON，不加任何解释。"
        )

        user_prompt = (
            f"工单：{ticket['title']} ({ticket_type}/{ticket_module})\n\n"
            f"关键事件（最近{len(logs)}条）：\n{events_text}\n\n"
            f"{existing_hint}\n\n"
            "请判断并返回：\n"
            '{"skip": true/false, '
            '"filename": "已知问题/XXX.md", '
            '"section_title": "## 章节标题", '
            '"content": "**症状**：...\\n**根因**：...\\n**修复**：...", '
            '"action": "append" 或 "create"}'
        )

        from llm_client import llm_client
        result = await llm_client.chat_json(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=1000,
        )

        if not result or not isinstance(result, dict):
            return ActionResult(status="fail", data={"error": "LLM 返回无效"})

        if result.get("skip"):
            logger.info("[知识蒸馏] 工单 %s 无通用价值，跳过", ticket_id)
            return ActionResult(status="success", data={"skipped": True})

        # 安全校验：filename 只能在允许的子目录下
        filename = (result.get("filename") or "").strip().lstrip("/")
        if not filename:
            return ActionResult(status="fail", data={"error": "filename 为空"})

        # 确保 filename 在允许的子目录
        parts = filename.replace("\\", "/").split("/")
        if len(parts) < 2 or parts[0] not in _ALLOWED_SUBDIRS:
            filename = f"已知问题/{filename.split('/')[-1]}"

        if not filename.endswith(".md"):
            filename += ".md"

        section_title = (result.get("section_title") or "").strip()
        content = (result.get("content") or "").strip()[:_MAX_CONTENT_CHARS]
        distill_action = result.get("action", "append")

        if not content:
            return ActionResult(status="fail", data={"error": "content 为空"})

        # 写入文件
        dest = docs_dir / filename
        dest.parent.mkdir(parents=True, exist_ok=True)

        new_block = f"\n\n{section_title}\n\n{content}" if section_title else f"\n\n{content}"

        if distill_action == "append" and dest.exists():
            existing_content = dest.read_text(encoding="utf-8", errors="replace")
            full_content = existing_content + new_block
        else:
            header = f"# {Path(filename).stem}\n\n> 由知识蒸馏自动生成，基于工单历史\n"
            full_content = header + new_block

        dest.write_text(full_content, encoding="utf-8")

        # 更新 FTS5 knowledge_index
        from api.knowledge import _upsert_knowledge_index
        await _upsert_knowledge_index(project_id, dest.name, full_content)

        logger.info("[知识蒸馏] 工单 %s → %s (%s)", ticket_id, filename, distill_action)
        return ActionResult(status="success", data={
            "skipped": False,
            "filename": filename,
            "action": distill_action,
            "ticket_id": ticket_id,
        })

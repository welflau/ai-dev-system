"""
change_impact.py — 评论变更影响分析器

用户在工单评论区提交评论时，轻量 LLM 调用分析是否包含需求变更，
返回变更类型和影响范围，供 Orchestrator 决定是否触发阶段重置。
"""
import json
import logging
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger("change_impact")

# 不触发变更分析的状态（黑名单）。
#
# 原先用白名单 ACTIVE_PHASES = {"development", "testing", "in_review", "verify", ...}，
# 但这些字符串**不是** TicketStatus 的真实取值 —— 真实值是 development_in_progress /
# testing_in_progress / testing_failed / review_in_progress …，所以测试、审查、验收
# 阶段的评论永远命中不到分析器，只能得到一段 LLM 客套回复。
# 而 fragments（engine_compile / play_test / smoke_test / ue_content_gen …）还会动态
# 派生更多状态，白名单注定追不上。改为黑名单：除下列状态外一律参与分析。
INACTIVE_PHASES = frozenset({
    # 尚未启动：改工单描述即可，重置阶段无意义
    "pending", "todo",
    # 需人工介入 / 已由人工接管
    "blocked", "cancelled",
    # 已收尾（对齐 orchestrator._HARD_TERMINAL）
    "testing_done", "deployed", "done", "completed",
})


def is_active_phase(status: Optional[str]) -> bool:
    """该状态的工单是否参与评论变更分析。"""
    return bool(status) and status.strip() not in INACTIVE_PHASES


@dataclass
class ChangeImpact:
    type: str = "none"           # none / tweak / partial / breaking
    reason: str = ""             # 变更原因说明
    affected_specs: List[str] = field(default_factory=list)  # partial 时受影响的 spec 场景
    raw: str = ""                # LLM 原始输出（调试用）

    @property
    def is_change(self) -> bool:
        return self.type in ("tweak", "partial", "breaking")

    @classmethod
    def none(cls) -> "ChangeImpact":
        return cls(type="none", reason="无需求变更")

    @classmethod
    def parse(cls, raw_text: str) -> "ChangeImpact":
        """解析 LLM 返回的 JSON，容错处理"""
        try:
            # 提取 JSON 块
            text = raw_text.strip()
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                text = text[start:end]
            data = json.loads(text)
            return cls(
                type=data.get("type", "none"),
                reason=data.get("reason", ""),
                affected_specs=data.get("affected_specs", []),
                raw=raw_text,
            )
        except Exception:
            logger.debug("ChangeImpact.parse 失败，原始输出: %s", raw_text[:200])
            return cls.none()


class ChangeImpactAnalyzer:
    """
    分析工单评论是否包含需求变更。

    轻量调用（非 ReAct，直接 chat），~1-2s 响应。
    无 specs 文件时直接返回 none（不分析纯代码修改评论）。
    """

    async def analyze(
        self,
        comment: str,
        ticket_title: str,
        ticket_status: str,
        specs_content: Optional[str] = None,
    ) -> ChangeImpact:
        """
        分析评论是否包含需求变更。

        Args:
            comment: 用户评论内容
            ticket_title: 工单标题
            ticket_status: 工单当前状态
            specs_content: OpenSpec specs.md 内容（可选）

        Returns:
            ChangeImpact，type 为 none/tweak/partial/breaking
        """
        # 未启动 / 终态 / 待人工的工单不分析
        if not is_active_phase(ticket_status):
            return ChangeImpact.none()

        # 过短评论（≤10字）大概率不是需求变更
        if len(comment.strip()) <= 10:
            return ChangeImpact.none()

        specs_block = ""
        if specs_content:
            specs_block = f"""
## 当前验收规范（OpenSpec specs）
{specs_content[:1500]}
---
"""

        prompt = f"""分析以下工单评论是否包含需求变更。

## 工单
标题：{ticket_title}
状态：{ticket_status}
{specs_block}
## 用户评论
{comment}

## 判断规则
- **none**：无需求变更（进度询问、鼓励、报告问题、要求调试已有功能）
- **tweak**：只影响实现细节，验收标准不变（如改文件名、换颜色、调参数）
- **partial**：需要新增或修改 1-2 个验收场景（如新增功能点、修改某个行为）
- **breaking**：需求根本性改变，原有大部分验收标准失效

只输出 JSON，不要解释：
{{"type": "none|tweak|partial|breaking", "reason": "一句话说明", "affected_specs": ["场景描述（partial时填写）"]}}"""

        try:
            from llm_client import llm_client
            raw = await llm_client.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=300,
            )
            impact = ChangeImpact.parse(raw)
            logger.info(
                "变更分析 ticket=%s type=%s reason=%s",
                ticket_title[:20], impact.type, impact.reason[:50],
            )
            return impact
        except Exception as e:
            logger.warning("ChangeImpactAnalyzer 失败（返回 none）: %s", e)
            return ChangeImpact.none()


# 全局单例
change_analyzer = ChangeImpactAnalyzer()

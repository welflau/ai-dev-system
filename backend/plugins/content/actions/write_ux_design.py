"""
WriteUXDesignAction — UX Agent 的核心 Action

产出：
- 交互流程图（Mermaid，页面间跳转关系）
- 组件线框说明（布局层级、关键组件清单）
- 交互状态定义（正常/hover/active/disabled/loading/empty/error）
- 响应式/适配规则
- 初版资产清单（UI 层）→ 写入 asset_manifest.yaml 初稿

适用范围：web / wechat / mobile / desktop / category:game（凡有界面的项目）
"""
import json
import logging
from typing import Any, Dict

from actions.base import ActionBase, ActionResult
from actions.action_node import ActionNode
from pydantic import BaseModel

logger = logging.getLogger("action.write_ux_design")


class UXDesignOutput(BaseModel):
    interaction_flow: str = ""     # Mermaid 流程图（页面跳转关系）
    component_wireframe: str = ""  # 组件线框说明（布局/层级/清单）
    interaction_states: str = ""   # 每个交互组件的状态定义
    responsive_rules: str = ""     # 响应式/适配规则
    ui_asset_list: str = ""        # UI 层资产清单（图标名/插画描述/图片说明）


class WriteUXDesignAction(ActionBase):

    @property
    def name(self) -> str:
        return "write_ux_design"

    @property
    def description(self) -> str:
        return "产出 UX 交互设计文档（流程图/线框/状态定义/资产清单初稿）"

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        from llm_client import llm_client

        ticket_title = context.get("ticket_title", "")
        ticket_desc  = context.get("ticket_description", "")
        req_title    = context.get("requirement_title", "")
        docs_prefix  = context.get("docs_prefix", "docs/")
        traits       = context.get("traits", [])

        # 读取 PRD（上一阶段 PlannerAgent 产出）
        prd_content = ""
        try:
            from database import db
            project_id = context.get("project_id", "")
            ticket_id  = context.get("ticket_id", "")
            art = await db.fetch_one(
                "SELECT content FROM artifacts WHERE ticket_id = ? AND type = 'prd' LIMIT 1",
                (ticket_id,),
            )
            if art:
                prd_content = art["content"] or ""
        except Exception:
            pass

        # 领域知识注入
        domain_kb  = context.get("domain_knowledge", "")
        agent_spec = context.get("agent_spec", "")
        knowledge_section = ""
        if domain_kb:
            knowledge_section += f"\n## 交互设计参考\n{domain_kb}\n"
        if agent_spec:
            knowledge_section += f"\n## UX 规范\n{agent_spec}\n"

        # 判断平台类型，调整提示
        is_game    = "category:game" in traits
        is_wechat  = "platform:wechat" in traits
        is_mobile  = "platform:mobile" in traits
        platform_hint = ""
        if is_game:
            platform_hint = "这是游戏项目 UI，需要考虑游戏风格的交互（HUD/面板/弹窗动效）。"
        elif is_wechat:
            platform_hint = "这是微信小程序，遵循微信设计规范，使用 rpx 单位，注意授权弹窗等微信特有交互。"
        elif is_mobile:
            platform_hint = "这是移动端应用，注意 iOS/Android 平台差异和手势操作。"

        req_context = f"""## 需求背景
{req_title}

## 当前工单
标题：{ticket_title}
描述：{ticket_desc or '（无详细描述）'}

## PRD（策划产出）
{prd_content[:2000] if prd_content else '（暂无 PRD，请基于工单描述推断）'}

## 平台说明
{platform_hint or '通用 Web 项目'}
{knowledge_section}
## UX 设计要求

**交互流程图**：用 Mermaid flowchart/stateDiagram 描述页面跳转，每个节点是一个页面或弹窗。

**组件线框说明**：列出主要区域和组件（不需要视觉样式，只需结构）。

**交互状态**：对每个可交互组件，列出所有状态：
  正常 / hover / active / disabled / loading / empty（无数据）/ error

**响应式规则**：{'小程序用 rpx，flex 布局，无需断点' if is_wechat else '移动端优先，断点 768px / 1024px' if is_mobile else '断点：mobile < 768px / tablet 768-1024px / desktop > 1024px'}

**UI 资产清单**：列出需要的图标（用途+风格）、插画（描述）、图片（尺寸+用途）。
格式：
- icon: home（导航首页，24px，outline 风格）
- illustration: empty-state（列表为空时显示，400x300）
- image: banner（首页顶部横幅，750x300）"""

        node = ActionNode(
            key="write_ux_design",
            expected_type=UXDesignOutput,
            instruction="[MODE: DESIGN] 你是专职 UX 设计师，只关注交互逻辑和组件结构，不关心视觉样式（颜色/字号等）。",
        )

        await node.fill(req=req_context, llm=llm_client, max_tokens=4000)
        output = node.instruct_content

        if not output or not output.component_wireframe:
            logger.warning("WriteUXDesignAction 输出不完整，使用降级文档")
            output = UXDesignOutput(
                interaction_flow="graph LR\n    A[主页面] --> B[功能页]\n    B --> C[结果页]",
                component_wireframe=f"## {ticket_title}\n- 主内容区\n- 操作区（按钮/表单）\n- 反馈区（Toast/弹窗）",
                interaction_states="- 按钮：正常 / hover / loading / disabled\n- 列表：正常 / 加载中 / 空状态 / 错误",
                responsive_rules="移动端优先，flex 布局",
                ui_asset_list="- icon: 待补充\n- illustration: 空状态图（400x300）",
            )

        # 构建 UX 设计文档
        ux_md = f"""# UX 设计 — {ticket_title}

> 所属需求：{req_title}

## 交互流程图

```mermaid
{output.interaction_flow}
```

## 组件线框说明

{output.component_wireframe}

## 交互状态定义

{output.interaction_states}

## 响应式/适配规则

{output.responsive_rules}

## UI 资产清单（初稿）

{output.ui_asset_list}
"""

        # 生成 asset_manifest.yaml 初稿（UI 层）
        asset_manifest = _build_asset_manifest_from_ux(output.ui_asset_list, ticket_title)

        logger.info("✅ WriteUXDesignAction 完成: %s", ticket_title[:30])

        return ActionResult(
            success=True,
            data={
                "ux_content": ux_md,
                "ui_asset_list": output.ui_asset_list,
                "component_wireframe": output.component_wireframe,
            },
            files={
                f"{docs_prefix}UX设计.md": ux_md,
                f"{docs_prefix}asset_manifest.yaml": asset_manifest,
            },
            message=f"UX 设计已完成：{ticket_title}",
        )


def _build_asset_manifest_from_ux(ui_asset_list: str, ticket_title: str) -> str:
    """从 UX 的资产清单文字，生成结构化 asset_manifest.yaml 初稿"""
    lines = [
        f"# asset_manifest.yaml — {ticket_title}",
        "# 由 UX Agent 自动生成初稿，美术 Agent 会补全和确认",
        "assets:",
    ]
    if not ui_asset_list:
        lines.append("  # 暂无资产需求")
        return "\n".join(lines)

    idx = 0
    for line in ui_asset_list.split("\n"):
        line = line.strip().lstrip("- •*")
        if not line:
            continue
        asset_type = "icon"
        if line.lower().startswith("illustration"):
            asset_type = "illustration"
        elif line.lower().startswith("image") or line.lower().startswith("photo"):
            asset_type = "photo"
        idx += 1
        lines.append(f"  - id: asset_{idx:03d}")
        lines.append(f"    type: {asset_type}")
        lines.append(f"    description: {line[:100]}")
        lines.append(f"    status: pending  # 待美术Agent确认来源和规格")

    return "\n".join(lines)

"""
WriteArtDesignAction — 美术 Agent 的核心 Action

读取 PRD + UX 设计，产出：
  1. Design Token（颜色/字体/间距/圆角 JSON）
  2. 组件视觉规范（Markdown，每个组件的视觉样式说明）
  3. 完整 asset_manifest.yaml（汇总所有类型资产，供技美并行使用）

游戏项目额外产出：
  - 精灵图规格说明
  - UI Atlas 方案

写入：
  docs/Reqs/{id}/视觉规范.md
  docs/Reqs/{id}/asset_manifest.yaml（完整版，覆盖 UX 初稿）
  docs/Reqs/{id}/design_tokens.json
"""
import json
import logging
from typing import Any, Dict

from actions.base import ActionBase, ActionResult
from actions.action_node import ActionNode
from pydantic import BaseModel

logger = logging.getLogger("action.write_art_design")


class ArtDesignOutput(BaseModel):
    design_tokens: str = ""        # JSON 格式的 Design Token
    component_visual_spec: str = "" # 各组件视觉规范（Markdown）
    asset_manifest_items: str = "" # 完整资产清单（YAML 条目文字格式）
    style_guidelines: str = ""     # 整体视觉风格说明
    game_sprite_spec: str = ""     # 精灵图规格（游戏项目）


class WriteArtDesignAction(ActionBase):

    @property
    def name(self) -> str:
        return "write_art_design"

    @property
    def description(self) -> str:
        return "产出 Design Token / 组件视觉规范 / 完整资产清单"

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        from llm_client import llm_client

        ticket_title = context.get("ticket_title", "")
        req_title    = context.get("requirement_title", "")
        docs_prefix  = context.get("docs_prefix", "docs/")
        traits       = context.get("traits", [])
        project_id   = context.get("project_id", "")
        ticket_id    = context.get("ticket_id", "")

        is_game   = "category:game" in traits
        is_wechat = "platform:wechat" in traits

        # 读取上游产出（PRD + UX 设计）
        prd_content  = ""
        ux_content   = ""
        ux_asset_list = ""
        try:
            from database import db
            rows = await db.fetch_all(
                "SELECT type, content FROM artifacts WHERE ticket_id = ? AND type IN ('prd','ux_design')",
                (ticket_id,),
            )
            for r in rows:
                if r["type"] == "prd":
                    prd_content = (r["content"] or "")[:1500]
                elif r["type"] == "ux_design":
                    ux_content = (r["content"] or "")[:2000]
                    # 提取 UI 资产清单部分
                    if "## UI 资产清单" in ux_content:
                        ux_asset_list = ux_content.split("## UI 资产清单")[-1][:500]
        except Exception:
            pass

        # 领域知识注入
        domain_kb  = context.get("domain_knowledge", "")
        agent_spec = context.get("agent_spec", "")
        knowledge_section = ""
        if domain_kb:
            knowledge_section += f"\n## 视觉设计参考\n{domain_kb[:1000]}\n"
        if agent_spec:
            knowledge_section += f"\n## 美术规范\n{agent_spec[:500]}\n"

        platform_hint = ""
        if is_game:
            platform_hint = "游戏 UI：扁平化/像素风/科幻风等根据游戏类型决定，注意 HUD 信息密度。"
        elif is_wechat:
            platform_hint = "微信小程序：遵循微信设计语言，主色推荐 #07C160（微信绿）或品牌色。"
        else:
            platform_hint = "Web 应用：现代扁平化风格，深色/浅色主题。"

        req_context = f"""## 任务
为工单「{ticket_title}」产出视觉设计规范和资产清单。

## PRD 摘要
{prd_content or '（无 PRD，基于工单描述推断）'}

## UX 设计摘要
{ux_content[:1000] if ux_content else '（无 UX 设计，基于工单描述推断）'}

## UX 识别的 UI 资产
{ux_asset_list or '（无 UX 资产清单）'}

## 平台风格
{platform_hint}
{knowledge_section}
## 产出要求

**design_tokens**：JSON 格式，包含 colors/typography/spacing/radius/shadow。
示例：
{{
  "colors": {{"primary": "#4F46E5", "bg": "#F9FAFB", "text": "#111827"}},
  "typography": {{"base": "14px", "sm": "12px", "lg": "16px", "heading": "20px"}},
  "spacing": {{"xs": "4px", "sm": "8px", "md": "16px", "lg": "24px"}},
  "radius": {{"sm": "4px", "md": "8px", "lg": "12px"}}
}}

**component_visual_spec**：Markdown，列出每个主要组件的视觉规格（背景色/边框/字体/状态颜色）。

**asset_manifest_items**：列出所有需要的资产，格式：
type: icon | id: nav_home | desc: 首页导航图标 24px outline | source: iconify
type: illustration | id: empty_state | desc: 空状态插画 400x300 | source: ai_generate
type: photo | id: hero_bg | desc: 首页背景图 1920x600 | source: pexels
type: audio | id: btn_click | desc: 按钮点击音效 | source: kenney
（仅游戏项目需要音频）

**style_guidelines**：2-3 句整体视觉风格说明。
{'**game_sprite_spec**：列出需要的精灵图（尺寸/帧数/动画）。' if is_game else ''}"""

        node = ActionNode(
            key="write_art_design",
            expected_type=ArtDesignOutput,
            instruction="[MODE: DESIGN] 你是专职视觉设计师，产出可直接供开发使用的设计规范。不写代码实现，只写视觉规格。",
        )

        await node.fill(req=req_context, llm=llm_client, max_tokens=4000)
        output = node.instruct_content

        if not output or not output.design_tokens:
            logger.warning("WriteArtDesignAction 输出不完整，使用降级规范")
            output = ArtDesignOutput(
                design_tokens='{"colors":{"primary":"#4F46E5","bg":"#F9FAFB","text":"#111827"},"typography":{"base":"14px"},"spacing":{"md":"16px"},"radius":{"md":"8px"}}',
                component_visual_spec=f"## {ticket_title}\n- 主按钮：primary 色背景，白色文字，8px 圆角\n- 卡片：白色背景，1px border，8px 圆角",
                asset_manifest_items="type: icon | id: placeholder | desc: 待补充 | source: iconify",
                style_guidelines="现代简洁风格，以蓝紫色为主色调。",
            )

        # 构建视觉规范文档
        tokens_json = output.design_tokens.strip()
        visual_md = f"""# 视觉规范 — {ticket_title}

> 所属需求：{req_title}

## 整体风格
{output.style_guidelines}

## Design Token

```json
{tokens_json}
```

## 组件视觉规范

{output.component_visual_spec}
{'## 精灵图规格\n' + output.game_sprite_spec if is_game and output.game_sprite_spec else ''}
"""

        # 构建完整 asset_manifest.yaml
        asset_manifest = _build_complete_manifest(output.asset_manifest_items, ticket_title)

        # 保存 design_tokens.json
        try:
            tokens_dict = json.loads(tokens_json)
        except Exception:
            tokens_dict = {"_raw": tokens_json}

        logger.info("✅ WriteArtDesignAction 完成: %s", ticket_title[:30])

        return ActionResult(
            success=True,
            data={
                "art_content": visual_md,
                "design_tokens": tokens_dict,
                "asset_manifest_raw": output.asset_manifest_items,
            },
            files={
                f"{docs_prefix}视觉规范.md": visual_md,
                f"{docs_prefix}asset_manifest.yaml": asset_manifest,
                f"{docs_prefix}design_tokens.json": json.dumps(tokens_dict, ensure_ascii=False, indent=2),
            },
            message=f"视觉规范已完成：{ticket_title}",
        )


def _build_complete_manifest(items_text: str, ticket_title: str) -> str:
    """将文字格式的资产清单转换为结构化 YAML"""
    lines = [
        f"# asset_manifest.yaml — {ticket_title}",
        "# 由美术 Agent 完整生成，覆盖 UX Agent 的初稿",
        "# status: pending=待生产 / sourced=已从资产库获取 / generated=已AI生成",
        "assets:",
    ]

    if not items_text or items_text.strip() == "（无 UX 资产清单）":
        lines.append("  # 暂无资产需求")
        return "\n".join(lines)

    idx = 0
    for line in items_text.split("\n"):
        line = line.strip().lstrip("-•* ")
        if not line or "type:" not in line:
            continue

        # 解析 "type: icon | id: nav_home | desc: ... | source: iconify" 格式
        parts = {p.split(":", 1)[0].strip(): p.split(":", 1)[1].strip()
                 for p in line.split("|") if ":" in p}
        idx += 1
        asset_id = parts.get("id", f"asset_{idx:03d}")
        asset_type = parts.get("type", "icon")
        desc = parts.get("desc", line[:80])
        source = parts.get("source", "iconify" if asset_type == "icon" else "ai_generate")

        lines.append(f"  - id: {asset_id}")
        lines.append(f"    type: {asset_type}")
        lines.append(f"    description: {desc}")
        lines.append(f"    source_hint: {source}")
        lines.append(f"    status: pending")

    return "\n".join(lines)

"""
WriteHtmlPrototypeAction — 先用 HTML 验证核心玩法循环

在进引擎开发之前，DevAgent 先生成一个完整的单文件 HTML 原型，
用浏览器验证核心机制是否可行，1-2天暴露问题，避免在引擎里走错方向。

适用场景：
  - 游戏项目（需要验证核心玩法循环）
  - 复杂 UI 功能（先验证交互逻辑）

输出：
  - index.html（完整可运行，纯前端，不依赖服务器）
  - 注意事项.md（已验证的核心逻辑 + 引擎实现要点）
"""
import logging
from typing import Any, Dict

from actions.base import ActionBase, ActionResult
from actions.action_node import ActionNode
from pydantic import BaseModel

logger = logging.getLogger("action.write_html_prototype")


class HtmlPrototypeOutput(BaseModel):
    html_content: str = ""         # 完整 HTML 内容
    core_mechanics: str = ""       # 核心机制说明
    engine_notes: str = ""         # 引擎实现要点（给后续 ArchitectAgent 参考）
    known_limitations: str = ""    # 原型的已知限制（不影响验收）


class WriteHtmlPrototypeAction(ActionBase):

    @property
    def name(self) -> str:
        return "write_html_prototype"

    @property
    def description(self) -> str:
        return "生成 HTML 单文件原型，验证核心玩法/交互循环，低成本暴露设计问题"

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        from llm_client import llm_client

        ticket_title = context.get("ticket_title", "")
        ticket_desc  = context.get("ticket_description", "")
        req_title    = context.get("requirement_title", "")
        docs_prefix  = context.get("docs_prefix", "docs/")
        traits       = context.get("traits", [])

        # 读取 PRD（PlannerAgent 产出）
        prd_content = ""
        try:
            from database import db
            ticket_id = context.get("ticket_id", "")
            art = await db.fetch_one(
                "SELECT content FROM artifacts WHERE ticket_id = ? AND type = 'prd' LIMIT 1",
                (ticket_id,),
            )
            if art:
                prd_content = (art["content"] or "")[:2000]
        except Exception:
            pass

        is_game = "category:game" in traits
        platform_hint = "游戏项目，用 Canvas 2D 或纯 HTML/CSS 实现核心玩法循环。" if is_game else \
                        "Web/App 项目，用纯 HTML+CSS+JS 实现核心交互流程。"

        req_context = f"""## 任务：生成 HTML 原型

**工单**：{ticket_title}
**需求**：{req_title}
**描述**：{ticket_desc or '（基于 PRD 推断）'}
**平台**：{platform_hint}

## PRD 摘要
{prd_content or '（无 PRD，基于工单描述实现）'}

## HTML 原型要求

1. **单文件原型**：所有代码在一个 `index.html` 里，不依赖外部 CDN 或服务器
2. **核心循环优先**：只实现核心玩法/交互，不做 UI 美化
3. **可直接打开**：双击 `index.html` 就能在浏览器跑起来
4. **有基本交互**：用户能操作，能看到反馈（点击/键盘/触摸）
5. **注释关键逻辑**：核心算法处加注释，方便后续引擎实现参考

## html_content 要求
- 完整的 HTML5 文档（<!DOCTYPE html> 开头）
- 包含 <style> 和 <script> 标签（全部内联）
- 合理的页面标题和说明文字
- 不超过 300 行代码（原型阶段，不要过度实现）"""

        node = ActionNode(
            key="write_html_prototype",
            expected_type=HtmlPrototypeOutput,
            instruction=(
                "[MODE: IMPLEMENT] 你是前端开发者，生成一个最小可用的 HTML 原型验证核心循环。\n"
                "html_content 必须是完整的 HTML 文档（<!DOCTYPE html>...）。\n"
                "engine_notes 说明引擎实现时的注意事项（数据结构/算法/性能要点）。"
            ),
        )

        await node.fill(req=req_context, llm=llm_client, max_tokens=6000)
        output = node.instruct_content

        if not output or not output.html_content or not output.html_content.startswith("<!"):
            logger.warning("WriteHtmlPrototypeAction 输出不完整")
            # 降级：生成一个基础的 HTML 骨架
            output = HtmlPrototypeOutput(
                html_content=f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{ticket_title} - HTML 原型</title>
<style>
body {{ font-family: sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; background: #1a1a2e; color: #eee; }}
#app {{ text-align: center; }}
canvas {{ border: 2px solid #4ade80; border-radius: 8px; }}
</style>
</head>
<body>
<div id="app">
  <h2>{ticket_title}</h2>
  <canvas id="gameCanvas" width="600" height="400"></canvas>
  <p>核心逻辑待实现</p>
  <script>
    const canvas = document.getElementById('gameCanvas');
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#0f3460';
    ctx.fillRect(0, 0, 600, 400);
    ctx.fillStyle = '#4ade80';
    ctx.font = '20px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('原型框架已就绪', 300, 200);
  </script>
</div>
</body>
</html>""",
                core_mechanics=ticket_desc or ticket_title,
                engine_notes="待细化",
                known_limitations="降级生成，需手动完善核心逻辑",
            )

        # 构建说明文档
        notes_md = f"""# HTML 原型说明 — {ticket_title}

## 核心机制
{output.core_mechanics}

## 引擎实现要点
{output.engine_notes}

## 已知限制（原型阶段可接受）
{output.known_limitations}

## 验收方式
1. 打开 `prototype.html`，确认核心循环可运行
2. 验证基本交互响应正常
3. 无需关注视觉效果，只验证逻辑可行性
"""

        logger.info("✅ HTML 原型已生成: %s (%d 行)", ticket_title[:30],
                    output.html_content.count('\n'))

        return ActionResult(
            success=True,
            data={
                "html_content": output.html_content[:500],  # 摘要存 DB
                "core_mechanics": output.core_mechanics,
                "engine_notes": output.engine_notes,
            },
            files={
                f"{docs_prefix}prototype.html": output.html_content,
                f"{docs_prefix}prototype-notes.md": notes_md,
            },
            message=f"HTML 原型已生成：{ticket_title}",
        )

"""Action: 代码开发（使用 ActionNode 结构化输出）"""
import json
import re
import logging
from typing import Any, Dict
from actions.base import ActionBase, ActionResult
from actions.action_node import ActionNode
from actions.schemas import DevOutput
from llm_client import llm_client

logger = logging.getLogger("action.write_code")


class WriteCodeAction(ActionBase):

    @property
    def name(self) -> str:
        return "write_code"

    @property
    def description(self) -> str:
        return "根据架构设计编写代码（增量开发）"

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        ticket_title = context.get("ticket_title", "")
        ticket_description = context.get("ticket_description", "")
        architecture = context.get("architecture", {})
        module = context.get("module", "other")
        existing_code = context.get("existing_code", {})

        # 精简架构
        arch_summary = ""
        if architecture:
            arch = architecture.get("architecture", architecture)
            compact = {k: arch[k] for k in ("architecture_type", "tech_stack", "module_design") if k in arch}
            arch_summary = json.dumps(compact, ensure_ascii=False, indent=1)[:1500] if compact else ""

        # 已有入口文件
        code_section = ""
        if existing_code:
            for fp in ["index.html", "main.py", "app.py"]:
                if fp in existing_code:
                    code_section = f"\n## 现有入口文件 {fp}\n```\n{existing_code[fp][:2000]}\n```"
                    break

        # Reflexion：重试场景的反思注入
        reflection = context.get("reflection")
        retry_count = int(context.get("retry_count") or 1)
        reflection_block = _format_reflection_block(reflection, retry_count) if reflection else ""

        # Insight 主动注入：历史经验
        prior_insights = context.get("prior_insights", "")
        insights_block = f"\n{prior_insights}\n" if prior_insights else ""

        req_context = f"""## 任务: {ticket_title}
{ticket_description}

## 架构
{arch_summary}
{code_section}
{insights_block}{reflection_block}
要求: 英文文件名 | 前端内联到 index.html | 增量修改不重写 | 只输出改动文件 | 完整可运行"""

        # 行为模式标签（来自 SOP stage.mode 字段）
        sop_config = context.get("sop_config") or {}
        mode = sop_config.get("mode", "")
        mode_prefix = {
            "IMPLEMENT": "[MODE: IMPLEMENT] 专注实现，严格遵循架构设计，不擅自扩展范围。",
            "REVIEW":    "[MODE: REVIEW] 以审查者视角审视代码，主动发现至少 3 个具体问题。",
            "DEBUG":     "[MODE: DEBUG] 系统性排查，追踪根因，逐步验证假设。",
        }.get(mode, "")

        # 使用 ActionNode 结构化输出
        node = ActionNode(
            key="write_code",
            expected_type=DevOutput,
            instruction=f"{mode_prefix}\n根据架构实现功能，返回 files 字段包含完整文件内容。".strip(),
        )
        await node.fill(req=req_context, llm=llm_client, max_tokens=16000)

        output = node.instruct_content
        if output and output.files:
            logger.info("✅ WriteCodeAction 产出 %d 个文件", len(output.files))
            return ActionResult(
                success=True,
                data={"dev_result": output.model_dump(), "estimated_hours": output.estimated_hours},
                files=output.files,
            )

        # 降级
        logger.warning("⚠️ WriteCodeAction 输出无文件，使用降级模板")
        return self._fallback(context)

    def _fallback(self, context: Dict) -> ActionResult:
        title = context.get("ticket_title", "feature")
        description = context.get("ticket_description", "")
        module = context.get("module", "other")
        existing_code = context.get("existing_code", {})

        # UE/C++ \u5de5\u5355\u4e0d\u9002\u5408\u901a\u7528\u964d\u7ea7\u6a21\u677f\uff0c\u76f4\u63a5\u6807\u8bb0\u5931\u8d25\u8ba9 orchestrator \u91cd\u8bd5
        traits = context.get("traits") or context.get("project_traits") or []
        is_ue = (
            any(t in str(traits) for t in ("engine:ue", "lang:cpp"))
            or module in ("ue", "cpp", "c++", "unreal")
            or any(kw in title.lower() for kw in ("c++", ".h", ".cpp", "actor", "component", "uclass", "npc"))
        )
        if is_ue:
            logger.warning("\u26a0\ufe0f WriteCodeAction \u964d\u7ea7\u8df3\u8fc7\uff1aUE/C++ \u9879\u76ee\u4e0d\u9002\u5408\u901a\u7528\u6a21\u677f\uff0c\u6807\u8bb0\u5931\u8d25")
            return ActionResult(
                success=False,
                data={"dev_result": {"files": {}, "notes": "[\u964d\u7ea7] LLM \u8fd4\u56de\u65e0\u6548\uff0cUE/C++ \u5de5\u5355\u9700\u91cd\u8bd5"}, "estimated_hours": 0},
                message="LLM \u8f93\u51fa\u65e0\u6548\uff0cUE/C++ \u5de5\u5355\u65e0\u6cd5\u4f7f\u7528\u901a\u7528\u964d\u7ea7\u6a21\u677f\uff0c\u8bf7\u91cd\u8bd5",
                error="LLM \u8fd4\u56de\u65e0\u6548\uff08NoneType\uff09",
            )

        safe = re.sub(r'[^a-zA-Z0-9_]', '', re.sub(r'[\u4e00-\u9fff]+', '', title.replace(" ", "_")))[:30].lower()
        if not safe:
            safe = f"feature_{abs(hash(title)) % 10000}"

        files = {}
        if module in ("frontend", "design", "other"):
            if "index.html" in existing_code:
                files[f"src/{safe}.js"] = f"// {title}\nconsole.log('{safe} loaded');\n"
            else:
                files["index.html"] = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>{title}</title>
<style>*{{margin:0;padding:0;box-sizing:border-box}}body{{font-family:sans-serif;background:#f0f2f5;min-height:100vh;display:flex;justify-content:center;align-items:center}}.container{{background:#fff;border-radius:12px;padding:40px;box-shadow:0 4px 20px rgba(0,0,0,.1);max-width:600px;width:90%;text-align:center}}h1{{color:#1a1a2e;margin-bottom:16px}}</style>
</head><body><div class="container"><h1>{title}</h1><p>{description[:200] or 'AI 自动开发系统生成'}</p></div></body></html>"""
        elif module in ("backend", "api"):
            files["main.py"] = f'from http.server import HTTPServer, SimpleHTTPRequestHandler\nimport json\nclass H(SimpleHTTPRequestHandler):\n  def do_GET(self):\n    if self.path=="/api/health":self.send_response(200);self.send_header("Content-Type","application/json");self.end_headers();self.wfile.write(json.dumps({{"status":"ok"}}).encode())\n    else:super().do_GET()\nif __name__=="__main__":HTTPServer(("0.0.0.0",8080),H).serve_forever()\n'

        return ActionResult(
            success=True,
            data={"dev_result": {"files": files, "notes": "[降级] 规则引擎"}, "estimated_hours": 2},
            files=files,
        )


def _format_reflection_block(reflection: Dict[str, Any], retry_count: int) -> str:
    """把 ReflectionAction 的结构化反思渲染成 prompt 段落。
    仅在重试场景（retry_count > 1 且有 reflection）时注入。"""
    if not reflection or retry_count <= 1:
        return ""

    missed = reflection.get("missed_requirements") or []
    changes = reflection.get("specific_changes") or []
    missed_lines = "\n".join(f"  - {x}" for x in missed) if missed else "  (无)"
    changes_lines = "\n".join(f"  - {x}" for x in changes) if changes else "  (无)"

    return f"""
## ⚠️ 上一次失败的反思（第 {retry_count - 1} 次失败后，这是第 {retry_count} 次尝试）

**根本原因**：{reflection.get('root_cause', '') or '(未提供)'}

**上次漏掉/误解的需求点**：
{missed_lines}

**上次自测环节为何没拦住**：{reflection.get('previous_attempt_issue', '') or '(未提供)'}

**本次策略调整**：{reflection.get('strategy_change', '') or '(未提供)'}

**具体必须执行的修改**：
{changes_lines}

⚠️ 本次**必须**按上述具体修改指令执行，不能再犯同样的错误。
"""

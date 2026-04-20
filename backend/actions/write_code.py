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

        req_context = f"""## 任务: {ticket_title}
{ticket_description}

## 架构
{arch_summary}
{code_section}
{reflection_block}
要求: 英文文件名 | 前端内联到 index.html | 增量修改不重写 | 只输出改动文件 | 完整可运行"""

        # 使用 ActionNode 结构化输出
        node = ActionNode(
            key="write_code",
            expected_type=DevOutput,
            instruction="根据架构实现功能，返回 files 字段包含完整文件内容。",
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

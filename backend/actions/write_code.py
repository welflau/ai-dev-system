"""Action: 代码开发（从 DevAgent 抽离核心 oneshot 逻辑）"""
import json
import re
import logging
from typing import Any, Dict
from actions.base import ActionBase, ActionResult
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
            compact = {k: arch[k] for k in ("architecture_type", "tech_stack", "module_design", "key_components") if k in arch}
            arch_summary = json.dumps(compact, ensure_ascii=False, indent=1)[:1500] if compact else json.dumps(arch, ensure_ascii=False)[:1500]

        # 已有入口文件
        code_section = ""
        if existing_code:
            for fp in ["index.html", "main.py", "app.py"]:
                if fp in existing_code:
                    code_section = f"\n## 现有入口文件 {fp}\n```\n{existing_code[fp][:2000]}\n```\n"
                    break

        prompt = f"""根据架构实现功能，返回纯 JSON。

## 任务: {ticket_title}
{ticket_description}

## 架构
{arch_summary}
{code_section}
## 返回: {{"files": {{"文件路径": "完整内容"}}, "notes": "备注"}}

要求: 英文文件名 | 前端内联到 index.html | 增量修改不重写 | 只输出改动文件 | 完整可运行代码"""

        result = await llm_client.chat_json(
            [{"role": "user", "content": prompt}],
            temperature=0.3, max_tokens=16000,
        )

        if result and isinstance(result, dict) and result.get("files"):
            files = result["files"]
            if isinstance(files, dict):
                logger.info("✅ WriteCodeAction LLM 返回 %d 个文件", len(files))
                return ActionResult(
                    success=True,
                    data={"dev_result": result, "estimated_hours": result.get("estimated_hours", 4)},
                    files=files,
                )

        # 降级
        logger.warning("⚠️ WriteCodeAction LLM 失败，使用降级模板")
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
            files["main.py"] = f'"""\\n{title}\\n"""\nfrom http.server import HTTPServer, SimpleHTTPRequestHandler\nimport json\n\nclass Handler(SimpleHTTPRequestHandler):\n    def do_GET(self):\n        if self.path == "/api/health":\n            self.send_response(200)\n            self.send_header("Content-Type","application/json")\n            self.end_headers()\n            self.wfile.write(json.dumps({{"status":"ok"}}).encode())\n        else:\n            super().do_GET()\n\nif __name__=="__main__":\n    HTTPServer(("0.0.0.0",8080),Handler).serve_forever()\n'

        return ActionResult(
            success=True,
            data={"dev_result": {"files": files, "notes": "[降级] 规则引擎生成"}, "estimated_hours": 2},
            files=files,
        )

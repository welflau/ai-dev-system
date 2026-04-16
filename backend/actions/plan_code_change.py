"""
Action: 规划代码变更（移植自 MetaGPT WriteCodePlanAndChange 思想）
先规划要改哪些文件、每个文件改什么，再逐个精准修改
解决"每次全文件重写"的根本问题
"""
import json
import logging
from typing import Any, Dict, List
from pydantic import BaseModel, Field
from actions.base import ActionBase, ActionResult
from actions.action_node import ActionNode
from llm_client import llm_client

logger = logging.getLogger("action.plan_code_change")


class CodeChangePlan(BaseModel):
    """代码变更计划 Schema"""
    files_to_create: List[Dict] = Field(default_factory=list,
        description="需要新建的文件 [{path: str, purpose: str}]")
    files_to_modify: List[Dict] = Field(default_factory=list,
        description="需要修改的已有文件 [{path: str, changes: str}]")
    files_unchanged: List[str] = Field(default_factory=list,
        description="不需要改动的文件路径")
    summary: str = ""


class PlanCodeChangeAction(ActionBase):

    @property
    def name(self) -> str:
        return "plan_code_change"

    @property
    def description(self) -> str:
        return "先规划变更范围再逐文件修改（精准增量，不全文件重写）"

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        ticket_title = context.get("ticket_title", "")
        ticket_description = context.get("ticket_description", "")
        architecture = context.get("architecture", {})
        module = context.get("module", "other")
        existing_files = context.get("existing_files", [])
        existing_code = context.get("existing_code", {})

        # --- Phase 1: 规划变更 ---
        plan = await self._plan(ticket_title, ticket_description, architecture, existing_files, existing_code)

        if not plan or (not plan.files_to_create and not plan.files_to_modify):
            # 规划失败，回退到普通写代码
            logger.warning("变更规划为空，回退到全文件生成")
            from actions.write_code import WriteCodeAction
            return await WriteCodeAction().run(context)

        logger.info("📋 变更规划: 新建 %d, 修改 %d, 不变 %d",
                     len(plan.files_to_create), len(plan.files_to_modify), len(plan.files_unchanged))

        # --- Phase 2: 逐文件执行 ---
        all_files = {}

        # 新建文件
        for f in plan.files_to_create:
            if isinstance(f, str):
                path, purpose = f, ""
            else:
                path = f.get("path", "") if isinstance(f, dict) else str(f)
                purpose = f.get("purpose", "") if isinstance(f, dict) else ""
            if path:
                content = await self._generate_file(path, purpose, ticket_title, ticket_description, existing_code)
                if content:
                    all_files[path] = content

        # 修改已有文件
        for f in plan.files_to_modify:
            if isinstance(f, str):
                path, changes = f, ""
            else:
                path = f.get("path", "") if isinstance(f, dict) else str(f)
                changes = f.get("changes", "") if isinstance(f, dict) else ""
            if path and path in existing_code:
                modified = await self._modify_file(path, existing_code[path], changes, ticket_title)
                if modified:
                    all_files[path] = modified

        if not all_files:
            logger.warning("规划执行后无文件产出，回退")
            from actions.write_code import WriteCodeAction
            return await WriteCodeAction().run(context)

        return ActionResult(
            success=True,
            data={
                "dev_result": {
                    "files": all_files,
                    "notes": f"[PlanAndChange] {plan.summary}",
                    "plan": plan.model_dump(),
                },
                "estimated_hours": 4,
            },
            files=all_files,
        )

    async def _plan(self, title, description, architecture, existing_files, existing_code) -> CodeChangePlan:
        """Phase 1: 规划要改哪些文件"""
        code_files = [f for f in existing_files if not f.startswith(("docs/", "tests/", ".git", "build/"))]

        # 精简架构
        arch_summary = ""
        if architecture:
            arch = architecture.get("architecture", architecture)
            arch_summary = json.dumps({k: arch[k] for k in ("architecture_type", "tech_stack", "module_design") if k in arch}, ensure_ascii=False)[:800]

        req_context = f"""## 任务: {title}
{description}

## 架构: {arch_summary}

## 项目已有文件
{chr(10).join(f'  - {f}' for f in code_files[:20]) or '  (空项目)'}

根据任务需求，规划代码变更方案：哪些文件要新建、哪些要修改、哪些不动。"""

        node = ActionNode(
            key="plan_code_change",
            expected_type=CodeChangePlan,
            instruction="规划代码变更，列出需要新建和修改的文件。只输出和任务相关的文件变更。",
        )
        await node.fill(req=req_context, llm=llm_client, max_tokens=2000)
        return node.instruct_content

    async def _generate_file(self, path: str, purpose: str, title: str, description: str, existing_code: Dict) -> str:
        """Phase 2a: 生成新文件"""
        # 如果是 HTML 且已有 index.html，提供已有代码参考
        ref = ""
        if "index.html" in existing_code:
            ref = f"\n## 已有 index.html（保持风格一致）\n```\n{existing_code['index.html'][:1500]}\n```"

        prompt = f"""生成文件 `{path}`。
用途: {purpose}
任务: {title} — {description[:200]}
{ref}

直接输出文件完整内容（不要 markdown 代码块包裹）。"""

        try:
            content = await llm_client.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.3, max_tokens=8000,
            )
            if content and not content.startswith("[LLM_UNAVAILABLE]"):
                # 清理 markdown 代码块
                if content.strip().startswith("```"):
                    lines = content.strip().split("\n")
                    lines = [l for l in lines if not l.strip().startswith("```")]
                    content = "\n".join(lines)
                return content
        except Exception as e:
            logger.warning("生成文件 %s 失败: %s", path, e)
        return ""

    async def _modify_file(self, path: str, original: str, changes: str, title: str) -> str:
        """Phase 2b: 修改已有文件"""
        prompt = f"""修改文件 `{path}`。

## 需要的改动
{changes}

## 任务背景
{title}

## 原文件内容
```
{original[:3000]}
```

输出修改后的完整文件内容（不要 markdown 代码块包裹）。保留所有原有功能，只做需要的改动。"""

        try:
            content = await llm_client.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.3, max_tokens=8000,
            )
            if content and not content.startswith("[LLM_UNAVAILABLE]"):
                if content.strip().startswith("```"):
                    lines = content.strip().split("\n")
                    lines = [l for l in lines if not l.strip().startswith("```")]
                    content = "\n".join(lines)
                return content
        except Exception as e:
            logger.warning("修改文件 %s 失败: %s", path, e)
        return ""

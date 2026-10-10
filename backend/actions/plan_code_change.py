"""
Action: 规划代码变更（移植自 MetaGPT WriteCodePlanAndChange 思想）
先规划要改哪些文件、每个文件改什么，再逐个精准修改
解决"每次全文件重写"的根本问题
"""
import json
import logging
from typing import Any, Dict, List
from pydantic import BaseModel, Field, field_validator
from actions.base import ActionBase, ActionResult
from actions.action_node import ActionNode
from llm_client import llm_client

logger = logging.getLogger("action.plan_code_change")


def _coerce_file_entries(v: Any, detail_key: str) -> Any:
    """把 LLM 常见的几种写法统一成 [{path, <detail_key>}]。

    LLM 经常无视 schema 直接回字符串数组 `["gallery.js", "post.js"]`。
    Pydantic 一报 ValidationError，ActionNode 就走宽松解析 → 整个 plan 退化，
    最终零文件 → 回退 WriteCode → 降级模板。一次格式不合规拖垮整条链
    （TK-20260920-ce79a9）。这里直接兼容，别为了 schema 洁癖丢掉可用信息。
    """
    if not isinstance(v, list):
        return v
    out = []
    for item in v:
        if isinstance(item, str):
            out.append({"path": item, detail_key: ""})
        elif isinstance(item, dict):
            # 有的模型用 file/filename/name 当 key
            if "path" not in item:
                for alt in ("file", "filename", "name", "file_path"):
                    if isinstance(item.get(alt), str):
                        item = {**item, "path": item[alt]}
                        break
            out.append(item)
        else:
            out.append({"path": str(item), detail_key: ""})
    return out


class CodeChangePlan(BaseModel):
    """代码变更计划 Schema"""
    files_to_create: List[Dict] = Field(default_factory=list,
        description="需要新建的文件 [{path: str, purpose: str}]")
    files_to_modify: List[Dict] = Field(default_factory=list,
        description="需要修改的已有文件 [{path: str, changes: str}]")
    files_unchanged: List[str] = Field(default_factory=list,
        description="不需要改动的文件路径")
    summary: str = ""

    @field_validator("files_to_create", mode="before")
    @classmethod
    def _fix_create(cls, v):
        return _coerce_file_entries(v, "purpose")

    @field_validator("files_to_modify", mode="before")
    @classmethod
    def _fix_modify(cls, v):
        return _coerce_file_entries(v, "changes")

    @field_validator("files_unchanged", mode="before")
    @classmethod
    def _fix_unchanged(cls, v):
        """反过来：这里要的是字符串，LLM 却可能给 [{path: ...}]。"""
        if not isinstance(v, list):
            return v
        return [
            (item.get("path") or item.get("file") or "") if isinstance(item, dict) else str(item)
            for item in v
        ]


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

        # Reflexion：重试场景有 reflection，注入到 prompt
        reflection = context.get("reflection")
        retry_count = int(context.get("retry_count") or 1)
        reflection_block = _format_reflection_block(reflection, retry_count) if reflection else ""

        # Insight 主动注入：历史经验
        prior_insights = context.get("prior_insights", "")

        # --- Phase 1: 规划变更 ---
        plan = await self._plan(ticket_title, ticket_description, architecture,
                                existing_files, existing_code, reflection_block,
                                prior_insights)

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
        skipped_modify = []
        for f in plan.files_to_modify:
            if isinstance(f, str):
                path, changes = f, ""
            else:
                path = f.get("path", "") if isinstance(f, dict) else str(f)
                changes = f.get("changes", "") if isinstance(f, dict) else ""
            if not path:
                continue
            # LLM 给的路径常和仓库里的差一层前缀（gallery.js vs src/gallery.js）。
            # 原先 `path in existing_code` 不匹配就**静默跳过**，一个文件都改不到
            # 却照样往下走，最后零产出回退降级模板（TK-20260920-ce79a9）。
            real_path = self._resolve_path(path, existing_code)
            if not real_path:
                skipped_modify.append(path)
                continue
            modified = await self._modify_file(real_path, existing_code[real_path], changes, ticket_title)
            if modified:
                all_files[real_path] = modified

        if skipped_modify:
            logger.warning("⚠️ 变更计划里 %d 个待改文件在仓库中找不到，已跳过: %s",
                           len(skipped_modify), ", ".join(skipped_modify[:5]))

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

    @staticmethod
    def _resolve_path(path: str, existing_code: Dict) -> str:
        """把 LLM 给的路径对到仓库里真实存在的文件；对不上返回 ""。

        依次尝试：原样 → 归一化斜杠 → 忽略大小写 → 按文件名唯一匹配。
        最后一条只在**全仓库该文件名唯一**时才认，避免把 a/util.js 改成 b/util.js。
        """
        if not path:
            return ""
        if path in existing_code:
            return path
        norm = path.replace("\\", "/").lstrip("./")
        table = {p.replace("\\", "/").lstrip("./"): p for p in existing_code}
        if norm in table:
            return table[norm]
        lower = {k.lower(): v for k, v in table.items()}
        if norm.lower() in lower:
            return lower[norm.lower()]
        base = norm.rsplit("/", 1)[-1].lower()
        hits = [orig for k, orig in table.items() if k.rsplit("/", 1)[-1].lower() == base]
        return hits[0] if len(hits) == 1 else ""

    async def _plan(self, title, description, architecture, existing_files,
                    existing_code, reflection_block: str = "",
                    prior_insights: str = "") -> CodeChangePlan:
        """Phase 1: 规划要改哪些文件"""
        code_files = [f for f in existing_files if not f.startswith(("docs/", "tests/", ".git", "build/"))]

        # 精简架构
        arch_summary = ""
        if architecture:
            arch = architecture.get("architecture", architecture)
            arch_summary = json.dumps({k: arch[k] for k in ("architecture_type", "tech_stack", "module_design") if k in arch}, ensure_ascii=False)[:800]

        insights_block = f"\n{prior_insights}\n" if prior_insights else ""

        req_context = f"""## 任务: {title}
{description}

## 架构: {arch_summary}
{insights_block}{reflection_block}
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
            ref_code = existing_code["index.html"]
            ref_snippet = ref_code if len(ref_code) <= 8000 else ref_code[:8000] + "\n... [已截断] ..."
            ref = f"\n## 已有 index.html（保持风格一致）\n```\n{ref_snippet}\n```"

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
                # 清理 markdown 代码块（含「散文 + 围栏」的混合回复）
                from content_sanitizer import strip_code_fences
                content, note = strip_code_fences(content, path)
                if note:
                    logger.warning("生成 %s 净化: %s", path, note)
                return content
        except Exception as e:
            logger.warning("生成文件 %s 失败: %s", path, e)
        return ""

    async def _modify_file(self, path: str, original: str, changes: str, title: str) -> str:
        """Phase 2b: 修改已有文件

        关键：原文件一定要完整传给 LLM，不能截断。历史 [:3000] 截断导致
        LLM 把"截断的 HTML"误认为是"不完整文件"，按自己想象重写整个页面。
        只在真的超长（>20k）时才截断，并加显式 marker。
        """
        if len(original) <= 20000:
            original_block = original
        else:
            original_block = original[:20000] + (
                f"\n\n/* ... [文件截断显示：原文共 {len(original)} 字符，"
                f"当前只给出前 20000；未展示部分保留不变] ... */"
            )

        prompt = f"""修改文件 `{path}`。

## 需要的改动
{changes}

## 任务背景
{title}

## 原文件完整内容（保留所有原有功能，只做增量改动）
```
{original_block}
```

输出修改后的完整文件内容（不要 markdown 代码块包裹）。
⚠️ **硬要求**：
- 必须保留原文件里所有已实现的功能，不能删减
- 只在原基础上叠加本次需要的改动
- 不要"重新设计"页面结构、不要添加未要求的模板化内容（如示例卡片、占位文字等）"""

        try:
            content = await llm_client.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.3, max_tokens=8000,
            )
            if content and not content.startswith("[LLM_UNAVAILABLE]"):
                from content_sanitizer import strip_code_fences
                content, note = strip_code_fences(content, path)
                if note:
                    logger.warning("修改 %s 净化: %s", path, note)
                return content
        except Exception as e:
            logger.warning("修改文件 %s 失败: %s", path, e)
        return ""


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

⚠️ 本次**必须**按上述具体修改指令执行，不能再犯同样的错误。规划时要明确标注哪些 change 对应哪个文件变更。
"""

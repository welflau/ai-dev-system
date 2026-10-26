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

    LLM 经常无视 schema 直接回字符串数组 `["gallery.js", "post.js"]`，
    或用 `reason / description / responsibility / summary / detail` 代替 `changes / purpose`。
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
                for alt in ("file", "filename", "name", "file_path", "target"):
                    if isinstance(item.get(alt), str):
                        item = {**item, "path": item[alt]}
                        break
            # 有的模型用 reason/description/responsibility/detail/action/what 代替 changes/purpose，或者把 changes 写成 list[str]
            cur_val = item.get(detail_key)
            if isinstance(cur_val, list):
                item = {**item, detail_key: "; ".join(str(x) for x in cur_val if x)}
            elif cur_val is not None and not isinstance(cur_val, str):
                item = {**item, detail_key: str(cur_val)}
            elif not cur_val:
                for d_alt in ("changes", "purpose", "reason", "description", "responsibility",
                              "detail", "action", "what", "summary", "modification", "fix"):
                    val = item.get(d_alt)
                    if isinstance(val, str) and val.strip():
                        item = {**item, detail_key: val.strip()}
                        break
                    if isinstance(val, list) and val:
                        item = {**item, detail_key: "; ".join(str(x) for x in val)}
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

        # --- Phase 0: 插件级确定性自愈 + 编译错误直达快通道 ---
        repo_path = context.get("repo_path") or ""
        failure_type = context.get("failure_type") or ""
        compile_errors = context.get("compile_errors") or []
        compile_hints = context.get("compile_hints") or []

        auto_fixed_files: Dict[str, str] = {}
        if failure_type and repo_path:
            try:
                from plugins.registry import apply_plugin_deterministic_fixes
                auto_fixed_files = apply_plugin_deterministic_fixes(
                    failure_type, repo_path, compile_errors, existing_code
                )
            except Exception as e:
                logger.debug("插件确定性自愈跳过: %s", e)

        # 若是编译/类型检查报错（精确到了具体文件路径和行号），直接定位报错文件修复，
        # 不再调 _plan 全量规划 6-7 个无关脚本（省掉 80s 规划 + N×150s 无关文件重写）
        error_by_file: Dict[str, List[str]] = {}
        for err in compile_errors:
            fp = (err.get("file") or "").replace("\\", "/").lstrip("./")
            if not fp or fp.startswith(("node_modules/", "dist/")):
                continue
            line_no = err.get("line", "?")
            col_no = err.get("column", "?")
            code_str = err.get("code", "")
            msg_str = err.get("msg", "")
            error_by_file.setdefault(fp, []).append(
                f"第 {line_no}:{col_no} 行 [{code_str}]: {msg_str}"
            )

        if error_by_file:
            # 过滤掉已被插件确定性修完且无其它错误的场景：若全部报错文件都已被确定性修好，直接返回！
            remaining_files = {
                fp: errs for fp, errs in error_by_file.items()
                if fp not in auto_fixed_files
            }
            if auto_fixed_files and not remaining_files:
                logger.info(
                    "⚡ 插件确定性快修已完成全部 %d 个报错文件修复，耗时 0 LLM token: %s",
                    len(auto_fixed_files), list(auto_fixed_files.keys()),
                )
                return ActionResult(
                    success=True,
                    data={
                        "dev_result": {
                            "files": auto_fixed_files,
                            "notes": f"[PluginAutoFix] 已按编译错误确定性修复 {', '.join(auto_fixed_files.keys())}",
                        },
                        "estimated_hours": 1,
                    },
                    files=auto_fixed_files,
                )

            logger.info("🎯 编译错误直达快通道：仅针对 %d 个报错文件执行精准修复: %s",
                        len(error_by_file), list(error_by_file.keys()))
            all_files = dict(auto_fixed_files)
            hints_text = ("\n\n## 领域修复提示\n" + "\n".join(f"- {h}" for h in compile_hints)) if compile_hints else ""
            repo_files_summary = "\n".join(f"  - `{p}`" for p in sorted(existing_files)[:60] if not p.startswith("docs/"))
            for fp, err_lines in error_by_file.items():
                if fp in all_files:
                    continue
                real_path = self._resolve_path(fp, existing_code) or fp
                # 优先从仓库磁盘读取完整未截断文件（existing_code 对 >15000 字符的文件被 memory.py 截断过）
                orig = None
                if repo_path:
                    from pathlib import Path as _P
                    cand = _P(repo_path) / real_path
                    if cand.is_file():
                        try:
                            orig = cand.read_text(encoding="utf-8", errors="replace")
                        except Exception:
                            pass
                if orig is None:
                    orig = existing_code.get(real_path)
                if orig is None:
                    continue
                specific_instructions = (
                    "请精准修复以下编译器报错（严禁改动其它无关逻辑）：\n"
                    + "\n".join(f"  - {line}" for line in err_lines)
                    + hints_text
                    + (
                        f"\n\n## 仓库真实存在的文件列表（处理 TS2307 Cannot find module 时，严禁 import 以下列表之外的本地路径！）\n{repo_files_summary}"
                        if repo_files_summary else ""
                    )
                )
                if reflection_block:
                    specific_instructions += "\n" + reflection_block
                modified = await self._modify_file(real_path, orig, specific_instructions, ticket_title)
                if modified and modified.strip() != orig.strip():
                    all_files[real_path] = modified
                elif modified:
                    logger.warning("⚠️ _modify_file(%s) 返回内容与原文件完全一致（未生效），交由后续验证处理", real_path)

            if all_files:
                return ActionResult(
                    success=True,
                    data={
                        "dev_result": {
                            "files": all_files,
                            "notes": f"[DirectErrorFix] 精准修复报错文件: {', '.join(all_files.keys())}",
                        },
                        "estimated_hours": 1,
                    },
                    files=all_files,
                )

        # --- Phase 1: 规划变更 ---
        plan = await self._plan(ticket_title, ticket_description, architecture,
                                existing_files, existing_code, reflection_block,
                                prior_insights)

        if not plan or (not plan.files_to_create and not plan.files_to_modify):
            if plan and plan.files_unchanged and existing_code:
                logger.info("📋 变更规划结论：仓库现有 %d 个文件已满足要求，无需额外修改", len(plan.files_unchanged))
                kept = {k: v for k, v in existing_code.items() if not k.endswith("dev-notes.md")}
                if kept:
                    return ActionResult(
                        success=True,
                        data={
                            "dev_result": {
                                "files": kept,
                                "notes": f"[PlanAndChange] {plan.summary or '现有文件已满足需求'}",
                                "plan": plan.model_dump(),
                            },
                            "estimated_hours": 2,
                        },
                        files=kept,
                    )
            # 规划失败，回退到普通写代码
            logger.warning("变更规划为空，回退到全文件生成")
            from actions.write_code import WriteCodeAction
            return await WriteCodeAction().run(context)

        logger.info("📋 变更规划: 新建 %d, 修改 %d, 不变 %d",
                     len(plan.files_to_create), len(plan.files_to_modify), len(plan.files_unchanged))

        # --- Phase 2: 逐文件执行 ---
        all_files = {}
        repo_path = context.get("repo_path") or ""

        # 新建文件
        for f in plan.files_to_create:
            if isinstance(f, str):
                path, purpose = f, ""
            else:
                path = f.get("path", "") if isinstance(f, dict) else str(f)
                raw_purp = f.get("purpose", "") if isinstance(f, dict) else ""
                purpose = "; ".join(str(x) for x in raw_purp) if isinstance(raw_purp, list) else str(raw_purp or "")
            norm_create = path.replace("\\", "/").lstrip("./") if path else ""
            if norm_create.startswith(("test/", "tests/")) or norm_create.endswith((".spec.ts", ".test.ts")):
                logger.info("⏭ 跳过测试脚本新建（由插件门禁自动验证）: %s", norm_create)
                continue
            if path:
                content = await self._generate_file(path, purpose, ticket_title, ticket_description, existing_code)
                if content:
                    all_files[path] = content

        # 修改已有文件
        skipped_modify = []
        fallback_instructions = ""
        if reflection and isinstance(reflection, dict):
            sc = reflection.get("specific_changes") or []
            if sc:
                fallback_instructions = "按反思要求修改：\n" + "\n".join(f"- {x}" for x in sc)
            elif reflection.get("strategy_change"):
                fallback_instructions = str(reflection.get("strategy_change"))

        for f in plan.files_to_modify:
            if isinstance(f, str):
                path, changes = f, ""
            else:
                path = f.get("path", "") if isinstance(f, dict) else str(f)
                raw_chg = f.get("changes", "") if isinstance(f, dict) else ""
                changes = "; ".join(str(x) for x in raw_chg) if isinstance(raw_chg, list) else str(raw_chg or "")
            if not path:
                continue
            norm_check = path.replace("\\", "/").lstrip("./")
            # 跳过重型 e2e 测试脚本的修改：门禁由插件 h5_typecheck + h5_playtest 执行，无需 LLM 反复重写几百行的 spec.ts（常耗费 6-8 分钟）
            if norm_check.startswith(("test/", "tests/")) or norm_check.endswith((".spec.ts", ".test.ts")):
                logger.info("⏭ 跳过测试脚本修改（由插件门禁自动验证）: %s", norm_check)
                continue
            if not changes.strip():
                changes = fallback_instructions or f"完成任务「{ticket_title}」对该文件的增量要求"
            real_path = self._resolve_path(path, existing_code) or path.replace("\\", "/").lstrip("./")
            orig_content = None
            if repo_path and real_path:
                from pathlib import Path as _P
                cand = _P(repo_path) / real_path
                if cand.is_file():
                    try:
                        orig_content = cand.read_text(encoding="utf-8", errors="replace")
                    except Exception:
                        pass
            if orig_content is None and real_path:
                orig_content = existing_code.get(real_path)
            if orig_content is not None and real_path:
                modified = await self._modify_file(real_path, orig_content, changes, ticket_title)
                if modified:
                    all_files[real_path] = modified
            else:
                # 仓库磁盘上也没有 → LLM 把待新建文件误放进了 files_to_modify，按新建生成
                norm_p = path.replace("\\", "/").lstrip("./")
                generated = await self._generate_file(norm_p, changes, ticket_title, ticket_description, existing_code)
                if generated:
                    all_files[norm_p] = generated
                else:
                    skipped_modify.append(path)

        if skipped_modify:
            logger.warning("⚠️ 变更计划里 %d 个待改文件在仓库中找不到，已跳过: %s",
                           len(skipped_modify), ", ".join(skipped_modify[:5]))

        if not all_files:
            if compile_errors:
                logger.error("❌ 编译错误直达快通道未能产出有效修改，拒绝回退到 WriteCodeAction 全仓重写！")
                return ActionResult(
                    success=False,
                    data={"dev_result": {"files": {}, "notes": "编译错误自动修复未产出有效变更"}},
                    files={},
                    error="编译错误自动修复未产出有效变更",
                )
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

请用单个 ``` 代码块包裹输出该文件的完整源码，禁止在代码块外附加任何解释、总结或前言后语。"""

        try:
            content = await llm_client.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.3, max_tokens=8000,
            )
            if content and not content.startswith("[LLM_UNAVAILABLE]"):
                # 清理 markdown 代码块（含「散文 + 围栏」或「无围栏散文 + 代码」的混合回复）
                from content_sanitizer import find_content_defects, strip_code_fences
                content, note = strip_code_fences(content, path)
                if note:
                    logger.warning("生成 %s 净化: %s", path, note)
                defects = find_content_defects(content, path)
                if defects:
                    logger.warning("生成 %s 净化后仍存在内容缺陷，已拒绝写入: %s", path, defects)
                    return ""
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

请用单个 ``` 代码块包裹输出修改后的完整文件内容，禁止在代码块外输出任何解释、总结或前言后语。
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
                from content_sanitizer import find_content_defects, strip_code_fences
                content, note = strip_code_fences(content, path)
                if note:
                    logger.warning("修改 %s 净化: %s", path, note)
                defects = find_content_defects(content, path)
                if defects:
                    logger.warning("修改 %s 净化后仍存在内容缺陷，已拒绝覆盖: %s", path, defects)
                    return ""
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

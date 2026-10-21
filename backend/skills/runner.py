"""
SkillRunner — 通用 skill 执行引擎。

把一个可执行 skill（ExecutableSkill）声明的工具集组装成 QueryEngine 的 tools，
拼 system prompt（skill body + 工单上下文），跑 REACT 循环让 LLM 自主调用工具完成任务，
消费事件流（通过 on_tool 回调让调用方写时间轴），最后按 outputs.globs 扫盘回收产出。

内核复用 query_engine.QueryEngine（同 agents/base.py:_react_with_think_inner），
但不绑 BaseAgent —— 输入是 skill 定义而非 agent，可被 Agent 内部或独立调用/测试。

SkillRunner 本身不碰 DB（时间轴落盘交给调用方的 on_tool），保持可独立测试。
"""
from __future__ import annotations

import logging
import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from skills.executable_loader import ExecutableSkill

logger = logging.getLogger("skills.runner")

# 认定为「文本」的扩展名 —— 只有这些会被 text_outputs 兼容属性读进内存。
# 其余（.png/.mp3/.mp4/...）一律只登记路径，绝不 read_text。
_TEXT_EXTS = frozenset({
    ".md", ".txt", ".json", ".yaml", ".yml", ".csv", ".tsv",
    ".html", ".htm", ".xml", ".ini", ".toml", ".cfg", ".log",
})


# ── 工具执行适配器（复刻 OrchestratorToolExecutorAdapter，加 mcp__ 分支）──
class SkillToolExecutorAdapter:
    def __init__(self, actions: Dict[str, Any], base_context: dict):
        self._actions = actions               # {name: ActionBase}
        self._base_context = base_context

    async def execute(self, tool_name: str, tool_input: dict, context: dict):
        import json
        # MCP 外部工具
        if tool_name.startswith("mcp__"):
            try:
                from mcp_client import mcp_client
                result = await mcp_client.call_tool(
                    tool_name, tool_input if isinstance(tool_input, dict) else {})
                return json.dumps(result, ensure_ascii=False), None
            except Exception as e:
                return json.dumps({"error": f"MCP 调用失败: {e}"}, ensure_ascii=False), None

        action = self._actions.get(tool_name)
        if not action:
            return f"未知工具: {tool_name}", None
        ctx = {**self._base_context, **context, **tool_input}
        try:
            result = await action.run(ctx)
            text = result.message or json.dumps(result.data or {}, ensure_ascii=False)
            return text, None
        except Exception as e:
            logger.warning("SkillToolExecutorAdapter %s 失败: %s", tool_name, e)
            return f"工具执行失败: {e}", None


@dataclass
class ArtifactOut:
    """一个产出文件的**索引**（不含内容）。

    v0.20 破坏性变更：原先 `SkillRunResult.outputs` 是 `Dict[相对路径 → 内容]`，
    回收时用 `p.read_text(encoding="utf-8", errors="replace")` 读全文。
    那对 PNG / MP3 / MP4 是灾难 —— 二进制被逐字节替换成 U+FFFD 塞进内存，
    既没法用又白占 token（skill 链接入生图后每轮都会踩）。

    现在只登记元信息，内容由需要的人自己读 abs_path。
    """
    rel_path: str                 # 相对 outputs.root，POSIX 分隔符
    abs_path: str
    kind: str = ""                # 由 x-workflow.produces 的 glob 反查，无声明则空
    mime: str = ""
    size: int = 0
    is_binary: bool = False

    @property
    def name(self) -> str:
        return self.rel_path.rsplit("/", 1)[-1]


@dataclass
class SkillRunResult:
    status: str                                  # success | partial | budget_exceeded | error | skipped
    outputs: List[ArtifactOut] = field(default_factory=list)
    rounds: int = 0
    message: str = ""

    @property
    def output_paths(self) -> List[str]:
        """相对路径列表。日志/时间轴用这个，不要用 len(outputs) 以外的结构假设。"""
        return [o.rel_path for o in self.outputs]

    @property
    def text_outputs(self) -> Dict[str, str]:
        """**兼容属性** —— 还原成旧的 `{相对路径: 内容}`，只收文本扩展名。

        给「真的需要全部文本内容」的旧调用方留的过渡口子。当前库内没有调用者
        （architect.py 只要文件名集合，已改用 output_paths），保留它是因为
        OpenSpec Apply 那类场景后续可能要回读内容做校验。

        新代码不要用它：
          - 二进制文件会被静默跳过（这正是它「安全」的地方，但也意味着不完整）
          - 每次访问都重新读盘，没有缓存
        需要内容就自己 `Path(o.abs_path).read_text()`，判断存在性用 output_paths。
        """
        out: Dict[str, str] = {}
        for o in self.outputs:
            if o.is_binary:
                continue
            try:
                out[o.rel_path] = Path(o.abs_path).read_text(
                    encoding="utf-8", errors="replace"
                )
            except Exception as e:
                logger.warning("text_outputs 读取失败 %s: %s", o.rel_path, e)
        return out


_DONE_SCHEMA = {
    "name": "done",
    "description": "所有步骤已完成、产出文件都已写好，调用此工具结束。",
    "input_schema": {"type": "object",
                     "properties": {"summary": {"type": "string", "description": "完成摘要（可选）"}},
                     "required": []},
}


class SkillRunner:
    def __init__(self, skill: ExecutableSkill, llm_client=None, hooks=None):
        self.skill = skill
        self._llm = llm_client
        # hooks 默认接全局 registry。历史上这里默认 None，而三个构造点
        # （agents/dev.py、agents/architect.py、agents/skill_agent.py）全都
        # 只传 skill —— 于是 engine.py 里 `if self.hooks:` 一路跳过，
        # PRE/POST_TOOL_USE 一次都不发。全库唯独这条 QueryEngine 漏了 hooks，
        # 而真正跑 shell 的两个 Action（GenericCLIAction / ShellAction）
        # **只**在这条路上 —— 唯一跑命令的路径成了唯一没有审计的路径。
        # 在 __init__ 兜底而不是改三个调用点，防止以后新增构造点再漏一次。
        if hooks is None:
            try:
                from hooks.registry import hook_registry
                hooks = hook_registry
            except Exception:
                hooks = None
        self._hooks = hooks

    async def is_available(self, context: dict) -> bool:
        """反射调用 x-runner.availability 里的 capability_check.* 函数，全 True 才可用。"""
        if not self.skill.availability:
            return True
        import capability_check as cap
        project_id = context.get("project_id")
        repo_path = context.get("repo_path")
        for fn_name in self.skill.availability:
            fn = getattr(cap, fn_name, None)
            if fn is None:
                logger.warning("availability 函数不存在: %s", fn_name)
                return False
            try:
                import inspect
                res = fn(project_id, repo_path)
                if inspect.isawaitable(res):
                    res = await res
                if not res:
                    return False
            except Exception as e:
                logger.warning("availability %s 调用失败: %s", fn_name, e)
                return False
        return True

    def _output_root(self, context: dict) -> Optional[Path]:
        """渲染 outputs.root 模板 → 绝对路径（相对 repo_path）。"""
        root_tpl = self.skill.output_root_template
        repo = context.get("repo_path")
        if not root_tpl or not repo:
            return None
        try:
            rendered = root_tpl.format(**{k: v for k, v in context.items() if isinstance(v, (str, int))})
        except Exception:
            rendered = root_tpl
        return (Path(repo) / rendered).resolve()

    def _build_actions(self) -> Dict[str, Any]:
        from actions.generic_cli import GenericCLIAction
        from plugins.registry import create_action
        actions: Dict[str, Any] = {}
        for spec in self.skill.cli_tools:
            actions[spec.name] = GenericCLIAction(spec)
        outs = self.skill.outputs or {}
        write_mode = str(outs.get("write_mode") or "skill")
        allowed_exts = outs.get("allowed_exts")
        if allowed_exts is not None and not isinstance(allowed_exts, list):
            allowed_exts = None
        skill_dir = self.skill.source_path.parent if self.skill.source_path else None
        for bt in self.skill.builtin_tools:
            # mcp__ 声明在 executor 层处理，不建 Action
            if str(bt).startswith("mcp__"):
                continue
            action = create_action(
                bt,
                skill_dir=skill_dir,
                allowed_exts=allowed_exts,
                write_mode=write_mode,
            )
            if action is None:
                continue
            actions[action.name] = action
        return actions

    def _build_system(self, context: dict) -> str:
        parts = [self.skill.body]
        ctx_lines = []
        if context.get("ticket_title"):
            ctx_lines.append(f"- 工单标题：{context['ticket_title']}")
        if context.get("ticket_description"):
            ctx_lines.append(f"- 工单描述：{str(context['ticket_description'])[:400]}")
        if context.get("change_id"):
            ctx_lines.append(f"- change_id：{context['change_id']}")
        if context.get("project_traits"):
            ctx_lines.append(f"- 项目 traits：{context['project_traits']}")
        if ctx_lines:
            parts.append("## 当前上下文\n" + "\n".join(ctx_lines))

        # v0.20 产物总线：上游 skill 的产出（路径为主，让 LLM 用 read_file 自取）。
        # 没有 _artifacts 时返回空串 —— openspec-* 这类老 skill 走的还是
        # context 直传，不该被塞一个空标题。
        try:
            from artifacts.injector import render_artifacts_prompt
            upstream = render_artifacts_prompt(context)
            if upstream:
                parts.append(upstream)
        except Exception as e:
            logger.warning("渲染上游产物失败（跳过）: %s", e)

        return "\n\n".join(parts)

    async def execute(
        self,
        context: dict,
        on_tool: Optional[Callable[[Any], Awaitable[None]]] = None,
    ) -> SkillRunResult:
        from query_engine import QueryEngine, Budget
        from query_engine.events import (
            MessageDoneEvent, BudgetExceededEvent, ToolDoneEvent, ErrorEvent,
        )

        llm = self._llm
        if llm is None:
            from llm_client import llm_client as _default_llm
            llm = _default_llm

        # 产出目录预填给 WriteFileAction
        out_root = self._output_root(context)
        if out_root is not None:
            context = {**context, "_skill_output_root": str(out_root)}

        actions = self._build_actions()
        tools = [a.tool_schema() for a in actions.values()] + [_DONE_SCHEMA]
        # 声明的 MCP 工具（builtin_tools 里以 mcp__ 开头的）
        mcp_names = [b for b in self.skill.builtin_tools if b.startswith("mcp__")]
        if mcp_names:
            try:
                from mcp_client import mcp_client
                all_mcp = mcp_client.list_all_tool_schemas()
                tools += [t for t in all_mcp if t.get("name") in mcp_names]
            except Exception as e:
                logger.warning("加载 MCP 工具 schema 失败: %s", e)

        b = self.skill.budget or {}
        budget = Budget(
            max_tokens=int(b.get("max_tokens") or 120_000),
            max_turns=int(b.get("max_rounds") or 12),
            max_seconds=float(b.get("max_seconds") or 300.0),
        )
        max_rounds = int(b.get("max_rounds") or 12)

        executor = SkillToolExecutorAdapter(actions, context)
        engine = QueryEngine(llm_client=llm, tool_executor=executor,
                             budget=budget, hooks=self._hooks, max_rounds=max_rounds)

        system = self._build_system(context)
        messages = [{"role": "user", "content": f"请执行 skill：{self.skill.name}。完成后调用 done。"}]

        # CLI 模式下 QueryEngine 不传 tools（见 tests/skills/test_cli_mode_tool_gap.py），
        # 上面组装的 actions 对 CLI 完全不可见。声明 skill_io 上下文让
        # llm_client._build_settings_args 注入对应的 MCP server —— 那是 CLI
        # 唯一能命名调用 ADS 工具的途径。API 模式下这个声明无害（走 tools 参数）。
        self._enter_skill_io_context(out_root, context)

        status, rounds, msg = "success", 0, ""
        try:
            async for ev in engine.run(messages, system, tools, context):
                if isinstance(ev, ToolDoneEvent):
                    if on_tool:
                        try:
                            await on_tool(ev)
                        except Exception as _e:
                            logger.debug("on_tool 回调异常（忽略）: %s", _e)
                elif isinstance(ev, MessageDoneEvent):
                    rounds, msg = ev.rounds, ev.full_text
                elif isinstance(ev, BudgetExceededEvent):
                    status, msg = "budget_exceeded", ev.reason
                elif isinstance(ev, ErrorEvent):
                    status, msg = "error", ev.message
        except Exception as e:
            logger.warning("SkillRunner.execute 循环异常: %s", e, exc_info=True)
            status = "error"
            msg = str(e)
        finally:
            # 必须清 —— contextvar 不会自动还原，留着会让后续的普通聊天调用
            # 带上一个 skill 的产出目录，把文件写到莫名其妙的地方
            self._exit_skill_io_context()

        outputs = self._collect_outputs(context, out_root)
        expected = self.skill.expected_output_count
        if status == "success" and expected and len(outputs) < expected:
            status = "partial"
        return SkillRunResult(status=status, outputs=outputs, rounds=rounds, message=msg)

    # ──────────── CLI 模式：skill_io MCP 上下文 ────────────

    def _enter_skill_io_context(self, out_root: Optional[Path], context: dict) -> None:
        """声明「正在跑 skill」，供 CLI 注入 skill_io MCP server。

        只在 skill 声明了 outputs.root 时生效 —— 没有产出目录的 skill
        （如 openspec-validate 这类只读校验）不需要 write_output。
        """
        if out_root is None:
            return
        outs = self.skill.outputs or {}
        exts = outs.get("allowed_exts")
        if not isinstance(exts, list):
            exts = []
        # builtin_tools 里的 `gen_image:images` → 子目录 images
        image_subdir = ""
        for bt in self.skill.builtin_tools:
            if bt.startswith("gen_image:"):
                image_subdir = bt.split(":", 1)[1]
                break
        try:
            from llm_client import set_skill_io_context
            set_skill_io_context(
                output_root=str(out_root),
                repo=context.get("repo_path") or "",
                allowed_exts=exts,
                image_subdir=image_subdir,
                tools=list(self.skill.builtin_tools),
            )
        except Exception as e:
            logger.warning("设置 skill_io 上下文失败（CLI 模式下工具将不可用）: %s", e)

    @staticmethod
    def _exit_skill_io_context() -> None:
        try:
            from llm_client import set_skill_io_context
            set_skill_io_context()
        except Exception:
            pass

    def _collect_outputs(
        self, context: dict, out_root: Optional[Path],
    ) -> List[ArtifactOut]:
        """按 outputs.globs 扫盘回收产出文件 —— **只登记元信息，不读内容**。

        这是 v0.20 二进制支持的关键：原实现对每个命中文件做
        `read_text(errors="replace")`，PNG/MP3/MP4 会变成一堆 U+FFFD 塞进内存。

        kind 归属：`x-workflow.produces` 里每条声明带一个 glob，
        `{glob: kind}` 反查即可。一个 glob 命中多文件（如 `images/*.png`）时
        它们共享同一 kind —— 这是刻意的，让「一次产出 N 张图」不必声明 N 条。
        """
        result: List[ArtifactOut] = []
        if out_root is None or not out_root.is_dir():
            return result

        # sop_config 由 orchestrator 注入（见 orchestrator.py:1833）
        sop_cfg = context.get("sop_config") or {}
        kind_by_glob: Dict[str, str] = {}
        for p in sop_cfg.get("_produces") or []:
            if isinstance(p, dict) and p.get("glob") and p.get("kind"):
                kind_by_glob[str(p["glob"])] = str(p["kind"])

        seen: set = set()
        for pattern in self.skill.output_globs:
            kind = kind_by_glob.get(pattern, "")
            for p in sorted(out_root.glob(pattern)):
                if not p.is_file():
                    continue
                try:
                    resolved = p.resolve()
                    # 同一文件被多个 glob 命中时只登记一次（首个匹配的 glob 定 kind）
                    if resolved in seen:
                        continue
                    seen.add(resolved)
                    rel = p.relative_to(out_root).as_posix()
                    suffix = p.suffix.lower()
                    result.append(ArtifactOut(
                        rel_path=rel,
                        abs_path=str(resolved),
                        kind=kind,
                        mime=mimetypes.guess_type(p.name)[0] or "application/octet-stream",
                        size=p.stat().st_size,
                        is_binary=suffix not in _TEXT_EXTS,
                    ))
                except Exception as e:
                    logger.warning("回收产出 %s 失败: %s", p, e)
        return result

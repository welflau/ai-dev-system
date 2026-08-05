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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from skills.executable_loader import ExecutableSkill

logger = logging.getLogger("skills.runner")


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
class SkillRunResult:
    status: str                                  # success | partial | budget_exceeded | error | skipped
    outputs: Dict[str, str] = field(default_factory=dict)   # 相对路径 → 内容
    rounds: int = 0
    message: str = ""


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
        from actions.write_file import WriteFileAction
        actions: Dict[str, Any] = {}
        for spec in self.skill.cli_tools:
            actions[spec.name] = GenericCLIAction(spec)
        outs = self.skill.outputs or {}
        write_mode = str(outs.get("write_mode") or "skill")
        allowed_exts = outs.get("allowed_exts")
        if allowed_exts is not None and not isinstance(allowed_exts, list):
            allowed_exts = None
        for bt in self.skill.builtin_tools:
            if bt == "write_file":
                actions["write_file"] = WriteFileAction(
                    allowed_exts=allowed_exts, write_mode=write_mode,
                )
            elif bt == "read_file":
                from actions.read_repo_file import ReadRepoFileAction
                actions["read_file"] = ReadRepoFileAction()
            elif bt == "shell":
                from actions.chat.shell_exec import ShellAction
                actions["shell"] = ShellAction()
            # mcp__ 声明在 executor 层处理，不建 Action
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

        outputs = self._collect_outputs(context, out_root)
        expected = self.skill.expected_output_count
        if status == "success" and expected and len(outputs) < expected:
            status = "partial"
        return SkillRunResult(status=status, outputs=outputs, rounds=rounds, message=msg)

    def _collect_outputs(self, context: dict, out_root: Optional[Path]) -> Dict[str, str]:
        """按 outputs.globs 扫盘回收产出文件。"""
        result: Dict[str, str] = {}
        if out_root is None or not out_root.is_dir():
            return result
        for pattern in self.skill.output_globs:
            for p in sorted(out_root.glob(pattern)):
                if p.is_file():
                    try:
                        rel = p.relative_to(out_root).as_posix()
                        result[rel] = p.read_text(encoding="utf-8", errors="replace")
                    except Exception:
                        pass
        return result

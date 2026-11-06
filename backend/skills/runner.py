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
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from skills.executable_loader import ExecutableSkill

logger = logging.getLogger("skills.runner")


def _plugin_knowledge_roots(source_path: Optional[Path]) -> List[Path]:
    """skill 位于 ``plugins/<id>/skills/<skill>/SKILL.md`` 时，附带该插件 ``knowledge/``。"""
    if source_path is None:
        return []
    try:
        plugin_root = source_path.resolve().parents[2]
    except IndexError:
        return []
    knowledge = plugin_root / "knowledge"
    if knowledge.is_dir() and (plugin_root / "plugin.json").is_file():
        return [knowledge]
    return []

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
        self.waiting_human: Optional[Dict[str, Any]] = None
        self.image_blocked: Optional[Dict[str, Any]] = None

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
        if self.image_blocked and tool_name == "gen_image":
            from actions.gen_image import IMAGE_BLOCK_STOP
            err = str(self.image_blocked.get("error") or IMAGE_BLOCK_STOP)
            return json.dumps({"ok": False, "error": f"{IMAGE_BLOCK_STOP} {err}",
                               "image_blocked": True}, ensure_ascii=False), None
        if self.image_blocked and tool_name == "confirm_video_gate":
            from actions.gen_image import IMAGE_BLOCK_STOP
            return json.dumps({"ok": False, "error": IMAGE_BLOCK_STOP,
                               "image_blocked": True}, ensure_ascii=False), None
        ctx = {**self._base_context, **context, **tool_input}
        try:
            result = await action.run(ctx)
            data = result.data or {}
            if data.get("waiting_human"):
                self.waiting_human = data
            if data.get("image_blocked"):
                self.image_blocked = {**data, "error": result.error or ""}
            text = result.message or json.dumps(data, ensure_ascii=False)
            if not result.success:
                text = result.error or text
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
    status: str                                  # success | partial | budget_exceeded | error | skipped | waiting_human
    outputs: List[ArtifactOut] = field(default_factory=list)
    rounds: int = 0
    message: str = ""
    waiting_human: Optional[Dict[str, Any]] = None

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
        extra_roots = _plugin_knowledge_roots(self.skill.source_path)
        for bt in self.skill.builtin_tools:
            # mcp__ 声明在 executor 层处理，不建 Action
            if str(bt).startswith("mcp__"):
                continue
            if str(bt) == "read_file" and extra_roots:
                from actions.read_repo_file import ReadRepoFileAction
                actions["read_file"] = ReadRepoFileAction(extra_roots=extra_roots)
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
        run_as = str(context.get("agent_type") or "").strip()
        if run_as:
            try:
                from skills import skill_loader
                extra = skill_loader.build_prompt_for_agent(
                    run_as, traits=context.get("project_traits") or [],
                )
                if extra:
                    parts.append(f"## 宿主 Role 知识（{run_as}）\n{extra}")
            except Exception as e:
                logger.warning("注入宿主 Role 知识失败（跳过）: %s", e)
        ctx_lines = []
        if context.get("ticket_title"):
            ctx_lines.append(f"- 工单标题：{context['ticket_title']}")
        if context.get("ticket_description"):
            ctx_lines.append(f"- 工单描述：{str(context['ticket_description'])[:400]}")
        if context.get("change_id"):
            ctx_lines.append(f"- change_id：{context['change_id']}")
        if context.get("project_traits"):
            ctx_lines.append(f"- 项目 traits：{context['project_traits']}")
        knowledge = _plugin_knowledge_roots(self.skill.source_path)
        if knowledge:
            ctx_lines.append(
                f"- 导演知识目录：用 read_file / mcp__skill_io__read_repo_file 读取 "
                f"`director-knowledge/<相对路径>`，例如 "
                f"director-knowledge/modes/cinematic-drama/workflow.md"
            )
            ctx_lines.append(
                "- **禁止**搜索或打开 `D:\\A_Works\\director`、"
                "`~/.codebuddy/projects`、用户主目录里的 director 源仓。"
                "知识已迁入本插件，只走 director-knowledge/ 前缀。"
            )
        if ctx_lines:
            parts.append("## 当前上下文\n" + "\n".join(ctx_lines))

        cli_map = []
        builtins = [str(b).split(":", 1)[0] for b in (self.skill.builtin_tools or [])]
        if "read_file" in builtins:
            cli_map.append(
                "- 读文件：`mcp__skill_io__read_repo_file`（导演知识 path 以 `director-knowledge/` 开头）"
            )
        if "write_file" in builtins:
            if str((self.skill.outputs or {}).get("write_mode") or "") == "repo":
                cli_map.append("- 写仓库文件：`mcp__skill_io__write_repo_file`（path 相对仓库根，如 works/<slug>/video_brief.json）")
            else:
                cli_map.append("- 写产出文件：`mcp__skill_io__write_output`（只传文件名，不要用原生 Write）")
        if "init_work_package" in builtins:
            cli_map.append("- 初始化工作包：`mcp__skill_io__init_work_package`")
        if "confirm_video_gate" in builtins:
            cli_map.append("- 发出人审卡：`mcp__skill_io__confirm_video_gate`")
        if "probe_backend" in builtins:
            cli_map.append("- 探测后端：`mcp__skill_io__probe_backend`")
        if "gen_video" in builtins:
            cli_map.append(
                "- 生成单段视频：`mcp__skill_io__gen_video`（阻塞到下载完成，不要为同一段重复调用）"
            )
        if "gen_video_batch" in builtins:
            cli_map.append(
                "- 批量生成：`mcp__skill_io__gen_video_batch`（跳过片段 1，clips 为 JSON 数组）"
            )
        if "download_video" in builtins:
            cli_map.append("- 补下载视频：`mcp__skill_io__download_video`")
        if "gen_image" in builtins or any(str(b).startswith("gen_image:") for b in (self.skill.builtin_tools or [])):
            cli_map.append(
                "- 生图：`mcp__skill_io__gen_image`。"
                "若返回后端失败/已停止：**禁止重试、禁止 confirm_video_gate**，立即 `done`，转人工。"
            )
        if cli_map:
            parts.append(
                "## CLI 工具（必须用这些 MCP 名）\n"
                + "\n".join(cli_map)
                + "\n完成后调用 `mcp__skill_io__done`。不要用原生 Write / Glob / Bash 满盘搜索。"
            )

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
        started_at = time.time()
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
        if not executor.waiting_human:
            marker = self._read_waiting_human_marker(
                out_root,
                work_slug=str(context.get("work_slug") or ""),
                ticket_id=str(context.get("ticket_id") or ""),
                started_at=started_at,
            )
            if marker:
                executor.waiting_human = marker
        image_blocked = executor.image_blocked or self._read_image_blocked_marker(out_root)
        expected = self.skill.expected_output_count
        if status == "success" and expected and len(outputs) < expected:
            status = "partial"
        if image_blocked:
            # 生图后端挂了：不能走人审确认，也不能假装成功。工单 blocked 等人改 key/引擎。
            status = "error"
            msg = str(
                image_blocked.get("error")
                or image_blocked.get("message")
                or "生图失败，需人工处理 LIGHTAI_API_KEY / 引擎"
            )
        elif executor.waiting_human and status in ("success", "partial"):
            status = "waiting_human"
            msg = str(executor.waiting_human.get("message") or msg or "等待人工确认")
        return SkillRunResult(
            status=status, outputs=outputs, rounds=rounds, message=msg,
            waiting_human=executor.waiting_human if status == "waiting_human" else None,
        )

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
        knowledge = _plugin_knowledge_roots(self.skill.source_path)
        try:
            from llm_client import set_skill_io_context
            set_skill_io_context(
                output_root=str(out_root),
                repo=context.get("repo_path") or "",
                allowed_exts=exts,
                image_subdir=image_subdir,
                tools=list(self.skill.builtin_tools),
                knowledge_root=str(knowledge[0]) if knowledge else "",
                write_mode=str(outs.get("write_mode") or ""),
                project_id=str(context.get("project_id") or ""),
                ticket_id=str(context.get("ticket_id") or ""),
                ticket_title=str(context.get("ticket_title") or ""),
                requirement_id=str(context.get("requirement_id") or ""),
                session_id=str(context.get("session_id") or ""),
                skill_id=str(context.get("skill_id") or self.skill.skill_id or ""),
            )
        except Exception as e:
            logger.warning("设置 skill_io 上下文失败（CLI 模式下工具将不可用）: %s", e)

    @staticmethod
    def _read_image_blocked_marker(out_root: Optional[Path]) -> Optional[Dict[str, Any]]:
        try:
            from actions.gen_image import read_image_blocked_marker
            return read_image_blocked_marker(out_root)
        except Exception:
            return None

    @staticmethod
    def _read_waiting_human_marker(
        out_root: Optional[Path],
        *,
        work_slug: str = "",
        ticket_id: str = "",
        started_at: float = 0.0,
    ) -> Optional[Dict[str, Any]]:
        """CLI 模式下 confirm_video_gate 跑在 MCP 子进程，waiting_human 回不来。
        Action 会在 works/<slug>/.ads-waiting-human.json 落盘，这里回收。

        只认当前 slug、当前工单、且本轮 skill 开始之后写入的标记。
        否则会把上一阶段/另一部片子的旧确认卡当成这一步已经发出人审。
        """
        if out_root is None or not out_root.is_dir():
            return None
        slug = (work_slug or "").strip().replace("\\", "/").strip("/")
        candidates = []
        if slug:
            candidates.append(out_root / slug / ".ads-waiting-human.json")
            candidates.append(out_root / ".ads-waiting-human.json")
        else:
            candidates.extend(sorted(out_root.glob("*/.ads-waiting-human.json")))
            candidates.append(out_root / ".ads-waiting-human.json")
        try:
            import json as _json
            seen = set()
            for p in candidates:
                try:
                    key = str(p.resolve())
                except Exception:
                    key = str(p)
                if key in seen or not p.is_file():
                    continue
                seen.add(key)
                if started_at and p.stat().st_mtime + 2 < started_at:
                    continue
                data = _json.loads(p.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or not data.get("waiting_human"):
                    continue
                marker_tid = str(data.get("ticket_id") or "")
                if ticket_id and marker_tid and marker_tid != ticket_id:
                    continue
                return data
        except Exception:
            return None
        return None

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

"""
Commands API — 斜杠命令路由

提供 /api/commands 端点，前端用 /command 前缀触发，直接执行后端操作，
无需经过 LLM 识别意图。

命令定义：backend/skills/commands/*.md（frontmatter 声明元信息）
内置命令：compact / memory / think / skills

路由：
  GET  /api/commands                  — 列出所有可用命令（用于前端补全）
  POST /api/commands/{name}           — 执行命令（全局上下文）
  POST /api/projects/{pid}/commands/{name} — 执行命令（项目上下文）
"""
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger("api.commands")

router = APIRouter(tags=["commands"])

# ── 内置命令定义 ──────────────────────────────────────────────────────────────

_BUILTIN_COMMANDS: Dict[str, Dict[str, Any]] = {
    "compact": {
        "description": "手动触发对话历史压缩，减少 context 占用",
        "args_hint": "",
        "requires_project": False,
    },
    "memory": {
        "description": "查看或搜索 Agent 记忆",
        "args_hint": "[query]",
        "requires_project": False,
    },
    "think": {
        "description": "切换 Extended Thinking 模式（on/off/adaptive）",
        "args_hint": "<on|off|adaptive>",
        "requires_project": False,
    },
    "skills": {
        "description": "查看当前项目已加载的 Skills 和 Rules",
        "args_hint": "",
        "requires_project": False,
    },
    "doctor": {
        "description": "检查 ADS 运行环境健康状态（DB / LLM / MCP / Git）",
        "args_hint": "",
        "requires_project": False,
    },
    "cost": {
        "description": "查看 LLM 使用费用（今日 / 本月 / 当前 session）",
        "args_hint": "[--today|--month|--session]",
        "requires_project": False,
    },
    "review": {
        "description": "对 git staged diff 做代码审查（/aicr-check 别名）",
        "args_hint": "",
        "requires_project": True,
    },
    "mcp": {
        "description": "查看或管理项目 MCP server（/mcp-config 别名）",
        "args_hint": "[enable|disable|add] [server名]",
        "requires_project": True,
    },
    "init": {
        "description": "初始化项目 .ads/ 目录（/ads-init 别名）",
        "args_hint": "[--claude] [--force]",
        "requires_project": True,
    },
    "diff": {
        "description": "查看当前项目 git diff",
        "args_hint": "[--staged] [文件路径]",
        "requires_project": True,
    },
    "config": {
        "description": "查看或修改当前 session 配置（model / think / compaction 等）",
        "args_hint": "[key] [value]",
        "requires_project": False,
    },
    "commit": {
        "description": "AI 辅助生成 commit message 并提交",
        "args_hint": "[消息]",
        "requires_project": True,
    },
    "context": {
        "description": "查看当前 session context token 使用分布",
        "args_hint": "",
        "requires_project": False,
    },
    "ue-run": {
        "description": "在运行中的 UE Editor 执行 Python 代码",
        "args_hint": "<python code>",
        "requires_project": True,
    },
    "ue-bp-gen": {
        "description": "生成 Blueprint 并写入 UE Editor",
        "args_hint": "<描述>",
        "requires_project": True,
    },
    "ue-level": {
        "description": "生成并布置 UE 关卡",
        "args_hint": "<描述>",
        "requires_project": True,
    },
}


def _parse_command_md(content: str, name: str, source: str = "system") -> Dict[str, Any]:
    """解析命令 .md 文件的 frontmatter，返回命令元数据。"""
    description = ""
    args_hint = ""
    requires_project = False
    if content.startswith("---"):
        fm_end = content.find("---", 3)
        if fm_end > 0:
            fm = content[3:fm_end]
            for line in fm.splitlines():
                if line.startswith("description:"):
                    description = line.split(":", 1)[1].strip().strip('"\'')
                elif line.startswith("args_hint:"):
                    args_hint = line.split(":", 1)[1].strip().strip('"\'')
                elif line.startswith("requires_project:"):
                    requires_project = "true" in line.lower()
    return {
        "description": description or f"/{name} 命令",
        "args_hint": args_hint,
        "requires_project": requires_project,
        "from_disk": True,
        "source": source,
    }


def _load_disk_commands() -> Dict[str, Dict[str, Any]]:
    """扫描 skills/commands/*.md，加载系统全局命令定义"""
    commands_dir = Path(__file__).resolve().parent.parent / "skills" / "commands"
    if not commands_dir.exists():
        return {}
    result = {}
    for md_file in sorted(commands_dir.glob("*.md")):
        try:
            result[md_file.stem] = _parse_command_md(
                md_file.read_text(encoding="utf-8"), md_file.stem, source="system"
            )
        except Exception as e:
            logger.warning("加载命令定义失败 %s: %s", md_file.name, e)
    return result


def _load_project_commands(repo_path: str) -> Dict[str, Dict[str, Any]]:
    """ClaudeCompat Phase C：扫描项目级命令定义，两路合并（低→高优先级）：

    1. {repo}/.claude/commands/*.md  — Claude Code 标准路径
    2. {repo}/.ads/commands/*.md     — ADS 扩展路径（同名覆盖）
    """
    if not repo_path:
        return {}
    repo = Path(repo_path)
    result: Dict[str, Dict[str, Any]] = {}

    for src_dir, source_label in [
        (repo / ".claude" / "commands", "claude"),
        (repo / ".ads" / "commands", "ads"),
    ]:
        if not src_dir.exists():
            continue
        for md_file in sorted(src_dir.glob("*.md")):
            try:
                result[md_file.stem] = _parse_command_md(
                    md_file.read_text(encoding="utf-8"), md_file.stem, source=source_label
                )
            except Exception as e:
                logger.warning("加载项目命令失败 %s: %s", md_file.name, e)

    if result:
        logger.debug("加载项目级命令 %d 条（%s）", len(result), repo_path)
    return result


def get_all_commands(repo_path: str = "") -> Dict[str, Dict[str, Any]]:
    """合并系统命令 + 项目级命令（项目可覆盖系统同名命令）。

    优先级（低→高）：内置 → 系统磁盘 → .claude/commands/ → .ads/commands/
    """
    all_cmds = dict(_BUILTIN_COMMANDS)
    all_cmds.update(_load_disk_commands())
    if repo_path:
        all_cmds.update(_load_project_commands(repo_path))
    return all_cmds


# ── 请求 / 响应模型 ───────────────────────────────────────────────────────────

class CommandResult(BaseModel):
    success: bool
    output: str = ""
    data: Optional[Dict[str, Any]] = None
    sse_events: List[Dict[str, Any]] = []  # 可选：额外 SSE 事件给前端


# ── 路由 ──────────────────────────────────────────────────────────────────────

@router.get("/api/commands")
async def list_commands(project_id: Optional[str] = None):
    """列出所有可用命令（供前端补全）。

    project_id 不为空时，额外合并 .claude/commands/ 和 .ads/commands/ 的项目级命令。
    """
    repo_path = ""
    if project_id:
        try:
            from database import db
            row = await db.fetch_one("SELECT git_repo_path FROM projects WHERE id = ?", (project_id,))
            repo_path = (row or {}).get("git_repo_path", "")
        except Exception:
            pass
    cmds = get_all_commands(repo_path=repo_path)
    result = [
        {
            "name": name,
            "description": info["description"],
            "args_hint": info.get("args_hint", ""),
            "requires_project": info.get("requires_project", False),
            "source": info.get("source", "system"),
        }
        for name, info in sorted(cmds.items())
    ]
    # 合并项目本地 Skill（.ads / .Agent / .codebuddy / .claude），可用 / 触发
    if project_id:
        try:
            existing = {c["name"] for c in result}
            for sk in await _list_project_skills_as_commands(project_id):
                if sk["name"] not in existing:
                    result.append(sk)
                    existing.add(sk["name"])
        except Exception as e:
            logger.debug("合并项目 Skill 到命令列表失败: %s", e)
    return {"commands": result}


async def _list_project_skills_as_commands(project_id: str) -> List[Dict[str, Any]]:
    """把项目本地 Skill 暴露成「伪命令」，供斜杠补全与触发。source=skill。"""
    from actions.chat.load_skill import _enum_project_skill_dirs, _load_agent_skill
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for skill_dir_base in await _enum_project_skill_dirs(project_id):
        for skill_dir in sorted(skill_dir_base.iterdir()):
            if not (skill_dir.is_dir() and (skill_dir / "SKILL.md").exists()):
                continue
            if skill_dir.name in seen:
                continue
            seen.add(skill_dir.name)
            desc = skill_dir.name
            try:
                _content, _name = await _load_agent_skill(
                    f"agent.{skill_dir.name}", project_id
                )
                # 从 frontmatter 提取 description
                import re as _re
                m = _re.match(r"^---\s*\n(.*?)\n---", (_content or ""), _re.DOTALL)
                if m:
                    import yaml as _yaml
                    fm = _yaml.safe_load(m.group(1)) or {}
                    desc = fm.get("description") or _name or skill_dir.name
            except Exception:
                pass
            out.append({
                "name": skill_dir.name,
                "description": (desc or "")[:200],
                "args_hint": "[任务描述]",
                "requires_project": True,
                "source": "skill",
            })
    return out


@router.post("/api/commands/{name}")
async def execute_global_command(name: str, body: dict = {}):
    """执行全局命令（无项目上下文）"""
    return await _dispatch_command(name, args=body.get("args", ""), project_id=None, context=body)


@router.post("/api/projects/{project_id}/commands/{name}")
async def execute_project_command(project_id: str, name: str, body: dict = {}):
    """执行项目命令（带项目上下文）"""
    return await _dispatch_command(name, args=body.get("args", ""), project_id=project_id, context=body)


@router.post("/api/projects/{project_id}/commands/{name:path}")
async def execute_project_command_path(project_id: str, name: str, body: dict = {}):
    """捕获命令名含 / 的错误请求（如 AI 误将 UE object path 拼入 URL），返回明确错误"""
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=400,
        content={
            "success": False,
            "output": (
                f"无效命令路径 '/{name}'。\n"
                "如需调用 UE Editor，请使用 ue_call 工具（TCP UCP 协议），"
                "不要将 UE object 路径拼入 HTTP URL。\n"
                f"收到的路径: /commands/{name}"
            ),
        },
    )


# ── 命令分发 ──────────────────────────────────────────────────────────────────

async def _dispatch_command(
    name: str,
    args: str = "",
    project_id: Optional[str] = None,
    context: dict = {},
) -> CommandResult:
    """命令分发器：路由到对应处理函数"""
    handlers = {
        "compact":        _cmd_compact,
        "memory":         _cmd_memory,
        "think":          _cmd_think,
        "skills":         _cmd_skills,
        "ue-run":         _cmd_ue_run,
        "ue-bp-gen":      _cmd_ue_bp_gen,
        "ue-level":       _cmd_ue_level,
        "memory-export":  _cmd_memory_export,
        "memory-import":  _cmd_memory_import,
        "ads-init":       _cmd_ads_init,
        "aicr-check":          _cmd_aicr_check,
        "aicr-config":         _cmd_aicr_config,
        "aicr-rules":          _cmd_aicr_rules,
        "save-to-knowledge":   _cmd_save_to_knowledge,
        "search-knowledge":    _cmd_search_knowledge,
        "harness-audit":       _cmd_harness_audit,
        "mcp-config":          _cmd_mcp_config,
        # ── 与 Claude Code 名称统一的命令 ──
        "doctor":    _cmd_doctor,
        "cost":      _cmd_cost,
        "review":    lambda a, p, c: _cmd_aicr_check(a, p, c),
        "mcp":       lambda a, p, c: _cmd_mcp_config(a, p, c),
        "init":      lambda a, p, c: _cmd_ads_init(a, p, c),
        "diff":      _cmd_diff,
        "config":    _cmd_config,
        "commit":    _cmd_commit,
        "context":   _cmd_context,
        # ── 通用便捷命令 ──
        "help":      _cmd_help,
        "model":     _cmd_model,
        "clear":     _cmd_clear,
        "status":    _cmd_status,
        "tasks":     _cmd_tasks,
        "todos":     _cmd_tasks,   # 别名
        "agents":    _cmd_agents,
    }

    handler = handlers.get(name)
    if not handler:
        # 回退：若匹配到项目本地 Skill，返回 run_skill 指令，让前端转成聊天消息触发 AI 加载执行
        if project_id:
            try:
                skill_id = await _match_project_skill(name, project_id)
                if skill_id:
                    return CommandResult(
                        success=True,
                        output=f"📚 通过 Skill `{name}` 执行…",
                        data={
                            "type": "run_skill",
                            "skill_id": skill_id,
                            "skill_name": name,
                            "args": args,
                        },
                    )
            except Exception as e:
                logger.debug("run_skill 回退匹配失败: %s", e)
        return CommandResult(success=False, output=f"未知命令：/{name}。输入 /help 查看可用命令。")

    try:
        return await handler(args=args, project_id=project_id, context=context)
    except Exception as e:
        logger.error("命令 /%s 执行失败: %s", name, e, exc_info=True)
        return CommandResult(success=False, output=f"命令执行失败: {e}")


async def _match_project_skill(name: str, project_id: str) -> Optional[str]:
    """按命令名匹配项目本地 Skill，命中返回其 skill_id（agent.<name>），否则 None。"""
    from actions.chat.load_skill import _enum_project_skill_dirs
    for skill_dir_base in await _enum_project_skill_dirs(project_id):
        candidate = skill_dir_base / name / "SKILL.md"
        if candidate.exists():
            return f"agent.{name}"
    return None


# ── 内置命令实现 ──────────────────────────────────────────────────────────────

async def _cmd_compact(args: str, project_id: Optional[str], context: dict) -> CommandResult:
    """手动触发历史压缩"""
    session_id = context.get("session_id", "default")
    # 通知前端触发 compact（前端持有历史，由前端调用 _compact_history_with_llm）
    return CommandResult(
        success=True,
        output="✅ 已触发对话历史压缩",
        sse_events=[{"type": "compact_triggered", "session_id": session_id}],
    )


async def _cmd_memory(args: str, project_id: Optional[str], context: dict) -> CommandResult:
    """查询 Agent 记忆"""
    from database import db
    query = args.strip()
    try:
        if query:
            rows = await db.fetch_all(
                """SELECT type, title, content, created_at
                   FROM agent_memory
                   WHERE (project_id = ? OR project_id IS NULL)
                   AND (title LIKE ? OR content LIKE ?)
                   ORDER BY created_at DESC LIMIT 10""",
                (project_id or "__global__", f"%{query}%", f"%{query}%"),
            )
        else:
            rows = await db.fetch_all(
                """SELECT type, title, content, created_at
                   FROM agent_memory
                   WHERE project_id = ? OR project_id IS NULL
                   ORDER BY created_at DESC LIMIT 20""",
                (project_id or "__global__",),
            )
        if not rows:
            return CommandResult(success=True, output="暂无记忆记录" + (f"（查询：{query}）" if query else ""))
        lines = [f"共找到 {len(rows)} 条记忆：\n"]
        for r in rows:
            lines.append(f"**[{r['type']}]** {r['title']}")
            if r['content']:
                lines.append(f"  {r['content'][:100]}{'…' if len(r['content']) > 100 else ''}")
        return CommandResult(success=True, output="\n".join(lines), data={"memories": [dict(r) for r in rows]})
    except Exception as e:
        return CommandResult(success=False, output=f"查询记忆失败: {e}")


async def _cmd_think(args: str, project_id: Optional[str], context: dict) -> CommandResult:
    """切换 thinking 模式"""
    mode = args.strip().lower()
    session_id = context.get("session_id", "default")
    valid = {"on", "off", "adaptive"}
    if mode not in valid:
        return CommandResult(
            success=False,
            output=f"用法：/think <on|off|adaptive>\n当前有效值：{', '.join(sorted(valid))}",
        )
    # 通过 Feature Flags 设置
    from actions.chat.set_session_flag import _SESSION_FLAGS
    mapping = {"on": True, "off": False, "adaptive": "adaptive"}
    _SESSION_FLAGS.setdefault(session_id, {})["thinking_mode"] = mapping[mode]
    labels = {"on": "已开启思考（固定 budget）", "off": "已关闭思考", "adaptive": "已设为自适应（模型自主决定）"}
    return CommandResult(success=True, output=f"✅ {labels[mode]}（本 session 有效）")


async def _cmd_skills(args: str, project_id: Optional[str], context: dict) -> CommandResult:
    """列出当前已加载的 Skills 和全局 Rules"""
    try:
        from skills import skill_loader
        import json as _j

        # 获取项目 traits + enabled_packs
        traits = []
        repo_path = ""
        _enabled_packs = None
        if project_id:
            from database import db
            row = await db.fetch_one("SELECT traits, git_repo_path FROM projects WHERE id = ?", (project_id,))
            if row:
                raw = row.get("traits") or "[]"
                traits = _j.loads(raw) if isinstance(raw, str) else list(raw or [])
                repo_path = row.get("git_repo_path") or ""
            from skills.loader import get_enabled_packs as _gep
            _enabled_packs = await _gep(project_id)

        # Skills
        skill_ids = skill_loader.get_skills_for_agent("ChatAssistant", traits=traits, enabled_packs=_enabled_packs)
        all_status = skill_loader.get_all_skills_status()

        skill_lines = []
        for sid in skill_ids:
            cfg = all_status.get(sid, {})
            name = cfg.get("name", sid)
            desc = cfg.get("description", "")[:60]
            src = "market" if cfg.get("source") == "marketplace" else "built-in"
            pack_tag = f" `pack:{skill_loader.skills[sid].get('pack')}`" if skill_loader.skills[sid].get("pack") else ""
            skill_lines.append(f"  • **{name}** `[{src}]`{pack_tag} — {desc}")

        # 全局 Rules（当前生效）
        rule_ids = skill_loader.get_rules_for_context(traits=traits, enabled_packs=_enabled_packs)
        rule_lines = []
        for rid in rule_ids:
            cfg = skill_loader.rules.get(rid, {})
            desc = cfg.get("description", "")[:60]
            tag = "always" if cfg.get("alwaysApply") else ("scene:" + cfg.get("scene", "")) if cfg.get("scene") else "traits"
            pack_tag = f" `pack:{cfg['pack']}`" if cfg.get("pack") else ""
            rule_lines.append(f"  • `{rid}` `[{tag}]`{pack_tag} — {desc}")

        # 项目规则来源
        proj_rule_summary = ""
        if repo_path:
            from pathlib import Path
            sources = []
            if (Path(repo_path) / "CLAUDE.md").exists():
                sources.append("CLAUDE.md")
            if (Path(repo_path) / "ADS.md").exists():
                sources.append("ADS.md")
            if (Path(repo_path) / ".claude" / "rules").exists():
                sources.append(".claude/rules/")
            if (Path(repo_path) / ".ads" / "rules").exists():
                sources.append(".ads/rules/")
            if sources:
                proj_rule_summary = f"\n\n**项目规则来源**：{', '.join(sources)}"

        parts = []
        if skill_lines:
            parts.append(f"**Skills（{len(skill_lines)} 个）**\n" + "\n".join(skill_lines))
        else:
            parts.append("**Skills**：当前无已加载 Skill")
        if rule_lines:
            parts.append(f"**全局 Rules（{len(rule_lines)} 条）**\n" + "\n".join(rule_lines))
        if proj_rule_summary:
            parts.append(proj_rule_summary.strip())

        return CommandResult(success=True, output="\n\n".join(parts))
    except Exception as e:
        return CommandResult(success=False, output=f"获取 Skills/Rules 失败: {e}")


async def _cmd_memory_export(args: str, project_id: Optional[str], context: dict) -> CommandResult:
    """将项目记忆导出到 {仓库}/.ads/memory.md（P3）"""
    if not project_id:
        return CommandResult(success=False, output="❌ /memory-export 需要在项目内使用")
    try:
        from database import db
        from pathlib import Path
        # 查项目仓库路径
        row = await db.fetch_one("SELECT git_repo_path, name FROM projects WHERE id = ?", (project_id,))
        if not row or not row.get("git_repo_path"):
            return CommandResult(success=False, output="❌ 项目没有配置 Git 仓库路径")
        repo_path = Path(row["git_repo_path"])
        ads_dir = repo_path / ".ads"
        ads_dir.mkdir(exist_ok=True)

        # 查记忆
        rows = await db.fetch_all(
            """SELECT type, title, content, created_at FROM agent_memory
               WHERE project_id = ? ORDER BY created_at DESC""",
            (project_id,),
        )
        if not rows:
            return CommandResult(success=True, output="项目暂无记忆，无需导出")

        _ICONS = {"user_profile":"👤", "behavior_feedback":"💬",
                  "project_context":"📁", "external_ref":"🔗",
                  "user":"👤", "project":"📁", "technical":"📁",
                  "decision":"📁", "insight":"💬", "project_status":"📁", "handoff":"📁"}
        from utils import now_iso
        lines = [f"# 项目记忆（{row['name']}）\n\n> 最后导出：{now_iso()[:10]}\n"]
        for r in rows:
            icon = _ICONS.get(r["type"], "📝")
            date = r["created_at"][:10]
            lines.append(f"- [{icon} {r['type']}] **{r['title']}**（{date}）")
            if r["content"]:
                lines.append(f"  {r['content'][:200]}")
        content = "\n".join(lines)
        (ads_dir / "memory.md").write_text(content, encoding="utf-8")
        return CommandResult(
            success=True,
            output=f"✅ 已导出 {len(rows)} 条记忆到 `.ads/memory.md`",
            data={"path": str(ads_dir / "memory.md"), "count": len(rows)},
        )
    except Exception as e:
        return CommandResult(success=False, output=f"导出失败: {e}")


async def _cmd_memory_import(args: str, project_id: Optional[str], context: dict) -> CommandResult:
    """从 {仓库}/.ads/memory.md 导入记忆到数据库（P3）"""
    if not project_id:
        return CommandResult(success=False, output="❌ /memory-import 需要在项目内使用")
    try:
        from database import db
        from pathlib import Path
        row = await db.fetch_one("SELECT git_repo_path FROM projects WHERE id = ?", (project_id,))
        if not row or not row.get("git_repo_path"):
            return CommandResult(success=False, output="❌ 项目没有配置 Git 仓库路径")
        memory_file = Path(row["git_repo_path"]) / ".ads" / "memory.md"
        if not memory_file.exists():
            return CommandResult(success=False, output="❌ 找不到 .ads/memory.md，请先在仓库中创建")
        content = memory_file.read_text(encoding="utf-8", errors="replace")

        # 简单解析：每行 "- [图标 type] **标题**（日期）" + 下一行内容
        import re
        from utils import generate_id, now_iso
        pattern = re.compile(r"-\s+\[.+?\s+(\w+)\]\s+\*\*(.+?)\*\*")
        imported = 0
        lines = content.splitlines()
        i = 0
        while i < len(lines):
            m = pattern.match(lines[i].strip())
            if m:
                mem_type, title = m.group(1), m.group(2)
                memo_content = ""
                if i + 1 < len(lines) and lines[i+1].startswith("  "):
                    memo_content = lines[i+1].strip()
                    i += 1
                # 不重复导入（按 title 去重）
                exists = await db.fetch_one(
                    "SELECT id FROM agent_memory WHERE project_id=? AND title=?",
                    (project_id, title),
                )
                if not exists:
                    await db.insert("agent_memory", {
                        "id": generate_id("MEM"),
                        "project_id": project_id,
                        "type": mem_type if mem_type in ("user_profile","behavior_feedback","project_context","external_ref") else "project_context",
                        "agent_type": "import",
                        "title": title[:200],
                        "content": memo_content[:2000],
                        "tags": "[]",
                        "requirement_id": None,
                        "ticket_id": None,
                        "created_at": now_iso(),
                    })
                    imported += 1
            i += 1
        return CommandResult(success=True, output=f"✅ 已导入 {imported} 条记忆（跳过重复项）")
    except Exception as e:
        return CommandResult(success=False, output=f"导入失败: {e}")


async def _cmd_ads_init(args: str, project_id: Optional[str], context: dict) -> CommandResult:
    """初始化项目 .ads/ 目录结构，根据 traits 生成对应规则模板"""
    if not project_id:
        return CommandResult(success=False, output="❌ /ads-init 需要在项目内使用")
    force = "--force" in (args or "")
    try:
        from database import db
        from pathlib import Path
        import json as _j
        row = await db.fetch_one("SELECT git_repo_path, name, traits FROM projects WHERE id = ?", (project_id,))
        if not row or not row.get("git_repo_path"):
            return CommandResult(success=False, output="❌ 项目没有配置 Git 仓库路径")
        repo = Path(row["git_repo_path"])
        ads_dir = repo / ".ads"

        # 创建目录结构
        (ads_dir / "rules").mkdir(parents=True, exist_ok=True)
        (ads_dir / "rules" / "workflow").mkdir(parents=True, exist_ok=True)
        (ads_dir / "skills").mkdir(parents=True, exist_ok=True)

        traits: list = _j.loads(row.get("traits") or "[]")
        traits_set = set(t.lower() for t in traits)
        created: list[str] = []

        def _write(rel: str, content: str) -> None:
            p = ads_dir / rel
            if not p.exists() or force:
                p.write_text(content, encoding="utf-8")
                created.append(rel)

        # config.json
        _write("config.json", _j.dumps({
            "project_name": row["name"],
            "traits": traits,
            "description": "",
            "aicr": {"autoaicr": True, "precommit": False}
        }, ensure_ascii=False, indent=2))

        # rules/project-rules.md — 常驻，无 paths
        _write("rules/project-rules.md",
            "---\nalwaysApply: true\npriority: medium\ndescription: 项目编码规范\n---\n\n"
            "# 项目规范\n\n<!-- 在这里写项目专属的编码约定 -->\n")

        # C++ 规则（ue5 / unreal / cpp 项目）
        if traits_set & {"ue5", "unreal", "ue", "cpp", "game-ue"}:
            _write("rules/cpp-rules.md",
                '---\nalwaysApply: false\npaths:\n  - "**/*.cpp"\n  - "**/*.h"\n  - "**/*.hpp"\n'
                'priority: high\ndescription: 项目 C++ 专属规范\n---\n\n'
                "# 项目 C++ 规范\n\n<!-- 在这里补充项目特有的 C++ 约定 -->\n")

        # TypeScript 规则
        if traits_set & {"typescript", "ts", "react", "frontend", "ui"}:
            _write("rules/ts-rules.md",
                '---\nalwaysApply: false\npaths:\n  - "**/*.ts"\n  - "**/*.tsx"\n'
                'priority: high\ndescription: 项目 TypeScript 专属规范\n---\n\n'
                "# 项目 TypeScript 规范\n\n<!-- 在这里补充项目特有的 TS 约定 -->\n")

        # Python 规则
        if traits_set & {"python", "py", "backend", "ml"}:
            _write("rules/python-rules.md",
                '---\nalwaysApply: false\npaths:\n  - "**/*.py"\n'
                'priority: high\ndescription: 项目 Python 专属规范\n---\n\n'
                "# 项目 Python 规范\n\n<!-- 在这里补充项目特有的 Python 约定 -->\n")

        # workflow/autoaicr.md — AutoAICR 场景补充
        _write("rules/workflow/autoaicr.md",
            "---\nalwaysApply: false\nscene: autoaicr\npriority: medium\n"
            "description: 项目级 AutoAICR 补充规则\n---\n\n"
            "# 项目 AutoAICR 补充\n\n<!-- 在这里写项目特有的编辑后自检规则 -->\n")

        # mcp_servers.json — 项目级 MCP 配置模板
        _write("mcp_servers.json", _MCP_TEMPLATE)

        # ── ClaudeCompat Phase E：检测 .claude/ 已存在 ──────────────────
        claude_dir = repo / ".claude"
        has_claude = claude_dir.exists()
        claude_mode = "--claude" in (args or "")

        if has_claude and not claude_mode:
            # 扩展模式：.claude/ 已有，只生成 ADS 专属文件，不重复创建规则
            ext_note = (
                "\n\n📌 **扩展模式**：检测到 `.claude/` 已存在。\n"
                "ADS 将自动读取 `.claude/rules/`、`CLAUDE.md` 和 `.claude/commands/`。\n"
                "`.ads/` 作为扩展层，仅需填写 ADS 专属配置（mcp_servers.json / wiki / config.json）。\n"
                "如需覆盖 `.claude/rules/` 中的规则，在 `.ads/rules/` 创建同名文件即可。"
            )
        elif claude_mode:
            # --claude 模式：同时生成标准 .claude/ 骨架
            claude_created = []
            def _write_claude(rel: str, content: str) -> None:
                p = claude_dir / rel
                if not p.exists() or force:
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(content, encoding="utf-8")
                    claude_created.append(f".claude/{rel}")

            _write_claude("settings.json", _j.dumps({"permissions": {"allow": [], "deny": []}}, indent=2))
            _write_claude("rules/.gitkeep", "")
            _write_claude("commands/.gitkeep", "")
            # 生成 CLAUDE.md 模板
            claude_md = repo / "CLAUDE.md"
            if not claude_md.exists() or force:
                claude_md.write_text(
                    "# 项目 AI 工作规范\n\n"
                    "<!-- 此文件同时被 Claude Code CLI 和 ADS 读取 -->\n\n"
                    "## 编码约定\n<!-- 在这里写项目编码规范 -->\n\n"
                    "## 禁止事项\n<!-- 在这里写 AI 禁止行为 -->\n",
                    encoding="utf-8"
                )
                claude_created.append("CLAUDE.md")
            created.extend(claude_created)
            ext_note = f"\n\n📁 已生成 `.claude/` 骨架（{len(claude_created)} 个文件）和 `CLAUDE.md`。"
        else:
            ext_note = ""

        # ADS.md 模板（如不存在）
        ads_md = repo / "ADS.md"
        if not ads_md.exists() or force:
            ads_md.write_text(
                "# ADS 项目指令\n\n"
                "<!-- 此文件仅被 ADS 读取，优先级高于 CLAUDE.md -->\n\n"
                "## Agent 行为约定\n<!-- 在这里写 ADS 专属指令 -->\n",
                encoding="utf-8"
            )
            created.append("ADS.md")

        summary = "\n".join(f"  ✅ {f}" for f in created) if created else "  （所有文件已存在，使用 --force 强制覆盖）"

        # .gitignore 检查
        gitignore_warn = ""
        gi_file = repo / ".gitignore"
        if gi_file.exists():
            gi_lines = gi_file.read_text(encoding="utf-8", errors="replace").splitlines()
            if any(l.strip() in (".*", "/.*") for l in gi_lines):
                gitignore_warn = (
                    "\n\n⚠️ 检测到 `.gitignore` 含 `.*` 规则，可能忽略 `.ads/`。\n"
                    "建议追加：\n```\n!.ads/\n!.ads/**\n```"
                )

        traits_info = f"（traits: {', '.join(traits) or '未设置'}）"
        return CommandResult(
            success=True,
            output=f"✅ `.ads/` 目录已初始化 {traits_info}\n{summary}\n\n"
                   f"目录：`{ads_dir}`\n\n"
                   f"编辑 `.ads/rules/` 下的规则文件写入项目约定，Agent 会自动按文件类型按需注入。"
                   f"{ext_note}{gitignore_warn}",
        )
    except Exception as e:
        return CommandResult(success=False, output=f"初始化失败: {e}")


async def _cmd_ue_run(args: str, project_id: Optional[str], context: dict) -> CommandResult:
    """在 UE Editor 执行 Python 代码（B-0 Python 桥接）"""
    if not project_id:
        return CommandResult(success=False, output="❌ /ue-run 需要在项目内使用")
    code = args.strip()
    if not code:
        return CommandResult(success=False, output="用法：/ue-run <python code>\n例：/ue-run import unreal; print(unreal.SystemLibrary.get_engine_version())")
    from engines.ue_python_bridge import run_python
    result = await run_python(code, project_id=project_id)
    if result["success"]:
        out = result.get("stdout") or result.get("result") or "✅ 执行成功（无输出）"
        return CommandResult(success=True, output=f"✅ 执行成功\n```\n{out}\n```", data=result)
    else:
        err = result.get("error") or "执行失败"
        return CommandResult(success=False, output=f"❌ {err}", data=result)


async def _cmd_ue_bp_gen(args: str, project_id: Optional[str], context: dict) -> CommandResult:
    """生成 Blueprint（B-1 LLM 生成 + Python 橋接）"""
    if not project_id:
        return CommandResult(success=False, output="❌ /ue-bp-gen 需要在项目内使用")
    if not args.strip():
        return CommandResult(
            success=False,
            output="用法：/ue-bp-gen <描述>\n例：/ue-bp-gen 创建一个波次生成器，每隔5秒在随机位置生成一个敌人",
        )
    from actions.ue_blueprint_gen import BlueprintGenAction
    action = BlueprintGenAction()
    result = await action.run({"description": args.strip(), "project_id": project_id})
    output = result.message or result.error or ""
    # 附加生成的代碼供用戶查看
    if result.data and result.data.get("generated_code"):
        code = result.data["generated_code"]
        output += f"\n\n**生成的代碼：**\n```python\n{code[:800]}\n```"
    return CommandResult(success=result.success, output=output, data=result.data)


async def _cmd_ue_level(args: str, project_id: Optional[str], context: dict) -> CommandResult:
    """生成關卡布局（B-2 LLM 生成 + Python 橋接）"""
    if not project_id:
        return CommandResult(success=False, output="❌ /ue-level 需要在项目内使用")
    if not args.strip():
        return CommandResult(
            success=False,
            output="用法：/ue-level <描述>\n例：/ue-level 8×8地面，四角放燈光，中央出生點，全NavMesh",
        )
    from actions.ue_level_gen import LevelGenAction
    action = LevelGenAction()
    result = await action.run({"description": args.strip(), "project_id": project_id})
    output = result.message or result.error or ""
    if result.data and result.data.get("generated_code"):
        code = result.data["generated_code"]
        output += f"\n\n**生成的代碼：**\n```python\n{code[:1000]}\n```"
    return CommandResult(success=result.success, output=output, data=result.data)


# ==================== AICR 命令 ====================

async def _cmd_aicr_check(args: str, project_id: Optional[str], context: dict) -> CommandResult:
    """对 git staged diff 执行 PreCommit 审查"""
    if not project_id:
        return CommandResult(success=False, output="❌ /aicr-check 需要在项目内使用")
    try:
        from database import db
        import subprocess
        row = await db.fetch_one("SELECT git_repo_path, traits FROM projects WHERE id = ?", (project_id,))
        if not row or not row.get("git_repo_path"):
            return CommandResult(success=False, output="❌ 项目没有配置 Git 仓库路径")
        repo = row["git_repo_path"]
        proc = subprocess.run(
            ["git", "diff", "--staged"],
            cwd=repo, capture_output=True, text=True, timeout=30
        )
        staged_diff = proc.stdout.strip()
        if not staged_diff:
            return CommandResult(success=True, output="✅ 没有 staged 变更，无需审查。")
        import json as _j
        traits = _j.loads(row.get("traits") or "[]")
        from aicr import aicr_engine
        result = await aicr_engine.run_precommit(
            staged_diff=staged_diff,
            project_traits=traits,
            project_id=project_id,
        )
        md = result.to_markdown()
        if not md:
            return CommandResult(success=True, output="✅ PreCommit 扫描通过，未发现问题。")
        status = "✅ 通过" if result.passed else "❌ 发现阻断项"
        return CommandResult(success=True, output=f"{status}\n\n{md}")
    except Exception as e:
        return CommandResult(success=False, output=f"审查失败: {e}")


async def _cmd_aicr_config(args: str, project_id: Optional[str], context: dict) -> CommandResult:
    """查看或切换 AICR 开关"""
    opt = (args or "").strip().lower()
    session_id = context.get("session_id", "")
    from actions.chat.set_session_flag import get_session_flag, _SESSION_FLAGS as _session_flags
    current_auto = _session_flags.get(session_id, {}).get("aicr_autoaicr", True)
    current_pre  = _session_flags.get(session_id, {}).get("aicr_precommit", False)

    if not opt:
        return CommandResult(success=True, output=(
            f"**AICR 当前状态**\n"
            f"- AutoAICR（写文件后自动审查）：{'开启 ✅' if current_auto else '关闭 ⭕'}\n"
            f"- PreCommit（提交前扫描）：{'开启 ✅' if current_pre else '关闭 ⭕'}\n\n"
            f"切换：`/aicr-config autoaicr` / `precommit` / `all` / `off`"
        ))
    if opt == "all":
        _session_flags.setdefault(session_id, {}).update({"aicr_autoaicr": True, "aicr_precommit": True})
        return CommandResult(success=True, output="AutoAICR + PreCommit 均已开启")
    elif opt == "off":
        _session_flags.setdefault(session_id, {}).update({"aicr_autoaicr": False, "aicr_precommit": False})
        return CommandResult(success=True, output="所有 AICR 审查已关闭")
    elif opt == "autoaicr":
        new_val = not current_auto
        _session_flags.setdefault(session_id, {})["aicr_autoaicr"] = new_val
        return CommandResult(success=True, output=f"AutoAICR 已{'开启' if new_val else '关闭'}")
    elif opt == "precommit":
        new_val = not current_pre
        _session_flags.setdefault(session_id, {})["aicr_precommit"] = new_val
        return CommandResult(success=True, output=f"PreCommit 已{'开启' if new_val else '关闭'}")
    return CommandResult(success=False, output=f"❌ 未知选项：{opt}。可选：autoaicr / precommit / all / off")


async def _cmd_aicr_rules(args: str, project_id: Optional[str], context: dict) -> CommandResult:
    """列出 AICR 规则"""
    from pathlib import Path
    from skills.loader import _parse_frontmatter
    scene = (args or "").strip().lower() or "all"
    rules_dir = Path(__file__).parent.parent / "skills" / "rules" / "workflow"
    output_parts = []
    scenes = []
    if scene in ("autoaicr", "all"):
        scenes.append(("AutoAICR", "autoaicr.md"))
    if scene in ("precommit", "all"):
        scenes.append(("PreCommit", "precommit.md"))
    for label, filename in scenes:
        path = rules_dir / filename
        if path.exists():
            _, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
            output_parts.append(f"## {label} 规则\n\n{body.strip()}")
    if project_id:
        try:
            from database import db
            from skills import skill_loader
            row = await db.fetch_one("SELECT git_repo_path FROM projects WHERE id = ?", (project_id,))
            repo_path = (row or {}).get("git_repo_path", "")
            if repo_path:
                proj_scene = None if scene == "all" else scene
                proj_rules = skill_loader.load_project_rules(repo_path, scene=proj_scene)
                if proj_rules:
                    output_parts.append(f"## 项目规则（.ads/rules/）\n\n{proj_rules}")
        except Exception:
            pass
    return CommandResult(
        success=True,
        output="\n\n---\n\n".join(output_parts) if output_parts else "无规则"
    )


# ==================== 知识库命令 ====================

async def _cmd_save_to_knowledge(args: str, project_id: Optional[str], context: dict) -> CommandResult:
    """将对话内容归档为 .ads/wiki/ 知识条目"""
    if not project_id:
        return CommandResult(success=False, output="❌ /save-to-knowledge 需要在项目内使用")
    try:
        from database import db
        from pathlib import Path
        import json as _j
        row = await db.fetch_one("SELECT git_repo_path, name FROM projects WHERE id = ?", (project_id,))
        if not row or not row.get("git_repo_path"):
            return CommandResult(success=False, output="❌ 项目没有配置 Git 仓库路径")
        repo = Path(row["git_repo_path"])
        wiki_dir = repo / ".ads" / "wiki"

        # 获取最近对话历史作为上下文
        history = context.get("history") or []
        recent = history[-6:] if len(history) > 6 else history
        history_text = "\n".join(
            f"{m.get('role','?')}: {str(m.get('content',''))[:300]}" for m in recent
        ) or "(无历史)"

        title_hint = args.strip() or "知识点"

        # LLM 生成 wiki 条目
        from llm_client import llm_client
        prompt = f"""你是技术文档助手。请根据下面的对话内容，生成一篇结构化的技术知识 wiki 条目。

标题提示：{title_hint}

对话内容：
{history_text}

请生成完整的 Markdown wiki 条目，包含 YAML frontmatter：

```markdown
---
title: "条目标题"
feature: <功能域，如：mass-npc / network-sync / rendering / ui / gameplay / misc>
role: [programmer]
type: <文档类型：technical-design / bugfix / howto / decision>
status: active
tags: [tag1, tag2]
summary: "一句话摘要（60字以内）"
---

# 标题

## 问题/背景
（描述问题或背景）

## 解决方案/结论
（核心知识点）

## 关键细节
（重要技术细节）
```

只输出 markdown 内容，不要额外解释。"""

        content = await llm_client.generate(prompt, max_tokens=2000, temperature=0.2)
        content = content.strip()

        # 从生成内容中提取 feature 字段确定保存路径
        import re
        feature_match = re.search(r'feature:\s*([^\n\r]+)', content)
        feature = feature_match.group(1).strip().strip('"\'') if feature_match else "misc"
        safe_feature = re.sub(r'[^\w\-]', '_', feature)

        # 生成文件名（从 title 字段）
        title_match = re.search(r'title:\s*"?([^"\n\r]+)"?', content)
        raw_title = title_match.group(1).strip() if title_match else title_hint
        safe_title = re.sub(r'[^\w\-一-鿿]', '_', raw_title)[:50]

        # 创建目录并写入
        feature_dir = wiki_dir / safe_feature
        feature_dir.mkdir(parents=True, exist_ok=True)
        from datetime import date
        filename = f"{date.today().strftime('%Y%m%d')}_{safe_title}.md"
        out_file = feature_dir / filename
        out_file.write_text(content, encoding="utf-8")

        # 重新生成 wiki_index
        try:
            import subprocess, sys
            script = Path(__file__).parent.parent / "scripts" / "gen_wiki_index.py"
            subprocess.run(
                [sys.executable, str(script), str(wiki_dir), "--budget", "600"],
                capture_output=True, timeout=10
            )
        except Exception:
            pass

        return CommandResult(
            success=True,
            output=f"✅ 已保存到 `.ads/wiki/{safe_feature}/{filename}`\n\n{content[:500]}..."
        )
    except Exception as e:
        return CommandResult(success=False, output=f"保存失败: {e}")


async def _cmd_search_knowledge(args: str, project_id: Optional[str], context: dict) -> CommandResult:
    """搜索项目 wiki 知识库"""
    if not project_id:
        return CommandResult(success=False, output="❌ /search-knowledge 需要在项目内使用")
    if not args.strip():
        return CommandResult(success=False, output="❌ 请提供搜索关键词：/search-knowledge <关键词>")
    try:
        from database import db
        from pathlib import Path
        import re
        row = await db.fetch_one("SELECT git_repo_path FROM projects WHERE id = ?", (project_id,))
        repo_path = (row or {}).get("git_repo_path", "")
        if not repo_path:
            return CommandResult(success=False, output="❌ 项目没有配置 Git 仓库路径")

        # 解析过滤器
        query = args
        feature_filter = ""
        type_filter = ""
        fm = re.search(r'feature:(\S+)', args)
        tm = re.search(r'type:(\S+)', args)
        if fm:
            feature_filter = fm.group(1)
            query = query.replace(fm.group(0), "").strip()
        if tm:
            type_filter = tm.group(1)
            query = query.replace(tm.group(0), "").strip()

        wiki_dir = Path(repo_path) / ".ads" / "wiki"
        if not wiki_dir.exists():
            return CommandResult(success=True, output="项目尚未创建 wiki 知识库。使用 `/save-to-knowledge` 保存第一条知识。")

        from scripts.gen_wiki_index import scan_wiki, _parse_frontmatter
        entries = scan_wiki(wiki_dir)

        # 过滤
        if feature_filter:
            entries = [e for e in entries if feature_filter.lower() in e["feature"].lower()]
        if type_filter:
            entries = [e for e in entries if type_filter.lower() in e["type"].lower()]

        # 关键词匹配（title + summary + tags）
        kw = query.lower()
        scored = []
        for e in entries:
            score = 0
            if kw in e["title"].lower():
                score += 3
            if kw in e["summary"].lower():
                score += 2
            if any(kw in t.lower() for t in (e["tags"] or [])):
                score += 1
            if score > 0 or not kw:
                scored.append((score, e))

        scored.sort(key=lambda x: -x[0])
        top = scored[:5]

        if not top:
            return CommandResult(success=True, output=f"未找到匹配「{query}」的知识条目。")

        lines = [f"搜索「{query}」，找到 {len(top)} 条结果：\n"]
        for _, e in top:
            lines.append(f"**{e['title']}** [{e['type']}] feature={e['feature']}")
            if e["summary"]:
                lines.append(f"> {e['summary']}")
            lines.append("")

        return CommandResult(success=True, output="\n".join(lines))
    except Exception as e:
        return CommandResult(success=False, output=f"搜索失败: {e}")


# ==================== Harness 审计命令 ====================

async def _cmd_harness_audit(args: str, project_id: Optional[str], context: dict) -> CommandResult:
    """生成 Harness 健康审计报告"""
    import re
    dm = re.search(r'--days\s+(\d+)', args or "")
    days = int(dm.group(1)) if dm else 7
    try:
        from scripts.skill_audit import run_audit
        report = await run_audit(project_id=project_id, days=days)

        # 可选：写入 audits/ 目录存档
        from pathlib import Path
        from datetime import date
        audits_dir = Path(__file__).parent.parent / "audits"
        audits_dir.mkdir(exist_ok=True)
        report_file = audits_dir / f"harness-{date.today()}.md"
        report_file.write_text(report, encoding="utf-8")

        return CommandResult(
            success=True,
            output=f"{report}\n\n---\n报告已存档：`{report_file}`"
        )
    except Exception as e:
        return CommandResult(success=False, output=f"审计失败: {e}")


# ==================== MCP 配置分层命令 ====================

_ADS_MCP_FILE = Path(".ads") / "mcp_servers.json"

_MCP_TEMPLATE = """{
  "_comment": "项目级 MCP 配置。与 backend/mcp_servers.json 合并，项目层优先。",
  "_usage": {
    "enable_global_server": "将全局层 enabled:false 的 server 在本项目启用",
    "disable_global_server": "将全局层 enabled:true 的 server 在本项目禁用",
    "add_private_server": "添加仅本项目可用的私有 MCP server"
  },
  "_example_enable_filesystem": {
    "type": "stdio",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "."],
    "enabled": true,
    "_note": "去掉此条目的 _ 前缀即可激活"
  }
}
"""


async def _cmd_mcp_config(args: str, project_id: Optional[str], context: dict) -> CommandResult:
    """查看或修改项目级 MCP 配置"""
    if not project_id:
        return CommandResult(success=False, output="❌ /mcp-config 需要在项目内使用")

    try:
        from database import db
        from pathlib import Path as _P
        import json as _j

        row = await db.fetch_one("SELECT git_repo_path FROM projects WHERE id = ?", (project_id,))
        repo_path = (row or {}).get("git_repo_path", "")
        if not repo_path:
            return CommandResult(success=False, output="❌ 项目没有配置 Git 仓库路径")

        repo = _P(repo_path)
        ads_mcp_file = repo / ".ads" / "mcp_servers.json"
        parts = (args or "").strip().split()
        op = parts[0].lower() if parts else "list"

        from mcp_client import mcp_client, _load_project_mcp_config, _merge_mcp_configs

        # ---- list（默认）----
        if op in ("list", ""):
            merged = mcp_client.get_merged_config_for_project(repo_path)
            sources = mcp_client.get_project_config_source(repo_path)
            status_map = {n: s.status for n, s in mcp_client._servers.items()}

            lines = ["**当前项目 MCP Server 列表**（全局层 + 项目层合并）\n"]
            lines.append(f"{'Server':<20} {'来源':<8} {'状态':<12} {'说明'}")
            lines.append("-" * 65)
            for name, cfg in sorted(merged.items()):
                src = sources.get(name, "global")
                enabled = cfg.get("enabled", False)
                svc_status = status_map.get(name, "disabled" if not enabled else "not_started")
                status_icon = "✅ 运行中" if svc_status == "running" else ("⭕ 已禁用" if not enabled else "⚠ 未启动")
                desc = cfg.get("description", "")[:30]
                src_tag = "项目层" if src == "project" else "全局层"
                lines.append(f"{name:<20} {src_tag:<8} {status_icon:<12} {desc}")

            project_cfg = _load_project_mcp_config(repo_path)
            if not project_cfg:
                lines.append(f"\n项目层配置文件不存在（`.ads/mcp_servers.json`）。执行 `/ads-init` 创建模板。")
            return CommandResult(success=True, output="\n".join(lines))

        # ---- enable <name> ----
        if op == "enable":
            name = parts[1] if len(parts) > 1 else ""
            if not name:
                return CommandResult(success=False, output="用法：/mcp-config enable <server名>")
            proj_cfg = _load_project_mcp_config(repo_path)
            proj_cfg[name] = {**proj_cfg.get(name, {}), "enabled": True}
            ads_mcp_file.parent.mkdir(parents=True, exist_ok=True)
            ads_mcp_file.write_text(_j.dumps(proj_cfg, ensure_ascii=False, indent=2), encoding="utf-8")
            return CommandResult(success=True, output=f"✅ `{name}` 已在项目层启用（写入 `.ads/mcp_servers.json`）\n重启服务后生效。")

        # ---- disable <name> ----
        if op == "disable":
            name = parts[1] if len(parts) > 1 else ""
            if not name:
                return CommandResult(success=False, output="用法：/mcp-config disable <server名>")
            proj_cfg = _load_project_mcp_config(repo_path)
            proj_cfg[name] = {**proj_cfg.get(name, {}), "enabled": False}
            ads_mcp_file.parent.mkdir(parents=True, exist_ok=True)
            ads_mcp_file.write_text(_j.dumps(proj_cfg, ensure_ascii=False, indent=2), encoding="utf-8")
            return CommandResult(success=True, output=f"⭕ `{name}` 已在项目层禁用（写入 `.ads/mcp_servers.json`）")

        # ---- add <name> <command> [args...] ----
        if op == "add":
            if len(parts) < 3:
                return CommandResult(success=False, output="用法：/mcp-config add <名称> <命令> [参数...]")
            name = parts[1]
            cmd = parts[2]
            cmd_args = parts[3:] if len(parts) > 3 else []
            proj_cfg = _load_project_mcp_config(repo_path)
            if name in proj_cfg:
                return CommandResult(success=False, output=f"❌ `{name}` 已存在于项目层配置中")
            proj_cfg[name] = {
                "type": "stdio",
                "command": cmd,
                "args": cmd_args,
                "enabled": True,
                "description": f"项目私有 MCP server（通过 /mcp-config add 添加）",
            }
            ads_mcp_file.parent.mkdir(parents=True, exist_ok=True)
            ads_mcp_file.write_text(_j.dumps(proj_cfg, ensure_ascii=False, indent=2), encoding="utf-8")
            return CommandResult(
                success=True,
                output=f"✅ 已添加项目私有 MCP server `{name}`\n命令：`{cmd} {' '.join(cmd_args)}`\n重启服务后生效。"
            )

        return CommandResult(success=False, output=f"❌ 未知操作：{op}。可选：list / enable / disable / add")
    except Exception as e:
        return CommandResult(success=False, output=f"MCP 配置操作失败: {e}")


# ==================== /doctor ====================

async def _cmd_doctor(args: str, project_id: Optional[str], context: dict) -> CommandResult:
    """检查 ADS 运行环境健康状态"""
    lines = ["## ADS 环境诊断\n"]

    # 1. 数据库
    try:
        from database import db
        await db.fetch_one("SELECT 1")
        lines.append("✅ 数据库：连接正常")
    except Exception as e:
        lines.append(f"❌ 数据库：{e}")

    # 2. LLM 连通性
    try:
        from llm_client import llm_client
        if llm_client.is_configured:
            lines.append(f"✅ LLM：已配置（{llm_client.model}）")
        else:
            lines.append("⚠️ LLM：未配置（缺少 LLM_BASE_URL / LLM_API_KEY）")
    except Exception as e:
        lines.append(f"❌ LLM：{e}")

    # 3. MCP servers
    try:
        from mcp_client import mcp_client
        status = mcp_client.get_status()
        servers = status.get("servers", {})
        if not servers:
            lines.append("⭕ MCP：无已配置 server")
        else:
            running = [n for n, s in servers.items() if s.get("status") == "running"]
            disabled = [n for n, s in servers.items() if not s.get("enabled")]
            failed = [n for n, s in servers.items() if s.get("enabled") and s.get("status") != "running"]
            lines.append(f"{'✅' if not failed else '⚠️'} MCP：{len(running)} 运行中 / {len(disabled)} 已禁用"
                        + (f" / {len(failed)} 启动失败（{', '.join(failed)}）" if failed else ""))
    except Exception as e:
        lines.append(f"❌ MCP：{e}")

    # 4. 项目 Git 仓库（若在项目内）
    if project_id:
        try:
            from database import db
            from pathlib import Path
            row = await db.fetch_one("SELECT git_repo_path, name FROM projects WHERE id = ?", (project_id,))
            if row and row.get("git_repo_path"):
                repo = Path(row["git_repo_path"])
                if repo.exists():
                    has_git = (repo / ".git").exists()
                    has_ads = (repo / ".ads").exists()
                    has_claude = (repo / ".claude").exists()
                    lines.append(f"✅ 项目仓库：`{repo}`")
                    lines.append(f"   git: {'✅' if has_git else '❌'}  .ads/: {'✅' if has_ads else '⭕'}  .claude/: {'✅' if has_claude else '⭕'}")
                else:
                    lines.append(f"❌ 项目仓库路径不存在：`{row['git_repo_path']}`")
            else:
                lines.append("⭕ 项目仓库：未配置 git_repo_path")
        except Exception as e:
            lines.append(f"❌ 项目仓库检查：{e}")

    # 5. 今日费用
    try:
        from database import db
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        row = await db.fetch_one(
            "SELECT COALESCE(SUM(cost_usd), 0) as total FROM llm_conversations WHERE created_at >= ?",
            (today + "T00:00:00",)
        )
        cost = round((row["total"] if row else 0.0), 4)
        lines.append(f"💰 今日费用：${cost:.4f}")
    except Exception:
        pass

    return CommandResult(success=True, output="\n".join(lines))


# ==================== /cost ====================

async def _cmd_cost(args: str, project_id: Optional[str], context: dict) -> CommandResult:
    """查看 LLM 使用费用"""
    opt = (args or "").strip().lower()
    try:
        from database import db
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        month_start = now.strftime("%Y-%m-01")

        async def _query(since: str, until: str = "") -> float:
            sql = "SELECT COALESCE(SUM(cost_usd), 0) as total FROM llm_conversations WHERE created_at >= ?"
            params: list = [since + "T00:00:00"]
            if until:
                sql += " AND created_at < ?"
                params.append(until + "T00:00:00")
            row = await db.fetch_one(sql, tuple(params))
            return round((row["total"] if row else 0.0), 4)

        if opt == "--session":
            session_id = context.get("session_id", "")
            if not session_id:
                return CommandResult(success=True, output="当前 session 费用：$0.0000（无 session_id）")
            row = await db.fetch_one(
                "SELECT COALESCE(SUM(cost_usd), 0) as total FROM llm_conversations WHERE session_id = ?",
                (session_id,)
            )
            cost = round((row["total"] if row else 0.0), 4)
            return CommandResult(success=True, output=f"当前 session 费用：${cost:.4f}")

        elif opt == "--month":
            # 按天展示本月明细
            rows = await db.fetch_all(
                "SELECT DATE(created_at) as day, SUM(cost_usd) as total, COUNT(*) as calls "
                "FROM llm_conversations WHERE created_at >= ? GROUP BY DATE(created_at) ORDER BY day DESC",
                (month_start + "T00:00:00",)
            )
            month_total = await _query(month_start)
            lines = [f"本月费用：${month_total:.4f}\n"]
            for r in rows:
                lines.append(f"  {r['day']}  ${r['total']:.4f}  ({r['calls']} 次调用)")
            return CommandResult(success=True, output="\n".join(lines))

        else:
            # 默认：今日 + 本月 + 7天趋势
            cost_today = await _query(today)
            cost_month = await _query(month_start)
            # 7 天趋势
            rows = await db.fetch_all(
                "SELECT DATE(created_at) as day, COALESCE(SUM(cost_usd),0) as total "
                "FROM llm_conversations WHERE created_at >= ? "
                "GROUP BY DATE(created_at) ORDER BY day DESC LIMIT 7",
                (today[:8] + str(int(today[8:]) - 6).zfill(2) + "T00:00:00",)
            )
            lines = [
                f"**今日费用**：${cost_today:.4f}",
                f"**本月累计**：${cost_month:.4f}",
            ]
            if rows:
                lines.append("\n近 7 天：")
                for r in rows:
                    bar = "█" * min(int(r["total"] * 1000), 20)
                    lines.append(f"  {r['day']}  ${r['total']:.4f}  {bar}")
            lines.append("\n`/cost --session` 查当前 session  |  `/cost --month` 查本月明细")
            return CommandResult(success=True, output="\n".join(lines))
    except Exception as e:
        return CommandResult(success=False, output=f"费用查询失败: {e}")


# ==================== /diff ====================

async def _cmd_diff(args: str, project_id: Optional[str], context: dict) -> CommandResult:
    """查看项目 git diff"""
    if not project_id:
        return CommandResult(success=False, output="❌ /diff 需要在项目内使用")
    try:
        from database import db
        from pathlib import Path
        import subprocess
        row = await db.fetch_one("SELECT git_repo_path FROM projects WHERE id = ?", (project_id,))
        repo = (row or {}).get("git_repo_path", "")
        if not repo or not Path(repo).exists():
            return CommandResult(success=False, output="❌ 项目仓库路径无效")

        opt = (args or "").strip()
        staged = "--staged" in opt
        file_path = opt.replace("--staged", "").strip()

        cmd = ["git", "diff"]
        if staged:
            cmd.append("--staged")
        if file_path:
            cmd += ["--", file_path]

        proc = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, timeout=15)
        diff_text = proc.stdout.strip()

        if not diff_text:
            label = "staged " if staged else ""
            return CommandResult(success=True, output=f"无{label}变更。")

        # 限制输出长度
        lines = diff_text.splitlines()
        truncated = len(lines) > 200
        output_lines = lines[:200]
        result = "\n".join(output_lines)
        if truncated:
            result += f"\n\n（已截断，共 {len(lines)} 行。使用 `/diff --staged <文件>` 查看单文件）"
        label = "Staged diff" if staged else "Working tree diff"
        return CommandResult(success=True, output=f"**{label}**\n```diff\n{result}\n```")
    except Exception as e:
        return CommandResult(success=False, output=f"git diff 失败: {e}")


# ==================== /config ====================

async def _cmd_config(args: str, project_id: Optional[str], context: dict) -> CommandResult:
    """查看或修改 session 配置"""
    from actions.chat.set_session_flag import get_all_session_flags, _SESSION_FLAGS, _FLAG_DEFAULTS, _parse_value

    session_id = context.get("session_id", "default")
    opt = (args or "").strip().split()

    # 无参数 → 列出所有配置
    if not opt:
        flags = get_all_session_flags(session_id)
        lines = ["**当前 session 配置**\n"]
        desc_map = {
            "compaction":     "对话历史自动压缩",
            "nudge":          "AI 回复后未完成需求提示",
            "verbose":        "详细模式",
            "max_turns":      "最大工具调用轮次",
            "budget_tokens":  "token 上限",
            "thinking_mode":  "推理模式（adaptive/on/off）",
            "thinking_budget":"推理 token 预算",
        }
        for k, v in flags.items():
            desc = desc_map.get(k, "")
            default_mark = " *(默认)*" if v == _FLAG_DEFAULTS.get(k) else ""
            lines.append(f"  `{k}` = **{v}**{default_mark}  {desc}")
        lines.append("\n用法：`/config <key> <value>`  例：`/config thinking_mode on`")
        return CommandResult(success=True, output="\n".join(lines))

    # 有参数 → 修改
    if len(opt) < 2:
        return CommandResult(success=False, output="用法：`/config <key> <value>`")
    key, value = opt[0], " ".join(opt[1:])
    if key not in _FLAG_DEFAULTS:
        valid = ", ".join(_FLAG_DEFAULTS.keys())
        return CommandResult(success=False, output=f"❌ 未知配置项：`{key}`\n可用：{valid}")
    try:
        parsed = _parse_value(key, value)
        _SESSION_FLAGS.setdefault(session_id, {})[key] = parsed
        return CommandResult(success=True, output=f"✅ `{key}` 已设置为 **{parsed}**")
    except Exception as e:
        return CommandResult(success=False, output=f"❌ 值无效：{e}")


# ==================== /commit ====================

async def _cmd_commit(args: str, project_id: Optional[str], context: dict) -> CommandResult:
    """AI 辅助生成 commit message 并提交"""
    if not project_id:
        return CommandResult(success=False, output="❌ /commit 需要在项目内使用")
    try:
        from database import db
        from pathlib import Path
        import subprocess
        row = await db.fetch_one("SELECT git_repo_path FROM projects WHERE id = ?", (project_id,))
        repo = (row or {}).get("git_repo_path", "")
        if not repo or not Path(repo).exists():
            return CommandResult(success=False, output="❌ 项目仓库路径无效")

        manual_msg = (args or "").strip()

        # 获取 staged diff
        proc = subprocess.run(["git", "diff", "--staged", "--stat"],
                              cwd=repo, capture_output=True, text=True, timeout=15)
        stat = proc.stdout.strip()
        if not stat:
            return CommandResult(success=True, output="⭕ 没有 staged 变更。请先 `git add` 要提交的文件。")

        if manual_msg:
            # 直接用指定消息提交
            commit_msg = manual_msg
        else:
            # LLM 生成 commit message
            diff_proc = subprocess.run(["git", "diff", "--staged"],
                                       cwd=repo, capture_output=True, text=True, timeout=15)
            diff_text = diff_proc.stdout[:6000]
            from llm_client import llm_client
            prompt = f"""请根据以下 git staged diff 生成一条简洁的 commit message。

规范：
- 第一行：英文，≤70 字符，格式 `<type>(<scope>): <subject>`
  type: feat/fix/refactor/docs/test/chore/perf
- 第二行：空行（如有正文）
- 正文：可用中文，说明原因和影响

只输出 commit message 文本，不要其他解释。

变更统计：
{stat}

Diff：
```diff
{diff_text}
```"""
            commit_msg = (await llm_client.generate(prompt, max_tokens=200, temperature=0.2)).strip()

        # 执行提交
        proc = subprocess.run(["git", "commit", "-m", commit_msg],
                              cwd=repo, capture_output=True, text=True, timeout=30)
        if proc.returncode == 0:
            output = proc.stdout.strip()
            return CommandResult(
                success=True,
                output=f"✅ 提交成功\n\n**Message**：\n```\n{commit_msg}\n```\n\n{output}"
            )
        else:
            return CommandResult(success=False, output=f"❌ 提交失败：\n{proc.stderr.strip()}")
    except Exception as e:
        return CommandResult(success=False, output=f"commit 失败: {e}")


# ==================== /context ====================

async def _cmd_context(args: str, project_id: Optional[str], context: dict) -> CommandResult:
    """查看当前 session context token 使用分布"""
    try:
        session_id = context.get("session_id", "")
        history = context.get("history") or []

        from actions.chat.set_session_flag import get_all_session_flags
        flags = get_all_session_flags(session_id or "default")
        budget = flags.get("budget_tokens", 300_000)

        # 估算各段 token（粗略：1 token ≈ 4 字符）
        def est(text: str) -> int:
            return max(1, len(str(text)) // 4)

        history_tokens = sum(est(m.get("content", "")) for m in history)
        history_msgs = len(history)

        # 最近一次 LLM 调用的 token 数（从 DB 取）
        last_call_tokens = 0
        if session_id:
            try:
                from database import db
                row = await db.fetch_one(
                    "SELECT input_tokens, output_tokens FROM llm_conversations "
                    "WHERE session_id = ? ORDER BY created_at DESC LIMIT 1",
                    (session_id,)
                )
                if row:
                    last_call_tokens = (row.get("input_tokens") or 0) + (row.get("output_tokens") or 0)
            except Exception:
                pass

        pct = min(100, round(history_tokens / budget * 100, 1)) if budget else 0
        bar_len = min(30, int(pct / 100 * 30))
        bar = "█" * bar_len + "░" * (30 - bar_len)

        lines = [
            "**Context 使用情况**\n",
            f"对话历史：约 {history_tokens:,} tokens（{history_msgs} 条消息）",
            f"Token 预算：{budget:,}",
            f"使用率：{pct}%  [{bar}]",
        ]
        if last_call_tokens:
            lines.append(f"上次调用：{last_call_tokens:,} tokens（输入+输出）")
        lines.append(f"\n`/config budget_tokens <N>` 调整 token 上限")
        return CommandResult(success=True, output="\n".join(lines))
    except Exception as e:
        return CommandResult(success=False, output=f"context 查询失败: {e}")


# ── /help ────────────────────────────────────────────────────────────────────

async def _cmd_help(args: str, project_id: Optional[str], context: dict) -> CommandResult:
    """显示所有可用命令"""
    from config import settings as _cfg
    from llm_client import llm_client

    # LLM 状态
    if llm_client.api_format == "cli":
        llm_info = f"CLI 模式 · {llm_client.cli_type} · {llm_client.cli_model}"
    else:
        llm_info = f"API 模式 · {llm_client.api_format} · {llm_client.model}"

    lines = [
        "## 🛠️ 可用命令\n",
        f"> 当前 LLM：{llm_info}\n",
        "### 基础",
        "| 命令 | 说明 |",
        "|------|------|",
        "| `/help` | 显示此帮助 |",
        "| `/model [模型名]` | 查看或切换当前模型 |",
        "| `/status` | 查看 LLM 连接状态 |",
        "| `/clear` | 清空当前对话历史 |",
        "| `/compact` | 手动压缩对话历史 |",
        "| `/context` | 查看 token 使用情况 |",
        "| `/cost` | 查看今日 API 费用 |",
        "",
        "### 记忆",
        "| 命令 | 说明 |",
        "|------|------|",
        "| `/memory [查询]` | 查看或搜索 Agent 记忆 |",
        "| `/memory-export` | 导出记忆到文件 |",
        "| `/memory-import <路径>` | 从文件导入记忆 |",
        "",
        "### AI 思考",
        "| 命令 | 说明 |",
        "|------|------|",
        "| `/think on/off/adaptive` | 切换 Extended Thinking 模式 |",
        "",
        "### 项目 / Git",
        "| 命令 | 说明 |",
        "|------|------|",
        "| `/commit [消息]` | 提交当前变更 |",
        "| `/diff` | 查看未提交变更 |",
        "| `/review` | AI 代码审查 |",
        "",
        "### 知识库",
        "| 命令 | 说明 |",
        "|------|------|",
        "| `/search-knowledge <关键词>` | 搜索知识库 |",
        "| `/save-to-knowledge` | 保存当前对话到知识库 |",
        "",
        "### UE 专属",
        "| 命令 | 说明 |",
        "|------|------|",
        "| `/ue-run <代码>` | 在 UE Editor 执行 Python |",
        "| `/ue-bp-gen <描述>` | AI 生成 Blueprint |",
        "| `/ue-level <描述>` | AI 生成关卡布局 |",
        "",
        "### 系统",
        "| 命令 | 说明 |",
        "|------|------|",
        "| `/skills` | 查看已加载 Skills |",
        "| `/doctor` | 系统健康检查 |",
        "| `/config <键> [值]` | 读写会话配置 |",
        "| `/mcp` | 查看 MCP 服务器状态 |",
        "| `/init` | 初始化 ADS 目录结构 |",
        "| `/harness-audit` | Harness 健康审计 |",
    ]
    return CommandResult(success=True, output="\n".join(lines))


# ── /model ───────────────────────────────────────────────────────────────────

async def _cmd_model(args: str, project_id: Optional[str], context: dict) -> CommandResult:
    """查看或切换当前模型"""
    from llm_client import llm_client, CLI_MODEL_OPTIONS
    from config import settings

    arg = args.strip()

    if not arg:
        # 查看当前模型
        if llm_client.api_format == "cli":
            available = CLI_MODEL_OPTIONS.get(llm_client.cli_type, [])
            lines = [
                f"**当前模型：** `{llm_client.cli_model}`",
                f"**接入方式：** CLI · {llm_client.cli_type}",
                "",
            ]
            if available:
                lines.append("**可用模型：**")
                for m in available:
                    marker = " ← 当前" if m == llm_client.cli_model else ""
                    lines.append(f"- `{m}`{marker}")
            lines.append("\n`/model <模型名>` 切换模型")
        else:
            lines = [
                f"**当前模型：** `{llm_client.model}`",
                f"**接入方式：** API · {llm_client.api_format}",
                "\n`/model <模型名>` 切换模型",
            ]
        return CommandResult(success=True, output="\n".join(lines))

    # 切换模型
    if llm_client.api_format == "cli":
        old = llm_client.cli_model
        llm_client.cli_model = arg
        settings.LLM_CLI_MODEL = arg
        # 持久化到 .env
        try:
            from config import BASE_DIR
            import re
            env_path = BASE_DIR / ".env"
            if env_path.exists():
                text = env_path.read_text(encoding="utf-8")
                if "LLM_CLI_MODEL=" in text:
                    text = re.sub(r"LLM_CLI_MODEL=.*", f"LLM_CLI_MODEL={arg}", text)
                else:
                    text += f"\nLLM_CLI_MODEL={arg}\n"
                env_path.write_text(text, encoding="utf-8")
        except Exception:
            pass
        return CommandResult(success=True, output=f"✅ 模型已切换：`{old}` → `{arg}`")
    else:
        old = llm_client.model
        llm_client.model = arg
        settings.LLM_MODEL = arg
        try:
            from config import BASE_DIR
            import re
            env_path = BASE_DIR / ".env"
            if env_path.exists():
                text = env_path.read_text(encoding="utf-8")
                if "LLM_MODEL=" in text:
                    text = re.sub(r"LLM_MODEL=.*", f"LLM_MODEL={arg}", text)
                else:
                    text += f"\nLLM_MODEL={arg}\n"
                env_path.write_text(text, encoding="utf-8")
        except Exception:
            pass
        return CommandResult(success=True, output=f"✅ 模型已切换：`{old}` → `{arg}`")


# ── /clear ───────────────────────────────────────────────────────────────────

async def _cmd_clear(args: str, project_id: Optional[str], context: dict) -> CommandResult:
    """清空当前对话历史"""
    session_id = context.get("session_id", "default")
    return CommandResult(
        success=True,
        output="✅ 对话历史已清空",
        sse_events=[{"type": "clear_history", "session_id": session_id}],
    )


# ── /status ──────────────────────────────────────────────────────────────────

async def _cmd_status(args: str, project_id: Optional[str], context: dict) -> CommandResult:
    """显示 LLM 连接状态和系统信息"""
    from llm_client import llm_client
    from config import settings
    import platform, sys

    # LLM 状态
    if llm_client.api_format == "cli":
        import shutil
        resolved = shutil.which(llm_client.cli_cmd) or "未找到"
        llm_lines = [
            f"**LLM 接入方式：** CLI",
            f"**工具类型：** {llm_client.cli_type}",
            f"**可执行文件：** `{llm_client.cli_cmd}` → `{resolved}`",
            f"**当前模型：** `{llm_client.cli_model}`",
            f"**超时：** {llm_client.cli_timeout}s",
        ]
    else:
        configured = "✅ 已配置" if llm_client.is_configured else "❌ 未配置"
        llm_lines = [
            f"**LLM 接入方式：** {llm_client.api_format.upper()} API  {configured}",
            f"**Endpoint：** `{llm_client.base_url or '未设置'}`",
            f"**当前模型：** `{llm_client.model}`",
            f"**超时：** {llm_client.timeout}s  **重试：** {llm_client.max_retries}次",
        ]

    # 系统信息
    sys_lines = [
        f"**Python：** {sys.version.split()[0]}",
        f"**平台：** {platform.system()} {platform.release()}",
        f"**DB：** `{settings.DB_PATH}`",
    ]

    lines = ["## 📊 系统状态\n", "### LLM"] + llm_lines + ["", "### 系统"] + sys_lines
    return CommandResult(success=True, output="\n".join(lines))


# ── /tasks ───────────────────────────────────────────────────────────────────

async def _cmd_tasks(args: str, project_id: Optional[str], context: dict) -> CommandResult:
    """显示正在执行的工单和 Agent 状态"""
    from database import db
    from utils import now_iso
    import datetime

    try:
        # 正在执行的工单（running / in_progress）
        running_tickets = await db.fetch_all(
            """SELECT id, title, status, assigned_agent, current_action, updated_at, project_id
               FROM tickets
               WHERE status IN ('running','in_progress','executing')
               ORDER BY updated_at DESC
               LIMIT 20"""
        )

        # 待执行的工单（pending / queued）
        pending_tickets = await db.fetch_all(
            """SELECT id, title, status, project_id
               FROM tickets
               WHERE status IN ('pending','queued','todo')
               ORDER BY created_at ASC
               LIMIT 10"""
        )

        # Agent 状态（从 agent_registry 获取）
        try:
            from agent_registry import agent_registry
            agents = agent_registry.get_all_status() if hasattr(agent_registry, 'get_all_status') else {}
        except Exception:
            agents = {}

        def elapsed(ts: str) -> str:
            try:
                dt = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
                now = datetime.datetime.now(datetime.timezone.utc)
                secs = int((now - dt).total_seconds())
                if secs < 60:   return f"{secs}s"
                if secs < 3600: return f"{secs//60}m{secs%60}s"
                return f"{secs//3600}h{(secs%3600)//60}m"
            except Exception:
                return "?"

        lines = ["## 🔄 任务状态\n"]

        # Agent 工作状态
        working_agents = {k: v for k, v in agents.items() if v.get("status") == "working"}
        if working_agents:
            lines.append(f"### ⚡ 工作中 Agent（{len(working_agents)}）")
            for name, info in working_agents.items():
                ticket_title = info.get("ticket_title", "")
                action = info.get("action", "")
                started = info.get("started_at", "")
                el = elapsed(started) if started else "?"
                lines.append(f"- **{name}** · {action} · {elapsed(started) if started else '?'}")
                if ticket_title:
                    lines.append(f"  工单：{ticket_title[:50]}")
            lines.append("")

        # 执行中工单
        if running_tickets:
            lines.append(f"### 🔄 执行中工单（{len(running_tickets)}）")
            lines.append("| 状态 | 工单 | Agent | 耗时 |")
            lines.append("|------|------|-------|------|")
            for t in running_tickets:
                el = elapsed(t.get("updated_at", ""))
                agent = t.get("assigned_agent") or "-"
                action = t.get("current_action") or ""
                title = (t.get("title") or "")[:40]
                status = t.get("status", "")
                action_str = f" · {action}" if action else ""
                lines.append(f"| {status} | {title} | {agent}{action_str} | {el} |")
            lines.append("")

        # 待执行工单
        if pending_tickets:
            lines.append(f"### ⏳ 待执行工单（{len(pending_tickets)}）")
            for t in pending_tickets:
                title = (t.get("title") or "")[:50]
                lines.append(f"- {title}")
            lines.append("")

        # CI 构建任务
        ci_builds = await db.fetch_all(
            """SELECT build_id, project_id, build_type, status, created_at, raw_output_tail
               FROM ci_builds
               WHERE status IN ('running','pending')
               ORDER BY created_at DESC
               LIMIT 10"""
        )

        if not running_tickets and not pending_tickets and not working_agents and not ci_builds:
            lines.append("✅ 当前无运行中任务\n")
            lines.append("> 进入项目查看工单详情，或提交新需求开始执行。")

        # 当前项目过滤提示
        if project_id:
            lines.append(f"\n> 仅显示项目 `{project_id[:8]}` 内工单，全局状态见各项目面板")

        # 构建结构化任务列表供前端分屏使用
        task_items = []
        for t in running_tickets:
            task_items.append({
                "id": t["id"], "type": "ticket",
                "title": (t.get("title") or "")[:60],
                "status": t.get("status", ""),
                "project_id": t.get("project_id", ""),
                "action": t.get("current_action", ""),
                "elapsed": elapsed(t.get("updated_at", "")),
                "agent": t.get("assigned_agent", ""),
            })
        for t in pending_tickets:
            task_items.append({
                "id": t["id"], "type": "ticket",
                "title": (t.get("title") or "")[:60],
                "status": t.get("status", ""),
                "project_id": t.get("project_id", ""),
                "action": "", "elapsed": "", "agent": "",
            })
        for b in ci_builds:
            task_items.append({
                "id": b["build_id"], "type": "ci_build",
                "title": f"CI: {b.get('build_type','build')}",
                "status": b.get("status", ""),
                "project_id": b.get("project_id", ""),
                "action": b.get("build_type", ""),
                "elapsed": elapsed(b.get("created_at", "")),
                "agent": "CI Pipeline",
                "log_tail": b.get("raw_output_tail", ""),
            })

        return CommandResult(
            success=True,
            output="\n".join(lines),
            data={"type": "tasks_panel", "tasks": task_items},
        )

    except Exception as e:
        return CommandResult(success=False, output=f"获取任务状态失败: {e}")


# ── /agents ──────────────────────────────────────────────────────────────────

async def _cmd_agents(args: str, project_id: Optional[str], context: dict) -> CommandResult:
    """显示所有 Agent 及其状态"""
    try:
        from orchestrator import orchestrator

        icons = {
            "ProductAgent":   "📝", "ArchitectAgent": "🏗️",
            "DevAgent":       "💻", "TestAgent":      "🧪",
            "ReviewAgent":    "🔍", "DeployAgent":    "🚀",
            "ChatAssistant":  "💬", "UEEditorAgent":  "🎮",
        }
        roles = {
            "ProductAgent":   "需求拆单 + 产品验收",
            "ArchitectAgent": "增量架构设计",
            "DevAgent":       "代码开发 + 自测",
            "TestAgent":      "5层质量测试",
            "ReviewAgent":    "代码审查",
            "DeployAgent":    "三环境部署",
            "ChatAssistant":  "AI 助手 + 全局工具",
            "UEEditorAgent":  "UE 蓝图/关卡生成",
        }

        lines = ["## 🤖 Agent 列表\n"]

        # 工单调度 Agent
        orch_agents = list(orchestrator.agents.items())
        if orch_agents:
            lines.append(f"### 工单 Agent（{len(orch_agents)} 个）\n")
            lines.append("| Agent | 角色 | 状态 | 完成 | 异常 |")
            lines.append("|-------|------|------|------|------|")
            for name, agent in orch_agents:
                status_info = orchestrator._agent_status.get(name, {})
                status = status_info.get("status", "idle")
                completed = status_info.get("completed_count", 0)
                errors = status_info.get("error_count", 0)
                icon = icons.get(name, "🤖")
                role = roles.get(name, name)
                status_label = "🔄 运行中" if status == "working" else "💤 空闲"
                lines.append(f"| {icon} {name} | {role} | {status_label} | {completed} | {errors} |")

            # 正在运行的工单详情
            working = [(n, orchestrator._agent_status.get(n, {}))
                       for n, _ in orch_agents
                       if orchestrator._agent_status.get(n, {}).get("status") == "working"]
            if working:
                lines.append("\n**正在执行：**")
                for name, info in working:
                    ticket = info.get("ticket_title", "")
                    action = info.get("action", "")
                    lines.append(f"- **{name}** → {ticket[:40]} `{action}`")

        # ChatAssistant
        try:
            from agents.chat_assistant import ChatAssistantAgent
            ca_actions = ChatAssistantAgent().list_actions()
            lines.append(f"\n### AI 助手\n")
            lines.append(f"- **💬 ChatAssistant** — {roles.get('ChatAssistant','')}  ·  {len(ca_actions)} 个工具")
        except Exception:
            pass

        # Skills 概览
        try:
            from skills import skill_loader
            all_skills = skill_loader.get_all_skills_status()
            enabled = [s for s in all_skills.values() if s.get("enabled")]
            lines.append(f"\n### Skills\n")
            lines.append(f"已加载 **{len(enabled)}** 个 Skill，`/skills` 查看详情")
        except Exception:
            pass

        return CommandResult(success=True, output="\n".join(lines))

    except Exception as e:
        return CommandResult(success=False, output=f"获取 Agent 列表失败: {e}")


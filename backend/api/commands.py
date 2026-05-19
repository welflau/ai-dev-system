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
        "description": "查看当前项目已加载的 Skills",
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


def _load_disk_commands() -> Dict[str, Dict[str, Any]]:
    """扫描 skills/commands/*.md，加载磁盘命令定义"""
    commands_dir = Path(__file__).resolve().parent.parent / "skills" / "commands"
    if not commands_dir.exists():
        return {}
    result = {}
    for md_file in sorted(commands_dir.glob("*.md")):
        name = md_file.stem
        try:
            content = md_file.read_text(encoding="utf-8")
            # 简单解析 YAML frontmatter
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
            result[name] = {
                "description": description or f"/{name} 命令",
                "args_hint": args_hint,
                "requires_project": requires_project,
                "from_disk": True,
            }
        except Exception as e:
            logger.warning("加载命令定义失败 %s: %s", md_file.name, e)
    return result


def get_all_commands() -> Dict[str, Dict[str, Any]]:
    """合并内置命令 + 磁盘命令（磁盘可覆盖内置）"""
    all_cmds = dict(_BUILTIN_COMMANDS)
    all_cmds.update(_load_disk_commands())
    return all_cmds


# ── 请求 / 响应模型 ───────────────────────────────────────────────────────────

class CommandResult(BaseModel):
    success: bool
    output: str = ""
    data: Optional[Dict[str, Any]] = None
    sse_events: List[Dict[str, Any]] = []  # 可选：额外 SSE 事件给前端


# ── 路由 ──────────────────────────────────────────────────────────────────────

@router.get("/api/commands")
async def list_commands():
    """列出所有可用命令（供前端补全）"""
    cmds = get_all_commands()
    return {
        "commands": [
            {
                "name": name,
                "description": info["description"],
                "args_hint": info.get("args_hint", ""),
                "requires_project": info.get("requires_project", False),
            }
            for name, info in sorted(cmds.items())
        ]
    }


@router.post("/api/commands/{name}")
async def execute_global_command(name: str, body: dict = {}):
    """执行全局命令（无项目上下文）"""
    return await _dispatch_command(name, args=body.get("args", ""), project_id=None, context=body)


@router.post("/api/projects/{project_id}/commands/{name}")
async def execute_project_command(project_id: str, name: str, body: dict = {}):
    """执行项目命令（带项目上下文）"""
    return await _dispatch_command(name, args=body.get("args", ""), project_id=project_id, context=body)


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
    }

    handler = handlers.get(name)
    if not handler:
        return CommandResult(success=False, output=f"未知命令：/{name}。输入 /help 查看可用命令。")

    try:
        return await handler(args=args, project_id=project_id, context=context)
    except Exception as e:
        logger.error("命令 /%s 执行失败: %s", name, e, exc_info=True)
        return CommandResult(success=False, output=f"命令执行失败: {e}")


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
    """列出当前项目已加载的 Skills"""
    try:
        from skills.loader import skill_loader
        # 获取项目 traits
        traits = []
        if project_id:
            from database import db
            row = await db.fetch_one("SELECT traits FROM projects WHERE id = ?", (project_id,))
            if row and row["traits"]:
                import json
                traits = json.loads(row["traits"]) if isinstance(row["traits"], str) else list(row["traits"])

        loaded = skill_loader.get_skills_for_agent("ChatAssistant", traits=traits)
        if not loaded:
            return CommandResult(success=True, output="当前无已加载 Skills")
        lines = [f"已加载 {len(loaded)} 个 Skills：\n"]
        for s in loaded:
            lines.append(f"• **{s.get('name', '?')}** — {s.get('description', '')[:60]}")
        return CommandResult(success=True, output="\n".join(lines))
    except Exception as e:
        return CommandResult(success=False, output=f"获取 Skills 失败: {e}")


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

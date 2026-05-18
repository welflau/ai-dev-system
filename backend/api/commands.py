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
        "compact":   _cmd_compact,
        "memory":    _cmd_memory,
        "think":     _cmd_think,
        "skills":    _cmd_skills,
        "ue-run":    _cmd_ue_run,
        "ue-bp-gen": _cmd_ue_bp_gen,
        "ue-level":  _cmd_ue_level,
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


async def _cmd_ue_run(args: str, project_id: Optional[str], context: dict) -> CommandResult:
    """在 UE Editor 执行 Python 代码"""
    if not project_id:
        return CommandResult(success=False, output="❌ /ue-run 需要在项目内使用")
    code = args.strip()
    if not code:
        return CommandResult(success=False, output="用法：/ue-run <python code>")
    try:
        # 尝试调用 ue_python_bridge（P0 实现后生效）
        from engines.ue_python_bridge import run_python
        result = await run_python(code, project_id)
        if result["success"]:
            return CommandResult(success=True, output=f"✅ 执行成功\n```\n{result.get('stdout', '')}\n```")
        else:
            return CommandResult(success=False, output=f"❌ 执行失败\n```\n{result.get('stderr', result.get('error', ''))}\n```")
    except ImportError:
        return CommandResult(success=False, output="⚠️ UE Python 桥接尚未实现（待 B-0 完成）")


async def _cmd_ue_bp_gen(args: str, project_id: Optional[str], context: dict) -> CommandResult:
    """生成 Blueprint"""
    if not project_id:
        return CommandResult(success=False, output="❌ /ue-bp-gen 需要在项目内使用")
    if not args.strip():
        return CommandResult(success=False, output="用法：/ue-bp-gen <描述，如：创建一个波次生成器 Blueprint>")
    try:
        from actions.ue_blueprint_gen import BlueprintGenAction
        action = BlueprintGenAction()
        result = await action.run({"description": args.strip(), "project_id": project_id})
        return CommandResult(success=result.success, output=result.message or (result.error or ""))
    except ImportError:
        return CommandResult(success=False, output="⚠️ BlueprintGenAction 尚未实现（待 B-1 完成）")


async def _cmd_ue_level(args: str, project_id: Optional[str], context: dict) -> CommandResult:
    """生成关卡"""
    if not project_id:
        return CommandResult(success=False, output="❌ /ue-level 需要在项目内使用")
    if not args.strip():
        return CommandResult(success=False, output="用法：/ue-level <描述，如：8x8 地板 + 4 盏灯 + NavMesh>")
    try:
        from actions.ue_level_gen import LevelGenAction
        action = LevelGenAction()
        result = await action.run({"description": args.strip(), "project_id": project_id})
        return CommandResult(success=result.success, output=result.message or (result.error or ""))
    except ImportError:
        return CommandResult(success=False, output="⚠️ LevelGenAction 尚未实现（待 B-2 完成）")

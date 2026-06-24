"""
ConfirmProjectAction — 识别到用户想新建项目时，返回前端展示的确认卡片

对 LLM 暴露为 tool（Anthropic tool_use），ChatAssistantAgent 在 P2 接入后
全局聊天里 LLM 识别"建项目"意图即调用本工具产出草稿卡片。

与 CreateProjectAction 的区别：
- ConfirmProjectAction 只生成草稿卡片，不碰 Git、不碰数据库
- CreateProjectAction 真正落库（用户在前端点击确认后，由 /confirm-create-project 端点触发）

v1.1 新增：支持「打开本地目录」手动挡模式
- local_path 有值时，自动调用 scan-directory 识别 VCS/traits
- 新增 mode（auto/manual）、extra_paths 字段
"""
from typing import Any, Dict
from actions.base import ActionBase, ActionResult


class ConfirmProjectAction(ActionBase):

    @property
    def name(self) -> str:
        return "confirm_project"

    @property
    def description(self) -> str:
        return "识别到用户想新建项目或打开本地目录时，生成项目草稿让用户确认。不直接创建，不碰 Git 不写库。"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "当用户明确表达想要新建项目，或发送了一个本地目录路径时使用。"
                "此工具只产出草稿给用户确认，不会真的创建项目。\n\n"
                "【两种使用场景】\n"
                "1. 用户发送本地路径（如 F:\\MyGame）→ 填 local_path，系统自动识别，"
                "mode 设为 manual（手动挡），其他字段可留空\n"
                "2. 用户想新建项目 → 填 name/traits 等，mode 设为 auto（自动挡）\n\n"
                "⚠️ 新建项目时 traits 必填，至少含 platform:* 和 category:*。"
                "打开本地路径时 traits 可留空（系统自动检测）。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "项目名称。打开本地路径时可留空，系统自动从目录名/特征文件读取。",
                    },
                    "local_path": {
                        "type": "string",
                        "description": (
                            "本地目录路径。用户发送类似路径的消息时填此字段，"
                            "系统会自动扫描识别 git/P4/traits 等信息。"
                            "例：F:\\ADS_Projects\\MyGame 或 /home/user/project"
                        ),
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["auto", "manual"],
                        "description": (
                            "运行模式。manual=手动挡（直接对话修改文件，不自动 commit/提交），"
                            "auto=自动挡（工单流转+自动 commit）。"
                            "打开本地已有项目时建议 manual，全新项目建议 auto。"
                        ),
                    },
                    "git_remote_url": {
                        "type": "string",
                        "description": "Git 远程仓库 URL，新建项目时填写",
                    },
                    "traits": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "项目特征标签，从 trait_taxonomy 选。"
                            "新建项目必填（至少 platform:* + category:*）；"
                            "打开本地路径时可留空。"
                        ),
                    },
                    "preset_id": {
                        "type": "string",
                        "description": "可选 preset 名（webapp/web-game/ue5-game 等）",
                    },
                    "description": {
                        "type": "string",
                        "description": "项目简要描述，可选",
                    },
                    "tech_stack": {
                        "type": "string",
                        "description": "技术栈，可选，打开本地路径时系统自动识别",
                    },
                    "local_repo_path": {
                        "type": "string",
                        "description": "本地仓库路径，留空则自动生成到 backend/projects/ 下",
                    },
                },
                "required": [],  # local_path 模式下无必填字段
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        name = (context.get("name") or "").strip()
        local_path = (context.get("local_path") or "").strip()
        mode = (context.get("mode") or "").strip() or None
        git_remote_url = (context.get("git_remote_url") or "").strip()
        description = (context.get("description") or "").strip()
        tech_stack = (context.get("tech_stack") or "").strip()
        local_repo_path = (context.get("local_repo_path") or "").strip()
        traits_raw = context.get("traits") or []
        preset_id = (context.get("preset_id") or "").strip() or None

        # ── 场景1：打开本地目录 ──────────────────────────
        if local_path:
            import os
            local_path = os.path.abspath(local_path)
            if not os.path.exists(local_path):
                return ActionResult(success=False, error=f"路径不存在: {local_path}")
            if not os.path.isdir(local_path):
                return ActionResult(success=False, error=f"路径不是目录: {local_path}")

            # 调用 scan-directory 自动识别
            try:
                import httpx
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.post(
                        "http://localhost:8000/api/projects/scan-directory",
                        json={"path": local_path},
                    )
                    scan = resp.json() if resp.status_code == 200 else {}
            except Exception:
                # 扫描失败时用目录名兜底
                scan = {"project_name": os.path.basename(local_path)}

            # 如果已有项目，直接返回切换指令
            if scan.get("already_exists"):
                return ActionResult(
                    success=True,
                    data={
                        "type": "switch_project",
                        "project_id": scan["project_id"],
                        "project_name": scan["project_name"],
                        "message": f"项目「{scan['project_name']}」已存在，正在切换…",
                    },
                )

            return ActionResult(
                success=True,
                data={
                    "type": "confirm_project",
                    "name": name or scan.get("project_name", os.path.basename(local_path)),
                    "git_remote_url": scan.get("git_remote_url", ""),
                    "description": description,
                    "tech_stack": tech_stack or scan.get("tech_stack", ""),
                    "local_repo_path": local_path,
                    "traits": traits_raw or scan.get("traits", []),
                    "preset_id": preset_id or scan.get("suggested_preset"),
                    "mode": mode or scan.get("suggested_mode", "manual"),
                    "extra_paths": scan.get("extra_paths", []),
                    "engine_path": scan.get("engine_path"),
                    "engine_path_warning": scan.get("engine_path_warning"),
                    "root_vcs": scan.get("root_vcs", "none"),
                    "p4_info": scan.get("p4_info"),
                    "scan_result": scan,  # 完整扫描结果，供前端展示
                    "recommended_packs": _get_recommended_packs(traits_raw or scan.get("traits", [])),
                },
            )

        # ── 场景2：新建项目（原有逻辑）───────────────────
        if not name:
            return ActionResult(success=False, error="项目名称不能为空")

        traits = [str(t).strip() for t in traits_raw if str(t).strip()]
        if not traits:
            return ActionResult(success=False, error="必须提供 traits（至少含 platform:* 和 category:*）")

        has_platform = any(t.startswith("platform:") for t in traits)
        has_category = any(t.startswith("category:") for t in traits)
        if not (has_platform and has_category):
            missing = []
            if not has_platform: missing.append("platform:*")
            if not has_category: missing.append("category:*")
            return ActionResult(
                success=False,
                error=f"traits 缺必填维度：{', '.join(missing)}，请反问用户补齐后再调用",
            )

        has_game = "category:game" in traits
        has_engine = any(t.startswith("engine:") for t in traits)
        if has_game and not has_engine:
            return ActionResult(
                success=False,
                error="traits 含 category:game 但缺 engine:*（ue5/godot4/unity/none 等），请反问用户",
            )

        return ActionResult(
            success=True,
            data={
                "type": "confirm_project",
                "name": name,
                "git_remote_url": git_remote_url,
                "description": description,
                "tech_stack": tech_stack,
                "local_repo_path": local_repo_path,
                "traits": traits,
                "preset_id": preset_id,
                "mode": mode or "auto",
                "extra_paths": [],
                "recommended_packs": _get_recommended_packs(traits),
            },
        )


def _get_recommended_packs(traits: list) -> list:
    """返回推荐 Pack 的完整元数据列表（供前端渲染选择卡片）。"""
    try:
        from pack_installer import get_recommended_packs, list_packs
        recommended_names = set(get_recommended_packs(traits))
        all_packs = {p["name"]: p for p in list_packs()}
        result = []
        for name in recommended_names:
            meta = all_packs.get(name, {})
            result.append({
                "name": name,
                "display_name": meta.get("display_name", name),
                "description": meta.get("description", ""),
                "tags": meta.get("tags", []),
                "contains": meta.get("contains", []),
                "targets": meta.get("targets", []),
                "selected": True,  # 推荐默认勾选
            })
        return result
    except Exception:
        return []

r"""
ProposeUEFrameworkAction — 识别到用户想生成 UE 项目框架时，返回方案卡片

对 LLM 暴露为 tool。LLM 在项目内聊天里识别"做个 FPS 游戏""初始化 UE 工程骨架"
这类意图时调用本工具，产出**方案卡片数据**给前端展示。用户点击卡片 [✓ 确认生成]
后前端调 POST /api/projects/{id}/ue-framework/instantiate 真正执行落地。

此工具不实际修改仓库（只读 + 计算），可以反复调用。

输入（LLM 给）：
    project_name_override : str?  可选。默认用项目名（去掉中文空格特殊字符）
    genre_hint            : str?  可选，覆盖 project traits 里的 genre:* 推断
    force_template        : str?  可选，强制用某个模板（如 TP_ThirdPerson）

Context 自动注入（后端注入，LLM 不可见）：
    project_id

输出 data:
    {
      "type": "propose_ue_framework",
      "project_id": "PRJ-xxx",
      "project_name_target": "MyFPS",        # 用于 rename 的目标名
      "traits": [...],
      "engines": [                            # 本机可用引擎列表
        {path, version, type, recommended: bool}
      ],
      "recommended_template": "TP_FirstPerson",
      "template_reason": "按 traits [genre:fps] 命中",
      "alternative_templates": ["TP_Blank"],  # 兜底
      "target_dir": "D:/Projects/MyFPS",
      "repo_is_empty": bool,
      "warnings": [...]                       # 目标非空 / 无引擎 / 缺 UBT 等
    }
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from actions.base import ActionBase, ActionResult

logger = logging.getLogger("actions.chat.propose_ue_framework")


def _sanitize_project_name(name: str) -> str:
    """把项目名规范化为可作 UE module 名的标识符（首字母 + 字母数字下划线）"""
    s = re.sub(r"[^A-Za-z0-9_]", "", (name or "").strip())
    if not s:
        return "MyUEProject"
    if not s[0].isalpha():
        s = "P" + s
    return s


class ProposeUEFrameworkAction(ActionBase):

    @property
    def name(self) -> str:
        return "propose_ue_framework"

    @property
    def description(self) -> str:
        return "识别到用户想生成 UE 项目框架时，产出方案卡片给前端确认（不直接修改仓库）"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "当用户在一个 UE 项目里明确表达想生成框架 / 初始化工程骨架 / 基于模板开始开发时使用。"
                "例如「做个 FPS 游戏」「基于 TP_FirstPerson 开始」「生成 UE 项目骨架」。"
                "此工具只生成方案卡片给用户确认，不会真实修改仓库或 clone。"
                "⚠️ 仅在项目 traits 含 engine:ue5 或 engine:ue4 时使用；"
                "若项目不是 UE 项目（traits 里没 engine:ue*）则不要调用。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "project_name_override": {
                        "type": "string",
                        "description": "项目名覆盖（用于 rename 模板类名）。留空则用项目当前名自动规范化",
                    },
                    "genre_hint": {
                        "type": "string",
                        "description": "可选的 genre hint：fps / third_person / topdown / racing 等",
                    },
                    "force_template": {
                        "type": "string",
                        "description": "强制指定模板名（TP_FirstPerson / TP_ThirdPerson / TP_TopDown / TP_VehicleAdv / TP_Blank），覆盖 traits 自动匹配",
                    },
                },
                "required": [],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        project_id = context.get("project_id")
        if not project_id:
            return ActionResult(success=False, error="未注入 project_id（全局聊天不允许调此工具）")

        # 读项目 traits + name + repo path
        from database import db
        proj = await db.fetch_one(
            "SELECT id, name, traits FROM projects WHERE id = ?", (project_id,)
        )
        if not proj:
            return ActionResult(success=False, error=f"项目不存在: {project_id}")

        import json as _json
        try:
            traits_raw = proj.get("traits") or "[]"
            traits = _json.loads(traits_raw) if isinstance(traits_raw, str) else list(traits_raw)
            if not isinstance(traits, list):
                traits = []
        except Exception:
            traits = []

        # 只对 UE 项目有效
        if not any(t.startswith("engine:ue") for t in traits):
            return ActionResult(
                success=False,
                error=(
                    "该项目不是 UE 项目（traits 里没 engine:ue5/ue4）。"
                    "若要生成非 UE 框架，请使用其他工具。"
                ),
            )

        # 叠加 LLM 给的 genre_hint 到 traits 参与匹配
        ephemeral_traits = list(traits)
        genre_hint = (context.get("genre_hint") or "").strip()
        if genre_hint and not any(t.startswith("genre:") for t in ephemeral_traits):
            ephemeral_traits.append(f"genre:{genre_hint}")

        # 目标项目名
        override = (context.get("project_name_override") or "").strip()
        project_name_target = _sanitize_project_name(override or proj["name"])

        # 推荐引擎：先从 detect 列表里找与任何 .uproject EngineAssociation 匹配的；
        # 无 .uproject 就推荐最新官方 Launcher
        from engines.ue_resolver import (
            detect_installed_engines,
            resolve_project_engine,
        )
        all_engines = detect_installed_engines()

        # 找仓库路径
        from git_manager import git_manager
        repo_path = git_manager._repo_path(project_id)
        repo_dir = Path(repo_path) if repo_path else None
        target_dir = str(repo_dir) if repo_dir else ""

        # 该项目已有 .uproject？
        existing_uproject: Optional[Path] = None
        if repo_dir and repo_dir.is_dir():
            matches = sorted(repo_dir.glob("*.uproject"))
            if matches:
                existing_uproject = matches[0]

        recommended_idx = 0
        if existing_uproject:
            try:
                resolved = resolve_project_engine(existing_uproject)
                if resolved and resolved.path:
                    for i, e in enumerate(all_engines):
                        if Path(e.path).resolve() == Path(resolved.path).resolve():
                            recommended_idx = i
                            break
            except Exception:
                pass
        else:
            # 没 .uproject 时，选最新 UE5 launcher（有 UBT 的）
            for i, e in enumerate(all_engines):
                if (e.type == "launcher" and e.version.startswith("5.")
                        and e.has_ubt):
                    recommended_idx = i
                    # 找到就替换成最新的（版本号最大）
                # 用末尾一个 —— 因为 detect 返回按版本升序

            # 倒着找最新 launcher
            for i in range(len(all_engines) - 1, -1, -1):
                e = all_engines[i]
                if (e.type == "launcher" and e.version.startswith("5.")
                        and e.has_ubt):
                    recommended_idx = i
                    break

        engines_dict: List[Dict[str, Any]] = []
        for i, e in enumerate(all_engines):
            engines_dict.append({
                **e.to_dict(),
                "recommended": (i == recommended_idx),
            })

        # 模板推荐
        force_template = (context.get("force_template") or "").strip()
        from actions.instantiate_ue_template import pick_template_by_traits
        if force_template:
            recommended_template = force_template
            template_reason = f"LLM 强制指定: {force_template}"
        else:
            recommended_template = pick_template_by_traits(ephemeral_traits)
            if not recommended_template:
                recommended_template = "TP_Blank"
                template_reason = "ue_templates.yaml 未匹配，兜底到 TP_Blank"
            else:
                matched_trait_hints = [t for t in ephemeral_traits
                                       if t.startswith(("genre:", "category:"))]
                template_reason = (
                    f"按 traits [{', '.join(matched_trait_hints) or 'engine:ue5'}] 命中 {recommended_template}"
                )

        # 目标仓库状态
        repo_is_empty = True
        warnings: List[str] = []
        if repo_dir and repo_dir.is_dir():
            non_git = [p for p in repo_dir.iterdir() if p.name != ".git"]
            repo_is_empty = len(non_git) == 0
            if not repo_is_empty:
                warnings.append(
                    f"仓库 {repo_dir.name} 已有 {len(non_git)} 个条目。"
                    f"实例化时需加 allow_overwrite=true 覆盖"
                )
        if not all_engines:
            warnings.append("本机未检测到任何 UE 引擎（HKLM + HKCU 都空），请先安装 Epic Launcher 或手填引擎路径")
        elif not any(e["has_ubt"] for e in engines_dict):
            warnings.append("检测到引擎但无一具备 UBT（可能都没完成 setup），请先在 UE 里 GenerateProjectFiles")

        return ActionResult(
            success=True,
            data={
                "type": "propose_ue_framework",
                "project_id": project_id,
                "project_name": proj["name"],
                "project_name_target": project_name_target,
                "traits": traits,
                "engines": engines_dict,
                "recommended_template": recommended_template,
                "template_reason": template_reason,
                "alternative_templates": ["TP_Blank", "TP_FirstPerson", "TP_ThirdPerson",
                                          "TP_TopDown", "TP_VehicleAdv"],
                "target_dir": target_dir,
                "repo_is_empty": repo_is_empty,
                "warnings": warnings,
            },
        )

"""
UEUprojectHealAction — UE uproject 自愈

触发条件：Playtest 因 "module X could not be loaded" 失败
动作：
  1. 从错误日志提取缺失的模块名
  2. 将模块名映射到对应的 UE 插件名（内置映射表 + LLM 兜底）
  3. 读取 .uproject，检查插件列表是否已有
  4. 缺失则追加 {"Name": "<plugin>", "Enabled": true}
  5. 写回 .uproject
  6. 返回修复结果（是否有变更，变更了哪些插件）

后续由 Orchestrator 重新触发 engine_compile + run_playtest。
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from actions.base import ActionBase, ActionResult

logger = logging.getLogger("ue_uproject_heal")

# 已知模块 → 插件的静态映射表（覆盖高频情况，兜底用 LLM）
_MODULE_TO_PLUGIN: Dict[str, str] = {
    # UE 官方插件
    "EnhancedInput":       "EnhancedInput",
    "GameplayAbilities":   "GameplayAbilities",
    "GameplayTasks":       "GameplayTasks",
    "AbilitySystemComponent": "GameplayAbilities",
    "Niagara":             "Niagara",
    "NiagaraCore":         "Niagara",
    "ModelingComponents":  "ModelingToolsEditorMode",
    "PCG":                 "PCG",
    "StateTreeModule":     "StateTree",
    "MassEntity":          "MassEntity",
    "MassAI":              "MassAI",
    "MassGameplay":        "MassGameplay",
    "ZoneGraph":           "ZoneGraph",
    "AnimationWarping":    "AnimationWarping",
    "MotionWarping":       "MotionWarping",
    "Chaos":               "ChaosVehicles",
    "ChaosVehicles":       "ChaosVehicles",
    "PhysicsControl":      "PhysicsControl",
    "Metasound":           "Metasound",
    "MetasoundEngine":     "Metasound",
    "AudioModulation":     "AudioModulation",
    "CommonUI":            "CommonUI",
    "CommonGame":          "CommonGame",
    "GameSubtitles":       "GameSubtitles",
    "OnlineServicesNull":  "OnlineServices",
    "OnlineServicesCommon": "OnlineServices",
    "Iris":                "Iris",
}

# 错误日志中 module not loaded 的正则
_MODULE_ERROR_RE = re.compile(
    r"(?:module|plugin)['\s]+([A-Za-z0-9_]+)['\s]+(?:could not be loaded|has not been turned on|not found)",
    re.IGNORECASE,
)


def _extract_missing_modules(log_text: str) -> List[str]:
    """从 UE log 或 Playtest 输出中提取无法加载的模块名"""
    found = set()
    for m in _MODULE_ERROR_RE.finditer(log_text):
        found.add(m.group(1).strip())
    return sorted(found)


def _module_to_plugin(module: str) -> str:
    """模块名 → 插件名（优先静态映射，找不到则假设同名）"""
    return _MODULE_TO_PLUGIN.get(module, module)


def _patch_uproject(uproject_path: Path, plugin_names: List[str]) -> List[str]:
    """
    将 plugin_names 中缺失的插件追加到 .uproject 的 Plugins 数组。
    返回实际新增的插件名列表（已存在的跳过）。
    """
    text = uproject_path.read_text(encoding="utf-8")
    data = json.loads(text)

    plugins: List[Dict] = data.setdefault("Plugins", [])
    existing = {p.get("Name", "").lower() for p in plugins}

    added = []
    for plugin in plugin_names:
        if plugin.lower() not in existing:
            plugins.append({"Name": plugin, "Enabled": True})
            added.append(plugin)
            logger.info("uproject 自愈：追加插件 %s", plugin)

    if added:
        uproject_path.write_text(
            json.dumps(data, indent="\t", ensure_ascii=False),
            encoding="utf-8"
        )

    return added


class UEUprojectHealAction(ActionBase):
    name = "ue_uproject_heal"
    description = "检测 Playtest module not loaded 错误并自动补写 .uproject 插件声明"

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        project_id = context.get("project_id", "")
        playtest_log = context.get("playtest_log", "")   # raw_head + raw_tail 拼接
        uproject_path_str = context.get("uproject_path", "")

        if not playtest_log:
            return ActionResult(success=False, error="缺少 playtest_log")

        # 1. 提取缺失模块
        missing_modules = _extract_missing_modules(playtest_log)
        if not missing_modules:
            logger.info("playtest 日志中未发现 module not loaded 错误，跳过自愈")
            return ActionResult(
                success=True,
                data={"healed": False, "reason": "日志中无 module not loaded 错误"}
            )

        logger.info("发现缺失模块：%s", missing_modules)

        # 2. 找 .uproject 路径
        uproject_path: Optional[Path] = None
        if uproject_path_str:
            uproject_path = Path(uproject_path_str)
        else:
            uproject_path = await self._find_uproject(project_id)

        if not uproject_path or not uproject_path.exists():
            return ActionResult(
                success=False,
                error=f"找不到 .uproject 文件（path={uproject_path_str}）"
            )

        # 3. 映射模块 → 插件
        plugin_names = [_module_to_plugin(m) for m in missing_modules]
        # LLM 兜底：对静态映射找不到的模块询问 LLM
        unknown = [m for m in missing_modules if m not in _MODULE_TO_PLUGIN]
        if unknown:
            llm_map = await self._llm_resolve_plugins(unknown)
            plugin_names = []
            for m in missing_modules:
                p = _MODULE_TO_PLUGIN.get(m) or llm_map.get(m) or m
                plugin_names.append(p)

        # 去重
        plugin_names = list(dict.fromkeys(plugin_names))

        # 4. 补写 .uproject
        added = _patch_uproject(uproject_path, plugin_names)

        if not added:
            return ActionResult(
                success=True,
                data={"healed": False, "reason": "所有插件已在 .uproject 中，无需修改"}
            )

        msg = (
            f"uproject 自愈成功：已追加 {len(added)} 个插件声明：{', '.join(added)}\n"
            f".uproject：{uproject_path}"
        )
        logger.info(msg)
        return ActionResult(
            success=True,
            message=msg,
            data={
                "healed": True,
                "added_plugins": added,
                "uproject_path": str(uproject_path),
                "missing_modules": missing_modules,
            }
        )

    async def _find_uproject(self, project_id: str) -> Optional[Path]:
        """从数据库获取 .uproject 路径"""
        try:
            from database import db
            row = await db.fetch_one(
                "SELECT uproject_path, git_repo_path FROM projects WHERE id=?", (project_id,)
            )
            if row:
                up = row.get("uproject_path") or ""
                repo = row.get("git_repo_path") or ""
                if up and repo:
                    p = Path(repo) / up
                    if p.exists():
                        return p
                # 兜底：扫描 repo 根目录找 .uproject
                if repo:
                    for f in Path(repo).glob("*.uproject"):
                        return f
        except Exception as e:
            logger.warning("查找 .uproject 失败: %s", e)
        return None

    async def _llm_resolve_plugins(self, unknown_modules: List[str]) -> Dict[str, str]:
        """对未知模块名用 LLM 推断对应的 UE 插件名"""
        if not unknown_modules:
            return {}
        try:
            from llm_client import llm_client
            prompt = (
                "请将以下 UE 模块名映射到对应的 UE 插件名。"
                "输出纯 JSON，格式：{\"模块名\": \"插件名\"}。\n\n"
                "模块列表：" + ", ".join(unknown_modules)
            )
            raw = await llm_client.generate(prompt, max_tokens=200, temperature=0.1)
            raw = raw.strip().lstrip("```json").rstrip("```").strip()
            return json.loads(raw)
        except Exception as e:
            logger.warning("LLM 推断插件名失败: %s", e)
            return {}

"""ArtistAgent — 美术资产落地 Agent

职责：把 ArtAgent 产出的 asset_manifest.yaml 变成磁盘上真实可用的资产。
Position in SOP: art_design_done → asset_gen (fragment) → assets_ready → development

与 ArtAgent 的分工：
  ArtAgent    ：产出"需要什么资产"（视觉规范 + asset_manifest 清单）
  ArtistAgent ：解决"资产从哪来"（检索资产库 → 命中即用，未命中给占位图）

不做 AI 图像生成 —— 系统尚未接入图像模型。真实 AIGC 落地后，
在 GenerateAssetsAction._resolve_one 里加一条来源分支即可，Agent 不用动。
"""
from typing import Any, Dict

from agents.base import BaseAgent, ReactMode
from actions.generate_assets import GenerateAssetsAction


class ArtistAgent(BaseAgent):

    action_classes = [GenerateAssetsAction]
    react_mode = ReactMode.SINGLE
    # 关心 ArtAgent 的输出（asset_manifest 由它产出）
    watch_actions = {"write_art_design"}

    @property
    def agent_type(self) -> str:
        return "ArtistAgent"

    async def execute(self, task_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if task_name == "generate_assets":
            return await self.run_action("generate_assets", context)
        return {"status": "error", "message": f"ArtistAgent 未知任务: {task_name}"}

"""ArtistAgent — 美术资产落地 Agent

职责：把 ArtAgent 产出的 asset_manifest.yaml 变成磁盘上真实可用的资产。
Position in SOP: art_design_done → asset_gen (fragment) → assets_ready → development

与 ArtAgent 的分工：
  ArtAgent    ：产出"需要什么资产"（视觉规范 + asset_manifest 清单）
  ArtistAgent ：解决"资产从哪来"（检索资产库 → 命中即用；未命中则投递
                AIGC 异步生图 + 占位图兜底，生图完成后自动回填覆盖占位图）

AIGC 的具体投递与回写在 GenerateAssetsAction._resolve_one /
image_processor._backfill_media，Agent 本身只负责调度。
"""
from typing import Any, Dict

from agents.base import BaseAgent, ReactMode
from plugins.registry import require_action_class


class ArtistAgent(BaseAgent):

    action_classes = [require_action_class("generate_assets")]
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

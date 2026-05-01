"""
ArtAgent — 美术/视觉设计 Agent

职责：产出 Design Token / 组件视觉规范 / 完整资产清单
Position in SOP: ux_design_done → art_design (fragment) → art_design_done → ArchitectAgent

与 UXAgent 的分工：
  UXAgent：交互逻辑（流程/布局/状态），不关心视觉样式
  ArtAgent：视觉规范（颜色/字体/风格），资产路由（图标从哪来/图片怎么生成）

通过 SOP fragment art_design.yaml 按 traits 条件插入
"""
from typing import Any, Dict
from agents.base import BaseAgent, ReactMode
from actions.write_art_design import WriteArtDesignAction


class ArtAgent(BaseAgent):

    action_classes = [WriteArtDesignAction]
    react_mode = ReactMode.SINGLE

    @property
    def agent_type(self) -> str:
        return "ArtAgent"

    async def execute(self, task_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if task_name == "write_art_design":
            return await self.run_action("write_art_design", context)
        return {"status": "error", "message": f"ArtAgent 未知任务: {task_name}"}

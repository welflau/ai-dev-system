"""
UEEditorAgent — UE 內容創作 Agent（B-3）

職責：
  接受 ue_content_pending 狀態的工單，根據工單描述自動判斷
  需要生成 Blueprint、關卡布局還是執行 Python 代碼，
  通過 Python 橋接寫入 UE Editor。

繼承 BaseAgent：自動獲得 Thinking/Compaction/Memory 能力（A-2 下沉）

工單流轉：
  ue_content_pending
    ↓ UEEditorAgent
  ue_content_done（成功）
  ue_content_failed（失敗，可重試）

支持的任務類型：
  - ue_bp_gen：Blueprint 生成
  - ue_level_gen：關卡布局生成
  - ue_run_python：自定義 Python 執行
"""
import logging
from typing import Any, Dict

from agents.base import BaseAgent, ReactMode
from actions.ue_blueprint_gen import BlueprintGenAction
from actions.ue_level_gen import LevelGenAction
from actions.ue_run_python import UERunPythonAction

logger = logging.getLogger("ue_editor_agent")

# 工單狀態
UE_CONTENT_PENDING = "ue_content_pending"
UE_CONTENT_DONE = "ue_content_done"
UE_CONTENT_FAILED = "ue_content_failed"


class UEEditorAgent(BaseAgent):
    """UE 內容創作 Agent — 通過 Python 橋接向 UE Editor 生成內容"""

    action_classes = [BlueprintGenAction, LevelGenAction, UERunPythonAction]
    react_mode = ReactMode.SINGLE
    watch_actions = set()  # 不依賴其他 Agent 的輸出

    @property
    def agent_type(self) -> str:
        return "UEEditorAgent"

    async def execute(self, task_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """根據 task_name 分發到對應的 UE 操作"""
        if task_name == "ue_bp_gen":
            return await self._do_bp_gen(context)
        elif task_name == "ue_level_gen":
            return await self._do_level_gen(context)
        elif task_name == "ue_run_python":
            return await self._do_run_python(context)
        elif task_name == "ue_content":
            # 通用入口：自動判斷類型
            return await self._do_auto_dispatch(context)
        else:
            return {"status": "error", "message": f"UEEditorAgent 不支持任務: {task_name}"}

    async def _do_bp_gen(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Blueprint 生成"""
        description = context.get("description") or context.get("ticket_title", "")
        result = await self.run_action("ue_blueprint_gen", {
            **context,
            "description": description,
        })
        return result

    async def _do_level_gen(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """關卡布局生成"""
        description = context.get("description") or context.get("ticket_title", "")
        result = await self.run_action("ue_level_gen", {
            **context,
            "description": description,
        })
        return result

    async def _do_run_python(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """直接執行 Python 代碼"""
        code = context.get("code") or context.get("description", "")
        result = await self.run_action("ue_run_python", {
            **context,
            "code": code,
        })
        return result

    async def _do_auto_dispatch(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """自動判斷工單類型並分發

        根據 context.ue_task_type 或工單描述判斷：
        - 含 Blueprint/BP 關鍵詞 → ue_bp_gen
        - 含 Level/關卡/地圖 關鍵詞 → ue_level_gen
        - 含 Python 代碼塊 → ue_run_python
        """
        desc = (context.get("description") or context.get("ticket_title", "")).lower()
        ue_task_type = context.get("ue_task_type", "")

        if ue_task_type == "blueprint" or any(kw in desc for kw in
                ["blueprint", "bp_", "藍圖", "蓝图"]):
            logger.info("UEEditorAgent: 判定為 Blueprint 生成任務")
            return await self._do_bp_gen(context)

        if ue_task_type == "level" or any(kw in desc for kw in
                ["level", "關卡", "关卡", "地圖", "地图", "场景", "場景"]):
            logger.info("UEEditorAgent: 判定為關卡生成任務")
            return await self._do_level_gen(context)

        if ue_task_type == "python" or "```python" in context.get("description", ""):
            logger.info("UEEditorAgent: 判定為 Python 執行任務")
            return await self._do_run_python(context)

        # 默認走 Blueprint 生成
        logger.info("UEEditorAgent: 無法判定類型，默認 Blueprint 生成")
        return await self._do_bp_gen(context)

"""
UERunPythonAction — 通過 Python 橋接在 UE Editor 執行 Python 代碼

供 ChatAssistantAgent 的 /ue-run 命令和 UEEditorAgent（B-3）使用。
"""
import logging
from typing import Any, Dict

from actions.base import ActionBase, ActionResult

logger = logging.getLogger("actions.ue_run_python")


class UERunPythonAction(ActionBase):

    @property
    def name(self) -> str:
        return "ue_run_python"

    @property
    def description(self) -> str:
        return "在運行中的 UE Editor 執行 Python 代碼（通過 Remote Execution 橋接）"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "在當前項目關聯的 UE Editor 中執行 Python 代碼。\n"
                "適用：查詢資產信息、創建 Blueprint、修改 Actor 屬性、布置關卡等。\n"
                "前置：UE Editor 已運行，Remote Execution Server 已啟用。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "要在 UE Editor 中執行的 Python 代碼",
                    },
                    "timeout": {
                        "type": "number",
                        "description": "執行超時（秒，默認 60）",
                    },
                },
                "required": ["code"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        code = (context.get("code") or "").strip()
        project_id = context.get("project_id")
        timeout = float(context.get("timeout") or 60.0)

        if not code:
            return ActionResult(success=False, error="code 不能為空")

        try:
            from engines.ue_python_bridge import run_python
            result = await run_python(code, project_id=project_id, timeout=timeout)

            if result["success"]:
                output = result.get("stdout") or result.get("result") or "執行成功（無輸出）"
                return ActionResult(
                    success=True,
                    message=output[:500],
                    data={
                        "type": "ue_python_result",
                        "success": True,
                        "stdout": result.get("stdout", ""),
                        "result": result.get("result", ""),
                    },
                )
            else:
                error = result.get("error") or "UE Python 執行失敗"
                return ActionResult(
                    success=False,
                    error=error,
                    data={
                        "type": "ue_python_result",
                        "success": False,
                        "error": error,
                    },
                )

        except Exception as e:
            logger.error("UERunPythonAction 異常: %s", e)
            return ActionResult(success=False, error=str(e))

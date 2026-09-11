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
                "前置：UE Editor 已運行，Remote Execution Server 已啟用。\n\n"
                "⚠️ 重要：若使用者提供了自然語言描述（如「列出所有Actor」），\n"
                "你必須先根據描述生成合適的 import unreal Python 代碼，\n"
                "然後將生成的代碼作為 code 參數傳入。不要直接傳遞自然語言描述！"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": (
                            "要在 UE Editor 中執行的 Python 代碼。必須是合法的 Python 代碼，\n"
                            "包含 import unreal。若使用者輸入自然語言，請先生成對應的 Python 代碼再傳入"
                        ),
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

        # 檢測：如果 code 看起來不像 Python 代碼（不含關鍵詞），提醒 LLM 重新生成
        _has_import = "import " in code
        _has_print  = "print(" in code or "print " in code or code.strip().startswith("print")
        _has_func   = "def " in code or "class " in code or "for " in code or "if " in code
        _has_unreal = "unreal" in code.lower()
        if not (_has_import or _has_print or _has_func or _has_unreal):
            return ActionResult(
                success=False,
                error=(
                    f"代碼無效：傳入的參數 '{code[:80]}' 不是合法的 Python 代碼。\n"
                    "請根據使用者需求生成 import unreal 的 Python 代碼，然後重新調用本工具。\n"
                    "例如：import unreal; actors = unreal.EditorLevelLibrary.get_all_level_actors(); print(len(actors))"
                ),
            )

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

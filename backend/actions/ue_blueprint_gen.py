"""
BlueprintGenAction — LLM 生成 UE Python 腳本 → Python 橋接寫入 Editor

流程：
  1. 讀取 ue-blueprint-patterns skill 作 few-shot
  2. LLM 生成 UE Python 代碼
  3. 通過 ue_python_bridge 發送到 UE Editor 執行
  4. 自動保存並編譯 Blueprint
"""
import logging
from typing import Any, Dict, Optional

from actions.base import ActionBase, ActionResult

logger = logging.getLogger("actions.ue_blueprint_gen")

# ── Blueprint 生成的 system prompt ───────────────────────────────────────────

_BP_SYSTEM_PROMPT = """你是一個 Unreal Engine Blueprint 生成專家。
根據功能描述，生成可在 UE Editor 中執行的 Python 代碼。

## 核心規則

1. **只輸出 Python 代碼**，不要任何解釋文字（除非遇到限制）
2. 代碼必須以 `import unreal` 開頭
3. 每個操作完成後調用 `unreal.EditorAssetLibrary.save_asset()`
4. 最後一行 `print(f"✅ 完成：{bp_path}")` 告知結果

## 常用模式

**新建 Blueprint 類：**
```python
import unreal

factory = unreal.BlueprintFactory()
factory.parent_class = unreal.load_class(None, "/Script/Engine.Actor")
asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
bp = asset_tools.create_asset("BP_MyActor", "/Game/Blueprints", unreal.Blueprint, factory)
unreal.EditorAssetLibrary.save_asset(bp.get_path_name())
print(f"✅ 已創建: {bp.get_path_name()}")
```

**修改 Blueprint CDO 屬性：**
```python
import unreal

bp = unreal.load_asset("/Game/Characters/BP_PlayerCharacter")
cdo = unreal.get_default_object(bp.generated_class())
cdo.set_editor_property("max_walk_speed", 600.0)
unreal.EditorAssetLibrary.save_asset(bp.get_path_name())
print(f"✅ 已修改: {bp.get_path_name()}")
```

**添加組件：**
```python
import unreal

bp = unreal.load_asset("/Game/BP_MyActor")
comp = unreal.EditorBlueprintLibrary.add_component(bp, unreal.StaticMeshComponent, "MyMesh", True, None, unreal.Transform())
unreal.EditorAssetLibrary.save_asset(bp.get_path_name())
print(f"✅ 已添加組件")
```

**編譯 Blueprint：**
```python
import unreal
bp = unreal.load_asset("/Game/Blueprints/BP_MyActor")
unreal.EditorBlueprintLibrary.compile_blueprint(bp)
```

## 限制說明

- 節點圖級別操作（直接增刪節點、連線）需要 `/ue-extend Blueprint` 先擴展 API
- 遇到 API 不可用時，說明限制並提供替代方案
"""


class BlueprintGenAction(ActionBase):

    @property
    def name(self) -> str:
        return "ue_blueprint_gen"

    @property
    def description(self) -> str:
        return "根據自然語言描述生成 Blueprint 並寫入 UE Editor（通過 Python 橋接）"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "根據功能描述自動生成 Unreal Engine Blueprint 並寫入運行中的 UE Editor。\n"
                "支持：新建 BP 類、修改屬性、添加組件、編譯 Blueprint 等。\n"
                "前置：UE Editor 已運行，Remote Execution Server 已啟用。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Blueprint 功能描述，如「創建一個波次生成器，每隔 5 秒在隨機位置生成一個敵人」",
                    },
                    "bp_path": {
                        "type": "string",
                        "description": "目標 Blueprint 路徑（可選，如 /Game/Blueprints/BP_WaveSpawner），不填則由 LLM 決定",
                    },
                    "parent_class": {
                        "type": "string",
                        "description": "父類路徑（可選，如 /Script/Engine.Actor），不填則為 Actor",
                    },
                },
                "required": ["description"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        description = (context.get("description") or "").strip()
        project_id = context.get("project_id")
        bp_path_hint = context.get("bp_path", "")
        parent_class_hint = context.get("parent_class", "")

        if not description:
            return ActionResult(success=False, error="description 不能為空")

        # Step 1：LLM 生成 UE Python 代碼
        py_code = await self._generate_bp_code(description, bp_path_hint, parent_class_hint)
        if not py_code:
            return ActionResult(success=False, error="LLM 生成代碼失敗")

        logger.info("BlueprintGenAction: 生成代碼 %d 字符，描述=%s", len(py_code), description[:40])

        # Step 2：通過 Python 橋接發送到 UE Editor
        try:
            from engines.ue_python_bridge import run_python
            result = await run_python(py_code, project_id=project_id, timeout=60.0)
        except Exception as e:
            return ActionResult(
                success=False,
                error=f"UE Python 橋接失敗: {e}",
                data={"generated_code": py_code},
            )

        if result["success"]:
            output = result.get("stdout") or result.get("result") or "Blueprint 操作完成"
            return ActionResult(
                success=True,
                message=output[:300],
                data={
                    "type": "ue_blueprint_result",
                    "success": True,
                    "stdout": result.get("stdout", ""),
                    "generated_code": py_code,
                },
            )
        else:
            error = result.get("error") or "Blueprint 生成失敗"
            return ActionResult(
                success=False,
                error=error,
                data={
                    "type": "ue_blueprint_result",
                    "success": False,
                    "error": error,
                    "generated_code": py_code,
                },
            )

    async def _generate_bp_code(
        self,
        description: str,
        bp_path_hint: str = "",
        parent_class_hint: str = "",
    ) -> Optional[str]:
        """調用 LLM 生成 UE Python 代碼"""
        try:
            from llm_client import llm_client

            user_parts = [f"請生成實現以下功能的 UE Python 代碼：\n\n{description}"]
            if bp_path_hint:
                user_parts.append(f"\n目標 Blueprint 路徑：{bp_path_hint}")
            if parent_class_hint:
                user_parts.append(f"\n父類：{parent_class_hint}")
            user_parts.append("\n\n只輸出 Python 代碼，不要 markdown 代碼塊，不要解釋。")

            response = await llm_client.chat(
                messages=[
                    {"role": "user", "content": "\n".join(user_parts)},
                ],
                system=_BP_SYSTEM_PROMPT,
                max_tokens=2000,
                temperature=0.2,
            )

            if not response:
                return None

            # 清理：去掉可能的 markdown 代碼塊標記
            code = response.strip()
            if code.startswith("```python"):
                code = code[9:]
            elif code.startswith("```"):
                code = code[3:]
            if code.endswith("```"):
                code = code[:-3]

            return code.strip()

        except Exception as e:
            logger.error("BlueprintGen LLM 調用失敗: %s", e)
            return None

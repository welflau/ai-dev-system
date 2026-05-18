"""
LevelGenAction — LLM 生成 UE 關卡布局 → Python 橋接寫入 Editor

流程：
  1. LLM 解析設計描述，生成 UE Python 關卡布局代碼
  2. 通過 ue_python_bridge 發送到 UE Editor 執行
  3. 放置地面、燈光、PlayerStart、NavMesh、障礙物等

參考：ECC/agents/ue-level-designer.md
"""
import logging
from typing import Any, Dict, Optional

from actions.base import ActionBase, ActionResult

logger = logging.getLogger("actions.ue_level_gen")

# ── 關卡生成 System Prompt ────────────────────────────────────────────────────

_LEVEL_SYSTEM_PROMPT = """你是一個 Unreal Engine 關卡布局生成專家。
根據關卡設計描述，生成可在 UE Editor 中執行的 Python 布局腳本。

## 核心規則

1. **只輸出 Python 代碼**，不要任何解釋文字
2. 代碼必須以 `import unreal` 開頭
3. 最後調用 `unreal.EditorLoadingAndSavingUtils.save_current_level()`
4. 最後一行 `print(f"✅ 關卡布局完成，共放置 {total} 個 Actor")` 報告結果

## 坐標系規則

- UE 單位 = 1cm，Z 軸朝上
- 地面 Z = 0，Actor 落在地面上通常 Z = 0 ~ 100
- 常用尺寸：地面格 400×400cm，牆高 400cm，房間 2000×2000cm

## 常用模式

**鋪設地面格子：**
```python
import unreal

els = unreal.EditorLevelLibrary
floor_mesh = unreal.load_asset("/Game/StarterContent/Architecture/Floor_400x400")

# 8×8 地面
for r in range(8):
    for c in range(8):
        actor = els.spawn_actor_from_class(unreal.StaticMeshActor,
                    unreal.Vector(c * 400, r * 400, 0))
        actor.static_mesh_component.set_static_mesh(floor_mesh)
        actor.set_actor_label(f"Floor_{r}_{c}")
```

**放置玩家出生點：**
```python
spawn = els.spawn_actor_from_class(unreal.PlayerStart, unreal.Vector(1600, 1600, 100))
spawn.set_actor_label("PlayerStart_Main")
```

**點光源：**
```python
light = els.spawn_actor_from_class(unreal.PointLight, unreal.Vector(x, y, 300))
light.point_light_component.set_editor_property("intensity", 3000.0)
light.point_light_component.set_editor_property(
    "light_color", unreal.LinearColor(1.0, 0.95, 0.8, 1.0))
light.set_actor_label(f"Light_{i}")
```

**定向光（室外）：**
```python
dir_light = els.spawn_actor_from_class(
    unreal.DirectionalLight, unreal.Vector(0, 0, 1000))
dir_light.set_actor_rotation(unreal.Rotator(-45, 30, 0), False)
dir_light.set_actor_label("SunLight")
```

**NavMesh（覆蓋整個可行走區域）：**
```python
nav = els.spawn_actor_from_class(
    unreal.NavMeshBoundsVolume, unreal.Vector(center_x, center_y, 200))
nav.set_actor_scale3d(unreal.Vector(size_x / 100, size_y / 100, 5))
nav.set_actor_label("NavMesh_Main")
```

**牆壁：**
```python
wall_mesh = unreal.load_asset("/Game/StarterContent/Architecture/Wall_400x400")
wall = els.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(x, y, 0))
wall.static_mesh_component.set_static_mesh(wall_mesh)
wall.set_actor_rotation(unreal.Rotator(0, rot_yaw, 0), False)
```

**障礙物（掩體）：**
```python
cube_mesh = unreal.load_asset("/Game/StarterContent/Shapes/Shape_Cube")
obs = els.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(x, y, 0))
obs.static_mesh_component.set_static_mesh(cube_mesh)
obs.set_actor_scale3d(unreal.Vector(2, 2, 1))
obs.set_actor_label(f"Cover_{i}")
```

## 設計原則

- **出生點**：放置在開闊區域，周圍 500cm 無障礙物
- **光源密度**：室內每 800cm 一個點光源
- **NavMesh**：覆蓋所有可行走區域，用 ActorLabel 標注關鍵 Actor
- 若描述提到 StarterContent 以外的資產，先用 StarterContent 替代
"""


class LevelGenAction(ActionBase):

    @property
    def name(self) -> str:
        return "ue_level_gen"

    @property
    def description(self) -> str:
        return "根據關卡設計描述生成並布置 UE 關卡（地面/燈光/NavMesh/出生點等）"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "根據自然語言描述在 UE Editor 中自動布置關卡元素。\n"
                "支持：地面格子、燈光、PlayerStart、NavMesh、障礙物、掩體等。\n"
                "前置：UE Editor 已打開目標關卡，Remote Execution Server 已啟用。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "關卡設計描述，如「8×8地面，四角各一盞燈，中央玩家出生點，NavMesh 全覆蓋」",
                    },
                    "clear_existing": {
                        "type": "boolean",
                        "description": "是否先清空現有 Actor（默認 false，疊加模式）",
                    },
                },
                "required": ["description"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        description = (context.get("description") or "").strip()
        project_id = context.get("project_id")
        clear_existing = bool(context.get("clear_existing", False))

        if not description:
            return ActionResult(success=False, error="description 不能為空")

        # Step 1：LLM 生成關卡布局代碼
        py_code = await self._generate_level_code(description, clear_existing)
        if not py_code:
            return ActionResult(success=False, error="LLM 生成代碼失敗")

        logger.info("LevelGenAction: 生成代碼 %d 字符，描述=%s", len(py_code), description[:40])

        # Step 2：通過 Python 橋接執行
        try:
            from engines.ue_python_bridge import run_python
            result = await run_python(py_code, project_id=project_id, timeout=120.0)
        except Exception as e:
            return ActionResult(
                success=False,
                error=f"UE Python 橋接失敗: {e}",
                data={"generated_code": py_code},
            )

        if result["success"]:
            output = result.get("stdout") or result.get("result") or "關卡布局完成"
            return ActionResult(
                success=True,
                message=output[:400],
                data={
                    "type": "ue_level_result",
                    "success": True,
                    "stdout": result.get("stdout", ""),
                    "generated_code": py_code,
                },
            )
        else:
            error = result.get("error") or "關卡生成失敗"
            return ActionResult(
                success=False,
                error=error,
                data={
                    "type": "ue_level_result",
                    "success": False,
                    "error": error,
                    "generated_code": py_code,
                },
            )

    async def _generate_level_code(
        self, description: str, clear_existing: bool = False
    ) -> Optional[str]:
        """調用 LLM 生成關卡布局 Python 代碼"""
        try:
            from llm_client import llm_client

            parts = []
            if clear_existing:
                parts.append("首先清空當前關卡的所有 Actor（除默認 Lighting 外）。\n")
            parts.append(f"請根據以下描述生成關卡布局代碼：\n\n{description}")
            parts.append("\n\n只輸出 Python 代碼，不要 markdown 代碼塊，不要解釋。")

            response = await llm_client.chat(
                messages=[{"role": "user", "content": "\n".join(parts)}],
                system=_LEVEL_SYSTEM_PROMPT,
                max_tokens=3000,
                temperature=0.2,
            )

            if not response:
                return None

            code = response.strip()
            if code.startswith("```python"):
                code = code[9:]
            elif code.startswith("```"):
                code = code[3:]
            if code.endswith("```"):
                code = code[:-3]

            return code.strip()

        except Exception as e:
            logger.error("LevelGen LLM 調用失敗: %s", e)
            return None

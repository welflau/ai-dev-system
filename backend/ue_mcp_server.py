"""
UE Bridge MCP Server
将 ADS 的 UE Editor 控制 Action 封装为标准 MCP tools，供 Multica Agent（Claude Code）调用。

前置条件：
  - UE Editor 已运行并载入项目
  - Edit > Project Settings > Plugins > Python > Enable Remote Execution Server 已勾选

启动方式：
  python ue_mcp_server.py

Multica Agent mcp_config 配置：
  {
    "servers": {
      "ue-bridge": {
        "command": "python",
        "args": ["F:/A_Works/ai-dev-system/backend/ue_mcp_server.py"]
      }
    }
  }
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

# 把 ADS backend 加入 sys.path，复用现有 bridge 和 LLM 客户端
_BACKEND = str(Path(__file__).parent)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("ue-bridge")
logger = logging.getLogger("ue_mcp_server")


# ── 复用 ADS 现有 bridge ──────────────────────────────────────────────────────
async def _ue_run(code: str, project_id: str = "", timeout: float = 60.0) -> dict:
    from engines.ue_python_bridge import run_python
    return await run_python(code, project_id=project_id or None, timeout=timeout)


async def _llm_generate(system: str, user: str) -> str:
    """复用 ADS llm_client 生成代码，无需重新配置 API Key"""
    from llm_client import LLMClient
    client = LLMClient()
    resp = await client.agenerate(
        messages=[{"role": "user", "content": user}],
        system=system,
        max_tokens=4096,
    )
    return resp.get("content", "")


# ── Tools：基础执行 ───────────────────────────────────────────────────────────
@mcp.tool()
async def ue_run_python(code: str, project_id: str = "", timeout: float = 60.0) -> str:
    """
    在运行中的 UE Editor 里执行 Python 代码（通过 Remote Execution 桥接）。
    适用：查询资产信息、创建 Blueprint、修改 Actor 属性、布置关卡等。
    前置：UE Editor 已运行，Remote Execution Server 已启用。
    """
    if not code.strip():
        return json.dumps({"success": False, "error": "code 不能为空"})
    result = await _ue_run(code, project_id=project_id, timeout=timeout)
    if result.get("success"):
        output = result.get("stdout") or result.get("result") or "执行成功（无输出）"
        return json.dumps({"success": True, "output": str(output)[:2000]})
    return json.dumps({"success": False, "error": result.get("error", "执行失败")})


@mcp.tool()
async def ue_call(command: str, project_id: str = "") -> str:
    """
    向 UE Editor 发送 UCP（Unreal Control Protocol）命令。
    适用：Actor 管理、资产操作、编辑器控制等高层操作。
    command 为 Python 表达式或 UCP 命令字符串。
    """
    result = await _ue_run(command, project_id=project_id)
    return json.dumps({
        "success": result.get("success", False),
        "output": str(result.get("stdout") or result.get("result") or "")[:2000],
        "error": result.get("error", ""),
    })


# ── Tools：Blueprint 生成 ─────────────────────────────────────────────────────
_BP_SYSTEM = """你是一个 Unreal Engine Blueprint 生成专家。
根据功能描述，生成可在 UE Editor 中执行的 Python 代码。

## 核心规则
1. 只输出 Python 代码，不要任何解释文字
2. 代码必须以 `import unreal` 开头
3. 每个操作完成后调用 `unreal.EditorAssetLibrary.save_asset(path)`
4. 最后一行 `print(f"✅ 完成：{path}")` 告知结果

## 常用模式
**新建 Blueprint 类：**
```python
import unreal
factory = unreal.BlueprintFactory()
factory.parent_class = unreal.load_class(None, "/Script/Engine.Actor")
asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
bp = asset_tools.create_asset("BP_MyActor", "/Game/Blueprints", unreal.Blueprint, factory)
unreal.EditorAssetLibrary.save_asset(bp.get_path_name())
print(f"✅ 已创建: {bp.get_path_name()}")
```

**修改 CDO 属性：**
```python
import unreal
bp = unreal.load_asset("/Game/Characters/BP_Player")
cdo = unreal.get_default_object(bp.generated_class())
cdo.set_editor_property("max_walk_speed", 600.0)
unreal.EditorAssetLibrary.save_asset(bp.get_path_name())
print(f"✅ 已修改: {bp.get_path_name()}")
```"""


@mcp.tool()
async def ue_blueprint_gen(description: str, target_path: str = "/Game/Blueprints", project_id: str = "") -> str:
    """
    根据功能描述在 UE Editor 中生成 Blueprint。
    LLM 生成 UE Python 代码 → 通过 Remote Execution 写入 Editor。
    description: Blueprint 功能描述，如「创建一个可以拾取的道具 Actor」
    target_path: 保存路径，默认 /Game/Blueprints
    """
    user_prompt = f"目标路径：{target_path}\n功能描述：{description}"
    code = await _llm_generate(_BP_SYSTEM, user_prompt)
    # 提取代码块
    if "```python" in code:
        code = code.split("```python")[1].split("```")[0].strip()
    elif "```" in code:
        code = code.split("```")[1].split("```")[0].strip()

    result = await _ue_run(code, project_id=project_id, timeout=90.0)
    return json.dumps({
        "success": result.get("success", False),
        "description": description,
        "target_path": target_path,
        "generated_code": code[:500] + "..." if len(code) > 500 else code,
        "output": str(result.get("stdout") or result.get("result") or "")[:1000],
        "error": result.get("error", ""),
    })


# ── Tools：关卡生成 ───────────────────────────────────────────────────────────
_LEVEL_SYSTEM = """你是一个 Unreal Engine 关卡布局生成专家。
根据设计描述，生成可在 UE Editor 中执行的 Python 布局脚本。

## 核心规则
1. 只输出 Python 代码，不要任何解释文字
2. 代码以 `import unreal` 开头
3. 最后调用 `unreal.EditorLoadingAndSavingUtils.save_current_level()`
4. 最后一行 `print(f"✅ 布置完成，共放置 {n} 个 Actor")`

## 坐标系
- UE 单位 = 1cm，Z 轴朝上
- 地面 Z = 0，常用地面格 400×400cm

## 示例：铺设地面
```python
import unreal
els = unreal.EditorLevelLibrary
mesh = unreal.load_asset("/Game/StarterContent/Architecture/Floor_400x400")
for r in range(4):
    for c in range(4):
        a = els.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(c*400, r*400, 0))
        a.static_mesh_component.set_static_mesh(mesh)
unreal.EditorLoadingAndSavingUtils.save_current_level()
print("✅ 布置完成，共放置 16 个 Actor")
```"""


@mcp.tool()
async def ue_level_gen(description: str, project_id: str = "") -> str:
    """
    根据关卡设计描述在 UE Editor 中自动布置关卡。
    LLM 生成布局 Python 代码 → 通过 Remote Execution 写入 Editor。
    description: 关卡设计描述，如「一个 20×20 的室外竞技场，有四个角落的掩体」
    """
    code = await _llm_generate(_LEVEL_SYSTEM, f"关卡设计描述：{description}")
    if "```python" in code:
        code = code.split("```python")[1].split("```")[0].strip()
    elif "```" in code:
        code = code.split("```")[1].split("```")[0].strip()

    result = await _ue_run(code, project_id=project_id, timeout=120.0)
    return json.dumps({
        "success": result.get("success", False),
        "description": description,
        "output": str(result.get("stdout") or result.get("result") or "")[:1000],
        "error": result.get("error", ""),
    })


# ── Tools：编译 / 打包 / 截图 ─────────────────────────────────────────────────
@mcp.tool()
async def ue_compile_check(project_id: str = "") -> str:
    """
    触发 UE 项目编译检查（UBT），返回编译结果和错误信息。
    适用：代码变更后验证编译是否通过。
    """
    code = """
import unreal
result = unreal.PythonScriptLibrary.execute_console_command("RECOMPILE", unreal.EditorLevelLibrary.get_editor_world())
print(f"编译触发完成: {result}")
"""
    res = await _ue_run(code, project_id=project_id, timeout=300.0)
    return json.dumps({
        "success": res.get("success", False),
        "output": str(res.get("stdout") or res.get("result") or "")[:2000],
        "error": res.get("error", ""),
    })


@mcp.tool()
async def ue_screenshot(save_path: str = "", project_id: str = "") -> str:
    """
    截取 UE Editor 视口截图。
    save_path: 截图保存路径（可选，默认保存到项目 Saved/Screenshots 目录）
    """
    if save_path:
        code = f'import unreal; unreal.AutomationLibrary.take_high_res_screenshot(1920, 1080, "{save_path}"); print("截图完成: {save_path}")'
    else:
        code = 'import unreal; unreal.PythonScriptLibrary.execute_console_command("HighResShot 1920x1080", unreal.EditorLevelLibrary.get_editor_world()); print("截图已保存到 Saved/Screenshots")'
    res = await _ue_run(code, project_id=project_id, timeout=30.0)
    return json.dumps({
        "success": res.get("success", False),
        "output": str(res.get("stdout") or res.get("result") or "")[:500],
        "error": res.get("error", ""),
    })


@mcp.tool()
async def ue_playtest(map_path: str = "", project_id: str = "") -> str:
    """
    在 UE Editor 中启动 PIE（Play In Editor）模式进行自动化测试。
    map_path: 要测试的地图路径（可选，使用当前打开的地图）
    """
    if map_path:
        code = f"""
import unreal
unreal.EditorLoadingAndSavingUtils.load_map("{map_path}")
unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).play_from_here(unreal.Vector(0,0,0), unreal.Rotator(0,0,0))
print("PIE 启动完成")
"""
    else:
        code = """
import unreal
unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).play_from_here(unreal.Vector(0,0,0), unreal.Rotator(0,0,0))
print("PIE 启动完成")
"""
    res = await _ue_run(code, project_id=project_id, timeout=60.0)
    return json.dumps({
        "success": res.get("success", False),
        "output": str(res.get("stdout") or res.get("result") or "")[:1000],
        "error": res.get("error", ""),
    })


# ── 入口 ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    mcp.run()

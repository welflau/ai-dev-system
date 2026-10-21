"""
LaunchUEEditorAction — 启动 UE Editor 并等待就绪

AI 判断需要打开 UE 工程时调用。调用 editor-launch 端点后台启动进程，
轮询 UCP 端口直到 Editor 就绪（或超时），返回状态给 AI 继续操作。
"""
from typing import Any, Dict
from actions.base import ActionBase, ActionResult


class LaunchUEEditorAction(ActionBase):

    @property
    def name(self) -> str:
        return "launch_ue_editor"

    @property
    def description(self) -> str:
        return "启动 UE Editor 并打开当前项目。Editor 未运行时先调此工具，再用 ue_call 操作场景。"

    # 仅对 UE 项目暴露
    available_for_traits = {"any_of": ["engine:ue5", "engine:ue4"]}

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "启动 UE Editor 并打开当前项目的 .uproject 文件。"
                "Editor 还没有运行时必须先调此工具，再调 ue_call 执行场景操作。"
                "启动后会等待 Editor 就绪（最多 3 分钟）。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {},
            },
        }

    async def run(self, params: Dict[str, Any]) -> ActionResult:
        import asyncio
        import httpx
        from database import db
        from git_manager import git_manager

        project_id = params.get("project_id")
        if not project_id:
            return ActionResult(success=False, error="缺少 project_id，无法启动 Editor")

        # 1. 先检查 Editor 是否已在运行
        try:
            status_resp = await httpx.AsyncClient(timeout=5).get(
                f"http://localhost:8000/api/projects/{project_id}/ue-framework/editor-status"
            )
            if status_resp.status_code == 200:
                st = status_resp.json()
                if st.get("ucp_connected"):
                    return ActionResult(success=True, data={
                        "type": "ue_editor_ready",
                        "message": "UE Editor 已运行且 UCP 已连接，可直接使用 ue_call 操作。",
                        "ucp_connected": True,
                    })
        except Exception:
            pass

        # 2. 触发启动
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                launch_resp = await client.post(
                    f"http://localhost:8000/api/projects/{project_id}/ue-framework/editor-launch"
                )
                if launch_resp.status_code != 200:
                    return ActionResult(
                        success=False,
                        error=f"启动失败: {launch_resp.text[:300]}",
                    )
                launch_data = launch_resp.json()
        except Exception as e:
            return ActionResult(success=False, error=f"启动请求异常: {e}")

        # 3. 轮询等待 UCP 就绪（最多 180 秒）
        for i in range(36):
            await asyncio.sleep(5)
            try:
                async with httpx.AsyncClient(timeout=5) as client:
                    st_resp = await client.get(
                        f"http://localhost:8000/api/projects/{project_id}/ue-framework/editor-status"
                    )
                    if st_resp.status_code == 200:
                        st = st_resp.json()
                        if st.get("ucp_connected"):
                            return ActionResult(success=True, data={
                                "type": "ue_editor_ready",
                                "message": f"UE Editor 已就绪（等待 {(i+1)*5}s），现在可以使用 ue_call。",
                                "ucp_connected": True,
                                "uproject": launch_data.get("uproject", ""),
                            })
            except Exception:
                pass

        return ActionResult(success=True, data={
            "type": "ue_editor_launching",
            "message": (
                "UE Editor 正在启动（超过 3 分钟未就绪）。"
                "可能原因：首次编译 Shader、项目较大、或 UCP 插件未启用。\n"
                "请确认：Edit → Project Settings → Plugins → Python → Enable Remote Execution Server 已勾选，"
                "然后重试。"
            ),
            "ucp_connected": False,
        })

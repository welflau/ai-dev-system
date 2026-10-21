"""
UECallAction — 向 UE Editor 发送任意 UCP 命令

ChatAssistant 专用的通用 UCP 执行工具。
LLM 通过 read_local_file 读取 SKILL.md 获得 API 知识后，
用本工具执行任意 UCP 命令（object / function / params）。

只对 engine:ue5 / engine:ue4 项目暴露。
"""
import asyncio
import json
import logging
import struct
from typing import Any, Dict, Optional

from actions.base import ActionBase, ActionResult

logger = logging.getLogger("actions.chat.ue_call")

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 9876
_DEFAULT_TIMEOUT = 15.0
_RESPONSE_MAX_CHARS = 8000


class UECallAction(ActionBase):

    # 只对 UE 项目暴露
    available_for_traits = {"any_of": ["engine:ue5", "engine:ue4"]}

    @property
    def name(self) -> str:
        return "ue_call"

    @property
    def description(self) -> str:
        return "向正在运行的 UE Editor 发送 UCP 命令"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "向正在运行的 Unreal Engine Editor 发送 UCP（UnrealClientProtocol）命令。\n"
                "需要：Editor 已打开 + UCP 插件已启用（Edit → Plugins → UnrealClientProtocol）。\n"
                "object/function/params 的具体值从 SKILL.md 文档里获取（先用 read_local_file 加载对应 Skill）。\n"
                "示例：获取场景所有 Actor → object=/Script/UnrealEd.Default__EditorActorSubsystem, function=GetAllLevelActors"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "object": {
                        "type": "string",
                        "description": "UObject 路径，如 /Script/UnrealEd.Default__EditorActorSubsystem",
                    },
                    "function": {
                        "type": "string",
                        "description": "UFunction 名，如 GetAllLevelActors、SpawnActorFromClass",
                    },
                    "params": {
                        "type": "object",
                        "description": "函数参数（可省略）。Out 参数无需传入，会自动返回。",
                    },
                },
                "required": ["object", "function"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        obj      = (context.get("object") or "").strip()
        function = (context.get("function") or "").strip()
        params   = context.get("params") or {}
        host     = context.get("ucp_host", _DEFAULT_HOST)
        port     = int(context.get("ucp_port", _DEFAULT_PORT))
        timeout  = float(context.get("ucp_timeout", _DEFAULT_TIMEOUT))

        if not obj:
            return ActionResult(success=False, error="object 不能为空")
        if not function:
            return ActionResult(success=False, error="function 不能为空")

        command: Dict[str, Any] = {"object": obj, "function": function}
        if params:
            command["params"] = params

        logger.info("[ue_call] %s::%s", obj.split(".")[-1], function)

        try:
            resp = await _ucp_call(host, port, command, timeout)
        except ConnectionRefusedError:
            return _editor_not_running(host, port)
        except OSError as e:
            if "refused" in str(e).lower() or "10061" in str(e):
                return _editor_not_running(host, port)
            return ActionResult(success=False, error=f"UCP 连接失败: {e}")
        except asyncio.TimeoutError:
            return ActionResult(
                success=False,
                error=f"UCP 超时（{timeout}s）—— Editor 响应慢或已无响应，请检查 Editor 状态",
            )
        except Exception as e:
            logger.warning("[ue_call] 异常: %s", e)
            return ActionResult(success=False, error=f"UCP 调用异常: {e}")

        success = resp.get("success", False)
        result  = resp.get("result")
        error   = resp.get("error", "")
        log     = resp.get("log", [])

        # 截断过长的结果
        result_str = json.dumps(result, ensure_ascii=False) if result is not None else ""
        if len(result_str) > _RESPONSE_MAX_CHARS:
            result_str = result_str[:_RESPONSE_MAX_CHARS] + f" ...[已截断，共 {len(result_str)} 字符]"
            result = {"_truncated": True, "_preview": result_str}

        return ActionResult(
            success=success,
            data={
                "success": success,
                "result": result,
                "error": error,
                "log": log[:20] if log else [],   # 最多保留 20 条日志
            },
            message=(
                f"UCP 成功: {function}" if success
                else f"UCP 失败: {error or '未知错误'}"
            ),
        )


# ── TCP 通信 ──────────────────────────────────────────────

async def _ucp_call(host: str, port: int, command: Dict, timeout: float) -> Dict:
    body  = json.dumps(command, ensure_ascii=False).encode("utf-8")
    frame = struct.pack("<I", len(body)) + body

    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(host, port),
        timeout=timeout,
    )
    try:
        writer.write(frame)
        await writer.drain()

        raw_len  = await asyncio.wait_for(reader.readexactly(4), timeout=timeout)
        resp_len = struct.unpack("<I", raw_len)[0]
        raw_body = await asyncio.wait_for(reader.readexactly(resp_len), timeout=timeout)
        return json.loads(raw_body.decode("utf-8"))
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


def _editor_not_running(host: str, port: int) -> ActionResult:
    return ActionResult(
        success=False,
        data={"status": "editor_not_running"},
        error=(
            f"无法连接 UE Editor（{host}:{port}）。\n"
            "请确认：\n"
            "1. Unreal Editor 已打开\n"
            "2. Edit → Plugins → 搜索 UnrealClientProtocol → 已启用并重启过 Editor\n"
            "3. 防火墙未拦截本地 9876 端口"
        ),
    )

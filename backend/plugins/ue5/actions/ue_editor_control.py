"""
UEEditorControlAction — 通过 UnrealClientProtocol (UCP) TCP 桥接操控 UE Editor

协议：4 字节小端长度前缀 + UTF-8 JSON 体
默认端口：127.0.0.1:9876

命令格式：
    {"object": "<uobject_path>", "function": "<ufunction_name>", "params": {...}}

响应格式：
    {"success": bool, "result": <any>, "error": "...", "log": [...]}

常用对象路径：
    Actor 管理：/Script/UnrealEd.Default__EditorActorSubsystem
    Property R/W：/Script/UnrealClientProtocol.Default__ObjectOperationLibrary
    关卡信息：/Script/Engine.Default__KismetSystemLibrary

输入 context:
    op              操作名（见下方 OP 映射），或直接传 raw_command
    args            操作参数（dict），根据 op 不同含义不同
    raw_command     直接传完整 UCP JSON 命令（与 op 互斥）
    ucp_host        UCP 监听地址（默认 127.0.0.1）
    ucp_port        UCP 监听端口（默认 9876）
    ucp_timeout     TCP 超时秒数（默认 10）
    project_id      所属项目 ID（用于 git stash 安全兜底）

支持的 op：
    get_actors          取当前关卡所有 Actor
    get_actors_of_class 取指定 class 的 Actor（args: class_path）
    get_property        读 UObject 属性（args: object_path, property_name）
    set_property        写 UObject 属性（args: object_path, property_name, value）—— 自动 git stash 兜底
    spawn_actor         Spawn Actor（args: class_path, location, rotation）
    destroy_actor       删除 Actor（args: object_path）
    call                原始 UCP 调用（args: object, function, params）
"""
from __future__ import annotations

import asyncio
import json
import logging
import struct
from typing import Any, Dict, Optional

from actions.base import ActionBase, ActionResult

logger = logging.getLogger("actions.ue_editor_control")

# UCP 对象路径常量
_ACTOR_SUB  = "/Script/UnrealEd.Default__EditorActorSubsystem"
_OBJ_LIB    = "/Script/UnrealClientProtocol.Default__ObjectOperationLibrary"
_KISMET_SYS = "/Script/Engine.Default__KismetSystemLibrary"


class UEEditorControlAction(ActionBase):
    """通过 UCP TCP 桥接操控 UE Editor（需 Editor 开着且 UCP 插件已启用）"""

    available_for_traits = {"any_of": ["engine:ue5", "engine:ue4"]}

    @property
    def name(self) -> str:
        return "ue_editor_control"

    @property
    def description(self) -> str:
        return "通过 UnrealClientProtocol 操控正在运行的 UE Editor（读写 Actor/属性/蓝图）"

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        host    = context.get("ucp_host", "127.0.0.1")
        port    = int(context.get("ucp_port", 9876))
        timeout = float(context.get("ucp_timeout", 10))

        # 构建 UCP 命令
        raw_cmd = context.get("raw_command")
        if raw_cmd:
            command = raw_cmd
        else:
            op   = context.get("op", "")
            args = context.get("args") or {}
            command = self._build_command(op, args)
            if command is None:
                return ActionResult(
                    success=False,
                    data={"status": "error", "error": f"未知 op: {op}"},
                    message=f"未知操作: {op}",
                )

        logger.info("[UCP] %s:%d op=%s", host, port, context.get("op", "raw"))

        # 写操作前 git stash 兜底
        project_id  = context.get("project_id")
        is_write    = context.get("op") in ("set_property", "destroy_actor", "spawn_actor")
        stash_ref   = None
        if is_write and project_id:
            stash_ref = await self._git_stash_before(project_id)

        try:
            resp = await self._ucp_call(host, port, command, timeout)
        except ConnectionRefusedError:
            return _editor_not_running()
        except OSError as e:
            if "refused" in str(e).lower() or "10061" in str(e):
                return _editor_not_running()
            return ActionResult(
                success=False,
                data={"status": "error", "error": str(e)},
                message=f"UCP 连接失败: {e}",
            )
        except asyncio.TimeoutError:
            return ActionResult(
                success=False,
                data={"status": "timeout"},
                message=f"UCP 超时（{timeout}s）—— Editor 响应慢或已无响应",
            )

        success = resp.get("success", False)
        result  = resp.get("result")
        error   = resp.get("error", "")
        log     = resp.get("log", [])

        if log:
            for line in log:
                logger.debug("[UCP log] %s", line)

        if not success and stash_ref:
            # 写操作失败 → 自动 pop stash
            await self._git_stash_pop(project_id, stash_ref)

        return ActionResult(
            success=success,
            data={
                "status": "success" if success else "error",
                "result": result,
                "error":  error,
                "log":    log,
            },
            message=f"UCP {'成功' if success else '失败'}: {error or (str(result)[:80] if result else 'ok')}",
        )

    # ==================== 命令构建 ====================

    def _build_command(self, op: str, args: Dict[str, Any]) -> Optional[Dict]:
        """把高层 op 映射到 UCP JSON 命令"""
        if op == "get_actors":
            return {"object": _ACTOR_SUB, "function": "GetAllLevelActors"}

        if op == "get_actors_of_class":
            return {
                "object": _ACTOR_SUB,
                "function": "GetAllLevelActorsOfClass",
                "params": {"ActorClass": args.get("class_path", "/Script/Engine.Actor")},
            }

        if op == "get_property":
            return {
                "object": _OBJ_LIB,
                "function": "GetObjectPropertyValue",
                "params": {
                    "ObjectPath":    args["object_path"],
                    "PropertyName":  args["property_name"],
                },
            }

        if op == "set_property":
            return {
                "object": _OBJ_LIB,
                "function": "SetObjectPropertyValue",
                "params": {
                    "ObjectPath":    args["object_path"],
                    "PropertyName":  args["property_name"],
                    "ValueAsString": str(args["value"]),
                },
            }

        if op == "spawn_actor":
            return {
                "object": _ACTOR_SUB,
                "function": "SpawnActorFromClass",
                "params": {
                    "ActorClass": args["class_path"],
                    "Location":   args.get("location", {"X": 0, "Y": 0, "Z": 0}),
                    "Rotation":   args.get("rotation", {"Pitch": 0, "Yaw": 0, "Roll": 0}),
                },
            }

        if op == "destroy_actor":
            return {
                "object": _ACTOR_SUB,
                "function": "DestroyActor",
                "params": {"ActorToDestroy": args["object_path"]},
            }

        if op == "call":
            # 原始 call：直接透传 object/function/params
            cmd: Dict[str, Any] = {
                "object":   args["object"],
                "function": args["function"],
            }
            if "params" in args:
                cmd["params"] = args["params"]
            return cmd

        return None

    # ==================== TCP 通信 ====================

    async def _ucp_call(
        self,
        host: str,
        port: int,
        command: Dict[str, Any],
        timeout: float,
    ) -> Dict[str, Any]:
        """4 字节小端长度前缀 + UTF-8 JSON，单次请求-响应"""
        body = json.dumps(command, ensure_ascii=False).encode("utf-8")
        frame = struct.pack("<I", len(body)) + body

        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout,
        )
        try:
            writer.write(frame)
            await writer.drain()

            # 读响应长度（4 字节）
            raw_len = await asyncio.wait_for(reader.readexactly(4), timeout=timeout)
            resp_len = struct.unpack("<I", raw_len)[0]

            # 读响应体
            raw_body = await asyncio.wait_for(reader.readexactly(resp_len), timeout=timeout)
            return json.loads(raw_body.decode("utf-8"))
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    # ==================== Git 安全兜底 ====================

    async def _git_stash_before(self, project_id: str) -> Optional[str]:
        try:
            from git_manager import git_manager
            rc, out, _ = await git_manager._run_git(
                git_manager._repo_path(project_id),
                "stash", "push", "-m", "ai-ucp-before-write",
            )
            if rc == 0 and "Saved" in out:
                logger.info("[UCP] git stash saved before write op")
                return "stash"
        except Exception as e:
            logger.warning("[UCP] git stash 失败（非致命）: %s", e)
        return None

    async def _git_stash_pop(self, project_id: str, stash_ref: str) -> None:
        try:
            from git_manager import git_manager
            await git_manager._run_git(
                git_manager._repo_path(project_id),
                "stash", "pop",
            )
            logger.info("[UCP] git stash pop（写操作失败回滚）")
        except Exception as e:
            logger.warning("[UCP] git stash pop 失败: %s", e)


# ==================== 健康检查（供其他模块调用）====================

async def probe_ucp(host: str = "127.0.0.1", port: int = 9876, timeout: float = 2.0) -> bool:
    """快速探测 UCP 是否可达（不执行任何操作）"""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout,
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True
    except Exception:
        return False


def _editor_not_running() -> ActionResult:
    return ActionResult(
        success=False,
        data={"status": "editor_not_running"},
        message="UE Editor 未运行或 UCP 插件未启用。请先打开 Editor 并确认插件已加载（Edit → Plugins → UnrealClientProtocol）。",
    )

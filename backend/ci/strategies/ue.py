"""UE 项目 CI 策略（v0.19.x Phase C）

跟 Web 完全不同的 pipeline：
  UBT 编译 → Automation 测试 → Package（Editor / Client / Server）

环境也跟 Web 完全不同：
  editor_live（UE Editor 进程状态）/ packaged_win64（打包产物目录） / dedicated_server

priority=100，高于 Web 的 50，让 UE 项目优先命中这里。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from ci.strategies.base import (
    BuildTypeSpec,
    CIStrategy,
    EnvSpec,
    PipelineStage,
)

logger = logging.getLogger("ci.strategies.ue")


class UECIStrategy(CIStrategy):
    name = "ue"
    required_traits = {"any_of": ["engine:ue5", "engine:ue4"]}
    priority = 100

    # ========== 元数据 ==========

    def pipeline_stages(self) -> List[PipelineStage]:
        return [
            PipelineStage(
                id="ubt_compile", name="UBT 编译", icon="🔧",
                description="UnrealBuildTool 编译 Editor target（复用 UECompileCheckAction）",
                blocking=True,
            ),
            PipelineStage(
                id="take_screenshot", name="运行截图", icon="📸",
                description="启动游戏截效果图（需 GPU，首次启动 1-3 分钟）",
                blocking=False,
            ),
            PipelineStage(
                id="playtest", name="Automation 测试", icon="🎮",
                description="headless UnrealEditor-Cmd 跑 Automation Framework（复用 UEPlaytestAction）",
                blocking=False,
            ),
            PipelineStage(
                id="package_client", name="打包 Client", icon="🎯",
                description="RunUAT BuildCookRun 产出 Shipping Client",
                blocking=False,
            ),
            PipelineStage(
                id="package_server", name="打包 Server", icon="🖥️",
                description="DedicatedServer 打包（需要 Target.cs 含 Server 类型）",
                blocking=False,
            ),
        ]

    def environment_specs(self) -> List[EnvSpec]:
        return [
            EnvSpec(
                name="editor_live", display_name="Editor 进程", branch_binding=None,
                icon="⚡",
                description="UE Editor 进程是否开启（v0.20 UCP 接入后可精准反映）",
                can_deploy=False, can_stop=False,
            ),
            EnvSpec(
                name="packaged_win64", display_name="打包 Win64 Client",
                branch_binding="main", icon="📦",
                description="Shipping 客户端产物（RunUAT Archive 目录）",
            ),
            EnvSpec(
                name="dedicated_server", display_name="Dedicated Server",
                branch_binding="main", icon="🖥️",
                description="DedicatedServer 产物（Target.cs 含 Server 类型才可用）",
                can_deploy=True, can_stop=True,
            ),
        ]

    def build_types(self) -> List[BuildTypeSpec]:
        return [
            BuildTypeSpec(
                id="ubt_compile", display_name="编译 (UBT)", icon="🔧",
                description="只跑 UBT 编译 Editor target",
            ),
            BuildTypeSpec(
                id="take_screenshot", display_name="运行截图", icon="📸",
                description="启动游戏截效果图（需要 GPU，首次 1-3 分钟）",
            ),
            BuildTypeSpec(
                id="playtest", display_name="跑 Automation", icon="🎮",
                description="headless 跑 Automation 测试（默认 filter Project.）",
            ),
            BuildTypeSpec(
                id="package_client", display_name="打包 Client", icon="📦",
                description="RunUAT BuildCookRun Win64 Shipping（10-30 min）",
            ),
        ]

    # ========== 运行期 ==========

    async def trigger_build(
        self, project_id: str, build_type: str, trigger: str = "manual", **kwargs
    ) -> Dict[str, Any]:
        """触发 UE 构建。

        UE 的 "build" 跟 Web 不同：不走 ci_builds 表自动调度器，
        而是直接异步跑对应 Action。结果通过 SSE 推到前端日志面板。

        为了让前端构建历史可查，也会往 ci_builds 表插一条记录。
        """
        from models import CIBuildStatus
        from database import db
        from utils import generate_id, now_iso
        from events import event_manager

        valid = {bt.id for bt in self.build_types()}
        if build_type not in valid:
            return {"error": f"UE 策略不支持 {build_type}；可选: {sorted(valid)}"}

        # 写 ci_builds 行（让构建历史可见）
        build_id = generate_id("ci-")
        await db.insert("ci_builds", {
            "id": build_id,
            "project_id": project_id,
            "build_type": build_type,
            "branch": "",  # UE 的构建不强绑分支
            "status": CIBuildStatus.PENDING.value,
            "trigger": trigger,
            "created_at": now_iso(),
        })

        await event_manager.publish_to_project(project_id, "ci_build_started", {
            "build_id": build_id,
            "build_type": build_type,
            "trigger": trigger,
            "strategy": "ue",
        })

        # 异步跑
        import asyncio
        asyncio.create_task(self._run_build(build_id, project_id, build_type, kwargs))
        return {"build_id": build_id, "status": "pending", "strategy": "ue"}

    async def _run_build(
        self, build_id: str, project_id: str, build_type: str, kwargs: Dict
    ):
        """在后台异步跑构建 + 更新 ci_builds 状态"""
        import time
        import json
        from models import CIBuildStatus
        from database import db
        from utils import now_iso
        from events import event_manager

        await db.update("ci_builds", {
            "status": CIBuildStatus.RUNNING.value,
            "started_at": now_iso(),
        }, "id = ?", (build_id,))

        async def _log_cb(line: str):
            try:
                # 事件类型按 build_type 分派，前端既有订阅器能接住
                event_type = {
                    "ubt_compile": "ue_compile_log",
                    "playtest": "ue_playtest_log",
                    "package_client": "ue_package_log",
                    "package_server": "ue_package_log",
                    "take_screenshot": "ue_screenshot_log",
                }.get(build_type, "ci_build_log")
                await event_manager.publish_to_project(project_id, event_type, {"line": line})
            except Exception:
                pass

        data: Dict[str, Any] = {}
        logs = []
        try:
            if build_type == "ubt_compile":
                from actions.ue_compile_check import UECompileCheckAction
                result = await UECompileCheckAction().run({
                    "project_id": project_id,
                    "log_callback": _log_cb,
                    **kwargs,
                })
                data = result.data or {}
                logs.append({"step": "ubt_compile", "passed": data.get("status") == "success"})

            elif build_type == "playtest":
                from actions.ue_playtest import UEPlaytestAction
                result = await UEPlaytestAction().run({
                    "project_id": project_id,
                    "log_callback": _log_cb,
                    **kwargs,
                })
                data = result.data or {}
                logs.append({"step": "playtest", "passed": data.get("status") == "success"})

            elif build_type == "take_screenshot":
                from actions.ue_screenshot import UEScreenshotAction
                result = await UEScreenshotAction().run({
                    "project_id": project_id,
                    "log_callback": _log_cb,
                    **kwargs,
                })
                data = result.data or {}
                shots = data.get("screenshots") or []
                logs.append({
                    "step": "take_screenshot",
                    "passed": data.get("status") == "success",
                    "screenshots": shots,
                })
                # 截图成功 → 把结果图持久化到项目聊天（让 AI 助手面板显示）
                if shots:
                    await self._save_screenshot_to_chat(project_id, shots, build_id)

            elif build_type == "package_client":
                from actions.ue_package import UEPackageAction
                result = await UEPackageAction().run({
                    "project_id": project_id,
                    "log_callback": _log_cb,
                    "platform": kwargs.get("platform", "Win64"),
                    "configuration": kwargs.get("configuration", "Shipping"),
                    **kwargs,
                })
                data = result.data or {}
                logs.append({"step": "package_client", "passed": data.get("status") == "success"})

            else:
                raise RuntimeError(f"unsupported ue build_type: {build_type}")

            status = (
                CIBuildStatus.SUCCESS.value
                if data.get("status") == "success"
                else CIBuildStatus.FAILED.value
            )
            err_msgs = data.get("errors") or []
            # 末尾 8KB stdout 存进 raw_output_tail，供前端"详情"弹窗显示
            raw_tail = (data.get("raw_tail") or data.get("partial_output") or "")[-8192:]
            raw_head = (data.get("raw_head") or "")[:2048]
            raw_output = (raw_head + "\n...\n" + raw_tail).strip() if raw_head and raw_tail else (raw_head or raw_tail)
            await db.update("ci_builds", {
                "status": status,
                "build_log": json.dumps(logs, ensure_ascii=False),
                "error_message": "; ".join(
                    f"{(e.get('file') or '?').split(chr(92))[-1]}:{e.get('line', '?')} {e.get('code', '')} {(e.get('msg') or '')[:80]}"
                    for e in err_msgs[:3]
                )[:500] if status == CIBuildStatus.FAILED.value else None,
                "raw_output_tail": raw_output[:10240] if raw_output else None,
                "completed_at": now_iso(),
            }, "id = ?", (build_id,))

            await event_manager.publish_to_project(project_id, "ci_build_completed", {
                "build_id": build_id,
                "build_type": build_type,
                "status": "success" if status == CIBuildStatus.SUCCESS.value else "failed",
                "strategy": "ue",
            })

            # v0.19.x 主动诊断：编译失败时 AI 助手主动写诊断消息到项目聊天
            if status == CIBuildStatus.FAILED.value:
                await self._proactive_diagnose(project_id, build_type, data, build_id)

        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            logger.error("UE %s build 异常: %s\n%s", build_type, repr(e), tb)
            err_msg = f"{type(e).__name__}: {e}"
            await db.update("ci_builds", {
                "status": CIBuildStatus.FAILED.value,
                "error_message": err_msg[:500],
                "completed_at": now_iso(),
            }, "id = ?", (build_id,))
            await event_manager.publish_to_project(project_id, "ci_build_failed", {
                "build_id": build_id,
                "build_type": build_type,
                "error_message": err_msg,
            })
            # 异常情况也主动通知
            await self._proactive_diagnose(project_id, build_type, {"status": "error", "message": err_msg}, build_id)

    async def _save_screenshot_to_chat(
        self, project_id: str, shot_paths: List[str], build_id: str
    ):
        """截图成功后把结果图写到项目 AI 助手聊天，刷新后可见"""
        try:
            from api.chat import _save_chat_message
            from pathlib import Path as _P

            img_urls = []
            for p in shot_paths[:3]:
                fname = _P(p).name
                img_urls.append(f"/api/projects/{project_id}/screenshots/{fname}")

            content = f"📸 **Editor 截图完成**（build `{build_id[:12]}`）"
            action = {
                "type": "ue_screenshot_result",
                "screenshots": img_urls,
                "local_paths": shot_paths,
                "project_id": project_id,
                "build_id": build_id,
            }
            await _save_chat_message(
                project_id=project_id,
                role="assistant",
                content=content,
                action=action,
            )
            logger.info("📸 截图消息已写入项目聊天 [%s]: %d 张", project_id[:8], len(img_urls))
        except Exception as e:
            logger.warning("截图消息写入聊天失败（忽略）: %s", e)

    async def _proactive_diagnose(
        self, project_id: str, build_type: str, data: Dict[str, Any], build_id: str
    ):
        """v0.19.x 主动诊断：构建失败后 AI 助手主动分析错误 + 写进项目聊天

        不调用 LLM（成本控制），用规则引擎基于结构化 errors 快速生成可读诊断。
        聊天消息类型 ci_build_diagnosis，前端渲染为 AI 消息 + "创建修复工单" 按钮。
        """
        try:
            from api.chat import _save_chat_message

            errors = data.get("errors") or []
            warnings = data.get("warnings") or []
            status = data.get("status", "error")
            raw_msg = data.get("message", "")

            # ---- 基于规则生成诊断文本（不调 LLM，毫秒级）----
            type_label = {
                "ubt_compile": "UBT 编译",
                "playtest": "Automation 测试",
                "package_client": "RunUAT 打包",
            }.get(build_type, build_type)

            if status == "error" or (not errors and raw_msg):
                # 早期失败（引擎找不到 / uproject 缺失等）
                intro = f"⚠️ {type_label}**启动失败**——不是代码错误，是环境/配置问题。"
                body = f"\n**原因**：{raw_msg[:300]}" if raw_msg else ""
                suggest = "\n\n建议检查：引擎路径是否正确、`.uproject` 是否存在、UBT.exe 有无权限。"
            elif errors:
                # C++ / UHT 编译错误
                intro = f"❌ {type_label}**失败**，共 {len(errors)} 个错误 / {len(warnings)} 个警告。"
                body = "\n\n**主要错误**：\n"
                for e in errors[:5]:
                    fname = (e.get("file") or "?").replace("\\", "/").split("/")[-1]
                    line = e.get("line") or "?"
                    code = e.get("code") or ""
                    msg = (e.get("msg") or "")[:160]
                    cat = e.get("category") or ""
                    body += f"- `{fname}:{line}` **{code}**（{cat}）{msg}\n"
                if len(errors) > 5:
                    body += f"- ……还有 {len(errors) - 5} 个错误\n"
                suggest = "\n\n**我可以帮你修复**——点下方按钮让 DevAgent 分析并自动修复代码。"
            else:
                intro = f"✅ {type_label}通过（{data.get('duration_ms', 0) // 1000}s）"
                body = ""
                suggest = ""

            content = intro + body + suggest

            # 诊断 action 卡片（前端渲染时显示"创建修复工单"按钮）
            action = {
                "type": "ci_build_diagnosis",
                "build_id": build_id,
                "build_type": build_type,
                "status": status,
                "errors": errors[:10],
                "error_count": len(errors),
                "warning_count": len(warnings),
                "project_id": project_id,
                "has_errors": len(errors) > 0,
            }

            await _save_chat_message(
                project_id=project_id,
                role="assistant",
                content=content,
                action=action,
            )
            logger.info(
                "🤖 主动诊断消息已写入项目聊天 [%s] %s: %d errors",
                project_id[:8], build_type, len(errors),
            )
        except Exception as e:
            import traceback
            logger.warning("主动诊断消息写入失败（忽略）: %s\n%s", repr(e), traceback.format_exc())

    async def deploy_environment(
        self, project_id: str, env_name: str, **kwargs
    ) -> Dict[str, Any]:
        """UE 的"部署"就是打包。deployEnv('packaged_win64') → 触发 package_client 构建"""
        if env_name == "packaged_win64":
            return await self.trigger_build(project_id, "package_client", trigger="manual", **kwargs)
        if env_name == "dedicated_server":
            return await self.trigger_build(project_id, "package_client", trigger="manual",
                                            platform=kwargs.get("platform", "Win64"),
                                            configuration="Shipping",
                                            **kwargs)
        if env_name == "editor_live":
            return {"error": "editor_live 不支持手动部署，由 UE Editor 自身控制"}
        return {"error": f"UE 策略不支持环境 {env_name}"}

    async def stop_environment(
        self, project_id: str, env_name: str
    ) -> Dict[str, Any]:
        # UE 项目通常不需要 stop（打包产物就在磁盘上）；dedicated_server 未来可补
        return {"status": "not_supported", "env": env_name,
                "hint": "UE 产物无需 stop；若要停 DedicatedServer 实例请手动"}

    async def get_environment_status(
        self, project_id: str, env_name: str
    ) -> Dict[str, Any]:
        """UE 环境状态查询"""
        from pathlib import Path
        from database import db

        if env_name == "editor_live":
            # Phase C 占位：v0.20 UCP 接入后查 9876 端口判定 editor 是否开
            return {
                "status": "unknown",
                "hint": "UE Editor 进程状态检测需要 v0.20 UCP 插件集成",
            }

        if env_name in ("packaged_win64", "dedicated_server"):
            # 看 <uproject_dir>/Packaged/<platform>-<config> 目录
            from git_manager import git_manager
            repo_path = git_manager._repo_path(project_id)
            status: Dict[str, Any] = {"status": "inactive"}
            if repo_path and Path(repo_path).is_dir():
                platform = "Win64"
                config = "Shipping"
                archive_dir = Path(repo_path) / "Packaged" / f"{platform}-{config}"
                if archive_dir.is_dir() and any(archive_dir.iterdir()):
                    size = sum(
                        (p.stat().st_size for p in archive_dir.rglob("*") if p.is_file()),
                        start=0,
                    )
                    from datetime import datetime
                    mtime = archive_dir.stat().st_mtime
                    status = {
                        "status": "built",
                        "deploy_path": str(archive_dir),
                        "archive_size_bytes": size,
                        "last_deployed_at": datetime.fromtimestamp(mtime).isoformat(),
                    }
            return status

        return {"status": "not_found", "name": env_name}

    async def get_all_environments(self, project_id: str) -> List[Dict[str, Any]]:
        """给每个 env spec 查状态 + 合并 spec 元信息"""
        out = []
        for spec in self.environment_specs():
            s = await self.get_environment_status(project_id, spec.name)
            merged = {**spec.to_dict(), **s}
            out.append(merged)
        return out

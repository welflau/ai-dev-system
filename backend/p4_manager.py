"""
P4 (Perforce) 管理器
提供基础的 P4 操作：检测 P4 环境、checkout 文件（p4 edit）等。
手动挡下 AI 修改 P4 管理的文件前自动调用 p4 edit，不自动 submit。
"""
import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger("p4_manager")


class P4Manager:
    """P4 操作管理器（异步）"""

    # ── 环境检测 ──────────────────────────────────────────────

    async def p4_info(self, cwd: Optional[str] = None) -> Optional[dict]:
        """
        执行 p4 info，返回解析后的 dict。
        失败（未配置 / 无网络 / p4 不在 PATH）返回 None。
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "p4", "info",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            if proc.returncode != 0:
                logger.debug("p4 info 失败: %s", stderr.decode(errors="replace"))
                return None
            result = {}
            for line in stdout.decode(errors="replace").splitlines():
                if ": " in line:
                    key, _, value = line.partition(": ")
                    result[key.strip()] = value.strip()
            return result
        except (FileNotFoundError, asyncio.TimeoutError) as e:
            logger.debug("p4 info 异常（p4 未安装或超时）: %s", e)
            return None
        except Exception as e:
            logger.debug("p4 info 异常: %s", e)
            return None

    async def detect_p4_root(self, path: str) -> Optional[str]:
        """
        检测给定路径是否在 P4 workspace 下。
        返回 P4 client root 路径，否则返回 None。
        """
        info = await self.p4_info(cwd=path)
        if not info:
            return None
        client_root = info.get("Client root")
        if not client_root:
            return None
        # 验证 path 确实在 client root 下
        try:
            Path(path).relative_to(client_root)
            return client_root
        except ValueError:
            return None

    async def p4_where(self, file_path: str) -> Optional[str]:
        """
        执行 p4 where <file>，确认文件是否在 P4 depot 映射中。
        返回 depot 路径，否则返回 None。
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "p4", "where", file_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            if proc.returncode != 0:
                return None
            output = stdout.decode(errors="replace").strip()
            # p4 where 输出格式: //depot/path //client/path /local/path
            parts = output.split()
            if parts:
                return parts[0]  # depot path
            return None
        except (FileNotFoundError, asyncio.TimeoutError):
            return None
        except Exception as e:
            logger.debug("p4 where 异常: %s", e)
            return None

    # ── 文件操作 ──────────────────────────────────────────────

    async def p4_edit(self, file_path: str) -> tuple[bool, str]:
        """
        执行 p4 edit <file>，将文件 checkout 为可写。
        返回 (success: bool, message: str)。
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "p4", "edit", file_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
            out = stdout.decode(errors="replace").strip()
            err = stderr.decode(errors="replace").strip()

            if proc.returncode == 0:
                logger.info("✅ p4 edit 成功: %s | %s", file_path, out)
                return True, out
            else:
                msg = err or out
                logger.warning("⚠️ p4 edit 失败: %s | %s", file_path, msg)
                return False, msg

        except FileNotFoundError:
            msg = "p4 命令未找到，请确认 P4 已安装并在 PATH 中"
            logger.error(msg)
            return False, msg
        except asyncio.TimeoutError:
            msg = f"p4 edit 超时: {file_path}"
            logger.error(msg)
            return False, msg
        except Exception as e:
            msg = f"p4 edit 异常: {e}"
            logger.error(msg)
            return False, msg

    async def p4_add(self, file_path: str) -> tuple[bool, str]:
        """
        执行 p4 add <file>，将新文件加入 P4 管理。
        返回 (success: bool, message: str)。
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "p4", "add", file_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
            out = stdout.decode(errors="replace").strip()
            err = stderr.decode(errors="replace").strip()
            success = proc.returncode == 0
            return success, out if success else (err or out)
        except Exception as e:
            return False, str(e)

    async def p4_revert(self, file_path: str) -> tuple[bool, str]:
        """
        执行 p4 revert <file>，撤销 checkout。
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "p4", "revert", file_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
            out = stdout.decode(errors="replace").strip()
            success = proc.returncode == 0
            return success, out
        except Exception as e:
            return False, str(e)

    # ── 状态查询 ──────────────────────────────────────────────

    async def is_p4_managed(self, file_path: str) -> bool:
        """快速判断文件是否在 P4 管理下"""
        depot_path = await self.p4_where(file_path)
        return depot_path is not None

    async def is_checked_out(self, file_path: str) -> bool:
        """判断文件是否已 checkout（opened）"""
        try:
            proc = await asyncio.create_subprocess_exec(
                "p4", "opened", file_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            output = stdout.decode(errors="replace").strip()
            return bool(output) and "not opened" not in output
        except Exception:
            return False


# 全局单例
p4_manager = P4Manager()

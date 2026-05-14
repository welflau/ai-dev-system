"""
CreateGithubRepoAction — 在 GitHub 上创建仓库（通过 gh CLI）

默认创建到 AiDS-Projects 组织下，也可指定其他 org 或创建为个人仓库。
返回仓库 HTTPS URL，供 confirm_project 的 git_remote_url 字段使用。

前提：gh CLI 已安装且已 gh auth login。
"""
import asyncio
import logging
import re
from typing import Any, Dict

from actions.base import ActionBase, ActionResult

logger = logging.getLogger("actions.chat.create_github_repo")

DEFAULT_ORG = "AiDS-Projects"


class CreateGithubRepoAction(ActionBase):

    @property
    def name(self) -> str:
        return "create_github_repo"

    @property
    def description(self) -> str:
        return f"在 GitHub 上创建新仓库（默认在 {DEFAULT_ORG} 组织下），返回仓库 URL"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                f"在 GitHub {DEFAULT_ORG} 组织下创建一个新仓库，返回仓库 URL。\n"
                "当用户想新建项目但还没有 GitHub 仓库时调用，获得 URL 后再调用 confirm_project。\n"
                "需要本机已安装 gh CLI 并登录（gh auth login）。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "repo_name": {
                        "type": "string",
                        "description": "仓库名称，建议用 kebab-case，如 jump-game / my-web-app",
                    },
                    "description": {
                        "type": "string",
                        "description": "仓库描述（可选）",
                    },
                    "private": {
                        "type": "boolean",
                        "description": "是否私有仓库，默认 true",
                    },
                    "org": {
                        "type": "string",
                        "description": f"GitHub 组织名，默认 {DEFAULT_ORG}",
                    },
                },
                "required": ["repo_name"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        repo_name   = (context.get("repo_name") or "").strip()
        description = (context.get("description") or "").strip()
        private     = context.get("private", True)
        org         = (context.get("org") or DEFAULT_ORG).strip()

        if not repo_name:
            return ActionResult(success=False, error="repo_name 不能为空")

        # 简单清理：只允许字母数字和连字符
        repo_name = re.sub(r"[^a-zA-Z0-9._-]", "-", repo_name).strip("-")
        if not repo_name:
            return ActionResult(success=False, error="仓库名称包含非法字符，请使用字母/数字/连字符")

        full_name  = f"{org}/{repo_name}"
        visibility = "--private" if private else "--public"

        cmd = ["gh", "repo", "create", full_name, visibility]
        if description:
            cmd += ["--description", description]

        logger.info("创建 GitHub 仓库: %s", full_name)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            out = stdout.decode("utf-8", errors="replace").strip()
            err = stderr.decode("utf-8", errors="replace").strip()

            if proc.returncode != 0:
                logger.warning("gh repo create 失败: %s", err)
                return ActionResult(
                    success=False,
                    error=f"创建仓库失败：{err or '未知错误'}",
                )

            # gh 输出形如 https://github.com/AiDS-Projects/jump-game
            url = out.split("\n")[0].strip()
            if not url.startswith("https://"):
                url = f"https://github.com/{full_name}"

            # 补 .git 后缀（git clone 标准格式）
            git_url = url if url.endswith(".git") else url + ".git"

            logger.info("GitHub 仓库已创建: %s", git_url)
            return ActionResult(
                success=True,
                message=f"GitHub 仓库已创建：{git_url}",
                data={
                    "type":           "github_repo_created",
                    "repo_name":      repo_name,
                    "org":            org,
                    "full_name":      full_name,
                    "html_url":       url,
                    "git_remote_url": git_url,
                    "private":        private,
                },
            )

        except asyncio.TimeoutError:
            return ActionResult(success=False, error="gh CLI 超时（30s），请检查网络或 gh 是否已登录")
        except FileNotFoundError:
            return ActionResult(
                success=False,
                error="未找到 gh CLI，请先安装：winget install GitHub.cli，然后 gh auth login",
            )
        except Exception as e:
            return ActionResult(success=False, error=f"执行异常：{e}")

"""
AI 自动开发系统 - Git 仓库管理器
封装项目级 Git 操作：初始化、文件写入、提交、推送
"""
import logging
import os
import json
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

from config import BASE_DIR

logger = logging.getLogger("git")


# 项目仓库根目录
PROJECTS_DIR = BASE_DIR / "projects"
PROJECTS_DIR.mkdir(exist_ok=True)


class GitManager:
    """Git 仓库管理器"""

    # 项目仓库标准目录结构
    REPO_DIRS = [
        "src/api",
        "src/models",
        "src/services",
        "src/utils",
        "tests",
        "docs",
        "config",
        "build",
    ]

    def __init__(self):
        # 存储项目 ID 到自定义路径的映射
        self._custom_paths: Dict[str, str] = {}

    def set_project_path(self, project_id: str, path: str):
        """设置项目的自定义仓库路径"""
        self._custom_paths[project_id] = path

    def _repo_path(self, project_id: str) -> Path:
        """获取项目仓库路径（优先使用自定义路径）"""
        if project_id in self._custom_paths:
            return Path(self._custom_paths[project_id])
        return PROJECTS_DIR / project_id

    async def _run_git(self, cwd: str, *args: str) -> tuple:
        """执行 git 命令，返回 (returncode, stdout, stderr)"""
        import subprocess
        cmd = ["git"] + list(args)
        try:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            return (
                result.returncode,
                result.stdout.strip(),
                result.stderr.strip(),
            )
        except Exception as e:
            return (1, "", str(e))

    # ==================== 仓库初始化 ====================

    async def init_repo(self, project_id: str, project_name: str, description: str = "") -> str:
        """初始化项目 Git 仓库，创建标准目录结构"""
        repo_dir = self._repo_path(project_id)

        if repo_dir.exists():
            return str(repo_dir)

        repo_dir.mkdir(parents=True, exist_ok=True)

        # 创建标准目录
        for d in self.REPO_DIRS:
            (repo_dir / d).mkdir(parents=True, exist_ok=True)

        # 生成 README.md
        readme = f"""# {project_name}

{description or '由 AI 自动开发系统创建的项目'}

## 目录结构

```
src/         - 源代码
  api/       - API 接口
  models/    - 数据模型
  services/  - 业务逻辑
  utils/     - 工具函数
tests/       - 测试代码
docs/        - 文档
config/      - 配置文件
build/       - 构建产物 (Dockerfile, CI/CD 等)
```

## 由 AI 自动开发系统管理

此仓库中的代码和文档由 AI Agent 自动生成和维护。
"""
        (repo_dir / "README.md").write_text(readme, encoding="utf-8")

        # 生成 .gitignore
        gitignore = """# Python
__pycache__/
*.py[cod]
*.egg-info/
dist/
build/
.eggs/
*.egg
.venv/
venv/

# IDE
.idea/
.vscode/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# Environment
.env
*.log
"""
        (repo_dir / ".gitignore").write_text(gitignore, encoding="utf-8")

        # git init + 初始提交
        await self._run_git(str(repo_dir), "init")
        await self._run_git(str(repo_dir), "add", ".")
        await self._run_git(
            str(repo_dir), "commit", "-m",
            f"init: {project_name} - project initialized by AI Dev System",
            "--author", "AI Dev System <ai@dev-system.local>",
        )

        # 创建 develop 分支（从 master/main 分出来）
        await self._run_git(str(repo_dir), "branch", "develop")
        logger.info("🌿 develop 分支已创建")

        return str(repo_dir)

    # ==================== 文件操作 ====================

    async def write_file(self, project_id: str, file_path: str, content: str) -> str:
        """写入单个文件到仓库（相对路径）"""
        repo_dir = self._repo_path(project_id)
        target = repo_dir / file_path

        # 确保目录存在
        target.parent.mkdir(parents=True, exist_ok=True)

        # 写入文件
        target.write_text(content, encoding="utf-8")
        return str(target)

    async def write_files(self, project_id: str, files: Dict[str, str]) -> List[str]:
        """批量写入文件到仓库"""
        written = []
        for file_path, content in files.items():
            path = await self.write_file(project_id, file_path, content)
            written.append(path)
        return written

    # ==================== Git 操作 ====================

    async def commit(self, project_id: str, message: str, author: str = "AI Agent") -> Optional[str]:
        """git add + commit，返回 commit hash"""
        repo_dir = str(self._repo_path(project_id))

        # git add all changes
        await self._run_git(repo_dir, "add", ".")

        # check if there are changes to commit
        rc, out, _ = await self._run_git(repo_dir, "status", "--porcelain")
        if rc != 0 or not out:
            return None  # nothing to commit

        # commit
        rc, out, err = await self._run_git(
            repo_dir, "commit", "-m", message,
            "--author", f"{author} <{author.lower().replace(' ', '-')}@ai-dev-system.local>",
        )
        if rc != 0:
            logger.error("git commit failed: %s", err)
            return None

        # get commit hash
        rc, hash_out, _ = await self._run_git(repo_dir, "rev-parse", "--short", "HEAD")
        return hash_out if rc == 0 else None

    async def push(self, project_id: str, remote: str = "origin", branch: str = None) -> bool:
        """git push（仅在配置了远程仓库时执行）"""
        repo_dir = str(self._repo_path(project_id))

        # check if remote exists
        rc, out, _ = await self._run_git(repo_dir, "remote")
        if rc != 0 or remote not in out:
            return False  # no remote configured

        # 自动检测当前分支名
        if not branch:
            rc, branch_out, _ = await self._run_git(repo_dir, "rev-parse", "--abbrev-ref", "HEAD")
            branch = branch_out if rc == 0 and branch_out else "main"

        rc, _, err = await self._run_git(repo_dir, "push", remote, branch)
        if rc != 0:
            # 如果 main 失败，尝试 master
            if "main" in (branch or ""):
                rc2, _, err2 = await self._run_git(repo_dir, "push", remote, "master")
                if rc2 == 0:
                    return True
            logger.error("git push failed: %s", err)
            return False
        return True

    async def set_remote(self, project_id: str, url: str, remote: str = "origin") -> bool:
        """设置远程仓库地址"""
        repo_dir = str(self._repo_path(project_id))

        # check if remote already exists
        rc, out, _ = await self._run_git(repo_dir, "remote")
        if remote in (out or ""):
            await self._run_git(repo_dir, "remote", "set-url", remote, url)
        else:
            await self._run_git(repo_dir, "remote", "add", remote, url)
        return True

    # ==================== 分支管理 ====================

    async def create_branch(self, project_id: str, branch_name: str) -> bool:
        """创建并切换到新分支"""
        repo_dir = str(self._repo_path(project_id))
        rc, _, err = await self._run_git(repo_dir, "checkout", "-b", branch_name)
        if rc != 0:
            logger.error("create branch '%s' failed: %s", branch_name, err)
            return False
        logger.info("分支已创建并切换: %s", branch_name)
        return True

    async def switch_branch(self, project_id: str, branch_name: str) -> bool:
        """切换到指定分支"""
        repo_dir = str(self._repo_path(project_id))
        rc, _, err = await self._run_git(repo_dir, "checkout", branch_name)
        if rc != 0:
            logger.error("switch branch '%s' failed: %s", branch_name, err)
            return False
        return True

    async def get_current_branch(self, project_id: str) -> str:
        """获取当前分支名"""
        repo_dir = str(self._repo_path(project_id))
        rc, out, _ = await self._run_git(repo_dir, "rev-parse", "--abbrev-ref", "HEAD")
        return out if rc == 0 else "main"

    async def push_branch(self, project_id: str, branch_name: str, remote: str = "origin") -> bool:
        """推送分支到远程"""
        repo_dir = str(self._repo_path(project_id))
        rc, _, err = await self._run_git(repo_dir, "push", "-u", remote, branch_name)
        if rc != 0:
            logger.error("push branch '%s' failed: %s", branch_name, err)
            return False
        return True

    async def merge_branch(self, project_id: str, source: str, target: str,
                           message: str = None) -> Dict:
        """将 source 分支合并到 target 分支，返回结果"""
        repo_dir = str(self._repo_path(project_id))

        # 切到目标分支
        rc, _, err = await self._run_git(repo_dir, "checkout", target)
        if rc != 0:
            return {"success": False, "error": f"切换到 {target} 失败: {err}"}

        # 合并
        merge_msg = message or f"merge: {source} → {target}"
        rc, out, err = await self._run_git(repo_dir, "merge", source, "--no-ff", "-m", merge_msg)
        if rc != 0:
            # 合并冲突，abort 并回报
            await self._run_git(repo_dir, "merge", "--abort")
            return {"success": False, "error": f"合并冲突: {err}"}

        # 获取合并后的 commit hash
        rc, hash_out, _ = await self._run_git(repo_dir, "rev-parse", "--short", "HEAD")
        commit_hash = hash_out if rc == 0 else None

        # push
        pushed = await self.push(project_id)

        logger.info("🔀 分支合并: %s → %s (commit: %s, pushed: %s)", source, target, commit_hash, pushed)
        return {"success": True, "commit": commit_hash, "pushed": pushed}

    async def list_branches(self, project_id: str) -> List[str]:
        """列出所有本地分支"""
        repo_dir = str(self._repo_path(project_id))
        rc, out, _ = await self._run_git(repo_dir, "branch", "--list")
        if rc != 0 or not out:
            return []
        return [b.strip().lstrip("* ") for b in out.split("\n") if b.strip()]

    async def ensure_branch(self, project_id: str, branch_name: str):
        """确保分支存在，不存在则创建（从当前分支）"""
        branches = await self.list_branches(project_id)
        if branch_name not in branches:
            repo_dir = str(self._repo_path(project_id))
            await self._run_git(repo_dir, "branch", branch_name)
            logger.info("🌿 分支 %s 已创建", branch_name)

    # ==================== 高级操作 ====================

    async def write_and_commit(
        self,
        project_id: str,
        files: Dict[str, str],
        message: str,
        agent: str = "AI Agent",
    ) -> Optional[Dict]:
        """
        批量写入文件 + commit + push
        返回: {"commit_hash": "abc1234", "files_count": 3, "files": [...]}
        """
        if not files:
            return None

        # write files
        written = await self.write_files(project_id, files)

        # commit
        commit_hash = await self.commit(project_id, message, author=agent)

        # push (best effort)
        pushed = await self.push(project_id)

        return {
            "commit_hash": commit_hash,
            "files_count": len(written),
            "files": list(files.keys()),
            "pushed": pushed,
        }

    # ==================== 查询 ====================

    async def get_log(self, project_id: str, limit: int = 20) -> List[Dict]:
        """获取 git log"""
        repo_dir = str(self._repo_path(project_id))

        rc, out, _ = await self._run_git(
            repo_dir, "log",
            f"--max-count={limit}",
            "--format=%H|%h|%an|%ae|%ai|%s",
        )
        if rc != 0 or not out:
            return []

        logs = []
        for line in out.strip().split("\n"):
            parts = line.split("|", 5)
            if len(parts) >= 6:
                logs.append({
                    "hash": parts[0],
                    "short_hash": parts[1],
                    "author": parts[2],
                    "email": parts[3],
                    "date": parts[4],
                    "message": parts[5],
                })
        return logs

    async def get_file_tree(self, project_id: str) -> Dict:
        """获取仓库文件树"""
        repo_dir = self._repo_path(project_id)
        if not repo_dir.exists():
            return {"name": project_id, "children": []}

        def _scan_dir(path: Path, relative: str = "") -> List[Dict]:
            children = []
            try:
                items = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
            except PermissionError:
                return children

            for item in items:
                if item.name.startswith("."):
                    continue
                if item.name == "__pycache__":
                    continue

                rel_path = f"{relative}/{item.name}" if relative else item.name

                if item.is_dir():
                    sub_children = _scan_dir(item, rel_path)
                    children.append({
                        "name": item.name,
                        "path": rel_path,
                        "type": "directory",
                        "children": sub_children,
                    })
                else:
                    children.append({
                        "name": item.name,
                        "path": rel_path,
                        "type": "file",
                        "size": item.stat().st_size,
                    })
            return children

        return {
            "name": project_id,
            "path": "",
            "type": "directory",
            "children": _scan_dir(repo_dir),
        }

    async def get_file_content(self, project_id: str, file_path: str) -> Optional[str]:
        """读取仓库中的文件内容"""
        repo_dir = self._repo_path(project_id)
        target = repo_dir / file_path

        if not target.exists() or not target.is_file():
            return None

        # security: prevent path traversal
        try:
            target.resolve().relative_to(repo_dir.resolve())
        except ValueError:
            return None

        try:
            return target.read_text(encoding="utf-8")
        except Exception:
            return None

    async def get_diff(self, project_id: str, commit_hash: str = None) -> str:
        """获取 diff"""
        repo_dir = str(self._repo_path(project_id))

        if commit_hash:
            rc, out, _ = await self._run_git(repo_dir, "show", "--stat", commit_hash)
        else:
            rc, out, _ = await self._run_git(repo_dir, "diff", "--stat")

        return out if rc == 0 else ""

    def repo_exists(self, project_id: str) -> bool:
        """检查项目仓库是否存在"""
        repo_dir = self._repo_path(project_id)
        return (repo_dir / ".git").exists()


# 全局实例
git_manager = GitManager()

"""
AI 自动开发系统 - Git 仓库管理器
封装项目级 Git 操作：初始化、文件写入、提交、推送
"""
import logging
import os
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
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
        # 存储项目 ID 到默认 push remote 名的映射
        self._push_remotes: Dict[str, str] = {}

    def set_project_path(self, project_id: str, path: str):
        """设置项目的自定义仓库路径"""
        self._custom_paths[project_id] = path

    def set_push_remote(self, project_id: str, remote_name: str):
        """设置项目的默认 push remote 名"""
        self._push_remotes[project_id] = remote_name

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
        await self._run_git(str(repo_dir), "init", "-b", "main")
        await self._run_git(str(repo_dir), "add", ".")
        await self._run_git(
            str(repo_dir), "commit", "-m",
            f"init: {project_name} - project initialized by AI Dev System",
            "--author", "AI Dev System <ai@dev-system.local>",
        )

        # 创建 develop 分支（从 main 分出来）
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

    async def push(self, project_id: str, remote: str = None, branch: str = None) -> bool:
        """git push（仅在配置了远程仓库时执行，禁止 Agent 直接 push 到 main/master）"""
        # remote=None 时使用项目配置的 push remote，fallback "origin"
        if remote is None:
            remote = self._push_remotes.get(project_id, "origin")

        repo_dir = str(self._repo_path(project_id))

        # check if remote exists
        rc, out, _ = await self._run_git(repo_dir, "remote")
        if rc != 0 or remote not in out:
            return False  # no remote configured

        # 自动检测当前分支名
        if not branch:
            rc, branch_out, _ = await self._run_git(repo_dir, "rev-parse", "--abbrev-ref", "HEAD")
            branch = branch_out if rc == 0 and branch_out else "main"

        # 保护：Agent 不能直接 push 到 main/master（只能通过 CI/CD merge）
        if branch in ("main", "master"):
            # 检查调用来源：如果是从 write_and_commit 调的（Agent 提交），阻止
            import traceback
            stack = traceback.format_stack()
            is_agent_push = any("write_and_commit" in frame or "_handle_git_files" in frame for frame in stack)
            if is_agent_push:
                logger.warning("🛑 阻止 Agent 直接 push 到 %s（应在 feat 分支上）", branch)
                return False

        rc, _, err = await self._run_git(repo_dir, "push", remote, branch)
        if rc != 0:
            logger.error("git push failed: %s", err)
            return False
        return True

    async def clone(self, url: str, dest_path: str) -> bool:
        """git clone 远程仓库到指定路径"""
        import subprocess
        cmd = ["git", "clone", url, dest_path]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding="utf-8", errors="replace", check=False,
            )
            if result.returncode == 0:
                logger.info("git clone 成功: %s -> %s", url, dest_path)
                return True
            else:
                logger.error("git clone 失败: %s", result.stderr.strip())
                return False
        except Exception as e:
            logger.error("git clone 异常: %s", e)
            return False

    async def pull(self, project_id: str, remote: str = "origin", branch: str = None) -> bool:
        """git pull 拉取远程更新"""
        repo_dir = str(self._repo_path(project_id))
        if branch:
            rc, out, err = await self._run_git(repo_dir, "pull", remote, branch)
        else:
            rc, out, err = await self._run_git(repo_dir, "pull", remote)
        if rc != 0:
            logger.warning("git pull 失败: %s", err)
            return False
        logger.info("git pull 成功: %s", out[:200] if out else "up to date")
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

    async def list_remotes(self, project_id: str) -> List[Dict]:
        """返回仓库所有 remote 列表（去重 fetch/push 相同 url）"""
        repo_dir = str(self._repo_path(project_id))
        rc, out, _ = await self._run_git(repo_dir, "remote", "-v")
        if rc != 0 or not out:
            return []
        seen: Dict[str, str] = {}
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                name, url = parts[0], parts[1]
                seen[name] = url  # 同名 remote fetch/push url 相同时去重
        return [{"name": n, "url": u} for n, u in seen.items()]

    async def add_remote(self, project_id: str, name: str, url: str) -> bool:
        """添加新 remote"""
        repo_dir = str(self._repo_path(project_id))
        rc, out, _ = await self._run_git(repo_dir, "remote")
        if name in (out or "").splitlines():
            await self._run_git(repo_dir, "remote", "set-url", name, url)
        else:
            rc, _, err = await self._run_git(repo_dir, "remote", "add", name, url)
            if rc != 0:
                logger.error("git remote add '%s' failed: %s", name, err)
                return False
        return True

    async def remove_remote(self, project_id: str, name: str) -> bool:
        """删除 remote"""
        repo_dir = str(self._repo_path(project_id))
        rc, _, err = await self._run_git(repo_dir, "remote", "remove", name)
        if rc != 0:
            logger.error("git remote remove '%s' failed: %s", name, err)
            return False
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
        # 先清理可能冲突的未跟踪文件（如 .pyc 缓存）
        await self._run_git(repo_dir, "clean", "-fd", "--exclude=.env")
        await self._run_git(repo_dir, "checkout", ".")
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

    async def get_branch_at_path(self, path: str) -> str:
        """读任意路径的当前 HEAD 分支（供环境管理显示真实 checkout）。
        失败返回空串；detached HEAD 返回 "HEAD"。"""
        from pathlib import Path as _P
        if not path or not _P(path).exists():
            return ""
        try:
            rc, out, _ = await self._run_git(path, "rev-parse", "--abbrev-ref", "HEAD")
            return out.strip() if rc == 0 else ""
        except Exception:
            return ""

    async def get_primary_branch(self, project_id: str) -> str:
        """检测仓库主分支名（main 或 master）

        优先级：
        1. 远程 HEAD 指向（origin/HEAD → origin/main 或 origin/master）
        2. 本地是否存在 main / master 分支
        3. 默认返回 main
        """
        branches = await self.list_branches(project_id)
        # 检查远程 HEAD 指向
        repo_dir = str(self._repo_path(project_id))
        rc, out, _ = await self._run_git(repo_dir, "symbolic-ref", "refs/remotes/origin/HEAD")
        if rc == 0 and out:
            # out 形如 refs/remotes/origin/main
            remote_primary = out.split("/")[-1]
            if remote_primary in ("main", "master"):
                return remote_primary
        # 本地分支检测
        if "main" in branches:
            return "main"
        if "master" in branches:
            return "master"
        return "main"

    async def push_branch(self, project_id: str, branch_name: str, remote: str = "origin") -> bool:
        """推送分支到远程"""
        repo_dir = str(self._repo_path(project_id))
        rc, _, err = await self._run_git(repo_dir, "push", "-u", remote, branch_name)
        if rc != 0:
            logger.error("push branch '%s' failed: %s", branch_name, err)
            return False
        return True

    async def merge_branch(self, project_id: str, source: str, target: str,
                           message: str = None, keep_conflict: bool = False) -> Dict:
        """将 source 分支合并到 target 分支，返回结果

        keep_conflict=False（默认）：冲突时 abort，保持原状。
        keep_conflict=True：冲突时**不** abort，保留冲突标记和 index 中的冲突条目，
          额外返回 `conflict_files` 供调用方尝试自动解决；调用方如果失败请显式
          abort_merge()。
        """
        repo_dir = str(self._repo_path(project_id))

        # 切到目标分支
        rc, _, err = await self._run_git(repo_dir, "checkout", target)
        if rc != 0:
            return {"success": False, "error": f"切换到 {target} 失败: {err}"}

        # 合并
        merge_msg = message or f"merge: {source} → {target}"
        rc, out, err = await self._run_git(repo_dir, "merge", source, "--no-ff", "-m", merge_msg)
        if rc != 0:
            if keep_conflict:
                # 保留冲突让调用方处理；把冲突文件列表也返回
                conflict_files = await self._list_conflict_files(repo_dir)
                return {
                    "success": False,
                    "error": f"合并冲突: {err}",
                    "conflict_files": conflict_files,
                    "repo_dir": repo_dir,
                    "has_conflict": True,
                }
            await self._run_git(repo_dir, "merge", "--abort")
            return {"success": False, "error": f"合并冲突: {err}"}

        # 获取合并后的 commit hash
        rc, hash_out, _ = await self._run_git(repo_dir, "rev-parse", "--short", "HEAD")
        commit_hash = hash_out if rc == 0 else None

        # push
        pushed = await self.push(project_id)

        logger.info("🔀 分支合并: %s → %s (commit: %s, pushed: %s)", source, target, commit_hash, pushed)
        return {"success": True, "commit": commit_hash, "pushed": pushed}

    async def _list_conflict_files(self, repo_dir: str) -> List[str]:
        """在 merge 冲突状态下列出冲突文件（unmerged paths）"""
        rc, out, _ = await self._run_git(repo_dir, "diff", "--name-only", "--diff-filter=U")
        if rc != 0 or not out:
            return []
        return [p.strip() for p in out.split("\n") if p.strip()]

    async def abort_merge(self, project_id: str) -> bool:
        """中止正在进行的 merge"""
        repo_dir = str(self._repo_path(project_id))
        rc, _, _ = await self._run_git(repo_dir, "merge", "--abort")
        return rc == 0

    async def finalize_merge(self, project_id: str, message: str = None) -> Dict:
        """在冲突已解决（工作树无冲突标记、所有冲突文件已 git add）后，
        commit + push 完成 merge。

        message=None → 用 git 现有的 MERGE_MSG（merge 命令已写好的默认消息）。
        """
        repo_dir = str(self._repo_path(project_id))

        if message:
            rc, out, err = await self._run_git(repo_dir, "commit", "-m", message)
        else:
            rc, out, err = await self._run_git(repo_dir, "commit", "--no-edit")
        if rc != 0:
            return {"success": False, "error": f"commit 失败: {err or out}"}

        rc, hash_out, _ = await self._run_git(repo_dir, "rev-parse", "--short", "HEAD")
        commit_hash = hash_out if rc == 0 else None

        pushed = await self.push(project_id)
        logger.info("🔀 自动解冲突后提交: commit=%s, pushed=%s", commit_hash, pushed)
        return {"success": True, "commit": commit_hash, "pushed": pushed}

    async def list_branches(self, project_id: str) -> List[str]:
        """列出所有本地分支"""
        repo_dir = str(self._repo_path(project_id))
        rc, out, _ = await self._run_git(repo_dir, "branch", "--list")
        if rc != 0 or not out:
            return []
        return [b.strip().lstrip("* ") for b in out.split("\n") if b.strip()]

    async def list_branches_enriched(self, project_id: str) -> List[Dict[str, Any]]:
        """v0.19.1 仓库分支视图：含 upstream / ahead-behind / 最后一次提交 / 推测 parent

        输出按 committerdate 降序；parent 依靠 merge-base 启发算法，对 main/master/develop
        做候选，和自身 merge-base 最晚的那个视为直接父。找不到则 parent=None（作为根）。
        """
        repo_dir = str(self._repo_path(project_id))
        # 拉全量分支元数据（只取本地 refs）
        fmt = "%(refname:short)|%(upstream:short)|%(committerdate:iso-strict)|%(objectname:short)|%(subject)"
        rc, out, _ = await self._run_git(
            repo_dir, "for-each-ref", f"--format={fmt}", "refs/heads",
        )
        if rc != 0 or not out:
            return []

        current = (await self.get_current_branch(project_id)) or ""
        branches: List[Dict[str, Any]] = []
        names: List[str] = []
        for raw in out.splitlines():
            if not raw.strip():
                continue
            parts = raw.split("|", 4)
            if len(parts) < 5:
                parts += [""] * (5 - len(parts))
            name, upstream, cdate, sha, subject = parts
            branches.append({
                "name": name.strip(),
                "upstream": upstream.strip() or None,
                "last_commit_at": cdate.strip() or None,
                "last_commit_sha": sha.strip() or None,
                "last_commit_subject": subject.strip() or "",
                "ahead": 0,
                "behind": 0,
                "parent": None,
                "current": name.strip() == current,
            })
            names.append(name.strip())

        # ahead / behind —— upstream 有的话用 upstream，没有用启发 parent（后面再算）
        for b in branches:
            if b["upstream"]:
                ahead, behind = await self._ahead_behind(repo_dir, b["name"], b["upstream"])
                b["ahead"], b["behind"] = ahead, behind

        # 基于命名约定的 parent 推断（graph 分析对 merge-heavy 仓库会反直觉，
        # 因为 `merge: develop → main` 后 develop 就成了 main 的祖先）：
        #   - main / master           → 根（parent=None）
        #   - develop                 → main / master（若存在）
        #   - feat/* fix/* hotfix/*   → develop（若存在）否则 main / master
        #   - 其他                    → 按 merge-base 找最近的主干分支
        trunk = "main" if "main" in names else ("master" if "master" in names else None)
        has_develop = "develop" in names

        async def _pick_parent(child: str) -> Optional[str]:
            if child in ("main", "master"):
                return None
            if child == "develop":
                return trunk
            # feat/fix/hotfix 等特性分支
            if has_develop:
                # 只有当 develop 确实是 child 的祖先时才挂到 develop 下，
                # 否则挂到 trunk（避免 "feat/old 从 master 切出、develop 后来才建" 这种历史 edge case）
                anc_rc, _, _ = await self._run_git(
                    repo_dir, "merge-base", "--is-ancestor", "develop", child,
                )
                if anc_rc == 0:
                    return "develop"
            return trunk

        for b in branches:
            # 候选分支本身：parent 也允许其他 candidate（形成 main→develop→master 链）
            parent = await _pick_parent(b["name"])
            b["parent"] = parent

            # 对没 upstream 的分支，用 parent 当基准算 ahead/behind
            if b["ahead"] == 0 and b["behind"] == 0 and not b["upstream"] and parent:
                ahead, behind = await self._ahead_behind(repo_dir, b["name"], parent)
                b["ahead"], b["behind"] = ahead, behind

        # 按 committerdate 降序
        branches.sort(key=lambda x: x.get("last_commit_at") or "", reverse=True)
        return branches

    async def _ahead_behind(self, repo_dir: str, a: str, b: str) -> tuple:
        """返回 (a 相对 b 领先数, a 相对 b 落后数)"""
        rc, out, _ = await self._run_git(
            repo_dir, "rev-list", "--left-right", "--count", f"{a}...{b}",
        )
        if rc != 0 or not out:
            return 0, 0
        try:
            left, right = out.strip().split()
            return int(left), int(right)
        except Exception:
            return 0, 0

    async def ensure_branch(self, project_id: str, branch_name: str, from_branch: str = None):
        """确保分支存在，不存在则创建（从 from_branch 或当前分支）"""
        branches = await self.list_branches(project_id)
        if branch_name not in branches:
            repo_dir = str(self._repo_path(project_id))
            if from_branch and from_branch in branches:
                # 从指定分支创建
                await self._run_git(repo_dir, "branch", branch_name, from_branch)
            else:
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

    async def get_commit_detail(self, project_id: str, sha: str) -> Optional[Dict]:
        """v0.19.1：获取单次提交的详细信息 + 每文件 patch。

        返回：
          {
            sha, short_sha, author, email, date, subject, body,
            files: [{path, old_path?, status, additions, deletions, binary, patch}]
          }
        status: A/M/D/R/C/T。RENAME 带 old_path。
        """
        repo_dir = str(self._repo_path(project_id))

        # 1. 元数据
        rc, out, _ = await self._run_git(
            repo_dir, "show", "-s", "--format=%H%n%h%n%an%n%ae%n%ai%n%s%n%b", sha,
        )
        if rc != 0 or not out:
            return None
        parts = out.split("\n", 6)
        if len(parts) < 6:
            return None
        meta = {
            "sha": parts[0],
            "short_sha": parts[1],
            "author": parts[2],
            "email": parts[3],
            "date": parts[4],
            "subject": parts[5],
            "body": parts[6] if len(parts) > 6 else "",
        }

        # 2. 文件状态 + numstat
        rc2, out2, _ = await self._run_git(
            repo_dir, "show", "--name-status", "--format=", sha,
        )
        files_status: Dict[str, Dict[str, Any]] = {}
        if rc2 == 0 and out2:
            for line in out2.strip().split("\n"):
                if not line.strip():
                    continue
                cols = line.split("\t")
                st = cols[0][0] if cols else ""
                if st in ("R", "C") and len(cols) >= 3:
                    old_path, new_path = cols[1], cols[2]
                    files_status[new_path] = {
                        "path": new_path, "old_path": old_path, "status": st,
                    }
                elif len(cols) >= 2:
                    files_status[cols[1]] = {"path": cols[1], "status": st}

        rc3, out3, _ = await self._run_git(
            repo_dir, "show", "--numstat", "--format=", sha,
        )
        if rc3 == 0 and out3:
            for line in out3.strip().split("\n"):
                if not line.strip():
                    continue
                cols = line.split("\t")
                if len(cols) < 3:
                    continue
                add_s, del_s, p = cols[0], cols[1], cols[2]
                key = p
                # rename: path 在 numstat 里是 "{old => new}"，从 name-status 里更可靠
                for k, v in files_status.items():
                    if v.get("path") == p or v.get("old_path") == p or k == p:
                        key = k
                        break
                entry = files_status.setdefault(key, {"path": key, "status": "M"})
                if add_s == "-" and del_s == "-":
                    entry["binary"] = True
                    entry["additions"] = 0
                    entry["deletions"] = 0
                else:
                    try:
                        entry["additions"] = int(add_s)
                        entry["deletions"] = int(del_s)
                    except ValueError:
                        entry["additions"] = entry["deletions"] = 0
                    entry["binary"] = False

        # 3. 每文件 patch（--format= 去掉头部）
        rc4, out4, _ = await self._run_git(
            repo_dir, "show", "--format=", sha,
        )
        patches_by_file: Dict[str, str] = {}
        if rc4 == 0 and out4:
            # 按 "diff --git " 切割
            cur_file: Optional[str] = None
            cur_lines: List[str] = []

            def _flush():
                if cur_file is not None:
                    patches_by_file[cur_file] = "\n".join(cur_lines)

            for raw in out4.split("\n"):
                if raw.startswith("diff --git "):
                    _flush()
                    cur_lines = [raw]
                    # diff --git a/<path> b/<path>   — 提取 b 路径
                    try:
                        # 最后一个 "b/" 之后是目标路径
                        idx = raw.rfind(" b/")
                        cur_file = raw[idx + 3:] if idx >= 0 else None
                    except Exception:
                        cur_file = None
                else:
                    cur_lines.append(raw)
            _flush()

        for k, v in files_status.items():
            v["patch"] = patches_by_file.get(v.get("path") or k, "")
            v.setdefault("additions", 0)
            v.setdefault("deletions", 0)
            v.setdefault("binary", False)

        meta["files"] = list(files_status.values())
        return meta

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

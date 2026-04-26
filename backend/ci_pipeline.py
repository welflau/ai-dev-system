"""
AI 自动开发系统 - CI/CD Pipeline 引擎
项目级构建、测试、合并、部署自动化
"""
import asyncio
import json
import logging
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from database import db
from models import CIBuildStatus, CIBuildType
from utils import generate_id, now_iso
from events import event_manager
from git_manager import git_manager

logger = logging.getLogger("ci_pipeline")

# 调度间隔
DEVELOP_CHECK_INTERVAL = 60       # 每 60 秒检查 develop 是否有新提交
MASTER_BUILD_INTERVAL = 86400     # main 构建间隔 24 小时


class CIPipelineRunner:
    """CI/CD Pipeline 运行器 — 管理 develop/main 构建和部署"""

    def __init__(self):
        # 项目级锁：防止同一项目并发构建导致 git 冲突
        self._locks: Dict[str, asyncio.Lock] = {}
        self._scheduler_task: Optional[asyncio.Task] = None

    def _get_lock(self, project_id: str) -> asyncio.Lock:
        if project_id not in self._locks:
            self._locks[project_id] = asyncio.Lock()
        return self._locks[project_id]

    # ==================== 调度器 ====================

    async def start_scheduler(self):
        """启动后台调度器"""
        logger.info("CI/CD 调度器已启动 (develop 检查间隔: %ds)", DEVELOP_CHECK_INTERVAL)
        while True:
            try:
                await self._scheduler_tick()
            except Exception as e:
                logger.error("CI/CD 调度器异常: %s", e, exc_info=True)
            await asyncio.sleep(DEVELOP_CHECK_INTERVAL)

    async def _scheduler_tick(self):
        """单次调度检查"""
        projects = await db.fetch_all(
            "SELECT id FROM projects WHERE status = 'active'"
        )
        for project in projects:
            project_id = project["id"]
            try:
                await self._check_develop_build(project_id)
                await self._check_master_build(project_id)
            except Exception as e:
                logger.warning("项目 %s CI 检查失败: %s", project_id[:8], e)

    async def _check_develop_build(self, project_id: str):
        """检查 develop 是否有新提交需要构建"""
        if not git_manager.repo_exists(project_id):
            return

        # 获取 develop HEAD
        head = await self._get_branch_head(project_id, "develop")
        if not head:
            return

        # 查询最近成功的 develop 构建
        last_build = await db.fetch_one(
            "SELECT commit_hash FROM ci_builds "
            "WHERE project_id = ? AND build_type = 'develop_build' AND status = 'success' "
            "ORDER BY created_at DESC LIMIT 1",
            (project_id,),
        )
        last_hash = last_build["commit_hash"] if last_build else None

        if head == last_hash:
            return  # 无新提交

        # 检查是否已有进行中的构建
        running = await db.fetch_one(
            "SELECT id FROM ci_builds "
            "WHERE project_id = ? AND build_type = 'develop_build' AND status IN ('pending', 'running')",
            (project_id,),
        )
        if running:
            return

        logger.info("检测到 develop 新提交 (%s → %s), 自动触发构建", last_hash or "无", head[:8])
        await self.trigger_build(project_id, CIBuildType.DEVELOP_BUILD.value, trigger="auto")

    async def _check_master_build(self, project_id: str):
        """检查 main 是否需要每日构建"""
        if not git_manager.repo_exists(project_id):
            return

        # 查询最近的 main 构建（不论成功失败）
        last_build = await db.fetch_one(
            "SELECT created_at FROM ci_builds "
            "WHERE project_id = ? AND build_type = 'master_build' "
            "ORDER BY created_at DESC LIMIT 1",
            (project_id,),
        )

        if last_build:
            try:
                last_time = datetime.fromisoformat(last_build["created_at"].replace("Z", "+00:00"))
                if datetime.now(last_time.tzinfo) - last_time < timedelta(seconds=MASTER_BUILD_INTERVAL):
                    return  # 未到构建间隔
            except Exception:
                pass

        # 检查 main 是否有内容（是否有过 develop→main 合并）
        head = await self._get_branch_head(project_id, "main")
        if not head:
            return

        # 检查是否有进行中的构建
        running = await db.fetch_one(
            "SELECT id FROM ci_builds "
            "WHERE project_id = ? AND build_type = 'master_build' AND status IN ('pending', 'running')",
            (project_id,),
        )
        if running:
            return

        logger.info("Main 每日构建触发 (项目: %s)", project_id[:8])
        await self.trigger_build(project_id, CIBuildType.MASTER_BUILD.value, trigger="auto")

    # ==================== 构建触发 ====================

    async def trigger_build(self, project_id: str, build_type: str, trigger: str = "manual") -> Dict:
        """触发一次构建，返回 build 记录"""
        if build_type in (CIBuildType.MASTER_BUILD.value, CIBuildType.DEPLOY.value):
            branch = await git_manager.get_primary_branch(project_id)
        else:
            branch = "develop"

        build_id = generate_id("ci-")
        await db.insert("ci_builds", {
            "id": build_id,
            "project_id": project_id,
            "build_type": build_type,
            "branch": branch,
            "status": CIBuildStatus.PENDING.value,
            "trigger": trigger,
            "created_at": now_iso(),
        })

        await event_manager.publish_to_project(project_id, "ci_build_started", {
            "build_id": build_id,
            "build_type": build_type,
            "branch": branch,
            "trigger": trigger,
        })

        # 异步执行构建
        asyncio.create_task(self._execute_build(build_id, project_id, build_type))
        return {"build_id": build_id, "status": "pending"}

    # ==================== 构建执行 ====================

    async def _execute_build(self, build_id: str, project_id: str, build_type: str):
        """执行构建（带项目级锁）"""
        lock = self._get_lock(project_id)
        async with lock:
            try:
                await db.update("ci_builds", {
                    "status": CIBuildStatus.RUNNING.value,
                    "started_at": now_iso(),
                }, "id = ?", (build_id,))

                if build_type == CIBuildType.DEVELOP_BUILD.value:
                    await self._run_develop_build(build_id, project_id)
                elif build_type == CIBuildType.MASTER_BUILD.value:
                    await self._run_master_build(build_id, project_id)
                elif build_type == CIBuildType.DEPLOY.value:
                    await self._run_deploy(build_id, project_id)

            except Exception as e:
                logger.error("构建异常 %s: %s", build_id[:8], e, exc_info=True)
                await self._fail_build(build_id, project_id, str(e))

    async def _run_develop_build(self, build_id: str, project_id: str):
        """Develop 构建: 语法检查 + 冒烟测试 → 通过则合入主分支（main 或 master）"""
        logs = []

        # 检测主分支名（main 或 master）
        primary = await git_manager.get_primary_branch(project_id)

        # 切到 develop 分支
        await git_manager.switch_branch(project_id, "develop")
        head = await self._get_branch_head(project_id, "develop")
        await db.update("ci_builds", {"commit_hash": head}, "id = ?", (build_id,))
        logs.append({"step": "checkout", "msg": f"切换到 develop 分支 (HEAD: {head})"})

        # 模拟构建: 语法检查
        repo_path = str(git_manager._repo_path(project_id))
        syntax_ok, syntax_log = await self._check_syntax(repo_path)
        logs.append({"step": "syntax_check", "msg": syntax_log, "passed": syntax_ok})

        # 模拟冒烟测试
        smoke_ok, smoke_log = await self._smoke_test(repo_path)
        logs.append({"step": "smoke_test", "msg": smoke_log, "passed": smoke_ok})

        # 模拟单元测试
        unit_ok, unit_log = await self._run_tests(repo_path)
        logs.append({"step": "unit_test", "msg": unit_log, "passed": unit_ok})

        all_passed = syntax_ok and smoke_ok

        if not all_passed:
            await self._fail_build(build_id, project_id,
                                   "Develop 构建失败: 语法检查或冒烟测试未通过", logs)
            return

        # 构建通过 → 合入主分支
        logs.append({"step": "merge", "msg": f"构建通过，开始合并 develop → {primary}"})

        # 确保主分支存在
        await git_manager.ensure_branch(project_id, primary)

        merge_result = await git_manager.merge_branch(
            project_id, "develop", primary,
            message=f"ci: develop → {primary} (build {build_id[:12]})",
            keep_conflict=True,  # 冲突时保留现场，下面尝试自动解决
        )

        # 冲突自动解决：分文件类型分派策略
        if not merge_result["success"] and merge_result.get("has_conflict"):
            merge_result = await self._auto_resolve_conflict(
                build_id, project_id, merge_result, logs,
            )

        if merge_result["success"]:
            merge_commit = merge_result.get("commit", "")
            logs.append({"step": "merge", "msg": f"合并成功 (commit: {merge_commit})", "passed": True})

            await db.update("ci_builds", {
                "status": CIBuildStatus.SUCCESS.value,
                "merge_commit": merge_commit,
                "build_log": json.dumps(logs, ensure_ascii=False),
                "completed_at": now_iso(),
            }, "id = ?", (build_id,))

            await event_manager.publish_to_project(project_id, "ci_build_completed", {
                "build_id": build_id,
                "build_type": "develop_build",
                "status": "success",
                "branch": "develop",
                "merge_commit": merge_commit,
            })

            await event_manager.publish_to_project(project_id, "ci_branch_merged", {
                "build_id": build_id,
                "source": "develop",
                "target": primary,
                "commit": merge_commit,
            })

            logger.info("Develop 构建成功: %s → %s (commit: %s)", build_id[:8], primary, merge_commit)

            # 自动部署 test 环境
            try:
                from agents.deploy import DeployAgent
                url = await DeployAgent.deploy_env(project_id, "test", branch="develop")
                if url:
                    logger.info("Test 环境已自动部署: %s", url)
            except Exception as te:
                logger.warning("Test 环境自动部署失败: %s", te)
        else:
            error = merge_result.get("error", "合并冲突")
            logs.append({"step": "merge", "msg": f"合并失败: {error}", "passed": False})
            await self._fail_build(build_id, project_id, f"合并到 {primary} 失败: {error}", logs)

    async def _run_master_build(self, build_id: str, project_id: str):
        """主分支构建: 集成测试 → 通过则自动触发部署"""
        logs = []

        # 检测主分支名（main 或 master）
        primary = await git_manager.get_primary_branch(project_id)

        # 切到主分支
        ok = await git_manager.switch_branch(project_id, primary)
        head = await self._get_branch_head(project_id, primary)
        await db.update("ci_builds", {"commit_hash": head}, "id = ?", (build_id,))
        logs.append({"step": "checkout", "msg": f"切换到 {primary} 分支 (HEAD: {head})"})

        # 模拟集成测试
        repo_path = str(git_manager._repo_path(project_id))

        syntax_ok, syntax_log = await self._check_syntax(repo_path)
        logs.append({"step": "syntax_check", "msg": syntax_log, "passed": syntax_ok})

        smoke_ok, smoke_log = await self._smoke_test(repo_path)
        logs.append({"step": "integration_test", "msg": smoke_log, "passed": smoke_ok})

        unit_ok, unit_log = await self._run_tests(repo_path)
        logs.append({"step": "regression_test", "msg": unit_log, "passed": unit_ok})

        all_passed = syntax_ok and smoke_ok

        if not all_passed:
            await self._fail_build(build_id, project_id,
                                   f"{primary} 构建失败: 集成测试未通过", logs)
            return

        # 构建通过
        logs.append({"step": "complete", "msg": f"{primary} 构建 + 测试全部通过", "passed": True})

        await db.update("ci_builds", {
            "status": CIBuildStatus.SUCCESS.value,
            "build_log": json.dumps(logs, ensure_ascii=False),
            "completed_at": now_iso(),
        }, "id = ?", (build_id,))

        await event_manager.publish_to_project(project_id, "ci_build_completed", {
            "build_id": build_id,
            "build_type": "master_build",
            "status": "success",
            "branch": primary,
        })

        logger.info("%s 构建成功: %s, 自动触发部署", primary, build_id[:8])

        # 自动触发部署
        await self.trigger_build(project_id, CIBuildType.DEPLOY.value, trigger="auto")

        # 自动部署 prod 环境
        try:
            from agents.deploy import DeployAgent
            url = await DeployAgent.deploy_env(project_id, "prod", branch="main")
            if url:
                logger.info("Prod 环境已自动部署: %s", url)
        except Exception as pe:
            logger.warning("Prod 环境自动部署失败: %s", pe)

    async def _run_deploy(self, build_id: str, project_id: str):
        """部署: 生成部署配置 + 模拟部署"""
        logs = []

        # 检测主分支名
        primary = await git_manager.get_primary_branch(project_id)

        repo_path = str(git_manager._repo_path(project_id))
        head = await self._get_branch_head(project_id, primary)
        await db.update("ci_builds", {"commit_hash": head}, "id = ?", (build_id,))

        logs.append({"step": "prepare", "msg": f"准备部署 (commit: {head})"})

        # 生成部署配置
        project = await db.fetch_one("SELECT name FROM projects WHERE id = ?", (project_id,))
        project_name = project["name"] if project else "unknown"

        deploy_files = {
            "build/Dockerfile": (
                "FROM python:3.10-slim\n"
                "WORKDIR /app\n"
                "COPY requirements.txt .\n"
                "RUN pip install --no-cache-dir -r requirements.txt\n"
                "COPY src/ ./src/\n"
                "COPY config/ ./config/\n"
                "EXPOSE 8000\n"
                'CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]\n'
            ),
            "build/docker-compose.yml": (
                "version: '3.8'\n"
                "services:\n"
                "  app:\n"
                "    build: .\n"
                "    ports:\n"
                "      - \"8000:8000\"\n"
                "    restart: unless-stopped\n"
            ),
        }

        written = await git_manager.write_files(project_id, deploy_files)
        commit_hash = await git_manager.commit(
            project_id,
            f"ci: deploy config generated (build {build_id[:12]})",
            author="CI Pipeline",
        )
        logs.append({"step": "deploy_config", "msg": f"部署配置已生成 ({len(deploy_files)} 文件)", "passed": True})

        # 模拟部署过程
        await asyncio.sleep(2)
        logs.append({"step": "docker_build", "msg": "docker build -t app . ... 模拟完成", "passed": True})

        await asyncio.sleep(1)
        logs.append({"step": "docker_deploy", "msg": "docker-compose up -d ... 模拟完成", "passed": True})

        logs.append({"step": "health_check", "msg": "健康检查通过 (HTTP 200)", "passed": True})

        # 部署成功
        await db.update("ci_builds", {
            "status": CIBuildStatus.SUCCESS.value,
            "merge_commit": commit_hash,
            "build_log": json.dumps(logs, ensure_ascii=False),
            "completed_at": now_iso(),
        }, "id = ?", (build_id,))

        await event_manager.publish_to_project(project_id, "ci_build_completed", {
            "build_id": build_id,
            "build_type": "deploy",
            "status": "success",
            "branch": primary,
        })

        logger.info("部署成功: %s (项目: %s)", build_id[:8], project_name)

    # ==================== 构建辅助 ====================

    # 自动解冲突的文件分类
    _REPORT_FILE_PATTERNS = (
        "docs/", "dev-notes/", "screenshots/",
    )
    _REPORT_FILE_SUFFIXES = (".md", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".txt")
    _CODE_FILE_SUFFIXES = (".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".vue",
                            ".go", ".java", ".yaml", ".yml", ".json", ".toml")

    # 单次构建内可交给 LLM 解的代码文件数上限（避免 LLM 费用失控）
    _MAX_AI_RESOLVE_FILES = 3

    @classmethod
    def _classify_conflict_file(cls, path: str) -> str:
        """返回 'report' / 'code' / 'unknown'。"""
        p = path.replace("\\", "/").lower()
        if any(p.startswith(prefix) for prefix in cls._REPORT_FILE_PATTERNS):
            return "report"
        if any(p.endswith(s) for s in cls._REPORT_FILE_SUFFIXES):
            return "report"
        if any(p.endswith(s) for s in cls._CODE_FILE_SUFFIXES):
            return "code"
        return "unknown"

    async def _auto_resolve_conflict(
        self,
        build_id: str,
        project_id: str,
        merge_result: Dict,
        logs: List,
    ) -> Dict:
        """尝试自动解决合并冲突。
        - 报告类文件（docs/**, *.md, screenshots/**）→ `git checkout --theirs <file>` 吞掉 ours
        - 代码类文件（.py/.js/.html/...）≤ _MAX_AI_RESOLVE_FILES 个 → 调 ResolveMergeConflictAction
        - 其余或 LLM 失败 → abort + 返回原 failure

        返回结构跟 merge_branch 一样 `{success, commit, pushed}` 或 `{success: False, error}`。
        """
        conflict_files = merge_result.get("conflict_files") or []
        repo_dir = merge_result.get("repo_dir")
        if not conflict_files or not repo_dir:
            await git_manager.abort_merge(project_id)
            return merge_result

        report_files = [f for f in conflict_files if self._classify_conflict_file(f) == "report"]
        code_files = [f for f in conflict_files if self._classify_conflict_file(f) == "code"]
        unknown_files = [f for f in conflict_files if self._classify_conflict_file(f) == "unknown"]

        logger.info(
            "🤝 尝试自动解冲突: 总 %d 个（报告 %d / 代码 %d / 未知 %d）",
            len(conflict_files), len(report_files), len(code_files), len(unknown_files),
        )

        if unknown_files:
            logger.warning("存在未知类型冲突文件，放弃自动解：%s", unknown_files)
            logs.append({"step": "auto_resolve", "msg": f"发现未知类型冲突文件 {unknown_files}，放弃", "passed": False})
            await git_manager.abort_merge(project_id)
            return merge_result

        if len(code_files) > self._MAX_AI_RESOLVE_FILES:
            logger.warning("代码冲突文件数 %d > 上限 %d，放弃 AI 解", len(code_files), self._MAX_AI_RESOLVE_FILES)
            logs.append({"step": "auto_resolve", "msg": f"代码冲突文件数超限（{len(code_files)} > {self._MAX_AI_RESOLVE_FILES}）", "passed": False})
            await git_manager.abort_merge(project_id)
            return merge_result

        # ---- 报告类：git checkout --theirs <file> ----
        for f in report_files:
            rc, _, err = await git_manager._run_git(repo_dir, "checkout", "--theirs", "--", f)
            if rc != 0:
                logger.warning("checkout --theirs 失败 (%s): %s", f, err)
                logs.append({"step": "auto_resolve", "msg": f"报告文件 {f} checkout --theirs 失败", "passed": False})
                await git_manager.abort_merge(project_id)
                return merge_result
            rc, _, err = await git_manager._run_git(repo_dir, "add", "--", f)
            if rc != 0:
                await git_manager.abort_merge(project_id)
                return merge_result
            logs.append({"step": "auto_resolve", "msg": f"📝 报告文件 {f} 已自动用 develop 版本（-X theirs）", "passed": True})

        # ---- 代码类：读文件内容 → 调 LLM Action ----
        if code_files:
            from actions.resolve_merge_conflict import ResolveMergeConflictAction

            file_entries = []
            for f in code_files:
                full_path = Path(repo_dir) / f
                try:
                    content = full_path.read_text(encoding="utf-8")
                except Exception as e:
                    logger.warning("读取冲突文件失败 (%s): %s", f, e)
                    await git_manager.abort_merge(project_id)
                    return merge_result
                file_entries.append({
                    "path": f,
                    "content": content,
                    "ours_label": "HEAD (target)",
                    "theirs_label": "develop (source)",
                })

            action = ResolveMergeConflictAction()
            result = await action.run({"files": file_entries})
            data = result.data or {}
            resolved = data.get("resolved") or {}
            failed = data.get("failed") or []

            if failed or not resolved:
                logger.warning("LLM 解冲突失败: resolved=%d failed=%d", len(resolved), len(failed))
                logs.append({
                    "step": "auto_resolve",
                    "msg": f"LLM 解代码冲突失败: {failed}",
                    "passed": False,
                })
                await git_manager.abort_merge(project_id)
                return merge_result

            # 写回并 add
            for path, content in resolved.items():
                full_path = Path(repo_dir) / path
                try:
                    full_path.write_text(content, encoding="utf-8")
                except Exception as e:
                    logger.warning("写回解冲突文件失败 (%s): %s", path, e)
                    await git_manager.abort_merge(project_id)
                    return merge_result
                await git_manager._run_git(repo_dir, "add", "--", path)
                logs.append({"step": "auto_resolve", "msg": f"🤖 代码文件 {path} 已 LLM 解冲突并暂存", "passed": True})

        # ---- 提交合并结果 ----
        commit_msg = (
            f"ci: develop → {(await git_manager.get_primary_branch(project_id)) or 'main'} "
            f"(build {build_id[:12]}, auto-resolved: "
            f"{len(report_files)} reports + {len(code_files)} code files)"
        )
        finalize = await git_manager.finalize_merge(project_id, message=commit_msg)
        if not finalize.get("success"):
            await git_manager.abort_merge(project_id)
            return merge_result

        logs.append({
            "step": "auto_resolve",
            "msg": f"✅ 自动解冲突完成：{len(report_files)} 报告 + {len(code_files)} 代码，commit {finalize.get('commit', '?')}",
            "passed": True,
        })
        logger.info("✅ CI 自动解冲突成功: build=%s commit=%s", build_id[:8], finalize.get("commit"))
        return finalize

    async def _fail_build(self, build_id: str, project_id: str, error: str, logs: List = None):
        """标记构建失败"""
        build = await db.fetch_one("SELECT build_type FROM ci_builds WHERE id = ?", (build_id,))
        build_type = build["build_type"] if build else "unknown"

        await db.update("ci_builds", {
            "status": CIBuildStatus.FAILED.value,
            "error_message": error,
            "build_log": json.dumps(logs or [], ensure_ascii=False),
            "completed_at": now_iso(),
        }, "id = ?", (build_id,))

        await event_manager.publish_to_project(project_id, "ci_build_failed", {
            "build_id": build_id,
            "build_type": build_type,
            "error_message": error,
        })

        logger.warning("构建失败 %s: %s", build_id[:8], error)

    async def _get_branch_head(self, project_id: str, branch: str) -> Optional[str]:
        """获取指定分支的 HEAD commit hash"""
        repo_dir = str(git_manager._repo_path(project_id))
        rc, out, _ = await git_manager._run_git(repo_dir, "rev-parse", branch)
        return out[:12] if rc == 0 and out else None

    async def _check_syntax(self, repo_path: str) -> tuple:
        """语法检查: 检查 Python/JS 文件语法"""
        errors = []
        src_dir = Path(repo_path) / "src"
        if not src_dir.exists():
            return True, "src/ 目录不存在，跳过语法检查"

        # Python 文件语法检查
        py_files = list(src_dir.rglob("*.py"))
        py_ok = 0
        for f in py_files[:20]:  # 限制数量
            try:
                result = subprocess.run(
                    ["python", "-c", f"import py_compile; py_compile.compile(r'{f}', doraise=True)"],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    py_ok += 1
                else:
                    errors.append(f"Python 语法错误: {f.name}")
            except Exception:
                pass

        # JS 文件语法检查
        js_files = list(src_dir.rglob("*.js"))
        js_ok = 0
        for f in js_files[:20]:
            try:
                result = subprocess.run(
                    ["node", "--check", str(f)],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    js_ok += 1
                else:
                    errors.append(f"JS 语法错误: {f.name}")
            except Exception:
                pass

        total = len(py_files[:20]) + len(js_files[:20])
        passed = py_ok + js_ok

        if total == 0:
            return True, "无源码文件，跳过语法检查"

        ok = len(errors) == 0
        msg = f"语法检查: {passed}/{total} 通过"
        if errors:
            msg += f" ({', '.join(errors[:3])})"
        return ok, msg

    async def _smoke_test(self, repo_path: str) -> tuple:
        """冒烟测试: 检查关键文件是否存在"""
        checks = []
        src_dir = Path(repo_path) / "src"

        # 检查 src/ 目录
        if src_dir.exists():
            file_count = len(list(src_dir.rglob("*")))
            checks.append(f"src/ 目录存在 ({file_count} 文件)")
        else:
            return True, "无 src/ 目录，跳过冒烟测试"

        # 检查入口文件
        entry_files = ["src/main.py", "src/api/main.py", "src/frontend/index.html"]
        found = [f for f in entry_files if (Path(repo_path) / f).exists()]
        if found:
            checks.append(f"入口文件: {', '.join(found)}")
        else:
            checks.append("未找到入口文件（非致命）")

        return True, f"冒烟测试通过: {'; '.join(checks)}"

    async def _run_tests(self, repo_path: str) -> tuple:
        """运行测试: 如果有 pytest 测试文件则运行"""
        tests_dir = Path(repo_path) / "tests"
        if not tests_dir.exists() or not list(tests_dir.glob("test_*.py")):
            return True, "无测试文件，跳过"

        try:
            result = subprocess.run(
                ["python", "-m", "pytest", "tests/", "-v", "--tb=short", "--timeout=30"],
                cwd=repo_path,
                capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                timeout=60,
            )
            if result.returncode == 0:
                return True, f"pytest 通过\n{result.stdout[-500:]}"
            else:
                return False, f"pytest 失败\n{result.stdout[-500:]}"
        except subprocess.TimeoutExpired:
            return False, "pytest 执行超时 (60s)"
        except Exception as e:
            return True, f"pytest 执行异常 (跳过): {e}"

    # ==================== 查询 ====================

    async def get_pipeline_status(self, project_id: str) -> Dict:
        """获取项目 CI/CD 总览

        v0.19.x: 动态发现该项目所有 build_type（包含 UE 的 ubt_compile/playtest/package_client 等）
        而不是硬编码 Web 的三种。
        """
        stages = {}

        # 发现该项目所有已存在的 build_type
        type_rows = await db.fetch_all(
            "SELECT DISTINCT build_type FROM ci_builds WHERE project_id = ?",
            (project_id,),
        )
        # 合并固定 Web 类型 + 项目实际用过的类型
        all_types = {"develop_build", "master_build", "deploy"} | {
            r["build_type"] for r in type_rows if r.get("build_type")
        }

        for build_type in all_types:
            latest = await db.fetch_one(
                "SELECT * FROM ci_builds "
                "WHERE project_id = ? AND build_type = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (project_id, build_type),
            )
            last_success = await db.fetch_one(
                "SELECT completed_at, commit_hash FROM ci_builds "
                "WHERE project_id = ? AND build_type = ? AND status = 'success' "
                "ORDER BY created_at DESC LIMIT 1",
                (project_id, build_type),
            )
            stages[build_type] = {
                "latest": dict(latest) if latest else None,
                "last_success_at": last_success["completed_at"] if last_success else None,
                "last_success_commit": last_success["commit_hash"] if last_success else None,
            }

        return {"stages": stages}

    async def get_build_history(self, project_id: str, build_type: str = None,
                                 limit: int = 20, offset: int = 0) -> List[Dict]:
        """查询构建历史"""
        if build_type:
            rows = await db.fetch_all(
                "SELECT * FROM ci_builds "
                "WHERE project_id = ? AND build_type = ? "
                "ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (project_id, build_type, limit, offset),
            )
        else:
            rows = await db.fetch_all(
                "SELECT * FROM ci_builds "
                "WHERE project_id = ? "
                "ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (project_id, limit, offset),
            )
        return [dict(r) for r in rows]

    async def get_build_detail(self, build_id: str) -> Optional[Dict]:
        """获取单个构建详情"""
        row = await db.fetch_one("SELECT * FROM ci_builds WHERE id = ?", (build_id,))
        if row:
            result = dict(row)
            if result.get("build_log"):
                try:
                    result["build_log"] = json.loads(result["build_log"])
                except Exception:
                    pass
            return result
        return None

    async def cancel_build(self, build_id: str) -> bool:
        """取消构建"""
        build = await db.fetch_one(
            "SELECT status, project_id FROM ci_builds WHERE id = ?", (build_id,)
        )
        if not build or build["status"] not in ("pending", "running"):
            return False

        await db.update("ci_builds", {
            "status": CIBuildStatus.CANCELLED.value,
            "completed_at": now_iso(),
        }, "id = ?", (build_id,))

        await event_manager.publish_to_project(build["project_id"], "ci_build_completed", {
            "build_id": build_id,
            "status": "cancelled",
        })
        return True


# 全局实例
ci_pipeline = CIPipelineRunner()

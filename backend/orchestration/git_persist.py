"""Agent 产出的文件落到 Git 仓库：改名，写入，提交，推送，提交后部署 dev 环境。

`handle_git_files` 从 Agent 结果里取 `files`，为空或不是字典时返回 None。路径里的非 ASCII 字符会被去掉，
`docs/` 下的 `.md` 保留原名，改完回写 `result["files"]`。项目登记了自定义仓库路径时先告诉 `git_manager`，
仓库不存在时初始化。手动挡的项目只写文件，其他项目写入并提交。`result` 里的 `_media_files` 是二进制
媒体文件，直接写进仓库目录，非手动挡时单独提交并推送，提交消息的标签取自 `MEDIA_COMMIT_LABELS`。
推送没成功时记 warning 并写一条 `git_push_failed` 日志。DevAgent 和 ArchitectAgent 有提交时，经
`runtime_facade` 取 DeployAgent 部署 dev 环境，失败只记 warning。

约定（`orchestration` 包里按职责拆出的模块都一样）：

- 函数体从 `TicketOrchestrator` 的同名方法原样搬来，函数名去掉了前导下划线。改动只有
  `self` 写成 `orch`，以及下面单独列出的几处。
- `TicketOrchestrator` 上保留同名方法，只做转发。这里的函数互相调用、调用别的模块里的
  逻辑都走 `orch.xxx`，测试给实例打的桩才会生效。
- `db` 由转发方法在调用时传入，这里不导入它。测试用
  `monkeypatch.setattr(orchestrator, "db", test_db)` 换库，函数必须拿到同一个对象。
- 状态都放在 `orch` 上，这个模块自己不存状态。
- 函数内的延迟导入保持原样，测试的打桩打在这些源模块上。

`MEDIA_COMMIT_LABELS` 这个常量也搬到了这里，类上的 `_MEDIA_COMMIT_LABELS` 指向同一个对象。函数里仍然经
`orch._MEDIA_COMMIT_LABELS` 这个类属性读它，和搬之前一样。
"""
import logging
import time
from typing import Dict, Optional

from git_manager import git_manager

logger = logging.getLogger("orchestrator")

# 二进制媒体文件的 commit 消息标签。key 可以是 (agent, action) 或仅 agent。
# 这条通道被多个 Agent 复用（TestAgent 截图 / ArtistAgent 占位图），
# 不按来源区分会产出「[ArtistAgent] 测试截图」这种自相矛盾的提交记录。
MEDIA_COMMIT_LABELS = {
    ("TestAgent", "run_tests"):          "测试截图",
    ("TestAgent", "run_playtest"):       "Playtest 截图",
    ("ArtistAgent", "generate_assets"):  "资产占位图",
    "TestAgent":    "测试截图",
    "ArtistAgent":  "美术资产",
    "UEEditorAgent": "UE 编辑器截图",
}


async def handle_git_files(
    orch, db,
    project_id: str,
    ticket_id: str,
    requirement_id: str,
    agent_name: str,
    action: str,
    result: Dict,
) -> Optional[Dict]:
    """从 Agent 结果中提取 files，写入 Git 仓库并提交"""
    files = result.get("files", {})
    if not files or not isinstance(files, dict):
        return None

    # === 强制将中文文件名转为英文（仅对非 docs/ 目录的代码文件）===
    # docs/ 下的 Markdown 文档保留中文名，方便人工阅读和知识库索引
    import re
    sanitized_files = {}
    for path, content in files.items():
        is_doc = path.startswith("docs/") and path.endswith(".md")
        if not is_doc and any(ord(c) > 127 for c in path):
            # 提取目录和扩展名
            parts = path.rsplit("/", 1)
            dir_part = parts[0] + "/" if len(parts) > 1 else ""
            filename = parts[-1]
            name, ext = (filename.rsplit(".", 1) if "." in filename else (filename, ""))
            # 去掉非 ASCII，保留英文数字下划线横线
            safe_name = re.sub(r'[^\x00-\x7f]', '', name).strip("_- ")
            if not safe_name:
                # 全是中文，用哈希替代
                safe_name = f"module_{abs(hash(name)) % 100000}"
            sanitized_files[f"{dir_part}{safe_name}.{ext}" if ext else f"{dir_part}{safe_name}"] = content
            logger.info("📝 文件名修正: %s → %s", path, list(sanitized_files.keys())[-1])
        else:
            sanitized_files[path] = content
    files = sanitized_files
    result["files"] = files  # 回写，确保后续产物记录也用修正后的路径

    start_time = time.time()

    # 确保仓库已初始化
    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if project:
        # 恢复自定义仓库路径映射（防止重启后丢失）
        repo_path = project.get("git_repo_path")
        if repo_path and project_id not in git_manager._custom_paths:
            from git_manager import PROJECTS_DIR
            default_path = str(PROJECTS_DIR / project_id)
            if repo_path != default_path:
                git_manager.set_project_path(project_id, repo_path)

    if not git_manager.repo_exists(project_id):
        if project:
            await git_manager.init_repo(project_id, project["name"], project.get("description", ""))

    # 记录命令：写入文件
    step = 0
    for file_path in files.keys():
        await orch._record_command(
            project_id, ticket_id, requirement_id, agent_name, action,
            step, "write_file", f"写入文件: {file_path}", "success"
        )
        step += 1

    # 构建有意义的 commit message
    ticket = await db.fetch_one("SELECT title FROM tickets WHERE id = ?", (ticket_id,))
    ticket_title = ticket["title"] if ticket else ticket_id
    file_names = ", ".join(f.split("/")[-1] for f in list(files.keys())[:3])
    if len(files) > 3:
        file_names += f" +{len(files)-3}"
    action_labels = {
        "design_architecture": "架构设计",
        "develop": "开发",
        "rework": "返工",
        "fix_issues": "修复",
        "acceptance_review": "验收",
        "run_tests": "测试",
    }
    action_label = action_labels.get(action, action)
    commit_msg = f"[{agent_name}] {action_label}: {ticket_title} ({file_names})"

    # 手动挡：只写文件，不自动 git commit
    project_mode = (project or {}).get("mode", "auto") if project else "auto"
    if project_mode == "manual":
        logger.info("🔧 手动挡：跳过 git commit，直接写入文件 (%d 个)", len(files))
        git_result = await git_manager.write_files_only(project_id, files)
    else:
        git_result = await git_manager.write_and_commit(
            project_id, files, commit_msg, agent=agent_name
        )

    # 写入二进制媒体文件（截图 / 占位图等），手动挡也只写不 commit
    media_files: dict = result.pop("_media_files", {}) or {}
    if media_files:
        try:
            repo_dir = git_manager._repo_path(project_id)
            for media_path, img_bytes in media_files.items():
                dest = repo_dir / media_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(img_bytes)
                logger.info("🖼️ 媒体文件写入: %s (%d bytes)", media_path, len(img_bytes))
            if project_mode != "manual":
                # 这条通道最早只给 TestAgent 的截图用，消息写死了「测试截图」。
                # 现在 ArtistAgent 的占位图也走这里，硬编码会产出
                # 「[ArtistAgent] 测试截图: ...」这种驴唇不对马嘴的 commit。
                media_label = orch._MEDIA_COMMIT_LABELS.get(
                    (agent_name, action), orch._MEDIA_COMMIT_LABELS.get(agent_name, "媒体文件"),
                )
                media_commit = await git_manager.commit(
                    project_id,
                    f"[{agent_name}] {media_label}: {ticket_title}",
                    author=agent_name,
                )
                await git_manager.push(project_id)
                logger.info("🖼️ %s已提交: %s", media_label, media_commit)
        except Exception as me:
            logger.warning("媒体文件提交失败（不影响主流程）: %s", me)
    # 记录当前分支名到 git_result
    if git_result:
        try:
            current_branch = await git_manager.get_current_branch(project_id)
            git_result["branch"] = current_branch
        except Exception:
            pass

    elapsed = int((time.time() - start_time) * 1000)

    # 记录命令：git commit
    if git_result and git_result.get("commit_hash"):
        await orch._record_command(
            project_id, ticket_id, requirement_id, agent_name, action,
            step, "git_commit",
            f"git commit -m \"{commit_msg}\" → {git_result['commit_hash']}",
            "success", elapsed
        )
        step += 1

        # 记录命令：git push
        if git_result.get("pushed"):
            await orch._record_command(
                project_id, ticket_id, requirement_id, agent_name, action,
                step, "git_push", "git push origin main", "success"
            )
        else:
            # push 失败：git_manager 已按原因分类并推送可执行的修复卡
            status = git_manager.get_last_push_status(project_id) or {}
            push_err_msg = (
                f"{agent_name}.{action} {status.get('title') or 'git push 失败'}。"
                f"{status.get('summary') or '代码已 commit 但未推送到远端。'}"
                f" 工单: {(ticket_id or '')[-8:] or '(需求级)'}。"
                f"{status.get('next_step') or ''}"
            )
            logger.warning("⚠️ %s", push_err_msg)
            await orch._log(
                project_id, requirement_id, ticket_id, agent_name,
                "git_push_failed", None, None, push_err_msg, "warn",
            )

        # 自动部署 dev 环境（Agent 完成文件提交后）
        if agent_name in ("DevAgent", "ArchitectAgent"):
            try:
                import runtime_facade
                await runtime_facade.agents_deploy().DeployAgent.deploy_env(project_id, "dev")
            except Exception as de:
                logger.warning("Dev 环境自动部署失败: %s", de)

    return git_result

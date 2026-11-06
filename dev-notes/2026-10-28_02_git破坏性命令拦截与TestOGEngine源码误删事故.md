# git 破坏性命令统一拦截 与 TestOGEngine 源码误删事故

2026-10-28

## 起因

用户报告 `D:\UEProjects\TestOGEngine`（PRJ-20261027-d9907a）执行工单时 `Source/` 等源码被删。排查 `ticket_command_log`：`git clean -fd --exclude=...` 从 23:33 到次日 14:17 被执行 **1763 次**（orchestrator 依赖等待每 30 秒重试 `process_ticket` → `switch_branch`）。

根因链：
1. `create_project` 对已存在目录（无 .git）误走「全新建仓库流程」：`git init` + `git add .` + `commit`。commit 失败留下**无任何提交的空仓库**（`.git/objects` 无 commit 对象），整个项目变成 untracked。
2. `switch_branch` 里 `git clean -fd` 在空仓库上把 untracked 源码当垃圾删除，exclude 只保护了 Binaries/Intermediate/Saved/DerivedDataCache，漏掉 Source/Config/Content/.uproject/.sln。

源码从未成功 commit，git 无法恢复。

## 实现

1. `git_manager.switch_branch`：**移除 `git clean` 与 `checkout .`**，改成纯 `git checkout`。自动流程不再有任何删除/覆盖能力，冲突时返回 False 交上层兜底。
2. `actions/chat/create_project.py`：已存在且非空目录（无 .git）按「导入已有项目」处理，跳过 git init/add/commit。
3. `permissions/gate.py` `_HIGH_RISK_RULES` 6→11 条：补 `git clean`、`del /s /q`、`Remove-Item -Recurse`、`rmdir /s`、`git reset --hard`，让用户主动触发的删除命令走 PermissionGate 弹卡片。
4. `git_manager._run_git` 加 `_destructive_git_reason` 统一拦截：clean / reset --hard / rm / checkout . -- <path> / stash drop|clear 默认拒绝（rc=1 + 落 status=blocked），合法内部操作显式 `allow_destructive=True`（rollback_paths、checkpoint 恢复、CI 冲突解决、隔离部署目录 clean）。
5. `main.py` 修正误导性启动日志（原硬编码「高风险规则 0 条」）。

保留拦截不放行：`create_project.py` 与 `api/projects.py` 里「有 remote 导入非空目录」时的 `checkout .`（覆盖本地文件），现在会显式失败而非静默覆盖。

## 验证

`_destructive_git_reason` 18 个边界用例全通过（clean/reset --hard/rm/checkout ./--/stash drop 命中；reset --soft/--mixed、rm --cached、checkout 分支、add/commit/push 放行）。相关文件 `py_compile` 通过。

## 遗留

TestOGEngine 源码需用户从远端/备份或 VS 本地历史恢复；DB 残留 3 个工单与损坏的 `.git`（HEAD 指向不存在分支、无 commit）。

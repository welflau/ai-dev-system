# Git 工程化规范

> 本项目遵循三层分支模型（feat → develop → main）+ 语义化提交消息。

## 分支模型

```
main          ← 生产发布，永远可部署
  ↑  merge after ReviewAgent 通过
develop       ← 集成分支，所有 feat 合到这里
  ↑  PR
feat/<ticket-id>-<slug>   ← DevAgent 每个工单一个分支
```

**硬规则**：
- **禁止**直接 push 到 `main` 或 `develop`
- DevAgent 工单一开始就切 `feat/TICKET-<id>-<short-slug>`，自测通过再 merge 到 `develop`
- ReviewAgent 审查通过 + TestAgent 测试通过 → 合并 `develop` → `main`
- 分支名只允许字母/数字/`-`/`/`，例：`feat/ticket-abc123-add-counter`

## 提交消息规范（Conventional Commits 精简版）

格式：`<type>: <中文简述>`

| type | 用途 | 示例 |
|------|------|------|
| `feat` | 新增功能 | `feat: 右下角加访问计数器` |
| `fix` | Bug 修复 | `fix: 计数器首次加载显示 undefined` |
| `refactor` | 重构（无功能变化） | `refactor: 把计数逻辑抽到 useVisitCount` |
| `ui` | 仅样式调整 | `ui: 计数器改为半透明背景` |
| `docs` | 仅文档 | `docs: 更新 Skills 使用说明` |
| `chore` | 杂项（依赖、构建） | `chore: 升级 FastAPI 到 0.115` |
| `test` | 测试相关 | `test: 加访问计数 E2E 用例` |

**规则**：
- 标题一行 ≤ 60 字，聚焦"做了什么"
- 多余细节写到 body（空一行 + 段落）
- 不要写 "改了一下"、"update" 这种无信息消息
- 一个提交只做一件事，不要把重构和功能混在一起

## 禁止操作清单

| 操作 | 原因 |
|------|------|
| `git push --force` 到共享分支 | 覆盖他人提交 |
| `git reset --hard` 到远程过的 commit | 丢失历史 |
| `git commit --no-verify` | 跳过 pre-commit hook |
| `git config` 改全局配置 | 影响机器其他项目 |
| 直接 push 到 `main` | 破坏发布流程 |

如果 hook 失败：**先修问题**，再重新提交；不要绕过。

## DevAgent 典型流程

```bash
# 1. 从 develop 切出 feat 分支
git fetch origin
git checkout develop && git pull
git checkout -b feat/ticket-<id>-<slug>

# 2. 写代码
# ... 代码改动 ...

# 3. 自测通过后提交
git add <具体文件>        # 不要 git add -A / git add .
git commit -m "feat: <描述>"

# 4. 推到远程
git push -u origin feat/ticket-<id>-<slug>

# 5. 由 orchestrator 触发后续 Review → Test → Merge
```

## 合并策略

- `feat → develop`：squash merge（一个工单 = 一个 commit 进 develop）
- `develop → main`：merge commit（保留集成历史）
- 冲突：**先尝试合并解决，不要丢任何一边的改动**；解决不了再找 DevAgent 重做

## 文件粒度

- 每个提交只 add 本次改动涉及的文件，**不要** `git add .` / `git add -A`
- `.env`、`*.key`、`*.pem`、`node_modules/`、`__pycache__/`、`.DS_Store` 绝不提交
- 大文件（>10MB）用 LFS 或不提交，DeployAgent 另行处理

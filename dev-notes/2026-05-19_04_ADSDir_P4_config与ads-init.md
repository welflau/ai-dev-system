# ADSDir P4：.ads/config.json + /ads-init 命令

> 系列：ADSDir（.ads 目录实现）
> 日期：2026-05-19
> 提交：`7b24cee`

---

## P4 实现内容

### .ads/config.json 格式

```json
{
  "project_name": "ThunderStrike",
  "traits": ["engine:ue5", "category:game", "feature:wave-spawner"],
  "description": "像素风纵向卷轴飞行射击游戏"
}
```

创建项目时自动读取，`traits` 与自动检测结果合并（去重），`description` 在未手动填写时自动补充。

### /ads-init 命令

一键初始化项目 `.ads/` 目录：

```
/ads-init
→ 创建 .ads/rules/project-rules.md（规范模板）
→ 创建 .ads/skills/（空目录）
→ 创建 .ads/config.json（当前 traits 导出）
```

---

## ADSDir 系列完整总结

| 阶段 | 功能 | 命令 | 提交 |
|---|---|---|---|
| P1 | `.ads/rules/` 项目级规则注入 | — | `6a3c0db` |
| P2 | `.ads/skills/` 替代 `.Agent/skills/` | — | `55f062a` |
| P3 | `memory.md` 导入/导出 | `/memory-export`、`/memory-import` | `d64f845` |
| P4 | `config.json` + 初始化命令 | `/ads-init` | `7b24cee` |

### 使用流程

```bash
# 1. 初始化
/ads-init

# 2. 编写项目规范
编辑 .ads/rules/project-rules.md

# 3. 安装项目 Skill（可选）
mkdir .ads/skills/my-skill && 编辑 SKILL.md

# 4. 导出记忆备份（可选）
/memory-export  →  git commit .ads/memory.md

# 5. 新成员同步记忆
git pull && /memory-import
```

### .ads/ 目录结构（最终形态）

```
{项目仓库}/.ads/
├── rules/
│   ├── project-rules.md     ← 项目编码规范（自动注入所有 Agent）
│   └── ue-conventions.md    ← UE 专项规范（可选）
├── skills/
│   └── wave-spawner/
│       └── SKILL.md
├── memory.md                ← 记忆快照（可 git 共享）
└── config.json              ← 项目配置（traits 声明）
```

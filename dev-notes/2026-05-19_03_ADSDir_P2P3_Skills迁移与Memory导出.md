# ADSDir P2/P3：.ads/skills/ 迁移 + memory.md 导入导出

> 系列：ADSDir（.ads 目录实现）
> 日期：2026-05-19
> 提交：`55f062a`（P2）、`d64f845`（P3）

---

## P2：.ads/skills/ 替代 .Agent/skills/

### 变化

`_get_project_agent_skills_dir()` 现在优先读 `.ads/skills/`：

```
优先级：
1. {仓库}/.ads/skills/     ← P2 新增（优先）
2. {仓库}/.Agent/skills/   ← 向后兼容（降级）
3. data/project_skills/    ← 最终兜底
```

**两处同步修改**：
- `actions/chat/load_skill.py`：加载 Skill 时判断
- `api/skills.py`：Skill 安装/卸载 API 时判断

### 使用方式

新项目直接在 `.ads/skills/` 创建 Skill：
```
{仓库}/.ads/skills/
└── wave-spawner/
    └── SKILL.md
```

已有项目 `.Agent/skills/` 继续有效，不需要迁移。

---

## P3：memory.md 导入/导出

### 新增两个斜杠命令

**`/memory-export`**：项目记忆 → `.ads/memory.md`

```markdown
# 项目记忆（ThunderStrike）

> 最后导出：2026-05-19

- [📁 project_context] **波次系统用独立配置文件**（2026-05-14）
  WaveConfig.json，不要硬编码
- [💬 behavior_feedback] **不要用 Tick 做重型计算**（2026-05-15）
  改用缓存引用
```

导出后可提交到 git，实现**团队共享项目关键记忆**。

**`/memory-import`**：`.ads/memory.md` → `agent_memory` 表

- 按标题去重，已存在的条目自动跳过
- 支持 4 类型映射（未知类型降级到 `project_context`）

### 典型使用场景

```
开发者 A：/memory-export  →  提交 .ads/memory.md 到 git
开发者 B：git pull        →  拿到最新 memory.md
开发者 B：/memory-import  →  同步到本地 ADS 数据库
```

---

## 下一步：P4

`.ads/config.json` 支持——创建/导入项目时读取 traits 等配置。

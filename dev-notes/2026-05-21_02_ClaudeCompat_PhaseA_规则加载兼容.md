# ClaudeCompat Phase A — 规则加载兼容

> 日期：2026-05-21
> 提交：`e6fde80`
> 系列：ClaudeCompat（ADS 兼容 Claude Code 目录结构）

---

## 目标

`load_project_rules()` 同时支持 `.claude/rules/`、`CLAUDE.md`、`.ads/rules/`、`ADS.md` 四路来源，`.ads/` 优先级高于 `.claude/`，实现已有 Claude Code 项目无需迁移即可接入 ADS。

---

## 改动文件

`backend/skills/loader.py`

---

## 四路合并逻辑

**读取顺序（低 → 高优先级）**：

```
1. .claude/rules/**/*.md   Claude Code 标准规则
       ↓
2. CLAUDE.md               Claude 项目总指令（alwaysApply，限 3000 字符）
       ↓
3. .ads/rules/**/*.md      ADS 专属规则（同名 rel_id 覆盖 .claude/rules/）
       ↓
4. ADS.md                  ADS 项目总指令（alwaysApply，追加最后，优先级最高）
```

**关键设计：用 `rel_id` 作为去重 key**

`.claude/rules/cpp.md` 和 `.ads/rules/cpp.md` 的 `rel_id` 都是 `cpp`，后写覆盖前写，因此 `.ads/rules/cpp.md` 自动替换 `.claude/rules/cpp.md`。

`CLAUDE.md` 和 `ADS.md` 使用固定 key（`__CLAUDE_MD__` / `__ADS_MD__`），不参与规则覆盖逻辑，保证两者都被注入。

```python
# .claude/rules/ → key = "cpp"（相对路径，无前缀）
# .ads/rules/    → key = "cpp"（相同，覆盖上面）
# CLAUDE.md      → key = "__CLAUDE_MD__"（固定，不会被覆盖）
# ADS.md         → key = "__ADS_MD__"（固定，不会被覆盖）
```

---

## 新增辅助方法

`_scan_rules_dir(rules_dir, prefix, out, current_file, scene)` 提取公共扫描逻辑，避免在 `load_project_rules()` 中重复两次相同的过滤代码。

---

## 测试结果（4 个场景全通过）

| 场景 | 验证点 | 结果 |
|------|--------|------|
| 无文件上下文 | CLAUDE.md + ADS.md 注入，paths 规则跳过 | ✅ |
| cpp 文件 | `.ads/rules/cpp.md` 覆盖 `.claude/rules/cpp.md` | ✅ |
| py 文件 | `.ads/rules/python.md` 注入，cpp 规则不注入 | ✅ |
| 注入顺序 | ADS.md 在 CLAUDE.md 之后（优先级更高） | ✅ |

---

## 使用方式

项目中任意一个路径有文件即生效，均不存在时静默跳过：

```
{项目仓库}/
├── CLAUDE.md         ← Claude Code 项目总指令，ADS 自动读取
├── ADS.md            ← ADS 专属项目指令（可选），优先级最高
├── .claude/
│   └── rules/
│       └── cpp.md    ← Claude Code 规则，ADS 自动读取
└── .ads/
    └── rules/
        └── cpp.md    ← 存在时覆盖 .claude/rules/cpp.md
```

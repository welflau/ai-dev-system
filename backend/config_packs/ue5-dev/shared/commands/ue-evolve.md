---
description: 从成功操作中提炼 Skill 草案，推动系统自进化
---

# /ue-evolve

分析本次会话中成功执行的 Python 代码，提炼值得复用的模式，生成 Skill 草案供人工确认。

## 用法

```
/ue-evolve                   # 分析当前会话并生成草案
/ue-evolve --list            # 查看待确认的草案
/ue-evolve --confirm <name>  # 确认某个草案，提升为正式 Skill
```

## 行为

1. 读取本次会话中通过 `/ue-run` 成功执行的代码
2. 用价值判断规则筛选（批量操作/资产导入/Blueprint 创建/DataTable 读写等）
3. 生成 Skill 草案到 `.claude/ue-runtime/pending_skills/`
4. 显示草案列表，提示用户确认

## 价值判断标准（参考 ADS 自进化方案）

以下类型代码会被标记为「值得提炼」：

| 模式 | 示例 |
|------|------|
| 批量修改 Actor 属性 | `for actor in get_all_level_actors(): set_editor_property(...)` |
| 资产导入流程 | `AssetImportTask → import_asset_tasks` |
| Blueprint 类创建 | `BlueprintFactory → create_asset` |
| DataTable 读写 | `export_to_json → Python 修改 → fill_from_json` |
| 关卡 Actor 批量放置 | `spawn_actor_from_class × N + ScopedEditorTransaction` |

## 草案文件格式

```markdown
# UE Skill: actor_batch_modify

> 状态：草案（待确认）
> 提炼时间：2026-05-17
> 提炼原因：批量修改 Actor 属性

## 代码
```python
# 提炼的代码...
```
```

## 草案目录

`.claude/ue-runtime/pending_skills/`
- `INDEX.json` — 草案索引
- `*.md` — 各草案文件

## 确认流程

1. `/ue-evolve --list` 查看草案
2. 检查代码是否通用（去掉项目特定路径）
3. 移动到 `skills/` 目录，删除 `status: draft` 标记
4. 更新 `MEMORY.md` 索引

## 与 ue-session-stop.py 的关系

会话结束时 `ue-session-stop.py` 更新 PROGRESS.md，
`/ue-evolve` 定期（由用户触发）从中提炼 Skill 草案。
自动化 → 手动确认 → 正式 Skill，形成知识飞轮。

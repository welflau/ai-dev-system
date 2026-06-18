---
description: 从事故记录自动提炼反模式草案，管理 AntiPatterns.md
---

# /ue-antipatterns

扫描 `.claude/ue-runtime/incidents/` 目录，从事故记录中提炼反模式草案，写入 `AntiPatterns.md`。

## 用法

```
/ue-antipatterns              # 扫描新事故，生成 pending 草案
/ue-antipatterns --list       # 查看待确认条目
/ue-antipatterns --confirm <ID>  # 确认某条（pending → confirmed）
/ue-antipatterns --dry-run    # 只打印，不写入
```

## 执行前置

```python
config     = json.loads(open('.claude/ue-config.json', encoding='utf-8').read())
unrealecc  = config['unrealecc_root']
```

## 行为

1. 读取 `incidents/*.md`，解析 frontmatter 和「潜在反模式」字段
2. 与现有 `AntiPatterns.md` 去重（按 source 路径）
3. 为每条新事故生成 ID（BP-/PY-/CI-/UE- 前缀 + 序号）
4. 以 `status: pending` 写入 `AntiPatterns.md`，等待确认

## 事故记录格式

新建事故文件：`.claude/ue-runtime/incidents/YYYYMMDD_<关键词>.md`

```markdown
---
date: 2026-05-XX
module: Blueprint|UEPython|CI|GAS|DataTable|Editor
severity: high|medium|low
trigger_action: <触发操作关键词>
status: confirmed
---

## 现象
<做了什么 → 出现了什么>

## 根因
<哪个假设是错的>

## 正确做法
<应该怎么做>

## 误导性默认值
<AI 或开发者通常会怎么猜错>

## 潜在反模式
<一句话泛化描述>
```

## 与 PSP 的关系

```
incidents/（事故原始记录）
    ↓ /ue-antipatterns 提炼
AntiPatterns.md（反模式百科，含 pending/confirmed）
    ↓ 高频高风险条目升级
PSP.md（项目特化做法，AI P-Start 必查）
```

## 示例

```
/ue-antipatterns
  [新草案] BP-003  BlueprintFactory 父类设置...
  已生成 1 条 pending 草案

/ue-antipatterns --list
  BP-003 [★★] BlueprintFactory parent_class
  来源：incidents/20260521_blueprint_factory.md

/ue-antipatterns --confirm BP-003
  已确认：BP-003 → confirmed
```

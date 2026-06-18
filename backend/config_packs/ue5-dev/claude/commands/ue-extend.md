---
description: 自动扩展 UE 引擎子系统的 Python API 覆盖能力
---

# /ue-extend

给定目标模块名，Agent 自动完成 6 阶段流程：读源码、审计能力缺口、写 C++ 扩展、生成能力文档和验证脚本。

## 用法

```
/ue-extend <模块名>
```

## 执行前置

读取 `.claude/ue-config.json`，根据引擎版本调整执行策略：

```python
config        = json.loads(open('.claude/ue-config.json').read())
ue_python     = config['ue_python_script']
has_source    = config.get('has_source', False)
engine_source = config.get('engine_source_path', '')
```

根据 `has_source` 走不同分支（详见下方）。

## 行为

调用 `ue-py-skills` 中的 `/ue-py-extend` skill（需先安装，见 `docs/ue-py-skills-setup.md`）。

### 源码版（has_source = true）— 完整 6 阶段

```
Phase 0  现状盘点    → 检查已有文档，避免重复工作
Phase 1  读源码+审计 → 在 engine_source_path 下读 .cpp + .h
                       四维度评估（资产面/验证/控制面/观测）
Phase 2  验证        → 逐属性实测，FObjectWriter 二进制对比找盲区
Phase 3  写 C++ 填缺口 → UBlueprintFunctionLibrary + UFUNCTION
Phase 4  生成能力文档 → 供后续 Agent 直接使用
Phase 5  独立复审    → spawn 新 Agent 从零验证
```

Phase 1 的源码搜索使用引擎路径：
```bash
grep -rn "TargetClass" {engine_source_path}/Runtime/AIModule/ --include="*.h" --include="*.cpp"
```

### 商店版（has_source = false）— 降级 4 阶段

```
Phase 0  现状盘点    → 同上
Phase 1  读头文件    → 只读 engine_path/Engine/Source 下的 .h 文件
                       跳过 .cpp 实现细节分析
                       ⚠️ 可能漏掉 Serialize() 隐藏状态
Phase 2  验证        → 同上（运行时实测替代源码分析）
Phase 3  写 C++ 填缺口 → 同上，但无法修改引擎源码
Phase 4  生成能力文档 → 注明「商店版，部分隐藏状态未覆盖」
```

> 商店版限制：Phase 1 无法读取 `.cpp` 实现，可能错过 `Serialize()` 写入的非反射状态和 `PostLoad()` 注入的数据。建议对关键模块切换源码版引擎后重新执行。

## 耗时参考

| 模块 | 预计时间 | 是否需改源码 | 商店版可用 |
|------|---------|------------|----------|
| DataTable（推荐入门）| 0.5–1h | 否 | ✅ |
| GameplayTag | 0.5h | 否 | ✅ |
| GAS（GameplayAbility）| 2–4h | 偶尔 | ⚠️ 部分 |
| Sequencer | 3–4h | 偶尔 | ⚠️ 部分 |
| Blueprint 节点图 | 4–6h | 需要 | ❌ |
| 动画蓝图状态机 | 4–6h | 需要 | ❌ |

## 前置条件

- 已安装 `ue-py-skills`（见 `docs/ue-py-skills-setup.md`）
- UE Editor 已运行，Python Plugin 已启用
- 已运行 `/ue-init`（`ue-config.json` 含 `has_source` 字段）

## 产出物

每次运行后在 `.claude/ue-knowledge/` 下生成：
- `<module>-capability.md` — 能力文档（资产面+控制面完整 API 表）
- `<module>-extensions.cpp` — C++ UFUNCTION 扩展代码
- `<module>-verify.py` — 验证脚本

## 示例

```
/ue-extend DataTable        ← 推荐入门，商店版/源码版均可
/ue-extend GameplayAbility
/ue-extend BehaviorTree
/ue-extend Sequencer
```

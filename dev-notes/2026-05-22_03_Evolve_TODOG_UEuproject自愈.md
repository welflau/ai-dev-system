# Evolve — TODO G：UE uproject 自愈

> 日期：2026-05-22
> 提交：`4550be2`

---

## 背景

UE Playtest 因 `module X could not be loaded` 失败时，根本原因通常是 `.uproject` 的 `Plugins` 数组缺少对应插件声明。原来需要人工查错误日志、手动补写，本次实现自动检测+修复。

---

## 完整自愈流程

```
Playtest 返回 playtest_failed
    ↓
result.module_load_errors 非空？
    ├─ 否 → 走原有 fix_issues 路径
    └─ 是 → UEUprojectHealAction
              ↓
           提取缺失模块（正则匹配日志）
              ↓
           模块 → 插件名（静态映射表 + LLM 兜底）
              ↓
           读取 .uproject，检查 Plugins 列表
              ↓
           追加缺失插件，写回 .uproject
              ↓
           自愈成功 → ticket 状态回退 engine_compile
           重走：编译 → Playtest（无需 DevAgent 介入）
```

---

## 核心实现

### `_extract_missing_modules(log_text)`
```python
# 正则匹配三种错误格式：
# - "module 'X' could not be loaded"
# - "plugin 'X' has not been turned on"
# - "module 'X' not found"
```

### `_module_to_plugin(module)` 映射表（20+ 条）

| 模块 | 插件 |
|------|------|
| EnhancedInput | EnhancedInput |
| GameplayAbilities | GameplayAbilities |
| Niagara / NiagaraCore | Niagara |
| MassEntity / MassAI | MassEntity / MassAI |
| StateTreeModule | StateTree |
| CommonUI | CommonUI |
| Metasound | Metasound |
| ... | ... |

未知模块 → LLM 兜底推断，失败则假设插件名与模块名相同。

### `.uproject` patch 逻辑

- 已存在的插件不重复追加（大小写不敏感匹配）
- 保留原有 JSON 结构，只追加 `{"Name": "X", "Enabled": true}`
- 返回实际新增的插件名列表

---

## 单元测试结果

```
[extract] ['EnhancedInput', 'GameplayAbilities', 'Niagara']  ✅
[map] EnhancedInput / UnknownMod（同名回退）                   ✅
[patch added] ['EnhancedInput', 'Niagara']（Paper2D 已存在跳过）✅
ALL PASS
```

---

## 安全性

- 自愈失败 → 静默降级，走原有 `fix_issues` 路径
- 不影响非 module not loaded 类的 Playtest 失败
- `.uproject` 只追加，不删除，不修改已有插件配置

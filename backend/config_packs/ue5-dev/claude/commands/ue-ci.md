---
description: UE 项目 CI 流水线：静态检查 + 编译验证 + 资产验证
---

# /ue-ci

对 UE 项目执行三层 CI 检查，输出结构化报告。

## 用法

```
/ue-ci                          # 当前项目完整 CI（L1+L2+L3）
/ue-ci --skip-compile           # 跳过编译（只做静态检查，< 1s）
/ue-ci --level l1               # 只跑 L1 静态规则
/ue-ci --project D:/UEProjects/MyGame
```

## 执行前置

```python
config   = json.loads(open('.claude/ue-config.json', encoding='utf-8').read())
ue_build = config['ue_build_script']
unrealcc = config['unrealecc_root']
```

## 三层检查

### L1 静态规则（< 1s）

| 规则 | 检查内容 | 级别 |
|------|---------|------|
| `missing_generated_body` | UCLASS/USTRUCT 缺少 GENERATED_BODY() | error |
| `log_temp_usage` | 使用了 LogTemp | error |
| `stl_containers` | 使用了 STL 容器（vector/map/string）| error |
| `raw_new_uobject` | 对 UObject 使用 new | error |
| `missing_include_order_version` | Build.cs 缺少 IncludeOrderVersion | warning |

### L2 UBT 编译（3-5 min）

调用 `ue_build.js` 增量编译，输出：
- 编译是否成功
- error / warning 数量
- 前 3 条错误摘要

### L3 资产验证（< 30s）

- `.uproject` 格式合法性
- 必要插件是否启用（PythonScriptPlugin）
- Target.cs 文件完整性（Game + Editor）
- Config 基础文件存在性

## 退出码

| 退出码 | 含义 |
|--------|------|
| 0 | 全部通过 |
| 1 | 有 error（阻断部署）|
| 2 | 只有 warning（可继续）|
| 3 | 项目配置错误 |

## 示例输出

```
L1 静态检查  [OK]   error=0  warning=1
   [WARN] [missing_include_order_version] Build.cs: 建议添加 IncludeOrderVersion

L2 UBT 编译  [OK]   耗时=45.2s  error=0  warning=3

L3 资产验证  [OK]   error=0  warning=0

[OK] 全部通过
```

## 在 /ue-auto 中的位置

```
/ue-scaffold → 生成骨架 → /ue-ci（编译验证）→ 通过则继续 /ue-bp-gen
```

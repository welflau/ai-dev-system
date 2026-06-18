---
description: 运行 UE Automation Framework 测试并输出结构化报告
---

# /ue-playtest

运行 UE 项目的自动化测试（基于 UE Automation Framework），解析结果并输出报告。

## 用法

```
/ue-playtest                           # 运行所有项目测试
/ue-playtest --filter "MyGame."        # 只跑 MyGame 前缀的测试
/ue-playtest --filter "Functional."    # 只跑 Functional 测试
/ue-playtest --check-only              # 只解析上次结果，不重新运行
/ue-playtest --timeout 600             # 超时 10 分钟（复杂测试）
```

## 执行前置

```python
config   = json.loads(open('.claude/ue-config.json', encoding='utf-8').read())
ue_build = config['ue_build_script']
engine   = config['engine_path']
```

## 行为

1. 查找 `{engine_path}/Binaries/Win64/UnrealEditor-Cmd.exe`
2. 运行：`UnrealEditor-Cmd.exe MyGame.uproject -ExecCmds="Automation RunTests {filter}; Quit" -NullRHI`
3. 等待测试完成（默认 5 分钟超时）
4. 解析 `Saved/Automation/` 下的 JSON/XML 结果文件
5. 输出结构化报告

## 在 UE 项目中创建测试

```cpp
// 在任意 .cpp 文件中
#include "Misc/AutomationTest.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(
    FMyGamePlayerTest,              // 测试类名
    "MyGame.Player.BasicMovement",  // 测试路径（用于 --filter）
    EAutomationTestFlags::ApplicationContextMask |
    EAutomationTestFlags::ProductFilter
)

bool FMyGamePlayerTest::RunTest(const FString& Parameters)
{
    // 测试逻辑
    TestTrue("Player exists", GWorld != nullptr);
    return true;
}
```

## 测试结果文件

UE 自动化测试结果保存在：
```
{ProjectRoot}/Saved/Automation/
├── index.json           ← 测试列表
└── {TestName}/
    └── report.json      ← 详细结果（JSON 格式）
```

## 示例输出

```
=======================================================
  Playtest 报告
=======================================================
  [OK]  总计=12  通过=11  失败=1  跳过=0
  结果文件: Saved/Automation/report.json

  [FAIL] MyGame.Player.BasicMovement
       Expected: player velocity > 0 after input
=======================================================
```

## 与 /ue-ci 的关系

```
/ue-ci   → 编译层验证（静态规则 + UBT + 资产结构）
/ue-playtest → 运行时验证（游戏逻辑正确性）
```

在 `/ue-auto` 中的位置（可选阶段 5.5）：
```
阶段 5  验收截图（/ue-review）
    ↓
阶段 5.5  /ue-playtest --filter "{ProjectName}."  （若项目有测试）
```

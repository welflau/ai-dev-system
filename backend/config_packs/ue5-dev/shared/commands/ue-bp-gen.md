---
description: 根据功能描述生成 Blueprint 逻辑并写入 UE Editor
---

# /ue-bp-gen

根据自然语言描述，生成对应的 Blueprint 逻辑并写入运行中的 UE Editor。

## 用法

```
/ue-bp-gen <功能描述>
```

## P-Start 协议（执行前必查）

```python
config    = json.loads(open('.claude/ue-config.json', encoding='utf-8').read())
ue_python = config['ue_python_script']
```

读取 `.claude/ue-runtime/PSP.md`，用「创建 Blueprint / 修改蓝图 / unreal.Color」匹配，汇报：

```
[P-Start] 已查 PSP：命中 PSP-002/PSP-006/PSP-007（蓝图操作/Color 字节序/事务不回滚）
```

若文件不存在，提示用户先运行 `/ue-init`。

## 行为

1. 读取 `ue-blueprint-patterns` skill，确定实现方案
2. 委托 `ue-blueprint-coder` agent 生成 Python 脚本
3. 通过 `Bash(f"python {ue_python} ...")` 写入 UE Editor
4. 报告创建/修改的 Blueprint 路径，并说明节点结构

## 前置条件

- UE Editor 已运行，Python Editor Script Plugin 已启用
- Project Settings > Python > Enable Remote Execution Server 已勾选
- 已运行 `/ue-init` 完成初始化

## 能力边界

**当前可做（无需额外扩展）：**
- 新建 Blueprint 类，设置父类、默认属性
- 修改已有 Blueprint 的 CDO（类默认对象）属性
- 编译 Blueprint
- 添加组件并设置属性

**需要先 `/ue-extend Blueprint`：**
- 直接操作 Blueprint 节点图（增删节点、连线）
- 读取现有节点结构
- 操作 Animation Blueprint 状态机

## 示例

```
/ue-bp-gen 创建一个 BP_Pickup，当角色重叠时触发 OnPickedUp 事件并销毁自身

/ue-bp-gen 修改 BP_PlayerCharacter 的移动速度为 600，跳跃速度为 800

/ue-bp-gen 给 BP_Door 添加一个 IsLocked 布尔属性，默认为 false，
          并暴露为 BlueprintReadWrite

/ue-bp-gen 用 GAS 创建一个冲刺技能 GA_Dash：消耗 30 耐力，
          持续 0.5 秒，期间应用 GE_DashImmunity 无敌效果
```

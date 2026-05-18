---
description: 根据描述生成 Blueprint 并写入 UE Editor
args_hint: "<描述>"
requires_project: true
---

# /ue-bp-gen <描述>

用自然语言描述，AI 生成对应的 Blueprint 并写入运行中的 UE Editor。

```
/ue-bp-gen 创建一个波次生成器，每隔 5 秒在随机位置生成一个敌人
/ue-bp-gen 修改 BP_PlayerCharacter 的移动速度为 600
/ue-bp-gen 创建一个 BP_Pickup，碰到玩家时触发 OnPickedUp 事件并销毁自身
```

**前置条件**：UE Editor 已运行，UE Python 桥接已配置。

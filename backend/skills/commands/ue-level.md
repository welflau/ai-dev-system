---
description: 根据关卡设计描述生成并布置 UE 关卡（地面/灯光/NavMesh/出生点等）
args_hint: "<描述>"
requires_project: true
---

# /ue-level <描述>

根据自然语言描述，AI 生成关卡布局 Python 脚本并写入运行中的 UE Editor。

```
/ue-level 8×8 地面，四角各一盏灯，中央玩家出生点，NavMesh 全覆蓋
/ue-level 室内竞技场 20m×20m，四角有掩体，中央开阔，顶部天窗采光
/ue-level 森林小径连接三个区域：入口、广场、神庙，路边有道具点
```

**前置条件**：UE Editor 已打开目标关卡，Remote Execution Server 已启用。

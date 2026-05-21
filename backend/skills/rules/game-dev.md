---
alwaysApply: false
traits_match:
  any_of: [game, game-ue, godot, unity]
priority: medium
description: 游戏开发通用规范（性能意识 / 网络 / 数值配置 / 防作弊）
---

# 游戏开发通用规范

## 一、性能意识

- **Tick/Update 函数**：不做高开销操作（射线检测、全局查询、字符串格式化）
- 对象池（Object Pool）优先于频繁创建/销毁
- LOD（Level of Detail）：远处对象降低更新频率或切换简化版本
- 避免每帧 GC 压力：预分配缓冲区，减少临时对象

## 二、数值与配置

- 游戏数值**禁止硬编码**，通过 DataTable / DataAsset / ScriptableObject 配置
- 平衡性参数从配置读取，支持热更新
- 数值命名语义化：`base_damage`、`max_health`，而非 `d1`、`hp`

## 三、网络与同步

- 服务端权威（Server-Authoritative）原则：伤害判定、物品获取在服务端确认
- 客户端预测 + 服务端校正（Prediction & Reconciliation）
- 不可信任客户端数据：坐标合理性检查，防止传送作弊
- 减少带宽：只同步玩家关心的数据，用 LOD 分层同步频率

## 四、防作弊基线

- 不在客户端做敏感计算（暴击判定、随机奖励）
- 服务端验证所有资源消耗（弹药、技能冷却、货币）
- 关键操作记录服务端日志，便于事后审计

## 五、状态机

- 复杂游戏对象（角色、AI、关卡）用状态机管理，避免多层 if/else
- 状态转换显式声明（触发条件、目标状态），禁止隐式全局 flag
- 状态机事件接口幂等（重复触发同一事件结果一致）

## 六、随机数

- 需要重现（replay、seed 系统）的场景，用可播种的随机数生成器
- 不用 `Math.random()` / `rand()` 做可复现逻辑
- 表现层（特效、音效变体）可用系统随机，逻辑层必须用种子随机

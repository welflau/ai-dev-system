---
description: 根据关卡设计描述生成并布置 UE 关卡
---

# /ue-level

根据关卡设计描述（文字说明或文档路径），生成关卡布局 Python 脚本并写入 UE Editor。

## 用法

```
/ue-level <设计描述>
/ue-level --file <设计文档路径>
```

## 执行前置

读取 `.claude/ue-config.json` 获取脚本路径：

```python
config = json.loads(open('.claude/ue-config.json').read())
ue_python = config['ue_python_script']
```

## 行为

1. 委托 `ue-level-designer` agent 解析设计意图
2. 查询内容浏览器可用资产
3. 生成布局 Python 脚本（Actor 放置 + 光源 + NavMesh）
4. 通过 `Bash(f"python {ue_python} ...")` 写入 UE Editor
5. 汇报 Actor 数量、关键坐标，建议后续步骤

## 前置条件

- UE Editor 已打开目标关卡（空白关卡或已有关卡）
- 已运行 `/ue-init`
- 内容浏览器中有可用的 Static Mesh 资产（无资产时使用 StarterContent）

## 生成的内容

| 元素 | 说明 |
|------|------|
| PlayerStart | 玩家出生点，放置在开阔区域 |
| Static Mesh Actor | 地面、墙体、障碍物等几何体 |
| PointLight / DirectionalLight | 基础光照 |
| NavMeshBoundsVolume | 导航网格覆盖区域 |
| 触发器（可选）| 区域进入/离开事件 |

## 示例

```
/ue-level 室内竞技场，20m×20m，四角有掩体，中央开阔，顶部天窗采光

/ue-level 森林探索关卡，蜿蜒小路连接三个区域：
          村庄入口、古树广场、废弃神庙，
          路边有随机道具点

/ue-level --file D:/Docs/Level_Design_v2.txt
```

## 迭代调整

生成后可以继续用自然语言调整：

```
把中央光源的颜色改暖一点
在坐标 (500, 500, 0) 再加一个掩体
把玩家出生点往北移 200cm
```

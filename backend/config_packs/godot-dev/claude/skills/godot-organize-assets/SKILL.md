---
name: godot-organize-assets
version: 3.0.0
displayName: 整理资源文件
description: >
  当 Godot 项目的资源（精灵图、音频、字体、材质）组织混乱时使用。
  检测分散的资源文件并将其整理为清晰的分类，使用一致的命名。
  在有益时创建精灵图集，按类型整理音频，并将相关资源分组。
author: Asreonn
license: MIT
category: game-development
type: tool
difficulty: beginner
audience: [developers]
keywords:
  - godot
  - asset-organization
  - sprites
  - audio
  - sprite-atlases
  - file-structure
  - performance
  - assets
platforms: [macos, linux, windows]
repository: https://github.com/asreonn/godot-superpowers
homepage: https://github.com/asreonn/godot-superpowers#readme

permissions:
  filesystem:
    read: [".png", ".jpg", ".wav", ".ogg", ".ttf", ".glb", ".tres"]
    write: ["*"]
    move: true
    delete: false
  git: true

behavior:
  auto_rollback: true
  validation: true
  git_commits: true

outputs: "整理后的资源目录、移动的文件、精灵图集、命名一致性、git 提交"
requirements: "Git 仓库、Godot 4.x"
execution: "全自动，保留引用"
integration: "godot-organize-project 编排器的一部分，与 godot-organize-files 协同工作"
---

# 整理资源文件

## 核心原则

**资源按类型和用途整理。** 容易查找，容易维护，容易优化。

## 本技能的功能

查找类似这样的资源目录：
```
assets/
├── player_sprite.png
├── enemy1.png
├── enemy2.png
├── jump.wav
├── background_music.ogg
├── font.ttf
├── tile1.png
├── tile2.png
└── ...（100 多个混杂的资源）
```

转换为：
```
assets/
├── sprites/
│   ├── characters/
│   │   └── player_sprite.png
│   ├── enemies/
│   │   ├── enemy1.png
│   │   └── enemy2.png
│   └── environment/
│       ├── tiles/
│       │   ├── tile1.png
│       │   └── tile2.png
│       └── atlases/
│           └── environment_atlas.png  # 合并的瓦片
├── audio/
│   ├── music/
│   │   └── background_music.ogg
│   └── sfx/
│       └── jump.wav
└── fonts/
    └── font.ttf
```

## 检测模式

识别：
- 资源在错误的分类中
- 没有子目录组织
- 命名约定不一致
- 潜在的精灵图集机会
- 未使用/重复的资源

## 何时使用

### 构建资源密集型游戏
包含大量精灵图、音效或视觉资源的游戏。

### 优化性能
创建精灵图集可减少绘制调用。

### 管理大型资源库
查找特定资源变得困难。

### 准备资源管线
清晰的结构支持自动化处理。

## 流程

1. **扫描** - 按类型清点所有资源文件
2. **分析** - 确定逻辑分组
3. **分组** - 识别相关资源（动画帧、瓦片集）
4. **优化** - 在有益时创建精灵图集
5. **移动** - 将资源迁移到整理后的结构
6. **更新** - 修复场景和脚本中的所有引用
7. **验证** - 确保资源正确加载
8. **提交** - 每个资源类别一个 git 提交

## 整理策略

### 按资源类型
主要整理：精灵图、音频、字体、材质。

### 按领域
次要整理：角色、敌人、环境、UI。

### 按用途
第三级整理：动画、图标、背景、特效。

## 精灵图整理

```
sprites/
├── characters/
│   ├── player/
│   │   ├── idle/
│   │   │   ├── idle_01.png
│   │   │   ├── idle_02.png
│   │   │   └── idle_03.png
│   │   ├── run/
│   │   └── jump/
│   └── npc/
├── enemies/
│   ├── goblin/
│   ├── orc/
│   └── dragon/
├── items/
│   ├── weapons/
│   ├── consumables/
│   └── collectibles/
├── environment/
│   ├── tiles/
│   ├── props/
│   └── backgrounds/
└── ui/
    ├── icons/
    ├── buttons/
    └── panels/
```

## 音频整理

```
audio/
├── music/
│   ├── main_theme.ogg
│   ├── battle_music.ogg
│   └── ambient/
│       ├── forest.ogg
│       └── cave.ogg
├── sfx/
│   ├── player/
│   │   ├── jump.wav
│   │   ├── land.wav
│   │   └── attack.wav
│   ├── enemies/
│   │   ├── hit.wav
│   │   └── death.wav
│   ├── ui/
│   │   ├── click.wav
│   │   └── hover.wav
│   └── environment/
│       ├── door_open.wav
│       └── chest_open.wav
└── voice/  # 适用于有语音的游戏
```

## 精灵图集创建

**检测图集机会：**
- 多个一起使用的小精灵图（UI 图标）
- 动画帧（8+ 帧的序列）
- 瓦片集碎片（可以合并）
- 同时加载的相关精灵图

**在以下情况创建图集：**
- 4+ 个 128x128 像素以下的精灵图
- 相关精灵图（相同领域）
- 有性能收益（减少绘制调用）

**示例：**
```
# 之前：20 个独立的 UI 图标文件（20 次绘制调用）
ui/icons/health_icon.png
ui/icons/mana_icon.png
...（18 个更多）

# 之后：1 个图集纹理（1 次绘制调用）
ui/atlases/ui_icons_atlas.png
ui/atlases/ui_icons_atlas.png.import  # 定义图集区域
```

## 命名约定

### 精灵图
- `character_player_idle_01.png`
- `enemy_goblin_attack_03.png`
- `item_sword_iron.png`

### 音频
- `music_main_theme.ogg`
- `sfx_player_jump.wav`
- `ambient_forest_birds.ogg`

### 材质
- `mat_character_player.tres`
- `mat_environment_grass.tres`

一致的命名可以：
- 按字母排序将相关资源分组
- 轻松搜索和过滤
- 支持自动化处理脚本

## 创建的内容

- 按类型整理的资源目录
- 按领域/用途划分的子目录
- 有益时创建的精灵图集
- 重命名的文件以保持一致性（可选）
- 所有场景/脚本中更新的引用
- 每个资源类别的 git 提交

## 智能分析

**检测使用模式：**
- 经常一起使用 → 分组在一起
- 动画序列 → 按帧整理
- UI 元素 → 图集候选
- 未使用的资源 → 标记供审查

**基于以下因素优化：**
- 文件大小（小精灵图 → 图集）
- 加载频率（常用 → 优化）
- 关联性（动画帧 → 文件夹）

## 集成

协同工作：
- **godot-organize-files** - 先进行基础整理
- **godot-organize-scripts** - 并行的脚本整理
- **godot-organize-project**（编排器）- 完整项目整理

## 安全性

- 移动过程中保留所有资源引用
- Godot .import 文件正确重新生成
- 精灵图集创建会验证区域
- 验证失败时回滚
- 原始结构保存在 git 历史中

## 何时不使用

不要在以下情况重新整理：
- 资源已经组织良好
- 使用了外部资源管理工具
- 开发中期（大规模变更的时机不佳）
- 管线要求自定义组织方式

## 收益

- **性能** - 精灵图集减少绘制调用
- **组织性** - 快速找到资源
- **工作流** - 将新资源导入正确位置
- **可扩展性** - 结构支持更多资源
- **协作** - 团队知道资源应放在哪里

## 图集性能

**没有图集：**
- 20 个 UI 图标 = 20 个独立纹理 = 20 次绘制调用
- 30 个敌人精灵图 = 30 个纹理 = 30 次绘制调用

**有图集：**
- 20 个 UI 图标 = 1 个图集纹理 = 1 次绘制调用
- 30 个敌人精灵图 = 2-3 个图集 = 2-3 次绘制调用

性能提升显著，尤其在移动端。

## 常见转换

| 之前 | 之后 |
|--------|-------|
| 根目录中的 `player.png` | `assets/sprites/characters/player/idle.png` |
| 混杂的 `sound.wav` | `assets/audio/sfx/player/jump.wav` |
| 20 个分散的图标 | `assets/sprites/ui/atlases/ui_atlas.png` |
| assets 中的 `font.ttf` | `assets/fonts/main_font.ttf` |

## 配置选项

- 启用/禁用精灵图集创建
- 最小图集精灵数量（默认：4）
- 最大图集尺寸（默认：4096x4096）
- 命名约定风格
- 整理深度（扁平 vs 深层级）

默认值遵循 Godot 最佳实践和性能指南。

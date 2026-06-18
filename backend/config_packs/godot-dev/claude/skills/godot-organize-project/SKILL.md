---
name: godot-organize-project
version: 3.0.0
displayName: "Godot 项目组织编排器"
description: >
  当需要重新组织项目文件夹结构、合并相似文件、按类型组织资源、以及从当前混乱的
  文件夹中创建整洁的项目架构时使用。编排所有 3 个组织子技能：organize-files、
  organize-assets 和 organize-scripts。每个操作独立运行，并保留引用完整性。
author: "Asreonn"
license: MIT
category: game-development
type: agent
difficulty: beginner
audience: [developers, teams]
keywords:
  - godot
  - organization
  - project-structure
  - folder-structure
  - assets
  - scripts
  - scenes
  - godot4
platforms: [macos, linux, windows]
repository: https://github.com/asreonn/godot-superpowers
homepage: https://github.com/asreonn/godot-superpowers#readme
filesystem:
  read:
    - "${PROJECT_ROOT}/**/*"
    - "${PROJECT_ROOT}/project.godot"
  write:
    - "${PROJECT_ROOT}/**/*"
  deny:
    - "**/.env*"
    - "**/secrets*"
    - "**/*.key"
    - "**/.git/**"
behavior:
  timeout: 300
  retry: 2
  cache: false
  interactive: true
use_cases:
  - "项目文件散落各处，没有结构"
  - "资源和脚本混杂在根目录中"
  - "由于没有组织系统，找不到文件"
  - "希望为团队协作做好项目准备"
  - "需要跨项目的一致结构"
  - "希望一次性组织所有内容"
outputs: "有序的目录结构、移动后引用完整的文件、按类别的 git 提交"
requirements: "Git 仓库、Godot 4.x"
execution: "完全自动，保留引用完整性"
auto_rollback: "是 - 验证失败时自动回滚"
integration: "编排：godot-organize-files、godot-organize-assets、godot-organize-scripts"
---

# Godot 项目组织编排器

**此编排器按顺序运行 3 个组织子技能。如需单独操作，请直接调用子技能。**

**目的**：扫描并智能重组 Godot 项目文件夹结构，以获得最佳组织和可维护性。

**核心原则**：自动化、非破坏性的项目重组，完整保留 git 历史。

---

## 调用时 - 从这里开始

当此技能被调用时，立即执行以下步骤：

### 1. 验证 Godot 项目（5 秒）

```bash
ls project.godot 2>/dev/null && echo "✓ Godot project detected" || echo "✗ Not a Godot project"
```

**如果不是 Godot 项目：**
- 告知用户此技能仅适用于 Godot 项目
- 在此停止

**如果是 Godot 项目：**
- 继续执行步骤 2

### 2. 扫描项目结构（自动）

并行执行：

```bash
# Directory tree
find . -type d -name "." -prune -o -type d -print | head -50

# File count by type
find . -type f \( -name "*.gd" -o -name "*.tscn" -o -name "*.tres" -o -name "*.png" -o -name "*.ogg" \) | wc -l

# Identify problem areas
find . -type f -name "*.gd" | wc -l  # Total scripts
find . -type f -name "*.tscn" | wc -l  # Total scenes
find . -type f -name "*.tres" | wc -l  # Total resources
find . -type d | wc -l  # Total directories

# Find orphaned files (files in root or misplaced)
find . -maxdepth 1 -type f \( -name "*.gd" -o -name "*.tscn" -o -name "*.tres" \)

# Detect unorganized directories
find . -type d -exec sh -c 'count=$(find "$1" -maxdepth 1 -type f | wc -l); [ $count -gt 10 ] && echo "$1 ($count files)"' _ {} \;
```

### 3. 分析当前结构

检测模式：
- 所有脚本在根目录？ → 建议创建 scripts/ 目录
- 所有场景与脚本混在一起？ → 建议创建 scenes/ 子目录
- 所有资源在顶层？ → 建议创建 resources/ 或 assets/ 组织
- 纹理、音频、字体散落各处？ → 建议在 assets/ 下按类型创建子目录
- 完全没有组织？ → 建议全面重组

### 4. 展示结果

向用户展示：

```
=== 项目结构分析 ===

项目：[项目名称]
当前状态：无组织

统计信息：
- 总目录数：X
- 总脚本数 (.gd)：Y
- 总场景数 (.tscn)：Z
- 总资源数 (.tres)：W
- 孤立文件（根目录级别）：N

检测到的问题：
- [ ] 脚本散落在整个项目中
- [ ] 场景与脚本混杂
- [ ] 资源在顶层
- [ ] 资产文件未组织
- [ ] 没有清晰的层级结构

重组将：
✓ 创建逻辑目录结构
✓ 按类型和类别分组文件
✓ 创建 components/ 子目录结构
✓ 组织资产（精灵、音频、字体等）
✓ 改善 IDE 导航
✓ 加快编译速度
✓ 使协作更容易

建议的结构：
res://
├─ scenes/
│  ├─ ui/
│  ├─ levels/
│  └─ entities/
├─ scripts/
│  ├─ ui/
│  ├─ gameplay/
│  ├─ utils/
│  └─ managers/
├─ assets/
│  ├─ sprites/
│  ├─ audio/
│  │  ├─ music/
│  │  └─ sfx/
│  ├─ fonts/
│  └─ shaders/
├─ resources/
│  ├─ configs/
│  ├─ data/
│  └─ materials/
└─ components/
   ├─ timers/
   ├─ areas/
   ├─ sprites/
   ├─ ui/
   └─ physics/

您希望我：
1. 重组项目（推荐）
2. 先显示详细分析
3. 在继续之前自定义结构
4. 取消
```

### 5. 等待用户选择

- **如果选 1（继续）：** 开始自动重组
- **如果选 2（详情）：** 显示逐文件的分析，然后提供继续选项
- **如果选 3（自定义）：** 询问结构偏好
- **如果选 4（取消）：** 退出技能

---

## 阶段 1：分析与规划

### 1.1 检测当前结构类型

```bash
# Analyze what kind of project this is

# Check for existing structure patterns
test -d "scripts" && echo "scripts/ exists"
test -d "scenes" && echo "scenes/ exists"
test -d "assets" && echo "assets/ exists"
test -d "components" && echo "components/ exists"

# Check if already organized
find . -maxdepth 1 -type f \( -name "*.gd" -o -name "*.tscn" \) | wc -l
# If 0: Already organized
# If >5: Needs organization
```

### 1.2 映射所有文件

创建全面的文件清单：

```bash
# Create inventory of all files with their types
find . -type f \( -name "*.gd" -o -name "*.tscn" -o -name "*.tres" -o -name "*.png" -o -name "*.ogg" -o -name "*.mp3" \) > file_inventory.txt

# Analyze each file:
# - Current location
# - Type (script, scene, resource, asset)
# - Category (ui, gameplay, editor, utils, etc.)
# - Related files (dependencies)
```

### 1.3 创建重组计划

生成分步计划：

```
重组计划：
====================

1. 创建目录 (20 个操作)
2. 移动脚本 (Y 个操作)
3. 移动场景 (Z 个操作)
4. 移动资源 (W 个操作)
5. 移动资产 (A 个操作)
6. 更新导入设置
7. 验证所有引用
8. 提交更改

总操作数：X
预计时间：自动（用户无需等待）
可回滚：是（完整 git 历史）
```

---

## 阶段 2：创建目录结构

### 2.1 创建主要类别

```bash
mkdir -p res://scripts
mkdir -p res://scenes
mkdir -p res://assets
mkdir -p res://resources
mkdir -p res://components
```

### 2.2 根据分析创建子类别

**基于检测到的使用模式：**

#### 脚本组织

```
res://scripts/
├─ ui/                    # UI 相关脚本
├─ gameplay/              # 游戏逻辑脚本
├─ entities/              # 实体脚本（玩家、敌人等）
├─ managers/              # 单例管理器
├─ utils/                 # 工具/辅助脚本
├─ editor/                # 编辑器脚本（如有）
└─ _autoload/             # Autoload 脚本
```

#### 场景组织

```
res://scenes/
├─ ui/                    # UI 界面、菜单、HUD
│  ├─ menus/
│  ├─ hud/
│  └─ dialogs/
├─ levels/                # 关卡/地图场景
├─ entities/              # 可复用的实体场景
│  ├─ player/
│  ├─ enemies/
│  ├─ npcs/
│  └─ props/
└─ _debug/                # 调试/测试场景
```

#### 资产组织

```
res://assets/
├─ sprites/               # 2D 图形
│  ├─ player/
│  ├─ enemies/
│  ├─ ui/
│  ├─ tiles/
│  └─ vfx/
├─ audio/                 # 音频文件
│  ├─ music/
│  ├─ sfx/
│  └─ voice/
├─ fonts/                 # 字体文件
├─ shaders/               # 着色器文件
└─ 3d/                    # 3D 模型（如有）
```

#### 资源组织

```
res://resources/
├─ configs/               # 配置资源
├─ data/                  # 游戏数据资源
│  ├─ enemies/
│  ├─ items/
│  └─ dialogue/
├─ materials/             # 材质资源
├─ tilesets/              # TileSet 资源
└─ theme/                 # UI 主题资源
```

#### 组件组织

```
res://components/
├─ timers/                # 计时器组件（来自 godot-refactoring）
├─ areas/                 # 检测区域组件
├─ sprites/               # 视觉组件模板
├─ physics/               # 物理体模板
├─ ui/                    # UI 组件模板
└─ audio/                 # 音频组件
```

### 2.3 创建目录结构

```bash
# Create all directories based on analysis
mkdir -p res://scripts/{ui,gameplay,entities,managers,utils,editor,_autoload}
mkdir -p res://scenes/{ui/{menus,hud,dialogs},levels,entities/{player,enemies,npcs,props},_debug}
mkdir -p res://assets/{sprites/{player,enemies,ui,tiles,vfx},audio/{music,sfx,voice},fonts,shaders,3d}
mkdir -p res://resources/{configs,data/{enemies,items,dialogue},materials,tilesets,theme}
mkdir -p res://components/{timers,areas,sprites,physics,ui,audio}

# Create .gitkeep files in empty directories
find res:// -type d -empty -exec touch {}/.gitkeep \;
```

---

## 阶段 3：文件迁移

### 3.1 分类现有文件

```bash
# Analyze each file and determine category

# Scripts
for file in $(find . -maxdepth 1 -name "*.gd"); do
    # Read file content
    # Detect if it's ui, gameplay, manager, util, etc.
    # Assign to appropriate category
done

# Scenes
for file in $(find . -maxdepth 1 -name "*.tscn"); do
    # Analyze scene name and content
    # Assign to ui/levels/entities
done

# Resources
for file in $(find . -maxdepth 1 -name "*.tres"); do
    # Check resource type
    # Assign to configs/data/materials/etc
done

# Assets
for file in $(find . -maxdepth 1 -name "*.png"); do
    # Check dimensions and usage
    # Assign to sprites/ui/tiles/vfx
done
```

### 3.2 智能移动文件

```bash
# Move scripts
mv player.gd res://scripts/entities/
mv ui_manager.gd res://scripts/managers/
mv utils.gd res://scripts/utils/
mv enemy.gd res://scripts/entities/

# Move scenes
mv menu.tscn res://scenes/ui/menus/
mv level_1.tscn res://scenes/levels/
mv player.tscn res://scenes/entities/player/
mv enemy.tscn res://scenes/entities/enemies/

# Move resources
mv game_config.tres res://resources/configs/
mv enemy_data.tres res://resources/data/enemies/
mv player_material.tres res://resources/materials/

# Move assets
mv player_sprite.png res://assets/sprites/player/
mv bg_music.ogg res://assets/audio/music/
mv explosion.png res://assets/sprites/vfx/
```

### 3.3 更新引用

```bash
# Scan all .gd and .tscn files for hardcoded paths
grep -rn "res://" --include="*.gd" --include="*.tscn" . > path_references.txt

# Update path references in scripts
# Old: load("res://player.gd")
# New: load("res://scripts/entities/player.gd")

# Update path references in scenes
# Old: [ext_resource type="Script" path="res://ui_manager.gd"]
# New: [ext_resource type="Script" path="res://scripts/managers/ui_manager.gd"]
```

---

## 阶段 4：特殊处理

### 4.1 Autoload 脚本

检测并移动到 _autoload/：

```bash
# In project.godot:
# [autoload]
# EventBus="res://event_bus.gd"

# Move to:
# [autoload]
# EventBus="res://scripts/_autoload/event_bus.gd"

# Update project.godot references
```

### 4.2 插件脚本（如有）

保留在 addons/ 目录中：

```bash
mkdir -p res://addons/
# Don't reorganize addons directory
```

### 4.3 生成的文件（如有）

```bash
# Don't reorganize:
# - .gd files in .godot/
# - Imported files
# - Cache files
```

---

## 阶段 5：与 godot-refactoring 的集成

如果检测到组件库（来自 godot-refactoring 技能）：

```bash
# Move existing components/ to new location
# components/ → res://components/

# Update parent .tscn files with new paths:
# Old: [ext_resource type="PackedScene" path="res://components/timers/..."]
# New: [ext_resource type="PackedScene" path="res://components/timers/..."]

# Ensure component library structure is respected
```

---

## 阶段 6：验证与校验

### 6.1 检查文件计数

```bash
# Before reorganization
find . -maxdepth 1 -type f | wc -l

# After reorganization
find . -type f | wc -l

# Should be equal
```

### 6.2 检查所有引用

```bash
# Run Godot in headless mode to detect reference errors
godot --headless --quit-after 5 project.godot 2>&1 | grep -i "error\|not found"

# Should report 0 errors
```

### 6.3 验证场景完整性

```bash
# Check that all scene files are still valid
for scene in $(find . -name "*.tscn"); do
    godot --editor -e "$scene" 2>&1 | grep -q "ERROR" && echo "ERROR in $scene"
done

# Should report 0 errors
```

### 6.4 验证脚本完整性

```bash
# Check that all scripts compile
for script in $(find . -name "*.gd"); do
    gdscript -c "$script" 2>&1 | grep -q "Error" && echo "ERROR in $script"
done

# Should report 0 errors
```

---

## 阶段 7：Git 与最终确认

### 7.1 创建备份提交

```bash
git add .
git commit -m "Backup: Pre-reorganization state

All files present before structure reorganization."
```

### 7.2 移动所有文件

（执行阶段 3 中的移动操作）

### 7.3 更新引用

（执行阶段 3.3 中的引用更新）

### 7.4 最终验证

```bash
# Run Godot validation
godot --headless --quit-after 5 project.godot

# Check for errors
# Should see: "All scenes and scripts loaded successfully"
```

### 7.5 创建最终提交

```bash
git add .
git commit -m "Refactor: Reorganize project structure for better organization

Project structure reorganization:
- Created logical directory hierarchy
- Organized scripts by category (ui, gameplay, entities, managers, utils)
- Organized scenes (ui, levels, entities)
- Organized assets (sprites, audio, fonts, shaders)
- Organized resources (configs, data, materials)
- Organized components (from godot-refactoring integration)
- Updated all internal path references
- Verified all scenes and scripts load without errors

Benefits:
- Improved IDE navigation and file organization
- Faster compilation and project loading
- Easier collaboration and code discovery
- Clear separation of concerns
- Integrated with godot-refactoring skill

Behavior: UNCHANGED
Visual: UNCHANGED
Performance: UNCHANGED (or improved)
"
```

### 7.6 标记完成

```bash
git tag reorganize-complete-$(date +%Y%m%d-%H%M%S)
```

---

## 结果指标

重组成功后：

```
=== 项目重组完成 ===

重组前：
- 结构：扁平/混乱
- 导航：困难
- 文件查找：缓慢

重组后：
- 结构：层级化 & 逻辑清晰
- 导航：快速 & 直观
- 文件查找：即时
- 构建时间：可能更快
- 协作：更容易

已组织的文件：
- 脚本：X → scripts/
- 场景：Y → scenes/
- 资源：Z → resources/
- 资产：W → assets/
- 组件：V → components/（如检测到 godot-refactoring）

总迁移数：X + Y + Z + W + V
错误：0
警告：0

状态：✓ 成功

后续步骤：
1. 在 Godot 编辑器中重新打开项目
2. 验证文件夹结构是否匹配
3. 检查所有资产是否正确加载
4. 在整洁的结构上继续开发
```

---

## 与 godot-refactoring 的集成

此技能与 godot-refactoring 技能**完美配合**：

1. **先运行 godot-refactoring** → 将代码创建的节点提取为模块化组件
   - 创建 `res://components/` 目录结构
   - 生成组件基础场景和预设

2. **运行 project-structure-organizer** → 识别组件结构
   - 保留组件组织
   - 创建支持目录
   - 围绕组件库组织项目其余部分
   - 更新所有引用

3. **结果** → 整洁、模块化、有组织的项目

---

## 回滚

如果重组导致问题：

```bash
# View commits
git log --oneline | head -5

# Find pre-reorganization commit
git log --oneline | grep "Pre-reorganization"

# Reset to before
git reset --hard <commit_hash>

# Project restored to previous state
```

---

## 使用场景

### 场景 1：新项目 - 从一开始就组织

用户创建新 Godot 项目，添加了一些文件后调用：
- 技能立即创建合适的结构
- 用户在整洁的结构上继续开发

### 场景 2：现有项目 - 清理

用户有一个 1 年的项目，200 个文件散落各处：
- 技能扫描并自动重组
- 所有引用已更新
- 项目现在可维护了

### 场景 3：godot-refactoring 之后 - 全面清理

用户运行 godot-refactoring 技能，创建了组件库：
- 组件已组织在 `res://components/` 中
- 然后运行此技能组织项目其余部分
- 结果：完全有组织的模块化项目

---

## 最佳实践

1. **在 godot-refactoring 之后运行** → 完整的项目清理流水线
2. **之前创建 git 提交** → 始终有回滚选项
3. **之后在编辑器中验证** → 打开 Godot 检查文件树
4. **在主分支上运行** → 不要在功能分支上执行
5. **记录结构** → 在 res:// 中添加 README 目录指南

---

**此技能提供完整的项目结构组织，零数据丢失且具有完整的回滚能力。**

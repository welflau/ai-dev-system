---
name: godot-create-plugin
version: 3.0.0
displayName: 创建 Godot 编辑器插件
description: >
  用于创建带有自定义面板、停靠栏和工具的 Godot 编辑器插件。生成 plugin.cfg 配置、
  EditorPlugin 脚本模板、自定义编辑器 UI 组件，并集成 ProjectSettings。按照
  Godot 4.x 最佳实践创建完整的插件结构。
author: Asreonn
license: MIT
category: game-development
type: tool
difficulty: intermediate
audience: [developers]
keywords:
  - godot
  - editor-plugin
  - plugin.cfg
  - EditorPlugin
  - custom-dock
  - editor-panel
  - tool-script
  - gdscript
  - project-settings
  - editor-extension
platforms: [macos, linux, windows]
repository: https://github.com/asreonn/godot-superpowers
homepage: https://github.com/asreonn/godot-superpowers#readme

permissions:
  filesystem:
    read: [".gd", ".tscn", "project.godot"]
    write: [".cfg", ".gd", ".tscn", "project.godot"]
  git: true

behavior:
  auto_rollback: true
  validation: true
  git_commits: true

outputs: "完整的插件结构，包含 plugin.cfg、EditorPlugin 脚本、自定义停靠栏/面板以及设置集成"
requirements: "Godot 4.x 项目, Git 仓库"
execution: "使用模板生成插件文件并进行 git 提交"
integration: "可与 godot-refactor 编排器配合使用，创建可复用的编辑器工具"
---

# 创建 Godot 编辑器插件

## 核心原则

**扩展编辑器，而不是对抗它。** Godot 编辑器插件让你可以直接在编辑器界面中添加自定义工具、面板和工作流。

## 本技能的功能

创建完整的 Godot 编辑器插件：
- **plugin.cfg** - 插件元数据和配置
- **EditorPlugin 脚本** - 带有生命周期钩子的入口点
- **自定义停靠栏** - 带有自定义 UI 的侧边面板
- **底部面板** - 底部停靠标签页，类似动画/Shader 编辑器
- **@tool 脚本** - 在编辑器中运行的脚本
- **设置集成** - 用于插件配置的 ProjectSettings

## 创建的插件结构

```
addons/my_plugin/
├── plugin.cfg              # Plugin metadata
├── my_plugin.gd            # EditorPlugin entry point
├── docks/
│   ├── main_dock.gd        # Custom side dock logic
│   ├── main_dock.tscn      # Dock UI scene
│   └── bottom_panel.gd     # Bottom panel logic
├── ui/
│   ├── inspector_plugin.gd # Custom inspector controls
│   └── property_editor.gd  # Custom property editors
└── tools/
    ├── scene_tool.gd       # @tool script for editor functionality
    └── asset_processor.gd  # Import/Process automation
```

## 使用场景

### 需要自定义编辑器工具
创建关卡编辑器、地形工具或集成到 Godot 中的专用工作流。

### 需要检查器扩展
为自定义 Resource 或 Node 添加自定义属性编辑器。

### 构建资源管线
自动化导入工作流、批量处理或自定义导出器。

### 需要项目级工具
跨场景操作、管理资源或提供项目洞察的工具。

## 流程

1. **生成 plugin.cfg** - 创建包含名称、描述、版本的元数据文件
2. **创建 EditorPlugin 脚本** - 实现 `_enter_tree()` 和 `_exit_tree()`
3. **构建自定义 UI** - 将停靠栏和面板设计为场景
4. **添加 @tool 脚本** - 创建用于编辑器功能的 @tool 脚本
5. **集成设置** - 添加 ProjectSettings 条目用于配置
6. **提交** - 使用完整插件结构进行 git 提交

## 示例：简单停靠栏插件

**生成文件：addons/my_dock/plugin.cfg**
```ini
[plugin]
name="My Custom Dock"
description="Adds a custom dock panel to the editor"
author="Your Name"
version="1.0.0"
script="my_dock.gd"
```

**生成文件：addons/my_dock/my_dock.gd**
```gdscript
@tool
extends EditorPlugin

const DOCK_SCENE = preload("res://addons/my_dock/dock.tscn")
var dock_instance: Control

func _enter_tree():
    # Add custom dock to left slot
    dock_instance = DOCK_SCENE.instantiate()
    add_control_to_dock(DOCK_SLOT_LEFT_BR, dock_instance)

    # Add custom settings
    _setup_project_settings()

func _exit_tree():
    # Remove dock when plugin is disabled
    if dock_instance:
        remove_control_from_docks(dock_instance)
        dock_instance.queue_free()

func _setup_project_settings():
    # Add custom project settings for plugin configuration
    if not ProjectSettings.has_setting("my_plugin/enabled_features"):
        ProjectSettings.set_setting("my_plugin/enabled_features", ["feature_a", "feature_b"])
        ProjectSettings.add_property_info({
            "name": "my_plugin/enabled_features",
            "type": TYPE_ARRAY,
            "hint": PROPERTY_HINT_TYPE_STRING,
            "hint_string": "24/17:Feature"
        })
```

**生成文件：addons/my_dock/dock.gd**
```gdscript
@tool
extends Control

@onready var button: Button = $VBoxContainer/Button
@onready var label: Label = $VBoxContainer/Label

func _ready():
    button.pressed.connect(_on_button_pressed)

func _on_button_pressed():
    label.text = "Button clicked at %s" % Time.get_time_string_from_system()

    # Access plugin settings
    var features = ProjectSettings.get_setting("my_plugin/enabled_features", [])
    print("Enabled features: ", features)
```

**生成文件：addons/my_dock/dock.tscn**
```ini
[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://addons/my_dock/dock.gd" id="1_script"]

[node name="MyDock" type="Control"]
layout_mode = 3
anchors_preset = 15
script = ExtResource("1_script")

[node name="VBoxContainer" type="VBoxContainer" parent="."]
layout_mode = 1
anchors_preset = 15

[node name="Button" type="Button" parent="VBoxContainer"]
text = "Click Me"

[node name="Label" type="Label" parent="VBoxContainer"]
text = "Ready"
```

## 示例：自定义检查器插件

**生成文件：addons/inspector_plugin/plugin.cfg**
```ini
[plugin]
name="Custom Inspector"
description="Adds custom property editors"
author="Your Name"
version="1.0.0"
script="custom_inspector.gd"
```

**生成文件：addons/inspector_plugin/custom_inspector.gd**
```gdscript
@tool
extends EditorPlugin

var inspector_plugin: EditorInspectorPlugin

func _enter_tree():
    inspector_plugin = preload("res://addons/inspector_plugin/my_inspector_plugin.gd").new()
    add_inspector_plugin(inspector_plugin)

func _exit_tree():
    remove_inspector_plugin(inspector_plugin)
```

**生成文件：addons/inspector_plugin/my_inspector_plugin.gd**
```gdscript
@tool
extends EditorInspectorPlugin

func _can_handle(object: Object) -> bool:
    # Apply to any node with custom script
    return object is Node

func _parse_property(object: Object, type: Variant.Type, name: String,
                     hint_type: PropertyHint, hint_string: String,
                     usage_flags: int, wide: bool) -> bool:
    # Handle specific property types
    if name == "my_custom_property":
        add_property_editor(name, preload("res://addons/inspector_plugin/custom_property_editor.gd").new())
        return true  # Handled
    return false  # Use default editor
```

## 示例：@tool 脚本模式

**生成文件：addons/tools/scene_batch_processor.gd**
```gdscript
@tool
extends EditorScript

## Batch process scenes in editor
## Run via: Editor > Run > Run Script

@export var target_directory: String = "res://scenes"
@export var operation: String = "cleanup"

func _run():
    print("Starting batch processing...")

    var dir = DirAccess.open(target_directory)
    if dir:
        dir.list_dir_begin()
        var file_name = dir.get_next()

        while file_name != "":
            if file_name.ends_with(".tscn"):
                _process_scene(target_directory.path_join(file_name))
            file_name = dir.get_next()

    print("Batch processing complete!")

func _process_scene(path: String):
    var scene = load(path)
    if scene:
        print("Processing: ", path)
        # Perform operations on packed scene
```

## 停靠栏位置选项

| 位置 | 说明 | 适用场景 |
|------|----------|----------|
| `DOCK_SLOT_LEFT_UL` | 左侧，左上 | 主要工具，频繁访问 |
| `DOCK_SLOT_LEFT_BL` | 左侧，左下 | 次要面板 |
| `DOCK_SLOT_LEFT_UR` | 左侧，右上 | 检查器辅助 |
| `DOCK_SLOT_LEFT_BR` | 左侧，右下 | 调试/信息面板 |
| `DOCK_SLOT_RIGHT_UL` | 右侧，左上 | 属性、设置 |
| `DOCK_SLOT_RIGHT_BL` | 右侧，左下 | 控制台、输出 |
| `DOCK_SLOT_RIGHT_UR` | 右侧，右上 | 低频工具 |
| `DOCK_SLOT_RIGHT_BR` | 右侧，右下 | 底部辅助 |

## EditorPlugin 生命周期

```gdscript
func _enter_tree():
    # Called when plugin is enabled
    # Add docks, menus, inspectors here
    pass

func _exit_tree():
    # Called when plugin is disabled
    # Clean up everything added in _enter_tree
    pass

func _has_main_screen() -> bool:
    # Return true if plugin provides main screen (like 2D/3D/Script)
    return false

func _make_visible(visible: bool):
    # Called when main screen tab is selected/deselected
    pass

func _get_plugin_name() -> String:
    # Name shown in main screen tabs
    return "My Plugin"

func _get_plugin_icon() -> Texture2D:
    # Icon for main screen tab
    return get_editor_interface().get_base_control().get_theme_icon("Node", "EditorIcons")
```

## 设置集成

添加自定义 ProjectSettings 条目：

```gdscript
func _enter_tree():
    # Add setting if it doesn't exist
    if not ProjectSettings.has_setting("my_plugin/enable_debug"):
        ProjectSettings.set_setting("my_plugin/enable_debug", false)

        # Define property metadata
        ProjectSettings.add_property_info({
            "name": "my_plugin/enable_debug",
            "type": TYPE_BOOL,
            "hint": PROPERTY_HINT_NONE
        })

        # Set as basic setting (shows in Project Settings UI)
        ProjectSettings.set_initial_value("my_plugin/enable_debug", false)
        ProjectSettings.set_as_basic("my_plugin/enable_debug", true)
```

## 从插件访问编辑器

```gdscript
# Get the editor interface
var interface = get_editor_interface()

# Access editor features
var editor_selection = interface.get_selection()
var editor_settings = interface.get_editor_settings()
var resource_preview = interface.get_resource_previewer()

# Get current scene
var edited_scene_root = interface.get_edited_scene_root()

# Get selected nodes
var selected_nodes = editor_selection.get_selected_nodes()

# Open scene in editor
interface.open_scene_from_path("res://scene.tscn")

# Reload scene
interface.reload_scene_from_path("res://scene.tscn")

# Play scene
interface.play_current_scene()
```

## 创建的内容

- `addons/plugin_name/` 中的**完整插件结构**
- 包含正确元数据的 **plugin.cfg**
- 带生命周期钩子的 **EditorPlugin 脚本**
- **停靠栏场景**（UI）和脚本（逻辑）
- 用于专用工具的**底部面板**
- 用于自定义属性编辑器的**检查器插件**
- 用于编辑器自动化的 **@tool 脚本**
- 用于配置的 **ProjectSettings 集成**
- 记录每个组件的 **git 提交**

## 集成

可与以下技能配合使用：
- **godot-refactor**（编排器） - 作为大型重构的一部分创建插件
- **godot-extract-to-scenes** - 在插件 UI 中使用提取的组件
- **godot-add-signals** - 连接插件 UI 的 Signal

## 安全性

- 验证 plugin.cfg 语法
- 检查插件名称冲突
- 确保在 `_exit_tree()` 中正确清理
- 验证失败时自动回滚
- 每个生成的组件对应一次 git 提交

## 不应使用的情况

以下情况不需要创建插件：
- 一次性脚本（使用 EditorScript 即可，无需插件）
- 简单工具（使用 Project > Tools > GDScript）
- 运行时游戏功能（插件仅在编辑器中运行）
- 替换现有的 Godot 功能

## 最佳实践

1. **在 `_exit_tree()` 中清理** - 移除所有添加的 UI/组件
2. **使用 `@tool` 脚本** - 使代码能在编辑器中运行
3. **检查 `Engine.is_editor_hint()`** - 区分编辑器和运行时
4. **设置前缀** - 使用 `plugin_name/setting_name` 命名约定
5. **保存设置** - 修改后调用 `ProjectSettings.save()`
6. **处理选择** - 编辑器选择变更时更新 UI
7. **延迟加载** - 仅在需要时加载重量级资源

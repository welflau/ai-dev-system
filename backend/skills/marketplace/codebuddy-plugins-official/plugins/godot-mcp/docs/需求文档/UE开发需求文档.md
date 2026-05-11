# Unreal Engine MCP 开发需求文档

## 文档信息

| 项目 | 内容 |
|------|------|
| 文档名称 | Unreal Engine MCP 开发需求文档 |
| 版本 | 1.0.0 |
| 创建日期 | 2026-04-15 |
| 基于项目 | Godot-MCP |
| 目标引擎 | Unreal Engine 5.x |

---

## 1. 项目概述

### 1.1 目标

将 Godot-MCP 项目移植到 Unreal Engine 5.x，创建一个类似的 MCP 服务器，使 AI 助手能够通过自然语言与 Unreal Editor 进行交互，实现代码辅助、场景操作、资源管理和编辑器控制等功能。

### 1.2 核心价值

- 通过自然语言快速创建和编辑 C++/Blueprint 类
- 自动化场景搭建和 Actor 操作
- 智能资源管理和项目配置
- 提升 UE 开发效率和体验

### 1.3 技术选型

| 组件 | 技术选择 | 说明 |
|------|----------|------|
| MCP 服务器 | Node.js + TypeScript + FastMCP | 与 Godot 版本保持一致 |
| UE 插件通信 | Python + UnrealEnginePython 或 Editor Utility Widget | 推荐使用 Python 桥接层 |
| 通信协议 | WebSocket + JSON-RPC | 与 Godot 版本架构统一 |
| UE 端实现 | C++ Plugin + Python 脚本 | 利用 UE 的 Python 脚本支持 |

---

## 2. 架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                     Claude AI Assistant                         │
└───────────────────────────┬─────────────────────────────────────┘
                            │ MCP Protocol (stdio)
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│              MCP Server (TypeScript / Node.js)                  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  server/src/                                                ││
│  │  ├── index.ts            - FastMCP 服务器入口              ││
│  │  ├── tools/              - MCP 工具定义                    ││
│  │  │   ├── actor_tools.ts    - Actor 操作工具              ││
│  │  │   ├── blueprint_tools.ts - Blueprint 工具              ││
│  │  │   ├── component_tools.ts - 组件操作工具                ││
│  │  │   ├── level_tools.ts    - 关卡/场景工具                ││
│  │  │   ├── asset_tools.ts    - 资源管理工具                 ││
│  │  │   ├── project_tools.ts  - 项目配置工具                 ││
│  │  │   └── editor_tools.ts    - 编辑器控制工具               ││
│  │  ├── resources/          - MCP 资源定义                    ││
│  │  └── utils/              - 工具函数                        ││
│  └─────────────────────────────────────────────────────────────┘│
└───────────────────────────┬─────────────────────────────────────┘
                            │ WebSocket (ws://localhost:9080)
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                  UE Plugin (C++ / Python)                        │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  UnrealMCP/                                                   ││
│  │  ├── UnrealMCP.uplugin     - 插件描述文件                   ││
│  │  ├── Source/                                                   ││
│  │  │   ├── UnrealMCP/                                            ││
│  │  │   │   ├── UnrealMCP.cpp      - 插件入口                   ││
│  │  │   │   ├── UnrealMCP.h                                       ││
│  │  │   │   ├── WebSocketServer.h/cpp - WebSocket 服务器         ││
│  │  │   │   ├── CommandRouter.h/cpp - 命令路由器                 ││
│  │  │   │   └── Commands/                                         ││
│  │  │   │       ├── ActorCommands.h/cpp    - Actor 命令         ││
│  │   │   │       ├── BlueprintCommands.h/cpp - Blueprint 命令   ││
│  │   │   │       ├── ComponentCommands.h/cpp - 组件命令         ││
│  │   │   │       ├── LevelCommands.h/cpp   - 关卡命令           ││
│  │   │   │       ├── AssetCommands.h/cpp   - 资源命令           ││
│  │   │   │       ├── ProjectCommands.h/cpp - 项目命令           ││
│  │   │   │       └── EditorCommands.h/cpp  - 编辑器命令          ││
│  │   │   └── UnrealMCPPython/                                   ││
│  │   │       ├── init_plugin.py     - Python 初始化脚本          ││
│  │   │       ├── command_bridge.py  - Python 命令桥接            ││
│  │   │       └── ue_wrapper.py      - UE API Python 封装         ││
│  │   └── Resources/                                              ││
│  │       └── EditorUtility/                                       ││
│  │           └── MCP_Panel.uasset  - 编辑器面板                 ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 通信协议

与 Godot 版本保持一致的 JSON-RPC 协议：

```json
// 请求格式
{
  "type": "command_type",
  "params": { ... },
  "commandId": "cmd_xxx"
}

// 成功响应
{
  "status": "success",
  "result": { ... },
  "commandId": "cmd_xxx"
}

// 错误响应
{
  "status": "error",
  "message": "错误描述",
  "commandId": "cmd_xxx"
}
```

---

## 3. 功能需求

### 3.1 Actor 相关命令 (ActorCommands)

| 命令 | 功能 | 参数 | 返回值 |
|------|------|------|--------|
| `create_actor` | 在关卡中创建 Actor | `class_name`, `location`, `rotation`, `name` | Actor 信息 |
| `delete_actor` | 删除 Actor | `actor_reference` | 执行结果 |
| `spawn_actor` | 从指定类动态生成 | `class_name`, `location`, `rotation`, `params` | Actor 引用 |
| `get_actor_transform` | 获取 Actor 变换 | `actor_reference` | Transform 数据 |
| `set_actor_transform` | 设置 Actor 变换 | `actor_reference`, `transform` | 执行结果 |
| `get_actor_components` | 获取 Actor 组件列表 | `actor_reference` | 组件数组 |
| `attach_actor` | 将 Actor 附加到另一个 Actor | `child_actor`, `parent_actor`, `socket_name` | 执行结果 |
| `detach_actor` | 从父 Actor 分离 | `actor_reference` | 执行结果 |
| `find_actors_by_tag` | 通过 Tag 查找 Actor | `tag` | Actor 数组 |
| `list_actors` | 列出关卡中所有 Actor | `level_path` (可选) | Actor 列表 |

### 3.2 Component 相关命令 (ComponentCommands)

| 命令 | 功能 | 参数 | 返回值 |
|------|------|------|--------|
| `add_component` | 添加组件到 Actor | `actor_reference`, `component_class` | 组件信息 |
| `remove_component` | 移除组件 | `actor_reference`, `component_class` | 执行结果 |
| `get_component_properties` | 获取组件属性 | `component_reference` | 属性字典 |
| `set_component_property` | 设置组件属性 | `component_reference`, `property_name`, `value` | 执行结果 |
| `find_component` | 查找指定类型的组件 | `actor_reference`, `component_class` | 组件引用 |

### 3.3 Blueprint 相关命令 (BlueprintCommands)

| 命令 | 功能 | 参数 | 返回值 |
|------|------|--------|
| `create_blueprint_class` | 创建 Blueprint 类 | `class_path`, `parent_class`, `description` | Blueprint 信息 |
| `create_blueprint_function` | 在 Blueprint 中创建函数 | `blueprint_path`, `function_name`, `inputs`, `outputs` | 函数定义 |
| `create_blueprint_variable` | 创建 Blueprint 变量 | `blueprint_path`, `variable_name`, `variable_type`, `default_value` | 变量信息 |
| `compile_blueprint` | 编译 Blueprint | `blueprint_path` | 编译结果 |
| `get_blueprint_schema` | 获取 Blueprint 结构定义 | `blueprint_path` | Schema 数据 |
| `set_blueprint_property` | 设置 Blueprint 默认属性 | `blueprint_path`, `property_name`, `value` | 执行结果 |
| `get_blueprint_functions` | 获取所有函数定义 | `blueprint_path` | 函数列表 |
| `get_blueprint_variables` | 获取所有变量定义 | `blueprint_path` | 变量列表 |
| `add_blueprint_node` | 添加 Blueprint 节点 | `blueprint_path`, `graph_name`, `node_class`, `position` | 节点信息 |
| `set_blueprint_pin_value` | 设置节点引脚值 | `node_reference`, `pin_name`, `value` | 执行结果 |

### 3.4 关卡相关命令 (LevelCommands)

| 命令 | 功能 | 参数 | 返回值 |
|------|------|------|--------|
| `create_level` | 创建新关卡 | `level_path`, `level_template` (可选) | 关卡信息 |
| `save_level` | 保存当前关卡 | `level_path` (可选) | 执行结果 |
| `load_level` | 加载关卡 | `level_path` | 关卡数据 |
| `get_current_level` | 获取当前关卡 | 无 | 关卡信息 |
| `get_level_actors` | 获取关卡所有 Actor | `level_path` (可选) | Actor 列表 |
| `get_level_actors_by_class` | 按类筛选 Actor | `level_path`, `actor_class` | Actor 列表 |
| `set_level_viewport` | 设置视口配置 | `camera_location`, `camera_rotation` | 执行结果 |

### 3.5 资源相关命令 (AssetCommands)

| 命令 | 功能 | 参数 | 返回值 |
|------|------|------|--------|
| `create_asset` | 创建资源文件 | `asset_type`, `asset_path`, `factory_params` | 资源信息 |
| `delete_asset` | 删除资源 | `asset_path` | 执行结果 |
| `load_asset` | 加载资源 | `asset_path` | 资源对象 |
| `save_asset` | 保存资源 | `asset_path` | 执行结果 |
| `duplicate_asset` | 复制资源 | `source_path`, `dest_path` | 新资源路径 |
| `rename_asset` | 重命名资源 | `old_path`, `new_path` | 新路径 |
| `move_asset` | 移动资源 | `source_path`, `dest_folder` | 新路径 |
| `find_assets` | 搜索资源 | `search_path`, `filter`, `recursive` | 资源列表 |
| `import_asset` | 导入外部资源 | `source_file`, `dest_path`, `import_options` | 资源信息 |
| `get_asset_info` | 获取资源元数据 | `asset_path` | 资源信息 |
| `reimport_asset` | 重新导入资源 | `asset_path` | 执行结果 |
| `list_asset_factory_types` | 列出可用的资源工厂类型 | 无 | 类型列表 |

### 3.6 项目相关命令 (ProjectCommands)

| 命令 | 功能 | 参数 | 返回值 |
|------|------|------|--------|
| `get_project_info` | 获取项目信息 | 无 | 项目配置 |
| `get_project_settings` | 获取项目设置 | `category` (可选) | 设置数据 |
| `set_project_setting` | 设置项目配置 | `key`, `value`, `category` | 执行结果 |
| `get_project_structure` | 获取项目目录结构 | `root_path` (可选), `depth` | 目录树 |
| `list_project_content` | 列出 Content 目录 | `folder_path`, `recursive` | 内容列表 |
| `get_engine_info` | 获取引擎版本信息 | 无 | 引擎信息 |
| `get_plugins_list` | 获取已安装插件列表 | 无 | 插件列表 |
| `enable_plugin` | 启用插件 | `plugin_name` | 执行结果 |
| `disable_plugin` | 禁用插件 | `plugin_name` | 执行结果 |

### 3.7 编辑器相关命令 (EditorCommands)

| 命令 | 功能 | 参数 | 返回值 |
|------|------|------|--------|
| `get_editor_state` | 获取编辑器状态 | 无 | 状态信息 |
| `get_selection` | 获取当前选中对象 | 无 | 选择集 |
| `select_actor` | 选中指定 Actor | `actor_reference` | 执行结果 |
| `deselect_all` | 取消所有选中 | 无 | 执行结果 |
| `get_editor_mode` | 获取编辑器模式 | 无 | 模式名称 |
| `set_editor_mode` | 设置编辑器模式 | `mode` | 执行结果 |
| `execute_command` | 执行控制台命令 | `command` | 执行结果 |
| `execute_editor_script` | 执行 Python 脚本 | `script_content` | 脚本输出 |
| `run_game` | 运行游戏 | `play_in_viewport` (可选), `game_mode` | 执行结果 |
| `stop_game` | 停止游戏运行 | 无 | 执行结果 |
| `pause_game` | 暂停游戏 | 无 | 执行结果 |
| `resume_game` | 恢复游戏 | 无 | 执行结果 |
| `screenshot` | 截取编辑器截图 | `save_path` | 文件路径 |
| `show_source_code` | 在 IDE 中打开源码 | `file_path`, `line_number` (可选) | 执行结果 |

### 3.8 C++ 代码相关命令 (CppCodeCommands)

| 命令 | 功能 | 参数 | 返回值 |
|------|------|------|--------|
| `create_cpp_class` | 创建 C++ 类 | `class_name`, `parent_class`, `header_path`, `source_path` | 类文件路径 |
| `create_cpp_function` | 在现有类中添加函数 | `class_header_path`, `function_signature`, `access_specifier` | 执行结果 |
| `create_cpp_property` | 在现有类中添加属性 | `class_header_path`, `property_declaration`, `access_specifier` | 执行结果 |
| `generate_project_files` | 重新生成 UE 项目文件 | 无 | 执行结果 |
| `compile_project` | 编译项目 | `target` (可选) | 编译结果 |
| `get_cpp_class_schema` | 获取 C++ 类定义 | `header_path` | 类 Schema |
| `find_cpp_reference` | 查找 C++ 代码引用 | `class_name` | 引用列表 |

---

## 4. MCP 资源端点

### 4.1 资源 URI 定义

| URI | 功能 | 说明 |
|-----|------|------|
| `unreal/editor/state` | 编辑器当前状态 | 模式、选中对象、视口 |
| `unreal/editor/selection` | 当前选择集 | 选中的 Actor/资产 |
| `unreal/level/current` | 当前关卡信息 | 关卡路径、Actor 列表 |
| `unreal/level/actors` | 关卡 Actor 列表 | 当前关卡所有 Actor |
| `unreal/blueprint/{path}` | Blueprint 定义 | 结构、变量、函数 |
| `unreal/asset/{path}` | 资源信息 | 资源类型、引用、属性 |
| `unreal/project/info` | 项目信息 | 项目名称、引擎版本、路径 |
| `unreal/project/settings` | 项目设置 | 所有配置项 |
| `unreal/project/structure` | 项目结构 | 目录树 |
| `unreal/class/{name}` | C++ 类信息 | 头文件、成员、继承关系 |

### 4.2 资源订阅

支持编辑器事件订阅：
- `unreal/editor/selection/changed` - 选择改变
- `unreal/editor/mode/changed` - 编辑模式改变
- `unreal/level/loaded` - 关卡加载完成
- `unreal/level/saved` - 关卡保存完成
- `unreal/asset/created` - 资源创建
- `unreal/asset/modified` - 资源修改
- `unreal/build/completed` - 构建完成

---

## 5. 技术实现要点

### 5.1 UE 端实现策略

#### 方案一：C++ Plugin + Python 桥接（推荐）

```
MCP Server (Node.js)
    ↓ WebSocket
Python Bridge (unreal的外置Python脚本)
    ↓ Unreal Python API
UE Editor
```

优点：
- 充分利用 UE 的 Python 脚本支持
- 开发效率高，迭代快
- 可以复用 Python 生态工具

缺点：
- 部分 UE API 可能不可用

#### 方案二：纯 C++ Plugin

```
MCP Server (Node.js)
    ↓ WebSocket
C++ WebSocketServer
    ↓ 直接调用
UE Editor API
```

优点：
- 完全访问所有 UE API
- 性能最优
- 稳定性好

缺点：
- 开发周期长
- 编译时间长

### 5.2 Blueprint 访问方案

使用 `FBlueprintEditorLibrary` 和 `FKismetEditorUtilities`：
- 读取/修改 Blueprint 变量
- 创建和连接节点
- 编译 Blueprint

### 5.3 WebSocket 实现

使用 UE 的 `FWebSocketsModule`：
```cpp
#include "IWebSocketsModule.h"
#include "WebSocketsManager.h"
```

### 5.4 JSON-RPC 编解码

使用 UE 的 `TJsonReaderFactory` 和 `TJsonWriterFactory`：
```cpp
#include "Serialization/JsonReader.h"
#include "Serialization/JsonWriter.h"
#include "Serialization/JsonTypes.h"
```

---

## 6. 开发任务分解

### 6.1 第一阶段：基础架构

| 任务 ID | 任务名称 | 预估工时 | 优先级 |
|---------|----------|----------|--------|
| T1.1 | 创建 UE Plugin 项目结构 | 2h | P0 |
| T1.2 | 实现 WebSocket 服务器 | 4h | P0 |
| T1.3 | 实现 JSON-RPC 编解码 | 2h | P0 |
| T1.4 | 实现命令路由器 | 2h | P0 |
| T1.5 | 实现编辑器面板 UI | 3h | P1 |
| T1.6 | 编写 MCP Server TypeScript 端 | 4h | P0 |

### 6.2 第二阶段：核心功能

| 任务 ID | 任务名称 | 预估工时 | 优先级 |
|---------|----------|----------|--------|
| T2.1 | Actor 相关命令实现 | 6h | P0 |
| T2.2 | 关卡相关命令实现 | 4h | P0 |
| T2.3 | 资源管理命令实现 | 6h | P0 |
| T2.4 | 项目配置命令实现 | 3h | P1 |
| T2.5 | 编辑器控制命令实现 | 4h | P1 |

### 6.3 第三阶段：高级功能

| 任务 ID | 任务名称 | 预估工时 | 优先级 |
|---------|----------|----------|--------|
| T3.1 | Blueprint 操作命令实现 | 8h | P0 |
| T3.2 | C++ 代码生成命令实现 | 6h | P1 |
| T3.3 | Component 操作命令实现 | 4h | P1 |
| T3.4 | MCP 资源端点实现 | 4h | P1 |
| T3.5 | 事件订阅系统实现 | 4h | P2 |

### 6.4 第四阶段：测试与优化

| 任务 ID | 任务名称 | 预估工时 | 优先级 |
|---------|----------|----------|--------|
| T4.1 | 单元测试编写 | 8h | P1 |
| T4.2 | 集成测试 | 4h | P1 |
| T4.3 | 性能优化 | 4h | P2 |
| T4.4 | 文档编写 | 4h | P1 |
| T4.5 | 用户测试与反馈 | 持续 | - |

---

## 7. API 映射参考

### 7.1 Godot → Unreal 对应关系

| Godot 概念 | Unreal 对应 | 说明 |
|------------|-------------|------|
| Node | Actor / Component | 场景基本单元 |
| Scene | Level / Map | 关卡文件 |
| GDScript | C++ / Blueprint | 脚本语言 |
| extends | inherit | 继承关系 |
| NodePath | Actor Reference | 节点路径 |
| SceneTree | World / Level | 场景树 |
| Resource | Asset / DataAsset | 资源 |
| signals | Delegates / Events | 事件信号 |
| export | BlueprintReadOnly/Write | 属性暴露 |
| onready | TSubclassOf / 构造函数 | 延迟初始化 |

### 7.2 常用 API 映射

| 功能 | Godot API | Unreal API |
|------|-----------|------------|
| 创建节点 | `Node.new()` | `World->SpawnActor()` |
| 获取节点 | `get_node(path)` | `Actor->FindComponentByClass()` |
| 添加子节点 | `add_child(node)` | `Actor->AttachToActor()` |
| 设置位置 | `position = Vector3()` | `Actor->SetActorLocation()` |
| 获取子节点 | `get_children()` | `Actor->GetComponents()` |
| 添加脚本 | `add_child(script)` | `Blueprint / C++ 组件 |
| 创建资源 | `Resource.new()` | `FAssetTools::CreateAsset()` |

---

## 8. 已知挑战与解决方案

### 8.1 Blueprint 与 C++ 混合处理

挑战：UE 中 Blueprint 和 C++ 类有不同的工作流程。

解决方案：
- 创建统一的 `UObjectWrapper` 抽象层
- Blueprint 操作通过 K2Node 和 KismetCompiler
- C++ 操作通过 HeaderParser 和 UHT

### 8.2 异步操作处理

挑战：UE 大量使用异步回调。

解决方案：
- 使用 `TFuture` 和 `TPromise` 封装
- 实现命令队列管理
- 添加超时和取消机制

### 8.3 编辑器上下文切换

挑战：不同编辑器模式有不同 API 可用。

解决方案：
- 实现编辑器状态检测
- 根据当前模式启用/禁用命令
- 提供友好的错误提示

### 8.4 中文路径支持

挑战：UE 对中文路径支持不完善。

解决方案：
- 在 UE Plugin 中使用 FPaths::GameSourceDir
- MCP Server 统一使用 UTF-8 编码
- 路径转换工具函数

---

## 9. 配置项

### 9.1 WebSocket 配置

```json
{
  "unreal_mcp": {
    "websocket": {
      "host": "localhost",
      "port": 9080,
      "auto_reconnect": true,
      "max_reconnect_attempts": 3,
      "reconnect_interval": 2000
    },
    "command": {
      "timeout": 30000,
      "retry_enabled": true
    },
    "logging": {
      "level": "info",
      "log_file": "unreal_mcp.log"
    }
  }
}
```

### 9.2 MCP Server 配置

```json
{
  "mcp": {
    "server_name": "Unreal Engine MCP",
    "server_version": "1.0.0"
  },
  "unreal": {
    "default_level": "/Game/Maps/Startup",
    "project_path": null,
    "auto_connect": true
  }
}
```

---

## 10. 文件结构

```
UnrealMCP/
├── UnrealMCP.uplugin                 # 插件描述文件
├── LICENSE
│
├── Source/
│   ├── UnrealMCP/                     # 主模块
│   │   ├── Public/
│   │   │   ├── UnrealMCP.h
│   │   │   ├── WebSocketServer.h
│   │   │   ├── CommandRouter.h
│   │   │   ├── JsonRpcHandler.h
│   │   │   └── Commands/
│   │   │       ├── ICommand.h
│   │   │       ├── ActorCommands.h
│   │   │       ├── BlueprintCommands.h
│   │   │       ├── ComponentCommands.h
│   │   │       ├── LevelCommands.h
│   │   │       ├── AssetCommands.h
│   │   │       ├── ProjectCommands.h
│   │   │       ├── EditorCommands.h
│   │   │       └── CppCodeCommands.h
│   │   ├── Private/
│   │   │   ├── UnrealMCP.cpp
│   │   │   ├── WebSocketServer.cpp
│   │   │   ├── CommandRouter.cpp
│   │   │   ├── JsonRpcHandler.cpp
│   │   │   └── Commands/
│   │   │       ├── ActorCommands.cpp
│   │   │       ├── BlueprintCommands.cpp
│   │   │       ├── ComponentCommands.cpp
│   │   │       ├── LevelCommands.cpp
│   │   │       ├── AssetCommands.cpp
│   │   │       ├── ProjectCommands.cpp
│   │   │       ├── EditorCommands.cpp
│   │   │       └── CppCodeCommands.cpp
│   │   └── UnrealMCP.Build.cs
│   │
│   └── UnrealMCPPython/               # Python 桥接模块
│       ├── init_plugin.py
│       ├── command_bridge.py
│       ├── ue_wrapper.py
│       ├── actor_utils.py
│       ├── blueprint_utils.py
│       ├── asset_utils.py
│       └── level_utils.py
│
├── Resources/
│   ├── EditorUtility/
│   │   └── MCP_Panel/
│   │       └── MCP_Panel.uasset
│   └── Icons/
│       └── icon.png
│
└── Content/
    └── Config/
        └── DefaultUnrealMCP.ini

server/
├── src/
│   ├── index.ts
│   ├── tools/
│   │   ├── actor_tools.ts
│   │   ├── blueprint_tools.ts
│   │   ├── component_tools.ts
│   │   ├── level_tools.ts
│   │   ├── asset_tools.ts
│   │   ├── project_tools.ts
│   │   ├── editor_tools.ts
│   │   └── cpp_tools.ts
│   ├── resources/
│   │   ├── unreal_resources.ts
│   │   └── editor_resources.ts
│   └── utils/
│       ├── unreal_connection.ts
│       └── types.ts
├── package.json
└── tsconfig.json

docs/
├── README.md
├── architecture.md
├── command-reference.md
├── installation-guide.md
├── ue-api-mapping.md
└── troubleshooting-guide.md
```

---

## 11. 验收标准

### 11.1 功能验收

- [ ] MCP Server 可以正常启动和连接
- [ ] 所有 Actor 命令正常工作
- [ ] 所有 Blueprint 命令正常工作
- [ ] 所有资源管理命令正常工作
- [ ] 编辑器控制命令正常工作
- [ ] MCP 资源端点返回正确数据
- [ ] WebSocket 断开后自动重连

### 11.2 性能指标

- 命令响应时间 < 500ms (不含编辑器操作)
- 支持同时处理 10+ 并发命令
- 内存占用 < 100MB
- CPU 占用 < 5% (空闲时)

### 11.3 稳定性要求

- 长时间运行不崩溃
- 错误命令有友好的错误提示
- 日志记录完整，便于排查问题

---

## 12. 附录

### 12.1 参考资料

- [Unreal Engine Python API](https://docs.unrealengine.com/en-US/PythonAPI/)
- [Unreal Editor Plugin Development](https://docs.unrealengine.com/en-US/Programming/Plugins/)
- [MCP Protocol Specification](https://modelcontextprotocol.io/)
- [JSON-RPC 2.0 Specification](https://www.jsonrpc.org/specification)

### 12.2 术语表

| 术语 | 说明 |
|------|------|
| Actor | UE 中的场景对象，类似 Godot 的 Node |
| Component | 组件，附加到 Actor 的功能模块 |
| Blueprint | UE 的可视化脚本系统 |
| Level | 关卡，场景文件 |
| Asset | 资源，项目的各种文件 |
| UPROPERTY | C++ 属性宏，用于暴露给编辑器 |
| UCLASS | C++ 类宏，声明 UE 类 |

---

*文档版本: 1.0.0*
*最后更新: 2026-04-15*

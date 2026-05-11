# Godot MCP 需求详解

## 1. 项目概述

### 1.1 项目定位
Godot MCP 是一个为 Godot 游戏引擎提供 Model Context Protocol (MCP) 支持的插件系统，允许 AI 助手（如 Claude）通过标准化协议与 Godot 编辑器进行交互，实现场景管理、节点操作、脚本编辑等功能的自动化。

### 1.2 系统架构
```
┌─────────────────┐    stdio     ┌─────────────────┐   WebSocket    ┌─────────────────┐
│   AI Assistant  │ ◄──────────► │  MCP Server     │ ◄────────────► │  Godot Editor   │
│   (Claude等)    │              │  (Node.js)      │    Port:8090   │  (GDScript插件) │
└─────────────────┘              └─────────────────┘                └─────────────────┘
```

### 1.3 技术栈
| 组件 | 技术 | 说明 |
|------|------|------|
| MCP Server | Node.js + TypeScript | 处理 stdio 通信，转发请求到 Godot |
| Godot 插件 | GDScript | 在编辑器中运行，处理实际操作 |
| 通信协议 | WebSocket | Server 与 Godot 之间的双向通信 |
| 默认端口 | 8090 | WebSocket 服务监听端口 |

---

## 2. 功能需求清单

### 2.1 MCP Server 端 (Node.js)

#### 2.1.1 核心通信功能
| 功能项 | 描述 | 优先级 |
|--------|------|--------|
| stdio 通信 | 通过标准输入输出与 AI 助手通信 | P0 |
| WebSocket 客户端 | 连接 Godot 编辑器的 WebSocket 服务 | P0 |
| 请求转发 | 将 MCP 工具调用转发到 Godot | P0 |
| 响应处理 | 接收 Godot 响应并返回给 AI | P0 |
| 连接状态管理 | 自动重连、心跳检测、超时处理 | P1 |
| 错误处理 | 优雅处理连接失败、超时等异常 | P1 |

#### 2.1.2 MCP Tools 实现
需要实现以下 MCP 工具供 AI 调用：

**场景操作 (Scene Tools)**
| 工具名称 | 功能描述 | 参数 |
|----------|----------|------|
| `get_current_scene` | 获取当前打开的场景信息 | 无 |
| `open_scene` | 打开指定场景文件 | `path: string` |
| `save_scene` | 保存当前场景 | `path?: string` |
| `create_scene` | 创建新场景 | `root_type: string, path: string` |
| `get_scene_tree` | 获取场景节点树结构 | 无 |

**节点操作 (Node Tools)**
| 工具名称 | 功能描述 | 参数 |
|----------|----------|------|
| `add_node` | 添加新节点 | `parent_path: string, node_type: string, node_name: string` |
| `remove_node` | 删除节点 | `node_path: string` |
| `get_node_properties` | 获取节点属性 | `node_path: string` |
| `set_node_property` | 设置节点属性 | `node_path: string, property: string, value: any` |
| `move_node` | 移动节点（改变父节点） | `node_path: string, new_parent_path: string` |
| `duplicate_node` | 复制节点 | `node_path: string` |
| `rename_node` | 重命名节点 | `node_path: string, new_name: string` |

**脚本操作 (Script Tools)**
| 工具名称 | 功能描述 | 参数 |
|----------|----------|------|
| `create_script` | 创建新脚本 | `path: string, content?: string, node_path?: string` |
| `read_script` | 读取脚本内容 | `path: string` |
| `update_script` | 更新脚本内容 | `path: string, content: string` |
| `attach_script` | 为节点附加脚本 | `node_path: string, script_path: string` |
| `detach_script` | 移除节点脚本 | `node_path: string` |

**编辑器操作 (Editor Tools)**
| 工具名称 | 功能描述 | 参数 |
|----------|----------|------|
| `run_project` | 运行项目 | 无 |
| `stop_project` | 停止运行 | 无 |
| `run_current_scene` | 运行当前场景 | 无 |
| `get_editor_settings` | 获取编辑器设置 | 无 |
| `execute_menu_action` | 执行编辑器菜单命令 | `action: string` |

#### 2.1.3 MCP Resources 实现
需要实现以下资源类型：

| 资源 URI 模式 | 描述 | 返回内容 |
|--------------|------|----------|
| `godot://scene/current` | 当前场景信息 | 场景路径、根节点类型、节点树 |
| `godot://scene/{path}` | 指定场景文件内容 | 场景 TSCN 内容 |
| `godot://script/{path}` | 脚本文件内容 | GDScript/C# 源码 |
| `godot://project/settings` | 项目设置 | project.godot 配置 |
| `godot://project/structure` | 项目结构 | 文件目录树 |

### 2.2 Godot 插件端 (GDScript)

#### 2.2.1 核心功能
| 功能项 | 描述 | 优先级 |
|--------|------|--------|
| WebSocket 服务端 | 监听端口接受 MCP Server 连接 | P0 |
| 命令处理器 | 解析并执行来自 Server 的命令 | P0 |
| 响应返回 | 将执行结果返回给 Server | P0 |
| 编辑器 API 封装 | 安全地调用 Godot 编辑器 API | P0 |
| UI 面板 | 显示连接状态、日志等信息 | P2 |

#### 2.2.2 命令处理器模块
需要实现以下命令处理器：

| 处理器 | 职责 | 对应文件 |
|--------|------|----------|
| `scene_commands` | 场景相关操作 | `commands/scene_commands.gd` |
| `node_commands` | 节点相关操作 | `commands/node_commands.gd` |
| `script_commands` | 脚本相关操作 | `commands/script_commands.gd` |
| `editor_commands` | 编辑器操作 | `commands/editor_commands.gd` |
| `project_commands` | 项目级操作 | `commands/project_commands.gd` |

#### 2.2.3 工具类模块
| 工具类 | 职责 | 对应文件 |
|--------|------|----------|
| `node_utils` | 节点路径解析、节点查找等 | `utils/node_utils.gd` |
| `script_utils` | 脚本模板生成、语法验证等 | `utils/script_utils.gd` |
| `resource_utils` | 资源加载、保存、路径处理 | `utils/resource_utils.gd` |

---

## 3. 详细任务分解

### 3.1 阶段一：基础通信 (P0)

#### 任务 1.1：MCP Server 基础框架
- [ ] 配置 TypeScript 项目结构
- [ ] 实现 MCP SDK 集成
- [ ] 实现 stdio 传输层
- [ ] 实现基本的工具注册机制

#### 任务 1.2：WebSocket 通信层
- [ ] Server 端：实现 WebSocket 客户端连接逻辑
- [ ] Server 端：实现请求-响应消息格式
- [ ] Godot 端：实现 WebSocket 服务端
- [ ] Godot 端：实现消息解析和分发

#### 任务 1.3：命令处理框架
- [ ] 定义统一的命令/响应 JSON 格式
- [ ] 实现命令路由机制
- [ ] 实现错误处理和返回

### 3.2 阶段二：核心功能 (P0)

#### 任务 2.1：场景操作
- [ ] 实现 `get_current_scene` - 获取当前场景
- [ ] 实现 `open_scene` - 打开场景
- [ ] 实现 `save_scene` - 保存场景
- [ ] 实现 `create_scene` - 创建场景
- [ ] 实现 `get_scene_tree` - 获取场景树

#### 任务 2.2：节点操作
- [ ] 实现 `add_node` - 添加节点
- [ ] 实现 `remove_node` - 删除节点
- [ ] 实现 `get_node_properties` - 获取属性
- [ ] 实现 `set_node_property` - 设置属性
- [ ] 实现 `move_node` - 移动节点
- [ ] 实现 `duplicate_node` - 复制节点
- [ ] 实现 `rename_node` - 重命名节点

#### 任务 2.3：脚本操作
- [ ] 实现 `create_script` - 创建脚本
- [ ] 实现 `read_script` - 读取脚本
- [ ] 实现 `update_script` - 更新脚本
- [ ] 实现 `attach_script` - 附加脚本
- [ ] 实现 `detach_script` - 移除脚本

### 3.3 阶段三：编辑器集成 (P1)

#### 任务 3.1：编辑器操作
- [ ] 实现 `run_project` - 运行项目
- [ ] 实现 `stop_project` - 停止项目
- [ ] 实现 `run_current_scene` - 运行当前场景
- [ ] 实现编辑器状态查询

#### 任务 3.2：资源系统
- [ ] 实现 MCP Resources 框架
- [ ] 实现场景资源读取
- [ ] 实现脚本资源读取
- [ ] 实现项目结构资源

### 3.4 阶段四：稳定性与体验 (P1-P2)

#### 任务 4.1：连接稳定性
- [ ] 实现自动重连机制
- [ ] 实现心跳检测
- [ ] 实现请求超时处理
- [ ] 实现并发请求处理

#### 任务 4.2：UI 面板
- [ ] 实现连接状态显示
- [ ] 实现日志查看
- [ ] 实现端口配置
- [ ] 实现手动连接/断开按钮

---

## 4. 通信协议规范

### 4.1 消息格式

#### 请求消息 (Server → Godot)
```json
{
  "id": "unique-request-id",
  "type": "request",
  "command": "scene/get_current",
  "params": {
    "key": "value"
  }
}
```

#### 响应消息 (Godot → Server)
```json
{
  "id": "unique-request-id",
  "type": "response",
  "success": true,
  "data": {
    "result": "..."
  },
  "error": null
}
```

#### 错误响应
```json
{
  "id": "unique-request-id",
  "type": "response",
  "success": false,
  "data": null,
  "error": {
    "code": "SCENE_NOT_FOUND",
    "message": "No scene is currently open"
  }
}
```

### 4.2 命令命名规范
- 格式：`{category}/{action}`
- 示例：`scene/get_current`, `node/add`, `script/create`

### 4.3 错误码定义
| 错误码 | 含义 |
|--------|------|
| `CONNECTION_ERROR` | 连接失败 |
| `TIMEOUT` | 请求超时 |
| `INVALID_PARAMS` | 参数无效 |
| `SCENE_NOT_FOUND` | 场景未找到 |
| `NODE_NOT_FOUND` | 节点未找到 |
| `SCRIPT_ERROR` | 脚本操作失败 |
| `PERMISSION_DENIED` | 权限不足 |
| `INTERNAL_ERROR` | 内部错误 |

---

## 5. 本地验证方案

### 5.1 环境准备

#### 5.1.1 前置条件
- [ ] Node.js >= 18 已安装
- [ ] npm 已安装
- [ ] Godot 4.x 编辑器已安装
- [ ] 项目代码已克隆

#### 5.1.2 构建 Server
```bash
cd server
npm install
npm run build
```

#### 5.1.3 安装 Godot 插件
1. 将 `addons/godot_mcp/` 复制到 Godot 项目的 `addons/` 目录
2. 打开 Godot 编辑器
3. 进入 Project → Project Settings → Plugins
4. 启用 "Godot MCP" 插件

### 5.2 功能验证测试用例

#### 5.2.1 连接测试
| 测试项 | 操作 | 预期结果 |
|--------|------|----------|
| 基础连接 | 启动 Server，确认 Godot 插件已启用 | Server 日志显示连接成功 |
| 断线重连 | 关闭 Godot 后重新打开 | Server 自动重新连接 |
| 连接状态显示 | 查看 Godot MCP 面板 | 显示 "已连接" 状态 |

#### 5.2.2 场景操作测试
| 测试项 | 操作 | 预期结果 |
|--------|------|----------|
| 获取当前场景 | 调用 `get_current_scene` | 返回当前打开场景的路径和信息 |
| 打开场景 | 调用 `open_scene` 指定有效路径 | Godot 编辑器切换到该场景 |
| 保存场景 | 修改场景后调用 `save_scene` | 场景文件被保存 |
| 创建新场景 | 调用 `create_scene` | 新场景被创建并打开 |
| 获取场景树 | 调用 `get_scene_tree` | 返回完整的节点树结构 |

#### 5.2.3 节点操作测试
| 测试项 | 操作 | 预期结果 |
|--------|------|----------|
| 添加节点 | 调用 `add_node` 添加 Sprite2D | 场景中出现新的 Sprite2D 节点 |
| 删除节点 | 调用 `remove_node` 删除刚添加的节点 | 节点被移除 |
| 获取属性 | 调用 `get_node_properties` | 返回节点的所有属性 |
| 设置属性 | 调用 `set_node_property` 修改 position | 节点位置发生变化 |
| 重命名节点 | 调用 `rename_node` | 节点名称被更新 |

#### 5.2.4 脚本操作测试
| 测试项 | 操作 | 预期结果 |
|--------|------|----------|
| 创建脚本 | 调用 `create_script` | 新脚本文件被创建 |
| 读取脚本 | 调用 `read_script` | 返回脚本内容 |
| 更新脚本 | 调用 `update_script` 修改内容 | 脚本内容被更新 |
| 附加脚本 | 调用 `attach_script` | 节点关联上脚本 |
| 移除脚本 | 调用 `detach_script` | 节点脚本被移除 |

#### 5.2.5 编辑器操作测试
| 测试项 | 操作 | 预期结果 |
|--------|------|----------|
| 运行项目 | 调用 `run_project` | 游戏窗口启动 |
| 停止项目 | 调用 `stop_project` | 游戏窗口关闭 |
| 运行当前场景 | 调用 `run_current_scene` | 当前场景在游戏窗口中运行 |

### 5.3 使用 MCP Inspector 验证

MCP Inspector 是官方提供的调试工具，可用于测试 MCP Server：

```bash
# 安装 MCP Inspector
npx @modelcontextprotocol/inspector server/dist/index.js
```

在 Inspector 中可以：
- 查看所有注册的 Tools 和 Resources
- 手动调用 Tools 并查看返回结果
- 调试通信过程

### 5.4 集成测试脚本

创建测试脚本 `test/integration_test.js`：

```javascript
// 测试流程：
// 1. 启动 MCP Server
// 2. 等待 Godot 连接
// 3. 执行一系列操作
// 4. 验证结果
// 5. 输出测试报告
```

---

## 6. 效果评估标准

### 6.1 功能完整性评估

#### 6.1.1 核心功能覆盖率
| 等级 | 标准 | 分数 |
|------|------|------|
| 优秀 | 所有 P0 功能实现，90%+ P1 功能实现 | 90-100 |
| 良好 | 所有 P0 功能实现，70%+ P1 功能实现 | 75-89 |
| 合格 | 所有 P0 功能实现 | 60-74 |
| 不合格 | P0 功能未完全实现 | <60 |

#### 6.1.2 功能验证清单
- [ ] 场景操作：5/5 功能可用
- [ ] 节点操作：7/7 功能可用
- [ ] 脚本操作：5/5 功能可用
- [ ] 编辑器操作：4/4 功能可用
- [ ] 资源访问：5/5 资源可读取

### 6.2 稳定性评估

#### 6.2.1 连接稳定性
| 指标 | 合格标准 | 优秀标准 |
|------|----------|----------|
| 连接成功率 | >= 95% | >= 99% |
| 断线重连成功率 | >= 90% | >= 99% |
| 心跳超时处理 | 正确检测并重连 | 无误报 |

#### 6.2.2 请求处理
| 指标 | 合格标准 | 优秀标准 |
|------|----------|----------|
| 请求成功率 | >= 95% | >= 99% |
| 平均响应时间 | < 500ms | < 100ms |
| 超时处理 | 正确返回错误 | 可配置超时时间 |
| 并发处理 | 支持 5 个并发 | 支持 20+ 并发 |

#### 6.2.3 错误处理
| 指标 | 合格标准 | 优秀标准 |
|------|----------|----------|
| 错误信息清晰度 | 包含错误类型和原因 | 包含解决建议 |
| 异常不崩溃 | Server/插件不崩溃 | 自动恢复 |
| 日志记录 | 记录错误日志 | 分级日志，可追溯 |

### 6.3 用户体验评估

#### 6.3.1 部署体验
| 指标 | 合格标准 | 优秀标准 |
|------|----------|----------|
| 安装步骤 | <= 5 步 | <= 3 步 |
| 安装文档 | 有基本说明 | 有详细图文教程 |
| 自动化程度 | 手动配置 | 一键部署 |

#### 6.3.2 使用体验
| 指标 | 合格标准 | 优秀标准 |
|------|----------|----------|
| 启动便捷性 | 明确的启动方式 | 自动启动 |
| 状态可见性 | 有连接状态显示 | 实时日志查看 |
| 配置灵活性 | 可配置端口 | 全参数可配置 |

### 6.4 代码质量评估

#### 6.4.1 代码规范
| 指标 | 合格标准 | 优秀标准 |
|------|----------|----------|
| 代码风格 | 统一风格 | 有 lint 检查 |
| 注释覆盖 | 关键函数有注释 | 全面的 JSDoc/文档注释 |
| 类型安全 | TypeScript 编译通过 | 严格模式无 any |

#### 6.4.2 架构设计
| 指标 | 合格标准 | 优秀标准 |
|------|----------|----------|
| 模块化 | 功能分模块 | 高内聚低耦合 |
| 可扩展性 | 可添加新命令 | 插件式架构 |
| 可维护性 | 代码可读 | 有单元测试 |

### 6.5 综合评分表

| 维度 | 权重 | 得分 | 加权分 |
|------|------|------|--------|
| 功能完整性 | 40% | /100 | |
| 稳定性 | 30% | /100 | |
| 用户体验 | 15% | /100 | |
| 代码质量 | 15% | /100 | |
| **总分** | 100% | | **/100** |

#### 评分等级
- **A (90-100)**: 优秀，可正式发布
- **B (80-89)**: 良好，小幅优化后可发布
- **C (70-79)**: 合格，需要改进
- **D (60-69)**: 基本可用，需要较多改进
- **F (<60)**: 不合格，需要重新开发

---

## 7. MCP 配置参考

### 7.1 Claude Desktop 配置示例
```json
{
  "mcpServers": {
    "godot-mcp": {
      "command": "node",
      "args": ["D:/Godot-MCP/server/dist/index.js"],
      "env": {
        "MCP_TRANSPORT": "stdio",
        "GODOT_WS_PORT": "8090"
      }
    }
  }
}
```

### 7.2 环境变量说明
| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `MCP_TRANSPORT` | `stdio` | 传输方式，固定为 stdio |
| `GODOT_WS_PORT` | `8090` | Godot WebSocket 服务端口 |
| `GODOT_WS_HOST` | `localhost` | Godot WebSocket 服务地址 |
| `MCP_REQUEST_TIMEOUT` | `10000` | 请求超时时间（毫秒） |
| `MCP_DEBUG` | `false` | 是否启用调试日志 |

---

## 8. 附录

### 8.1 参考资源
- [MCP 官方文档](https://modelcontextprotocol.io/)
- [Godot 编辑器插件开发](https://docs.godotengine.org/en/stable/tutorials/plugins/editor/index.html)
- [Godot WebSocket API](https://docs.godotengine.org/en/stable/classes/class_websocketpeer.html)

### 8.2 相关文件
- [架构文档](./architecture.md)
- [命令参考](./command-reference.md)
- [安装指南](./installation-guide.md)
- [快速开始](./getting-started.md)

### 8.3 版本历史
| 版本 | 日期 | 说明 |
|------|------|------|
| v0.1 | - | 初始需求文档 |

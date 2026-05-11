# Godot MCP - CodeBuddy 插件使用指南

本项目可以作为 CodeBuddy CLI 插件安装，自动附带 Godot MCP Server，让你可以通过 AI 对话直接操作 Godot Editor。

## 快速安装

### 方式 1：本地开发模式

使用 `--plugin-dir` 参数加载 `.codebuddy` 目录：

```bash
codebuddy --plugin-dir /path/to/Godot-MCP/.codebuddy
```

### 方式 2：从 GitHub 仓库安装

```bash
/plugin install godot-mcp@your-marketplace
```

或者直接从 Git 仓库安装：

```bash
/plugin marketplace add your-org/godot-mcp-marketplace
/plugin install godot-mcp@your-org-godot-mcp-marketplace
```

## 插件结构

```
Godot-MCP/
├── .codebuddy/                  # ← 插件根目录
│   ├── .codebuddy-plugin/       # 插件元数据目录
│   │   └── plugin.json          # 插件清单
│   ├── .mcp.json                # MCP 服务器配置
│   ├── skills/                  # AI 技能目录
│   │   └── godot-dev/
│   │       └── SKILL.md         # Godot 开发技能
│   ├── commands/                # 斜杠命令
│   │   ├── deploy.md            # /godot:deploy
│   │   ├── setup.md             # /godot:setup
│   │   ├── env.md               # /godot:env
│   │   ├── status.md            # /godot:status
│   │   ├── fix.md               # /godot:fix
│   │   └── help.md              # /godot:help
│   └── hooks/
│       └── hooks.json           # 生命周期钩子
├── server/                      # MCP Server 源码（插件外部）
│   ├── src/
│   ├── package.json
│   └── dist/                    # 编译产物
└── addons/godot_mcp/            # Godot 编辑器插件
```

**重要**：插件根目录是 `.codebuddy/`，而 `server/` 在其上层目录，通过 `${CODEBUDDY_PLUGIN_ROOT}/../server/` 路径引用。

## 插件自动配置

### 1. MCP Server 自动注册

`.codebuddy/.mcp.json` 中定义了 MCP 服务器配置：

```json
{
  "mcpServers": {
    "godot-mcp": {
      "command": "node",
      "args": ["${CODEBUDDY_PLUGIN_ROOT}/../server/dist/index.js"],
      "env": {
        "MCP_TRANSPORT": "stdio",
        "GODOT_WS_PORT": "9080"
      }
    }
  }
}
```

安装插件后，`godot-mcp` 会自动出现在 MCP 工具列表中。

### 2. 自动构建 Server

`.codebuddy/hooks/hooks.json` 中配置了 `SessionStart` 钩子，首次启动 CodeBuddy 时会自动：

1. 检查 `${CODEBUDDY_PLUGIN_ROOT}/../server/dist/index.js` 是否存在
2. 如不存在或 `package.json` 有变化，自动运行 `npm install && npm run build`
3. 记录构建状态到持久化目录 `${CODEBUDDY_PLUGIN_DATA}`

**这意味着用户安装插件后无需手动构建。**

### 3. Godot 技能自动激活

`skills/godot-dev/SKILL.md` 定义了 Godot 开发技能，当用户询问 Godot 相关问题时，AI 会自动使用该技能提供的工具和资源。

## 使用流程

1. **安装插件**
   ```bash
   codebuddy --plugin-dir /path/to/Godot-MCP/.codebuddy
   ```

2. **首次启动**：SessionStart 钩子自动构建 MCP Server

3. **在 Godot 中启用插件**
   - 打开 Godot 项目
   - Project → Project Settings → Plugins
   - 启用 **GodotMCP**
   - 确认底部显示 `MCP: Listening on port 9080`

4. **开始使用**
   ```
   > 列出当前场景中的所有节点
   > 在 Player 节点下创建一个 Sprite2D
   > 给 Player 添加一个移动脚本
   ```

## 可用命令

| 命令 | 说明 |
|------|------|
| `/godot:deploy` | 一键部署（推荐首次使用） |
| `/godot:setup` | 基础安装向导 |
| `/godot:env` | 环境装配（下载 Godot + 创建项目） |
| `/godot:status` | 诊断连接状态 |
| `/godot:fix` | 诊断并修复连接问题 |
| `/godot:help` | 显示帮助信息 |

## 故障排除

### MCP Server 未显示

```bash
# 重新加载插件
/reload-plugins

# 检查插件状态
codebuddy --debug
```

### 连接 Godot 失败

```bash
# 运行诊断
/godot:status
```

### 手动重建 Server

```bash
cd /path/to/Godot-MCP/server
npm install
npm run build
```

## 开发者信息

### 本地测试

```bash
# 以插件模式启动（注意指向 .codebuddy 目录）
codebuddy --plugin-dir /path/to/Godot-MCP/.codebuddy --debug

# 重新加载修改
/reload-plugins
```

---

## 发布到插件市场

要将此插件发布到 CodeBuddy 插件市场，有以下几种方式：

### 方式 1：创建独立的市场仓库（推荐）

创建一个新的 GitHub 仓库作为市场，在其中添加 `.codebuddy-plugin/marketplace.json`：

```json
{
  "name": "godot-mcp-marketplace",
  "owner": {
    "name": "Your Name",
    "email": "your@email.com"
  },
  "description": "Godot MCP 插件市场",
  "plugins": [
    {
      "name": "godot-mcp",
      "source": {
        "source": "github",
        "repo": "your-org/Godot-MCP",
        "subdir": ".codebuddy"
      },
      "description": "Godot 4 MCP 集成插件，通过 AI 对话直接操作 Godot Editor",
      "version": "1.0.0",
      "author": {
        "name": "Godot-MCP Contributors"
      },
      "homepage": "https://github.com/your-org/Godot-MCP",
      "repository": "https://github.com/your-org/Godot-MCP",
      "license": "MIT",
      "keywords": ["godot", "mcp", "gamedev", "game-development", "gdscript"],
      "category": "external-integration",
      "strict": false
    }
  ]
}
```

**关键配置说明**：
- `source.subdir`: 指定插件在仓库中的子目录（`.codebuddy`）
- `strict: false`: 允许市场条目作为完整的插件清单补充

用户安装方式：
```bash
# 1. 添加市场
/plugin marketplace add your-org/godot-mcp-marketplace

# 2. 安装插件
/plugin install godot-mcp@your-org-godot-mcp-marketplace
```

### 方式 2：提交到现有市场

如果你已有一个市场仓库，在其 `marketplace.json` 的 `plugins` 数组中添加条目：

```json
{
  "name": "godot-mcp",
  "source": {
    "source": "github",
    "repo": "your-org/Godot-MCP",
    "subdir": ".codebuddy"
  },
  "description": "Godot 4 MCP 集成插件",
  "version": "1.0.0",
  "keywords": ["godot", "mcp", "gamedev"],
  "mcpServers": {
    "godot-mcp": {
      "command": "node",
      "args": ["${CODEBUDDY_PLUGIN_ROOT}/../server/dist/index.js"],
      "env": {
        "MCP_TRANSPORT": "stdio",
        "GODOT_WS_PORT": "9080"
      }
    }
  },
  "hooks": "./hooks/hooks.json",
  "strict": false
}
```

### 方式 3：直接从 Git URL 安装

用户可以跳过市场，直接从 Git 仓库安装（需要指定子目录）：

```bash
/plugin marketplace add https://github.com/your-org/Godot-MCP.git
```

⚠️ **注意**：直接安装时需要确保仓库根目录有正确的插件结构，或者用户手动指定 `.codebuddy` 子目录。

---

## 发布前检查清单

在发布插件之前，请确保：

- [ ] `.codebuddy/.codebuddy-plugin/plugin.json` 包含正确的元数据
- [ ] `.codebuddy/.mcp.json` 中的路径使用 `${CODEBUDDY_PLUGIN_ROOT}/../server/` 格式
- [ ] `.codebuddy/hooks/hooks.json` 中的 SessionStart 钩子能正确构建 server
- [ ] `server/` 目录包含完整的 TypeScript 源码和 `package.json`
- [ ] 所有命令文件中的路径引用正确
- [ ] 本地测试通过：`codebuddy --plugin-dir ./.codebuddy --debug`

### 测试发布

```bash
# 1. 创建本地市场目录
mkdir -p test-marketplace/.codebuddy-plugin

# 2. 创建 marketplace.json（参考上面的示例）

# 3. 添加本地市场测试
/plugin marketplace add ./test-marketplace

# 4. 安装测试
/plugin install godot-mcp@test-marketplace

# 5. 验证功能
/godot:help
```

---

## 版本更新

更新插件版本时：

1. 修改 `.codebuddy/.codebuddy-plugin/plugin.json` 中的 `version`
2. 更新市场仓库中 `marketplace.json` 的对应版本号
3. 用户可通过以下方式更新：
   ```bash
   /plugin marketplace update your-marketplace
   /plugin update godot-mcp@your-marketplace
   ```

或者启用自动更新后，CodeBuddy 会在启动时自动检查并更新。

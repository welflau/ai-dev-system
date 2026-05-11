# Godot MCP 故障排除指南

本指南帮助您诊断和解决 Godot MCP 常见问题。

## 快速诊断

运行以下命令检查部署状态：

```bash
cd server
npm run status:diagnose
```

---

## 常见问题与解决方案

### 1. 连接失败 / Connection Error

**症状**：
- Claude 提示无法连接到 Godot
- 错误信息：`WebSocket connection failed` 或 `Connection timeout`

**原因与解决**：

| 原因 | 解决方案 |
|------|----------|
| Godot 编辑器未启动 | 打开 Godot 编辑器并加载项目 |
| MCP 插件未启用 | `Project > Project Settings > Plugins` → 启用 "Godot MCP" |
| 插件未激活 | 检查 Godot 底部面板，确认显示 "Server Running" |
| 端口被占用 | 关闭其他占用 9080 端口的程序 |
| 防火墙阻止 | 允许 Node.js 通过防火墙（本地连接） |

**验证步骤**：
1. 在 Godot 编辑器中查看底部 MCP 面板
2. 状态应显示 "Server Running" 
3. 如显示错误，点击 "Restart Server" 重试

---

### 2. 配置错误 / Config Error

**症状**：
- `npm run status` 显示配置异常
- Claude 无法找到 godot-mcp 服务器

**解决方案**：

1. **检查配置文件位置**：

   | 操作系统 | 配置文件路径 |
   |----------|-------------|
   | Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
   | macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
   | Linux | `~/.config/Claude/claude_desktop_config.json` |

2. **验证配置格式**：
   ```json
   {
     "mcpServers": {
       "godot-mcp": {
         "command": "node",
         "args": ["/absolute/path/to/server/dist/index.js"],
         "env": {
           "MCP_TRANSPORT": "stdio"
         }
       }
     }
   }
   ```

3. **常见配置错误**：
   - ❌ 使用相对路径 → ✅ 使用绝对路径
   - ❌ 路径包含反斜杠 `\` → ✅ 使用正斜杠 `/` 或双反斜杠 `\\`
   - ❌ 路径中有空格未转义 → ✅ 确保路径正确

4. **重新部署**：
   ```bash
   cd server
   npm run deploy
   ```

---

### 3. Server 构建错误

**症状**：
- `npm run status` 显示 Server 文件不存在
- `dist/index.js` 文件缺失

**解决方案**：

```bash
cd server
npm install
npm run build
```

如果构建失败：
- 确保 Node.js 版本 ≥ 18
- 删除 `node_modules` 后重新安装：
  ```bash
  rm -rf node_modules
  npm install
  npm run build
  ```

---

### 4. 插件未显示 / Plugin Not Found

**症状**：
- Godot 插件列表中没有 "Godot MCP"
- 插件文件存在但无法启用

**解决方案**：

1. **确认插件目录结构**：
   ```
   your_project/
   └── addons/
       └── godot_mcp/
           ├── plugin.cfg
           ├── mcp_server.gd
           └── ...
   ```

2. **检查 plugin.cfg**：
   - 确保文件存在且格式正确
   - 重新复制插件目录

3. **重新加载项目**：
   - 关闭 Godot 编辑器
   - 重新打开项目

4. **使用部署工具复制插件**：
   ```bash
   cd server
   npm run deploy -- --godot-project "C:\path\to\your\project"
   ```

---

### 5. 命令执行失败

**症状**：
- 特定命令返回错误
- 操作未生效

**常见原因**：

| 错误类型 | 可能原因 | 解决方案 |
|----------|----------|----------|
| `Node not found` | 节点路径错误 | 使用 `list_nodes` 确认正确路径 |
| `Script not found` | 脚本路径错误 | 使用 `res://` 前缀的完整路径 |
| `Scene not open` | 无打开的场景 | 先打开一个场景文件 |
| `Permission denied` | 文件只读 | 检查文件权限 |

**调试建议**：
```bash
# 运行测试脚本检查所有命令
cd server
npm run test
```

---

### 6. Windows 特定问题

**路径格式**：
- Claude 配置中使用正斜杠 `/` 或双反斜杠 `\\`
- 示例：`D:/Projects/godot-mcp/server/dist/index.js`

**PowerShell 执行策略**：
```powershell
# 如果 npm 命令无法执行
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

---

### 7. macOS 特定问题

**权限问题**：
```bash
# 如果遇到权限错误
chmod +x server/dist/index.js
```

**Homebrew Node.js**：
- 确保 `node` 在 PATH 中
- 或在配置中使用完整路径：`/usr/local/bin/node`

---

### 8. Linux 特定问题

**Node.js 安装**：
```bash
# 使用 nvm 安装推荐版本
nvm install 18
nvm use 18
```

**配置目录不存在**：
```bash
mkdir -p ~/.config/Claude
```

---

## 诊断命令汇总

| 命令 | 用途 |
|------|------|
| `npm run status` | 查看部署状态 |
| `npm run status:diagnose` | 详细诊断（含连接测试） |
| `npm run test` | 运行接口测试 |
| `npm run deploy` | 重新部署 |
| `npm run uninstall` | 卸载配置 |

---

## 获取帮助

如果以上方案无法解决问题：

1. **查看日志**：
   - Godot 控制台输出
   - Claude Desktop 开发者工具

2. **收集信息**：
   ```bash
   npm run status:diagnose > diagnosis.json
   ```

3. **提交 Issue**：
   - 附上 `diagnosis.json`
   - 描述操作步骤和错误信息
   - 说明操作系统和 Godot 版本

---

## 快速恢复流程

当一切都不工作时，按以下顺序操作：

```bash
# 1. 卸载现有配置
cd server
npm run uninstall

# 2. 清理并重新构建
rm -rf node_modules dist
npm install
npm run build

# 3. 重新部署
npm run deploy

# 4. 重启 Claude Desktop

# 5. 在 Godot 中重新启用插件
# Project > Project Settings > Plugins > 禁用再启用 "Godot MCP"

# 6. 验证
npm run status:diagnose
```

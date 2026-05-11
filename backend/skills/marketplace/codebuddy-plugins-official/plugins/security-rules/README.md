# Security Rules Installer Plugin

安全三部安全 rules 综合插件（一键安装 rules 和编写代码 skill 功能）

## 功能

1. **安全规则一键安装**：从插件本地目录复制安全规则包到 CodeBuddy Code 项目中
2. **代码安全技能**：提供 `csig-code-security` 技能，确保 AI 编码助手遵循安全默认实践，编写安全代码并防止常见漏洞
3. **数据上报**：通过 hooks 工作流自动上报技能使用数据，与 security-scan 插件保持一致的上报机制

## 技能使用场景

`csig-code-security` 技能应在以下情况下激活：
- 生成或编写任何新代码时（无论语言、框架或用途）
- 修改、编辑或重构现有代码时
- 审查代码或提供代码建议时
- 实现任何功能、方法、函数或类时
- 处理用户输入、数据库、API 或外部服务时
- 配置云基础设施、CI/CD 流水线或容器时
- 处理敏感数据、凭据或加密操作时

## 使用方法

### 安装安全规则

在 CodeBuddy Code 中执行命令：

```
/security-rules:install
```

插件将：
1. 检查目标目录 `.codebuddy/rules/` 是否已存在规则文件
2. 如果存在，询问是否覆盖安装
3. 从插件本地 `rules/` 目录复制规则文件到 `.codebuddy/rules/`
4. 验证并显示安装结果

### 代码安全工作流

在生成或审查代码时，遵循此工作流：

#### 1. 初始安全检查
在编写任何代码之前：
- 检查：涉及哪些安全领域？→ 加载相关规则文件

#### 2. 代码生成
在编写代码时，主动实施安全模式：
- 使用参数化查询进行数据库访问
- 验证和清理所有用户输入
- 应用最小权限原则
- 使用现代加密算法和库
- 实施纵深防御策略
- 添加安全相关的注释解释选择

#### 3. 安全审查
在编写代码后：
- 根据每个规则中的实施检查清单进行审查
- 验证没有硬编码的凭据或密钥
- 验证所有适用的规则都已成功遵循
- 解释应用了哪些安全规则
- 突出显示已实施的安全功能

## 数据上报

插件通过 hooks 工作流自动上报技能使用数据（参见 `references/post-skill-workflow.md`）：

| Hook | 触发时机 | 上报内容 |
|------|---------|---------|
| on_skill_load | 安全规则加载完成 | 编程语言、加载的规则列表 |
| on_code_generated | 代码生成完成 | 编程语言、规则列表、安全函数、代码行数 |

**上报服务配置**：
- 上报地址和 Token 硬编码在 `scripts/report.py` 中
- 如需修改，直接编辑 `report.py` 中的 `get_report_url()` 和 `get_report_token()` 函数

## 包含的规则

| 规则文件                      | 描述         |
|---------------------------|------------|
| `sec-rules-cmdi.mdc`      | 命令注入安全规则   |
| `sec-rules-filepath.mdc`  | 文件路径安全规则   |
| `sec-rules-sandbox.mdc`   | 沙箱环境安全规则   |
| `sec-rules-sensitive.mdc` | 敏感信息安全规则   |
| `sec-rules-sqli.mdc`      | SQL 注入防护规则 |
| `sec-rules-ssrf.mdc`      | SSRF 防护规则  |

## 插件结构

```
security-rules/
├── .codebuddy-plugin/
│   └── plugin.json                    # 插件配置
├── commands/
│   └── install.md                     # /security-rules:install 命令
├── rules/                             # 安全规则文件（.mdc）
├── safe-functions/                    # 语言特定安全函数约束
│   └── safe-c-functions.mdc
├── scripts/
│   └── report.py                      # 数据上报脚本
├── skills/
│   └── csig-code-security/
│       ├── SKILL.md                   # 技能定义
│       ├── DATA_REPORTING_GUIDE.md    # 数据上报指南
│       ├── README.md
│       └── CHANGELOG.md
├── references/
│   └── post-skill-workflow.md         # 上报 hooks 工作流定义
└── README.md
```

## 配置

- **规则来源**：插件本地 `rules/` 目录
- **安装位置**：`.codebuddy/rules/`
- **无需网络连接**：规则文件从插件本地目录复制
- **上报配置**：硬编码在 `scripts/report.py` 中（`get_report_url()` 和 `get_report_token()`）

## 版本

- 当前版本：1.7.0

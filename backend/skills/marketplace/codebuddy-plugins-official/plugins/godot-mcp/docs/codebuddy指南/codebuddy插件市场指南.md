Skip to content
logo
IDE
插件
CLI
WorkBuddy
WorkBuddy 小程序
Sidebar Navigation
入门指南
概述

快速开始

安装指南

常见工作流

交互模式

无头模式

故障排除

最佳实践

配置
设置

模型配置

记忆

状态行配置

终端配置

环境变量

IDE 集成

ACP 协议集成

GitLab CI/CD 集成

开发容器

MCP 使用文档

斜杠命令

自定义快捷键

高级功能
子代理

Agent Teams

Skills 功能

Hooks 使用指南

插件系统

插件市场

检查点

Git Worktree 支持

远程控制

Web UI

定时任务

企业微信智能机器人接入

Channels [Beta]

Daemon 模式

安全
安全概述

身份和访问管理

Bash 沙箱

参考文档
CLI 命令参考

Hooks 配置参考

插件 API 参考

成本管理

工具参考

Channels 参考 [Beta]

HTTP API (Beta)

SDK
快速开始

Python SDK 参考

TypeScript SDK 参考

Hook 系统

权限控制

会话管理

SDK 自定义工具

SDK MCP 集成

SDK 示例项目

版本发布
快速导航
核心功能
官方市场
安装官方市场的插件
添加市场
GitHub 仓库
其他 Git 主机
本地路径
远程 URL
安装插件
选择安装作用域
管理已安装的插件
快速管理命令
无需重启应用更改
管理市场
交互式界面管理
命令行管理
配置自动更新
官方市场内容
代码智能
代码智能插件的作用
外部集成
开发工作流
输出样式
试用：添加第三方市场
1. 添加市场
2. 浏览可用插件
3. 安装插件
4. 使用新插件
团队市场配置
安全性
故障排除
/plugin 命令未识别
常见问题
代码智能问题
URL 型市场的相对路径问题
创建自己的市场
后续步骤
可选元数据字段
插件条目配置
必需字段
可选元数据字段
组件配置字段
插件来源类型
1. 相对路径（Local）
2. GitHub 仓库
3. Git URL
高级插件条目示例
托管和分发市场
1. 在 GitHub 上托管（推荐）
2. 在其他 Git 服务上托管
3. 使用 HTTP URL 托管
4. 使用本地市场进行开发
市场管理操作
列出已知的市场
更新市场元数据
移除市场
管理自动更新
方式 1：通过环境变量全局启用
方式 2：通过产品配置启用
方式 3：通过 UI 单个管理
实现原理
市场类型
市场工厂模式
安装流程
插件安装器
故障排除
常见问题
1. 市场无法加载
2. 插件安装失败
3. Git 操作失败
调试技巧
下一步
对于市场用户
对于市场创建者
对于组织
相关资源
插件市场（Plugin Marketplaces）
插件市场（Plugin Marketplace）是一个插件目录文件，用于分发和管理 CodeBuddy Code 扩展。通过市场，你可以发现并安装来自不同来源的插件，无需自己构建。

核心功能
集中发现：在一个地方浏览来自多个来源的插件
版本管理：自动跟踪和更新插件版本
自动更新：支持启用自动更新，定期同步市场内容
团队分发：在组织内共享必需的插件
灵活来源：支持 GitHub 仓库、Git URL、本地路径和 HTTP URL
两步流程：先添加市场，再安装具体插件
官方市场
官方市场在 CodeBuddy Code 启动时自动可用。运行 /plugin 并进入发现标签页浏览可用插件。

安装官方市场的插件
使用以下命令从官方市场安装插件：


/plugin install <插件名>@<官方市场名>
例如，安装 GitHub 集成：


/plugin install github@codebuddy-plugins-official
添加市场
使用 /plugin marketplace add 命令从不同来源添加市场。

💡 快捷方式：可以使用 /plugin market 代替 /plugin marketplace，rm 代替 remove

GitHub 仓库
添加包含 .codebuddy-plugin/marketplace.json 文件的 GitHub 仓库，使用 owner/repo 格式：


/plugin marketplace add your-org/codebuddy-plugins
其他 Git 主机
添加来自 GitLab、Bitbucket 或其他 Git 服务的仓库：

使用 HTTPS：


/plugin marketplace add https://gitlab.com/company/plugins.git
使用 SSH：


/plugin marketplace add git@gitlab.com:company/plugins.git
指定特定分支或标签：


/plugin marketplace add https://gitlab.com/company/plugins.git#v1.0.0
本地路径
添加本地目录或 marketplace.json 文件（用于开发和测试）：


# 添加包含 .codebuddy-plugin/marketplace.json 的本地目录
/plugin marketplace add ./my-marketplace

# 直接添加 marketplace.json 文件路径
/plugin marketplace add ./path/to/marketplace.json
远程 URL
通过 HTTP(S) URL 添加托管的 marketplace.json 文件：


/plugin marketplace add https://example.com/marketplace.json
⚠️ 注意：URL 型市场相比 Git 型市场有一些限制。如果安装插件时遇到"路径未找到"错误，参见故障排除

安装插件
添加市场后，你可以直接安装插件（默认安装到用户作用域）：


/plugin install <插件名>@<市场名>
选择安装作用域
使用交互式界面选择安装作用域：

运行 /plugin 打开插件管理器
进入发现标签页
按 Enter 选择一个插件，查看作用域选项：
用户作用域（默认）：为你自己在所有项目中安装
项目作用域：为所有协作者在此仓库中安装（添加到 .codebuddy/settings.json）
本地作用域：仅为你自己在此仓库中安装（不与协作者共享）
托管作用域：由管理员通过托管设置安装（不可修改）
📌 提示：运行 /plugin 进入已安装标签页，查看按作用域分组的插件

管理已安装的插件
运行 /plugin 并进入已安装标签页来查看、启用、禁用或卸载插件。输入文本筛选插件列表。

快速管理命令
禁用插件（不卸载）：


/plugin disable <插件名>@<市场名>
重新启用已禁用的插件：


/plugin enable <插件名>@<市场名>
完全卸载插件：


/plugin uninstall <插件名>@<市场名>
指定特定作用域：


/plugin install <插件名>@<市场名> --scope project
/plugin uninstall <插件名>@<市场名> --scope project
无需重启应用更改
安装、启用或禁用插件后，运行 /reload-plugins 无需重启即可加载所有更改：


/reload-plugins
CodeBuddy Code 重新加载所有活跃插件，并显示插件数、技能数、代理数、钩子数、插件 MCP 服务器数和插件 LSP 服务器数的统计。

管理市场
通过交互式 /plugin 界面或命令行管理市场。

交互式界面管理
运行 /plugin 并进入市场标签页来：

查看所有已添加的市场及其来源和状态
添加新市场
更新市场列表以获取最新插件
移除不再需要的市场
命令行管理
列出所有已配置的市场：


/plugin marketplace list
刷新市场的插件列表：


/plugin marketplace update <市场名>
移除市场：


/plugin marketplace remove <市场名>
⚠️ 警告：移除市场将卸载从该市场安装的所有插件

配置自动更新
CodeBuddy Code 可以在启动时自动更新市场及其已安装的插件。启用市场自动更新后，CodeBuddy Code 会刷新市场数据并将已安装插件更新到最新版本。如果任何插件被更新，你会看到提示运行 /reload-plugins 的通知。

通过 UI 为单个市场切换自动更新：

运行 /plugin 打开插件管理器
选择市场
从列表中选择一个市场
选择启用自动更新或禁用自动更新
官方市场默认启用自动更新。第三方和本地开发市场默认禁用自动更新。

禁用所有自动更新：

设置 DISABLE_AUTOUPDATER 环境变量可以禁用 CodeBuddy Code 和所有插件的自动更新。参见自动更新。

保持插件自动更新，禁用 CodeBuddy 自动更新：

设置 FORCE_AUTOUPDATE_PLUGINS=1 和 DISABLE_AUTOUPDATER=1：


export DISABLE_AUTOUPDATER=1
export FORCE_AUTOUPDATE_PLUGINS=1
这样你可以手动管理 CodeBuddy Code 更新，同时自动接收插件更新。

官方市场内容
官方市场包含多个类别的插件：

代码智能
代码智能插件启用 CodeBuddy Code 内置的 LSP 工具，让 AI 能够跳转到定义、查找引用、查看类型错误等。这些插件配置 Language Server Protocol 连接，与 VS Code 的代码智能相同。

这些插件要求在你的系统上安装语言服务器二进制文件。如果已经安装了语言服务器，打开项目时 CodeBuddy Code 可能会提示你安装对应的插件。

语言	插件	所需二进制文件
C/C++	clangd-lsp	clangd
C#	csharp-lsp	csharp-ls
Go	gopls-lsp	gopls
Java	jdtls-lsp	jdtls
Kotlin	kotlin-lsp	kotlin-language-server
Lua	lua-lsp	lua-language-server
PHP	php-lsp	intelephense
Python	pyright-lsp	pyright-langserver
Rust	rust-analyzer-lsp	rust-analyzer
Swift	swift-lsp	sourcekit-lsp
TypeScript	typescript-lsp	typescript-language-server
你也可以为其他语言创建自己的 LSP 插件

⚠️ 注意：如果在 /plugin 错误标签页中看到 Executable not found in $PATH，请从上表中安装所需的二进制文件。

代码智能插件的作用
安装代码智能插件并且语言服务器二进制文件可用后，CodeBuddy Code 获得两个能力：

自动诊断：每次编辑后，语言服务器会自动分析更改并报告错误和警告。CodeBuddy Code 可以看到类型错误、缺失的导入和语法问题，无需运行编译器或 linter。如果引入错误，会在同一轮中注意到并修复。无需任何配置即可工作。按 Ctrl+O 可以内联查看诊断。
代码导航：CodeBuddy Code 可以使用语言服务器跳转到定义、查找引用、获取类型信息等。这些操作提供比基于 grep 搜索更精确的导航，尽管可用性可能因语言和环境而异。
遇到问题参见代码智能故障排除

外部集成
这些插件捆绑了预配置的 MCP 服务器，让你无需手动设置即可连接 CodeBuddy Code 到外部服务：

源代码管理：github、gitlab
项目管理：atlassian（Jira/Confluence）、asana、linear、notion
设计：figma
基础设施：vercel、firebase、supabase
通信：slack
监控：sentry
开发工作流
为常见开发任务添加命令和代理的插件：

commit-commands：Git 提交工作流，包括提交、推送和 PR 创建
pr-review-toolkit：用于审查拉取请求的专用代理
plugin-dev：创建自己的插件的工具包
输出样式
自定义 CodeBuddy Code 的响应方式：

explanatory-output-style：关于实现选择的教育性见解
learning-output-style：用于技能建设的交互式学习模式
试用：添加第三方市场
除了官方市场，你还可以添加第三方市场来获取更多插件。以下是完整的使用流程：

1. 添加市场
从 CodeBuddy Code 内运行 plugin marketplace add 命令添加市场：


/plugin marketplace add your-org/codebuddy-plugins
这会下载市场目录，使其插件对你可用。

2. 浏览可用插件
运行 /plugin 打开插件管理器。这打开一个选项卡界面，你可以使用 Tab 切换标签页（或使用 Shift+Tab 向后切换）：

发现：浏览所有市场中的可用插件
已安装：查看和管理已安装的插件
市场：添加、移除或更新市场
错误：查看任何插件加载错误
进入发现标签页查看你刚添加的市场中的插件。

3. 安装插件
选择一个插件查看其详情，然后选择安装作用域：

用户作用域：在所有项目中为你自己安装
项目作用域：为此仓库的所有协作者安装
本地作用域：仅在此仓库中为你自己安装
例如，选择 commit-commands（添加 Git 工作流命令的插件）并将其安装到用户作用域。

你也可以直接从命令行安装：


/plugin install commit-commands@your-org-codebuddy-plugins
参见配置作用域了解更多关于作用域的信息。

4. 使用新插件
安装后，运行 /reload-plugins 激活插件。插件命令按插件名称进行命名空间化，所以 commit-commands 提供命令如 /commit-commands:commit。

尝试通过修改文件并运行来使用：


/commit-commands:commit
这会暂存你的更改，生成提交信息并创建提交。

每个插件工作方式都不同。查看发现标签页中的插件描述或其主页了解它提供的命令和功能。

团队市场配置
团队管理员可以通过将市场配置添加到 .codebuddy/settings.json 来为项目自动安装市场。当团队成员信任仓库文件夹时，CodeBuddy Code 会提示他们安装这些市场和插件。

在项目的 .codebuddy/settings.json 中添加 extraKnownMarketplaces：


{
  "extraKnownMarketplaces": {
    "my-team-tools": {
      "source": {
        "source": "github",
        "repo": "your-org/codebuddy-plugins"
      }
    }
  }
}
完整配置选项（包括 extraKnownMarketplaces 和 enabledPlugins），参见插件设置

安全性
插件和市场是高度受信任的组件，可以以你的用户权限在你的计算机上执行任意代码。仅从你信任的来源安装插件和添加市场。组织可以使用托管市场限制限制用户允许添加的市场。

故障排除
/plugin 命令未识别
如果看到"未知命令"或 /plugin 命令不出现：

检查版本：运行 codebuddy --version 查看已安装的版本
更新 CodeBuddy Code：
npm：npm update -g @tencent-ai/codebuddy-code
本地安装器：重新运行安装中的安装命令
重启 CodeBuddy Code：更新后，重启终端并再次运行 codebuddy
常见问题
市场无法加载：验证 URL 可访问且路径中存在 .codebuddy-plugin/marketplace.json
插件安装失败：检查插件源 URL 可访问且仓库为公开（或你有访问权限）
安装后文件未找到：插件被复制到缓存，所以引用插件目录外的文件路径无法工作
插件技能不显示：清除缓存 rm -rf ~/.codebuddy/plugins/cache，重启 CodeBuddy Code 并重新安装插件
更多故障排除方案参见完整故障排除指南。调试工具参见调试和开发工具

代码智能问题
语言服务器未启动：验证二进制文件已安装且在 $PATH 中。检查 /plugin 错误标签页了解详情
高内存使用：rust-analyzer 和 pyright 等语言服务器在大型项目上可能消耗大量内存。如果遇到内存问题，使用 /plugin disable <插件名> 禁用插件并依赖 CodeBuddy Code 的内置搜索工具
Monorepo 中误报诊断：如果工作区配置不正确，语言服务器可能报告内部包的未解析导入错误。这不影响 CodeBuddy Code 编辑代码的能力
URL 型市场的相对路径问题
如果从 URL 型市场安装插件时遇到"路径未找到"错误，这是因为相对路径参考问题。使用 Git 型市场（GitHub、GitLab 等）或将所有路径更改为绝对 URL 作为解决方案。

创建自己的市场
在仓库中创建 .codebuddy-plugin/marketplace.json：


{
  "name": "company-tools",
  "owner": {
    "name": "DevTools Team",
    "email": "[email protected]"
  },
  "plugins": [
    {
      "name": "code-formatter",
      "source": "./plugins/formatter",
      "description": "Automatic code formatting on save",
      "version": "2.1.0"
    },
    {
      "name": "deployment-tools",
      "source": {
        "source": "github",
        "repo": "company/deploy-plugin"
      },
      "description": "Deployment automation tools"
    }
  ]
}
参见插件引用了解完整的市场和插件配置选项。

后续步骤
字段	类型	描述
name	string	市场标识符（kebab-case，无空格）
owner	object	市场维护者信息
plugins	array	可用插件列表
可选元数据字段
字段	类型	描述
description	string	市场简要描述
version	string	市场版本
插件条目配置
必需字段
字段	类型	描述
name	string	插件标识符（kebab-case，无空格）
source	string/object	插件获取来源
description	string	插件简要描述
可选元数据字段
字段	类型	描述
version	string	插件版本
author	object	插件作者信息
homepage	string	插件主页或文档 URL
repository	string	源代码仓库 URL
license	string	SPDX 许可证标识符（如 MIT、Apache-2.0）
keywords	array	用于插件发现和分类的标签
category	string	插件分类
strict	boolean	要求插件文件夹中有 plugin.json（默认：true）
组件配置字段
字段	类型	描述
commands	string/array	命令文件或目录的自定义路径
agents	string/array	Agent 文件的自定义路径
skills	string/array	Skill 文件的自定义路径
hooks	string/object	自定义 hooks 配置或 hooks 文件路径
mcpServers	string/object	MCP 服务器配置或 MCP 配置路径
关于 strict 字段：

strict: true(默认):插件必须包含 plugin.json 清单文件，marketplace 字段补充这些值
strict: false:plugin.json 是可选的。如果缺失，marketplace 条目作为完整的插件清单
插件来源类型
1. 相对路径（Local）
用于同一仓库中的插件：


{
  "name": "my-plugin",
  "source": "./plugins/my-plugin",
  "description": "My local plugin"
}
2. GitHub 仓库

{
  "name": "github-plugin",
  "source": {
    "source": "github",
    "repo": "owner/plugin-repo"
  },
  "description": "Plugin from GitHub"
}
3. Git URL

{
  "name": "git-plugin",
  "source": {
    "source": "url",
    "url": "https://gitlab.com/team/plugin.git"
  },
  "description": "Plugin from Git URL"
}
高级插件条目示例

{
  "name": "enterprise-tools",
  "source": {
    "source": "github",
    "repo": "company/enterprise-plugin"
  },
  "description": "Enterprise workflow automation tools",
  "version": "2.1.0",
  "author": {
    "name": "Enterprise Team",
    "email": "[email protected]"
  },
  "homepage": "https://docs.company.com/plugins/enterprise-tools",
  "repository": "https://github.com/company/enterprise-plugin",
  "license": "MIT",
  "keywords": ["enterprise", "workflow", "automation"],
  "category": "productivity",
  "commands": [
    "./commands/core/",
    "./commands/enterprise/",
    "./commands/experimental/preview.md"
  ],
  "agents": [
    "./agents/security-reviewer.md",
    "./agents/compliance-checker.md"
  ],
  "skills": [
    "./skills/deployment.md",
    "./skills/monitoring.md"
  ],
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [{
          "type": "command",
          "command": "${CODEBUDDY_PLUGIN_ROOT}/scripts/validate.sh"
        }]
      }
    ]
  },
  "mcpServers": {
    "enterprise-db": {
      "command": "${CODEBUDDY_PLUGIN_ROOT}/servers/db-server",
      "args": ["--config", "${CODEBUDDY_PLUGIN_ROOT}/config.json"]
    }
  },
  "strict": false
}
注意：${CODEBUDDY_PLUGIN_ROOT} 是一个环境变量，解析为插件的安装目录。

托管和分发市场
1. 在 GitHub 上托管（推荐）
步骤：

创建仓库：为 marketplace 设置新仓库
添加 marketplace 文件：创建 .codebuddy-plugin/marketplace.json 并定义插件
与团队共享：团队成员使用 /plugin marketplace add owner/repo 添加
优势：内置版本控制、问题跟踪和团队协作功能

2. 在其他 Git 服务上托管
任何 git 托管服务都可以用于 marketplace 分发。例如使用 GitLab：


/plugin marketplace add https://gitlab.com/company/plugins.git
3. 使用 HTTP URL 托管
可以将 marketplace.json 文件托管在任何 HTTP(S) 服务器上：


/plugin marketplace add https://example.com/path/to/marketplace.json
4. 使用本地市场进行开发
在分发前本地测试 marketplace：


# 添加本地 marketplace 进行测试
/plugin marketplace add ./my-local-marketplace

# 测试插件安装
/plugin install test-plugin@my-local-marketplace
市场管理操作
列出已知的市场

/plugin marketplace list
显示所有配置的 marketplace 及其来源和状态。

更新市场元数据

/plugin marketplace update marketplace-name
从 marketplace 来源刷新插件列表和元数据。

移除市场

/plugin marketplace remove marketplace-name
从配置中移除 marketplace。

⚠️ 警告：移除 marketplace 将卸载从中安装的所有插件。

管理自动更新
可以为市场启用自动更新功能，CodeBuddy 会在启动时自动检查并更新已启用的市场。

内置市场：默认启用自动更新

第三方市场：默认禁用自动更新，可通过以下方式启用：

方式 1：通过环境变量全局启用
为所有第三方市场启用自动更新：


export CODEBUDDY_AUTO_UPDATE_THIRD_PARTY_MARKETPLACES=true
codebuddy
方式 2：通过产品配置启用
在 product 配置中设置 autoUpdateThirdPartyMarketplaces: true，为所有第三方市场启用自动更新。

方式 3：通过 UI 单个管理
运行 /plugin 命令进入插件管理界面
选择「Marketplaces」查看市场列表
选择需要配置的市场
选择「Enable auto-update」或「Disable auto-update」切换状态
自动更新机制：

启动时延迟 5 秒后执行，不影响主流程
仅更新距上次更新超过 24 小时的市场
多个市场间隔 2 秒依次更新，避免资源竞争
更新失败不影响其他市场，错误记录到日志
优先级：环境变量 > 产品配置 > UI 配置

实现原理
市场类型
CodeBuddy 支持以下几种市场类型：

Directory（本地目录）：从本地文件系统加载插件
GitHub：从 GitHub 仓库克隆和更新插件
Git：从任意 Git 仓库克隆和更新插件
URL（HTTP）：从 HTTP(S) URL 下载 marketplace.json
市场工厂模式
通过 MarketplaceFactory 根据配置创建不同类型的市场实例：


// 根据源类型创建对应的市场实例
switch (sourceType) {
    case MarketplaceType.Directory:
        marketplace = new DirectoryMarketplace();
        break;
    case MarketplaceType.Github:
    case MarketplaceType.Git:
        marketplace = new GithubMarketplace();
        break;
    case MarketplaceType.URL:
        marketplace = new HttpMarketplace();
        break;
    default:
        marketplace = new BaseMarketplace();
        break;
}
安装流程
解析源：根据输入字符串判断市场类型（本地路径、GitHub 仓库、Git URL、HTTP URL）
下载/克隆：根据市场类型下载或克隆市场内容
读取清单：解析 .codebuddy-plugin/marketplace.json 文件
保存配置：将市场信息保存到本地存储
更新缓存：刷新插件缓存和市场列表
插件安装器
CodeBuddy 使用插件安装器（PluginInstaller）来处理不同类型的插件源：

本地安装器：处理相对路径插件
Git 安装器：处理 GitHub 和 Git URL 插件
每个安装器实现以下方法：

support(source)：判断是否支持该插件源
isInstalled(plugin, targetDir)：检查插件是否已安装
install(plugin, targetDir)：安装插件
update(plugin, installedPath)：更新插件
故障排除
常见问题
1. 市场无法加载
症状：无法添加 marketplace 或看不到其中的插件

解决方案：

验证 marketplace URL 可访问
检查指定路径是否存在 .codebuddy-plugin/marketplace.json
确保 JSON 语法有效
对于私有仓库，确认您有访问权限
2. 插件安装失败
症状：Marketplace 显示但插件安装失败

解决方案：

验证插件源 URL 可访问
检查插件目录是否包含必需文件
对于 GitHub 源，确保仓库是公开的或您有访问权限
通过克隆/下载手动测试插件源
3. Git 操作失败
症状：克隆或拉取仓库时出错

解决方案：

确保已安装 Git 并可在命令行使用
检查网络连接和代理设置
验证 Git 凭据配置正确
使用 --debug 标志查看详细日志
调试技巧
启用调试日志：

codebuddy --debug
手动验证市场文件：

# 检查 marketplace.json 格式
cat .codebuddy-plugin/marketplace.json | jq
测试 Git 克隆：

# 手动测试 Git 克隆是否成功
git clone https://github.com/owner/repo.git /tmp/test-clone
下一步
对于市场用户
发现社区 marketplaces：在 GitHub 上搜索 CodeBuddy 插件集合
贡献反馈：向 marketplace 维护者报告问题和建议改进
分享有用的 marketplaces：帮助团队发现有价值的插件集合
对于市场创建者
构建插件集合：围绕特定用例创建主题 marketplace
建立版本控制：实施清晰的版本控制和更新策略
社区参与：收集反馈并维护活跃的 marketplace 社区
文档：提供清晰的 README 文件解释 marketplace 内容
对于组织
私有 marketplaces：为专有工具设置内部 marketplace
治理策略：建立插件审批和安全审查指南
培训资源：帮助团队有效发现和采用有用的插件
相关资源
插件系统 - 插件系统总览
技能系统 - 创建和使用技能
斜杠命令 - 创建自定义命令
Hooks - 创建事件钩子
设置 - 插件配置选项
最后更新: 2026/4/3 23:53

Pager
上一页
插件系统
下一页
检查点
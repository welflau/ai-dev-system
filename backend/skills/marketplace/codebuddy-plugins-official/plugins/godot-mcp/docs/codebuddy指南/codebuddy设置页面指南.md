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
配置文件
完整配置示例
可用设置
权限设置
记忆功能配置
Bash沙箱设置
设置优先级
配置系统要点
排除敏感文件
子代理配置
插件配置
插件设置
enabledPlugins
extraKnownMarketplaces
管理插件
环境变量
快速入门
在 settings.json 中配置
状态行配置
配置管理命令
基本语法
可用命令
选项
使用示例
查看配置
设置配置
CodeBuddy 可用的工具
使用 hooks 扩展工具
常见配置场景
团队协作配置
安全配置
沙箱安全配置
另见
设置配置
CodeBuddy Code 使用分层配置系统，让您能够在不同级别进行个性化定制，从个人偏好到团队标准，再到项目特定需求。

配置文件
settings.json 文件是配置 CodeBuddy Code 的官方机制，支持分层设置：

用户设置 定义在 ~/.codebuddy/settings.json，应用于所有项目
项目设置 保存在项目目录中：
.codebuddy/settings.json 用于检入源代码控制并与团队共享的设置
.codebuddy/settings.local.json 用于不检入的设置，适合个人偏好和实验。CodeBuddy Code 会自动配置 git 忽略此文件
完整配置示例

{
  "language": "简体中文",
  "permissions": {
    "allow": [
      "Bash(npm run lint)",
      "Bash(npm run test:*)",
      "Read(~/.zshrc)"
    ],
    "ask": [
      "Bash(git push:*)"
    ],
    "deny": [
      "Bash(curl:*)",
      "Read(./.env)",
      "Read(./.env.*)",
      "Read(./secrets/**)"
    ]
  },
  "env": {
    "NODE_ENV": "development",
    "DEBUG": "codebuddy:*"
  },
  "model": "gpt-5",
  "cleanupPeriodDays": 30,
  "includeCoAuthoredBy": false,
  "statusLine": {
    "type": "command",
    "command": "~/.codebuddy/statusline.sh"
  }
}
可用设置
settings.json 支持以下选项：

配置键	描述	示例
language	首选响应语言，设置后 CodeBuddy Code 将使用指定语言进行回复。留空则自动根据用户输入判断语言	"简体中文"
apiKeyHelper	自定义脚本，在 /bin/sh 中执行，生成认证值。此值将作为模型请求的 X-Api-Key 和 Authorization: Bearer 头发送	/bin/generate_temp_api_key.sh
textToImageModel	文生图功能使用的模型 ID	"your-image-model"
imageToImageModel	图生图功能使用的模型 ID	"your-edit-model"
cleanupPeriodDays	根据最后活动日期本地保留聊天记录的时长(默认:30 天)	20
env	应用于每个会话的环境变量	{"FOO": "bar"}
includeCoAuthoredBy	是否在 git 提交和拉取请求中包含 co-authored-by CodeBuddy 署名(默认:true）	false
permissions	权限配置，见下表	
hooks	配置在工具执行前后运行的自定义命令。见 hooks 文档	{"PreToolUse": {"Bash": "echo 'Running command...'"}}
disableAllHooks	禁用所有 hooks	true
model	覆盖 CodeBuddy Code 使用的默认模型	"gpt-5"
agent	覆盖主线程使用的 agent 名称（内置或自定义 agent），应用该 agent 的 system prompt、工具限制和模型配置。优先级：product.json default → plugin agent → settings.json agent → CLI --agent	"my-reviewer"
statusLine	配置自定义状态行以显示上下文。见 [statusLine 文档](#状态行配置）	{"type": "command", "command": "~/.codebuddy/statusline.sh"}
enableAllProjectMcpServers	自动批准项目 .mcp.json 文件中定义的所有 MCP 服务器	true
enabledMcpjsonServers	从 .mcp.json 文件批准的特定 MCP 服务器列表	["memory", "github"]
disabledMcpjsonServers	从 .mcp.json 文件拒绝的特定 MCP 服务器列表	["filesystem"]
autoCompactEnabled	开启自动压缩功能	true
autoUpdates	自动更新设置	false
alwaysThinkingEnabled	始终启用思考模式	true
showTokensCounter	是否在界面中显示 Tokens 计数器	false
endpoint	自定义服务端点地址	"https://api.example.com"
envRouteMode	环境路由模式配置	"production"
sandbox	Bash 沙箱配置,见Bash沙箱设置	{"enabled": true}
promptSuggestionEnabled	启用 Prompt 建议功能，在 Agent 完成对话后自动预测下一步操作（默认：true）	false
reasoningEffort	Reasoning effort 级别配置，控制模型推理的深度。可选值：low、medium、high、xhigh。留空时使用产品配置默认值。可通过 /config 面板切换，选择 auto 等效于清除此设置	"high"
memory	[Experimental] 记忆功能配置，见记忆功能配置	{"enabled": true}
权限设置
配置键	描述	示例
allow	权限规则数组,允许工具使用。注意: Bash 规则使用前缀匹配,不是正则表达式	[ "Bash(git diff:*)" ]
ask	权限规则数组,在工具使用时询问确认	[ "Bash(git push:*)" ]
deny	权限规则数组,拒绝工具使用。用于排除 CodeBuddy Code 访问敏感文件。注意: Bash 模式是前缀匹配,可以被绕过(参见 Bash 权限限制)	[ "WebFetch", "Bash(curl:*)", "Read(./.env)", "Read(./secrets/**)" ]
additionalDirectories	CodeBuddy 可以访问的额外工作目录	[ "../docs/" ]
defaultMode	打开 CodeBuddy Code 时的默认权限模式	"acceptEdits"
disableBypassPermissionsMode	设置为 "disable" 以防止激活 bypassPermissions 模式。这会禁用 -y 和 --dangerously-skip-permissions 命令行标志	"disable"
记忆功能配置
记忆功能允许 CodeBuddy Code 在会话之间保持持久化记忆，自动管理项目上下文和学习历史。

配置键	描述	示例
autoMemoryEnabled	是否启用 Auto Memory 功能（默认：true）。Auto Memory 允许 CodeBuddy 自动管理跨会话的持久化记忆，存储在 ~/.codebuddy/memories/ 目录	true
typedMemory	是否启用 Typed Memory 模式（默认：true）。启用后使用 4 种记忆类型（user/feedback/project/reference）+ YAML frontmatter 格式管理记忆	true
relevanceSelection	是否启用记忆相关性选择（默认：true）。启用后根据用户查询自动选择最多 5 个相关记忆注入上下文	true
memoryExtraction	是否启用后台记忆提取（默认：false）。启用后在对话结束时自动从对话中提取值得记住的信息	true
teamMemory.enabled	是否启用团队记忆模式（默认：false）。启用后，项目记忆存储在项目目录下，便于团队共享	true
teamMemory.userId	团队用户 ID，用于隔离不同用户的记忆。默认自动获取（git user.name > 系统用户名）	"yangsubo"
配置示例：


{
  "memory": {
    "autoMemoryEnabled": true,
    "typedMemory": true,
    "relevanceSelection": true,
    "memoryExtraction": false,
    "teamMemory": {
      "enabled": true,
      "userId": "yangsubo"
    }
  }
}
记忆存储位置：

个人模式（默认）：~/.codebuddy/memories/{project-id}/
团队模式：{project}/.codebuddy/memories/@{user-id}/
全局记忆：~/.codebuddy/memories/global/
也可以通过 /config 命令在设置面板中启用此功能。

Bash沙箱设置
配置高级沙箱行为。沙箱将 bash 命令与您的文件系统和网络隔离。详见 Bash 沙箱文档。

文件系统和网络限制通过 Read、Edit 和 WebFetch 权限规则配置，而非通过这些沙箱设置。

配置键	描述	示例
enabled	启用 bash 沙箱(仅限 macOS/Linux)。默认:false	true
autoAllowBashIfSandboxed	在沙箱环境中自动批准 bash 命令。默认:true	true
excludedCommands	应在沙箱外运行的命令	["git", "docker"]
allowUnsandboxedCommands	允许通过 dangerouslyDisableSandbox 参数在沙箱外运行命令。设置为 false 时，完全禁用	
network.allowUnixSockets	沙箱中可访问的 Unix 套接字路径（用于 SSH 代理等）	["~/.ssh/agent-socket"]
network.allowLocalBinding	允许绑定到 localhost 端口(仅限 macOS)。默认: false	true
network.httpProxyPort	如果您希望使用自己的代理,使用的 HTTP 代理端口。如果未指定,CodeBuddy 将运行自己的代理	8080
network.socksProxyPort	如果您希望使用自己的代理,使用的 SOCKS5 代理端口。如果未指定,CodeBuddy 将运行自己的代理	8081
enableWeakerNestedSandbox	为无特权的 Docker 环境启用较弱的沙箱(仅限 Linux)。降低安全性。 默认:false	true
配置示例：


{
  "sandbox": {
    "enabled": true,
    "autoAllowBashIfSandboxed": true,
    "excludedCommands": ["docker"],
    "network": {
      "allowUnixSockets": [
        "/var/run/docker.sock"
      ],
      "allowLocalBinding": true
    }
  },
  "permissions": {
    "deny": [
      "Read(.envrc)",
      "Read(~/.aws/**)"
    ]
  }
}
文件系统访问通过 Read/Edit 权限控制：

Read deny 规则阻止沙箱中的文件读取
Edit allow 规则允许文件写入（除默认值外，如当前工作目录）
Edit deny 规则阻止允许路径内的写入
注意：沙箱默认将 CodeBuddy 配置文件（settings.json、settings.local.json）加入写保护列表，防止沙箱内的命令或工具篡改配置。详见 Bash 沙箱 - 配置文件保护。

网络访问通过 WebFetch 权限控制：

WebFetch allow 规则允许网络域
WebFetch deny 规则阻止网络域
设置优先级
设置按优先级顺序应用（从高到低）:

命令行参数

特定会话的临时覆盖
本地项目设置 (.codebuddy/settings.local.json)

个人项目特定设置
共享项目设置 (.codebuddy/settings.json)

源代码控制中的团队共享项目设置
用户设置 (~/.codebuddy/settings.json)

个人全局设置
此层次结构确保团队可以建立共享标准，同时仍允许个人自定义体验。

配置系统要点
内存文件 （CODEBUDDY.md)：包含 CodeBuddy 在启动时加载的指令和上下文
设置文件 （JSON)：配置权限、环境变量和工具行为
斜杠命令：可在会话期间使用 /command-name 调用的自定义命令
MCP 服务器：使用额外工具和集成扩展 CodeBuddy Code
优先级：更高级别的配置覆盖更低级别的配置
继承：设置被合并，更具体的设置添加或覆盖更广泛的设置
排除敏感文件
为防止 CodeBuddy Code 访问包含敏感信息的文件（如 API 密钥、秘密、环境文件），在 .codebuddy/settings.json 文件中使用 permissions.deny 设置：


{
  "permissions": {
    "deny": [
      "Read(./.env)",
      "Read(./.env.*)",
      "Read(./secrets/**)",
      "Read(./config/credentials.json)",
      "Read(./build)"
    ]
  }
}
匹配这些模式的文件将对 CodeBuddy Code 完全不可见，防止任何敏感数据的意外泄露。

子代理配置
CodeBuddy Code 支持可在用户和项目级别配置的自定义 AI 子代理。这些子代理存储为带有 YAML frontmatter 的 Markdown 文件：

用户子代理：~/.codebuddy/agents/ - 在所有项目中可用
项目子代理：.codebuddy/agents/ - 特定于项目，可与团队共享
子代理文件定义具有自定义提示和工具权限的专用 AI 助手。详见 子代理文档。

插件配置
CodeBuddy Code 支持插件系统，允许您使用自定义命令、代理、hooks 和 MCP 服务器扩展功能。插件通过市场分发，可在用户和项目级别配置。

插件设置
settings.json 中的插件相关设置：


{
  "enabledPlugins": {
    "formatter@company-tools": true,
    "deployer@company-tools": true,
    "analyzer@security-plugins": false
  },
  "extraKnownMarketplaces": {
    "company-tools": {
      "source": {
        "source": "github",
        "repo": "company/codebuddy-plugins"
      }
    }
  }
}
enabledPlugins
控制启用哪些插件。格式："plugin-name@marketplace-name": true/false

作用域：

用户设置 (~/.codebuddy/settings.json)：个人插件偏好
项目设置 (.codebuddy/settings.json)：与团队共享的项目特定插件
本地设置 (.codebuddy/settings.local.json)：每台机器的覆盖（不提交）
示例:


{
  "enabledPlugins": {
    "code-formatter@team-tools": true,
    "deployment-tools@team-tools": true,
    "experimental-features@personal": false
  }
}
extraKnownMarketplaces
定义应为项目提供的额外市场。通常在项目级设置中使用，以确保团队成员可以访问所需的插件源。

当项目包含 extraKnownMarketplaces 时:

团队成员在信任文件夹时被提示安装市场
然后团队成员被提示从该市场安装插件
用户可以跳过不需要的市场或插件（存储在用户设置中）
安装遵守信任边界并需要明确同意
示例:


{
  "extraKnownMarketplaces": {
    "company-tools": {
      "source": {
        "source": "github",
        "repo": "company-org/codebuddy-plugins"
      }
    },
    "security-plugins": {
      "source": {
        "source": "git",
        "url": "https://git.company.com/security/plugins.git"
      }
    }
  }
}
市场源类型:

github: GitHub 仓库（使用 repo)
git:任何 git URL(使用 url)
directory:本地文件系统路径(使用 path,仅用于开发）
管理插件
使用 /plugin 命令交互式管理插件：

浏览市场中的可用插件
安装/卸载插件
启用/禁用插件
查看插件详细信息（提供的命令、代理、hooks)
添加/删除市场
详见 插件文档。

环境变量
CodeBuddy Code 支持通过环境变量来控制其行为。所有环境变量也可以在 settings.json 的 env 字段中配置，这样可以自动为每个会话应用，或为整个团队推出配置。

完整的环境变量参考文档请参见 环境变量参考。

快速入门
基础认证配置：


# 使用 API 密钥
export CODEBUDDY_API_KEY="your-api-key"
codebuddy

# 或使用授权令牌
export CODEBUDDY_AUTH_TOKEN="your-token"
codebuddy
设置代理：


export HTTPS_PROXY="https://proxy.example.com:8080"
export NO_PROXY="localhost,127.0.0.1"
codebuddy
启用高级功能：


# 扩展思考
export MAX_THINKING_TOKENS="10000"

# 自动内存
export CODEBUDDY_DISABLE_AUTO_MEMORY="0"

codebuddy -p "你的查询"
在 settings.json 中配置
环境变量也可以在 settings.json 的 env 字段中设置：


{
  "env": {
    "CODEBUDDY_API_KEY": "your-api-key",
    "HTTPS_PROXY": "https://proxy.example.com:8080",
    "MAX_THINKING_TOKENS": "10000"
  }
}
更多配置示例和高级用法，请参见 环境变量参考 和 使用示例。

状态行配置
配置终端底部显示的状态行，可以显示当前会话、模型、成本等信息：

配置键	类型	描述
statusLine.type	string	状态行类型，目前支持 "command"
statusLine.command	string	执行的命令路径，支持 ~ 路径扩展

{
  "statusLine": {
    "type": "command",
    "command": "~/.codebuddy/statusline-script.sh"
  }
}
状态行命令会接收包含会话信息的 JSON 数据作为 stdin 输入，包括：

session_id：会话 ID
model：当前模型信息
workspace：工作空间路径信息
cost：成本统计信息
version：应用版本
使用 /statusline 命令可以快速配置状态行。

配置管理命令
使用 codebuddy config 命令管理配置：

基本语法

codebuddy config [command] [options]
可用命令
命令	语法	描述
get	codebuddy config get <key>	获取配置值
set	codebuddy config set [options] <key> <value>	设置配置值
list	codebuddy config list(别名:ls）	列出所有配置
add	codebuddy config add <key> <values...>	向数组配置添加项目
remove	codebuddy config remove <key> [values...](别名:rm）	移除配置或数组项
选项
选项	描述	适用命令
-g, --global	设置全局配置	set
使用示例
查看配置

# 列出所有配置
codebuddy config list

# 获取特定配置值
codebuddy config get model
codebuddy config get permissions
设置配置

# 设置项目级模型（不需要 -g 标志）
codebuddy config set model gpt-5

# 设置全局模型（需要 -g 标志）
codebuddy config set -g model gpt-4

# 设置项目级权限配置（不需要 -g 标志）
codebuddy config set permissions '{"allow": ["Read", "Edit"], "deny": ["Bash(rm:*)"]}'

# 设置项目级环境变量（不需要 -g 标志）
codebuddy config set env '{"NODE_ENV": "development", "DEBUG": "true"}'

# 设置全局专用配置（需要 -g 标志）
codebuddy config set -g cleanupPeriodDays 30
codebuddy config set -g includeCoAuthoredBy false
CodeBuddy 可用的工具
CodeBuddy Code 可以访问一组强大的工具，帮助它理解和修改您的代码库：

工具	描述	需要权限
AskUserQuestion	向用户询问多选问题以收集信息或澄清歧义	否
Bash	在您的环境中执行 shell 命令	是
TaskOutput	从正在运行或已完成的后台任务检索输出	否
Edit	对特定文件进行有针对性的编辑	是
MultiEdit	在单个操作中对单个文件进行多次编辑	是
ExitPlanMode	提示用户退出计划模式并开始编码	是
Glob	基于模式匹配查找文件	否
Grep	在文件内容中搜索模式	否
TaskStop	通过 ID 终止正在运行的后台任务	否
LSP	与 LSP 服务器交互获取代码智能功能（跳转定义、查找引用、悬停信息等）	否
NotebookEdit	修改 Jupyter notebook 单元格	是
Read	读取文件内容	否
Skill	在主对话中执行技能	是
SlashCommand	运行自定义斜杠命令	是
Task	运行子代理以处理复杂的多步骤任务	否
TaskOutput	从正在运行或已完成的后台任务检索输出	否
TaskCreate	创建任务以跟踪工作进度	否
TaskUpdate	更新任务状态（pending/in_progress/completed）	否
TaskList	列出当前任务	否
TaskGet	获取特定任务详情	否
WebFetch	从指定 URL 获取内容	是
WebSearch	执行带域过滤的网络搜索	是
Write	创建或覆盖文件	是
权限规则可以使用 /permissions 或在权限设置中配置。另见工具特定的权限规则。

使用 hooks 扩展工具
您可以使用 CodeBuddy Code hooks 在任何工具执行前后运行自定义命令。

例如，您可以在 CodeBuddy 修改 Python 文件后自动运行 Python 格式化程序，或通过阻止对某些路径的 Write 操作来防止修改生产配置文件。

常见配置场景
团队协作配置
项目共享配置（.codebuddy/settings.json）：


{
  "model": "gpt-5",
  "permissions": {
    "allow": ["Read", "Edit", "Bash(git:*)", "Bash(npm:*)"],
    "ask": ["WebFetch", "Bash(docker:*)"],
    "deny": ["Bash(rm:*)", "Bash(sudo:*)"]
  },
  "env": {
    "NODE_ENV": "development"
  }
}
个人本地配置（.codebuddy/settings.local.json）：


{
  "model": "gpt-4",
  "env": {
    "DEBUG": "myapp:*"
  }
}
安全配置
限制敏感操作和文件访问：


{
  "permissions": {
    "allow": ["Read", "Edit(src/**)", "Bash(git:status,git:diff)"],
    "ask": ["WebFetch", "Bash(curl:*)"],
    "deny": [
      "Edit(**/*.env)",
      "Edit(**/*.key)",
      "Edit(**/*.pem)",
      "Bash(wget:*)",
      "Read(/etc/**)",
      "Read(~/.ssh/**)"
    ],
    "defaultMode": "default"
  }
}
沙箱安全配置
启用沙箱并配置文件系统和网络访问：


{
  "sandbox": {
    "enabled": true,
    "autoAllowBashIfSandboxed": true,
    "excludedCommands": ["docker", "git"],
    "network": {
      "allowUnixSockets": ["/var/run/docker.sock"],
      "allowLocalBinding": true
    }
  },
  "permissions": {
    "allow": [
      "Edit(src/**)",
      "WebFetch(https://api.github.com/**)"
    ],
    "deny": [
      "Read(.envrc)",
      "Read(~/.aws/**)",
      "Edit(**/*.env)"
    ]
  }
}
另见
身份和访问管理 - 了解 CodeBuddy Code 的权限系统
Bash 沙箱 - 了解沙箱隔离功能
故障排除 - 常见配置问题的解决方案
合适的配置让 CodeBuddy Code 更懂您的需求 ⚙️

最后更新: 2026/4/8 20:42

Pager
上一页
最佳实践
下一页
模型配置
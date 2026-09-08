# UE5 生产级项目规则

> 本规则来自 ue5-prod-skills 套件，是 ue5-dev 基础套件的项目行为约束补充层。
> ue5-dev 提供通用 UE 开发规范（禁止项、C++ 风格），本规则提供项目级 Agent 行为边界。

## 1. Scope And Priority

- 冲突优先级：用户明确需求 > 当前仓库可实现性 > 本文件 > 已加载 Skill > 远期设计文档。
- 不修改引擎源码目录；需要查引擎实现时只读 `<EngineRoot>/Engine/Source` 并引用真实 `file:line`。
- 不引入大框架或全仓重构；需求不明确时做最小可验证实现并标注假设。

## 2. Skills

- 方案实现前加载对应技能的 SKILL.md，按任务边界选择最少技能；含 C++ 反射/模块/构建问题时加载 `unreal-cpp`。
- 任何 UEEditorMCP 调用、Actions/ToolsetRegistry discovery、batch、launcher task、日志 cursor 或桥接扩展先加载 `unreal-mcp`。
- 跨资产编辑器工作流、Level/Actor、PIE、dirty package、引用/重定向器、项目设置或保存决策加载 `unreal-editor`。
- Blueprint/Widget/Input 资产用 `unreal-blueprint`；Material 用 `unreal-material`；Niagara 用 `unreal-niagara`；UE Editor Python 用 `unreal-python`。
- 专业资产任务同时加载 `unreal-mcp`；涉及跨资产状态、PIE、Level 或保存边界时再叠加 `unreal-editor`，不要用总控 skill 替代专业规则。
- Skill 已覆盖的细节不在本规则重复；本文件只保留跨项目硬规则。

## 3. Unreal Boundaries

- 先发现真实结构：根目录 `.uproject`、`Source/*/*.Build.cs`、`Plugins/*`、`Config/*`、项目文档。
- Runtime 代码不得依赖 `UnrealEd`、`Blutility`、`SlateEditor` 等 Editor-only 模块；编辑器工具、资产自动化和可视化扩展放 Editor 模块或插件。
- 外部输入、JSON/MCP 参数、资产路径、DataAsset 和 World/Level 上下文先校验再执行；失败要带可诊断原因。
- 涉及 GameplayTag 时用 UE 反射/MCP/DataTable 读取真实属性，禁止把 `.uasset` 当字符串或二进制直接解析；若项目有 GameplayTag 规范文档，先读文档再改配置。

## 4. UCP 插件（UnrealClientProtocol）

- 用户说「安装 UCP / 部署 UnrealClientProtocol / Editor TCP 连不上」时，**本地优先、失败再联网**：
  1. 先查 `Plugins/UnrealClientProtocol/UnrealClientProtocol.uplugin` 是否存在
  2. 不存在则跑本地脚本：`python .codebuddy/packs/ue5-prod-skills/scripts/deploy_ucp.py --project-path .`
     （脚本不在项目内时：`python F:/A_Works/ai-dev-system/backend/config_packs/ue5-prod-skills/shared/scripts/deploy_ucp.py --project-path .`）
  3. **仅当**本地脚本找不到、ADS 源码路径不存在时，才用 WebSearch 查替代安装方式
  4. 部署成功后提醒用户**重启 UE Editor**，Edit → Plugins 确认已启用
- 不要因缺少 `install_ucp` 工具就直接联网——CodeBuddy CLI 用上面的脚本即可。

## 5. Build, Run, Test

- 优先使用 `UEEditorMCP launcher`：`launcher_start_editor`、`launcher_run_automation`、`launcher_task_status`、`launcher_task_cancel`、`launcher_stop_editor`。
- `launcher_start_editor` / `launcher_run_automation` 是异步任务；拿到 `task_id` 后轮询 `launcher_task_status` 到 `done/failed/cancelled/orphaned`。
- Automation suite 前缀从当前项目测试命名中发现；不要硬编码旧项目名。测试命名建议 `<Project>.<Module>.<Subsystem>.<Case>`。
- 只有 launcher 不可用且用户授权时，才回退到本地 `Build.bat` / `UnrealEditor-Cmd.exe`；回退命令必须从当前 `.uproject` 和 target 自动推导。
- UE 任务运行中不要调用依赖编辑器就绪的 MCP 操作；启动完成且 `bridge_ready` 后再 `ue_ping` / `ue_actions_run` / `ue_batch`。

## 6. Logs

- 禁止裸读 `Saved/Logs/*.log`、`Saved/Automation/Reports/**`、`.uemcp/tasks/*.log`。
- 首选 `unreal.logs.get(mode="auto", tailLines=..., filter={...})`；UE 已连接时可用 `ue_logs_tail`；launcher 任务日志用 `launcher_task_status(task_id, log_tail_lines=...)`。
- 先窄化类别、级别和关键字，再扩大日志范围；需要连续排查时复用 `cursor`。

## 7. Tests

- Automation 测试放对应 Runtime 或 Editor 模块的 `Tests/` 目录，使用 `#if WITH_DEV_AUTOMATION_TESTS` 守卫。
- 测试默认使用 in-memory 对象，不读写真实 `Content/` 资产，除非用户明确要求资产级验证。
- 反射类型、`*.Build.cs`、新增/删除 `.cpp` 或插件依赖变化后，完整 build + 重启编辑器验证，不依赖 Live Coding。

## 8. Output

- 非简单请求先给简短计划，列出要加载的技能和要操作的文件。
- 完成时说明：改了什么、如何验证、风险与后续建议。尽量简洁。

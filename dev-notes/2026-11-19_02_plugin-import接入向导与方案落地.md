# plugin-import 接入向导与方案落地（2026-11-19）

> 关联方案：`docs/20261119_01_plugin-import外部仓库接入插件方案.md`
> 关联 Skill：`.codebuddy/skills/plugin-import/SKILL.md`
> 本轮为**纯文档 / 配置产出**，未改动任何业务代码，未新增 `backend/plugins/` 插件目录。

## 背景

从「分析 `G:\Github\AI\VideoAgent\VideoClaw` 能否作为 Plugin 放进 ADS」开始，连续四轮推演：

1. **形态分析**：VC 是 monorepo 混合仓，主产品 `video-claw` 是独立 FastAPI + SSE Web 服务（8 个 router），外层是 OpenClaw Skill 文档包装，`FilmAgent/` 是 SIGGRAPH 论文复现代码且互不调用。ADS 的 Plugin 是进程内 `ActionBase` 插件套件 → 形态不匹配，但 ADS 有外部程序通道。
2. **路径 1 清单**：sidecar + REST/SSE 接入。首版误把 VC 注册成 `director` 的第 4 个后端。
3. **纠正**：用户指出 `director` 与 VC 是两个平级、互相独立的生视频系统。核实 `backend/plugins/director/backends.py:11` 的 `lightai/libtv/dreamina` 是底层引擎/CLI 而非独立系统 → 改为新建平级插件 `backend/plugins/videoclaw/`。
4. **零改造确认**：用户问「引入 VC 是否要改造 VC 本身代码和结构」。核实 `config.yaml.example:2-6`、`config.py:17-22`、`.gitignore:17` → 只需部署配置（复制 config 模板、改端口、填 Key），VC 代码与结构一行不动。
5. **自动化可行性**：用户问「给个 GitHub 链接，AI 助手能否直接适配成 Plugin」→ 结论可实现，但卡在识别 / 决策 / 验证三点，合理目标是「AI 探测+生成，人确认决策+验证」。
6. **本轮**：用户要求先把 `/plugin-import` 的 SKILL.md 写出来，并补一份方案文档和 DevLog。

## 本轮做的事

### 1. 核实项目约定（避免文档写错路径）

| 核实项 | 结果 |
|---|---|
| 项目级 Skill 规范 | `.codebuddy/skills/<name>/SKILL.md`；frontmatter 支持 `name` / `description` / `allowed-tools` / `user-invocable`；`$ARGUMENTS` 为参数占位符（查 CodeBuddy 内置文档 `cn/cli/skills.md`、`common-workflows.md`） |
| ADS 斜杠命令支持项目 Skill | `dev-notes/2026-07-01_01:38-60`，四套目录 `.ads/skills` / `.Agent/skills` / `.codebuddy/skills` / `.claude/skills`；项目 Skill 可作 `source="skill"` 伪命令进补全 |
| 项目级 skill 目录现状 | 四套目录**均不存在**，故新建 `.codebuddy/skills/plugin-import/`（选 CodeBuddy 原生目录，ADS 亦兼容） |
| trait 词表真实路径 | `backend/skills/rules/trait_taxonomy.yaml`。**注意**：`docs/20261023_01_...:152` 写的是 `backend/sop/trait_taxonomy.yaml`，实际不存在，文档有漂移 → Skill 与方案文档均按真实路径写 |
| 配置权威源 | `backend/.env`（`backend/config.py:25-35` 明确「backend/.env 是权威配置源」），模板 `backend/.env.example` |
| 时间轴 | `backend/command_log.py:140` `record_traced_command` |
| 测试范例 | `backend/tests/plugins/test_director_plugin.py`、`test_h5_plugin.py` |
| 文档命名约定 | `docs/` 用 `YYYYMMDD_NN_标题.md`；`dev-notes/` 用 `YYYY-MM-DD_NN_标题.md`。今日 dev-notes 已有 `_01`（六层架构改造），故本篇取 `_02`；docs 今日无文件，取 `20261119_01` |

### 2. 三个产出物

| 文件 | 内容 |
|---|---|
| `.codebuddy/skills/plugin-import/SKILL.md` | 五阶段流程（探测 → 报告 → 决策 → 生成 → 静态校验/交付）、探测报告模板、决策清单、最小骨架、10 条生成约束、7 条硬性禁止项、参考文件索引、VC 首例 |
| `docs/20261119_01_plugin-import外部仓库接入插件方案.md` | 问题与目标、可实现性与三卡点、仓库形态分级表、平级独立/零改造两条设计决策、架构与安全边界、VC 案例、验收、风险、后续演进 |
| `dev-notes/2026-11-19_02_plugin-import接入向导与方案落地.md` | 本篇 |

### 3. 写进文档的关键决策

- **平级独立**：VC 不进 `director/backends.py`，新建 `backend/plugins/videoclaw/`；registry 约定式自动发现（`backend/plugins/registry.py:45-51,149-166`），无需改注册表、无需改 director、无需写 MCP 包装服务。
- **零改造外部仓库**：适配层写在 ADS 侧；VC 只补部署配置；保持可独立 `git pull`。
- **Action 名全局唯一**：一律加 `<id缩写>_` 前缀；`registry.py:160-162` 重名会静默覆盖并告警。
- **安全硬闸门**：registry 是进程内 `importlib` 全量导入而非沙箱（`registry.py:97-120,149-166`），第三方代码落进 `backend/plugins/` 即在 ADS 进程内执行 → 生成物必须人审合入，禁止运行时自动加载。
- **准入条件项**：`reflection.py` 仅「凡有门禁打回」必选（`docs/20261023_01_...:43`），`acceptance.py` 仅「具备专属运行态或门禁报告」必选（:129）；不定义 `*_failed` 打回则两者可省 → 这是路径 1 能保持轻的原因。
- **环境缺失分流**：`env_missing` / `blocked`，绝不 `*_failed`（:102-109）；`data["command"]` 必须 `str`（:90-99）。
- **端口冲突**：VC 默认 8000 与 ADS `backend/config.py:48` / `start_server.py:10` 冲突，决策阶段强制改（建议 8100）。
- **trait 冲突**：`director/plugin.json:6-8` 已占 `category:video` / `pipeline:video`；新插件优先用独立 `engine:<id>`。Action 注册不看 trait，冲突只发生在 SOP/skill 注入层。

## 验证情况

- 三个文件已落盘，路径与项目命名约定一致。
- SKILL.md frontmatter 字段、`$ARGUMENTS`、`user-invocable` 已对照内置文档核实。
- 文档中引用的 ADS 路径/行号均来自本轮或前几轮**实际读过的文件**；VC 侧引用来自 `workflow.py` / `configuration.py` / `orchestrator.py` / `config.yaml.example` / `config.py` / `.gitignore` 实读结果。
- **未验证**：`/plugin-import` 尚未真实跑过一次完整流程（需要真实 GitHub 仓库 + API Key + 起 sidecar）。Skill 的可执行性待首例（VC）实测。
- **未改动**：任何业务代码、`backend/plugins/` 目录、`.env`、`config.py`、`mcp_servers.json`、trait 词表 —— 本轮只新增 3 个文档/配置文件。

## 待办（下一步）

1. 用 VC 作为首例跑一遍 `/plugin-import`，验证五阶段流程与探测报告模板是否够用，回填 Skill 里的细节。
2. 定 trait 方案（`engine:videoclaw` 独立 vs 与 director 共用 `category:video`），再决定是否进入实现阶段。
3. 实现阶段按方案 §7 的最小骨架：`plugin.json` + `<id>_client.py` + `actions/` + `test_<id>_plugin.py`，并补 `backend/.env.example` 与 `config.py` 字段。
4. 层次 B（运行时 `import_plugin` Action + 补丁/PR 人审 + 静态扫描）单独排期，不在本轮范围。
5. 顺手可修：准入规范 `docs/20261023_01_...:152` 的 trait 词表路径写成 `backend/sop/trait_taxonomy.yaml`，实际在 `backend/skills/rules/`，属文档漂移（本轮未改，避免扩大改动面）。

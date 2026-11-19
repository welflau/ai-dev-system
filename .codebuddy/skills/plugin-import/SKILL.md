---
name: plugin-import
description: 给一个 GitHub 链接（或本地仓库路径），把一个外部库适配成 ADS 的平级插件套件 backend/plugins/<id>/。用于"把这个仓库接进 ADS / 做成 Plugin / 生成插件骨架 / 适配外部视频或 AI 服务"等任务。自动完成仓库探测、探测报告、决策清单、插件骨架生成与静态校验；关键决策和运行验证必须交由人完成。
user-invocable: true
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Agent, AskUserQuestion, TaskCreate, TaskUpdate, TaskList, WebFetch
---

# plugin-import：外部仓库 → ADS 平级插件

输入：`$ARGUMENTS`（GitHub URL / `owner/repo` / 本地绝对路径）。为空则先用 AskUserQuestion 询问目标仓库与用途。

## 定位与边界

- **产物**：`backend/plugins/<id>/` 下一个**与现有插件平级、独立**的新插件套件；外部仓库作为**独立 sidecar 进程**运行，通过 HTTP/CLI/MCP 被适配层调用。
- **不做**：不改造外部仓库本身的代码与结构；不把外部仓库整仓拷进 `backend/plugins/`；不 `import` 外部仓库的模块；不让运行时自动加载未经人审的第三方代码。
- **自动化程度**：探测、报告、骨架生成、静态校验可自动完成；**集成方式/端口/trait/排除目录等决策必须人确认**，**端到端运行验证必须人完成**（AI 无法自动补 API Key、装系统二进制、真实起服务、承担付费调用）。
- 合理预期是「AI 完成约 80% 的探测与生成，人确认决策并跑一次验证」，不是「给链接就开箱可用」。

## 为什么 ADS 适合（执行时依据）

- 插件是**约定式自动发现**：`backend/plugins/registry.py:45-51,149-166` 扫描所有 `plugins/<id>/actions/*.py` 中的 `ActionBase` 子类，按 `name` 全局注册，无显式注册表 → 文件放对位置即生效。
- 现有平级插件：`content / h5 / unity / ue5 / director`。新插件 `id` 不得与它们重名。
- 准入规范是可机器检查的：`docs/20261023_01_插件套件准入规范与五道约束.md:148-158`。

## 五个阶段（严格按顺序，阶段 3 是硬闸门）

### 阶段 1 · 探测（只读，不改任何文件）

1. 取仓库：GitHub URL 则 `git clone --depth 1` 到系统临时目录；本地路径直接用。**不要** clone 进 ADS 工作目录。
2. 用 Explore agent（very thorough）或 Read/Glob/Grep 判定以下项目，每条都要有 `路径:行号` 证据：
   - **仓库形态**：独立 Web 服务 / CLI / MCP server / 可 import 的库 / 论文脚本 / monorepo 混合体；各子目录之间是否互不调用。
   - **对外契约**：HTTP 端点（含 SSE）、OpenAPI、CLI 子命令、可复用类、是否有 health 探活。
   - **入口与启动**：启动命令、监听端口/host、**CWD 假设**、配置加载方式。
   - **依赖与前提**：Python/Node 版本、requirements/pyproject、系统二进制（ffmpeg、Chromium）、付费 API Key、GPU/CUDA。
   - **副作用**：导入即建目录、全局单例、类属性配置、固定端口、磁盘 session/产物目录。
   - **许可与漂移**：LICENSE 类型、子目录许可标注是否不一致；README 与源码是否矛盾（**以源码为准**，README 只作线索）。
   - **应排除的部分**：论文代码、配图目录、纯文档包装层。
3. 按形态查「自动化可行性分级」表（见方案文档 `docs/20261119_01_plugin-import外部仓库接入插件方案.md` §3），若属「无对外契约的脚本集合」，**停止生成**，只交探测报告并说明原因。

### 阶段 2 · 探测报告（产出给人过目）

在对话中输出结构化报告，不落盘：

```
① 项目定位（一句话）
② 仓库分层与各子项目关系（谁调用谁 / 互不相关）
③ 技术栈、运行方式、入口
④ 对外接口清单（端点 / 命令 / 类，带路径:行号）
⑤ 依赖与运行前提（Key、二进制、端口、CWD、付费）
⑥ 副作用与可嵌入性障碍
⑦ 许可证与文档漂移点
⑧ 推荐集成方式 + 理由
⑨ 关键文件路径清单
```

**硬闸门**：报告须人确认形态判断无误后才进入阶段 3。README 与源码冲突时以源码为准，并在报告里点名。

### 阶段 3 · 决策清单（必须人确认，AI 不自作主张）

用 AskUserQuestion 或逐项列出，至少确认：

| 决策项 | 默认/建议 | 依据 |
|---|---|---|
| 集成方式 | 有 REST/SSE → sidecar HTTP；标准 MCP → 改 `backend/mcp_servers.json`；CLI → 子进程 | 分级表 |
| 端口 | 避开 ADS 已占用的 8000（`backend/config.py:48`、`start_server.py:10`）与桌面版 18000 | 冲突检查 |
| 插件 `id` | 小写短名，不与 5 个现有插件重名 | `backend/plugins/registry.py:45-51` |
| Action 命名 | 一律加 `<id缩写>_` 前缀（如 `vc_start_project`）；**禁止**使用 `gen_video` 等现有名 | 重名会静默覆盖并告警 `registry.py:160-162` |
| trait | 优先用独立 `engine:<id>` 并登记词表；若要与同类插件共用 `category:*` 需说明两套 Skill/SOP 会同时注入 | `plugin.json` `required_traits` |
| 排除目录 | 阶段 1 找出的无关子目录不部署 | — |
| Accessor 契约 | 必填参数、模型名从外部 `GET /config` 类接口动态取，不写死 | 服务端硬校验会 400 |
| 门禁 | 是否定义 `reject_status` 打回 / 是否有专属门禁报告（决定要不要 `reflection.py` / `acceptance.py`） | 准入约束 1 / 6 |

### 阶段 4 · 生成骨架（写到 ADS 仓库内）

**生成目标**：`backend/plugins/<id>/`，最小文件集：

```
backend/plugins/<id>/
├── __init__.py
├── plugin.json              # id / name / version / description / required_traits
├── <id>_client.py           # 适配层：只发 HTTP/CLI，不碰 ADS 业务；不复制外部仓库代码
└── actions/
    ├── __init__.py
    └── <prefix>_*.py        # ActionBase 子类
```

生成时逐条落实（**全部是硬性约束**）：

1. **Action 契约**：继承 `backend/actions/base.py:52-75` 的 `ActionBase`，实现 `name` 与 `async run(context) -> ActionResult`（`ActionResult` 见 :29-49）。
2. **配置**：新增变量写 `backend/.env`（权威配置源，`backend/config.py:25-35`）并同步 `backend/.env.example`；在 `config.py` 的 `Settings` 类（:43）补字段，照 `LIGHTAI_*` 写法用 `os.getenv`。**禁止提交真实 API Key**。
3. **环境缺失分流**：外部服务没起 / 缺 Key / 缺 CLI → 返回 `env_missing`、`blocked`，**绝不返回 `*_failed`**（否则会错误触发 DevAgent 空改业务代码）。依据 `docs/20261023_01_插件套件准入规范与五道约束.md:102-109`。
4. **时间轴**：外部命令一律走 `backend/command_log.py:140` 的 `record_traced_command(...)`，`ActionResult.data["task_id"]` 带 `TCMD-*`，`data["command"]` **必须是 `str`**（用 `shlex.quote` 拼），严禁 `List[str]`。依据准入约束 2（:90-99）。
5. **产物隔离**：下载产物落 `works/<slug>/...`；重型/运行时产物目录按准入约束 4 加 `git clean` 排除。不要污染外部仓库的 `code/result/`。
6. **长超时**：视频/生成类任务用独立长超时，不要复用 `LLM_TIMEOUT`（120s）。
7. **测试**：`backend/tests/plugins/test_<id>_plugin.py`，参考现有 `test_director_plugin.py` / `test_h5_plugin.py`。
8. **trait 登记**：新 trait 写 `backend/skills/rules/trait_taxonomy.yaml`（注意：不是 `backend/sop/`）。
9. **条件文件**：仅当阶段 3 确认有门禁打回才生成 `reflection.py`（准入约束 1，:43）；仅当确认有专属门禁报告才生成 `acceptance.py`（约束 6，:129）。**不改** `backend/agents/dev.py`、`backend/actions/reflection.py`。
10. **外部仓库零改造**：只在报告里写「部署说明」（复制 config 模板、改端口、填 Key、启动命令、CWD），不改其源码/结构。配置模板文件通常被对方 `.gitignore` 忽略，属于部署方自供。

### 阶段 5 · 静态校验 + 交付

AI 可自动完成：

- [ ] `plugin.json` 合法、`id` 唯一、trait 已登记
- [ ] 生成的模块可 import，无 import 期副作用
- [ ] `available_action_names()` 出现新 Action，`backend/plugins/registry.py` 无「插件 Action 重名」告警
- [ ] `data["command"]` 为 `str`，无 `os.system` / 任意网络请求 / 未审子进程调用
- [ ] 准入 Checklist（`docs/20261023_01_插件套件准入规范与五道约束.md:148-158`）逐项过
- [ ] mock 掉外部调用的单元测试通过
- [ ] **回归**：不指定新后端时既有插件（尤其 `director`）行为不变

**明确交给人的验收**（写进交付说明，不要声称已完成）：起 sidecar、探活、补 Key、装系统二进制、跑一次最小闭环、确认产物落 `works/`、时间轴有 `TCMD-*`、停掉服务后返回 `blocked` 而非 `*_failed`。

## 硬性禁止项

1. **不整仓拷入 / 不 submodule 进 `backend/plugins/` / 不 import 外部仓库模块**（顶层 `config`/`models`/`core`/`api` 会与 ADS 撞名）。
2. **不改外部仓库代码或目录结构**——sidecar 方案的立身之本是外部仓库可独立 `git pull` 跟上游。
3. **不把外部仓库塞进既有插件的 `backends.py` 当第 4 后端**——那会把一个平级独立系统降级成别人的引擎。已有插件的 `ALLOWED_BACKENDS` 里是底层引擎/CLI，不是独立系统。
4. **不让运行时自动加载未审代码**：`backend/plugins/registry.py:97-120,149-166` 是进程内 `importlib` 全量导入，不是沙箱。第三方代码落进 `backend/plugins/` 即等同在 ADS 进程内执行，属供应链风险 → 生成物必须走「补丁 / PR + 人审合入」。
5. **不改宿主** `backend/agents/dev.py` / `backend/actions/reflection.py`。
6. **不以 README/文档为准**替代源码契约；发现文档漂移要在报告里点名。
7. **不把环境缺失判成 `*_failed`**。

## 参考文件（ADS 仓库内相对路径）

| 用途 | 文件 |
|---|---|
| 准入规范与 Checklist | `docs/20261023_01_插件套件准入规范与五道约束.md` |
| 完整插件套件范例 | `docs/20261101_02_Director视频插件套件方案.md`、`backend/plugins/director/` |
| 本 skill 的设计方案 | `docs/20261119_01_plugin-import外部仓库接入插件方案.md`（§11 用户级安装） |
| 本次落地记录 | `dev-notes/2026-11-19_02_plugin-import接入向导与方案落地.md`、`dev-notes/2026-11-19_03_ConfigPack用户级安装落地.md` |
| 多 CLI 分发 | 「套件与插件 → ConfigPack」面板选「用户目录」安装 → 写入 `~/.claude/` / `~/.codebuddy/` / `~/.cursor/` / `~/.workbuddy/` 原生目录，本机所有项目、所有 CLI 后端通用 |
| 自动发现 / 命名 | `backend/plugins/registry.py` |
| Action 契约 | `backend/actions/base.py` |
| 时间轴 | `backend/command_log.py`、准入规范约束 2 |
| 配置 | `backend/config.py`、`backend/.env.example` |
| trait 词表 | `backend/skills/rules/trait_taxonomy.yaml` |
| MCP 通道 | `backend/mcp_servers.json`、`backend/mcp_client.py` |
| 测试范例 | `backend/tests/plugins/test_director_plugin.py` |

## 首例（回归样本）

`VideoClaw`（`G:\Github\AI\VideoAgent\VideoClaw`）：FastAPI + SSE 的 REST 服务，8 个 router，`/api/health` 现成，`config.yaml.example` 现成端口/Key 配置项，MIT 许可。结论 = 独立 sidecar（端口改 8100 避开 ADS 8000）+ 平级插件 `videoclaw`；`FilmAgent/` 论文代码整体排除；外部仓库零代码改造。详见方案文档 §6。

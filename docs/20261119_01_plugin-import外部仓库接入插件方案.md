# plugin-import：给一个 GitHub 链接自动把外部仓库接成 ADS 插件

日期：2026-11-19
状态：方案待评审（已落地 Skill 骨架，运行时自动化未实现）
关联：`docs/20261023_01_插件套件准入规范与五道约束.md`、`docs/20261101_02_Director视频插件套件方案.md`、`.codebuddy/skills/plugin-import/SKILL.md`、`dev-notes/2026-11-19_02_plugin-import接入向导与方案落地.md`

---

## 一、问题与目标

起因：评估 `G:\Github\AI\VideoAgent\VideoClaw`（下称 VC）能否作为 Plugin 放进 ADS。经四轮分析得到结论后，进一步提出：**能不能做到「给一个 GitHub 链接，AI 助手就把这个库适配成 ADS 插件」**。

目标形态：

```
GitHub URL / 本地路径
   ↓ AI 探测（只读）
探测报告（形态 / 契约 / 依赖 / 风险 / 许可）
   ↓ 人确认
决策清单（集成方式 / 端口 / trait / 排除目录）
   ↓ AI 生成
backend/plugins/<id>/ 骨架 + 测试 + 静态校验
   ↓ 人验证
补 Key、起 sidecar、跑一次最小闭环、回归
```

**合理预期是「AI 完成约 80% 的探测与生成，人确认决策并跑一次验证」，不是「给链接就开箱可用」。**

---

## 二、结论：可以实现，但有三个卡点

技术上可实现，且 ADS 的地基比一般系统更好：

| 地基层面 | 依据 |
|---|---|
| 约定式自动发现，无显式注册表 | `backend/plugins/registry.py:45-51,149-166` 扫 `plugins/<id>/actions/*.py` |
| 准入规范可机器检查 | `docs/20261023_01_插件套件准入规范与五道约束.md:148-158` |
| 现成完整范例 | `backend/plugins/director/`、`docs/20261101_02_Director视频插件套件方案.md` |
| 可复用零件 | `backend/actions/scaffold_web.py`、`scaffold_utils.py`、`git_manager.py`、`actions/chat/create_github_repo.py` |
| 外部命令可观测 | `shell` Action + `backend/command_log.py:140` 时间轴 |
| MCP 通道 | `backend/mcp_servers.json`、`backend/mcp_client.py` 支持 stdio/http |

目前**没有**现成的「从 URL 自动生成插件」能力，但零件齐全。

### 卡点 1 · 识别

GitHub 仓库没有标准形态。VC 一个仓库里同时混了：独立 FastAPI 服务、OpenClaw Skill 文档包装层、SIGGRAPH 论文复现代码、两层同名 `video-claw/` 目录、配图目录。而且**文档会漂移**：`references/workflow/create_project.md` 装的是 sandbox 视频接口的内容；`CLAUDE.md` 写 9 个停点而 `SKILL.md` 写 7 个。

→ AI 必须**以源码为准、README 只作线索**，并产出探测报告让人过目。

### 卡点 2 · 决策

端口（VC 默认 8000 与 ADS `backend/config.py:48` / `start_server.py:10` 冲突）、trait 是否与 `director` 共用、排除哪些目录、用哪种集成方式、要不要加鉴权 —— 这些是**产品决策**而非技术推导，必须人确认（或给默认值 + 可改）。

### 卡点 3 · 验证

AI 无法自动完成端到端验证：缺 API Key、缺 ffmpeg/Playwright Chromium、要真实起服务、会产生付费调用、SSE 长连接分钟级。**能自动验的只有静态部分**：生成代码可 import、Action 名不冲突、plugin.json 合法、准入 lint、mock 掉 HTTP 的单测。

---

## 三、按仓库形态分级（自动化可行性）

| 仓库形态 | 自动化程度 | 理由 |
|---|---|---|
| 标准 MCP server | 极高 | 只需往 `backend/mcp_servers.json` 加一项，零插件代码 |
| 带 OpenAPI/REST 的服务（**VC**） | **高** | 从 `openapi.json` / router 源码直接生成 client + Action |
| CLI 工具（`--help` 规范） | 中 | 从 help 生成 adapter，但输出解析易错 |
| 可 import 的 Python 库 | 中低 | 依赖冲突、顶层模块名冲突、导入副作用要人判 |
| 论文脚本 / 无对外契约的 monorepo（`FilmAgent`） | 低 | 无契约可生成，基本人工重写 → 只出报告，停止生成 |

VC 落在第二档偏上（FastAPI + 8 个 router + `/api/health` + 配置模板 + MIT），**最适合做第一个样本**。

---

## 四、两条关键设计决策（由前几轮纠正得出）

### 4.1 平级独立，不寄生

最初方案把 VC 注册为 `backend/plugins/director/backends.py:11` 的第 4 个后端。**这是错的**：该文件里的 `lightai / libtv / dreamina` 是底层生视频引擎 / CLI，不是独立系统；VC 和 `D:\A_Works\director` 是两个**平级、互相独立**的生视频系统。把 VC 塞进去等于把平级系统降级成别人的引擎。

正确形态：VC 成为第 6 个平级插件 `backend/plugins/videoclaw/`。ADS 现有 5 个平级插件 `content / h5 / unity / ue5 / director`。

好消息是 registry 是目录约定式自动发现，所以「独立注册」= 建一个平级目录，**不用改 director 一行代码、不用改注册表、不用写 MCP 包装服务**（`mcp_servers.json` 里只有 3 个官方 MCP 且全 disabled，director 本身也不走 MCP）。

### 4.2 外部仓库零改造

VC 侧唯一要动的是**部署配置，不是代码**：

| 动作 | 依据 |
|---|---|
| 新建 `VC/backend/config.yaml`（复制 `config.yaml.example`） | 该文件本来就被 `video-claw/.gitignore:17` 忽略，`config.py:12-13` 无它时回退读 example |
| 改 `server.port: 8000 → 8100` | 现成配置项 `config.yaml.example:2-6`、`config.py:17-22` |
| 填 `api_providers.*.api_key` | `config.yaml.example:7-34` |
| `cd backend && uv run python api_server.py` | 现成入口，CWD=backend/ 是它自己的约定 |

VC 已有 8 个 router（`/api/health`、`/api/config`、`/api/project/*`、`/api/sandbox/*`、`/api/pipelines/*`），ADS 需要的接口全部现成。适配层写在 **ADS 仓库**的 `backend/plugins/videoclaw/videoclaw_client.py`，不落到 VC 仓库。

**什么时候才需要动 VC 代码**：只有走「直接 import 进 ADS 进程」（已否）才必须大改 —— `pyproject.toml:41` 的 `package=false` 改掉、补 `__init__.py`、把满仓的 `from config import ...` 改成相对 import 消解顶层模块名冲突、拆掉导入即建目录/全局单例的副作用、去掉 CWD 假设。这正是选择 sidecar 的原因。

零改造还有一个实际好处：VC 可独立 `git pull` 跟上游，ADS 适配器只跟 API 契约走；一旦改了 VC 代码，每次上游更新都要合并冲突。

---

## 五、架构与安全边界

### 5.1 两个落地层次

**层次 A（本次落地）：开发时**
做成项目级 Skill `.codebuddy/skills/plugin-import/SKILL.md`，由 AI 助手在开发时执行探测 + 生成。依据：CodeBuddy 项目级 Skill 规范 `.codebuddy/skills/<name>/SKILL.md`；ADS 亦支持把项目 Skill 暴露成斜杠命令，四套目录 `.ads/skills` / `.Agent/skills` / `.codebuddy/skills` / `.claude/skills`（`dev-notes/2026-07-01_01:38-60`）。因此 `/plugin-import <url>` 可手动触发，AI 也可主动识别。

**层次 B（不本次实现）：运行时**
做成 `import_plugin` Action / Skill，让 ADS 内的 Agent 在工单流水线里接入外部仓库。**只做到「生成补丁 / PR + 人审合入」**。

### 5.2 供应链风险（硬约束）

`backend/plugins/registry.py:97-120,149-166` 是**进程内 `importlib` 全量导入**，不是沙箱。第三方代码一旦落进 `backend/plugins/` 就等同在 ADS 进程里执行。

因此「给个陌生 URL 就自动加载」= 让 AI 替你执行任意第三方代码。必须有：

1. 人工审核闸门（生成物走补丁 / PR，不自动落盘启用）；
2. 生成代码静态校验（禁 `os.system`、任意网络请求、未审子进程调用）；
3. Action 名全局唯一校验（`registry.py:160-162` 重名会静默覆盖并告警）。

### 5.3 与既有插件不冲突

- 新插件 `id` 不与 5 个现有插件重名；
- 新 Action 一律加 `<id缩写>_` 前缀，不占用 `gen_video` 等既有名；
- `resolve_backend` 等默认值保持不变，只在显式指定时才走新后端；
- trait 优先用独立 `engine:<id>`，避免与 `director/plugin.json:6-8` 的 `category:video` / `pipeline:video` 撞车导致两套 Skill/SOP 同时注入（Action 注册不看 trait，冲突只在 SOP/skill 注入层）。

---

## 六、案例：VideoClaw

| 项 | 结论 |
|---|---|
| 定位 | monorepo 混合仓：主产品 `video-claw` 是独立 FastAPI+SSE Web 服务（后端 8000 + Next.js 前端 3000）；外层是 OpenClaw Skill 文档包装；`FilmAgent/` 是 SIGGRAPH Asia 2024 论文复现代码，与主产品互不调用 |
| 对外契约 | REST + SSE，8 个 router，`/api/health` 现成，**无需 VC 新增任何接口** |
| 硬校验 | `workflow.py:18-23,44-52` 的 `_require_model_fields` 要求显式传 4 个模型字段，否则 400 → 适配器从 `GET /api/config`（`configuration.py:16-21`）动态取 `models`，不写死 |
| 阶段 | `script_generation / character_design / storyboard / reference_generation / video_generation / post_production`（`orchestrator.py:32-51`） |
| 产物 | `/code/result/...` 静态挂载（`app.py:52-53`），下载落 ADS `works/<slug>/video/` |
| 端口 | 改 8100，避开 ADS 8000（`config.py:48`）与桌面版 18000 |
| 无认证 | `app.py:43-49` CORS `*`、`docs/api.md:11-13` 无认证 → sidecar 只绑 `127.0.0.1` |
| 许可 | 根 `LICENSE` 为 MIT；`FilmAgent/README.md:11` 徽章写 Apache-2.0 但无独立 LICENSE，若将来复用需向作者确认 |
| 排除 | `FilmAgent/`、`*-pics/`、外层 `SKILL.md`/`references/` 不部署，也**不需要删除或整理** |

首例最小闭环：`GET /api/health` → `POST /api/project/start`（带齐模型字段）→ `POST /api/project/{sid}/continue`（同步返回，比 SSE 简单）→ `GET .../artifact/{stage}` → 从 `/code` 下载产物。端到端仍需人补 Key、装 ffmpeg/Chromium、真实起服务。

---

## 七、验收标准

**AI 可自动完成（静态）**

- [ ] `plugin.json` 合法、`id` 唯一、trait 已登记 `backend/skills/rules/trait_taxonomy.yaml`
- [ ] 生成模块可 import，无 import 期副作用
- [ ] `available_action_names()` 出现新 Action，无重名告警
- [ ] `ActionResult.data["command"]` 为 `str`；时间轴有 `TCMD-*`
- [ ] 准入 Checklist（`docs/20261023_01_...:148-158`）逐项过
- [ ] mock 单测通过；既有插件（尤其 `director`）回归不变

**必须人完成（动态）**

- [ ] 起 sidecar、探活、补 API Key、装系统二进制
- [ ] 跑一次最小闭环，产物落 `works/`
- [ ] 停掉服务后返回 `env_missing` / `blocked` 而非 `*_failed`
- [ ] 确认付费调用成本与 trait 注入行为

---

## 八、风险清单

1. **文档漂移**：外部仓库 README/SKILL 与源码矛盾 → 以源码为准，报告点名。
2. **契约漂移**：外部上游改模型字段名或必填校验，会让适配器 400 → 动态取配置，不写死；上游更新只需调适配器。
3. **端口冲突**：默认 8000 与 ADS 冲突 → 决策阶段强制确认。
4. **无认证**：sidecar 只绑 `127.0.0.1`，禁止 `0.0.0.0`；非本机暴露需自行加网关/鉴权。
5. **两套产物目录**：外部 `code/result/` 与 ADS `works/` 各管各的；外部 `DELETE /api/sessions` 会删文件，别在 ADS 侧随意调。
6. **长连接**：SSE 分钟级，客户端必须设读超时与断线处理。
7. **进程生命周期**：本次 ADS 不管启停，靠 `probe_backend` / `health()` 识别；后续可并进 `start-backend.bat`。
8. **成本**：全流程连打多个付费 API，验证期传 `episodes: 1` 或先用 sandbox 单次能力。

---

## 九、后续演进（层次 B，不在本次范围）

1. 把探测报告模板 + 骨架生成器 + 准入 linter 固化成可复用的 generator（可基于 `backend/actions/scaffold_utils.py`）。
2. 分级泛化：MCP server → 只改 json；REST → 从 `openapi.json` 生成 client；CLI → 从 `--help` 生成 adapter。
3. 运行时 `import_plugin` Action，输出补丁 / PR，人审合入。
4. 生成代码静态扫描 + 白名单，作为供应链闸门。
5. 6 阶段项目级编排 + `intervene` / `update_artifact` 人工介入，属于路径 2（深度集成），独立于本方案。

---

## 十、本次产出物

| 文件 | 作用 |
|---|---|
| `.codebuddy/skills/plugin-import/SKILL.md` | 开发时接入向导（五阶段流程 + 硬闸门 + 禁止项） |
| `docs/20261119_01_plugin-import外部仓库接入插件方案.md` | 本方案文档 |
| `dev-notes/2026-11-19_02_plugin-import接入向导与方案落地.md` | 落地 DevLog（Skill 骨架） |
| `dev-notes/2026-11-19_03_ConfigPack用户级安装落地.md` | 落地 DevLog（用户级安装 7 条） |

---

## 十一、追加落地：ConfigPack 用户级安装（2026-11-19）

### 11.1 为什么需要

§5.1 层次 A 里「写装机脚本把 skill 复制到 `~/.<cli>/skills/`」是多余的。核实后发现
`backend/pack_installer.py` 本来就是 ADS 的分发器，只是被三处限制卡住：

- `pack_installer.py:111-113` `_detect_cli_targets` 白名单硬编码 `("claude","codebuddy")`，Cursor/WorkBuddy 被静默丢弃；
- `pack_installer.py:312` 目标根固定 `Path(project_path) / f".{target}"`，且 `:289-292` 把文件写进 `packs/<pack>/` 隔离子目录 → CLI 原生自扫不到；
- 端点全是 `/{project_id}/packs/...`（`api/projects.py:2442,2483,3632,3766`），`project_packs.project_id NOT NULL`（`database.py:965-971`）→ 没有用户级入口。

用户澄清「ADS 调用的 CLI 不固定，要覆盖多个 CLI 环境」，因此把安装范围做成**用户可选**：
项目级保持不变，新增用户级路径。这同时解决了之前列的所有痛点：

| 痛点 | 用户级安装如何解决 |
|---|---|
| 覆盖多 CLI | `scope=user` 强制 `ALL_CLI_TARGETS = (claude, codebuddy, cursor, workbuddy)` |
| cwd 限制 | 用户主目录不受 `llm_client.py:1472-1492` 隔离临时目录影响（`env=os.environ.copy()`，不改 HOME） |
| 保留 CLI 原生语义 | 写 `~/.<cli>/skills/` 等顶层原生目录，`/plugin-import` 斜杠、`$ARGUMENTS`、`allowed-tools` 仍有效 |
| 换机器 | Pack 定义（`backend/config_packs/`，405 tracked 文件）随 git 走；新机器只需点一次「装到用户目录」，而非每个项目点一次 |
| 不写独立装机脚本 | 复用现成 Pack 分发器 + UI + 记录机制 |

### 11.2 七条改动（已落地）

| # | 改动 | 文件 |
|---|---|---|
| 1 | `install_pack` / `install_packs` 加 `scope`（`project`/`user`）；`user` 时 `install_root = Path.home()`，文件写 CLI 顶层原生目录 | `backend/pack_installer.py:155-342` |
| 2 | `ALL_CLI_TARGETS` 白名单扩到 4 CLI；`scope=user` 时忽略 pack.json 声明不足、强制全 4 | `backend/pack_installer.py:24-27,111-113,195-201` |
| 3 | 用户级落点从 `.{target}/packs/<pack>/` 改为 `.{target}/skills/` 顶层（项目级仍用隔离目录，行为不变） | `backend/pack_installer.py:316-325` |
| 4 | 新增 4 个无 `project_id` 端点：`GET /packs/user`、`GET /packs/user/available`、`POST /packs/user/{name}/install`、`DELETE /packs/user/{name}`；静态路由声明在 `/{project_id}/packs` 之前 | `backend/api/projects.py`（`get_user_packs` 等） |
| 5 | 新增 `user_packs` 表（无 `project_id`，`pack_name UNIQUE`，含 `install_root`），重装按名字 upsert | `backend/database.py:974-983` |
| 6 | Packs 面板加「安装范围」选择器 + 用户级已安装/可安装列表；用户级安装不要求 `currentProjectId`；前端 confirm 提示会写 `~/.claude/CLAUDE.md` 与 `settings.json` | `frontend/index.html`、`frontend/app.js` |
| 7 | 13 个 `pack.json` 的 `targets` 补齐 `cursor` / `workbuddy`（含原本只写 `["codebuddy"]` 的 `ue5-prod-skills`） | `backend/config_packs/*/pack.json` |

**两个实现取舍**（均已写进代码注释）：

- 用户级安装**不做模板变量替换**：`{{project_name}}` / `{{repo_path}}` 等占位符保留原文，避免在没有项目上下文时被静默抹成空串。
- 用户级安装**强制 4 CLI**，不受个别 Pack 旧声明限制，保证「一次装好、任意后端可用」。

### 11.3 行为兼容性

- `install_pack(..., scope="project")` 默认参数保持原语义：仍写 `<project>/.{cli}/packs/<pack>/`，`create_project.py:311,478` 的自动安装不受影响。
- 项目级端点返回结构未变；用户级端点返回 `scope` / `install_root` / `copied_files` / `installed_targets`。
- 用户级安装**不写 `ticket_logs`**（该表 `project_id TEXT NOT NULL REFERENCES projects(id)`，`database.py:430`），只记 `user_packs`。卸载同样只删记录、不删用户目录文件（与项目级 `remove_pack` 语义一致）。

### 11.4 验证

- `backend/tests/test_pack_user_scope.py` 9 项全通过：项目级行为不变、用户级 4 CLI 顶层落盘、忽略 `project_path`、scope 校验、13 个 pack.json targets、`install_packs` 批量。
- FastAPI 实际注册路由验证：`GET /api/projects/packs/user` 命中静态 `get_user_packs`，未被 `/{project_id}/packs` 吃掉。
- TestClient 端到端 9 项通过：空列表 / available 13 个 / 安装 4 targets / 顶层落盘 / 记录 upsert / 重装去重 / 删除 / 项目级端点不变。临时 home + 临时 DB，未碰真实用户目录与 `ads.db`。
- `node --check frontend/app.js` 通过；`python -m pytest tests/test_pack_user_scope.py tests/plugins/test_action_registry.py` 19 项全通过。

### 11.5 仍存在的边界

1. **换机器仍要手动点一次**：用户级文件在 home，不随仓库走；`user_packs` 记在 `ads.db`（`.gitignore:64` 忽略）。若要全自动需加「首次运行检测 + 提示/自动重装」，把用户级安装清单另存为随 git 走的配置（如 `backend/config_packs/user_installs.json`）。
2. **各 CLI 是否读自己的用户级 skills 目录是各 CLI 原生行为**：ADS 不改 HOME，只能按约定写文件，不能保证某 CLI 一定加载。Cursor 另有 `~/.cursor/skills-cursor`（`api/projects.py:2836-2838`），当前未单独处理。
3. **用户级安装会写全局配置**：`shared/rules.md` 对 claude 追加到 `~/.claude/CLAUDE.md`，`mcps/*.json` / `hooks/*.json` 合并到 `~/.claude/settings.json`。前端已加 confirm 明确提示，但这是真实副作用，需在 UI 文案与文档中持续标注。
4. **本项目级 Pack 的 13 个 targets 扩到 4 CLI** 会让新建项目自动安装时也创建 `.cursor/` / `.workbuddy/` 目录（`.gitignore:93,112` 忽略 `.workbuddy/` / `.claude/`，`.cursor/` 未忽略）。这是覆盖多 CLI 的预期代价。

---

## 十二、追加落地：路径 1 把 VideoClaw 接成 ADS 插件（2026-11-19）

前几轮都在做「接入能力基建」，主线（VC 本体接进 ADS）一度是 0%。本节记录按 §7 清单
A→E 阶段落地的结果，详见 `dev-notes/2026-11-19_04_VideoClaw接入路径1落地.md`。

### 12.1 各阶段

| 阶段 | 结果 |
|---|---|
| A 独立 sidecar | VC 侧新建 `backend/config.yaml`（仅 `server.port: 8000→8100`，host `127.0.0.1`）；被 VC `.gitignore:17` 忽略，**未改 VC 源码与结构**；Key 留空待人填 |
| B ADS 配置 | `config.py` Settings 加 `VIDEOCLAW_BASE_URL` / `VIDEOCLAW_TIMEOUT=600` / `VIDEOCLAW_ENABLED=false`；`.env.example` 补注释；未写真实 `.env` |
| C 平级插件 | 新建 `backend/plugins/videoclaw/`：`plugin.json` + `videoclaw_client.py` + `actions/vc_project.py`（`vc_run_project`） |
| D trait 决策 | **复用 `category:video` / `pipeline:video`，不新增词表条目**（见 §12.2） |
| E 验收 | 静态项全过、60 项回归通过；动态 7 项待人完成 |

### 12.2 trait 决策（偏离 §7 清单建议）

清单 D1 建议「独立 `engine:videoclaw` 并登记词表让二者互斥」。**实际采用复用现有
`category:video` / `pipeline:video`**，理由：

1. `registry.py:149-166` 全量加载 Action，**不看 trait**；`vc_` 前缀已保证命名唯一。
2. 路径 1 骨架不建 `skills/`、不声明 `x-workflow`，「两套 Skill/SOP 同时注入」这个
   D1 担心的冲突层在本阶段根本不存在。
3. `trait_taxonomy.yaml` 明确「扩 trait 需改本文件 + review + 部署，不开放 UI 自由输入」，
   且 `engine` 维度语义是「游戏/客户端引擎」，塞 `videoclaw` 语义不对。
4. YAML 解析严格核对：`category:video` / `pipeline:video` 均已在词表 `values` 内。

**可回退点**：若做路径 2 并引入 `skills/` / `x-workflow`，届时再新增独立维度做互斥。

### 12.3 关键实现约束

- 模型名从 `GET /api/config` 动态取，不写死（VC `workflow.py:44-52` 是 400 硬校验）。
- 环境缺失（未启用 / 服务没起）→ `success=False` + `env_missing=True`，**绝不 `*_failed`**。
- `data["command"]` 用 `shlex.quote` 拼单个 `str`；`data["task_id"]` 带 `TCMD-*`。
- 长超时 600s，不复用 `LLM_TIMEOUT=120`。
- 不建 `reflection.py` / `acceptance.py`（无门禁打回、无门禁报告，按约束 1/6 属条件必选）。

### 12.4 一个真实 bug（已修）

`actions/base.py:38-49` 的 `ActionResult.to_dict()` 会把 `data` 展开到顶层，
初版把 VC 状态快照放 `data["status"]` 会**覆盖**结果自身的 `status`，成功被误读成
`in_progress`。测试当场抓到，已改名 `data["vc_status"]`。
**后续写 Action 都要注意：`status` 是保留字段，不能塞进 `data`。**

### 12.5 验收状态

- 静态全过：plugin.json / trait 词表 / Action 自动注册且无重名 / command 为 str / 准入 Checklist / 9 项 VC 单测 + 60 项全量回归。
- **动态未做**：填 Key、起 sidecar、`VIDEOCLAW_ENABLED=true`、跑最小闭环、停服验证 blocked、director 回归。这 7 项需要真实环境与付费 Key，必须由人完成。

---

## 十三、追加落地：生图 / 生视频接 VC 现成 sandbox 接口（2026-11-19）

用户要求「生图、生视频先接上现有接口」——即直接调 VC 已有的单次能力接口，
不走 6 阶段项目流程。详见 `dev-notes/2026-11-19_05_生图生视频接VC_sandbox落地.md`。

### 13.1 选型：sandbox 同步接口，不用 pipelines

| | sandbox（采用） | pipelines（未采用） |
|---|---|---|
| 语义 | 5 个同步 POST，一次调用直接返回产物 | 异步多阶段短片流水线（LLM 分镜 → 多图 → TTS → 多段视频 → ffmpeg 拼接） |
| 生图 | `POST /api/sandbox/t2i`、`/i2i` | 无纯生图接口 |
| 生视频 | `POST /api/sandbox/video` | 生成"成片"，还需 LLM key / edge-tts / ffmpeg / 可能 Playwright |
| 客户端成本 | 1 POST + 1 次 `/code/` 下载 | POST → 轮询/SSE → 解析 artifacts → 下载 |

做「单次生图/生视频」用 pipelines 属于杀鸡用牛刀，故只接 sandbox。

### 13.2 契约要点（VC 源码实读）

- `api/schemas/sandbox.py:19-39`：`t2i{model,prompt,style,ratio}`、`i2i{...,image}`、
  `video{model,prompt,image,ratio,resolution,duration}`。`style` 实际不生效（`sandbox.py:299` 只写历史）。
- **成功/失败都是 HTTP 200**：`{success:true,...}` 或 `{success:false,error}`（`sandbox.py:331-333` 等）
  → 客户端必须查 `success` 字段，不能只看状态码。
- 生图取 `result[]`（相对 `result/...` 路径列表）；**生视频取 `video_path` 而非 `result`** ——
  `result` 是会过期的远端 URL（`models/video_dashscope.py:379`）。
- 静态挂载 `app.mount("/code", StaticFiles(directory=CODE_DIR))`（`api/app.py:52-53`），
  下载规则 = `GET {BASE}/code/<相对于 code/ 的路径>`。
- **VC 没有纯文生视频**：默认 `wan2.7-i2v` 及所有 provider 都要求首帧图
  （`models/video_dashscope.py:257`）。故 `vc_gen_video` 在缺 `image` 时自动先 `t2i` 出首帧，
  并把归一化后的路径拼回 VC 自己可访问的 `/code/` URL 传回（**两次付费调用**，已在 description 标注）。
- **Windows 路径 bug**：VC `_normalize_path`（`sandbox.py:56-73`）用 `path.startswith('/')` 判绝对路径，
  是 POSIX 假设；Windows 下返回 `result/G:\\...\\code\\result\\sandbox\\...`，直接拼 `/code/` 必然 404。
  → ADS 侧 `normalize_media_rel()` 统一兜底（反斜杠转正、取最后一个 `code/` 之后补成 `result/...`）。

### 13.3 改动

| 文件 | 内容 |
|---|---|
| `plugins/videoclaw/videoclaw_client.py` | 加 `get_models` / `resolve_sandbox_models` / `sandbox_t2i` / `sandbox_i2i` / `sandbox_video` / `media_url` / `normalize_media_rel` / `_require_success`；`_request` 支持自定义 timeout；`download_product` 支持远端 URL |
| `plugins/videoclaw/actions/vc_media.py` | `vc_gen_image`（t2i / 有参考图走 i2i）、`vc_gen_video`（缺首帧自动 t2i）；产物落 `works/<slug>/videoclaw/{image,video}/` |
| `backend/config.py` / `.env.example` | 加 `VIDEOCLAW_VIDEO_TIMEOUT=900`（生视频分钟级，Kling 最坏 600s + 下载，`VIDEOCLAW_TIMEOUT=600` 边界会先超时而 VC 后台仍在跑） |
| `backend/tests/plugins/test_videoclaw_media.py` | 17 项，全部 mock |

### 13.4 准入约束落实

- Action 名 `vc_gen_image` / `vc_gen_video` 加前缀，**不撞** ADS 公共 `gen_image` 与 director 的 `gen_video`；
  实测三个 `vc_*` Action 注册齐全、两个既有 Action 未受影响。
- `env_missing → blocked`（未启用 / 服务不可达），绝不 `*_failed`；VC 业务失败是 `env_missing=False`。
- `data["command"]` 为 `str`（`shlex.quote`），`task_id` 带 `TCMD-*`；文件名白名单 + 路径穿越回退。
- 模型名从 `GET /api/config` 动态取，不写死；长超时单独配置。

### 13.5 验收

- 17 项 VC media 单测 + 全量 77 项回归通过；Windows 坏路径归一化、HTTP 200 失败、
  `video_path` 优先、自动首帧、长超时、路径穿越、产物落 `works/` 均有覆盖。
- **动态仍未做**（需真实 Key 与起服务）：填 Key、`uv sync`、起 sidecar、`VIDEOCLAW_ENABLED=true`、
  跑 `vc_gen_image` / `vc_gen_video`、确认产物非空、停服验证 blocked。
- 修掉了测试自身的一个副作用：`repo_path=str(Path("."))` 会在 `backend/works/` 留残留文件，
  已改用 `tmp_path` 并清理。

---

## 十四、追加落地：MiniMax H3 云端生视频上提到系统公共层（2026-11-19）

用户要求「参考 `F:\A_Works\ComicAI` 的生视频接口，把 Minimax 云端也加进去」，
并明确「**这些接口 ADS 共用的，配置到系统配置中，不属于 Plugin，Plugin 可以直接适配调用接口**」。
经拍板：卡密钥为鼠鼠工具 `sk_...`、只接 MiniMax H3、**先不改现有 plugin，只建公共层**。

### 14.1 关键定性（避免误接）

ComicAI 里的「MiniMax 云端」**不是 MiniMax 官方 API**，而是第三方「鼠鼠工具」卡密中转：
- Base `https://www.runlive.top/mnmx`，鉴权头 `X-Card-Key: sk_...`，白名单放行制
  （`backend/app/api/v1/endpoints/video_mnmx.py:89`、`Docs/鼠鼠工具-视频生成API文档.md:11-14`）
- 无 `Authorization: Bearer`、无 GroupID、无 `file_id` retrieval（全项目零匹配）
- 任务名 `minimax_h3_v2` / `minimax_h3_multi_ref`，**不是** `T2V-01` / `MiniMax-Hailuo-*`
- 异步：提交 → 轮询（5s×180）→ `file-url` 取带时效签名直链
- 已知坑：签名直链可能是内网 IP（`Docs/DevLog/2026-11-05_10:45`），公共层照实抛错由调用方决定

**用户手上的官方 MiniMax API key 不能填在这里**。若将来要接官方 `/v1/video_generation`，
需在 `backend/cloud_video/` 另登记 provider，配置仍走系统配置。

### 14.2 架构：公共层，不属于任何 Plugin

依据 `docs/20261019_01_Action成套插件与公共工具边界方案.md:89`「任何项目的工单循环或聊天
都要用的留在公共模块」，以及 ADS 现状（`backend/image_processor.py` 是公共生图 client，
被 6+ 上层模块复用；`plugins/director/lightai_video.py` 反向依赖它）。

```
依赖方向（单向 DAG，公共层零 plugins.* import）：
  plugins/director/* ─┐
  plugins/videoclaw/* ─┼──▶ backend/cloud_video/ ──▶ backend/config.py (settings) + 标准库
  未来 Plugin ─────────┘         ✗ 不 import plugins / actions / database / events / git_manager
```

公共层**只做 transport + 协议编排**，抛分层异常（`CloudVideoUnavailable` 环境缺失 /
`CloudVideoError` 上游失败）；**不返回 `ActionResult`、不写时间轴、不判 `env_missing`** ——
这些是 Action/Plugin 层职责（准入规范约束 2/3，`docs/20261023_01_...:90-109`）。

### 14.3 改动

| 文件 | 内容 |
|---|---|
| `backend/config.py` | 新增系统配置分节 `MINIMAX_H3_BASE_URL` / `CARD_KEY` / `ENABLED` / `TIMEOUT` / `POLL_INTERVAL` / `MAX_POLLS`，注释标明是第三方卡密中转 |
| `backend/.env.example` | 补注释块（key 留空模板），标明真实 key 只写 `backend/.env`、不入库 |
| `backend/cloud_video/__init__.py` | 公开 API 与分层异常：`submit` / `query` / `file_url` / `ping` / `generate_video` / `CloudVideoFile` / `PROVIDERS` |
| `backend/cloud_video/client.py` | 纯 urllib + `asyncio.to_thread`；手搓 multipart；参数归一化；429/502/503/504 退避；轮询终止条件；`PROVIDERS` 注册表留扩展位 |
| `backend/tests/test_cloud_video.py` | 28 项，全部 mock HTTP |

**未改动** `plugins/director/*`、`plugins/videoclaw/*`（按用户选择「先不改，只建公共层」）；
未写入任何真实 key。

### 14.4 参数归一化（照鼠鼠文档 :33-83，避免上游 400 拒单）

- `resolution`：`0.4`/`1`/`2` = 480P/768P/1080P，`multi_ref` 强制降到 `1`
- `duration`：clamp 到 4–15s；首尾帧 + 1080P 最长 10s
- `aspect_ratio`：必须整串（如 `16:9 (Widescreen)`），非法值回退默认
- `task_name`：无参考图 → `minimax_h3_v2`；多参考 → `minimax_h3_multi_ref`
- 文件字段：`first_frame` / `last_frame` / `ref_0..5` / `ref_audio_0..2`

### 14.5 Plugin 适配调用范例（本轮只给范例，不改 plugin）

```python
from cloud_video import generate_video, CloudVideoUnavailable, CloudVideoError
from pathlib import Path

try:
    r = await generate_video(prompt="一只猫在草地上奔跑", duration=5,
                             dest=Path("works/my-slug/videoclaw/video/clip01.mp4"))
    # r = {task_id, status, credit_cost, url, filename, downloaded, path, bytes}
except CloudVideoUnavailable as e:
    # ← 调用方 Action 转成 env_missing=True / blocked，绝不 *_failed
    return ActionResult(success=False, error=str(e),
                        data={"env_missing": True, "command": command, "task_id": task_id})
except CloudVideoError as e:
    # ← 普通业务失败，env_missing=False
    return ActionResult(success=False, error=str(e),
                        data={"env_missing": False, "command": command, "task_id": task_id})
```

`data["command"]` 仍须是 `str`、外部调用走 `record_traced_command` 落时间轴 —— 都由
调用方 Action 负责，公共层不越界。

### 14.6 验收

- **28 项 `test_cloud_video.py` + 全量 105 项回归通过**：配置分流、参数归一化、multipart、
  403→Unavailable / 400→Error / 200+success:false→Error、429 退避重试、failed 状态、
  轮询超时保留 task_id、ping 403/404、一站式编排均有覆盖。
- 硬核对：`cloud_video/*.py` 除注释外**零** `plugins` / `actions` / `database` / `events` /
  `ActionResult` / `record_traced` 引用。
- **动态未做**（需真实卡密钥）：`backend/.env` 填 `MINIMAX_H3_CARD_KEY=sk_...` +
  `MINIMAX_H3_ENABLED=true` → `ping()` → 跑一次 `generate_video`。因白名单制，
  卡必须先被管理员放行，否则 403。

### 14.7 待办

1. 现有 plugin 适配到公共层（director 的 `lightai_video.py` / `gen_video.py`、videoclaw 的
   `vc_gen_video`），消除两份后端真源 —— **已于 §15 落地**。
2. 若要接 MiniMax **官方** API / 火山 Ark / LibTV / LiblibAI，在 `cloud_video/PROVIDERS`
   登记，配置仍走系统配置；不要塞进 plugin。
3. 可选：参照 `api/image_gen.py:200-215` 做「设置面板热更新 key + 回写 .env」。
4. 签名直链内网 IP 问题：必要时在 ADS 侧做一层代下代理。

---

## 十五、追加落地：director / videoclaw 适配公共层（2026-11-19）

用户拍板（AskUserQuestion）：改造深度 = **新增可选后端**（原有 lightai / libtv /
dreamina / VC sandbox 完全不动）；同时**补上 LightAI provider、统一后端真源**。

### 15.1 依赖方向（公共层零 plugins import，已硬核对）

```
plugins/director/*  ─┐
plugins/videoclaw/* ─┼──▶ backend/cloud_video/ ──▶ config.py + 标准库
                     │        └─(函数内延迟)─▶ image_processor（公共模块，非 plugin）
                     └──▶ plugins/director/work_package.py（CLI/brief 私有业务，留 plugin）
```

`cloud_video/lightai.py` 顶层只 import `config` + 标准库；`image_processor` 的
HTTP/信号量工具保持**函数内延迟 import**（沿用原实现），避免公共层顶层继承
`database`/`events` 等业务依赖。

### 15.2 公共层改动

| 文件 | 内容 |
|---|---|
| `cloud_video/lightai.py`（新增） | 从 `plugins/director/lightai_video.py` 逐行上提 LightAI 实现；新增 `generate(req, dest)` 统一结果结构 |
| `plugins/director/lightai_video.py` | 改为**兼容 shim**，re-export 公共层函数。保留 `gen_video.py:148,291` / `download_video.py:51,66` 的 import 路径与测试 monkeypatch 目标，行为零变化 |
| `cloud_video/client.py` | `PROVIDERS` 补 `lightai`；新增 `ALLOWED_PROVIDERS`（单一真源）、`normalize_provider`、`probe_provider`、`generate_video_with_provider(provider, ...)` 统一 dispatch |
| `cloud_video/__init__.py` | 导出上述新 API |

### 15.3 后端真源统一

- 公共层 `ALLOWED_PROVIDERS = ("lightai", "minimax_h3")` 是**唯一真源**。
- `plugins/director/backends.py`：`ALLOWED_BACKENDS = tuple(ALLOWED_PROVIDERS) + ("libtv","dreamina")`，
  CLI 后端仍是 director 私有业务；`_ALIASES` 补 `minimax/h3/mnmx/鼠鼠 → minimax_h3`；
  `probe_backend` 的云端探活委托 `probe_provider()`。
- `gen_video.py` 删除此前重复的 `_BACKENDS = ("lightai","libtv","dreamina","jimeng")` 字面量，
  改为 `from plugins.director.backends import ALLOWED_BACKENDS as _BACKENDS`（实测两者是同一对象）。
- `video_brief.json` 读取、成本锁、CLI 探活等 plugin 私有业务**未上提**。

### 15.4 两个 Plugin 的新增可选分支（原有路径完全不动）

| Plugin | 触发 | 走法 |
|---|---|---|
| director `gen_video` | `backend=minimax_h3`（或别名 minimax/h3/mnmx/鼠鼠） | `_run_cloud_provider()` → `cloud_client.generate_video_with_provider()`；做 ratio `16:9`→`16:9 (Widescreen)`、resolution `720p`→`1` 映射；`env_missing`/`command`/`task_id` 分流留 Action 层 |
| videoclaw `vc_gen_video` | `provider=minimax_h3` | `_run_cloud_provider()` → 同上；**不要求 VC sidecar 可用**（VC 未启用时也能用云端）。留空则走原 VC sandbox 路径 |

lightai 分支：实现已上提到公共层，但 director 仍通过 shim 调用，**参数/产物/失败分流零变化**，
`test_director_plugin.py` 的 monkeypatch 目标不变、105 项回归全通过。

### 15.5 一个实现坑（已修）

包级 re-export 是**静态绑定**：`__init__.py` 里 `from cloud_video.client import generate_video_with_provider`
会让 monkeypatch `cloud_video.client.generate_video_with_provider` 失效（首次尝试时测试真的打到了
runlive.top 拿到 401）。改为 Plugin 内 `from cloud_video import client as cloud_client` 再调
`cloud_client.generate_video_with_provider(...)`，即 patch **源模块**（与
`test_gen_image.py:26-28` 的教训一致）。修复后适配测试全程无网络痕迹。

### 15.6 验收

- 新增 `tests/plugins/test_cloud_video_adapters.py` **18 项** + 全量 **123 项回归全通过**。
- 覆盖：单一真源、别名归一化、双 provider 探活、lightai shim 等价性、dispatch 两路分流、
  director 新后端（成功 / 缺 key blocked / 未知后端仍拒 / lightai 分支行为不变）、
  videoclaw 新 provider（成功 / 不需 VC sidecar / 缺 key blocked / 默认仍走 VC sandbox）。
- 硬核对：`cloud_video/*.py` 零 `plugins.*` import；三个 `vc_*` Action 与 `gen_video`/`gen_image` 均无重名。

### 15.7 待办

1. 真实卡密钥下的端到端验收（填 `backend/.env` → 跑 `gen_video backend=minimax_h3` /
   `vc_gen_video provider=minimax_h3`）。
2. 若要接 MiniMax 官方 API / Ark / LibTV / LiblibAI，在 `PROVIDERS` 登记即可，Plugin 无需再改后端枚举。

---

## 十六、追加落地：生成任务排队机制（2026-11-20）

用户要求「生成任务有个排队机制，参考 ComicAI 实现一下」。三个拍板（AskUserQuestion）：
范围 = **只给 `cloud_video` 加信号量**；并发规则 = **照搬但时区可配**；名额粒度 =
**照搬全程占用**（提交+429 退避+轮询+下载一个名额到底）。

### 16.1 ComicAI 参考调研结论（只读，逐行核对）

- ComicAI 的排队**只有一块**：`frontend/src/api/index.ts:2551-2582` 的模块级手写信号量
  （`_h3cloudActive` 计数 + `_h3cloudWaiters` FIFO 数组 + `acquire/release`）。
  **后端没有任何通用调度器**——`video_mnmx.py:5` 明写「只做代发+透传，不缓存任务状态」，
  `generation.py` / `libtv.py` / `liblib.py` 是三份各自独立的内存结果表 + `create_task`，
  全仓 `asyncio.Queue` 零命中。
- 规则：闲时（`0<=h<8`）每账号 5 并发、白天 `Infinity`；一个名额从 acquire（`:2720`，try 之前）
  到 release（`:2791-2792`，finally）覆盖提交+429 重试+轮询+取直链全程。
- 三处**缺陷**（本次移植时修正，不照抄）：
  1. `new Date().getHours()` 用**浏览器本地时区**（`:2558`），服务端多机/多用户不一致；
  2. acquire 排队期间**不监听 abort**，只在被唤醒时才检查 `signal.aborted`（延迟取消）；
  3. 等待**无超时上限**，名额被慢任务占住时后来者永久挂起。
- 上游规则原文 `Docs/鼠鼠工具-视频生成API文档.md:22`，查询/下载各 1 次/秒限速见 `:18`。
- 行号提示：ADS `cloud_video/client.py` 头部注释里引用的 `index.ts:2504-2747` 是**旧行号**
  （ComicAI 该文件后续改动过），以本次调研的实际行号为准。

### 16.2 实现

| 文件 | 内容 |
|---|---|
| `A backend/cloud_video/queue.py` | `CloudVideoQueue`：时段感知 FIFO 信号量；`QueueStats` 可观测；`async with slot()` 全程占用 |
| `M backend/cloud_video/client.py` | 模块级队列单例 + `get_queue/set_queue/queue_stats`；`generate_video_with_provider()` 用 `async with get_queue().slot():` 包住两路 provider |
| `M backend/cloud_video/__init__.py` | 导出队列 API |
| `M backend/config.py` / `.env.example` | `MINIMAX_H3_QUEUE_ENABLED` / `IDLE_LIMIT=5` / `IDLE_START=0` / `IDLE_END=8` / `TZ=Asia/Shanghai` / `TZ_OFFSET=8` / `WAIT_TIMEOUT=900` |
| `A backend/tests/test_cloud_video_queue.py` | 18 项 |

**放在统一 dispatch 层**而非底层 `generate_video` / `lightai.generate`：
两个 provider 共用同一队列，且避免一次调用占两次名额（双重占用）。

### 16.3 与 ComicAI 的差异（有意为之）

| 项 | ComicAI | ADS |
|---|---|---|
| 时区 | 浏览器本地时区 | IANA 名显式配置（`ZoneInfo`），不可用时回退固定 UTC 偏移，绝不用服务器本地时区 |
| 取消 | 延迟取消（排队中不响应 abort） | `asyncio.Future` + `wait_for`，`task.cancel()` 即时唤醒并清理 waiter、归还名额 |
| 等待超时 | 无 | `WAIT_TIMEOUT=900`，到点抛 `CloudVideoUnavailable` → 调用方 `blocked`，文案明确「未提交，不会改打别的后端」 |
| 上限动态性 | 每次 acquire 读当前小时 | `limit_now()` 按配置时段动态返回，`0-8`/跨午夜（如 22-6）都支持 |
| 可观测 | 只显示计数，无排队位置/上限 | `QueueStats{active, waiting, limit, unlimited, idle_window, tz}` + `queue_stats()` 公开 API |
| 并发安全 | 单标签页闭包 | 所有状态读写在**无 await 的同步段**内，asyncio 单线程天然原子，无需 Lock（也避免跨 loop 绑定） |

### 16.4 验收

- 新增 **18 项**排队单测 + 全量 **141 项回归通过**。
- 覆盖：闲时 5 并发上限、白天不限、`0-8` 与跨午夜时段、显式时区（UTC16:00=上海00:00）、
  ZoneInfo 回退、FIFO 顺序、异常路径名额不泄漏、慢任务全程占用、取消即时唤醒无泄漏、
  等待超时与「未提交/不改打」文案、配置构造、dispatch 两路共用同一队列且各占一次名额。
- 修复测试自身一处 Python 3.14 兼容问题：`asyncio.run` 之外不能先建 `gather` 协程，
  改为 loop 内 `_gather()`。

### 16.5 边界与待办

1. 队列是**单进程内存态**（单 uvicorn worker 有效）。多 worker 需换 Redis 等跨进程队列 ——
   与 ComicAI `video_service.py:24` 的注释同一约束。
2. 排队粒度是「全程占用」：一个慢任务（最长 15min 轮询 + 429 重试）会占住名额，
   与 ComicAI 一致。若将来要更细，可拆「提交并发限流」与「查询 1 次/秒限速」两个限流器。
3. 真实卡密钥下的排队压测（闲时并发 6 个任务，确认第 6 个排队等待）。
4. 可选：把 `queue_stats()` 接到运维 API / 前端面板（ComicAI 的 TaskDrawer 只显示计数，
   这里已有完整 stats，接 UI 是纯展示工作）。




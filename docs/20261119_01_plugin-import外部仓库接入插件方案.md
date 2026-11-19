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

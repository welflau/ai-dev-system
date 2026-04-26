# CI/CD 环境管理合并 + 项目类型感知 Pipeline 方案

> 日期：2026-04-25
> 起因：用户反馈 CI/CD 页面和环境管理页面内容重叠，且当前 pipeline 逻辑只适合网页项目，UE / 游戏项目需要完全不同的流水线
> 版本上下文：v0.19.x（v0.17 trait-first 已实现 SOP 层，CI 层未下沉）

---

## 1. 问题分解

### 1.1 两个页面为什么重叠

| 维度 | CI/CD 页面（`#tab-cicd`） | 环境管理页面（`#tab-settings-envs`） |
|---|---|---|
| HTML 位置 | `index.html:425-443` | `index.html:742-755` |
| 核心内容 | 三阶段流水线图 + 构建历史 + 「构建 develop/master」「部署」按钮 | dev/test/prod 三环境卡片 + 状态 / 端口 / 路径 / 部署按钮 |
| 后端 API | `api/ci.py`（status/builds/trigger） | `api/projects.py`（environments/deploy/stop） |
| 渲染函数 | `app.js:9264 loadCICD()` | `app.js:1608 loadEnvironments()` |

**重叠点**：
- 两处都能「手动触发部署」
- 两处都涉及"develop → test，main → prod"的分支/环境映射
- 部署后的结果（端口、URL、分支）两边都在读

**分工不清**：
- CI/CD 页重点在"**事件/时间维度**"——每次构建的历史
- 环境管理重点在"**状态维度**"——当前 3 个环境各自在什么分支、啥状态
- 但触发入口重复、分支-环境映射重复

### 1.2 当前 pipeline 为什么只适合网页项目

代码 `backend/ci_pipeline.py:179-390` 硬编码了三类构建：

```
develop_build → 语法 + 冒烟测试 → 合入 main → deploy test 环境
master_build  → 集成测试 → 触发 deploy prod
deploy        → 生成 Dockerfile + docker-compose
```

配合 `agents/deploy.py:151-156` 启 Python `http.server` 在 9000+ 端口提供静态文件服务。

对**网页项目**（category:app + platform:web）这一套刚好：
- 分支合并模型是 feat/* → develop → main
- 冒烟测试跑 lint + Playwright
- 部署 = 起 http 服务给用户预览

对**UE 项目**（category:game + engine:ue5）就完全错位：
- 「develop 合入 main」对 `.uasset` 二进制文件容易冲突（Git 对二进制无法自动三方合并）
- 「起 http.server」对 UE 项目毫无意义
- 真正的"构建"是 UBT（我们已有 `UECompileCheckAction`），"部署"是 **Packaging**（`RunUAT.bat BuildCookRun` 打 `.exe`）
- 真正的"环境"不是 dev/test/prod 三个端口，而是 **Editor / PIE / PackagedClient / DedicatedServer** 四种运行形态

对**后端服务**（category:service + platform:server）又是另一套：
- Docker build + push registry + k8s apply / systemctl restart
- "环境"按 namespace 区分（dev.example.com / staging / prod cluster）

### 1.3 Trait-first 没下沉到 CI 层

- `ci_pipeline.py` 压根没读 `project.traits`
- `deploy.py` 同样
- SOP fragments 有 `engine_compile.yaml` / `play_test.yaml` / `asset_gen.yaml` / `i18n_check.yaml` 等 trait-gated 片段，**但没有 deploy 类 fragment**
- 导致 v0.17 的 trait-first 架构只管到 SOP+Skill+Agent 层，CI/部署层是"trait 盲"的

---

## 2. 设计目标

1. **一个页面一件事**：把 CI/CD 和环境管理合成一个 "交付 & 环境" 页，同一入口看构建历史 + 当前环境状态 + 手动触发
2. **Pipeline 按 traits 动态分流**：Web / UE / Godot / Unity / Service 各走各的 pipeline 实现，统一接口
3. **环境概念可扩展**：不再硬编码 dev/test/prod 三环境，由 strategy 各自定义；UE 可能是 Editor/PackagedWin64/DedicatedServer，服务项目可能是 staging/canary/prod
4. **复用 v0.17 trait-first 模式**：新增 pipeline strategy 跟 SOP fragment 同构（trait 条件注册 + 组合）

---

## 3. 架构设计

### 3.1 CI Strategy 抽象（后端核心）

新增 `backend/ci/strategies/base.py`：

```python
class CIStrategy(ABC):
    """项目类型感知的 CI pipeline 策略接口"""
    name: str                              # "web" / "ue" / "unity" / "service" / ...
    required_traits: Dict                  # {any_of: [...], all_of: [...]} 跟 SOP fragment 同语义
    priority: int                          # 多个 strategy 命中时按优先级选

    @abstractmethod
    def pipeline_stages(self) -> List[PipelineStage]:
        """返回本 strategy 的 pipeline 阶段定义（给 UI 渲染用）"""

    @abstractmethod
    def environment_specs(self) -> List[EnvSpec]:
        """本 strategy 支持的环境列表（给 UI 环境卡片用）"""

    @abstractmethod
    async def trigger_build(self, project_id: str, build_type: str, **kwargs) -> Dict:
        """触发一次构建（由 api/ci.py 调用）"""

    @abstractmethod
    async def deploy_environment(self, project_id: str, env_name: str, **kwargs) -> Dict:
        """部署到指定环境"""

    @abstractmethod
    async def get_environment_status(self, project_id: str, env_name: str) -> Dict:
        """取某环境当前状态（给 /environments API 用）"""
```

数据类：

```python
@dataclass
class PipelineStage:
    id: str                    # "syntax_check" / "ubt_compile" / "playtest" / "package"
    name: str                  # 显示名 "UBT 编译"
    icon: str                  # emoji
    description: str
    blocking: bool             # 失败是否阻塞后续阶段

@dataclass
class EnvSpec:
    name: str                  # "dev" / "test" / "prod" / "editor" / "packaged_win64"
    display_name: str          # "开发环境" / "打包 Win64 Client"
    branch_binding: Optional[str]  # None 表示不绑定分支（如 UE packaged）
    icon: str
    description: str
```

### 3.2 三个初始 Strategy

#### 3.2.1 `ci/strategies/web.py`（从 `ci_pipeline.py` 抽出现有逻辑）

```python
class WebCIStrategy(CIStrategy):
    name = "web"
    required_traits = {"any_of": ["platform:web", "category:app"]}
    priority = 50

    def pipeline_stages(self):
        return [
            PipelineStage("syntax_check", "语法检查", "🔍", "ESLint + Playwright smoke", True),
            PipelineStage("integration_test", "集成测试", "🧪", "端到端场景验证", True),
            PipelineStage("deploy_test", "部署测试", "🚀", "起 http.server 到 test 环境", False),
            PipelineStage("deploy_prod", "部署生产", "🌐", "合入 main + 部署 prod", False),
        ]

    def environment_specs(self):
        return [
            EnvSpec("dev", "开发环境", "HEAD", "⚡", "跟当前分支实时同步"),
            EnvSpec("test", "测试环境", "develop", "🧪", "develop 构建通过后自动部署"),
            EnvSpec("prod", "生产环境", "main", "🌐", "main 日构建触发"),
        ]

    # trigger_build / deploy_environment / get_environment_status 迁移自现有 ci_pipeline.py
```

#### 3.2.2 `ci/strategies/ue.py`（新）

```python
class UECIStrategy(CIStrategy):
    name = "ue"
    required_traits = {"any_of": ["engine:ue5", "engine:ue4"]}
    priority = 100    # 高于 web 的 50，命中 UE 就走 UE

    def pipeline_stages(self):
        return [
            PipelineStage("ubt_compile", "UBT 编译", "🔧", "复用 UECompileCheckAction", True),
            PipelineStage("playtest", "Automation 测试", "🎮", "复用 UEPlaytestAction（v0.19 ②）", True),
            PipelineStage("package_editor", "打包 Editor", "📦", "RunUAT BuildCookRun + Target=Editor", False),
            PipelineStage("package_client", "打包 Client", "🎯", "Shipping/Development 客户端", False),
            PipelineStage("package_server", "打包 Server", "🖥️", "DedicatedServer（若有）", False),
        ]

    def environment_specs(self):
        return [
            EnvSpec("editor_live", "Editor 联调", None, "⚡", "UE Editor 进程状态（v0.20 UCP 接入后能精准反映）"),
            EnvSpec("packaged_win64", "打包 Win64 Client", "main", "📦", "Staging build 产物"),
            EnvSpec("dedicated_server", "Dedicated Server", "main", "🖥️", "可选：运行 DedicatedServer 实例"),
        ]

    async def trigger_build(self, project_id, build_type, **kwargs):
        # build_type=syntax → 单独跑 UBT（不打包）
        # build_type=full   → UBT + Playtest + Package
        # 内部调用 UECompileCheckAction + UEPlaytestAction + RunUAT
```

UE 打包调用链（放入新 Action `actions/ue_package.py`）：
```
<Engine>/Engine/Build/BatchFiles/RunUAT.bat BuildCookRun
  -project=<.uproject>
  -platform=Win64
  -configuration=Shipping
  -cook -stage -pak -archive -archivedirectory=<out>
```

#### 3.2.3 `ci/strategies/default.py`

兜底——现有 `web.py` 行为的 light 版本，不建议命中但别让系统崩。

### 3.3 Strategy Loader

`backend/ci/loader.py`:

```python
class CIStrategyLoader:
    def __init__(self):
        self._strategies: List[CIStrategy] = []
        self.load_all()

    def load_all(self):
        # 扫 ci/strategies/*.py，import，按 priority 降序
        ...

    def pick_for_project(self, project_id: str) -> CIStrategy:
        proj = db.fetch_one("SELECT traits FROM projects WHERE id = ?", project_id)
        traits = json.loads(proj["traits"])
        for s in self._strategies:   # 已按 priority 降序
            if self._traits_match(traits, s.required_traits):
                return s
        return DefaultCIStrategy()
```

`ci_pipeline.py` 的后台调度器改造：遍历项目 → `loader.pick_for_project(pid)` → `strategy.trigger_build(...)`。

### 3.4 API 统一层

`backend/api/ci.py` 现有端点保留，**内部转发到 strategy**：

```python
@router.post("/{project_id}/ci/builds/trigger")
async def trigger(project_id, req: TriggerRequest):
    strategy = ci_loader.pick_for_project(project_id)
    return await strategy.trigger_build(project_id, req.build_type, **req.options)
```

新增 meta 端点：

```python
@router.get("/{project_id}/ci/pipeline-definition")
async def pipeline_def(project_id):
    """返回 {strategy_name, stages[], environments[]}，给前端动态渲染用"""
    s = ci_loader.pick_for_project(project_id)
    return {
        "strategy": s.name,
        "stages": [stage.__dict__ for stage in s.pipeline_stages()],
        "environments": [env.__dict__ for env in s.environment_specs()],
    }
```

环境相关端点从 `api/projects.py` 迁到 `api/ci.py` 下（同源）：
- `GET /api/projects/{pid}/ci/environments` ← 合并现有 `/environments`
- `POST /api/projects/{pid}/ci/environments/{env}/deploy`
- `POST /api/projects/{pid}/ci/environments/{env}/stop`

### 3.5 前端：合并成一个"交付 & 环境"页

```
┌─────────────────────────────────────────────────────────┐
│ 🚀 交付 & 环境        [Strategy: Web App]  [刷新]       │
├─────────────────────────────────────────────────────────┤
│ Pipeline（按 strategy 动态生成）                        │
│                                                         │
│  🔍 语法检查 ─▶ 🧪 集成测试 ─▶ 🚀 部署 test ─▶ 🌐 prod │
│  [●完成]       [●运行中]        [○待定]      [○待定]   │
│                                                         │
│  最近构建                         [手动触发 ▾]          │
│  ┌─────────────────────────────────────────┐           │
│  │ #42  develop_build  ✅  3m  8a7b3c       │           │
│  │ #41  master_build   ✅  2m  70b3437      │           │
│  │ ... (10 条)                              │           │
│  └─────────────────────────────────────────┘           │
│                                                         │
├─────────────────────────────────────────────────────────┤
│ 环境（按 strategy 动态生成）                            │
│ ┌─────────────┐  ┌─────────────┐  ┌─────────────┐      │
│ │ ⚡ dev      │  │ 🧪 test     │  │ 🌐 prod     │      │
│ │ feat/new    │  │ develop     │  │ main        │      │
│ │ :9000       │  │ :9201       │  │ :9280       │      │
│ │ [打开] [停] │  │ [打开] [停] │  │ [打开] [停] │      │
│ └─────────────┘  └─────────────┘  └─────────────┘      │
└─────────────────────────────────────────────────────────┘
```

UE 项目加载时会换成：

```
Pipeline:
  🔧 UBT 编译 ─▶ 🎮 Automation ─▶ 📦 打包 Editor ─▶ 🎯 打包 Client
  
环境卡片:
  ⚡ Editor 联调    📦 打包 Win64    🖥️ DedicatedServer
```

前端实现（替代 `loadCICD` + `loadEnvironments`）：

```js
async function loadDeliveryPage() {
    const def = await api(`/projects/${currentProjectId}/ci/pipeline-definition`);
    renderPipelineHeader(def.strategy);        // 顶部 badge
    renderPipelineStages(def.stages);          // 阶段进度条
    renderBuildHistory();                       // 跟原 loadCICD 的表格
    renderEnvCards(def.environments);          // 按 strategy.environments 生成卡片
}
```

原 `#tab-cicd` 和 `#tab-settings-envs` 合并到 `#tab-delivery`。环境管理 tab 从「设置」里移除。

### 3.6 SOP 集成

给每种 strategy 开一个 SOP deploy fragment，打通「工单 → SOP 驱动 → strategy 触发」链路：

```yaml
# backend/sop/fragments/deploy_web.yaml
id: deploy_web
name: 部署（Web）
insert_after: acceptance
required_traits:
  any_of: [platform:web, category:app]
stage:
  agent: DeployAgent
  action: run_ci_deploy          # 新 action 转发到 strategy
  trigger_on: deployment_pending
  success_status: deployed
```

```yaml
# backend/sop/fragments/deploy_ue.yaml
id: deploy_ue
name: 打包（UE）
insert_after: play_test
required_traits:
  any_of: [engine:ue5, engine:ue4]
stage:
  agent: DeployAgent
  action: run_ci_deploy
  trigger_on: packaging_pending
  success_status: packaged
  reject_status: packaging_failed
  reject_goto: development
  config:
    platform: Win64
    configuration: Shipping
```

这样 UE 工单 `play_test_passed` → `packaging_pending` → `DeployAgent.run_ci_deploy` → UECIStrategy → RunUAT，失败了自动走 reject_goto 回 DevAgent.fix_issues。

---

## 4. 实施路径（分阶段）

| Phase | 内容 | 依赖 | 估时 |
|---|---|---|---|
| **A** | CIStrategy 抽象 + Loader；把现有逻辑抽到 `WebCIStrategy`；API 转发层（行为完全兼容） | 无 | 1 天 |
| **B** | 前端「交付 & 环境」页合并：`loadDeliveryPage()` + 按 strategy 动态渲染 + 原两个 tab 去除 | A | 1 天 |
| **C** | `UECIStrategy` + `actions/ue_package.py`（RunUAT） + 测试 | A | 2 天 |
| **D** | SOP deploy fragments（web / ue）+ DeployAgent.run_ci_deploy 统一转发 | A + C | 1 天 |
| **E** | Smoke test：Web 不退化 + UE 打包能触发 | C + D | 1 天 |
| **F（可选）** | `ServiceCIStrategy`（docker build + push）；`UnityCIStrategy` stub | A | 按需 |

**合计 ~6 天**（照 v0.18/v0.19 经验可能 2-3 天）。**A + B 一批**先跑通"页面合并 + Web 不退化"，这是最小闭环；**C + D** 二批补 UE 流水线。

---

## 5. 风险与考虑

### 5.1 兼容性

- 现有 `/api/projects/{pid}/ci/*` 和 `/environments` 端点都保留（内部转发）
- 老前端代码（如果有第三方用）仍可工作
- Phase A 完成时 Web 项目行为必须 **零差异**，这是验收 gate

### 5.2 trait-first 空 trait 兜底

老项目可能 `traits=[]`，按匹配规则命中不了任何 strategy → 走 `DefaultCIStrategy`（等同 Web 的简化版）。这跟 v0.17 SOP 对 empty traits 的处理思路一致。

### 5.3 UE 打包耗时

`RunUAT BuildCookRun -pak` 首次要 10-30 分钟（cook + shader 编译）。超时默认给 1800s，SOP config 可覆盖。必须有进度 SSE（类似 `ue_compile_log`）否则用户以为挂了。

### 5.4 环境数量可变

Web 固定 3 环境，UE 可能 2-4 个，Service 可能跨 k8s 多集群。前端卡片渲染要按后端返回的 `environments[]` 动态生成（不要硬编码 3 列 grid）。

### 5.5 ci_pipeline.py 后台调度器的改造

现在它固定每 60s 轮询所有项目扫 develop 新提交。改造后按每项目的 strategy 决定"要不要轮询"和"轮询什么"。UE 项目可能根本不需要这种轮询（因为 UE 开发模型不同），可以让 strategy 声明 `supports_auto_build = False`。

---

## 6. 对比现状的价值

| 维度 | 现状 | 改造后 |
|---|---|---|
| 页面数 | 2（CI/CD + 环境） | 1（交付 & 环境） |
| 对 Web 项目 | ✅ 工作 | ✅ 工作（Phase A 零差异） |
| 对 UE 项目 | ❌ 会荒谬地起 http.server | ✅ UBT + Automation + Package 流水线 |
| 对新项目类型（Godot/Unity/Service） | ❌ 得改核心代码 | ✅ 新增 strategy 文件即可 |
| Pipeline 定义 | 硬编码在 ci_pipeline.py | 声明在 strategy 类（跟 SOP fragment 同构） |
| 环境定义 | 硬编码 dev/test/prod | 由 strategy 动态声明 |
| SOP 与 CI 打通 | ❌ 分离 | ✅ SOP deploy fragment 驱动 strategy |

---

## 7. 一句话总结

**CI/CD + 环境管理合成"交付 & 环境"一页**，后端抽 `CIStrategy` 接口让 Web / UE / 服务各走各的 pipeline 实现，跟 v0.17 trait-first 架构同构。Phase A+B 一批跑通"页面合并 + Web 零退化"，Phase C+D 二批把 UE 打包链路接上，全程 ~6 天。

**是否立即做**：建议放在 v0.19 稳定（UBT 编译修完 + 真机 playtest 过一次）之后。当前优先级低于修 v0.19 的 asyncio subprocess 挂起 bug 和 TestFPS 编译闭环。

---

*2026-04-25 · 对应用户问题「CI/CD 和环境管理页面重叠 + 项目类型差异化 pipeline」*

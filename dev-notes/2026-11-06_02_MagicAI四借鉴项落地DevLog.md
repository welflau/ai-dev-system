# DevLog：MagicAI 四借鉴项落地

> 日期：2026-11-05 ~ 2026-11-06
> 关联：`docs/20261105_05_借鉴落地开发计划.md`（总计划）、`docs/20261105_01~04`（对标分析）
> 提交：`6c02048`

本次会话从 MagicAI 的对标分析（`_01`~`_04`）收敛出 4 个可借鉴项，逐项落地。本 DevLog 记录第 1~4 项的开发过程（Phase 2 的 DevLog 见 `2026-11-06_01`）。

---

## 第 1 项：路径纠偏（fix_output_path）

### 探索发现

`ue_mcp_server.py::_ue_import_asset_impl` 已有两道校验：
- ✅ UE 内路径白名单（`/Game/` 前缀，:308）
- ✅ 本地文件存在（`.exists()`，:299）

但**缺**：
- ❌ `resolve()` 归一化
- ❌ 越权拦截（白名单根目录）
- ⚠️ 路径转义（`abs_path` 直接 f-string 拼进 UE Python 代码）

风险点：`ART_ASSETS_LOCAL_PATH` 未配置时，`file_path` 直接当绝对路径（:287 `elif rel_path: abs_path = rel_path`），无目录约束。

### 改动

在 `abs_path = abs_path.replace("\\", "/")` 之后插入（+15 行）：
- `_P(abs_path).resolve()` 归一化
- 白名单根目录：`ART_ASSETS_LOCAL_PATH` 或 `DATA_DIR/session_materials`
- 越界 → 拒绝导入

### 验证

- 越权路径（`C:/Windows/...`）→ 拒绝 ✅
- 合法路径 → 放行 ✅

---

## 第 2 项：AIGC 接入 ArtistAgent（方案 C）

### 探索发现（关键矛盾）

`generate_assets.py::_resolve_one` 已有 fallback 链「搜库 → 占位图」，缺 AIGC 中间层。

**矛盾**：`generate_assets.py:9-11` 注释写"系统当前没有接入图像模型"，但 `image_processor.py` 早已接入 LightAI（`request_image` 默认 `requester="ArtAgent"`，image_processor.py:592）——注释过时，且 AIGC 能力默认就是给美术设计的，只是从没接上。

### 改动

1. `_resolve_one` 签名加 `project_id`/`ticket_id`/`allow_aigc`
2. 未命中本地库后投递 `image_processor.request_image`（**异步投递**，不阻塞流水线）
3. 占位图照出兜底，生图完成后由 image_processor 自动入库 art_assets
4. `asset_gen.yaml` 加 `use_aigc: false`（默认关，生图有成本）
5. `_render_manifest` 补 `aigc_tag` 字段渲染

### 关键决策

**异步投递而非同步等待**：生图几十秒/张，同步会拖垮工单流水线。`request_image` 投递后立即返回 `[IMG_PENDING:id]`，占位图照出，后台生图完成后回填。

### 验证

- `use_aigc=true` 未命中 → 投递（带 aigc_tag + requester=ArtAgent）✅
- `use_aigc=false` → 不投递 ✅
- 命中本地库 → 不投递（搜库优先，代码强制）✅

---

## 第 3 项：请求分类前置层

### 探索发现

ADS 的 `start_from` 三档（`pending`/`architecture_done`/`development_in_progress`）机制**已完整存在**（models.py:296 + api/tickets.py:1206 + 规范层钩子），但依赖 LLM 判断或人工指定，**无代码强制分类**——正是 MagicAI 反面教训"优先级只在 prompt"的同类问题。

对齐 MagicAI 的 Phase -1（agent_session.py:202-231 + agent_session_config.py:60-124）：
- `_MODIFY_INDICATORS` / `_NEW_PROJECT_INDICATORS` 词表（原文）
- `MODIFY_KEYWORD_AGENT_MAP` 关键词评分（映射 ADS 5 个 Role）

### 改动

1. 新建 `ticket_classifier.py`：纯函数 `classify_start_from` + 词表 + 评分
2. `create_direct_ticket` 接入：默认 `pending` 时自动分类，用户显式指定优先

### 关键决策（实测修正）

初版"判不准 → architecture_done"被测试抓出 bug：短消息启发式（`len < 100`）会把"重构整个架构"这类**短标题大改**误判为小改。修正为**判不准一律 `pending`**（严格保守，宁可多跑不可漏做）。

### 验证

10 用例全过（bugfix/新建词/纯代码修改/涉及美术设计/空标题/判不准）。

---

## 第 4 项 Phase 1：QA 报告渲染

### 探索发现

`UEPlaytestAction`（plugins/ue5/actions/ue_playtest.py）**已经把引擎日志解析成结构化结果**（`_parse_automation_output` 抽出 tests/summary/errors），这是 MagicAI 的核心难点，ADS 已做完。缺的是**把结构化证据渲染成规范报告**。

### 改动

1. `test.py::run_playtest`：拿到结果后渲染 `playtest-report.md`
2. 新增 `_render_playtest_report` + `_grade_playtest`（A-F 评级）

### 验证

4 场景（失败/通过/模块错误/评级）。

---

## 通用发现

- 四个改动都用 `py_compile` + 针对性 mock 脚本验证。
- 提交时用 `git add -p` 精确排除工作区里混入的非本轮改动（`_run_registered_action` 插件 Action 注册，属其他会话的工作）。
- 验证脚本 `_verify_borrow_changes.py` 保留在 backend/ 下（符合项目 `_test_*.py` 惯例）。

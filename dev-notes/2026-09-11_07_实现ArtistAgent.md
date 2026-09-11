# DevNote · 2026-09-11（五）

**类型**: 实现 ArtistAgent，恢复 asset_gen 阶段
**状态**: 已落地，27 项断言全绿（含真实 33000 条资产库检索）
**前置**: `dev-notes/2026-09-10_01_UE工单流转闭环修复.md`（该 note 停用了 asset_gen）

---

## 一、背景

`asset_gen.yaml` 声明 `agent: ArtistAgent`，但这个类从来没实现过。
一旦 fragment 被组装进 SOP，orchestrator 因 "Agent 不存在" 直接 return，
工单卡在 `architecture_done` 反复重试直到死循环。09-10 那次修复用一个
假 trait `_disabled:artist-agent-not-implemented` 把它关停了。

本次补齐实现并恢复。

---

## 二、职责划分

系统里已有 `ArtAgent`（美术**设计**），容易混淆，所以明确切分：

| Agent | 回答的问题 | 产出 |
|---|---|---|
| ArtAgent | **需要什么资产** | 视觉规范 + `asset_manifest.yaml`（全是 `status: pending`）|
| ArtistAgent | **资产从哪来** | 检索资产库 → 命中即用；未命中 → 占位图 |

SOP 位置：`art_design_done → architecture → asset_gen → development`

---

## 三、实现

```
backend/agents/artist.py              ArtistAgent（SINGLE 模式，一个 action）
backend/actions/generate_assets.py    GenerateAssetsAction（核心逻辑）
```

三条落地路径：

| 路径 | 条件 | 结果 |
|---|---|---|
| `sourced` | 资产库检索命中且评分 ≥ 0.6 | 记录库内路径 + 匹配度 |
| `placeholder` | 未命中且 SOP 开了降级 | 生成洋红斜纹 PNG |
| `manual_required` / `not_found` | 音频等非图像类 / 关降级 | 如实标记，交人工 |

**刻意没做 AI 图像生成**：系统尚未接入图像模型。写一个"假装生成"的分支
只会产出空文件，让下游误以为资产已就绪。真实 AIGC 落地后在
`_resolve_one` 加一条来源分支即可，Agent 不用动。

**占位图故意做成洋红斜纹**（缺失资产的行业惯例色）+ 标注 "PLACEHOLDER"，
避免被误当成正式资产混进交付物。

---

## 四、检索算法：被测试逼着改了三轮

这部分是本次最花时间的地方，三轮都是**测试暴露了我自己没看出的问题**。

### 第一版：逐词 LIKE，命中即返回

测试输出：

```
PASS  资产库命中 arrow_up → a-arrow-down
```

我把它判成了 PASS。但要的是**向上**箭头，匹配到的是**向下**箭头 —— 假阳性。

根因：`arrow_up` 拆成 `[arrow, up]`，第一个词 `arrow` 就撞上 `a-arrow-down`，
`up` 根本没参与判断。33000 条库里单词 LIKE 几乎必然命中垃圾。

> 教训：断言写成"有没有返回结果"是无效断言，必须断言**语义正确性**。
> 后来把用例改成「不能匹配到含 down 的资产」才抓出问题。

### 第二版：召回 + 评分 + 阈值 + 反义词否决

改成召回 60 条候选、按 id 词覆盖率打分、低于 0.6 宁可走占位图，
并对 up/down、on/off、open/close 等做反义否决。

结果 `settings_gear` 反而找不到了：

```
FAIL  settings_gear 精确命中 → (score=None)
库里正确答案 `settings` 只覆盖 id 的 1/2 → 0.35 分被阈值挡掉
```

图标库里 `gear` 本就是 `settings` 的同义描述词，不该强制两词都命中。

### 第三版：加"资产名整体等于某 id 词 → 0.85"规则

`settings_gear` 修好了，但 `zzz_nonexistent_thing_xyz` 又开始误命中 ——
库里恰好有个叫 `zzz` 的图标，单词名命中 0.85。

最终收窄为 `len(id_tokens) <= 2`：id 只有两个词时，命中其中一个算强信号；
四个词的 id 蹭中一个不算。

### 最终效果（真实库验证）

```
arrow_up       → arrow-up          （不再错配 arrow-down）
settings_gear  → settings  0.85    （同义词命中）
volume_on      → volume            （不含 off）
panel_open     → panel-bottom-open （不含 close）
zzz_nonexistent_thing_xyz → 无匹配，走占位图
```

---

## 五、验证（27 项）

**A. Action 单测（真查资产库）**

清单解析 / PyYAML 缺失时行解析回退 / 关键词抽取 / PNG 合法性 /
反义词否决 3 例 / 三路径全覆盖 / 产物文件 / `_media_files` 通道 /
manifest 三种状态回写 / 音频不产占位图 / 关闭降级 / 空清单不阻断

**B. SOP 与注册**

asset_gen 已启用 / 链路 `architecture_done → assets_ready → development` 不断 /
ArtistAgent 已注册 / **SOP 引用的所有 Agent 都已注册**（防再犯同类错）/
web 项目不触发（不误伤）/ orchestrator 有结果分支

---

## 六、改动清单

```
backend/agents/artist.py                    新增
backend/actions/generate_assets.py          新增
backend/agent_registry.py                 ~ 注册 ArtistAgent
backend/sop/fragments/asset_gen.yaml      ~ 移除假 trait，恢复启用
backend/orchestrator.py                   + ArtistAgent 结果分支（→ assets_ready）
backend/requirements.txt                  + Pillow>=10.0.0
```

orchestrator 分支是必须的 —— 没有它会落到函数末尾
`else: new_status = current_status`，状态不推进导致死循环
（与 09-10 修 UEEditorAgent 时踩的是同一个坑）。

---

## 七、待办

- **未经真实工单验证**：本次为单元级 + SOP 组装级验证，没跑完整流转。
  真实场景下 ArtAgent 产出的 manifest 条目命名风格可能与测试用例差异较大，
  检索命中率待观察
- **检索仅覆盖 icon/sprite 类**：库里 27784 个 icon、3141 个 sprite，
  但 model/animation/hdri 的匹配规则未针对性调优
- **音频/字体资产无来源**：manifest 里这类条目一律 `manual_required`。
  `art_asset_searcher.py` 里有 Pexels/Polyhaven 的接入代码但缺 API key
- 09-11_02 剩余：④插库建单绕过 feat 分支（测试方法问题）
- 09-11_03 遗留：OpenSpec Propose 被 300s kill 后半成品是否可用（需真实 LLM）

---

*相关：`dev-notes/2026-09-10_01`、`backend/actions/write_art_design.py`*

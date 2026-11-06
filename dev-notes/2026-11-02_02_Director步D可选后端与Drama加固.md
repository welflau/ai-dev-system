# Director 步 D：可选后端与 Drama 加固（2026-11-02）

2026-11-02

方案：`docs/20261101_02_Director视频插件套件方案.md` §9.6 / §十 / §十三步 D
前置：步 A–C 已上架；`2026-11-02_01` 只开了 x-workflow.agent 口，与本步无关。

## 一、步 D 要关掉的三个口子

步 C 把 LightAI `gen_video` 跑通了，但三件事仍是文档愿望：

1. **非 LightAI 后端**被写成「第一期未启用」，指定 `libtv` 也会被这句话挡掉；未知名字还会**静默改成 lightai**。
2. Drama 的场景卡、连续性矩阵、三视图只写在 SKILL.md 里，LLM 跳过仍能发 `confirm_video_gate`。
3. Explainer 封面 `video_cover` 有 kind、有 glob，交付 skill 却不生图；polish 工单会把七段 skill 全跑一遍。

## 二、后端：探测真跑，失败不换

### 选择顺序（`backends.resolve_backend`）

```
用户 tool 参数 backend
  → video_brief.json.backend
  → lightai
```

未知名字原样返回，由 `gen_video` 报错。**禁止**再写成 `if backend not in _BACKENDS: backend = "lightai"`。

### 三条后端

| 后端 | 可用条件 | 生成 |
|---|---|---|
| lightai | `LIGHTAI_API_KEY` | 步 C 已有 |
| dreamina | 本机 `dreamina` / `dreamina.cmd` | `text2video` 或 `multimodal2video` → `query_result --download_dir` → 改名为 `片段NN.mp4` |
| libtv | 本机 `libtv` | **只探测** `libtv version`。无 `projectUuid` 或需要实时 schema 时停止，不代跑过期 `libtv node` 快照 |

`jimeng` 是 dreamina 的别名。与 LightAI 即梦引擎不是同一条登录。

CLI 用 argv 列表，不走 `shell=True`。参考文件必须是本地路径；HTTP URL 直接失败，而不是丢掉参考后当纯文生。

### 成本锁

`apply_cost_lock`：Mode 为 cinematic-drama 时，分辨率不是 720p、或模型名带 2.5 → 失败（`cost_lock: true`）。只有 `allow_cost_unlock=true` 才放行。时长仍封顶 15 秒。失败不降级、不换后端。

### 时间轴

`probe_backend` / `gen_video` 的 command 仍是 `str`，走 `record_traced_command`。缺 CLI 的 `env_missing` 与缺 Key 同级，调用方映射 blocked。

## 三、Drama 自检：文件，不是自觉

`mode_check.check_mode_assets` / `check_gate`：

| Mode | visual 门槛 |
|---|---|
| Explainer | 定稿旁白 + character-bible（可写「无关键人物」） |
| Storytime | 同上 + 至少一张人物参考 |
| Drama | 片段表、场景卡、场景图、人物图、音色计划、连续性矩阵（Markdown 表）、生成锁 |

工作包模板带「Drama 必填」等库存字样。自检把库存稿当缺口，init 之后立刻发确认卡会失败。这是故意的。

`confirm_video_gate` 增加 `gate=brief|script|visual|clip`。指定后先自检，不齐则 `waiting_human=false`。LLM 跳过 `check_mode_assets` 也发不出人审卡。

不新增 `continuity_matrix` kind：矩阵是 Drama 内部清单，不是跨 skill 总线产物。`scene_bible` 已有 kind。

## 四、封面与 polish

- `director-deliver` 对 Explainer 调 `gen_image` → `works/<slug>/video_cover.png`。outputs.root 改成 `works/{work_slug}`，因为 `gen_image` 的 filename 不准带路径。
- 七条主链 `required_ticket_type.none_of` 加上 `polish`。
- 新 skill `director-polish`：`any_of: [polish]`，只 `gen_video` 一次。consumes 的 `video_brief` / `shot_prompts` 为 `required: false`，否则 polish SOP 没有 producer，组装期缺源出局。运行时读工作包。

## 五、假绿

| 风险 | 锁法 |
|---|---|
| 未知 backend 仍走 LightAI | `backend=runway` 断言错误文案含「不会改打」，且不写 mp4 |
| 指定 libtv 但 which 被漏掉 | monkeypatch `which_binary` 返回空，`env_missing` + backend=libtv |
| Drama 缺口仍进人审 | 空工作包 `gate=visual` → success=False、waiting_human=False |
| 模板文件被当成已完成 | 库存字样算 placeholder |
| polish 工单仍组装 brief | `ticket_type=polish` 有 director_polish、无 director_brief |
| dreamina 路径从未调用 | mock `generate_dreamina` 写文件，backend 必须是 dreamina |

## 六、没做什么

- 没有把 LibTV 画布节点跑通。当前 CLI schema 会变，硬编码 `libtv node` 正是原文档禁止的。
- 没有把 LibTV token / 即梦 OAuth 写进仓库。
- 没有自动剪辑、没有静默升 1080p。
- 没有新 Agent 类。

## 七、改动清单

```
backend/plugins/director/backends.py
backend/plugins/director/cli_video.py
backend/plugins/director/mode_check.py
backend/plugins/director/actions/gen_video.py
backend/plugins/director/actions/probe_backend.py
backend/plugins/director/actions/check_mode_assets.py
backend/plugins/director/actions/confirm_video_gate.py
backend/plugins/director/actions/init_work_package.py
backend/plugins/director/skills/director-*    主链 none_of + polish skill
backend/plugins/director/knowledge/tools/backends.md
backend/plugins/director/knowledge/modes/cinematic-drama/workflow.md
backend/plugins/director/templates/work-package/{scene-bible,continuity-matrix,character-bible,voice-plan}.md
backend/tests/plugins/test_director_plugin.py
```

## 八、验证

```bash
cd backend
python -m pytest tests/plugins/test_director_plugin.py tests/artifacts/test_registry_drift.py tests/sop/test_compose_sop_skills.py -q
```

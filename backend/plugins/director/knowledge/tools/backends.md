# 生成后端能力边界

Mode 决定做什么片，后端只决定怎么生成。缺登录、缺 Key、缺模型时停止，不静默切换。

## 选择顺序

1. 用户指定后端（`gen_video backend=` 或简报 `backend` 字段）→ 只用该后端，能力不够就停。
2. 未指定 → 项目简报 `director.backend` / `video_brief.json` 的 `backend`，默认 `lightai`。
3. 不得因 LightAI 失败自动改打 LibTV 或即梦 CLI；也不得把未知名字改写成 lightai。
4. 先 `probe_backend`，再 `gen_video`。探测命令会进时间轴。

允许的名字：`lightai` / `libtv` / `dreamina`（`jimeng` 是 dreamina 的别名）。

## LightAI（缺省执行后端）

- 使用 ADS 已有的 `LIGHTAI_API_KEY`。
- 视频走插件 Action `gen_video` / `gen_video_batch`，不要自己拼 HTTP。
- 人物参考图、Explainer 封面继续用公共 `gen_image`。
- Key 缺失 → 工单 blocked，不改讲稿。

## 即梦 `dreamina` CLI

与 LightAI 的即梦引擎**不是**同一条登录。本机有 `dreamina` 且用户明确指定时才走：

- 纯文字：`dreamina text2video --prompt … --duration … --ratio … --video_resolution=720p --model_version=seedance2.0fast --poll=30`
- 人物/音色参考：`dreamina multimodal2video`，本地 `--image` / `--audio` 按职责重复传入。
- 提交后用返回的 `submit_id` 调 `query_result --download_dir=<作品>/video`，再把文件改名为 `片段NN.mp4`。
- `--poll` 超时不是失败，继续查同一个 submit_id，不重新提交。
- 正式调用前以当前 `dreamina --help` 为准，不把 2026-08 的命令快照当唯一真相。
- 未安装、未登录、额度不足、缺少本地参考文件 → 停止。

## LibTV CLI

director 原主力，ADS 里是可选后端。本机有 `libtv` 且用户明确指定才探测：

- 探测：`libtv version`（时间轴记这条命令）。
- 生成依赖画布 `projectUuid` 与**当前安装版本**的实时 schema。未绑定画布不得生成。
- 本插件不代跑过期的 `libtv node …` 快照。画布内生成完成后可用 `download_video` 拉回本地。
- 未安装 → `env_missing`，给出安装说明，不改打 LightAI。

## 成本锁

Cinematic Drama 正式片段：720p、时长 ≤ 15 秒。不主动升 1080p 或 Seedance 2.5。用户针对本任务二次确认后，才能传 `allow_cost_unlock=true`。后端没有等价 720p 模型时停止，不换未验证模型。

# director / videoclaw 适配系统公共云端层（2026-11-19）

> 关联方案：`docs/20261119_01_plugin-import外部仓库接入插件方案.md` §15
> 前一篇：`dev-notes/2026-11-19_06_MiniMax_H3公共云端视频层落地.md`
> 提交基线：`74495b0`（公共层 + VC sandbox）；本篇改动**尚未提交**。

## 背景

上一轮按用户要求「这些接口 ADS 共用的，配置到系统配置中，不属于 Plugin」建了
`backend/cloud_video/`（只有 MiniMax H3）。本轮用户要求「把 director 和 videoclaw 适配到公共层」。

两个拍板（AskUserQuestion）：
1. 改造深度 = **新增可选后端**：原有 lightai / libtv / dreamina / VC sandbox **完全不动**，
   低风险不破坏现有流程。
2. **补上 LightAI provider，统一后端真源**：把 lightai 登记进 `cloud_video.PROVIDERS`，
   director 的 lightai 分支改走公共层，顺手消除 `_BACKENDS` / `ALLOWED_BACKENDS` 两份真源。

## 架构：依赖方向单向，公共层零 plugins import

```
plugins/director/*  ─┐
plugins/videoclaw/* ─┼──▶ backend/cloud_video/ ──▶ config.py + 标准库
                     │        └─(函数内延迟)─▶ image_processor（公共模块）
                     └──▶ plugins/director/work_package.py（brief/CLI 私有业务，留 plugin）
```

`cloud_video/lightai.py` 顶层只 import `config` + 标准库；`image_processor` 的
`_lightai_post`/`_lightai_get`/`_lightai_sem`/`_SSL_CTX`/`_collect_http_strings` 保持
**函数内延迟 import**（沿用原 `lightai_video.py` 写法），避免公共层顶层继承
`database`/`events`/`git_manager` 等业务依赖。

## 改动清单

| 文件 | 内容 |
|---|---|
| `A backend/cloud_video/lightai.py` | 从 `plugins/director/lightai_video.py` 逐行上提 LightAI 实现；新增 `generate(req, dest)` 统一结果结构 |
| `M plugins/director/lightai_video.py` | 改为**兼容 shim**，re-export 公共层；保留既有 import 路径与测试 monkeypatch 目标 |
| `M backend/cloud_video/client.py` | `PROVIDERS` 补 lightai；新增 `ALLOWED_PROVIDERS` / `normalize_provider` / `probe_provider` / `generate_video_with_provider(provider,...)` 统一 dispatch |
| `M backend/cloud_video/__init__.py` | 导出新 API |
| `M plugins/director/backends.py` | `ALLOWED_BACKENDS = tuple(ALLOWED_PROVIDERS) + ("libtv","dreamina")`；别名补 minimax/h3/mnmx/鼠鼠；云端探活委托 `probe_provider()` |
| `M plugins/director/actions/gen_video.py` | 删重复的 `_BACKENDS` 字面量改引用真源；新增 `_run_cloud_provider()` 与 `backend=minimax_h3` 分支 |
| `M plugins/videoclaw/actions/vc_media.py` | `VCGenVideoAction` 加 `provider` 参数与 `_run_cloud_provider()`；留空仍走 VC sandbox |
| `A backend/tests/plugins/test_cloud_video_adapters.py` | 18 项 |
| `M docs/20261119_01_...方案.md` | 追加 §15，`§14.7` 待办 #1 标记为已落地 |
| `A dev-notes/2026-11-19_07_...md` | 本篇 |

**原有 lightai / libtv / dreamina / VC sandbox 的调用参数、产物、失败分流全部未改。**

## 关键实现点

- **单一真源**：公共层 `ALLOWED_PROVIDERS = ("lightai","minimax_h3")`；director 的
  `ALLOWED_BACKENDS` 由它派生 + 两个 CLI 后端。实测 `gen_video._BACKENDS is backends.ALLOWED_BACKENDS`。
- **兼容 shim**：`plugins/director/lightai_video.py` 保留原模块路径，让
  `gen_video.py:148,291`、`download_video.py:51,66`、
  `test_director_plugin.py:194,196` 的 monkeypatch 目标全部继续生效。
  实测 `shim.create_and_poll_video is cloud_video.lightai.create_and_poll_video`。
- **统一 dispatch**：`generate_video_with_provider(provider, ...)` 先做轻量配置探活
  （不联网），缺 key → `CloudVideoUnavailable` → 调用方转 `env_missing → blocked`；
  lightai 走 `lightai.generate(req,dest)`，minimax_h3 走 `client.generate_video(...)`。
- **参数映射留 Plugin 层**：director/videoclaw 把 `16:9` → `16:9 (Widescreen)`、
  `720p` → `1`，公共层不认这些别名。
- **videoclaw 云端分支不要求 VC sidecar**：`provider` 非空时直接走公共层，
  `VIDEOCLAW_ENABLED=false` 也能用；留空才调 `_prepare()`（VC health）。

## 一个真实踩坑（已修）

首版 Plugin 用 `from cloud_video import generate_video_with_provider`（包级 re-export），
而测试 monkeypatch 的是源模块 `cloud_video.client.generate_video_with_provider`。
**包级 re-export 是静态绑定**，patch 源模块不影响包命名空间 → 测试真的打到了
runlive.top 拿到 `HTTP 401: 卡 key 无效`（幸好是无效测试 key，未产生费用）。

修复：Plugin 内改 `from cloud_video import client as cloud_client`，调用
`cloud_client.generate_video_with_provider(...)`，即 patch **源模块** —— 与
`backend/tests/actions/test_gen_image.py:26-28` 记录的教训一致。
修复后适配测试输出里已确认无任何网络痕迹。

## 验证（全部通过）

| 项 | 结果 |
|---|---|
| `tests/plugins/test_cloud_video_adapters.py` | 18 项通过 |
| 全量回归 | **123 项通过**：adapters + cloud_video + VC media + VC plugin + director + registry + pack_user_scope |
| 依赖方向 | `cloud_video/*.py` 零 `plugins.*` import（grep 硬核对） |
| Action 注册 | `vc_gen_image/vc_gen_video/vc_run_project` 齐全；`gen_video`/`gen_image` 未受影响 |
| 无网络 | 适配测试输出 grep `401\|403\|runlive\|HTTP\|urlopen` 无命中 |
| 语法 | 7 个改动文件 `ast.parse` 通过 |

覆盖：单一真源、别名归一化、双 provider 探活、lightai shim 等价性、dispatch 两路分流、
director 新后端（成功 / 缺 key blocked / 未知后端仍拒 / lightai 分支行为不变）、
videoclaw 新 provider（成功 / 不需 VC sidecar / 缺 key blocked / 默认仍走 VC sandbox）。

## 必须人完成（动态，未做）

1. `backend/.env` 填 `MINIMAX_H3_CARD_KEY=sk_...` + `MINIMAX_H3_ENABLED=true`，
   卡须先被管理员加白名单。
2. 跑 `gen_video backend=minimax_h3 ...` 与 `vc_gen_video provider=minimax_h3 ...`，
   确认产物落 `works/<slug>/video/` 与 `works/<slug>/videoclaw/video/`、时间轴有 `TCMD-*`。
3. LightAI 分支回归：`gen_video`（不带 backend）仍走公共层 shim，行为与之前一致。

## 待办

1. 接 MiniMax 官方 API / 火山 Ark / LibTV / LiblibAI → 只在 `cloud_video.PROVIDERS`
   登记，Plugin 的后端枚举自动包含，无需再改。
2. 可选：设置面板热更新 key + 回写 `.env`（参照 `api/image_gen.py:200-215`）。
3. 签名直链内网 IP 问题，必要时 ADS 侧做代下代理。
4. 本轮改动提交 git（等用户确认）。

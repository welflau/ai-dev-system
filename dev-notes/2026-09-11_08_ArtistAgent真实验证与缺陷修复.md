# DevNote · 2026-09-11（五）

**类型**: ArtistAgent 真实工单验证 + 修复暴露的 2 个缺陷
**状态**: 验证通过；2 个缺陷已修，18 项断言全绿
**前置**: `dev-notes/2026-09-11_07_实现ArtistAgent.md`（该 note 的待办「未经真实工单验证」）

---

## 一、真实验证

**项目**：ThunderStrike（Phaser 像素射击游戏，web，`category:game`）
**工单**：为敌机添加三种类型的视觉区分（module=design）

```
pending → planning_done → ux_design_done → art_design_done
        → architecture_done → assets_ready        379s
```

ArtAgent 产出 9 条真实资产需求（敌机精灵 ×3、血条/护盾条、爆炸特效、速度线、
护盾光环、HUD 警示图标），ArtistAgent 全部处理：

```
1 命中资产库 / 8 占位图 / 0 待人工     (1131ms)
```

8 张占位图确实落盘且是合法 PNG，视觉上是设计好的洋红斜纹 + PLACEHOLDER 标注。
命中的 `explosion` 资产在 `G_ArtRes` 里文件真实存在。

**核心链路可用。** 但暴露了 2 个单元测试没覆盖到的缺陷。

---

## 二、缺陷 1：sprite 错配 SVG 图标

```
fx_explosion | sprite | explosion | 0.85 | icons/material-symbols/explosion.svg
```

需求是「爆炸序列帧 64x64 **8帧**」，命中的是一个 **343 字节的 SVG 图标**。

根因在我自己写的 `_TYPE_ALIAS`：

```python
"sprite": ["sprite", "icon"],   # 想着"图标也能当小精灵用"
```

两层问题：
- **格式不兼容** —— Phaser 加载 spritesheet 要 PNG，SVG 根本用不了
- **语义不同** —— 单帧静态图标 ≠ 8 帧动画序列

> 为什么单元测试没抓到：我的测试用例是 `zzz_nonexistent_thing_xyz`（**完全不存在**），
> 而这里是**存在但不合适** —— 假阳性的另一种形态。评分 0.85 很高，
> 因为 `explosion` 这个名字确实精确匹配，错的是类型。

**修复（三层，缺一不可）**：

1. `_TYPE_ALIAS` 取消跨类型回退：sprite 只查 sprite，不再退到 icon
2. 新增 `_TYPE_ALLOWED_EXT` 格式白名单：sprite/tileset/texture 只接受位图，拒绝 svg
3. 新增 `_MULTIFRAME_RE`：描述含「N帧 / frames / 序列帧 / spritesheet」直接跳过检索 ——
   多帧动画不可能从图标库拿到，省一次无用查询且避免误判

只做 1 不够（库里也有叫 explosion 的 png）；只做 2 不够（单帧 png 仍不是 8 帧序列）。

---

## 三、缺陷 2：commit 消息硬编码「测试截图」

```
commit bb8b20e8
    [ArtistAgent] 测试截图: 为敌机添加三种类型的视觉区分
    8 个 placeholder/*.png
```

`orchestrator.py` 的 `_media_files` 通道最早只给 TestAgent 截图用，消息写死了。
ArtistAgent 的占位图复用这条通道，就产出了自相矛盾的提交记录。

**修复**：抽出 `_MEDIA_COMMIT_LABELS` 映射，按 `(agent, action)` → 仅 agent → 兜底
三级查找：

| 来源 | 标签 |
|---|---|
| TestAgent.run_tests | 测试截图 |
| TestAgent.run_playtest | Playtest 截图 |
| ArtistAgent.generate_assets | 资产占位图 |
| 未知 | 媒体文件 |

---

## 四、验证（18 项）

```
1. fx_explosion 不再命中 SVG                          PASS
2. 多帧检测 6 例（8帧/2帧/frames/spritesheet/静态）    PASS
3. 扩展名提取 + sprite 拒 svg + TYPE_ALIAS 收紧        PASS
4. settings_gear 仍正常命中（修复不过度）              PASS
5. 真实 manifest 回归：fx_explosion→placeholder       PASS
   且 note 写明"须由美术制作"
6. commit 标签 4 例 + 硬编码已移除                     PASS
```

第 4、5 项是关键 —— 收紧后必须确认 icon 类没被误伤，
真实工单的 6 条清单里 `settings_gear` 仍能命中 `icons/lucide/settings.svg`。

---

## 五、改动清单

```
backend/actions/generate_assets.py
  ~ _TYPE_ALIAS            取消跨类型回退
  + _TYPE_ALLOWED_EXT      格式白名单
  + _MULTIFRAME_RE         多帧描述检测
  + _ext_of()
  ~ _search_library()      召回后按格式过滤
  ~ _resolve_one()         多帧直接走占位图 + note 说明

backend/orchestrator.py
  + _MEDIA_COMMIT_LABELS   媒体 commit 标签映射
  ~ _handle_git_files()    按来源取标签，移除硬编码
```

---

## 六、本次验证的额外收获

**探针脚本自己踩了待办 ④ 的坑**：直接调 `git_manager` 建 feat 分支，
但没先 `set_project_path()`，`_repo_path()` 返回了不存在的默认路径
`backend/projects/PRJ-...`，报 `WinError 267`，分支没建成，全程在 main 上跑。

有意思的是 **Agent 的 commit 反而成功了** —— orchestrator 的
`_handle_git_files`（:2799）有路径自恢复逻辑。这反向验证了那段代码有效。

正常流程（走 API 建单）不会有这个问题，属测试方法缺陷，不是产品 bug。

---

## 七、待办

- **ThunderStrike 有 6 个本地 commit 未推送**（在 main 分支，push 被保护策略拦）。
  其中 `bb8b20e8` 的消息是修复前的「测试截图」，如需推送建议先改写
- **本次修复未经真实工单二次验证**：用真实 manifest 做了回归，但没重跑完整流转
- 09-11_03 遗留：OpenSpec Propose 被 300s kill 后半成品是否可用（需真实 LLM）
- 资产库检索仍只覆盖 icon/sprite 类，model/animation/hdri 未调优（承接 09-11_07）

---

*相关：`dev-notes/2026-09-11_07`、`backend/actions/generate_assets.py`*

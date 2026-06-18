---
description: 用 AI 生成纹理或 3D Mesh 并自动导入 UE
---

# /ue-asset

用自然语言描述资产，调用 AI 生成服务生成纹理或 3D Mesh，自动导入 UE Content Browser。

## 用法

```
/ue-asset <资产描述> --name <资产名> [--type texture|mesh] [--ue-path <路径>]
```

## 执行前置

读取 `.claude/ue-config.json` 获取脚本绝对路径：

```python
config = json.loads(open('.claude/ue-config.json').read())
generate_texture = config['generate_texture_script']
generate_mesh    = config['generate_mesh_script']
ue_python        = config['ue_python_script']
```

## 行为

1. 根据 `--type` 选择生成脚本：
   - `texture` → `{generate_texture_script}`
   - `mesh` → `{generate_mesh_script}`
2. 调用 AI 服务生成资产（本地缓存到 `assets/cache/`）
3. 若 UE Editor 在线且指定了 `--ue-path`，通过 `{ue_python_script}` 导入 Content Browser
4. 报告资产路径和导入状态

## 前置条件

默认使用 LightAI 内部平台，设置 API Key（二选一）：

```bash
# 方式1：环境变量
export LIGHTAI_API_KEY="your-key"

# 方式2：在 scripts/env.json 配置（与 LightAI Skill 共用）
{"LIGHTAI_API_KEY": "your-key"}
```

外部服务备选：

| Provider | 环境变量 | 服务 |
|----------|---------|------|
| `lightai`（默认）| `LIGHTAI_API_KEY` | LightAI 平台（nano-banana/即梦/Tripo）|
| `dalle` | `OPENAI_API_KEY` | DALL-E 3 |
| `sd` | — | 本地 Stable Diffusion WebUI |
| `meshy` | `MESHY_API_KEY` | Meshy.ai |

## 资产命名规范

名称需遵循 `rules/ue-asset-naming.md`：
- 纹理：`T_<名称>_<类型>`（`_D` Diffuse / `_N` Normal / `_M` Mask）
- 静态网格：`SM_<名称>_<编号>`

## 示例

```
/ue-asset 潮湿的青苔石块地面纹理，绿色为主 --name T_Stone_Mossy_D --type texture --ue-path /Game/Environment/Terrain/Textures

/ue-asset 废弃的生锈铁桶，带破洞 --name SM_Barrel_Rusty_01 --type mesh --ue-path /Game/Environment/Props/Meshes

/ue-asset 火焰粒子所需的噪声纹理，黑白灰渐变 --name T_Fire_Noise --type texture --ue-path /Game/VFX/Textures
```

## 生成耗时参考

| 类型 | Provider | 预计时间 |
|------|---------|--------|
| 纹理 | DALL-E 3 | 15–30s |
| 纹理 | SD 本地 | 10–20s |
| 3D Mesh | Meshy | 3–5min |
| 3D Mesh | Tripo3D | 2–4min |

## 本地缓存

所有生成资产缓存在 `assets/cache/`，重复生成时优先使用缓存（如需强制重新生成，加 `--force`）。

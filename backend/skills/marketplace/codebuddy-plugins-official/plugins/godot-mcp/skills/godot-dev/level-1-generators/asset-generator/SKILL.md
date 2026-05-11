---
name: asset-generator
description: >
  游戏资产生成技能。调用外部 AI 服务生成 3D 模型、贴图、音效等资产，
  并自动导入到 Godot 项目中。
version: 1.0.0
dependencies:
  - godot-core
  - file-manager
  - external-api
triggers:
  - pattern: "生成模型|生成贴图|生成材质|生成音乐|生成音效|生成角色|创建资产"
inputs:
  - name: asset_type
    type: string
    enum: ["model_3d", "texture", "sprite", "music", "sfx", "voice"]
    required: true
  - name: prompt
    type: string
    required: true
  - name: style
    type: string
    required: false
outputs:
  - name: asset_path
    type: string
    description: 生成的资产在项目中的路径
  - name: manifest_entry
    type: object
    description: 添加到 manifest.json 的条目
---

# 游戏资产生成技能

通过 AI 服务生成游戏资产，并自动导入 Godot 项目。

## 前置条件

1. 确保已配置相应服务的 API Key（见 external-api skill）
2. 确保项目目录结构已初始化

---

## 资产类型与服务映射

| 资产类型 | 首选服务 | 备选服务 | 输出格式 |
|----------|----------|----------|----------|
| 3D 模型 | Meshy.ai | Tripo3D | .glb |
| 贴图 | Stable Diffusion | Leonardo.ai | .png |
| 精灵图 | Stable Diffusion | - | .png |
| 背景音乐 | Suno | - | .ogg |
| 音效 | - | - | .wav |
| 语音 | ElevenLabs | - | .ogg |

---

## 3D 模型生成

### 生成流程

```
用户提示 → AI 生成 → 下载 GLB → 导入 Godot → 更新清单
```

### 提示词模板

#### 角色模型
```
{style} {character_type} character, game-ready model, T-pose, 
low-poly ({poly_count} triangles), clean topology, 
{texture_style} texture, full body
```

**示例**：
```
cartoon fantasy knight character, game-ready model, T-pose,
low-poly (5000 triangles), clean topology, 
hand-painted texture, full body
```

#### 道具模型
```
{item_name}, game prop, {style} style, 
{poly_count} polygons, centered, {material_description}
```

**示例**：
```
medieval sword, game prop, stylized fantasy style,
2000 polygons, centered, metallic blade with leather-wrapped handle
```

#### 环境模型
```
{environment_object}, game asset, modular, 
{style} style, optimized for games, {additional_details}
```

### 导入配置

```json
{
  "import_options": {
    "generate_collisions": false,
    "generate_lightmap_uv": false,
    "create_shadow_mesh": true,
    "scale": 1.0,
    "offset": [0, 0, 0],
    "import_animations": true
  }
}
```

### 生成后处理

1. **碰撞体生成**：复杂模型需手动或使用简化网格
2. **材质调整**：检查材质是否正确导入
3. **LOD 设置**：为大型模型设置细节层次

---

## 贴图生成

### 贴图类型

#### 无缝贴图（Tileable）
```
seamless tileable {material} texture, top-down view, 
high detail, 4k resolution, pbr ready, {additional_details}
```

**示例**：
```
seamless tileable stone floor texture, top-down view,
high detail, 4k resolution, pbr ready, medieval dungeon style
```

#### 精灵/角色
```
{character} sprite, {view} view, {style} style, 
transparent background, game asset, {size} pixels
```

**示例**：
```
pixel art knight sprite, side view, 16-bit style,
transparent background, game asset, 64x64 pixels
```

#### UI 图标
```
game UI icon, {item_name}, flat design style, 
{color_scheme} colors, transparent background, {size}x{size}
```

#### Tileset
```
2D game tileset, {theme} theme, {tile_size}x{tile_size} tiles,
{count} variations, top-down view, seamless edges
```

### 尺寸规范

| 用途 | 推荐尺寸 | 说明 |
|------|----------|------|
| 角色精灵 | 64x64, 128x128 | 2D 游戏角色 |
| UI 图标 | 32x32, 64x64 | 物品、技能图标 |
| 贴图 | 512x512, 1024x1024 | 3D 模型贴图 |
| 背景 | 1920x1080 | UI 背景 |
| Tileset | 16x16, 32x32 per tile | 地图瓦片 |

### 导入配置

```json
{
  "import_options": {
    "compress_mode": "lossless",
    "mipmaps": true,
    "filter": true,
    "repeat": "enabled",
    "size_limit": 0
  }
}
```

---

## 音频生成

### 背景音乐

#### 提示词模板
```
{genre} {mood} music, {tempo} bpm, {instruments},
game soundtrack, {duration} seconds, loop-ready
```

**场景音乐示例**：

| 场景 | 提示词 |
|------|--------|
| 主菜单 | `orchestral epic theme, moderate tempo, strings and brass, game soundtrack, 90 seconds, loop-ready` |
| 探索 | `ambient atmospheric music, slow, piano and synth pads, mysterious mood, 120 seconds, seamless loop` |
| 战斗 | `intense action music, fast 140bpm, drums and orchestra, battle theme, 60 seconds, loopable` |
| Boss 战 | `epic boss battle music, dramatic, choir and orchestra, intense and climactic, 90 seconds` |
| 胜利 | `triumphant victory fanfare, uplifting, brass and strings, short 15 seconds` |

### 音效

音效通常需要组合或后处理，建议：
1. 使用音效库（Freesound、Sonniss 等）
2. AI 生成基础音效后在 Audacity 中调整

**常用音效类型**：
- 脚步声（草地、石头、木板）
- 攻击/打击声
- 拾取物品
- UI 点击/悬停
- 环境音效（风、水、火）

### 语音生成

```typescript
interface VoiceConfig {
  character_name: string;
  voice_id: string;        // ElevenLabs voice ID
  personality: string;     // "wise old man" | "young hero" | "villain"
  emotion: string;         // "neutral" | "angry" | "sad" | "happy"
}

// 批量生成对话
interface DialogueLine {
  id: string;
  text: string;
  emotion?: string;
}
```

### 音频导入配置

```json
{
  "music_import": {
    "loop": true,
    "bpm": 120,
    "beat_count": 0
  },
  "sfx_import": {
    "loop": false
  }
}
```

---

## 资产清单管理

### manifest.json 结构

```json
{
  "version": "1.0.0",
  "last_updated": "2026-04-16T10:30:00Z",
  "assets": {
    "models": [],
    "textures": [],
    "audio": {
      "music": [],
      "sfx": [],
      "voice": []
    }
  }
}
```

### 资产条目格式

```json
{
  "id": "model_player_knight",
  "name": "Player Knight",
  "type": "model_3d",
  "path": "res://assets/models/characters/player_knight.glb",
  "source": {
    "service": "meshy.ai",
    "prompt": "cartoon fantasy knight character...",
    "generation_date": "2026-04-16T10:30:00Z",
    "task_id": "task_abc123"
  },
  "metadata": {
    "poly_count": 5000,
    "has_animations": true,
    "animations": ["idle", "walk", "run", "attack"],
    "materials": ["body", "armor", "weapon"]
  },
  "tags": ["player", "character", "knight", "humanoid"]
}
```

### 更新清单

```gdscript
func add_asset_to_manifest(asset_info: Dictionary) -> bool:
    var manifest_path = "res://assets/manifest.json"
    var manifest = load_json(manifest_path)
    
    if manifest == null:
        manifest = {
            "version": "1.0.0",
            "last_updated": "",
            "assets": {
                "models": [],
                "textures": [],
                "audio": {"music": [], "sfx": [], "voice": []}
            }
        }
    
    # 根据类型添加到对应数组
    var asset_type = asset_info.get("type", "")
    match asset_type:
        "model_3d":
            manifest.assets.models.append(asset_info)
        "texture", "sprite":
            manifest.assets.textures.append(asset_info)
        "music":
            manifest.assets.audio.music.append(asset_info)
        "sfx":
            manifest.assets.audio.sfx.append(asset_info)
        "voice":
            manifest.assets.audio.voice.append(asset_info)
    
    manifest.last_updated = Time.get_datetime_string_from_system()
    
    return save_json(manifest_path, manifest)
```

---

## 批量生成

### 从配置批量生成

```json
{
  "batch_generate": {
    "characters": [
      {
        "id": "player",
        "prompt_template": "cartoon {class} character",
        "variants": ["knight", "mage", "archer"]
      }
    ],
    "items": [
      {
        "category": "weapons",
        "items": ["sword", "staff", "bow"],
        "style": "fantasy medieval"
      }
    ]
  }
}
```

### 批量处理流程

```typescript
async function batchGenerate(config: BatchConfig): Promise<BatchResult[]> {
  const results: BatchResult[] = [];
  
  for (const item of config.items) {
    // 控制并发，避免 API 限制
    await delay(1000);
    
    const result = await generateAsset(item);
    results.push(result);
    
    // 更新进度
    console.log(`Generated ${results.length}/${config.items.length}`);
  }
  
  return results;
}
```

---

## 最佳实践

1. **提示词迭代**：先用低质量快速测试，确认效果后再生成高质量版本
2. **版本管理**：在清单中记录生成参数，方便重新生成
3. **统一风格**：在提示词中保持一致的风格描述词
4. **资源复用**：相似资产使用变体而非重新生成
5. **本地缓存**：避免重复生成相同资产

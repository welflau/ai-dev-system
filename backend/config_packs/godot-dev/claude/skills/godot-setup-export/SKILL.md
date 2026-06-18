---
name: godot-setup-export
version: 1.0.0
displayName: Godot 导出配置
description: 用于设置 Godot 项目的多平台导出，配置导出预设、图标、功能标签、构建脚本或 CI/CD 流水线
author: Godot Superpowers Team
license: MIT
repository: https://github.com/anomalyco/godot-superpowers
homepage: https://github.com/anomalyco/godot-superpowers/tree/main/mini-skills/godot-setup-export
category: Godot
type: tool
difficulty: intermediate
audience: developers
keywords:
  - godot
  - export
  - build
  - ci/cd
  - github-actions
  - cross-platform
  - windows
  - mac
  - linux
  - web
  - mobile
platforms:
  - linux
  - macos
  - windows
---

# Godot 导出配置

## 概述

**自动化 Godot 项目的多平台导出配置。**

设置导出是一项繁琐、容易出错且需要平台特定知识的工作。本技能生成导出预设、配置图标和启动画面、设置功能标签、创建构建脚本，并与 CI/CD 流水线集成。

## 适用场景

**适合使用：**
- 为新 Godot 项目创建导出配置
- 添加新平台支持（Windows、Mac、Linux、Web、移动端）
- 通过 GitHub Actions 设置自动化构建
- 配置图标、启动画面或功能标签
- 创建自定义导出构建脚本
- 从本地导出迁移到 CI/CD

**不适合用于：**
- 调试导出失败（使用 godot-debug-exports）
- 平台特定的原生代码编译
- 一次性手动导出（使用 Godot 编辑器）

## 快速参考

| 任务 | 工具/方法 |
|------|-----------|
| 生成导出预设 | `godot --headless --generate-export-presets` |
| 设置图标 | `export_presets.cfg` icon 字段 |
| 配置功能标签 | `project.godot` `[feature]` 部分 |
| 自动化构建 | GitHub Actions 工作流 |
| 自定义脚本 | `export_presets.cfg` `custom_template/release` |

## 核心模式

### 导出预设生成

**Windows 桌面：**
```ini
[preset.0]
name="Windows Desktop"
platform="Windows Desktop"
export_filter="all_resources"
include_filter=""
export_files=[]
include_filter=""
export_path="builds/windows/Game.exe"
custom_features=""
export_filter="scenes"
export_files=PackedStringArray("res://main.tscn")
[preset.0.options]
custom_template/release=""
custom_template/debug=""

binary_format/architecture="x86_64"
codesign/enable=false
icon="res://assets/icons/windows_icon.ico"
```

**macOS：**
```ini
[preset.1]
name="macOS"
platform="macOS"
export_filter="all_resources"
export_path="builds/macos/Game.zip"
[preset.1.options]
binary_format/architecture="universal"
codesign/certificate_file=""
codesign/identity=""
icon="res://assets/icons/mac_icon.icns"
export/distribution_type=1
```

**Linux：**
```ini
[preset.2]
name="Linux"
platform="Linux"
export_filter="all_resources"
export_path="builds/linux/Game.x86_64"
[preset.2.options]
binary_format/architecture="x86_64"
custom_template/release=""
icon="res://assets/icons/linux_icon.png"
```

**Web：**
```ini
[preset.3]
name="Web"
platform="Web"
export_filter="all_resources"
export_path="builds/web/index.html"
[preset.3.options]
custom_template/release=""
custom_template/debug=""
variant/size_limit=16777216
vram_texture_compression/for_desktop=true
html/canvas_resize_policy=2
html/experimental_virtual_keyboard=false
progressive_web_app/enabled=false
```

**Android：**
```ini
[preset.4]
name="Android"
platform="Android"
export_filter="all_resources"
export_path="builds/android/Game.apk"
[preset.4.options]
gradle_build/use_gradle_build=false
gradle_build/export_format=0
gradle_build/min_sdk=21
gradle_build/target_sdk=33
version/code=1
version/name="1.0"
architectures/armeabi-v7a=false
architectures/arm64-v8a=true
architectures/x86=false
architectures/x86_64=false
keystore/debug=""
keystore/debug_user=""
keystore/debug_password=""
keystore/release=""
keystore/release_user=""
keystore/release_password=""
icon/export_identifier="com.example.game"
```

**iOS：**
```ini
[preset.5]
name="iOS"
platform="iOS"
export_filter="all_resources"
export_path="builds/ios/Game.xcodeproj"
[preset.5.options]
binary_format/architecture=1
application/app_store_team_id=""
application/bundle_identifier="com.example.game"
application/short_version="1.0"
application/version="1.0"
application/icon_interpolation=4
application/export_method_release=0
application/targeted_device_family=2
application/remove_simulator_arch=true
codesign/codesign=1
codesign/identity=""
codesign/provisioning_profile=""
```

## 图标和启动画面设置

### 各平台图标要求

| 平台 | 格式 | 尺寸 | 说明 |
|------|------|------|------|
| Windows | `.ico` | 256x256 | 多分辨率 ICO 文件 |
| macOS | `.icns` | 1024x1024 | Apple 图标格式 |
| Linux | `.png` | 256x256 | 标准 PNG |
| Web | `.png` | 512x512 | 用于 favicon/PWA |
| Android | `.png` | 512x512 | 支持自适应图标 |
| iOS | `.png` | 1024x1024 | App Store 图标 |

### 项目配置

**project.godot：**
```ini
[application]
config/name="Game Name"
config/description="Game description"
run/main_scene="res://scenes/main.tscn"
config/features=PackedStringArray("4.2", "Mobile")
boot_splash/bg_color=Color(0.14, 0.14, 0.14, 1)
boot_splash/image="res://assets/splash/splash_screen.png"
boot_splash/fullsize=true
boot_splash/use_filter=true

[display]
window/size/viewport_width=1920
window/size/viewport_height=1080
window/stretch/mode="canvas_items"
window/stretch/aspect="expand"
```

## 功能标签配置

**使用功能标签实现平台特定行为：**

```ini
[feature_tags]
editor=false
standalone=true
debug=false
release=true

; Platform-specific features
windows=false
macos=false
linux=false
android=false
ios=false
web=false
mobile=false
desktop=false
```

**在 GDScript 中使用：**
```gdscript
# Platform-specific code
if OS.has_feature("mobile"):
    # Mobile touch controls
    touch_controls.visible = true
elif OS.has_feature("desktop"):
    # Desktop keyboard/mouse
    touch_controls.visible = false

# Debug vs release
if OS.has_feature("debug"):
    show_debug_info()
    enable_cheats()
```

## 自定义构建脚本

### Windows 批处理脚本
```batch
@echo off
set PROJECT_PATH=%~dp0
set GODOT_PATH="C:\Program Files\Godot\Godot_v4.x.exe"
set BUILD_DIR=%PROJECT_PATH%builds\windows

if not exist %BUILD_DIR% mkdir %BUILD_DIR%

%GODOT_PATH% --headless --path %PROJECT_PATH% --export-release "Windows Desktop" "%BUILD_DIR%\Game.exe"

if %ERRORLEVEL% NEQ 0 (
    echo Export failed!
    exit /b 1
)

echo Export complete: %BUILD_DIR%\Game.exe
```

### Linux/macOS Shell 脚本
```bash
#!/bin/bash
set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GODOT_PATH="/usr/bin/godot"
BUILD_DIR="$PROJECT_DIR/builds"

mkdir -p "$BUILD_DIR/linux" "$BUILD_DIR/macos" "$BUILD_DIR/web"

# Linux
$GODOT_PATH --headless --path "$PROJECT_DIR" \
    --export-release "Linux" "$BUILD_DIR/linux/Game.x86_64"

# macOS
$GODOT_PATH --headless --path "$PROJECT_DIR" \
    --export-release "macOS" "$BUILD_DIR/macos/Game.zip"

# Web
$GODOT_PATH --headless --path "$PROJECT_DIR" \
    --export-release "Web" "$BUILD_DIR/web/index.html"

echo "All exports complete!"
```

### PowerShell 脚本
```powershell
$ProjectPath = $PSScriptRoot
$GodotPath = "C:\Program Files\Godot\Godot_v4.x.exe"
$BuildDir = Join-Path $ProjectPath "builds"

New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null

$Presets = @(
    @{ Name = "Windows Desktop"; Path = "$BuildDir\windows\Game.exe" },
    @{ Name = "Linux"; Path = "$BuildDir\linux\Game.x86_64" }
)

foreach ($Preset in $Presets) {
    $Dir = Split-Path $Preset.Path -Parent
    New-Item -ItemType Directory -Force -Path $Dir | Out-Null

    & $GodotPath --headless --path $ProjectPath `
        --export-release $Preset.Name $Preset.Path

    if ($LASTEXITCODE -ne 0) {
        Write-Error "Export failed for $($Preset.Name)"
        exit 1
    }
}

Write-Host "Exports complete!"
```

## CI/CD 集成

### GitHub Actions 工作流

```yaml
name: Build and Export

on:
  push:
    branches: [main]
    tags: ['v*']
  pull_request:
    branches: [main]

env:
  GODOT_VERSION: 4.2.1
  EXPORT_NAME: game-name

jobs:
  export-windows:
    name: Windows Export
    runs-on: ubuntu-22.04
    container:
      image: barichello/godot-ci:4.2.1
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Godot
        run: |
          mkdir -p ~/.config/godot/
          echo "[export_presets]" > ~/.config/godot/editor_settings-4.tres

      - name: Windows Build
        run: |
          mkdir -p build/windows
          godot --headless --verbose --export-release "Windows Desktop" ./build/windows/$EXPORT_NAME.exe

      - name: Upload Artifact
        uses: actions/upload-artifact@v4
        with:
          name: windows
          path: build/windows

  export-linux:
    name: Linux Export
    runs-on: ubuntu-22.04
    container:
      image: barichello/godot-ci:4.2.1
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Linux Build
        run: |
          mkdir -p build/linux
          godot --headless --verbose --export-release "Linux" ./build/linux/$EXPORT_NAME.x86_64

      - name: Upload Artifact
        uses: actions/upload-artifact@v4
        with:
          name: linux
          path: build/linux

  export-web:
    name: Web Export
    runs-on: ubuntu-22.04
    container:
      image: barichello/godot-ci:4.2.1
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Web Build
        run: |
          mkdir -p build/web
          godot --headless --verbose --export-release "Web" ./build/web/index.html

      - name: Upload Artifact
        uses: actions/upload-artifact@v4
        with:
          name: web
          path: build/web

      - name: Deploy to GitHub Pages
        if: github.ref == 'refs/heads/main'
        uses: peaceiris/actions-gh-pages@v3
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          publish_dir: ./build/web

  export-android:
    name: Android Export
    runs-on: ubuntu-22.04
    container:
      image: barichello/godot-ci:4.2.1
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Android SDK
        run: |
          mkdir -p ~/.config/godot/
          echo "[export_presets]" > ~/.config/godot/editor_settings-4.tres

      - name: Android Build
        run: |
          mkdir -p build/android
          godot --headless --verbose --export-release "Android" ./build/android/$EXPORT_NAME.apk

      - name: Upload Artifact
        uses: actions/upload-artifact@v4
        with:
          name: android
          path: build/android

  export-macos:
    name: macOS Export
    runs-on: ubuntu-22.04
    container:
      image: barichello/godot-ci:4.2.1
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: macOS Build
        run: |
          mkdir -p build/macos
          godot --headless --verbose --export-release "macOS" ./build/macos/$EXPORT_NAME.zip

      - name: Upload Artifact
        uses: actions/upload-artifact@v4
        with:
          name: macos
          path: build/macos

  create-release:
    name: Create Release
    needs: [export-windows, export-linux, export-web, export-android, export-macos]
    runs-on: ubuntu-latest
    if: startsWith(github.ref, 'refs/tags/v')
    steps:
      - name: Download All Artifacts
        uses: actions/download-artifact@v4

      - name: Create Release
        uses: softprops/action-gh-release@v1
        with:
          files: |
            windows/*.exe
            linux/*
            android/*.apk
            macos/*.zip
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

## 常见错误

| 错误 | 解决方案 |
|------|----------|
| 缺少导出预设文件 | 运行一次 Godot 编辑器生成或复制模板 |
| 导出路径格式错误 | 所有平台使用正斜杠 |
| 图标无法加载 | 确保图标文件存在于指定路径 |
| Android 密钥库错误 | 设置调试密钥库或配置发布密钥库 |
| Web 导出失败 | 检查导出模板是否已安装 |
| CI/CD 找不到 Godot | 使用 godot-ci Docker 镜像或手动安装 Godot |

## 示例

### 修改前：手动导出
```gdscript
# Manual export via Godot editor
# 1. Open Project > Export
# 2. Click Add for each platform
# 3. Configure each preset manually
# 4. Click Export Project for each
# 5. Repeat every time you want to build
```

### 修改后：自动化配置
```ini
# export_presets.cfg - generated once, committed to repo
[preset.0]
name="Windows Desktop"
export_path="builds/windows/Game.exe"
...

[preset.1]
name="macOS"
export_path="builds/macos/Game.zip"
...

[preset.2]
name="Linux"
export_path="builds/linux/Game.x86_64"
...

[preset.3]
name="Web"
export_path="builds/web/index.html"
...

# Then run: ./build.sh or let GitHub Actions handle it automatically
```

### 完整项目结构
```
my-game/
├── project.godot
├── export_presets.cfg          # All export configurations
├── .github/
│   └── workflows/
│       └── export.yml          # CI/CD pipeline
├── assets/
│   └── icons/
│       ├── windows_icon.ico
│       ├── mac_icon.icns
│       ├── linux_icon.png
│       ├── android_icon.png
│       └── ios_icon.png
├── scripts/
│   └── build.sh                # Local build script
└── builds/                     # Output directory (gitignored)
    ├── windows/
    ├── macos/
    ├── linux/
    ├── web/
    └── android/
```

## 导出命令参考

```bash
# Export release build
godot --headless --export-release "Preset Name" "output/path"

# Export debug build
godot --headless --export-debug "Preset Name" "output/path"

# Export with pack file only (no executable)
godot --headless --export-pack "Preset Name" "output.pck"

# Export from specific project path
godot --headless --path /path/to/project --export-release "Preset" "output"

# Verbose output for debugging
godot --headless --verbose --export-release "Preset" "output"
```

## 平台特定说明

### Windows
- 需要导出模板：`windows_x86_64.exe`
- 图标必须是包含多分辨率的 `.ico` 格式
- 代码签名可选但建议用于分发

### macOS
- 需要导出模板：`macos.zip`
- App Store 需要特定的配置描述文件
- App Store 外分发需要公证

### Linux
- 最简单的导出流程
- 单个可执行文件
- 无特殊要求

### Web
- 需要导出模板：`web.zip`
- 线程需要 SharedArrayBuffer
- 全屏可能需要自定义 HTML 模板

### Android
- 需要 Android SDK 和导出模板
- 发布构建需要密钥库
- 未指定时会自动生成调试密钥库

### iOS
- 需要 macOS 和 Xcode
- 必须导出为 Xcode 项目后再构建
- 需要 Apple 开发者账号

## 版本控制

**提交到仓库：**
- `export_presets.cfg` - 包含所有导出配置
- `.github/workflows/export.yml` - CI/CD 流水线
- 构建脚本（`build.sh`、`build.bat`、`build.ps1`）

**添加到 `.gitignore`：**
```
builds/
*.tmp
*.import
```

## 故障排除

### "Export preset not found"
- 确保预设名称完全匹配（区分大小写）
- 检查 `export_presets.cfg` 是否存在于项目根目录
- 验证预设是否在 Godot 编辑器中已配置

### "Export template not found"
- 安装导出模板：Editor > Manage Export Templates
- CI/CD 中使用包含模板的 godot-ci Docker 镜像

### "Cannot open file for writing"
- 确保输出目录存在
- 检查写入权限
- CI/CD 环境中使用绝对路径

### Android 构建失败
- 验证 ANDROID_HOME 环境变量
- 检查密钥库配置
- 确保最低 SDK 版本与模板匹配

### Web 导出空白
- 检查浏览器控制台错误
- 使用线程时验证 SharedArrayBuffer 头信息
- 尝试在导出选项中禁用线程

## 实际效果

- **配置时间**：2 小时缩减至 10 分钟
- **构建一致性**：消除手动错误
- **发布节奏**：从数天缩短到数小时
- **多平台**：一次配置，随处构建

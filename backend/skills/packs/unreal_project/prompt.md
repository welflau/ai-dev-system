# Unreal Engine 项目结构规范

> 适用于 engine:ue5 / ue4 项目。理解项目骨架布局以便正确增删改。

## 顶层目录结构

```
<ProjectName>/
├── <ProjectName>.uproject    # 项目描述文件（JSON）
├── Source/                    # C++ 源码
│   ├── <ProjectName>/         # 主 runtime 模块
│   │   ├── <ProjectName>.Build.cs
│   │   ├── <ProjectName>.cpp
│   │   ├── <ProjectName>.h
│   │   └── <其他 .h / .cpp>
│   ├── <ProjectName>.Target.cs       # Game target（打包后的 exe）
│   └── <ProjectName>Editor.Target.cs # Editor target（开发时用，带热重载）
├── Content/                   # 资产（.uasset / .umap 二进制）
├── Config/                    # ini 配置
│   ├── DefaultEngine.ini
│   ├── DefaultGame.ini
│   ├── DefaultInput.ini
│   └── DefaultEditor.ini
├── Plugins/                   # 项目级插件（可选）
├── Binaries/                  # 编译输出（.dll / .exe，不入 git）
├── Intermediate/              # 编译中间产物（不入 git）
├── Saved/                     # 运行时存档、日志（不入 git）
└── DerivedDataCache/          # 资产缓存（不入 git）
```

## .uproject 结构

```json
{
  "FileVersion": 3,
  "EngineAssociation": "5.3",
  "Category": "",
  "Description": "",
  "Modules": [
    {
      "Name": "<ProjectName>",
      "Type": "Runtime",
      "LoadingPhase": "Default",
      "AdditionalDependencies": ["Engine"]
    }
  ],
  "Plugins": [
    { "Name": "ModelingToolsEditorMode", "Enabled": true, "TargetAllowList": ["Editor"] }
  ]
}
```

- **EngineAssociation**：对应引擎版本（`"5.3"` = Launcher 5.3；`"{GUID}"` = 自编译 build）
- **Modules[].Name**：必须和 `Source/<Name>/` 目录名 + `<Name>.Build.cs` 一致
- 新增模块（比如独立的 WeaponSystem / AICore）要同时：
  1. 建 `Source/WeaponSystem/` + `Source/WeaponSystem/WeaponSystem.Build.cs`
  2. `.uproject` 里 Modules[] 加一条

## 多模块拆分

小项目所有代码放主模块即可。大项目建议按功能拆模块（降低编译依赖 + 加快增量编译）：

```
Source/
├── MyGame/            # 主 runtime
├── MyGameCore/        # 公共基础类 / 工具
├── WeaponSystem/      # 武器相关
├── AICore/            # AI 行为树相关
├── MyGame.Target.cs
└── MyGameEditor.Target.cs
```

模块间依赖**必须显式声明**：被依赖的模块要在依赖者的 `Build.cs` 里：

```csharp
// WeaponSystem.Build.cs
PublicDependencyModuleNames.AddRange(new string[] {
    "Core", "CoreUObject", "Engine",
    "MyGameCore"      // ← 依赖公共模块
});
```

## Target.cs

两份 Target.cs 对应 Game 和 Editor 两种构建目标：

```csharp
// MyGame.Target.cs（打包游戏用）
public class MyGameTarget : TargetRules
{
    public MyGameTarget(TargetInfo Target) : base(Target)
    {
        Type = TargetType.Game;
        DefaultBuildSettings = BuildSettingsVersion.V4;
        IncludeOrderVersion = EngineIncludeOrderVersion.Unreal5_3;
        ExtraModuleNames.Add("MyGame");
    }
}

// MyGameEditor.Target.cs（开发时用，支持热重载）
public class MyGameEditorTarget : TargetRules
{
    public MyGameEditorTarget(TargetInfo Target) : base(Target)
    {
        Type = TargetType.Editor;
        DefaultBuildSettings = BuildSettingsVersion.V4;
        IncludeOrderVersion = EngineIncludeOrderVersion.Unreal5_3;
        ExtraModuleNames.Add("MyGame");
    }
}
```

**开发时跑 `<ProjectName>Editor` target**（带热重载，编译快）。**打包发布时跑 `<ProjectName>` target**（Shipping 配置）。

## Config/ INI 文件

- `DefaultEngine.ini` — 引擎级（渲染、物理、模块加载）
- `DefaultGame.ini` — 游戏级（GameMode/GameInstance 配置）
- `DefaultInput.ini` — 输入映射（UE5 推荐迁移到 Enhanced Input Assets 放 Content/）
- `DefaultEditor.ini` — 编辑器偏好

修改 `.ini` 后要**重启 Editor** 才生效（运行时不热加载）。

## Git 忽略规则

`.gitignore` 应该包含：

```
# 编译产物
Binaries/
Intermediate/
DerivedDataCache/
Saved/

# IDE
.vs/
.vscode/
*.VC.db
*.sln                   # UE 会自动 generate，不入 git

# OS
Thumbs.db
.DS_Store
```

**二进制资产**（`Content/**/*.uasset`、`*.umap`）通常入 git（或用 Git LFS）。

## 模板（Templates/）对照

UE 自带 `Templates/TP_*` 是 Epic 提供的官方骨架：

| 模板 | 特点 |
|---|---|
| TP_FirstPerson | 第一人称角色 + 武器 + 射击 |
| TP_ThirdPerson | 第三人称角色 + 相机 |
| TP_TopDown | 俯视角 + 点击移动 |
| TP_VehicleAdv | 物理驾驶 |
| TP_Blank | 空白基线 |

本系统生成项目时会基于这些模板做 rename（`TP_FirstPerson` → `<ProjectName>`）。**基于模板开发时，不要重新创建模板里已有的类**（如 `<ProjectName>Character` / `<ProjectName>GameMode`），直接改它们或继承扩展。

## 修改现有代码的原则

1. **先读再写**：改文件前先完整读一遍头文件+实现，理解当前责任
2. **最小侵入**：只改必要行，不重构没任务的部分
3. **保留 UCLASS/UPROPERTY 元数据**：编辑过的 BP 资产依赖这些元数据反射，乱改会导致 BP 变量丢失
4. **删除类是高风险**：类被 BP / .uasset 引用时直接删会导致 BP 损坏，要先确认没引用再删

## 典型开发任务模板

### 新增一个 Actor 类

1. 头文件（`Source/<Module>/<ClassName>.h`）
2. 实现文件（`Source/<Module>/<ClassName>.cpp`）
3. 不改 Build.cs（除非用了新模块功能）
4. 不改 .uproject（除非新模块）

### 给现有 Actor 加属性

只改 `.h`（加 UPROPERTY）和 `.cpp`（初始化），不涉及模块/项目结构。

### 新增模块

1. `Source/<NewModule>/` 目录
2. `<NewModule>.Build.cs`（基础 4 模块 + 必要依赖）
3. `<NewModule>/<NewModule>.cpp` + `.h`（模块 Entry）
4. `.uproject` Modules[] 加一条
5. 如果要暴露到 Game / Editor target，在 Target.cs 里 `ExtraModuleNames.Add("<NewModule>")`

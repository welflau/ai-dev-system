---
name: godot-setup-csharp
version: 3.0.0
displayName: 设置 C# 集成
description: >
  用于为 Godot 4.x 项目添加 C# 支持或创建混合 GDScript/C# 架构。
  设置项目结构，配置 .csproj 文件，启用 GDScript 与 C# 之间的通信，
  实现 C# 中的 Signal 连接，处理 Resource 加载，并识别适合用 C# 优化的
  性能关键代码候选项。
author: Asreonn
license: MIT
category: game-development
type: tool
difficulty: intermediate
audience: [developers]
keywords:
  - godot
  - csharp
  - dotnet
  - csproj
  - gdscript-interop
  - signals
  - resource-loading
  - performance
  - mono
  - mixed-language
platforms: [macos, linux, windows]
repository: https://github.com/asreonn/godot-superpowers
homepage: https://github.com/asreonn/godot-superpowers#readme

permissions:
  filesystem:
    read: [".gd", ".cs", ".csproj", ".sln"]
    write: [".cs", ".csproj", ".sln"]
  git: true

behavior:
  auto_rollback: true
  validation: true
  git_commits: true

outputs: "C# 项目文件、.csproj 配置、C# 脚本模板、Signal 绑定、Resource 加载代码"
requirements: "Godot 4.x（含 .NET 支持）、dotnet CLI、Git 仓库"
execution: "半自动，包含人工审查节点"
integration: "与 godot-refactor、godot-extract-resources、godot-add-signals 配合使用"
---

# 设置 C# 集成

## 核心原则

**将 C# 用于性能关键代码，将 GDScript 用于快速迭代。** Godot 4.x 的 .NET 集成支持无缝的混合语言开发。

## 本技能的功能

将单语言项目转换为优化的混合 GDScript/C# 架构：

1. **生成项目结构** - .csproj、.sln、解决方案文件夹
2. **启用跨语言通信** - GDScript 调用 C#、C# 调用 GDScript
3. **在 C# 中实现 Signal** - 类型安全的 Signal 连接和发射
4. **设置 Resource 加载** - 从 C# 加载 .tres、.tscn 文件
5. **识别优化候选项** - 适合用 C# 优化的代码模式

## 检测模式

识别适合迁移到 C# 的候选项：
- 重型数学运算（物理、寻路、AI）
- 复杂数据处理（背包系统、存档系统）
- 外部库需求（NuGet 包、.NET 生态系统）
- GDScript 分析器显示的性能瓶颈
- 需要强类型的系统（网络、序列化）

## 适用场景

### 你正在启动一个新的 Godot 4.x 项目
从一开始就设置 C#，获得混合语言的灵活性。

### 你遇到了性能瓶颈
GDScript 分析器显示热路径中存在大量计算。

### 你需要 .NET 库
想要使用 Newtonsoft.Json、System.Text.Json、Math.NET 等。

### 你正在从 Unity 移植
有现有的 C# 代码库需要与 Godot 集成。

### 你需要强类型
大型代码库中编译时类型检查可以防止 bug。

## 流程

1. **分析** - 分析 GDScript 性能，识别 C# 候选项
2. **生成** - 使用 Godot.NET.Sdk 创建 .csproj
3. **配置** - 设置解决方案结构和引用
4. **迁移** - 将选定的脚本转换为 C#
5. **互操作** - 设置 GDScript 与 C# 之间的通信
6. **Signal** - 在 C# 中实现 Signal 连接
7. **Resource** - 配置从 C# 加载 Resource
8. **验证** - 测试跨语言功能
9. **提交** - 每个主要组件进行 git 提交

## 生成的项目结构

```
project-root/
├── project.godot
├── MyProject.csproj          # Auto-generated
├── MyProject.sln             # Solution file
├── scripts/
│   ├── gdscript/             # GDScript files
│   └── csharp/               # C# scripts
│       ├── Core/             # Performance-critical systems
│       ├── Utils/            # Helper classes
│       └── Resources/        # Resource loaders
└── .vscode/
    └── launch.json           # Debug configuration
```

## 转换示例

### 项目设置

**修改前（仅 GDScript）：**
```gdscript
# No C# configuration
```

**修改后（混合设置）：**
```xml
<!-- MyProject.csproj -->
<Project Sdk="Godot.NET.Sdk/4.2.0">
  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
    <EnableDynamicLoading>true</EnableDynamicLoading>
  </PropertyGroup>

  <ItemGroup>
    <!-- Godot already includes GodotSharp -->
    <PackageReference Include="Newtonsoft.Json" Version="13.0.3" />
  </ItemGroup>
</Project>
```

### GDScript 调用 C#

**C# 类：**
```csharp
// scripts/csharp/Pathfinder.cs
using Godot;

namespace MyProject.Core;

[GlobalClass]
public partial class Pathfinder : Node
{
    [Export] public float CellSize { get; set; } = 32.0f;

    public Godot.Collections.Array<Vector2> FindPath(Vector2 start, Vector2 end)
    {
        // A* implementation in C#
        var path = new Godot.Collections.Array<Vector2>();
        // ... pathfinding logic
        return path;
    }
}
```

**GDScript 中的使用：**
```gdscript
# enemy.gd
@onready var pathfinder: Pathfinder = $"../Pathfinder"

func move_to_target(target_pos: Vector2):
    var path = pathfinder.find_path(global_position, target_pos)
    follow_path(path)
```

### C# 调用 GDScript

**带方法的 GDScript：**
```gdscript
# ui_manager.gd
class_name UIManager

func show_damage_number(amount: int, position: Vector2):
    var label = preload("res://ui/damage_label.tscn").instantiate()
    label.text = str(amount)
    label.position = position
    add_child(label)
```

**C# 调用 GDScript：**
```csharp
// scripts/csharp/CombatSystem.cs
using Godot;

public partial class CombatSystem : Node
{
    private Node _uiManager;

    public override void _Ready()
    {
        _uiManager = GetNode("../UIManager");
    }

    public void ApplyDamage(Node target, int damage)
    {
        // Call GDScript method from C#
        var pos = ((Node2D)target).GlobalPosition;
        _uiManager.Call("show_damage_number", damage, pos);
    }
}
```

### C# 中的 Signal

**定义和发射：**
```csharp
// scripts/csharp/HealthComponent.cs
using Godot;

namespace MyProject.Core;

[GlobalClass]
public partial class HealthComponent : Node
{
    [Signal] public delegate void HealthChangedEventHandler(int newHealth, int maxHealth);
    [Signal] public delegate void DiedEventHandler();

    [Export] public int MaxHealth { get; set; } = 100;

    private int _currentHealth;
    public int CurrentHealth
    {
        get => _currentHealth;
        set
        {
            _currentHealth = Mathf.Clamp(value, 0, MaxHealth);
            EmitSignal(SignalName.HealthChanged, _currentHealth, MaxHealth);

            if (_currentHealth <= 0)
                EmitSignal(SignalName.Died);
        }
    }
}
```

**在 GDScript 中连接：**
```gdscript
# player.gd
@onready var health: HealthComponent = $HealthComponent

func _ready():
    health.health_changed.connect(_on_health_changed)
    health.died.connect(_on_died)

func _on_health_changed(new_health: int, max_health: int):
    update_health_bar(new_health, max_health)

func _on_died():
    play_death_animation()
```

**在 C# 中连接：**
```csharp
// scripts/csharp/HealthBarUI.cs
using Godot;

public partial class HealthBarUI : ProgressBar
{
    public override void _Ready()
    {
        var healthComponent = GetNode<HealthComponent>("../HealthComponent");
        healthComponent.HealthChanged += OnHealthChanged;
    }

    private void OnHealthChanged(int newHealth, int maxHealth)
    {
        MaxValue = maxHealth;
        Value = newHealth;
    }
}
```

### C# 中的 Resource 加载

**加载自定义 Resource：**
```csharp
// scripts/csharp/WeaponLoader.cs
using Godot;

namespace MyProject.Utils;

[GlobalClass]
public partial class WeaponLoader : Node
{
    public WeaponData LoadWeapon(string weaponId)
    {
        string path = $"res://resources/weapons/{weaponId}.tres";
        return GD.Load<WeaponData>(path);
    }

    public PackedScene LoadScene(string scenePath)
    {
        return GD.Load<PackedScene>(scenePath);
    }
}

// Custom resource class
[GlobalClass]
public partial class WeaponData : Resource
{
    [Export] public string WeaponName { get; set; }
    [Export] public int Damage { get; set; }
    [Export] public float AttackSpeed { get; set; }
    [Export] public Texture2D Icon { get; set; }
}
```

**GDScript Resource 定义：**
```gdscript
# resources/weapon_data.gd
class_name WeaponData
extends Resource

@export var weapon_name: String
@export var damage: int
@export var attack_speed: float
@export var icon: Texture2D
```

## 性能关键代码识别

### 以下情况应迁移到 C#：

| 模式 | GDScript 开销 | C# 优势 |
|------|--------------|---------|
| 重型循环（1000+ 次迭代） | 解释器开销 | 编译后，JIT 优化 |
| 复杂数学运算 | 较慢的浮点运算 | 向量化运算 |
| 字符串操作 | 内存分配 | StringBuilder、Span |
| 字典查找 | 哈希开销 | 泛型 Dictionary<T,T> |
| JSON 序列化 | 手动解析 | Newtonsoft.Json/System.Text.Json |
| 物理计算 | 每帧解释执行 | 原生性能 |
| 寻路/AI | 算法开销 | C# 中的 A*，多线程 |

### 适合 C# 的示例：

```gdscript
# BAD: Heavy computation in GDScript
func process_voxels():
    for x in range(64):
        for y in range(64):
            for z in range(64):
                var voxel = calculate_voxel(x, y, z)  # 262k iterations!

# BETTER: Call C# for heavy work
@onready var voxel_processor: VoxelProcessor = $VoxelProcessor

func process_voxels():
    var result = voxel_processor.process_chunk(position)  # C# handles loops
```

```csharp
// C# Implementation
using Godot;

public partial class VoxelProcessor : Node
{
    public byte[,,] ProcessChunk(Vector3I chunkPos)
    {
        var voxels = new byte[64, 64, 64];
        // Fast C# loops with compiler optimizations
        for (int x = 0; x < 64; x++)
            for (int y = 0; y < 64; y++)
                for (int z = 0; z < 64; z++)
                    voxels[x, y, z] = CalculateVoxel(chunkPos, x, y, z);
        return voxels;
    }
}
```

## 通信模式

### 模式 1：C# 核心 + GDScript UI
- C#：游戏逻辑、AI、物理、数据处理
- GDScript：UI、动画、场景管理、输入处理

### 模式 2：GDScript 游戏逻辑 + C# 工具
- GDScript：主要游戏循环、节点交互
- C#：数学工具、存档/读档系统、外部 API 调用

### 模式 3：共享 Resource
- 两种语言使用相同的 .tres 资源文件
- C# Resource 类使用 [GlobalClass] 属性
- GDScript Resource 定义

## 创建的内容

- 使用 Godot.NET.Sdk 的 `.csproj` 项目文件
- 用于 IDE 集成的 `.sln` 解决方案文件
- `scripts/csharp/` 中的 C# 脚本模板
- 带 `[GlobalClass]` 属性的跨语言类
- 使用正确 C# 语法的 Signal 定义
- Resource 加载工具
- 用于调试的 `.vscode/launch.json`
- 互操作边界文档

## 安全注意事项

- 渐进式迁移——每次一个系统
- 每个集成点进行 git 提交
- 跨语言调用的验证测试
- 类型安全防止运行时错误
- 原始 GDScript 保留在 git 历史中

## 不适用场景

在以下情况不要添加 C#：
- 团队没有 C# 经验
- 项目较小（< 1000 行）
- 不存在性能问题
- 构建复杂度不值得收益
- 目标平台不支持 .NET（某些游戏主机）

## 最佳实践

### 保持互操作边界清晰
```csharp
// GOOD: Self-contained C# class
public partial class InventorySystem : Node
{
    public void AddItem(string itemId, int quantity) { }
    public bool RemoveItem(string itemId, int quantity) => true;
    public Godot.Collections.Array<string> GetItems() => null;
}
```

### 互操作使用 Godot 类型
```csharp
// GOOD: Godot types work across languages
public void MoveEntity(Node2D entity, Vector2 position) { }

// AVOID: Pure C# types require conversion
public void ProcessList(List<string> items) { }  // GDScript can't call easily
```

### Signal 命名一致性
```csharp
// C# signals use PascalCase
[Signal] public delegate void ItemCollectedEventHandler(string itemId);

// Connect from GDScript (snake_case in GDScript)
inventory_system.item_collected.connect(_on_item_collected)
```

### @export 属性双向通用
```csharp
// C# exports visible in editor
[Export] public float MovementSpeed { get; set; } = 200.0f;
[Export] public PackedScene ProjectileScene { get; set; }
```

## 集成

可配合以下技能使用：
- **godot-extract-resources** - 带 [GlobalClass] 的 C# Resource 类
- **godot-add-signals** - 类型安全的 C# Signal 实现
- **godot-refactor**（协调器）- 混合语言架构决策

## 常用转换对照

| 场景 | GDScript | C# |
|------|----------|-----|
| 类声明 | `class_name MyClass` | `public partial class MyClass : Node` |
| 导出变量 | `@export var speed: float` | `[Export] public float Speed { get; set; }` |
| Signal | `signal health_changed` | `[Signal] public delegate void HealthChangedEventHandler(int health);` |
| 调用 GDScript 方法 | `node.method()` | `node.Call("method", args)` |
| 加载资源 | `load("path")` | `GD.Load<Resource>("path")` |
| 字典 | `var dict = {}` | `new Godot.Collections.Dictionary()` |
| 数组 | `var arr = []` | `new Godot.Collections.Array<T>()` |

## 调试设置

```json
// .vscode/launch.json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Play",
            "type": "coreclr",
            "request": "launch",
            "program": "${config:godotEditorPath}",
            "args": ["--path", "${workspaceRoot}"],
            "cwd": "${workspaceRoot}",
            "stopAtEntry": false
        }
    ]
}
```

## 优势

- **性能** - 编译后的 C# 在重型计算上快 10-100 倍
- **类型安全** - 编译时错误检测
- **生态系统** - 访问 NuGet 包和 .NET 库
- **工具支持** - Visual Studio、VS Code、Rider 提供完整 IDE 支持
- **调试** - 完整的调试器支持，含断点
- **渐进式** - 可以逐步迁移系统

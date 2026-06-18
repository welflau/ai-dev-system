---
description: 截取 UE Editor 视口并分析当前状态
---

# /ue-review

截取 UE Editor 当前视口截图，结合场景 Actor 信息，分析问题并给出改进建议。

## 用法

```
/ue-review
/ue-review <具体关注点>
```

## 执行前置

读取 `.claude/ue-config.json`：

```python
config = json.loads(open('.claude/ue-config.json').read())
ue_python = config['ue_python_script']
```

## 行为

1. 调用 `Bash(f"python {ue_python} ...")` 截取编辑器视口截图（保存到 `screenshots/`）
2. 查询当前关卡的 Actor 列表、光源配置、NavMesh 状态
3. 结合截图和场景数据综合分析
4. 输出问题清单和改进建议

## 截图实现

```python
import unreal, shutil, os, datetime

# UE 5.3+ 中 HighResShot 自定义路径不生效，使用 AutoScreenshot 固定路径
auto_shot = "Saved/AutoScreenshot.png"
if os.path.exists(auto_shot):
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs("screenshots", exist_ok=True)
    saved_path = f"screenshots/review_{timestamp}.png"
    shutil.copy2(auto_shot, saved_path)
    print(f"Screenshot: {saved_path}")
else:
    # 触发一次截图更新
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    unreal.SystemLibrary.execute_console_command(world, "Shot")
    print("Screenshot command sent, check Saved/AutoScreenshot.png")

# 同时收集场景信息
actors = unreal.EditorLevelLibrary.get_all_level_actors()
lights = [a for a in actors if isinstance(a, unreal.Light)]
meshes = [a for a in actors if isinstance(a, unreal.StaticMeshActor)]

print(f"截图: {output_path}")
print(f"Actor 总数: {len(actors)}")
print(f"光源数量: {len(lights)}")
print(f"StaticMesh 数量: {len(meshes)}")
```

## 分析维度

截图 + 场景数据获取后，Claude 会从以下维度分析：

| 维度 | 检查项 |
|------|--------|
| **光照** | 是否有未光照区域、光源强度是否合理、阴影质量 |
| **布局** | 通道宽度是否合理（>150cm）、掩体分布是否均匀 |
| **导航** | NavMesh 是否覆盖所有可行走区域 |
| **性能** | 可见 Actor 数量、光源数量（超过 8 个动态光源警告）|
| **规范** | Actor Label 命名、文件夹组织 |

## 示例

```
/ue-review

/ue-review 检查光照是否均匀，有没有漏光问题

/ue-review 分析这个战斗区域的掩体覆盖率是否合理

/ue-review 检查 NavMesh 覆盖情况，有没有 AI 走不到的区域
```

## 输出格式

```
## 视口截图
[截图路径]

## 场景概况
- Actor 总数：42
- 光源：3 个点光源，1 个定向光
- StaticMesh：28 个

## 发现的问题
1. [严重] 东北角区域无光照，玩家视野盲区
2. [建议] 中央掩体高度 80cm，建议提高到 120cm 以提供更好遮蔽
3. [建议] PlayerStart 附近 300cm 内有 StaticMesh 阻挡，建议移除

## 改进建议
...
```

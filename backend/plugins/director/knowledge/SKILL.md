---
name: director
description: 导演并制作多类型视频。知识来源 github.com/s1dashu/director（MIT）。
---

# director（ADS 插件知识）

本目录从 `director` skill 精选迁入。执行工具是 ADS 插件 Action，不是 LibTV 独有路径。

## 三层选择

1. **Mode** 决定内容目标与叙事方式。
2. **style + 人物/音色** 决定视觉语言。
3. **Tool** 由 `gen_video` / `gen_image` / 工作包落地，见 [tools/backends.md](tools/backends.md)。

## Mode

- [Storytime Animation](modes/storytime-animation/workflow.md)
- [Animated Explainer](modes/animated-explainer/workflow.md)
- [Cinematic Drama](modes/cinematic-drama/workflow.md)

未建立的类型（如 MV）不得冒充已支持流程。

## 读取方式

在视频项目的 skill 里用 `read_file` 读取 `director-knowledge/<相对本目录的路径>`。
聊天里用 `read_local_file` 读取本插件 `knowledge/` 下的绝对路径。

来源：github.com/s1dashu/director（MIT）。

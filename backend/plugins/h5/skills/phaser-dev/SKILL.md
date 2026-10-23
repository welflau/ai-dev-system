---
name: Phaser 3 开发规范
description: Phaser 3 + TypeScript + Vite 网页游戏的结构、场景、触控和常见 API 坑
inject_to:
  - DevAgent
  - ArchitectAgent
  - ChatAssistant
traits_match:
  any_of:
    - framework:phaser
priority: high
paths:
  - "**/*.ts"
  - "**/*.tsx"
  - "src/**"
---

# Phaser 3 + TypeScript 开发规范

本项目交付物就是 H5 游戏，不要再写单文件 HTML 原型。用 Phaser 3 + Vite + `.ts`。

## 工程结构

```
package.json / tsconfig.json / vite.config.ts / index.html
src/
  main.ts              # 唯一入口，直接 new Phaser.Game，不要包 DOMContentLoaded
  constants.ts         # SceneKey / TextureKey 用 enum
  scenes/              # Boot →（Preloader）→ MainMenu → Game → GameOver
  gameobjects/
```

简单项目（≤8 文件）可以扁平：`constants.ts` + `scenes/*` + `main.ts`。中等项目再拆 `core/`、`gameobjects/`。

## 画布与输入

- 设计分辨率 **402×874 竖屏**（iPhone 16 Pro 逻辑像素）
- `scale.mode = Phaser.Scale.FIT`，`autoCenter = CENTER_BOTH`
- `parent: 'game-container'`，与 `index.html` 一致
- **必须有触控**：`pointerdown` / 滑动（记录 down/up 差值）/ 虚拟按钮。键盘可兼做桌面调试
- 资源优先 Graphics 代码绘制；角色、道具、标题艺术字才考虑 `gen_image`。背景、按钮底、粒子、文字不要出图

## 场景

```
constructor → init(data) → preload() → create() → update(time, delta)
```

`scene.start()` **重用实例**，不重新构造。`create()` 开头必须：

1. `this.input.removeAllListeners()`
2. 重置分数等状态
3. 清掉上次留下的 Graphics

场景 key 用 enum，`super({ key: SceneKey.Game })`。自定义 Sprite 要声明 `body!: Phaser.Physics.Arcade.Body`，`preUpdate` 必须 `super.preUpdate()`。

## 禁止

- `this.time.addEvent(...).on(...)` — TimerEvent 没有 `.on()`
- Phaser 3.60+ 不要 `particles().createEmitter()`，用 `this.add.particles(x, y, key, config)`
- Graphics 没有 Canvas 的 `save()` / `restore()`
- 子类不要声明 `originX` / `alpha` / `visible` 等与 mixin 冲突的字段（TS2415）
- `import Phaser from 'phaser'` 保持这样；不要写 `.ts` 后缀（标准 Vite）

## 自测

写完一批文件后应能过 `h5_typecheck`（`tsc --noEmit`）和 `h5_playtest`（vite build + 打开产物页）。缺 `package.json` 时先 `instantiate_h5_template`。本套件不对仓库另开 Vite 沙箱，也不常驻 Dev Server。

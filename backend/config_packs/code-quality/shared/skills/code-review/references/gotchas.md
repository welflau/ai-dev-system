# Gotchas（踩坑记录）

> code-review skill 在实际运行中遇到的常见陷阱，按发生频率排序。

---

## G-001: vue-tsc -b 复合项目模式要求所有被引用文件都在 include 中

**症状**：`pnpm --filter web build` 报 `TS6307: File 'xxx.ts' is not under 'rootDir'` 或 `TS2307: Cannot find module 'yyy'`，但本地 `tsc` 单独编译却通过。

**原因**：`vue-tsc -b`（`--build` 模式）在复合项目（`composite: true`）下对 `tsconfig.node.json` 有额外约束：**所有被该 tsconfig 间接引用的文件都必须显式列在 `include` 中**，不能仅列入口文件后靠自动发现。例如 `vite.config.ts` 若 `import` 了 `vite.shared.ts`，则 `vite.shared.ts` 也必须出现在 `include` 里。

此外，`tsconfig.node.json` 缺少 `"skipLibCheck": true` 时，第三方库（如 `fabric`）的类型声明文件报错也会被 `-b` 模式放大，导致构建失败。

**✅ 正确做法**：

```json
// apps/web/tsconfig.node.json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    ...
  },
  "include": ["vite.config.ts", "vite.shared.ts", "vitest.config.ts"]
}
```

- 将所有被 `vite.config.ts` 直接或间接引入的文件逐一加入 `include`。
- 加入 `"skipLibCheck": true` 屏蔽第三方类型声明中的噪音报错。

**❌ 错误做法**：

```json
// 只列入口，不列被引用的辅助文件
{
  "include": ["vite.config.ts"]
}
```

**触发条件**：`pnpm --filter web build`（底层调用 `vue-tsc -b`），在添加新的 vite 配置辅助文件或引入新第三方库后尤为常见。

---

## G-002: `docs/arch/*.md` 链接指向目录会被 `doc:lint` 以 `ARCH_LINK_IS_DIR` 判死

**症状**：写架构文档时直接用 `[packages/xxx](../../packages/xxx)` 指向一个目录做"入口参考"，`pnpm run doc:lint` 报：

```
[ARCH_LINK_IS_DIR] docs/arch/xxx.md:NN
  目标为目录（请指向具体文件）：../../packages/xxx
```

**原因**：`scripts/docs/lint-arch-docs.mjs` 的 LINK 规则要求架构文档内的相对链接必须指向**具体文件**（`.md` / `.ts` / `package.json` 等），不允许落在目录上。目的是保证"一跳抵达事实"，避免 IDE/GitHub 上点开后还要在目录里翻找。

**✅ 正确做法**：

```markdown
详见 [packages/xxx/package.json](../../packages/xxx/package.json)
# 或指向子目录下的具体入口文件
详见 [packages/xxx/src/index.ts](../../packages/xxx/src/index.ts)
```

**❌ 错误做法**：

```markdown
详见 [packages/xxx](../../packages/xxx)
```

**触发条件**：写新架构文档时常见——想"给个目录入口让读者自行探索"，但 doc:lint 不允许。落到具体文件即可（如 `package.json` 这种稳定存在的目录索引文件也算）。

**快速兜底**：如果真的想"指向一个概念上的模块"而非文件，改为不带链接的纯文本引用 `` `packages/xxx` ``，避免触发 LINK 检查。

---

## G-003: 新建治理文档时未与现有命名债 / ADR 交叉对齐，同符号分类冲突

**症状**：新建 `docs/arch/terminology.md` 一类治理文档时，凭直觉把 `build_app` / `gameFiles` / `GameSandbox` 等代码符号统一标为 `历史包袱`，但 `docs/arch/build-studio-naming-debt.md` 实际已把它们列为 **A 类"必须保留的契约名"**。两份文档对同一符号给出矛盾分类，会让后续作者按错误标记污染 `docs/arch/*.md`。

**原因**：`docs/arch` 存在**多份治理文档分层共治**：

- `terminology.md`：中文叙事的业务主名词
- `build-studio-naming-debt.md`：代码符号的命名债（A=契约必保 / B=低风险收口 / C=文档品牌）
- `adr/*.md`：决策留痕（如 ADR-0014 移除 `prototypeGenerator`）

同一个符号（如 `build_app`）可能在**命名债**里是 A 类契约、在**术语表**里又被误当历史包袱，因为术语表作者未读命名债分层。

**✅ 正确做法**：新建或修订治理文档时，先跑一遍交叉对齐：

1. 若术语表/新文档涉及代码符号，必须先通读 `build-studio-naming-debt.md §3.1 / §3.2 / §3.3`，沿用其分类；
2. 若涉及已废弃代号，必须附带对应 ADR 的退出决策链接（如 `prototypeGenerator` → ADR-0014）；
3. `/review` 阶段对 `docs/arch/` 新增的治理文档做"跨文档同符号分类一致性"核查，发现冲突 AUTO-FIX。

**❌ 错误做法**：凭"这个符号看起来像旧词"就一律标 `历史包袱`，不查命名债分层。

**触发条件**：

- 新建 `docs/arch/terminology.md` / `docs/arch/xxx-naming-rules.md` 类治理文档
- 修订 ADR 时顺带调整术语
- `/review` 对 `docs/arch/*.md` 做评审时

**快速识别信号**：同一个反引号符号（如 \`build_app\`）在两份 `docs/arch/*.md` 里标记不同（一个标 `历史包袱`、另一个标 "必须保留"），就是这条踩坑。

**本次真实发生**：v0.35.5 首版 `terminology.md` §4 ④ 与 §4.3 把 `build_app` / `gameFiles` / `GameSandbox` 统一标 `历史包袱`，`/review` 阶段交叉 `build-studio-naming-debt.md L62-64` 发现冲突（A 类契约名），AUTO-FIX 拆分为"A 类契约名（仅反引号）"与"真历史包袱（反引号 + `历史包袱` + ADR 链接）"两小类。

---

## G-004: service 层归并时按"原 db 函数清单"机械镜像，引入零调用方死代码

**症状**：把 `api/xxx.ts` 的 N 处 db 直写上移到新 service 时，凭"原 db 模块导出 5 个 CRUD"或"审计意见说 5 个操作要走 service"机械创建 5 个薄转发函数，而实际路由层只调用其中 4 个——其中 1 个路径走的是鉴权封装（如 `auth/ownership.getOwnedProject` 内含 `db.getProjectById`），新 service 的对应函数零调用方，反而违反"无死代码"清洁性，与本批 P3 "low-usage composables 清理"主旨自相矛盾。

**原因**：service 层归并的目标是**让真实调用点走 service**，不是**镜像 db 模块的函数表**。判断"哪些函数需要进 service"应该基于路由层的**实际调用清单**：

```
正确顺序：
  1. grep api/xxx.ts 中所有 db.* 调用点
  2. 对每个调用点判断：是直接调（→ 上移到 service） vs 通过鉴权封装/工具函数间接调（→ 不上移，那是封装层的实现细节）
  3. service 函数清单 = 直接调用清单（≠ db 模块导出清单）

错误顺序：
  1. 看 db 模块导出 5 个 CRUD
  2. 看审计文字说"5 个操作要走 service"
  3. 创建 5 个对应的 ForUser/ForProject 转发
  4. 实际路由 import 时发现只用 4 个，第 5 个零调用方
```

**✅ 正确做法**：

1. service 层创建前，先 `grep` 路由文件实际调用了哪些 db 函数
2. 对"通过鉴权封装/工具函数间接调用"的路径，**不**上移到 service（封装层已承担该职责）
3. service 命名带语义后缀（`ForProject` / `ForUser`）反映实际承载的语义，而非镜像 db 函数名
4. AUDIT_NOTES 措辞同步：写"4 个薄转发函数（getById 路径仍由 auth/ownership.getOwnedProject 承担鉴权 + 查询）"而非"5 个 CRUD 转发"——把分类决策留痕

**❌ 错误做法**：

```typescript
// projectService.ts —— 镜像 db 5 个 CRUD
export function getProjectByIdForUser(id: string) {
  return getProjectById(id);  // ⚠️ 零调用方：路由用的是 getOwnedProject
}
```

**触发条件**：

- L1/L2 风险层路由的 service 化重构（特别是审计意见笼统说"X 个操作未走 service"的场景）
- 路由层混用了"db 直调 + 鉴权封装"两种模式时

**快速识别信号**：service 创建后 `grep` 新函数名，**应至少有 1 个调用方**——零调用方即推测性死代码，AUTO-FIX 直接删除。

**本次真实发生**：v0.35.6 新建 `apps/server/src/services/projectService.ts` 时按审计意见"5 个 CRUD"创建 5 函数，`/review` 阶段 grep `getProjectByIdForUser` 发现零调用方（`GET /api/project/:id` 走 `getOwnedProject`），AUTO-FIX 删除该函数，AUDIT_NOTES 措辞修正为"4 个薄转发函数 + getById 路径鉴权封装承担"。

---

## G-005: 安全正则凭"常见标准"枚举白名单 → 一个未列事件名即绕过全部纵深

**症状**：用于拦截 HTML 内联事件处理器的正则写成显式枚举 —— 例如 `/\s(on(?:click|dblclick|keydown|...|transitionend))\s*=\s*["'][^"']*["']/gi`。单看测试用例（`onclick` / `onerror` / `onload` 都拦得到）感觉"覆盖够了"，实际只要攻击者挑一个未列出的 `on*` 事件（`onpointerdown` / `onwheel` / `onbeforeunload` / `ontoggle` / `onpaste` 等），或者用 HTML5 合法的无引号属性语法（`<button onclick=alert(1)>`），就直接绕过整条纵深防线。

**原因**：HTML 事件属性家族非常庞大（DOM L3、PointerEvent、ClipboardEvent、WindowEventHandlers、GlobalEventHandlers 并起来 60+ 个），枚举清单**必然**落后于浏览器实现；而"要求引号 `["']...["']`" 是对 HTML5 属性语法的错误假设（无引号属性值是合法的且浏览器会执行）。安全侧正则应当遵循"**over-block 优于 over-trust**"——宁可把自定义非事件属性（如 `data-on-xxx` 这种不会触发 handler 的自定义名）也误拦，让 LLM 改写成 `data-*`，也不要留任何通道给真实事件。

**✅ 正确做法**：

```typescript
const HTML_INLINE_EVENT_HANDLER_REGEX =
  /\s(on[a-z]+)\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)/gi;
```

- 事件名：`on[a-z]+` 通配（HTML 事件属性标准化为全小写字母）
- 属性值：`(?:"[^"]*"|'[^']*'|[^\s>]+)` 覆盖双引号 / 单引号 / 无引号（HTML5 三种合法语法）
- 合规产物根本不会出现任何 `on*` HTML 属性（规则强制走 `addEventListener`），所以误报风险=自定义非事件属性被迫改名，零功能代价

测试要求：不仅要覆盖"典型事件名 + 双引号"，还必须显式覆盖 **未枚举事件名**（`onpointerdown` / `onwheel` / `onbeforeunload` / `ontoggle` / `onpaste` 等代表）+ **无引号 / 单引号属性值** 两类绕过用例，防止测试盲区与代码盲区重合。

**❌ 错误做法**：

```typescript
// 白名单枚举 + 强制引号：漏检一堆真实事件 + HTML5 无引号语法绕过
const REGEX = /\s(on(?:click|dblclick|keydown|...))\s*=\s*["'][^"']*["']/gi;
```

**触发条件**：

- 编写安全过滤正则时（HTML / CSS / URL / header 注入场景都有类似陷阱）
- 用"只写几个代表，其他未来再加"的思路开题
- 审查时只看测试用例通过就认为覆盖完整

**快速识别信号**：正则里出现 `(?:a|b|c|...)` 长枚举 + 属性/值部分要求严格分隔符 → 立刻问自己"如果攻击者用未列举的选项 + HTML5 的宽松语法，会不会漏？"如果会，改通配 + 多分支值语法。

**对称检查**：同样适用于 `src=` / `href=` / `style=` 等注入敏感属性的过滤 —— 别假定属性值一定带引号。

**本次真实发生**：v0.35.7 Web 页面 HTML 脚本 AST 校验落地时，`verifyFixer.collectInlineHandlerErrors` 初版用 30+ 事件名白名单 + `["'][^"']*["']` 强制引号。`/review` 阶段发现两路绕过（漏检事件名 + 无引号语法），结合 iframe 沙箱 `allow-scripts allow-same-origin`（ADR-0009）可直接穿透到本域发起 `fetch('/leak')`。AUTO-FIX 改为 `on[a-z]+` + 三种属性值语法通配，补 3 条漏检场景测试（无引号 / 单引号 / 5 个未枚举事件名），全绿。

---

## G-006: Prompt 禁词守卫正则必须区分"正向使用"与"负向约束"

**症状**：给双轨（game / web-page）Prompt 写禁词 guard 测试时，简单的 `/Phaser/i.test(prompt)` 必然误伤。因为 web-page 轨 Prompt 里合法出现过"禁止引入 Phaser"、"不要输出 `this.load.`"等**负向约束文案**；纯字面量匹配会把这些合法约束也当成违规。

**原因**：禁词守卫的真实语义是"不得**正向建议**使用游戏概念"，而不是"禁词字面量零出现"。Prompt 里往往需要主动告诉 LLM "不要用 X"，这种负向语境是必要的。

**✅ 正确做法**：

```ts
// 用负向断言（lookahead）排除"禁止 / 不要 / 不得 / 禁用 / not to use"等上下文
const FORBIDDEN_IN_WEB_PAGE: RegExp[] = [
  /(?<!禁止引入\s?|不得使用\s?|不要用\s?)Phaser/i,
  /(?<!禁止|不要|不得)\bgameplayGoal\b/,
  /玩法闭环|至少可玩|核心玩法/,   // 这类词在 web-page Prompt 里根本不该出现，无需放行
  /this\.(load|add|physics)\./,   // Phaser API 残留，绝不放行
];
```

- 对"攻防两用词"（Phaser / gameplayGoal 等）用 **lookbehind 负向断言** 放行负向约束文案。
- 对"纯游戏叙事词"（玩法闭环 / 至少可玩 / 核心玩法）直接字面量拦截 —— web-page 轨 Prompt 没有理由出现。
- 对"API 前缀"（`this.load.` / `this.physics.`）用 `\.` 转义锚定，避免误匹配 `this.loading`。

**❌ 错误做法**：

```ts
// 1. 纯字面量：把合法的"禁止引入 Phaser"也当违规
const forbidden = [/Phaser/i, /gameplayGoal/];

// 2. 依赖 .includes() 暴力扫：信息量不够，无法区分正反向
if (prompt.includes('Phaser')) fail();
```

**触发条件**：

- 任何多轨/多租户 Prompt 场景（游戏 vs 网页、C 端 vs B 端、未成年人 vs 成年人）需要写"禁词守卫单测"
- Prompt 里本身就会出现"请不要使用 X"的负向约束
- 守卫测试被用作 CI 回归门禁，误报率必须接近零

**快速识别信号**：当你在单测里写"Prompt 不得包含 X"时，先搜一下 `prompt` 源码里是否本来就有 `禁止.*X` / `不要用.*X` / `not to use X` 的合法约束——有就必须用 lookbehind / lookahead 放行，否则这条守卫将来一定被绕过。

**对称检查**：同样适用于广告 / 合规 / 版权等 Prompt 守卫场景 —— "禁止提及竞品品牌"的规则，往往要先允许"不要提到 {品牌}"的 meta 表述自己能在 Prompt 中合法出现。

**本次真实发生**：v0.35.8 (B47) web-page 轨 Prompt 去游戏味整改时，新增 `promptBuilder.webpage.spec.ts` 13 条禁词守卫。`Phaser` / `gameplayGoal` 用 lookbehind 放行负向约束，"玩法闭环"等纯游戏叙事词直接字面量拦截，`this\.(load|add|physics)\.` 用转义锚点避开误匹配。测试套 13/13 全绿，同时不拦截 `buildSystemPrompt` 里"禁止引入 Phaser"这类合法文案。

**⚠️ v0.35.10 策略反转（更根本的解法）**：lookbehind 放行负向约束只是**次优解**。真正的根因是：既然编排层（`projectType === 'web-page'`）已经明确分轨，网页轨 prompt **根本不需要**写反游戏负向约束——它们在 6 个独立位置反复堆叠（system 开场 / `WEB_PAGE_FOUNDATION_RULES` / 两档 first-pass channel constraint / 5 个 user 指令的 `avoidLines`），让用户观感"冗余刻意"，还会让团队形成"必须显式写禁止 Phaser 才安全"的错觉。**v0.35.10 把契约升级为"零次提及"**：

- Prompt 层：网页轨全链路不提游戏 / Phaser / gameState / Scene / READY / PLAYING / GAME_OVER 任何字面量（哪怕是反向约束里）。
- AST 层（承担反游戏兜底）：`web_page` profile 扩展 blocked globals 增加 `Phaser`（`apps/server/src/security/astValidator.ts`）——LLM 真漏生成 `new Phaser.Game(...)` 会在落盘前拦截。
- 测试层（契约守卫）：`promptBuilder.webpage.spec.ts` 的 `FORBIDDEN_IN_WEB_PAGE` 表改为**纯字面量禁词**（不再做 lookbehind 豁免），覆盖 `buildSystemPrompt` / `buildPlanGeneratePrompt` / `buildStepPrompt` / `buildFixPrompt` / `buildModificationPrompt` / `buildIncrementalModifyPrompt` 六个入口。
- 治理 ADR：见 `docs/arch/adr/0015-web-page-prompt-zero-mention-of-game.md`。

**何时仍用 G-006 原方案（lookbehind 放行）**：如果你的 prompt **必须在同一条 prompt 里同时正向指导 + 负向约束**（例如没有分轨编排层，或禁词本身就是用户动态输入的话术约束），此时保留负向约束 + lookbehind 放行仍是正解。

**何时升级到 v0.35.10 方案（零次提及）**：编排层已经做过场景分轨（game vs web / C端 vs B端 / 成年 vs 未成年），且安全性有独立层（AST / 内容审核 / 策略引擎）能承担兜底——此时把 prompt 正向化、反向约束下沉到安全层，最干净也最可持续。

**反模式信号**：当你发现同一条负向约束（"禁止 X"）在 3+ 个独立 prompt 模板位置出现、且每次线上回归都需要在 prompt 里再加一句"不要 X"时——说明已经偏离 prompt 本职（表达意图），该把反向约束下沉到 AST / 校验 / 内容过滤层，而不是继续堆。

---

## G-007: 全路径覆盖与副作用完整性 — "rescue / bypass / fallback" 类自愈逻辑必须两路同改、写回正向信号

**症状**：B48 / v0.35.9 把 stepExecutor / verifyFixer 的 `TimeoutError` OR 短路治理干净、v0.35.11 (B49) 又给 `ModelRouter.selectProviderForCall` 加了 `single_source_fast_path` + `bypassHealthCache` rescue，单源 stream 链路的 rescue 死循环全部消除、全仓 1507 测试绿。然而用户第一次走 `/plan` 就立即命中 `No LLM provider available`，日志里**零 timeout**、零 rescue 循环——因为 orchestrator 的 plan 阶段走的是另一条路径 `modelRouter.getProvider(taskType)`，它沿用"常规遍历，健康不通过就返回 null"的老语义，**B49 的 fast-path / bypass 对它完全没覆盖**。一次 `reportProviderFailure` 写入的 `healthy=false`（或一次 `checkProviderHealth` 偶发失败）就在 `cacheTtlMs=30s` 内让 orchestrator 抛 "No LLM provider available"，用户表现"第一步就报错"。

**原因（两个叠加）**：

1. **路径覆盖偏科**：`ModelRouter` 对外暴露两条选源路径——`selectProviderForCall`（stepExecutor / verifyFixer 的 stream/complete 入口）和 `getProvider`（orchestrator 的 `planning` / `codeGeneration` 同步获取入口）。B49 只在前者加 `single_source_fast_path` + `bypassHealthCache` rescue，后者没碰。"修了 A 路径就以为治好了 rescue 问题"的心智断层导致第二轮用户取证才暴露缺口。
2. **副作用不完整**：`bypassHealthCache=true` 命中 `selected` 时只**绕过读缓存**，没有**写回任何正向信号**。被 `reportProviderFailure` 刚刚污染的 `healthy=false` 继续留在 cache 里——下一次 `getProvider`（没有 bypass 能力）仍然会读到 unhealthy 直接返回 null。虽然 fast-path 自己通过 bypass 兜底不崩，但观感是"rescue 成功 + 缓存僵尸"，且跨路径触发时（A 路径 bypass 成功 → B 路径继续读脏缓存）会把问题隐形导出。

**✅ 正确做法（/review 阶段强制对称性审查）**：

```
选源 / 熔断 / 健康 / 限流类"自愈"逻辑的评审清单：

□ 对外暴露几条选源入口？（grep `ModelRouter.` / `modelRouter\.` 方法调用，列全）
□ 每条入口在 rescue / fast-path / bypass 场景是否都走同一个分支？
□ bypass / rescue 命中成功时，**有没有写回正向信号 / 重置污染状态**？
  - 若有共享 cache → 显式重置（保守：lastCheckedAt=0；激进：markSuccess）
  - 若走状态机 → 显式 transition 到自愈态
□ rescue 路径的"硬约束门禁"（熔断 / 上下文 / 权限）在所有入口是否都保留？
□ 跨入口调用链（如 orchestrator → stepExecutor）是否会共享污染状态？
□ 对 LLM / 外部 API / DB 连接池 / 缓存预热等**所有**自愈类场景都做同样检查。
```

**关键教训**：

- **不要信任"修了 stream 路径就等于修好了 rescue"**。同一个 Router / Client / Pool 类暴露 N 个获取方法时，rescue 语义必须在所有入口对称，或者统一下沉到一个私有 helper 里让所有入口共享（B50 选了前者 + `isSingleSourceMode()` 抽出共享判定）。
- **"绕过读缓存" ≠ "修复缓存"**。bypass 只是临时豁免，若不写回就是把问题藏在下一个入口。B50 采用**保守重置**（`lastCheckedAt=0, healthy=true, 保留 failCount/circuitOpenUntil`）而不是激进 `markHealthSuccess`——既让下次 `getProvider` 真实探活，又不掩盖累计故障信号；circuit breaker 仍是刚性信号不突破。
- **日志"零 timeout + N 条 No provider"是强信号**：意味着选源在 LLM 调用发生**之前**就挂了，源头一定在 Router 某条路径的健康 / 缓存 / 熔断逻辑里，而不是 LLM 侧。

**❌ 错误做法**：

```ts
// 1. 只修 stream 路径，忽略同步路径
class ModelRouter {
  async selectProviderForCall() { /* ✅ 加了 fast-path + bypass rescue */ }
  async getProvider() { /* ❌ 没动 —— orchestrator 路径仍然死在健康缓存 */ }
}

// 2. bypass 成功但不写回
if (options.bypassHealthCache) {
  // 绕过 checkProviderHealth ✅
  // ...selected...
  // ❌ 下一次 getProvider 仍然读到 healthy=false
}
```

**触发条件**：

- 修改 `ModelRouter` / `ClientPool` / `CircuitBreaker` / `CacheManager` 等有多个获取入口的类
- 新增 rescue / fallback / bypass / fast-path 等"自愈"语义
- 共享状态缓存（健康 / 熔断 / 限流计数 / 租约 / token）跨多个方法读写
- 两阶段路径：caller A 写污染 → caller B 读污染（如 stepExecutor 调 reportProviderFailure → orchestrator 调 getProvider）

**快速识别信号**：

- "老代码和新代码各跑一条链"时先 `grep ^Class\.method ` 列全所有对外入口
- 看每个入口是否都用了相同的健康 / 熔断 / rescue 分支
- bypass / rescue 分支里**没有任何 write** 到共享状态 → 99% 是副作用遗漏
- `/review` 阶段问一句："如果 caller A 走 rescue 成功、caller B 紧接着调这个类的另一个方法，会看到什么？"

**对称检查**：

- 同类问题适用于 **DB 连接池**（`getConnection` vs `acquire`）、**CircuitBreaker**（`execute` vs `canExecute`）、**Redis / Cache**（`get` vs `getOrLoad`）、**限流器**（`tryAcquire` vs `acquire`）、**token 管理**（`getAccessToken` vs `refreshAccessToken`）等类的 rescue / fallback 语义。
- 凡是"对外暴露 N 个语义相近的获取/执行方法 + 内部维护共享状态"的类，**必须** rescue 语义对称 + 副作用对称。

**本次真实发生**：v0.35.11 (B49) 修复单源 LLM 环境的 rescue 死循环时，只改了 `selectProviderForCall` 加 `single_source_fast_path` + `bypassHealthCache`；全仓 1507 测试全绿、`/review` CLEARED、发布 v0.35.11。用户取证发现"第一步就 No LLM provider available"，原来 `orchestrator.ts` 的 7 处 plan 阶段调用走的是 `modelRouter.getProvider(taskType)` 完全没被 B49 覆盖。B50 补 `getProvider` 的单源 rescue 分支（发出 `rescue:single_source_getProvider`）与 `tryPickProvider` 的保守健康缓存重置（`lastCheckedAt=0, healthy=true, 保留 failCount / circuitOpenUntil`）两处；新增 3 条专项测试（单源 rescue / 熔断刚性 / 缓存重置）锁死契约；ADR-0010 ledger 补录 v0.35.11 / v0.35.12 两版决策摘要。教训：后续 `/review` 遇到 rescue / fallback / bypass 类改动时，**先列全入口再审对称性**，比盯单条链路细节更重要。

---

## G-008: Prompt 模板与静态校验器必须同源 — "我自己教的代码，我自己又检不出"

**症状**：首轮生成游戏后，质量检查报告每次稳定报相同几项 `fail`，且与同一报告中其他维度的 `pass` 结论自相矛盾（例如"解谜类专项检查 3/3 pass，但整体 HUD fail"）。用户反复反馈"质量报告不可信"，但运行时并无 `ReferenceError`、HUD 也并未真的常驻冲突——纯粹是**静态校验器**的识别面跟不上**prompt 模板**要求 LLM 写的合规代码。典型场景：

1. `referenceSnippets.ts::AUDIO_PLACEHOLDER` 常驻在首轮系统 prompt 中，教 LLM 写 `const AudioCtor = globalThis.AudioContext || globalThis.webkitAudioContext`，但 `verifyFixer.collectDefinedConstructorSymbols` 的 4 条正则只认"直接类声明 / 函数声明 / ClassExpression / FunctionExpression"，**不认识 `A || B` / 三元 / `globalThis.X` 等条件赋值**——LLM 严格按模板写 → 校验器判"AudioCtor 未定义" → 100% 稳定误报。
2. `playabilityStaticHeuristics.evaluateHudCenterConflict` 用固定变量名白名单（`startText|guideText|...`）+ 硬编码 `gameState==='ready'` 字面量 + `setVisible(false)` 单一隐藏模式。LLM 用 Phaser 合理的替代方案（`tween.onComplete → destroy()`、`this.time.delayedCall → setVisible(false)`、`this.events.once`、`group.setVisible(false)`）全都被判 `fail`，与同报告 genre 专项 3/3 pass 自相矛盾。

**原因（核心反模式）**：Prompt 模板和静态校验器是同一个"契约"的**正向面**和**反向面**——模板教 LLM "应该这样写"，校验器判定"是否这样写了"。两者由不同开发者/不同时间迭代，缺少一个**共享 truth-set** 就会漂移：

- 模板先更新（教新写法），校验器未更新 → 合规代码被判 fail（**假阳性 100%**）。
- 校验器先更新（扩识别面），模板未更新 → 少部分旧写法继续漏过，但不阻塞。

对称性在 prompt/校验两侧都需要被制度化，而非靠评审时"凭脑子对齐"。

**✅ 正确做法**：

```typescript
// 1. 把模板常量作为校验器单测的正向样本输入
import { AUDIO_PLACEHOLDER } from '../templates/referenceSnippets';
it('constructor_definition_integrity passes on our own AUDIO_PLACEHOLDER template', () => {
  const state = buildStateFromCode(AUDIO_PLACEHOLDER);
  const result = verifyGeneratedCode(state);
  const check = result.checks.find((c) => c.key === 'constructor_definition_integrity');
  expect(check?.status).toBe('pass'); // 如果 fail，要么改校验器、要么改模板，不能放着不管
});

// 2. 校验器扩展识别面时，同步追加"LLM 常见写法"golden samples
it.each(HUD_GOLDEN_SAMPLES)('hud_center_prompt_separation handles %s', (scenario, code) => {
  const result = evaluateHudCenterConflict(buildCheckContextFromCode(code));
  expect(['pass', 'warn']).toContain(result.status); // 绝不是 fail
});

// 3. 静态启发式必须有 observability（pass 率分布自监测）
recordHeuristicOutcome('hud_center_prompt_separation', status, sessionId);
// 当某 check 的 pass 率 < 20% → 标 `false_positive` 嫌疑自动报警
```

关键三件套：

- **模板 × 校验单测同源**：模板常量直接作为校验器单测输入，断言 pass。任何一方改动都会红测另一方。
- **反向用例 golden samples**：LLM 常见写法必须在校验器单测里出现，确保扩识别面后不回归。
- **自监测 observability**：进程内 ring buffer 记录每次判定，对 pass 率异常（< 20% 或 > 99%）自动标可疑。

**❌ 错误做法**：

```typescript
// 模板一处写、校验器一处写，没有任何机制保证两者对齐
// referenceSnippets.ts
export const AUDIO_PLACEHOLDER = `const AudioCtor = globalThis.AudioContext || globalThis.webkitAudioContext;`;

// verifyFixer.ts
const CONSTRUCTOR_DECLARATION_RE = /class\s+([A-Z]\w*)|function\s+([A-Z]\w*)/;  // ❌ 只认 class/function
// 测试里没有把 AUDIO_PLACEHOLDER 输入进来验证 pass
```

**触发条件**：

- 新增或修改 prompt 模板（`referenceSnippets.ts` / `promptBuilder.ts` / `systemFragments.ts`）教 LLM 新写法
- 新增或修改静态校验器（`verifyFixer.ts` / `playabilityStaticHeuristics.ts` / `webPageHeuristics.ts` / `astValidator.ts`）
- 质量报告出现"同一维度 genre 专项 pass，但整体 check fail"的自相矛盾结论
- 用户反复反馈"这个检查项总在误报"
- 质量检查 pass 率连续偏低（< 20%）且无明显证据证明问题确实这么严重

**快速识别信号**：

- 质量报告某个 check 的失败率 **100%** 或 > 80%，但 LLM 产出本身是按模板规定写的 → 99% 是校验器识别面没跟上
- 新增 prompt 模板常量但没改任何 `*Heuristics.spec.ts` / `verifyFixer.spec.ts` → 必然是一个潜在的 G-008 地雷
- `/review` 时 grep 模板常量名在 `__tests__/` 里是否出现，**没出现就是缺对齐**

**对称检查**：

- 同类问题适用于：**Lint 规则 vs 编码风格文档**（文档教 A 写法，lint 强制 B 写法）、**API schema vs 客户端 SDK**（schema 加字段，SDK 未消费）、**错误分类码 vs 前端文案映射**（后端加 `errorCode`，前端 `errorLabels.ts` 漏加）、**DB 迁移 vs ORM 模型**（DB 加列，ORM `types.ts` 未扩）。
- 凡是**契约由 A / B 两侧合作维持**的模式，都应把"A 的常量直接作为 B 的单测输入"作为第一道护栏。

**本次真实发生**：v0.35.21 (WG-1) 根治首轮质量报告误报时，根因定位到 `referenceSnippets.ts::AUDIO_PLACEHOLDER`（教 LLM 写 `globalThis.X || globalThis.Y`）与 `verifyFixer.collectDefinedConstructorSymbols`（4 条正则不识别 `A || B` 赋值）之间缺少同源对齐——"自己教的自己检不出"。修复三件套：T1.1 扩 `verifyFixer` 识别面到 6 类赋值模式 + `rhsLooksLikeConstructorSource` 反向兜底，T1.2 `evaluateHudCenterConflict` 加 7 组动态隐藏信号 + genre consensus 降级，T1.3 新建 `heuristicsObservability.ts` 进程内 ring buffer 自监测 + `HEURISTICS_DIAGNOSTIC` 环境变量诊断通道，T1.4 golden samples 合集回归 spec（把 `AUDIO_PLACEHOLDER` 原文作为正向输入 + 5 种 LLM 常见 HUD 写法作为反向用例）。教训：任何"prompt 教 LLM 这样写 + 校验器判定是否这样写了"的契约，**必须在同一个 PR 里同步改两侧 + 加 golden samples 锁死**，否则必然漂移。

---

## G-009: 浏览器 importmap + Blob URL 对子路径不透传 — AST 白名单与预览运行时协议必须同源枚举子路径

**症状**：Wave 1 落地 `@runtime/*` 受控 import 白名单后，`astValidator` 允许游戏轨 AI 代码 `import { shake } from '@runtime/juice'`（barrel） 与 `import { shake } from '@runtime/juice/shake'`（子路径），单测全绿；但真实浏览器跑 LLM 生成的 `@runtime/juice/shake` 形式的 import 时报 `Failed to resolve module specifier "@runtime/juice/shake"` 直接黑屏——而同一份代码的 `from '@runtime/juice'` barrel 写法又能正常工作。

**原因（两层叠加）**：

1. **浏览器 importmap 对 Blob URL 的子路径解析不透传**。ES module importmap 规范规定，只有当 `scopes` / `imports` 的 key **以 `/` 结尾**且值**指向 HTTP(S) URL 时**才会做"前缀替换 + 拼接剩余路径"的解析（trailing-slash semantics）；对 `blob:` URL，子路径拼接不生效（即使加了 trailing slash 也不会把 `@runtime/juice/shake` 解析为 `blob:xxx/shake`——blob URL 没有路径空间）。因此 `{ "@runtime/juice": "blob:xxx" }` 只能解析 `@runtime/juice`，子路径 `@runtime/juice/shake` 会落到"未解析"分支直接抛错。
2. **AST 白名单的"前缀匹配"与 importmap 的"exact match"协议不同源**。服务端 `ALLOWED_RUNTIME_IMPORT_PREFIXES` 用 `source === prefix || source.startsWith(prefix + '/')` 通配所有子路径（正则思维）；浏览器 importmap 是 exact-match 映射表（查表思维）。两侧没对齐 → AST 放行的路径浏览器解析不了 → 运行时 500。

**✅ 正确做法**：

```typescript
// 1. 提供唯一的子路径真源（而不是在 runtimeChunks / previewTemplate / AST 三处各写一套）
// apps/runtime/src/preview/runtimeChunks.ts
export const KNOWN_RUNTIME_SUBPATHS: Record<keyof RuntimeChunksMap, readonly string[]> = {
  '@runtime/juice': ['shake', 'flash', 'hitStop', 'tween', 'particle'], // = barrel 实际 re-export 的符号名
  '@runtime/theme': ['palette', 'fontStack', 'filters'],
};

// 2. previewTemplate 根据 subpaths 显式展开成 exact-match importmap 条目（都指向同一个 barrel Blob URL）
function buildImportmap(chunks, subpaths) {
  const imports = {};
  for (const [alias, url] of Object.entries(chunks)) {
    imports[alias] = url; // barrel entry
    for (const sub of subpaths[alias] ?? []) {
      imports[`${alias}/${sub}`] = url; // 子路径 exact match → 仍指向 barrel
    }
  }
  return { imports };
}

// 3. 单测用同一个 KNOWN_RUNTIME_SUBPATHS 同时驱动「AST 白名单子路径接受列表」与「importmap 生成断言」
it.each(KNOWN_RUNTIME_SUBPATHS['@runtime/juice'])(
  'importmap has exact entry for @runtime/juice/%s',
  (sub) => expect(map.imports[`@runtime/juice/${sub}`]).toBeDefined()
);
```

关键三件套（对应 G-008 模板×校验器同源的运行时协议版）：

- **子路径唯一真源**：barrel 实际 re-export 的符号清单就是合法子路径清单，其他地方只读不写。
- **AST 通配 → importmap exact 显式展开**：AST 可以继续用前缀匹配（服务端正则便于泛化），但预览模板必须**在注入前把通配展开成 exact 条目列表**，保证两侧运行时语义对称。
- **浏览器真实解析测试**：jsdom 对 importmap + Blob URL 的解析**不完整**（即便手动注入 script 也不会做真解析），所以 importmap 行为的最终兜底**必须**在 browser-harness 真实 Chrome smoke 或等价真实浏览器 E2E 中验证；纯 jsdom 单测最多能验"HTML 里确实有这条 entry"（结构断言），验不了"浏览器真能按它解析 module specifier"（语义断言）。

**❌ 错误做法**：

```typescript
// 1. 把"AST 允许 A/B" 当成 "importmap 也自动允许 A/B 的子路径"
const ALLOWED = ['@runtime/juice', '@runtime/theme'];
const astOK = (src) => ALLOWED.some(p => src === p || src.startsWith(p + '/'));
// importmap: { "@runtime/juice": blobUrl, "@runtime/theme": blobUrl } // ❌ 子路径解析不了
// AST 放行 `@runtime/juice/shake` → 浏览器 "Failed to resolve module specifier"

// 2. 依赖 trailing-slash 语义（对 HTTP URL 有效，对 Blob URL 无效）
const importmap = {
  "@runtime/juice/": "blob:xxx/"  // ❌ blob URL 没有子路径空间
};

// 3. 只在 jsdom 里测 importmap，没用浏览器 E2E 兜底
it('module resolves in sandbox', async () => {
  const iframe = createIframe(html); // jsdom iframe 不会真跑 importmap
  await import(/* @vite-ignore */ '@runtime/juice/shake'); // ❌ 根本没跑到浏览器
});
```

**触发条件**：

- 用 `<script type="importmap">` + `blob:` / `data:` URL 把 ESM 子模块注入 iframe 沙箱
- 服务端 AST / 安全校验用"通配/前缀/正则"允许 bare specifier + 子路径，但预览模板是"查表式" importmap
- jsdom 单测对 module specifier resolution 不模拟（`new URL('@runtime/x', blob:...)` 走的是 URL 解析而非 importmap）
- 有"barrel alias + 子模块 re-export"架构（`index.ts` re-export 多个子文件）

**快速识别信号**：

- AST / 安全校验单测出现 `describe('accepts subpath', () => { it('@runtime/juice/shake', ...) })` 但预览模板测试只断言 barrel → 必然漂移
- 浏览器控制台报 `Failed to resolve module specifier` 但服务端日志无 AST 拒绝记录 → 协议两侧不对称的信号
- 所有单测全绿但手动 smoke 第一次就黑屏 → jsdom / 单元测试覆盖不了的"真实浏览器协议语义"盲区

**对称检查**：

- 同类问题适用于：**Service Worker cache + 请求路径**（cache key 通配 vs 浏览器 request exact match）、**CSP `script-src` + nonce / hash**（配置通配 vs 浏览器 exact match）、**iframe `sandbox` 属性 + postMessage origin**（后端允许 `*` vs 浏览器实际传入 exact origin）、**DNS wildcard + TLS SAN**（wildcard 证书只允许一级子域名，不允许任意深度）。
- 凡是**服务端用通配/正则写"允许集"，浏览器按 exact-match 查表执行**的协议，都要显式展开通配到 exact 列表，或把 exact 列表反向校验一次"通配是否有漏网之鱼"。

**本次真实发生**：v0.36.0 Wave 1 Runtime 地基落地 `@runtime/*` 受控 import 时，`astValidator.spec` 的子路径测试用 `@runtime/juice/shake` 覆盖、`previewTemplate.spec` 的 importmap 测试用 `@runtime/juice` barrel 覆盖，两侧单测全绿；`/review` 阶段交叉比对发现 AST 允许的 "shake" / "flash" 子路径在实际 importmap 里**不存在 exact 条目**，浏览器会黑屏。AUTO-ASK 用户选择 "expand importmap"（而非收窄 AST 白名单），**Fix**：在 `runtimeChunks.ts` 新增 `KNOWN_RUNTIME_SUBPATHS` 作为唯一真源，`previewTemplate.buildRuntimeChunksScript` 根据 subpaths 参数展开每个 `alias/subname` 为 exact importmap entry 都指向同一个 barrel Blob URL，新增 T20/T21/T22 三条测试断言展开结果 + `runtimeImportWhitelist.integration.spec` 加两条跨 AST / previewTemplate 集成测试锁死"AST 放行的子路径 ↔ importmap 一定有对应条目"。**未来仍有的一块兜底**：jsdom 没有真实 importmap + module specifier resolution，这类"协议两侧对称性"的最终运行时兜底必须在浏览器 smoke（Wave 1 已转 BACKLOG [P0 🔥] 追踪）里闭环。教训：运行时协议不是"通配等价于展开"——服务端写通配是便于泛化 + 防御深度，前端写 exact 是被浏览器规范所迫，两侧之间必须**由一个共享常量驱动展开**而非靠评审脑力对齐。

---

## G-010: 模板隐含前提 vs LLM "教科书记忆" — few-shot 示例必须显式反例化禁用 API

**错误现象**：

- 用户手动 smoke 打砖块游戏，预览瞬间报 `[onerror] Uncaught TypeError: brick.disableBody is not a function`
- 砖块无法消除，控制台一条错误后游戏死循环（ball 穿过本应消除的 brick）
- 服务端日志正常：代码生成成功、AST 校验放行、预览 bundle 200 构建成功
- 但 genre 模板里明明写的是 `brick.destroy()`，实际运行的 AI 生成代码写的是 `brick.disableBody(true, true)`

**根本原因**：

1. **"低资源"姿势的隐含前提未显式传达**。`brick-breaker.ts` 模板为了不依赖 texture 资源（首轮生成最大障碍是素材），选择 `this.add.rectangle(...) + this.physics.add.existing(brick, true)` 创建砖块。这条路径产出 `GameObjects.Rectangle` + 外挂 Arcade Body，**没有** `Arcade.Components.Enable` mixin，所以 `disableBody()` / `enableBody()` / `setTexture()` 等 Sprite/Image 专属方法全部不存在。但这个"隐含前提"只存在于模板作者脑子里，LLM 完全看不到。
2. **LLM 的先验 > 模板的显式姿势**。Phaser 官方 Breakout 教程、StackOverflow 经典答案、YouTube 教程里，打砖块都是用 `this.physics.add.staticGroup() + group.create(x,y,'brick')` 产出 `Arcade.Image`，然后 `brick.disableBody(true, true)` 是**教科书标准写法**。LLM 训练数据里这个搭配权重极高。结果：模板只示范了 `brick.destroy()`（隐含"因为是 Rectangle 不能 disableBody"），但 LLM 以为自己在"优化写法"，把 destroy 换成了更专业/更常见的 disableBody → 运行时爆炸。
3. **测试覆盖盲区**。genre 模板 spec（`genres.spec.ts`）只校验"模板本身是合法代码 + 产出 ≥ minFiles 个文件"，不校验"LLM 拿模板生成的真实代码是否保持模板的隐含前提"。playabilityStaticHeuristics 当前只盯 HUD / 状态机叠层 / runner 闭环，不识别"Rectangle 上调用 Arcade.Sprite 专属方法"反模式。verifyFixer 没有"Rectangle × disableBody"语义检查 rubric。三层兜底全漏。
4. **预览沙箱 `onerror` 冒泡可见但不阻断生成**。错误正确进入 `parent postMessage`，用户能看到红字，但代码已经进入 artifact 存储 + 工作台 composer，不会触发任何"生成失败"回滚——UX 上"代码成功生成"与"游戏完全不能玩"同时出现，误导性极强。

**✅ 正确做法**：

```typescript
// 1. 模板里显式写入"反例化禁用 API"注释（即刻生效，降低下一次 LLM 调用再犯概率）
// apps/server/src/agents/codegen/templates/genres/brick-breaker.ts
// ⚠️ brick 是 GameObjects.Rectangle + 外挂 Arcade Body（不是 Arcade.Sprite/Image）
//    → 消除砖块只能用 brick.destroy()，禁止 brick.disableBody(...)（该 API 仅 Arcade.Sprite/Image 才有）
const brick = this.add.rectangle(bx, by, w, h, color);
this.physics.add.existing(brick, true);
this.bricks.add(brick);
// ...
hitBrick(ball, brick) {
  // ⚠️ 必须是 brick.destroy()；brick 是 Rectangle，没有 disableBody() 方法
  brick.destroy();
}

// 2. promptBuilder 四段式"约束段"显式列出禁用 API 清单（Wave 2 落地）
const CONSTRAINT_SEGMENT = `
【禁用 API · 基于本次模板路径】
- 使用 this.add.rectangle(...) + physics.add.existing(...) 创建的对象是 Rectangle + 外挂 Body，
  禁止调用 Arcade.Sprite/Image 专属方法：disableBody() / enableBody() / setTexture() / anims.play() 等。
  消除对象必须用 obj.destroy()。
`;

// 3. playabilityStaticHeuristics 新增反模式识别（Wave 2 落地）
function evaluateRectangleArcadeApiMisuse(allCode: string): StaticSubcheck {
  // 收集所有通过 add.rectangle 创建的对象名
  const rectVarRe = /(?:const|let|var)\s+(\w+)\s*=\s*this\.add\.rectangle\s*\(/g;
  const rectNames = new Set<string>();
  let m; while ((m = rectVarRe.exec(allCode)) !== null) rectNames.add(m[1]);
  // 扫 Arcade.Sprite 专属方法调用
  const misuseRe = /(\w+)\.(?:disableBody|enableBody|setTexture|anims\.play)\s*\(/g;
  const violations: string[] = [];
  let mm; while ((mm = misuseRe.exec(allCode)) !== null) {
    if (rectNames.has(mm[1])) violations.push(`${mm[1]}.${mm[0].match(/\.(\w+)/)?.[1]}`);
  }
  if (!violations.length) return { key: 'rectangle_arcade_api_misuse', status: 'pass', ... };
  return {
    key: 'rectangle_arcade_api_misuse',
    status: 'fail',
    detail: `【可玩性】Rectangle 对象调用了 Arcade.Sprite/Image 专属 API：${violations.join(', ')}。
    建议改为 obj.destroy() 或改用 this.physics.add.sprite(...) 创建对象。`,
  };
}

// 4. verifyFixer rubric 自动改写（Wave 2 落地）
//    匹配 <rectVar>.disableBody(...) → <rectVar>.destroy()
//    前置条件：同作用域 rectVar 由 this.add.rectangle(...) 创建
```

**❌ 错误做法**：

```typescript
// 1. 模板只写"正确姿势"而不显式禁用错误姿势
const brick = this.add.rectangle(...);
this.physics.add.existing(brick, true);
// ...
hitBrick(ball, brick) {
  brick.destroy();  // ❌ LLM 看到会以为"教程姿势 disableBody 也行，只是这里写得保守了"
}

// 2. 把"隐含前提"藏在 TypeScript 类型注释里
/** @param brick Phaser.GameObjects.Rectangle */  // ❌ LLM 不读 JSDoc 类型也会照样错写
hitBrick(ball, brick) { ... }

// 3. 只靠 AST 白名单兜底（AST 不会拒绝 brick.disableBody —— 这是合法的 member access）
```

**触发条件**：

- 为了降成本/不依赖资源而采用"非标准 + 但能用"的对象创建姿势（Rectangle + existing / Circle + existing / Container + 外挂 Body）
- 该姿势创建的对象**少了** mixin（Enable / Flip / Crop / Animation），但 member access 在 JS 里是动态的 → AST / 类型系统都拦不住
- 被拦截的 API 有极强的"Phaser 教科书常见写法"先验（disableBody / setTexture / play 等都是高权重 token）
- 模板作者假定"示范 destroy() 就等于禁用 disableBody()"，但 LLM 的推理是"看到 destroy 觉得可以优化为 disableBody"
- 没有单测 / 启发式 / verifyFixer rubric 任一层反向锚定"禁用集"

**快速识别信号**：

- 运行时 `TypeError: X is not a function` 且 `X` 是 Arcade.Sprite/Image 专属方法（`disableBody` / `enableBody` / `setTexture` / `anims.play` 等）
- 同一个对象 `this.add.rectangle(...)` / `this.add.circle(...)` / `this.add.graphics(...)` 创建
- 服务端日志显示 AST 校验放行、预览 bundle 正常、但手动复现必现报错
- 模板本身是正确的，但 AI 生成代码偏离了模板的"隐含前提"

**对称检查**：

- 同类问题适用于：**`this.add.container` + 外挂 Body**（无 `setCollideWorldBounds` / `setVelocity` 等 Body-proxy 方法）、**`this.add.graphics`**（无 `x/y` 直接拖动）、**`StaticBody` 调用 `setVelocity`**（静态体无速度）、**React 函数组件里写 `this.setState`**（函数组件无 `this`）、**Python dict 调用 list 方法**（结构相似但方法集不同）。
- 凡是**"同一领域内有两种结构相似但 API 集不同的类型"且**"一种是教科书高权重 / 另一种是项目实际采用"的场景，模板必须同时提供**正向示范 + 反向禁用清单**，仅靠正向示范会被 LLM 的先验覆盖。

**本次真实发生**：v0.36.0 Wave 1 完成后用户在工作台手动 smoke 打砖块游戏，真实报错 `[onerror] Uncaught TypeError: brick.disableBody is not a function at .../moaup5zndu9x5geio/.../index.html:755:13`。根因是 AI 偏离 `brick-breaker.ts` 模板第 136 行的 `brick.destroy()`，写成了 Phaser 官方 Breakout 教程的经典 `brick.disableBody(true, true)`（但教程用的是 `staticGroup().create()` 产 Arcade.Image，我们用的是 `add.rectangle() + physics.add.existing()` 产 Rectangle，两种对象的 API 集不同）。**即时兜底**（v0.36.0 patch）：`brick-breaker.ts` 模板在创建 brick 处与 `hitBrick` 处各加一条反例警示注释，显式告诉 LLM "禁止 disableBody(...) "。**Wave 2 根治三件套**：（a）promptBuilder 四段式"约束段"显式列出 Rectangle + existing 路径的 API 禁用清单；（b）`playabilityStaticHeuristics` 新增 `rectangle_arcade_api_misuse` 反模式识别；（c）`verifyFixer` 新增 `rectangle_api_misuse` auto-rewrite rubric 把 `rectVar.disableBody(...)` 改写为 `rectVar.destroy()`。已作为 BACKLOG [P1 🔥] Wave 2 First Failing Case 条目追踪，纳入 Wave 4 50 次盲测协议的"已知 failing case"benchmark 样本。教训：**模板里的正确姿势不等于 prompt 里的约束集**——模板能解释"该写什么"，但反模式化清单才能阻止 LLM 用先验覆盖模板姿势；few-shot 示例的"隐含前提"必须显式写成"禁用 API 注释"，否则 LLM 会按教科书先验填回。

---

## G-011: Wave 2 三件套 wedge 落地（brick.disableBody 案复盘）

**前置**：见 G-010 的完整根因分析（模板隐含前提 vs LLM 教科书记忆冲突、`brick.disableBody is not a function` 真实 smoke）。G-011 记录 **Wave 2 v0.37.0** 把 G-010 的"三件套"从设想推进到"集成验证"阶段的落地坐标 + 骨架状态，便于后续同构风险复用相同范式。

**摘要**：把"prompt 约束段 / 静态启发式 / auto-rewrite"三件套分别落在三个稳定模块里，由三位并行 Agent（A/B/C）各自闭环实现，另由 Agent D 产出对称性审计 + 同构风险 BACKLOG 沉淀。

**三件套落地位置**：

- **Prompt 约束段（Agent A）**：`apps/server/src/agents/codegen/templates/systemFragments.ts::RECTANGLE_ARCADE_API_CONSTRAINT`，注入 `promptBuilder` 的"约束段"分段（即 Wave 2 四段式 prompt 的 Constraints 段落）。内容逐条列出 `Rectangle + physics.add.existing` 路径的 API 禁用清单（`disableBody` / `enableBody` / `setTexture` / `setFrame` / `anims.play`），并显式指示消除 = `obj.destroy()`。
- **静态启发式（Agent B）**：`apps/server/src/agents/codegen/playabilityStaticHeuristics.ts::evaluateRectangleArcadeApiMisuse`，key=`rectangle_arcade_api_misuse`。扫 `this.add.rectangle(...)` 创建的变量名集合，在同作用域内命中 `.disableBody(` / `.enableBody(` / `.setTexture(` / `.anims.play(` 时 fail，附建议文案（改 destroy 或改 `physics.add.sprite`）。
- **auto-rewrite（Agent C）**：`apps/server/src/agents/codegen/verifyFixer.ts::applyRectangleArcadeApiRewrite`，rubric id=`rectangle_api_misuse`。在同源锚点（rect 变量由 `this.add.rectangle` 创建）前置条件下，把 `rectVar.disableBody(...)` 改写为 `rectVar.destroy()`；失败回退到静态启发式信号。配套 `templates/rectangleArcadeApi.ts` 作为模板层共享常量（rewrite rubric 与 constraint 段同源）。

**骨架状态**（与 v0.37.0 集成验证共存）：

- `apps/server/src/agents/codegen/templates/referenceSnippets/` 目录化（Wave 0 已完成）：为后续 genre × constraint 分片管理预留槽位。
- `visual_style_compliance` rubric slot（Wave 2 占位 `weight=0`，Wave 3 补正文）：避免 Wave 3 视觉风格契约落地时再改 rubric 注册表结构。
- 启发式自监测（WG-1 产物）`HEURISTICS_DIAGNOSTIC=true` 通路保留：三件套上线后首轮 pass 率曲线可直接消费该通路数据评估误报/漏报。

**同构风险**：brick case 不是孤例——"模板选低资源路径 / LLM 按教科书高权重写法优化回完整路径"是一个**问题范式**，在 9 个 genre 模板与相邻层至少还有 4~5 条同构风险（Container + 子对象 Body / Graphics 误用 Sprite API / StaticBody 调用 dynamic-only 方法 / Container.alpha 级联语义），已在 `docs/arch/ast-template-mismatch-symmetric-audit.md` 系统性枚举并登记 BACKLOG（P2/P3 分层）。Wave 3 优先级以 WG-1 自监测数据驱动。

**落地版本**：v0.37.0（Wave 2 集成验证通过后发布）；与 BACKLOG [P1 🔥] Wave 2 First Failing Case 条目双向绑定（该条目在本 Wave 收敛后标 done 并入 CHANGELOG）。

**对称检查清单**（后续同构风险复用时走一遍）：

- [ ] prompt 约束段常量 + 启发式 key + auto-rewrite rubric id **三者同源**（命名约定：`<pattern>_api_misuse` / `<pattern>_arcade_api_misuse`），避免跨文件漂移。
- [ ] 启发式扫的锚点（变量来源）与 auto-rewrite 的锚点**同一条判定逻辑**（G-008 范式：模板 × 校验器同源）。
- [ ] golden samples 回归 spec 覆盖"正向 pass"+"反向 fail"+"auto-rewrite 幂等"三类用例（`playabilityStaticHeuristics.spec.ts` / `verifyFixer.spec.ts` / `referenceSnippets.spec.ts`）。
- [ ] BACKLOG 收敛该条时同步登记到 benchmark 样本清单（见"简单的打砖块小游戏"决策）。

**本次真实发生**：v0.37.0 Wave 2 把 G-010 的三件套设想落地为三条可运行 wedge，由 4 个并行 Agent（A/B/C 实现 + D 审计）同一版本闭环完成。Agent D 产出 `docs/arch/ast-template-mismatch-symmetric-audit.md` 枚举 5 大同构风险 + 1 条跨轨参照，BACKLOG 新增 4 条 P2/P3 条目避免 Wave 2 scope 扩散。教训：**问题范式一旦抽象成功，三件套 wedge 是高性价比的复用模板**——每个同构 case 大约一个工作日的边际成本；但必须用"自监测数据"而非"脑力直觉"决定批量铺开顺序，否则会把误报面放大到启发式本身不可信。

---

## G-012: Wave 3 首轮生成质量体系升级（WG-2 + WG-3 + WG-4 三合一）

**前置**：G-011 把 Wave 2 三件套 wedge 落地对完 brick.disableBody 案，但首轮生成"能运行但朴素"——调色板随机 / 字体族不统一 / HUD 与主场景叠压。G-012 记录 **Wave 3 v0.38.0** 把"首轮主观质量"从静态启发式层上提到 **Prompt 结构 + 视觉风格契约 + Benchmark 基线**三合一体系升级的落地坐标与经验沉淀。

**摘要**：四段式 Prompt 结构（WG-2）+ `VisualStyleDirective` 共享契约（WG-3）+ 24 prompt × 2 档 Benchmark 基线（WG-4）+ 7 genre few-shot 示范对（Agent γ）一版发布，**用数据而非直觉**驱动 Wave 4 方向决策。

**三大楔子落地位置**：

- **四段式 Prompt 结构（WG-2）**：`apps/server/src/agents/codegen/promptBuilder.ts::buildSystemPrompt` 从单层线性拼接重构为"§ 1 角色设定 / § 2 约束 / § 2.5 视觉风格契约（动态渲染）/ § 3 范例 / § 4 自省清单"五段式；`templates/systemFragments.ts` 新增 `GAME_ROLE_DIRECTIVE` / `GAME_SELF_REFLECTION_CHECKLIST` 两个头常量；自省清单显式包含"HUD 与主场景元素叠压自检" + "调色板 ≤ 6 主色自检"两条硬指令；compact / first_pass 通道保留兜底。
- **视觉风格契约（WG-3）**：`packages/shared-types/src/visualStyleDirective.ts` 新建 `VisualStyleDirective` interface + Zod schema（`palette` + `typography` + `layout` + `visualTheme` 四字段 + `VISUAL_THEME_IDS` 5 主题枚举）作为 **shared-types 正式契约**（为 Wave 4 "LLM 自主选择 visualTheme"升级铺路）；`workflowPlanner.ts::inferVisualStyleDirective(genre, difficulty)` 规则式推导 directive；`orchestrator.ts` 新建对话 game 分支写入 `CodeGenState.visualStyleDirective`；`promptBuilder.ts::renderVisualStyleSection(directive)` 按 directive 渲染 § 2.5 4 行文本；`playabilityStaticHeuristics.ts::evaluateVisualStyleCompliance` 三维度启发式（palette 去重 ≤ 6 / 字体族 ≤ 2 / HUD AABB 非重叠）；`verifyFixer.ts` `visual_style_compliance` rubric weight 从 v0.37.0 占位 0 升为 `VISUAL_STYLE_COMPLIANCE_WEIGHT=3` + fail 时 `determineVerdict` 降级 `needs_fix`（**"fail-downgrade"语义而非硬门禁 block**·避免视觉误报 kill 真 playable 产物）；阈值常量集中在 `templates/visualStyleCompliance.ts`。
- **Benchmark 基线（WG-4）**：`scripts/codegen-benchmark/runFirstPass.ts` first-pass adapter（ModelRouter 单轮 stream + `extractCodeBlocks` + `verifyGeneratedCode` **最小闭环**）+ 24 prompt 样本（8 genre × 3 complexity）+ `WAVE3_WG3_ENABLED` env flag 解耦 WG-2 / WG-3 注入 + CSV + MD 报告归档 `results/{wg2-only,wg2-wg3}-<date>.csv` + `results/diff-*-<date>.md`；benchmark 目录独立 `package.json` + `"type": "module"` 让 `tsx` 按 ESM 解析跨包 import（见 G-009 同类 importmap / ESM 坑）。
- **7 genre Few-shot 战略填充（Agent γ · B-3 路径）**：`templates/referenceSnippets/genres/` 新增 `catch-game` / `endless-runner` / `platformer` / `arcade-shooter` / `arcade-dodge` / `puzzle-match` / `tap-rhythm` 7 个文件，每个 `bad` 示范对 `antipatternNote` **反向链到** `docs/arch/ast-template-mismatch-symmetric-audit.md` 对应风险编号（# 1 / # 2 / # 3 / # 5），让 Wave 2 审计报告从"死文档"变成首轮生成运行时预防层。

**Benchmark 数据驱动决策（核心教训 · 最重要）**：

- **效果确证**：两档 benchmark（n=24 each, Gemini 3.1 Pro 真实调用）显示 `visual_style_compliance` fail 数 4 → 1（-75%），验证 WG-3 视觉契约在 prompt 层 + 启发式层确实降低违反率。
- **协同覆盖显著**：`rectangle_arcade_api_misuse` / `static_body_dynamic_api_misuse` fail **两档均为 0**——说明 v0.37.0 Wave 2 三件套 wedge + v0.38.0 bad few-shot 反例 **协同覆盖已足够**，不需要为每个同构风险单独开辟三件套（原 BACKLOG P2 StaticBody / Container / Graphics 三条 **数据驱动降级到 P3**）。
- **意外收益**：TTFT p95 改善 -23.8s（WG-3 包更精确的视觉描述让 Gemini implicit cache 命中率上升，符合 v0.35.15 B52 `stickyRouting` 观测），证明"更多约束 = 更慢"是直觉误解。
- **瓶颈识别**：`needs_fix` 率 79%（19/24），确认 Wave 4 主要瓶颈是 `game_loop / input_feedback / hud / difficulty` 启发式本体覆盖不足，**不是**视觉风格或同构 API 误用——这是纯粹靠数据而不是直觉才能得出的结论。

**关键决策范式**（沉淀为后续 Wave 复用）：

- **契约 vs 内部类型选择**：`VisualStyleDirective` 放在 shared-types 而非 agent 内部，**为未来升级留协议扩展空间**（Wave 4 "LLM 自主选择 visualTheme"不用破协议）；代价是改动面稍大，收益是下次扩展零迁移成本。
- **fail-downgrade vs 硬门禁**：首版 weight=3 + fail → `needs_fix` 而非 weight=10 + verdict-block，避免启发式误报 kill 真 playable 产物——**启发式可信度需要数据积累后再逐步加权**。
- **Benchmark 简化策略**：first-pass 单轮 adapter 而非 orchestrator 全流程回放，每 prompt 1 次 LLM 调用而非 5-6 次（成本从 ≈ ¥15 降到 ¥3 / 档），**aligned 于"首轮生成质量"意图且成本可控**。
- **两档对比设计**：`WAVE3_WG3_ENABLED` env flag 解耦 WG-2 / WG-3 注入，**同一 benchmark runner 跑两次**生成 diff 报告——比 A/B 测试两条平行 CI 流水线成本低一个数量级且结果直接可对比。

**遇到的真实坑**：

- **`vi.mock` + `inferVisualStyleDirective` 新导出** → `vitest` 报错 `No "inferVisualStyleDirective" export is defined on the "../workflowPlanner.js" mock`。修复：把 `vi.mock('../workflowPlanner.js', () => ({ ... }))` 改为 `vi.mock('../workflowPlanner.js', async (importOriginal) => ({ ...await importOriginal(), inferVisualStyleDirective: vi.fn(...) }))`——`importOriginal` 透传所有既有导出的同时允许精确覆写，避免"新增导出必须同步更新所有 mock"的脆弱性。
- **`tsx` 默认 CommonJS 解析跨包 ESM exports** → `ERR_PACKAGE_PATH_NOT_EXPORTED: './preview' is not defined by "exports" in @vibe-game-creator/runtime/package.json`。修复：`scripts/codegen-benchmark/` 独立 `package.json` + `"type": "module"`，让 `tsx` 只对 benchmark 目录按 ESM 解析而不影响其他包。见 G-009（importmap / ESM / 子路径）的同类模式。
- **Heuristic 硬编码 DEFAULT_GAME_HEIGHT=600** → 对竖屏游戏可能误判（本轮 8 genre 全横屏故未触发）。留 Wave 4 改扫 `this.game.config` 或 Phaser scene size 精确获取画布尺寸。
- **`VisualThemeIdEnum` 定义 5 主题但 `pickVisualTheme` 仅覆盖 3** → `minimal-flat` / `dark-sci-fi` 暂不可达（fall-through 到 `pixel-retro`），**刻意保留**作为 Wave 4 "LLM 自主选择 visualTheme"的激活锚点；不是 bug 是 forward-compat 契约。

**对称检查清单**（后续首轮质量体系升级走一遍）：

- [ ] 契约（如 `VisualStyleDirective`）放 shared-types 而非 agent 内部 —— 为未来协议扩展留空间
- [ ] 启发式首版用 **fail-downgrade** 而非硬门禁 —— 误报容忍度 > 漏报容忍度
- [ ] Benchmark 设计 **两档对比 env flag** —— A/B 数据比单档绝对值更能驱动决策
- [ ] few-shot `bad` 示范对 **反向链到审计文档** —— 让死文档变活预防层
- [ ] 新增共享类型导出时 **批量扫描 `vi.mock` 调用点** —— 使用 `importOriginal` 模式预防 mock 脆弱性
- [ ] 数据驱动 BACKLOG —— 用 benchmark 结果决定 P2→P3 降级，不靠直觉

**本次真实发生**：v0.38.0 Wave 3 把 v0.37.0 的"首轮质量骨架 slot"一版填满，Agent γ 策略的 `bad` 反例 few-shot 让 v0.37.0 Wave 2 审计报告从"死文档"变成运行时预防层，benchmark 数据明确告诉我们 Wave 4 该聚焦 heuristics 本体扩容（79% `needs_fix` 率）而非继续叠加同构风险 wedge。教训：**"首轮生成质量"是长期工程，需要客观回归基线而不是直觉判断**——benchmark runner 一次性投入，后续每次 Wave 都能用同一套数据对齐方向，ROI 极高。

## G-013: "高失败率"在归因前不等于"规则覆盖不足"——先区分 false_positive vs true_positive 再决定 Wave 方向

**症状**：v0.38.0 benchmark 报告 `needs_fix` 率 79%（19/24），`restartability` / `hud` / `input_feedback` 三个维度 fail 数占比最高。直觉结论是"heuristics 覆盖不够，要加新规则 / 加新 few-shot"。按这个方向规划 Wave 4 会导致：模板/规则膨胀 → 维护成本指数上升 → 真实 true_positive 仍然覆盖不全（因为方向错了）。

**根因（两层叠加）**：

1. **Genre 路由静默回退放大 false_positive**。`getGenreChecklistDefinition('endless-runner')` 在 benchmark 传入的 genre（如 `endless-runner` / `arcade-shooter` / `puzzle-match`）不在 `GENRE_CHECKLISTS` 注册表时，静默 fallback 到 `casual` 默认清单。用 `casual_quick_restart` 等 casual 专属规则判定 runner 代码的 `restartability`，自然全面 fail——这不是"规则不够"，而是"用错了规则"。
2. **规则白名单字符串穷举放大 false_positive**。`restartability.casual_quick_restart` 的 `matcher.any` 只枚举 `/restart\(/` / `/startGame\(/` 两个函数名，漏了 LLM 同样常见的 `restartGame()` / `resetGame()` / 中文"重新开始"；`evaluateHudCheck.hasReadableSignals` 只扫 `scoreText` / `lifeText` 等 5 种固定变量名，漏了 `this.scoreText` / `scoreLabel` / `levelDisplay` / 中文"分数:" 等变体。LLM 严格按模板写 → 合规代码被误判 fail。和 G-005（安全正则白名单枚举）、G-008（模板 × 校验器同源）是同一族问题——**防御性规则过严导致 false_positive 压倒 true_positive**。

**✅ 正确做法（Wave 方向决策前必做的归因步骤）**：

```
第 1 步（分类）：把 N 条 fail 样本按"false_positive / true_positive / structural"三分类
  - false_positive = 代码其实已达标，但规则没识别（规则问题）
  - true_positive = 代码确实有问题（模板/few-shot 问题）
  - structural = benchmark 配置问题（genre 路由 / 测试样本本身不合理）

第 2 步（取证）：对"false_positive 嫌疑"样本做人工 spot check
  - 抽 5~10 条，读代码 + 对照规则，确认是规则漏识别还是代码真有问题
  - 写 revalidateSpotcheck.ts 脚本零 LLM 成本重跑 verifyGeneratedCode，验证修改规则后分类正确

第 3 步（决策）：按分类比例决定 Wave 方向
  - false_positive > 60% → 分支 B：放宽启发式 + 补 genre 路由（规则工程）
  - true_positive > 60% → 分支 A：补 few-shot 反例 + auto-rewrite rubric（模板工程）
  - 混合 ≤ 60% → 分支 C：两条同时做（但风险高，优先取证是否还有更深的结构性问题）
```

关键三件套：

- **AI agent 辅助分类**：对 N 条样本用一个独立 LLM call 做规则式分类（读代码 + 读规则 + 输出 `verdict: false_positive | true_positive | structural`），避免"人力评审 24 条样本"的认知偏差。
- **零成本 spot check 脚本**：`revalidateSpotcheck.ts` 从已归档的 CSV / capture 里取代码片段，本地重跑 `verifyGeneratedCode`——不依赖真实 LLM，验证"改规则后分类是否翻转"。
- **显式 genre alias 表**：静默 fallback 是 anti-pattern。任何"A 归约到 B 默认"的行为都应该在**一张 alias 表**里显式声明（`endless-runner → runner`），让读者一眼看清路由关系，测试可以断言。

**❌ 错误做法**：

```typescript
// 1. 只看 fail 率决定方向，不分类
if (needsFixRate > 0.5) addMoreRules(); // ❌ 80% fail 可能 95% 是 false_positive

// 2. 静默 fallback
function getGenreChecklistDefinition(genre: string) {
  return GENRE_CHECKLISTS[genre] ?? GENRE_CHECKLISTS['casual']; // ❌ 静默 fallback
}

// 3. 规则白名单字符串穷举
const RESTART_PATTERNS = [/restart\(/, /startGame\(/]; // ❌ 漏 restartGame/resetGame/中文

// 4. 没有人工 spot check 直接加新规则
// "fail 率高 → 加新规则 → 回归测试绿 → 合并" —— 新规则也可能是 false_positive 源头
```

**触发条件**：

- Benchmark / 回归报告出现"同一维度 fail 率 > 50%" 的强信号
- 规则作者用"常见写法白名单"思路写 matcher（枚举几个典型名字就觉得够）
- 存在"默认兜底 genre / 默认兜底规则"的静默 fallback 路径
- 缺少按"false_positive / true_positive"分类的归因步骤
- 规划 Wave 时"按 fail 率从高到低" 排优先级而不问根因

**快速识别信号**：

- 某维度 fail 率 > 80% 但 LLM 产出在人工阅读下确实能玩 → 99% 是 false_positive
- 规则匹配器里出现 `/(?:a|b|c|d)\(/` 长枚举 → 问自己"LLM 还会写什么变体？中文？驼峰变化？"
- 代码里 `GENRE_CHECKLISTS[unknown] ?? DEFAULTS` 之类静默兜底 → 99% 是 silent routing bug
- `/review` 阶段看见"新规则 / 新 few-shot"为主的 Wave 方向但没有 false_positive / true_positive 数据 → 先补归因再规划

**对称检查**：

- 同类问题适用于：**Lint 规则误报率**（严格 lint 导致合规代码被误报 → 开发者关 lint）、**告警系统误报率**（告警太多 → 告警疲劳 → 真告警被忽略）、**垃圾邮件过滤 false_positive**（正常邮件进垃圾箱 → 用户弃用过滤器）、**CI 抖动测试**（flaky test → 开发者 `--retry` 绕过 → 真 bug 被掩盖）。
- 凡是**"判定系统 + 高失败率 + 下游决策成本高"**的场景，都应先做 false_positive / true_positive 归因再决定方向，而不是凭失败率直接扩规则。

**本次真实发生**：v0.39.0 Wave 4 规划阶段，v0.38.0 benchmark 报告 `needs_fix` 率 79%，直觉方向是"补 heuristics + 补 few-shot"。`/think` 阶段先做 AI agent 标注（23 条 fail 样本）得出 **22/23 = 95.7% false_positive**——其中 `restartability` 100% 是 genre 路由把 `endless-runner` / `puzzle-match` 静默 fallback 到 `casual`；`hud` 70% 是规则白名单穷举漏 `this.scoreText` / 中文"分数:" 变体。**Wave 方向从"分支 A（补 few-shot）"翻转到"分支 B（修 genre 路由 + 放宽规则）"**。实际落地 3 行代码级别改动（genreAliases 表 + 3 条 restart matcher + 12 条 hud regex）+ 11 条回归测试，benchmark 结果：`playable` 4.2% → 41.7%（10×），`needs_fix` 87.5% → 50%（-37.5pp），`restartability` fail 17 → 3（-82.4%）。**如果当时走了分支 A（补 few-shot）会怎样**：估计需要为 8 genre × top-2 维度 = 16 组 good/bad 示例 + 16 组对比测试 = 数百行代码 + 更严的 prompt 长度，效果还不一定比分支 B 好——因为根因是"路由错 + 规则过严"，不是"LLM 不知道怎么写"。教训：**遇到"高失败率要不要加规则"的分叉路口，花半天做 false_positive / true_positive 归因比直接开干更高 ROI**；静默 fallback 是"看似稳健"的反模式，任何归约关系都应该显式登记到 alias 表并测试；规则白名单枚举和安全正则同理——宁可 over-accept 少数假阴性，也不要 over-reject 把合规产物全部打回。

---

## G-014: 配置与子包脚本不能只看源码通过，要跑真实入口

**症状**：本地评审时源码看起来已经把 timeout 提到了 `config.ts`，但 `LLM_REFINEMENT_INTENT_TIMEOUT_MS=abc` 会被 `Number(...)` 解析成 `NaN`，最终传入 timeout 逻辑；另一个常见形态是子包脚本直接写 `tsc --noEmit`，在非 workspace 子目录运行时 `tsc` 不在 PATH，实际门禁报 `sh: tsc: command not found`。

**原因**：这类问题不在业务逻辑分支里，而在"真实启动/真实脚本入口"处暴露：

- 环境变量解析如果只做 `Number(process.env.X ?? default)`，非法字符串不会回退默认值，而是得到 `NaN`。
- `scripts/codegen-benchmark/` 这类非根 workspace 脚本不能假设根包或其它包的 bin 自动进入当前 PATH。
- `package.json` scripts、`config.ts` 这种入口文件很容易通过类型检查，但在真实命令执行时失败。

**✅ 正确做法**：

- 对新增环境变量使用显式 helper，例如 `readPositiveNumberEnv(raw, fallback)`，要求 `Number.isFinite(parsed) && parsed > 0` 才接受。
- 子包脚本优先跑真实入口验证，例如 `pnpm --dir scripts/codegen-benchmark typecheck`，必要时通过 `pnpm --dir ../../apps/server exec tsc ...` 显式使用已有工具链。
- `/review` 和 `/done` 阶段至少跑一次新增脚本或配置相关的定向测试，而不是只依赖全仓 typecheck。

**❌ 错误做法**：

```ts
// 非法 env 会得到 NaN，不会回退
llmRefinementIntentTimeoutMs: Number(process.env.LLM_REFINEMENT_INTENT_TIMEOUT_MS ?? 5_000)
```

```json
{
  "scripts": {
    "typecheck": "tsc --noEmit -p ./tsconfig.json"
  }
}
```

**本次真实发生**：v0.39.4 全局审计行动池收口时，`scripts/codegen-benchmark` 的 `typecheck` 在子包上下文里找不到 `tsc`，需改为显式借用 backend 工具链；`/review` 又发现 `LLM_REFINEMENT_INTENT_TIMEOUT_MS` 非法值会进入 `NaN` 分支，已 AUTO-FIX 为 `readPositiveNumberEnv()` 并补 `config.spec.ts`。教训：**新增配置和脚本必须用真实命令跑一次**，否则"源码合理"不等于"门禁可用"。

---

## G-015: 跨包“单一真源”不能无视构建边界

**症状**：为了让 server 侧 AST 白名单与 runtime 侧 importmap alias 共享真源，直接从 runtime 包导入一个新增数组常量（例如 `RUNTIME_IMPORT_ALIASES`）。源码层看起来类型正确，但 backend 定向测试报 `TypeError: ALLOWED_RUNTIME_IMPORT_PREFIXES is not iterable`，或在未先构建 runtime 包时拿到陈旧 / 不存在的 `dist` 导出。

**原因**：workspace 包之间的 `exports` 往往指向构建产物。server 测试和 typecheck 不一定会先重建 runtime 包；此时“新导出的常量”在源码里存在，但消费方实际解析的是旧 `dist`。这类问题不是 TypeScript 类型能完全覆盖的，而是包边界与构建顺序问题。

**✅ 正确做法**：

- 优先复用消费方已经能稳定解析的既有导出，不为“单一真源”新增跨包运行时导出。
- 如果已有对象常量承载同一事实，可在消费侧通过 `Object.keys(KNOWN_RUNTIME_SUBPATHS)` 派生 alias 列表，避免再加一个容易和 dist 漂移的新数组。
- 给跨包同步关系加集成测试，断言“AST 放行的 alias/subpath 一定能被 importmap 映射覆盖”，而不是只测单侧常量。
- 当确实需要新增 workspace export 时，验证顺序必须包含“先 build 被依赖包，再跑消费方测试”的真实入口。

**❌ 错误做法**：

```ts
// server 侧直接依赖 runtime 新增导出；runtime dist 未重建时会读到旧产物
import { RUNTIME_IMPORT_ALIASES } from '@vibe-game-creator/runtime/preview/runtimeChunks';
const ALLOWED_RUNTIME_IMPORT_PREFIXES = RUNTIME_IMPORT_ALIASES;
```

**本次真实发生**：v0.39.5 契约护栏小包中，初版把 AST 白名单改为导入 runtime 新增的 alias 数组，backend runtime whitelist 测试出现 `ALLOWED_RUNTIME_IMPORT_PREFIXES is not iterable`。最终改为从既有 `KNOWN_RUNTIME_SUBPATHS` 派生 `Object.keys(...)`，并在 `runtimeImportWhitelist.integration.spec.ts` 中覆盖 root alias、subpath 与未知 alias 拒绝路径。教训：**跨包单一真源要同时尊重“事实唯一”和“构建产物可用”两个约束**。

---

## G-016: SSE 软恢复不能替代断点续传重连

**症状**：前端把 SSE 断流后的处理从 `lastEventId` 断点续传重连改成短延迟后触发 `onInterrupted`，测试也从多次 fetch 改成只 fetch 一次。表面上用户仍能看到“正在恢复最新会话状态”，但实时流已经不再续接。

**原因**：软恢复和断点续传解决的是两类问题：

- `lastEventId` 重连用于网络抖动、reader 异常、未收到 `done` 前的流截断，目标是继续消费同一条实时流。
- `onInterrupted` / hydrate 软恢复用于重试耗尽后的降级，目标是让 UI 回到已持久化状态。

把前者替换成后者，会让临时网络抖动直接停止流式体验；如果服务端未把最后几个 chunk 及时落库，用户还可能看到状态倒退或生成卡住。

**✅ 正确做法**：

- `parseSseStream` 继续暴露 `onLastEventId`，`streamChat` 在重连请求体中附带 `{ lastEventId }`。
- 服务端主动 `error` 事件应单独暴露为 `SSE_ERROR_EVENT`，不要进入重连循环，避免错误事件被误判为网络抖动。
- 测试必须同时覆盖：未 `done` 截断会重试、reader 异常会重试、服务端 `error` 不重试、重连请求体包含 `lastEventId`。

**❌ 错误做法**：

```ts
// 只等一小段时间后软恢复，等价于放弃实时流续接
await runLimitedSseRecoveryRetry({ recover: () => notifyInterruption(detail) })
```

**本次真实发生**：v0.39.7 `/review` 阶段发现 `apps/web/src/api/chat.ts` 移除了基线中的 `lastEventId` 记录与 3 次退避重连，只保留 `onInterrupted` 软恢复。最终恢复 `SSE_RECOVERY_RETRY_DELAYS_MS = [1000, 2000, 4000]` 的断点续传路径，同时保留 `SSE_ERROR_EVENT` 语义，并在 `chat.spec.ts` 中断言重连次数与 `lastEventId` 请求体。教训：**SSE 恢复链路必须区分“实时续接”和“状态软恢复”，评审时看到 fetch 次数从 N 次降到 1 次要默认当作回归检查**。

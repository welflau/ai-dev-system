**OpenSpec ≠ Harness Engineering**，两者是"工程范式 vs 落地工具"的关系，不是隶属或等同。

## 一句话区分

- 

  **Harness Engineering（驾驭工程）**：是 OpenAI 在 2026 年 2 月那篇《Harness engineering: leveraging Codex in an agent-first world》里正式化的**AI 工程化范式**，最早由 HashiCorp 创始人 Mitchell Hashimoto 提出雏形。核心是"**人类掌舵，智能体执行**"——设计约束、反馈回路、工具编排、权限边界这套"马具"，把 AI 套住让它稳定产出。

- 

  **OpenSpec**：是 Fission-AI 开源的一个**轻量 CLI 框架**（@fission-ai/openspec），属于 Spec-Driven Development（规范驱动开发）工具，干的事是把变更拆成 proposal / specs / design / tasks 四件套，让人类和 AI 先对齐"做什么"再写代码。

## 两者的关系

常被放在一起聊，是因为 **OpenSpec 是 Harness Engineering 在"规范管理"这块的一个具体落地**，但：

> 💡 OpenSpec 与 Harness Engineering 理念相通但相互独立，**无底座与上层的依赖关系**。OpenSpec 无需依赖 Harness 即可独立运行。

用一个流传较广的类比：

| 层级                | 角色             | 类比                |
| ------------------- | ---------------- | ------------------- |
| Harness Engineering | 管理哲学         | 公司的治理体系      |
| OpenSpec            | 规范层（做什么） | 产品经理 / 施工图纸 |
| Superpowers         | 纪律层（怎么做） | 施工规范手册        |
| hooks / gstack      | 执行与协作层     | 公司制度 / 项目经理 |

所以完整链路一般是：老板提需求 → **OpenSpec** 定规格 → Superpowers 管流程 → Harness 管多 Agent 编排与权限 → 交付。

如果你是在选型——单用 OpenSpec 就能解决"AI 写代码前先对齐需求"的问题；想要多 Agent 协作、权限管控、验证门禁那层，才需要往 Harness 那套去补。


这条链路不是某个工具的内置流程，而是 **OpenSpec（规范）+ Superpowers（纪律）+ Harness（编排/约束）** 三层各自站好自己的位置，接力把"老板一句话"变成"可交付代码"。下面按一趟真实需求走一遍，每站说清**谁主导、输入输出、交接物**。

------

## 🚀 完整链路：5 站，从需求到交付

### Phase 0 · 老板提需求（入口）

老板/PM 一句话进来，比如："给订单列表加 Excel 导出，仅管理员可用。"

此时还是**非结构化自然语言**，三层都还没动。接下来三层的铁律是：**没进 OpenSpec 之前，任何人（包括 Agent）不准动手写代码。**

------

### Phase 1 · OpenSpec 定规格（规范层）

**主导：OpenSpec CLI**｜**时机：开发前**

```
/sdd-propose order-export
# 或 opsx:propose "order export"
```

OpenSpec 会生成 `openspec/changes/order-export/` 目录，里面四件套：

| 文件                         | 内容                                                 |
| ---------------------------- | ---------------------------------------------------- |
| `proposal.md`                | 目标 / 非目标 / 影响范围（"仅管理员"这种边界就写这） |
| `specs/order-export/spec.md` | GIVEN/WHEN/THEN 场景化验收标准                       |
| `design.md`                  | 技术选型（用啥库、API 怎么挂）                       |
| `tasks.md`                   | 拆到可执行粒度的任务卡                               |

> 📦 **输出物**：`openspec/` 目录，后面所有 Agent **只读这一份真相源**，不准各自理解。

这一步解决的是"AI 各做各的、需求理解不一致"。老板那句话里没说的"非目标"（比如"暂不支持 CSV""暂不支持超大分页"），也得在这补齐，否则后面 Superpowers 再严也救不回来。

------

### Phase 2 · Harness 组队 + 分派（编排层）

**主导：Harness（AGENTS.md 定义角色）**｜**时机：Phase 1 确认后**

Harness 这边干三件事：

1. 

   **启动**：加载 `AGENTS.md`，里面写死每个 Agent 的角色、工具权限、文件边界

   ```
   code_writer: [read_file, write_file, run_tests]
   reviewer:    [read_file, comment]        # 只评不改
   deployer:    [run_ci, deploy_staging]     # 不能直发生产
   ```

2. 

   **组队**：Planner Agent 读 `tasks.md`，按 Backend / Frontend / QA / DevOps 分派

3. 

   **调度**：Team Lead Agent 把任务卡丢给对应角色的 Agent，**并行起**

典型六 Agent 流水线（Anthropic/OpenAI 那套推广的）：

> 用户需求 → **Planner** → **Generator** → **Code Reviewer** → **Security Reviewer** → **QA** → 交付

每个 Agent 有独立认知边界，"生成者"和"评判者"分离——让评估者变怀疑比让生成者变自律容易得多。

------

### Phase 3 · Superpowers 管执行（纪律层）

**主导：Superpowers（SKILL.md 强制）**｜**时机：每个 Agent 拿到任务后**

这一层**不归 Harness 管，也不归 OpenSpec 管**——它是绑在单个 Agent 身上的"行为纪律"，通过 SessionStart Hook 注入，Agent 启动时先读 `using-superpowers`，规则是"**1% 可能适用就必须用，不可协商**"。

Backend Agent 拿到 task 后走七步：

1. 

   **Brainstorm**（苏格拉底式反问，澄清边界——虽然 OpenSpec 已写过，但 Superpowers 还是会再对一遍）

2. 

   **Git worktree**（隔离分支，主分支不动）

3. 

   **Write plan**（拆成 2-5 分钟微任务，每个带验证步骤）

4. 

   **Subagent 驱动**（每任务起一个 fresh subagent，避免长上下文漂移）

5. 

   **TDD 红-绿-重构**（没失败测试不准写实现，写了也删）

6. 

   **Code review**（`requesting-code-review` skill，Critical 级阻塞）

7. 

   **Finish branch**（merge / PR / keep / discard）

> 💡 这一层解决的是"Agent 走野路子、不写测试、不做审查"。OpenSpec 写了"必须写测试"没用，得靠 Superpowers 在**执行侧**把它焊死。

------

### Phase 4 · Harness 校验 + 门禁（回管控层）

**主导：Harness 钩子 + 权限**｜**时机：每个 task 完成 / PR 前**

Agent 自己说"我做完了"不算数，Harness 跑几道硬约束：

- 

  **PreToolUse / PostToolUse Hooks**：跑测试、Lint、安全扫描

- 

  **权限校验**：Agent 有没有越权碰不该碰的目录

- 

  **反馈回路**：测试失败自动回灌给开发 Agent，修完再验

- 

  **OPA 策略**（企业级）：模型白名单、最大 turn 数、connector 限制

不通过？**不让合并**，打回 Phase 3 重走。

------

### Phase 5 · OpenSpec Verify 验收（回规范层）

**主导：OpenSpec verify**｜**时机：所有 task 跑完**

```
/sdd-verify order-export
# 或 opsx:verify
```

逐条对账 `specs/*.md` 里的 GIVEN/WHEN/THEN：

- 

  ✅ 过了 → `/sdd-ship` → `opsx:archive` 归档到 `openspec/changes/archive/`

- 

  ❌ 没过 → 打回 Phase 3，标注哪条 spec 没满足

> 🎯 这是一个**闭环**：Phase 1 出的 spec，Phase 5 拿来对账。规范层"不变"，中间怎么折腾都得回到这份文档上。

------

## 三层配合的三个原则

把上面 5 站压成一句话就是：

> **规范不变（OpenSpec）、纪律不变（Superpowers）、团队可弹性伸缩（Harness）。**

- 

  项目小 → Harness 里 Planner+Generator 合并成一个 Agent 也能跑

- 

  项目大 → Backend/Frontend/QA/Security 全拉开并行

- 

  但 `openspec/` 那几份文档和 Superpowers 的 SKILL.md 铁律，**一动不用动**

缺哪一层的代价也很清楚：

| 缺             | 症状                                    |
| -------------- | --------------------------------------- |
| 缺 OpenSpec    | Agent 各做各的，返工率高                |
| 缺 Superpowers | 不写测试不审查，代码质量失控            |
| 缺 Harness     | 多 Agent 协作混乱，权限冲突，并行变串行 |

------

如果想看更"能抄"的版本， 那个 `/sdd-propose → /sdd-design → /sdd-plan → /sdd-execute → /sdd-verify → /sdd-ship` 的命令族是目前把三层串成 slash-command 的最完整实现，可以直接对照着自己仓库先跑一轮试试，比纯看概念来得快。
# ConfigPack 内容库大规模扩充 — 多来源 agents/skills/commands 导入

**日期**：2026-06-18 ~ 2026-06-19

---

## 背景

ConfigPack 系统搭建后，需要从现有项目中筛选高质量的 agents、skills、commands 充实内置 Pack 库，让用户安装后即可获得完整的 AI 工作配置。

本轮从4个来源库批量导入，并完善了 scripts/ 目录机制。

---

## 来源库

| 来源 | 路径 | 主要内容 |
|------|------|--------|
| agency-agents | `G:/Github/AI/agency-agents/game-development/` | 游戏开发角色 Agent |
| vibe-game-creator | `G:/B_OA/AI/opengame/vibe-coding-game/vibe-game-creator/.agents/` | 工作流规则、通用工程技能 |
| MagicAI | `F:/A_Works/MagicAI/src/agents/claude_agent/` | Godot 专属 agents + skills |
| Claude-Code-Game-Studios | `F:/A_Works/Claude-Code-Game-Studios/.claude/` | 完整游戏工作室角色 + 技能体系 |
| everything-claude-code | `F:/A_Works/everything-claude-code/` | UE 命令套件、工程技能、内容创作技能 |

---

## 新增 / 扩充的 Pack

### 新建 Pack（5个）

| Pack | 内容 |
|------|------|
| `game-dev` | 32个通用游戏开发 Agent（创意/技术总监、程序/设计/QA/运营等全角色）+ 35个工作流 skill + 11条代码规范 |
| `godot-dev` | 8个 Claude subagent（game-dev/asset-creator/design-doc/qa + specialist/gdscript/gdextension/shader）+ 6个 Codebuddy 团队 agent + 25个专项 skill |
| `unity-dev` | 5个 Unity 专属 Agent（specialist/DOTS/shader/addressables/UI） |
| `content-creation` | 8个内容创作 skill（article-writing/brand-voice/content-engine/crosspost/slides/investor/research/strategic） |
| `ai-workflow` | 5个 AI 工作流 skill（deep-research/agent-debug/agent-sort/dmux/mle-workflow） |

### 大幅扩充的 Pack

| Pack | 扩充内容 |
|------|--------|
| `ue5-dev` | +5个 Agent（blueprint/GAS/replication/UMG/specialist）+ 16个 commands（ue-init/scaffold/gdd/auto/run/asset/bp-gen/level/playtest/review/ci/evolve/extend/antipatterns + build/playtest）+ 8个 scripts |
| `code-quality` | +6个 skill（tdd-workflow/security-review/verification-loop/coding-standards/e2e-testing/eval-harness）+ 2个 rule |
| `web-dev` | +7个 skill（api-design/backend-patterns/frontend-patterns/nextjs-turbopack/bun-runtime/documentation-lookup/mcp-server-patterns） |
| `vibe-workflow` | +2个 command（retro/verify）+ 3个 rule（workflow-guardrails/sprint-lifecycle/workflow-parallel-dev） |
| `git-workflow` | +1个 rule（git-conventions） |
| `typescript-quality` | +1个 rule（quality-typescript-coding） |

---

## Scripts 目录机制完善

**问题**：`build.md` / `playtest.md` 中调用 `python scripts/ue_python.py`，但 pack installer 把 `shared/scripts/` 装到 `.claude/scripts/`，路径不对。

**修复**：
1. 把 `ue5-dev/claude/commands/`（14个）统一移入 `shared/commands/`，两端都能分发
2. 新增 `ue5-dev/shared/scripts/`，收录8个 UE 工具脚本
3. `build.md`/`playtest.md` 路径修正为 `.claude/scripts/ue_python.py`

**安装后结构**：
```
项目/.claude/
  scripts/        ← shared/scripts/ copy 过来
    ue_python.py
    ue_build.js
    ue_ci.py
    ...
  commands/       ← shared/commands/ copy 过来
    build.md      → python .claude/scripts/ue_python.py "..."  ✓
```

---

## Scripts 依赖审计

对全部 Pack 的 skills/agents/commands 做脚本引用完整性检查：

- **结论：零缺失** — 所有被引用的脚本均存在于 pack 内或通过配置路径可访问
- 其他 pack（godot-dev 等）的 .md 里有 bash 代码块但均为教学示范，不是运行时工具依赖，无需补充 scripts/
- `ue-init.md` 中引用的 `{unrealecc_root}/scripts/` 属外部 UnrealECC 项目，通过 `.claude/ue-config.json` 运行时解析，风险可控

---

## 最终 Pack 库统计

| Pack | 主要内容类型 | 文件数 |
|------|-----------|------|
| `game-dev` | 32 agents + 35 skills + 11 rules | 80 |
| `godot-dev` | 14 agents + 25 skills | 55 |
| `web-dev` | 1 rule + 8 skills + 1 command | 37 |
| `ue5-dev` | 9 agents + 16 commands + 8 scripts + 1 rule | 35 |
| `code-quality` | 2 rules + 8 skills | 16 |
| `vibe-workflow` | 8 commands + 3 rules | 11 |
| `content-creation` | 8 skills | 10 |
| `unity-dev` | 5 agents | 5 |
| `ai-workflow` | 5 skills | 5 |
| `git-workflow` | 2 commands + 1 rule | 3 |
| `typescript-quality` | 1 rule + 1 skill | 2 |

---

## 跳过的内容

| 来源 | 跳过原因 |
|------|--------|
| godot/unity/roblox/blender agents（agency-agents） | 无对应 pack |
| monorepo_guide.md、test-performance-guardrails.md（vibe-game-creator） | 项目特定 |
| generate-ui-assets（MagicAI） | 西部赌场主题 Python 脚本，项目特定 |
| exa-search、fal-ai-media、video-editing、x-api（everything-claude-code） | 依赖特定外部 MCP 服务 |
| docs/、hooks/、settings.json（Claude-Code-Game-Studios） | 项目特定配置脚本 |

---

## 关键文件

| 文件 | 变更 |
|------|------|
| `backend/config_packs/*/pack.json` | 新建或更新 contains/version/description |
| `backend/pack_installer.py` | 无变更（scripts/ 路径逻辑已支持） |
| `backend/config_packs/ue5-dev/shared/scripts/` | 新增 8个 UE 脚本 |
| `backend/config_packs/ue5-dev/shared/commands/build.md` | 修正脚本路径 |

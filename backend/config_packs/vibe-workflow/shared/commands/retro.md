---
name: retro
description: "研发复盘（git 数据采集 + 指标分析 + 趋势追踪）"
argument-hint: "[7d | 14d | 30d | 24h | compare | compare 14d]"
---

# 执行指令 (Instructions)

生成全面的研发复盘报告，分析 commit 历史、工作模式和代码质量指标。团队感知：识别当前用户，分析每个贡献者的表扬和成长点。

## 参数

- `/retro` — 默认最近 7 天
- `/retro 24h` — 最近 24 小时
- `/retro 14d` — 最近 14 天
- `/retro 30d` — 最近 30 天
- `/retro compare` — 对比当前窗口与上一个同长度窗口
- `/retro compare 14d` — 指定窗口的对比模式

## 执行步骤

解析参数确定时间窗口。默认 7 天。所有时间使用用户**本地时区**。

**午夜对齐**：对于天（`d`）单位，计算绝对起始日期（本地午夜）。例如今天是 2026-03-19，窗口 7 天：起始日期 2026-03-12。使用 `--since="2026-03-12"` 进行 git log 查询。小时（`h`）单位使用 `--since="N hours ago"`。

**参数校验**：如果参数不匹配 `数字+d/h/w`、`compare`、或 `compare 数字+d/h/w`，显示用法说明并停止。

---

### Step 1: 采集原始数据

先 fetch、识别远端默认主干基线并识别当前用户：
```bash
git fetch origin --quiet
BASE_REF=$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD || true)
[ -z "$BASE_REF" ] && DEFAULT_BRANCH=$(git remote show origin | rg 'HEAD branch' | sed 's/.*: //')
[ -n "$DEFAULT_BRANCH" ] && BASE_REF="origin/$DEFAULT_BRANCH"
[ -z "$BASE_REF" ] && BASE_REF=$(git for-each-ref --format='%(refname:short)' refs/remotes/origin | grep -v '^origin/HEAD$' | head -n1)
git config user.name
git config user.email
```

`git config user.name` 返回的名字就是 **"你"**——正在阅读复盘的人。其他作者是队友。

**并行运行**以下所有 git 命令：

```bash
# 1. 窗口内所有 commits（时间戳、摘要、hash、作者、文件变更、增删行数）
git log "$BASE_REF" --since="<window>" --format="%H|%aN|%ae|%ai|%s" --shortstat

# 2. 每 commit 的测试 vs 总 LOC（按作者）
git log "$BASE_REF" --since="<window>" --format="COMMIT:%H|%aN" --numstat

# 3. Commit 时间戳（用于 session 检测和小时分布）
git log "$BASE_REF" --since="<window>" --format="%at|%aN|%ai|%s" | sort -n

# 4. 最常变更文件（热点分析）
git log "$BASE_REF" --since="<window>" --format="" --name-only | grep -v '^$' | sort | uniq -c | sort -rn

# 5. 每作者文件热点
git log "$BASE_REF" --since="<window>" --format="AUTHOR:%aN" --name-only

# 6. 每作者 commit 数
git shortlog "$BASE_REF" --since="<window>" -sn --no-merges

# 7. 测试文件计数
find . -name '*.test.*' -o -name '*.spec.*' 2>/dev/null | grep -v node_modules | wc -l

# 8. 窗口内测试文件变更
git log "$BASE_REF" --since="<window>" --format="" --name-only | grep -E '\.(test|spec)\.' | sort -u | wc -l
```

---

### Step 2: 计算指标

计算并呈现指标汇总表：

| 指标 | 值 |
|------|-----|
| Commits to master | N |
| 贡献者 | N |
| 总增加行 | N |
| 总删除行 | N |
| 净 LOC | N |
| 测试 LOC（增加） | N |
| 测试 LOC 占比 | N% |
| 活跃天数 | N |
| 检测到的 session 数 | N |
| 平均 LOC/session-hour | N |

紧接显示**贡献者排行榜**：

```
贡献者           Commits    +/-          主要领域
你 (haiyang)          32   +2400/-300   apps/web/
alice                 12   +800/-150    apps/server/
bob                    3   +120/-40     packages/
```

按 commits 降序排列。当前用户始终排首位，标记为"你 (name)"。

---

### Step 3: Commit 时间分布

显示本地时间的小时直方图：

```
小时  Commits  ████████████████
 00:    4      ████
 07:    5      █████
 ...
```

识别并标注：
- 高峰时段
- 空白时段
- 是否双峰（早/晚）或连续型
- 深夜编码集群（22 点后）

---

### Step 4: 工作 Session 检测

使用 **45 分钟间隔**阈值检测 session。对每个 session 报告：
- 开始/结束时间
- Commit 数
- 持续时间（分钟）

分类 session：
- **深度 session**（50+ 分钟）
- **中等 session**（20-50 分钟）
- **微 session**（<20 分钟，通常是单次 commit）

计算：
- 总活跃编码时间（session 时长之和）
- 平均 session 长度
- 每活跃小时 LOC

---

### Step 5: Commit 类型拆分

按 conventional commit 前缀分类（feat/fix/refactor/test/chore/docs），显示百分比条形图：

```
feat:     20  (40%)  ████████████████████
fix:      27  (54%)  ███████████████████████████
refactor:  2  ( 4%)  ██
```

如果 fix 占比超过 50% — 标记为需关注：可能表示"快速发布、快速修复"模式。

---

### Step 6: 热点分析

**可选（与指标无关）**：若需在当前环境快速确认前端单测健康，**包脚本优先**使用 `pnpm --filter @vibe-game-creator/web test`；Vitest 参数置于 `--` 后透传。全仓多包测试用根目录 `pnpm test`。

显示变更最频繁的 Top 10 文件。标注：
- 变更 5+ 次的文件（代码搅动热点）
- 热点列表中测试文件 vs 生产文件的比例
- CHANGELOG 频率（版本纪律指标）

---

### Step 7: PR 大小分布

从 commit diff 估算 PR 大小并分桶：
- **Small**（<100 LOC）
- **Medium**（100-500 LOC）
- **Large**（500-1500 LOC）
- **XL**（1500+ LOC）— 标记并附文件数

---

### Step 8: Focus Score + 本周之星

**Focus score**：计算 commits 触及最多的单个顶层目录的百分比。分数越高 = 越专注。分数越低 = 上下文切换越多。

**本周之星**：自动识别窗口内 LOC 最高的变更，高亮展示：
- 标题和涉及目录
- LOC 变化量
- 为什么重要（从 commit messages 和文件推断）

---

### Step 9: 团队成员分析

对每个贡献者（包括当前用户）计算：

1. **Commits 和 LOC** — 总 commits、增删行数、净 LOC
2. **专注领域** — 最常触及的目录/文件（Top 3）
3. **Commit 类型分布** — 个人 feat/fix/refactor/test 拆分
4. **Session 模式** — 编码高峰时段、session 数
5. **测试纪律** — 个人测试 LOC 占比
6. **最大贡献** — 窗口内最高影响力的 commit

**对当前用户（"你"）**：最深入的分析。包含 session 分析、时间模式、focus score。用第一人称："你的高峰时段…"、"你的最大贡献…"

**对每个队友**：2-3 句概述 + 表扬（1-2 个具体点） + 成长建议（1 个具体点）。

- **表扬**锚定在实际 commits。不说"做得好"——说具体好在哪。
- **成长建议**框架为投资建议，不是批评。锚定在实际数据。

**如果只有一个贡献者（单人仓库）**：跳过团队拆分，做个人深度复盘。

**AI 协作说明**：如果发现 `Co-Authored-By` trailer 中有 AI 作者，记录 AI 辅助 commit 百分比作为指标。

---

### Step 10: 周环比趋势（窗口 >= 14d 时）

如果时间窗口 >= 14 天，按周拆分并显示趋势：
- 每周 Commits（总计和按人）
- 每周 LOC
- 每周测试占比
- 每周 fix 占比
- 每周 Session 数

---

### Step 11: 连续发布天数 (Streak Tracking)

统计从今天往回数的连续有 commit 的天数：

```bash
# 团队连续天数
git log "$BASE_REF" --format="%ad" --date=format:"%Y-%m-%d" | sort -u

# 个人连续天数
git log "$BASE_REF" --author="<user_name>" --format="%ad" --date=format:"%Y-%m-%d" | sort -u
```

从今天往回数——有多少连续天至少有一个 commit？显示：
- "团队发布连续天数: N 天"
- "你的发布连续天数: N 天"

---

### Step 12: 加载历史 & 对比

保存新快照前，检查历史复盘数据：

```bash
ls -t .agents/memory/retros/*.json 2>/dev/null
```

**如果有历史数据**：读取最近一个。计算关键指标的增量，输出 **趋势对比**：
```
                    上次        现在         变化
测试占比:           22%    →    41%         ↑19pp
Sessions:           10     →    14          ↑4
LOC/hour:           200    →    350         ↑75%
Fix 占比:           54%    →    30%         ↓24pp (改善中)
```

**如果无历史数据**：跳过对比，附注"首次复盘——下次运行时可以看到趋势。"

---

### Step 13: 保存复盘快照

计算完所有指标后，保存 JSON 快照到 `.agents/memory/retros/`：

```bash
mkdir -p .agents/memory/retros
```

文件名：`.agents/memory/retros/{日期}-{序号}.json`

JSON schema：
```json
{
  "date": "2026-03-19",
  "window": "7d",
  "metrics": {
    "commits": 47,
    "contributors": 3,
    "insertions": 3200,
    "deletions": 800,
    "net_loc": 2400,
    "test_loc": 1300,
    "test_ratio": 0.41,
    "active_days": 6,
    "sessions": 14,
    "deep_sessions": 5,
    "avg_session_minutes": 42,
    "loc_per_session_hour": 350,
    "feat_pct": 0.40,
    "fix_pct": 0.30,
    "peak_hour": 22,
    "ai_assisted_commits": 32
  },
  "authors": {
    "haiyang": { "commits": 32, "insertions": 2400, "deletions": 300, "test_ratio": 0.41, "top_area": "apps/web/" }
  },
  "streak_days": 47,
  "tweetable": "Week of Mar 12: 47 commits, 3.2k LOC, 38% tests, peak: 10pm | Streak: 47d"
}
```

---

### Step 14: 撰写报告

按以下结构输出：

---

**一句话摘要**（第一行）：
```
Week of Mar 12: 47 commits (3人), 3.2k LOC, 38% tests | Streak: 47d
```

## 研发复盘: [日期范围]

### 指标总览
（来自 Step 2）

### 趋势对比
（来自 Step 12，首次跳过）

### 时间与 Session 模式
（来自 Steps 3-4）
解读团队的时间模式意味着什么。

### 交付速度
（来自 Steps 5-7）
覆盖 commit 类型、PR 大小纪律、fix 链检测。

### 代码质量信号
- 测试 LOC 占比趋势
- 热点分析
- XL PR 是否应拆分

### 专注度 & 亮点
（来自 Step 8）

### 你的本周
（来自 Step 9，仅当前用户）
个人深度分析：commit 数、LOC、测试占比、session 模式、focus score、最大贡献、做得好的 2-3 点、提升空间 1-2 点。

### 团队拆分
（来自 Step 9，每个队友——单人仓库则跳过）

### Top 3 团队成果
窗口内最高影响力的 3 件事。

### 3 件需改善
具体、可操作、锚定在实际 commits。

### 3 个下周习惯
小的、实用的、可在 5 分钟内采纳的。

### 周环比趋势
（如适用，来自 Step 10）

---

## Compare 模式

当运行 `/retro compare`（或 `/retro compare 14d`）时：

1. 计算当前窗口的指标（午夜对齐）
2. 计算前一个同长度窗口的指标（使用 `--since` 和 `--until` 避免重叠）
3. 显示并排对比表（含增量和箭头）
4. 撰写简短叙事，突出最大的改善和退步
5. 只保存当前窗口的快照到 `.agents/memory/retros/`

---

## 语调

- 鼓励但坦诚，不拍马屁
- 具体而非抽象——始终锚定在实际 commits/代码
- 跳过泛泛表扬（"做得好！"）——说具体好在哪、为什么好
- 改善建议框架为"升级"，不是批评
- 表扬应该像 1:1 时真正会说的话——具体、真诚
- 成长建议像投资建议——"这值得投入因为…"
- 不要消极对比团队成员。每个人的部分独立评价
- 总输出控制在 3000-4500 字
- 数据用 markdown 表格和代码块，分析用散文
- 输出到对话中，唯一写入文件的是 `.agents/memory/retros/` JSON 快照

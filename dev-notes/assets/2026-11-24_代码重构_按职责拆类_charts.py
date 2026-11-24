"""「代码重构_按职责拆类」这篇笔记的图。数字都抄自笔记正文的表格，改表格时一起改这里。

用法：python 本文件
"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["font.size"] = 11

OUT = os.path.dirname(os.path.abspath(__file__))
PRE = "2026-11-24_代码重构_按职责拆类_"
BLUE, GREY, GREEN, RED, AMBER = "#2f6fb5", "#a9b4c2", "#3a9a5b", "#c8503c", "#d99a1e"

# 组名, 搬走的方法数, 新文件行数, 搬完后 orchestrator.py 行数, 改坏处数, 对照组数, 全量 pytest 通过数
GROUPS = [
    ("rewind", 7, 378, 4224, 132, 6, 1127),
    ("sop_rules", 13, 604, 3765, 159, 12, 1199),
    ("change_flows", 6, 562, 3318, 146, 6, 1229),
    ("reporting", 3, 437, 2924, 42, 3, 1244),
    ("polling", 13, 350, 2680, 139, 13, 1309),
    ("bug_flow", 7, 305, 2449, 104, 7, 1344),
    ("agent_state", 6, 150, 2354, 67, 6, 1374),
    ("failure_counters", 5, 138, 2259, 47, 4, 1395),
    ("ticket_log", 7, 370, 2039, 266, 7, 1431),
    ("context_builder", 5, 271, 1818, 54, 5, 1456),
]
START, TARGET = 4493, 1500
# orchestrator.py 里还有实际函数体的 13 个方法：名字, 行数, 留下的原因
REST = [
    ("_build_context", 176, "L3"), ("_handle_git_files", 167, "L3"), ("_handle_agent_result", 166, "驱动"),
    ("_diagnose_blocked_ticket", 153, "L3"), ("_poll_once", 142, "L3"), ("process_ticket", 77, "驱动"),
    ("__init__", 51, "驱动"), ("_finalize_openspec_after_done", 46, "L3"), ("handle_requirement", 45, "驱动"),
    ("_maybe_openspec_verify", 34, "L3"), ("_check_subtasks_complete", 26, "L3"),
    ("_execute_assigned_agent", 26, "驱动"), ("_try_uproject_heal", 19, "驱动"),
]


def save(fig, name):
    p = os.path.join(OUT, PRE + name + ".png")
    fig.savefig(p, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(p, os.path.getsize(p))


def clean(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)


# ---- 01 orchestrator.py 行数 ----
fig, ax = plt.subplots(figsize=(11.5, 4.8))
names = ["开始"] + [g[0] for g in GROUPS]
vals = [START] + [g[3] for g in GROUPS]
ax.bar(names, vals, color=[GREY] + [BLUE] * len(GROUPS), width=0.62)
for i, v in enumerate(vals):
    ax.text(i, v + 60, f"{v:,}", ha="center", va="bottom", fontsize=10)
    if i:
        ax.text(i, 700, f"−{vals[i - 1] - v}", ha="center", va="center", fontsize=9.5, color="white")
ax.axhline(TARGET, color=RED, lw=1.3, ls="--")
ax.set_xlim(-0.6, len(vals) + 1.3)
ax.text(len(vals) - 0.5, TARGET + 45, f"验收线 {TARGET:,} 行", ha="left", va="bottom", color=RED, fontsize=10)
ax.set_ylabel("orchestrator.py 行数"); ax.set_ylim(0, 5000)
plt.setp(ax.get_xticklabels(), rotation=28, ha="right")
clean(ax)
ax.set_title("每搬一组之后 orchestrator.py 的行数（4,493 → 1,818，离验收线还差 318 行）", fontsize=13, fontweight="bold")
save(fig, "01_orchestrator行数")

# ---- 02 新模块大小和方法数 ----
fig, ax = plt.subplots(figsize=(10.5, 4.6))
order = sorted(GROUPS, key=lambda g: g[2])
ax.barh([g[0] for g in order], [g[2] for g in order], color=BLUE, height=0.62)
for i, g in enumerate(order):
    ax.text(g[2] + 8, i, f"{g[2]} 行，{g[1]} 个方法", va="center", fontsize=10)
ax.set_xlim(0, 760); ax.set_xlabel("新文件行数（含模块说明）")
clean(ax)
ax.set_title("orchestration/ 下新增的 10 个模块（合计 3,565 行，72 个方法）", fontsize=13, fontweight="bold")
save(fig, "02_新模块大小")

# ---- 03 改坏检查和全量测试 ----
fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 4.6), gridspec_kw={"width_ratios": [1.15, 1]})
xs = [g[0] for g in GROUPS]
a1.bar(xs, [g[4] for g in GROUPS], color=GREEN, width=0.62)
for i, g in enumerate(GROUPS):
    a1.text(i, g[4] + 4, f"{g[4]} / {g[5]}", ha="center", va="bottom", fontsize=9.5)
a1.set_ylabel("改坏处数 / 对照组数"); a1.set_ylim(0, 300)
plt.setp(a1.get_xticklabels(), rotation=30, ha="right"); clean(a1)
a1.set_title("转发层改坏检查：1,156 处，存活 0，对照组 69 个全绿", fontsize=12, fontweight="bold")
ys = [1071] + [g[6] for g in GROUPS]
a2.plot(["开始"] + xs, ys, marker="o", color=BLUE, lw=1.8)
for i, v in enumerate(ys):
    a2.text(i - 0.12, v + 10, f"{v:,}", ha="right", va="bottom", fontsize=9)
a2.set_ylim(1000, 1520); a2.set_xlim(-1.0, len(ys) - 0.5); a2.set_ylabel("全量 pytest 通过数（失败 0）")
plt.setp(a2.get_xticklabels(), rotation=30, ha="right"); clean(a2)
a2.set_title("每组提交前的全量测试：1,071 → 1,456", fontsize=12, fontweight="bold")
fig.tight_layout()
save(fig, "03_改坏检查与全量测试")

# ---- 04 orchestrator.py 里还剩什么 ----
fig, ax = plt.subplots(figsize=(10.8, 5.2))
rest = REST[::-1]
ax.barh([r[0] for r in rest], [r[1] for r in rest], color=[AMBER if r[2] == "L3" else BLUE for r in rest], height=0.62)
for i, r in enumerate(rest):
    if 130 <= r[1] <= 150:
        ax.text(r[1] - 2, i, f"{r[1]} 行", va="center", ha="right", fontsize=10, color="white")
    else:
        ax.text(r[1] + 2, i, f"{r[1]} 行", va="center", fontsize=10)
ax.axvline(150, color=RED, lw=1.3, ls="--")
ax.set_ylim(-0.6, len(rest) + 0.3)
ax.text(148.5, len(rest) - 0.55, "验收线 150 行", color=RED, fontsize=10, va="bottom", ha="right")
ax.set_xlim(0, 205); ax.set_xlabel("函数行数")
clean(ax)
from matplotlib.patches import Patch
ax.legend(handles=[Patch(color=AMBER, label="函数里导入 L3（agents / actions），搬走会新增分层违规"),
                   Patch(color=BLUE, label="流程入口和驱动，本步不搬")], loc="upper center", bbox_to_anchor=(0.45, -0.13), frameon=False, fontsize=10)
ax.set_title("orchestrator.py 里还有实际函数体的 13 个方法（另外 69 个方法只做转发）", fontsize=13, fontweight="bold")
save(fig, "04_剩余方法")
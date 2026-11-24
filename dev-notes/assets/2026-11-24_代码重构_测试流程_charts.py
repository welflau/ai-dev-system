"""生成 dev-notes/2026-11-24_07_代码重构_测试流程.md 的五张配图。

用法：python dev-notes/assets/2026-11-24_代码重构_测试流程_charts.py
依赖 matplotlib 和系统里的中文字体（Microsoft YaHei 或 SimHei）。图里的数字取自同系列 03 到 06 四篇笔记
和 2026-11-24 的一次本机复跑，是写死的，不会随代码变化自动更新。
"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["font.size"] = 11

OUT = os.path.dirname(os.path.abspath(__file__))
PRE = "2026-11-24_代码重构_测试流程_"
BLUE, GREY, GREEN, RED, AMBER = "#2f6fb5", "#a9b4c2", "#3a9a5b", "#c8503c", "#d99a1e"

def save(fig, name):
    p = os.path.join(OUT, PRE + name + ".png")
    fig.savefig(p, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(p, os.path.getsize(p))

def clean(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)

# ---- 01 触发方式 ----
fig, ax = plt.subplots(figsize=(12.6, 5.6))
ax.set_xlim(0, 12.6); ax.set_ylim(0, 5.6); ax.axis("off")
rows = [
    ("改代码、保存文件", "没有任何检查", "仓库里没有文件监听式的测试", RED, "不触发"),
    ("git commit", "pre-commit：分层守卫\ncheck_layers.py", "配置已入库；本机没装 pre-commit，\n.git/hooks 里只有 .sample", AMBER, "本机不生效"),
    ("push / PR 到\nmain、develop", "CI 三个 job：全量 pytest、\nflake8、分层守卫", "pytest 这一步还没提交；本批改动\n没推送，CI 没在它上面跑过", AMBER, "尚未跑过"),
    ("每轮重构时手动执行", "特征测试、覆盖率、改坏检查、\n搬移核对、全量 pytest、守卫、flake8", "四轮都跑了，结果记在\n各篇 dev-note 里", GREEN, "实际在用"),
]
heads = ["什么时候", "会跑什么", "现状", "结论"]
xs = [0.1, 2.85, 7.05, 11.0]; ws = [2.3, 3.75, 3.5, 1.5]
for x, w, h in zip(xs, ws, heads):
    ax.text(x + w / 2, 5.3, h, ha="center", va="center", fontsize=12, fontweight="bold", color="#333")
for i, (a, b, c, col, tag) in enumerate(rows):
    y = 4.0 - i * 1.22
    for x, w, txt, fc in zip(xs[:3], ws[:3], (a, b, c), ("#eef3f9", "#f6f7f9", "#f6f7f9")):
        ax.add_patch(FancyBboxPatch((x, y), w, 0.98, boxstyle="round,pad=0.02,rounding_size=0.08", fc=fc, ec="#c9d2dc", lw=1))
        ax.text(x + w / 2, y + 0.49, txt, ha="center", va="center", fontsize=10.5, color="#222", linespacing=1.5)
    ax.add_patch(FancyBboxPatch((xs[3], y + 0.19), ws[3], 0.6, boxstyle="round,pad=0.02,rounding_size=0.2", fc=col, ec=col))
    ax.text(xs[3] + ws[3] / 2, y + 0.49, tag, ha="center", va="center", fontsize=11, color="white", fontweight="bold")
    for k in range(2):
        x0 = xs[k] + ws[k] + 0.06; x1 = xs[k + 1] - 0.06
        ax.annotate("", xy=(x1, y + 0.49), xytext=(x0, y + 0.49), arrowprops=dict(arrowstyle="->", color="#8894a3", lw=1.2))
ax.set_title("修改代码时，哪些检查会自己跑", fontsize=14, fontweight="bold", pad=6)
save(fig, "01_触发方式")

# ---- 02 每步耗时 ----
steps = [("分层守卫 check_layers.py", 2.4), ("flake8（CI 那组规则）", 7.8), ("相关测试文件（65 条）", 12.9),
         ("相关测试文件，带分支覆盖率", 15.8), ("全量 pytest（1,071 条）", 223), ("改坏检查（129 处）", 1205)]
fig, ax = plt.subplots(figsize=(10, 4.2))
names = [s[0] for s in steps][::-1]; vals = [s[1] for s in steps][::-1]
cols = [RED if v > 600 else AMBER if v > 60 else BLUE for v in vals]
ax.barh(names, vals, color=cols, height=0.62)
ax.set_xscale("log"); ax.set_xlim(1, 6000)
for i, v in enumerate(vals):
    lab = f"{v:g} 秒" if v < 60 else f"{v:g} 秒（约 {v/60:.1f} 分钟）"
    ax.text(v * 1.12, i, lab, va="center", fontsize=10.5)
ax.set_xlabel("耗时（秒，对数刻度）"); clean(ax)
ax.set_title("每一步检查的耗时（本机实测，2026-11-24）", fontsize=13, fontweight="bold")
save(fig, "02_每步耗时")

# ---- 03 用例数与行数 ----
rounds = ["起点\n7b9e7f0", "03\n结果处理器", "04\nprocess_ticket", "05\nskill 处理器", "06\nhandle_\nrequirement"]
cases = [868, 925, 998, 1008, 1071]; lines = [6694, 5841, 5236, 4907, 4493]
fig, (a1, a2) = plt.subplots(1, 2, figsize=(13.5, 4.6))
a1.bar(rounds, cases, color=BLUE, width=0.6); a1.set_ylim(800, 1110)
for i, v in enumerate(cases):
    extra = "" if i == 0 else f"\n+{v - cases[i-1]}"
    a1.text(i, v + 5, f"{v:,}{extra}", ha="center", va="bottom", fontsize=10.5)
a1.set_title("全量 pytest 通过的用例数", fontsize=12.5, fontweight="bold"); a1.set_ylabel("条（纵轴从 800 起）"); clean(a1)
a2.plot(range(5), lines, marker="o", color=RED, lw=2.2)
a2.set_xticks(range(5)); a2.set_xticklabels(rounds); a2.set_ylim(0, 7400)
for i, v in enumerate(lines):
    a2.text(i, v + 230, f"{v:,}", ha="center", fontsize=10.5)
a2.set_title("orchestrator.py 行数", fontsize=12.5, fontweight="bold"); a2.set_ylabel("行"); clean(a2)
for a in (a1, a2):
    a.tick_params(axis="x", labelsize=9.5)
fig.tight_layout(w_pad=3)
save(fig, "03_用例数与行数")

# ---- 04 函数拆分前后 ----
fns = ["_handle_agent_result", "process_ticket", "handle_requirement"]
lb, la = [1026, 682, 456], [171, 77, 45]; cb, ca = [153, 113, 65], [22, 19, 4]
fig, (a1, a2) = plt.subplots(1, 2, figsize=(12.5, 4.2))
for ax, b, a, ttl, unit in ((a1, lb, la, "函数行数", "行"), (a2, cb, ca, "圈复杂度", "")):
    x = range(3)
    ax.bar([i - 0.2 for i in x], b, 0.38, color=GREY, label="拆分前")
    ax.bar([i + 0.2 for i in x], a, 0.38, color=GREEN, label="拆分后")
    for i in x:
        ax.text(i - 0.2, b[i], f"{b[i]:,}", ha="center", va="bottom", fontsize=10.5)
        ax.text(i + 0.2, a[i], f"{a[i]:,}", ha="center", va="bottom", fontsize=10.5)
    ax.set_xticks(list(x)); ax.set_xticklabels(fns, fontsize=10)
    ax.set_title(ttl, fontsize=12.5, fontweight="bold"); ax.set_ylabel(unit); ax.legend(frameon=False); clean(ax)
    ax.set_ylim(0, max(b) * 1.14)
fig.tight_layout(w_pad=3)
save(fig, "04_函数拆分前后")

# ---- 05 覆盖率与改坏检查 ----
fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 4.6), gridspec_kw=dict(width_ratios=[1, 1.05]))
fn4 = ["_handle_agent_result", "process_ticket", "_handle_skill_\nagent_result", "handle_requirement"]
c0, c1 = [6, 0, 92.9, 1], [92.2, 94.1, 100, 100]
x = range(4)
a1.bar([i - 0.2 for i in x], c0, 0.38, color=GREY, label="补测试前")
a1.bar([i + 0.2 for i in x], c1, 0.38, color=BLUE, label="补测试后")
for i in x:
    a1.text(i - 0.2, c0[i] + 1.5, f"{c0[i]:g}%", ha="center", fontsize=10)
    a1.text(i + 0.2, c1[i] + 1.5, f"{c1[i]:g}%", ha="center", fontsize=10)
a1.set_xticks(list(x)); a1.set_xticklabels(fn4, fontsize=9.3); a1.set_ylim(0, 118)
a1.set_ylabel("目标函数行覆盖率（%）"); a1.set_title("目标函数的覆盖率", fontsize=12.5, fontweight="bold")
a1.legend(frameon=False, loc="upper center", ncol=2); clean(a1)
mt = ["04\nprocess_ticket", "05\nskill 处理器", "06 拆分前\nhandle_requirement", "06 拆分后\n分步管线"]
total, first = [15, 22, 105, 129], [15, 20, 104, 126]
miss = [t - f for t, f in zip(total, first)]
a2.bar(mt, first, 0.55, color=GREEN, label="第一遍就被测试发现")
a2.bar(mt, miss, 0.55, bottom=first, color=RED, label="第一遍漏掉，补用例或断言后发现")
for i in range(4):
    note = f"{first[i]} / {total[i]}" + (f"\n漏 {miss[i]} 处" if miss[i] else "\n没有漏")
    a2.text(i, total[i] + 2.5, note, ha="center", va="bottom", fontsize=10)
a2.set_ylim(0, 165); a2.set_ylabel("故意改错的处数"); a2.tick_params(axis="x", labelsize=9.3)
a2.set_title("改坏检查：测试抓到多少处故意的错误", fontsize=12.5, fontweight="bold")
a2.legend(frameon=False, loc="upper left", fontsize=9.5); clean(a2)
fig.tight_layout(w_pad=3)
save(fig, "05_覆盖率与改坏检查")

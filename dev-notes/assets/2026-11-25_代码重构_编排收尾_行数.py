"""在仓库任意目录运行本文件，从已提交的 orchestrator.py 生成本期行数图。"""
from pathlib import Path
import subprocess

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

out = Path(__file__).resolve().parent
repo = out.parent.parent
# 历史基点与本期六个代码提交。
steps = [
    ("d582d06", "上期"), ("7627834", "依赖"), ("c0aeea2", "OpenSpec"),
    ("2403571", "Git"), ("66aee5b", "诊断"), ("6a49432", "轮询"), ("e2e4c2b", "上下文"),
]
sizes = [len(subprocess.check_output(
    ["git", "show", rev + ":backend/orchestrator.py"], cwd=repo,
).splitlines()) for rev, _ in steps]

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
fig, ax = plt.subplots(figsize=(9, 3.7), layout="constrained")
fig.patch.set_facecolor("#fafaf6")
ax.set_facecolor("#fafaf6")
x = list(range(len(steps)))
ax.plot(x, sizes, linewidth=2.8, marker="o", color="#14776f")
ax.axhline(1500, color="#98512f", linestyle="--", linewidth=1)
ax.text(0.02, 1515, "验收线 1,500 行", color="#98512f", fontsize=10)
for i, n in enumerate(sizes):
    ax.annotate(f"{n:,}", (i, n), xytext=(0, -17 if n == 1450 else 9), textcoords="offset points", ha="center")
ax.set(xticks=x, xticklabels=[s for _, s in steps], ylim=(1000, 1940), ylabel="文件行数")
ax.grid(axis="y", color="#deded9", linewidth=0.6)
ax.spines[["right", "top"]].set_visible(False)
ax.set_title("编排入口从 1,818 行减到 1,119 行", loc="left", weight="bold", pad=12)
fig.savefig(out / "2026-11-25_代码重构_编排收尾_行数.png", dpi=145)

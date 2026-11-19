"""六层严格 DAG 门禁单测（方案 §6.3 + §11 拍板结论）。

P0 阶段现状本就有大量方向律违规，故门禁断言为「相对基线只许减少不许增加」
+ 「硬性违规为 0」，而非 §6.3 字面的「断言 0 违规」—— 后者会让 P0 直接红。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CHECKER = REPO / "scripts" / "check_layers.py"
BASELINE = REPO / "backend" / "layers_baseline.json"


def run(*args: str):
    proc = subprocess.run(
        [sys.executable, str(CHECKER), "--json", *args],
        cwd=str(REPO), capture_output=True, text=True,
    )
    # ast.parse 的 SyntaxWarning 走 stderr，stdout 是纯 JSON
    return proc.returncode, json.loads(proc.stdout)


def test_checker_runs_and_loads_config():
    code, result = run()
    assert code in (0, 1)
    assert result["stats"]["modules"] > 0
    assert result["stats"]["parse_errors"] == 0


def test_baseline_registered():
    assert BASELINE.exists(), "P0 须先跑 scripts/check_layers.py --baseline 登记基线"


def test_no_new_violations_vs_baseline():
    _, result = run()
    assert result["baseline_found"] is True
    assert result["new_violations"] == [], (
        "相对 P0 基线出现新增违规（只许减少不许增加）: "
        + ", ".join(v["key"] for v in result["new_violations"][:5])
    )


def test_hard_failures_absent():
    _, result = run()
    hard = [v for v in result["violations"]
            if v["type"] in ("BOUNDARY", "EXPIRED_EXCEPTION")]
    assert hard == [], f"分界律 / 豁免到期违规: {hard}"


def test_structural_metrics_not_regressed():
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))["stats"]
    _, result = run()
    s = result["stats"]
    assert s["scc_groups"] <= baseline["scc_groups"], "SCC 组数只许减少不许增加"
    assert s["scc_max"] <= baseline["scc_max"], "最大 SCC 只许缩小不许扩大"
    assert s["bidirectional_pairs"] <= baseline["bidirectional_pairs"], "双向对数只许减少"


def test_main_ring_eliminated():
    """P2 验收（§7/§10）：62 模块主环已打散，依赖图必须无环、无双向 import 对。

    单独锁死成果 —— test_structural_metrics_not_regressed 只断言「<= P0 基线
    3 组」，若主环重新长回 1 组（哪怕 62 模块）仍会通过那条宽松断言。
    """
    _, result = run()
    s = result["stats"]
    assert s["scc_groups"] == 0, f"主环未清零，仍有 {s['scc_groups']} 个 SCC（最大 {s['scc_max']}）"
    assert s["bidirectional_pairs"] == 0, f"仍有 {s['bidirectional_pairs']} 对双向 import"


def test_expired_exception_fails_gate(tmp_path):
    """§11 #5：豁免到期未清零必须让门禁非 0 退出。

    用自包含的合成项目验证，不依赖仓库里是否还有真实环 —— P1 拆完两组
    小环后已无 until=P1 豁免，后续 P2/P3 也不该让本测试失效。
    """
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "a.py").write_text("import b\n", encoding="utf-8")
    (proj / "b.py").write_text("import a\n", encoding="utf-8")

    cfg = tmp_path / "layers.toml"
    cfg.write_text(
        '\n'.join([
            "[scan]",
            f'root = "{proj.as_posix()}"',
            "exclude_dirs = []",
            "",
            "[levels]",
            'L0 = ["a"]',
            "L1 = []",
            "L2 = []",
            "L3 = []",
            "",
            "[rules.can_import]",
            'L0 = ["L0"]',
            'L1 = ["L0", "L1", "L2"]',
            'L2 = ["L0", "L2"]',
            'L3 = ["L0", "L2", "L3"]',
            "",
            "[boundaries]",
            "distribution_modules = []",
            "",
            "[exceptions]",
            'phase = "P1"',
            "",
            "[[exceptions.allowed_cycles]]",
            'modules = ["a", "b"]',
            'until = "P1"',
            'owner = "test"',
            'reason = "合成环：验证到期未清零"',
            "",
        ]),
        encoding="utf-8",
    )
    baseline = tmp_path / "no_baseline.json"
    code, result = run("--config", str(cfg), "--phase", "P1",
                       "--baseline-path", str(baseline))
    assert result["stats"]["scc_groups"] == 1, "合成项目应形成 1 个 SCC"
    expired = [v for v in result["violations"] if v["type"] == "EXPIRED_EXCEPTION"]
    assert expired, "到期未清零的豁免应产生 EXPIRED_EXCEPTION"
    assert code != 0, "到期未清零时门禁必须非 0 退出"

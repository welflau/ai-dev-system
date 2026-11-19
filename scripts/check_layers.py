#!/usr/bin/env python3
"""ADS 六层严格 DAG 静态守卫（方案 §6.2）。

扫描 backend/**/*.py 的 ast（含函数/类体内延迟 import 与动态导入字符串），
构建模块依赖图，校验方向律 / 无环律 / 分界律，支持 --baseline 生成快照。

  python scripts/check_layers.py --baseline          # P0 登记基线
  python scripts/check_layers.py                     # 常规检查：相对基线只许减少不许增加
  python scripts/check_layers.py --phase P1 --json   # 指定阶段 / 机器可读输出

退出码：出现「相对基线新增违规」「豁免到期未清零」「分界律违规」时非 0。
P0 的既有违规全部登记进基线，不因此判红（否则渐进收敛无从起步）。
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
import tomllib
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO / "backend" / "layers.toml"
DEFAULT_BASELINE = REPO / "backend" / "layers_baseline.json"
PHASES = ["P0", "P1", "P2", "P3", "P4", "P5"]


# ---------- 配置与模块发现 ----------

def load_config(path: Path) -> dict:
    with path.open("rb") as f:
        return tomllib.load(f)


def module_name(rel: Path) -> str:
    parts = list(rel.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def is_excluded(rel_posix: str, dirs: list[str]) -> bool:
    padded = "/" + rel_posix
    for d in dirs:
        if rel_posix == d or rel_posix.startswith(d + "/") or ("/" + d + "/") in padded:
            return True
    return False


def discover_modules(root: Path, exclude_dirs: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root)
        if is_excluded(rel.as_posix(), exclude_dirs):
            continue
        mod = module_name(rel)
        if not mod:
            continue
        is_pkg = rel.name == "__init__.py"
        out[mod] = {
            "path": path,
            "rel": rel.as_posix(),
            "package": mod if is_pkg else mod.rpartition(".")[0],
        }
    return out


# ---------- import 解析 ----------

def iter_nodes(tree: ast.AST):
    """带 delayed 标记的前序遍历：进入函数/类体后子树内 import 全算延迟。"""
    stack = [(tree, False)]
    while stack:
        node, delayed = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            delayed = True
        yield node, delayed
        for child in ast.iter_child_nodes(node):
            stack.append((child, delayed))


def resolve_relative(level: int, mod: str | None, package: str) -> str:
    parts = package.split(".") if package else []
    up = level - 1
    if up:
        parts = parts[:-up] if up <= len(parts) else []
    return ".".join(x for x in (".".join(parts), mod or "") if x)


def normalize_target(raw: str, known: set[str]) -> str | None:
    if not raw:
        return None
    if raw in known:
        return raw
    if any(m.startswith(raw + ".") for m in known):  # raw 指向包
        return raw
    return None


def dynamic_target(call: ast.Call) -> str | None:
    f = call.func
    is_import_module = (
        isinstance(f, ast.Attribute)
        and f.attr == "import_module"
        and isinstance(f.value, ast.Name)
        and f.value.id == "importlib"
    )
    is_dunder = isinstance(f, ast.Name) and f.id == "__import__"
    if not (is_import_module or is_dunder) or not call.args:
        return None
    arg = call.args[0]
    return arg.value if isinstance(arg, ast.Constant) and isinstance(arg.value, str) else None


def parse_file(src: str, info: dict, known: set[str]):
    """返回 (edges, warnings, import 语句数, 延迟 import 数)。"""
    try:
        tree = ast.parse(info["path"].read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, OSError):
        return [], [{"type": "PARSE_ERROR", "file": info["rel"]}], 0, 0

    edges, warnings = [], []
    total = delayed_count = 0
    seen: set[tuple] = set()

    for node, delayed in iter_nodes(tree):
        raws: list[str] = []
        if isinstance(node, ast.Import):
            total += 1
            delayed_count += int(delayed)
            raws = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            total += 1
            delayed_count += int(delayed)
            raw = (resolve_relative(node.level, node.module, info["package"])
                   if node.level else (node.module or ""))
            if raw:
                raws = [raw]
        elif isinstance(node, ast.Call):
            tgt = dynamic_target(node)
            if tgt:
                mapped = normalize_target(tgt, known)
                warnings.append({"type": "DYNAMIC_IMPORT", "file": info["rel"],
                                 "line": node.lineno, "target": tgt, "mapped": mapped})
                if mapped:
                    raws = [mapped]
        else:
            continue

        for raw in raws:
            dst = normalize_target(raw, known)
            if not dst or dst == src:
                continue
            key = (src, dst, node.lineno)
            if key in seen:
                continue
            seen.add(key)
            edges.append({"src": src, "dst": dst, "file": info["rel"],
                          "line": node.lineno, "delayed": delayed,
                          "dynamic": isinstance(node, ast.Call)})

    return edges, warnings, total, delayed_count


# ---------- 规则 ----------

def layer_of(mod: str, levels: dict) -> str | None:
    best, best_len = None, -1
    for layer, prefixes in levels.items():
        for p in prefixes:
            if (mod == p or mod.startswith(p + ".")) and len(p) > best_len:
                best, best_len = layer, len(p)
    return best


def dedup(violations: list[dict]) -> list[dict]:
    seen, out = set(), []
    for v in violations:
        if v["key"] not in seen:
            seen.add(v["key"])
            out.append(v)
    return out


def check_direction(edges, levels, can_import) -> list[dict]:
    out = []
    for e in edges:
        ls, ld = layer_of(e["src"], levels), layer_of(e["dst"], levels)
        if not ls or not ld:
            continue
        if ld not in can_import.get(ls, []):
            out.append({"type": "DIRECTION", "key": f"DIRECTION:{e['src']}->{e['dst']}",
                        "detail": f"{ls} {e['src']} -> {ld} {e['dst']}",
                        "file": e["file"], "line": e["line"]})
    return dedup(out)


def tarjan(nodes: list[str], adj: dict[str, list[str]]) -> list[list[str]]:
    index, low, on_stack, stack, result = {}, {}, set(), [], []
    counter = [0]

    def visit(v):
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on_stack.add(v)
        for w in adj.get(v, ()):
            if w not in index:
                visit(w)
                low[v] = min(low[v], low[w])
            elif w in on_stack:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                comp.append(w)
                if w == v:
                    break
            result.append(comp)

    for v in nodes:
        if v not in index:
            visit(v)
    return result


def name_match(a: str, b: str) -> bool:
    return a == b or a.endswith("." + b) or b.endswith("." + a)


def find_exemption(comp: list[str], exceptions: list[dict]) -> dict | None:
    for ex in exceptions:
        if all(any(name_match(m, e) for e in ex["modules"]) for m in comp):
            return ex
    return None


def check_cycles(cycles, exceptions, phase):
    violations, exempted, expired, extensions = [], [], [], []
    for comp in cycles:
        ex = find_exemption(comp, exceptions)
        key = "CYCLE:" + ",".join(sorted(comp))
        if ex:
            until = ex.get("extended_to") or ex["until"]
            if ex.get("extended_to"):
                extensions.append({"modules": ex["modules"], "from": ex["until"],
                                   "to": until, "reason": ex.get("reason", "")})
            entry = {"key": key, "modules": sorted(comp), "until": until,
                     "owner": ex.get("owner", ""), "reason": ex.get("reason", "")}
            if PHASES.index(until) <= PHASES.index(phase):
                expired.append(entry)
            else:
                exempted.append(entry)
            continue
        violations.append({"type": "CYCLE", "key": key,
                           "detail": f"SCC size={len(comp)}: {', '.join(sorted(comp)[:6])}"
                                     + (" ..." if len(comp) > 6 else "")})
    return violations, exempted, expired, extensions


def check_boundaries(edges, forbidden) -> list[dict]:
    out = []
    for e in edges:
        if e["src"] in forbidden or e["dst"] in forbidden:
            out.append({"type": "BOUNDARY", "key": f"BOUNDARY:{e['src']}->{e['dst']}",
                        "detail": f"分发层出现在 backend 依赖图: {e['src']} -> {e['dst']}",
                        "file": e["file"], "line": e["line"]})
    return dedup(out)


def bidirectional_pairs(edges) -> set:
    seen = {(e["src"], e["dst"]) for e in edges}
    return {(a, b) for a, b in seen if (b, a) in seen and a < b}


# ---------- 汇总 ----------

def run_check(config: dict, phase: str, repo: Path) -> dict:
    sys.setrecursionlimit(10000)
    scan = config["scan"]
    root = repo / scan["root"]
    modules = discover_modules(root, scan.get("exclude_dirs", []))
    levels = config["levels"]
    can_import = config["rules"]["can_import"]
    distribution = set(config["boundaries"].get("distribution_modules", []))
    exceptions = config["exceptions"].get("allowed_cycles", [])
    resolve_known = set(modules) | distribution

    edges, warnings, total_imports, delayed_imports = [], [], 0, 0
    for mod, info in modules.items():
        e, w, t, d = parse_file(mod, info, resolve_known)
        edges.extend(e)
        warnings.extend(w)
        total_imports += t
        delayed_imports += d

    nodes = set(modules)
    graph_edges = [e for e in edges if e["src"] in nodes and e["dst"] in nodes]
    adj = defaultdict(set)
    for e in graph_edges:
        adj[e["src"]].add(e["dst"])
    cycles = [c for c in tarjan(sorted(nodes), {k: sorted(v) for k, v in adj.items()})
              if len(c) > 1]

    direction = check_direction(graph_edges, levels, can_import)
    cycle_v, exempted, expired, extensions = check_cycles(cycles, exceptions, phase)
    boundary = check_boundaries(graph_edges, distribution)
    for entry in expired:
        boundary.append({"type": "EXPIRED_EXCEPTION", "key": "EXPIRED:" + entry["key"],
                         "detail": f"豁免到期未清零: {', '.join(entry['modules'][:4])}",
                         "file": "", "line": 0})
    violations = dedup(direction + cycle_v + boundary)

    stats = {
        "phase": phase,
        "modules": len(modules),
        "edges": len(graph_edges),
        "import_statements": total_imports,
        "delayed_imports": delayed_imports,
        "delayed_ratio": round(delayed_imports / total_imports, 4) if total_imports else 0,
        "scc_groups": len(cycles),
        "scc_max": max((len(c) for c in cycles), default=0),
        "bidirectional_pairs": len(bidirectional_pairs(graph_edges)),
        "unclassified_modules": sum(1 for m in modules if not layer_of(m, levels)),
        "dynamic_imports": sum(1 for w in warnings if w["type"] == "DYNAMIC_IMPORT"),
        "parse_errors": sum(1 for w in warnings if w["type"] == "PARSE_ERROR"),
    }
    by_type = defaultdict(int)
    for v in violations:
        by_type[v["type"]] += 1
    return {"stats": stats, "violations": violations, "violation_counts": dict(by_type),
            "exempted_cycles": exempted, "extensions_used": extensions,
            "warnings": warnings}


def write_baseline(result: dict, phase: str, path: Path) -> None:
    data = {
        "phase": phase,
        "generated_by": "scripts/check_layers.py --baseline",
        "stats": result["stats"],
        "violation_keys": sorted({v["key"] for v in result["violations"]}),
        "violation_counts": result["violation_counts"],
        "exempted_cycles": result["exempted_cycles"],
        "extensions_used": result["extensions_used"],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def compare_baseline(result: dict, path: Path):
    if not path.exists():
        return None, []
    data = json.loads(path.read_text(encoding="utf-8"))
    known = set(data.get("violation_keys", []))
    return data, [v for v in result["violations"] if v["key"] not in known]


def main() -> int:
    ap = argparse.ArgumentParser(description="ADS 六层严格 DAG 静态守卫")
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--baseline", action="store_true", help="生成/更新基线快照")
    ap.add_argument("--baseline-path", type=Path, default=DEFAULT_BASELINE)
    ap.add_argument("--phase", choices=PHASES, default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    config = load_config(args.config)
    phase = args.phase or config["exceptions"].get("phase", "P0")
    result = run_check(config, phase, REPO)
    s = result["stats"]

    if args.baseline:
        write_baseline(result, phase, args.baseline_path)
        print(f"基线已写入 {args.baseline_path.relative_to(REPO).as_posix()}")
        print(f"phase={phase} 违规 {len(result['violations'])} 条 "
              f"(豁免 {len(result['exempted_cycles'])} 组)")
        if args.json:
            print(json.dumps({"stats": s, "baseline_written": True}, ensure_ascii=False))
        return 0

    baseline, new = compare_baseline(result, args.baseline_path)
    result["baseline_found"] = baseline is not None
    result["new_violations"] = new
    hard_fail = bool(new) or any(v["type"] in ("BOUNDARY", "EXPIRED_EXCEPTION")
                                 for v in result["violations"])

    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"=== ADS 六层 DAG 守卫 (phase={phase}) ===")
        print(f"模块 {s['modules']} | 项目内边 {s['edges']} | import 语句 "
              f"{s['import_statements']} (延迟 {s['delayed_imports']}, "
              f"{s['delayed_ratio'] * 100:.1f}%)")
        print(f"SCC>1: {s['scc_groups']} 组 (最大 {s['scc_max']}) | "
              f"双向对 {s['bidirectional_pairs']} | 动态导入 {s['dynamic_imports']} | "
              f"未归层模块 {s['unclassified_modules']} | 解析失败 {s['parse_errors']}")
        print(f"违规 {len(result['violations'])} 条 {result['violation_counts']} | "
              f"豁免环 {len(result['exempted_cycles'])} 组 | "
              f"基线 {'已登记' if baseline else '未登记'} | 相对基线新增 {len(new)}")
        for v in result["violations"][:20]:
            print(f"  [{v['type']}] {v['detail']}  {v['file']}:{v['line']}")
        if len(result["violations"]) > 20:
            print(f"  ... 其余 {len(result['violations']) - 20} 条，用 --json 查看")
        if new:
            print(f"  [新增违规] {len(new)} 条 —— 只许减少不许增加")
        if not baseline:
            print("  提示：尚无基线快照，P0 请先跑 --baseline 登记现状")

    return 1 if hard_fail else 0


if __name__ == "__main__":
    sys.exit(main())

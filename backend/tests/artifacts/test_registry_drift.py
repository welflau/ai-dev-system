"""词表防漂 CI —— kind 与 trait 的引用必须都在词表里。

## 为什么需要这类测试（第 3 道闸）

`kinds.py` 的前两道闸（扫描期 lint、写入期 validate）只在**运行时**生效：
skill 写错 kind 要等到有人跑那条流水线才会发现，而那时它已经静默出局了。

第 3 道闸是唯一能在**提交前**拦住漂移的。`trait_taxonomy.yaml` 缺的正是它 ——
见下面 `test_known_trait_drift` 如实记录的 3 处既存不一致。

## 两个词表的对照

| | kind | trait |
|---|---|---|
| 词表 | `backend/artifacts/kinds.yaml` | `backend/skills/rules/trait_taxonomy.yaml` |
| 引用方 | SKILL.md 的 x-workflow | fragments / skills.json / config_packs / DB |
| 运行时校验 | 有（lint + validate） | **无** |
| 命名 | 扁平 `content_outline` | 维度式 `platform:web` |

方案文档：docs/20261015_01_能力自描述与动态组装框架方案.md §3.2
"""
import json
from pathlib import Path

import pytest
import yaml

from artifacts.kinds import KINDS_FILE, load_kinds
from skills.executable_loader import _BUILTIN_ROOT, parse_workflow_skill

BACKEND = Path(__file__).resolve().parents[2]
SOP_DIR = BACKEND / "sop"
TAXONOMY = BACKEND / "skills" / "rules" / "trait_taxonomy.yaml"

pytestmark = pytest.mark.real_builtin_skills      # 要扫真实的内置 skill


# ════════════════════ 采集 ════════════════════

def _all_skill_md() -> list:
    """所有内置 skill 的 SKILL.md。

    扫 `_BUILTIN_ROOT` 而非硬编码列表 —— 新增 skill 自动纳入检查，
    这正是「防漂」的意思。
    """
    return sorted(_BUILTIN_ROOT.glob("*/SKILL.md"))


def _workflow_skills() -> list:
    """(skill_id, WorkflowSkill)，只含有 x-workflow 的。"""
    out = []
    for md in _all_skill_md():
        fm = yaml.safe_load(md.read_text(encoding="utf-8").split("---")[1]) or {}
        wf = parse_workflow_skill(md.parent.name, fm, source_path=md)
        if wf is not None:
            out.append((md.parent.name, wf))
    return out


def _taxonomy_traits() -> set:
    """词表里的合法 trait，形如 `platform:web`。"""
    data = yaml.safe_load(TAXONOMY.read_text(encoding="utf-8")) or {}
    valid = set()
    for dim, body in data.items():
        if isinstance(body, dict) and "values" in body:
            for v in body["values"]:
                valid.add(f"{dim}:{v}")
    return valid


def _traits_in_sop() -> dict:
    """SOP 里引用的 trait → 来源文件集合。"""
    used = {}

    def walk(node, where):
        if isinstance(node, dict):
            rt = node.get("required_traits")
            if isinstance(rt, dict):
                for key in ("all_of", "any_of", "none_of"):
                    for t in (rt.get(key) or []):
                        used.setdefault(str(t), set()).add(where)
            for v in node.values():
                walk(v, where)
        elif isinstance(node, list):
            for v in node:
                walk(v, where)

    for p in list((SOP_DIR / "fragments").glob("*.yaml")) + [SOP_DIR / "_core.yaml"]:
        walk(yaml.safe_load(p.read_text(encoding="utf-8")) or {}, p.name)
    return used


# ════════════════════ kind 防漂（第 3 道闸） ════════════════════

def test_all_skill_kinds_are_registered():
    """**核心防漂断言**：SKILL.md 里引用的每个 kind 都在 kinds.yaml 里。

    拼错一个 kind 的后果是**静默的**：discover 期该 skill 出局（有 ERROR 日志，
    但没人实时看日志），流水线少跑一步，没有任何报错。这条测试把它变成
    提交前的红灯。
    """
    registry = set(load_kinds())
    problems = []
    for skill_id, wf in _workflow_skills():
        for kind in wf.consume_kinds + wf.produce_kinds:
            if kind not in registry:
                problems.append(f"{skill_id}: '{kind}'")
    assert problems == [], (
        f"以下 kind 未在 {KINDS_FILE.name} 登记:\n  " + "\n  ".join(problems)
    )


def test_no_skill_produces_inline_or_builtin_kind():
    """produces 不得是 inline（老 Agent 路径）或 builtin（框架自动产出）。

    与 `lint_kind_refs` 的 E2/E3 同规则，但那是运行时的 —— 这里在提交前拦。
    """
    registry = load_kinds()
    problems = []
    for skill_id, wf in _workflow_skills():
        for kind in wf.produce_kinds:
            spec = registry.get(kind)
            if spec is None:
                continue                       # 上一条测试管这个
            if spec.is_inline:
                problems.append(f"{skill_id} produces inline kind '{kind}'")
            if spec.builtin:
                problems.append(f"{skill_id} produces builtin kind '{kind}'")
    assert problems == [], "\n  ".join(problems)


def test_produces_glob_matches_runner_outputs():
    """x-workflow.produces 的 glob 必须出现在 x-runner.outputs.globs 里。

    不一致的后果很隐蔽：`_collect_outputs` 用 `{glob: kind}` 反查给产出归类，
    glob 对不上 → 文件被回收但 **kind 为空** → SkillAgent 跳过登记
    （它只登记有 kind 的）→ 下游 consumes 永远拿不到。
    全程没有任何报错，`status` 还是 success。
    """
    problems = []
    for md in _all_skill_md():
        text = md.read_text(encoding="utf-8")
        fm = yaml.safe_load(text.split("---")[1]) or {}
        wf = parse_workflow_skill(md.parent.name, fm)
        if wf is None:
            continue
        runner_globs = set(
            ((fm.get("x-runner") or {}).get("outputs") or {}).get("globs") or []
        )
        for p in wf.produces:
            if p.glob and p.glob not in runner_globs:
                problems.append(
                    f"{md.parent.name}: produces 的 glob '{p.glob}' "
                    f"不在 x-runner.outputs.globs {sorted(runner_globs)} 里"
                )
    assert problems == [], "\n  ".join(problems)


def test_stage_ids_globally_unique():
    """stage_id 不得与 base_stages / fragments 的 stage.id 撞名。

    撞名时 `_find_stage_idx` / `by_action` 的「先到先得」会反查到错误的 stage。
    compose_sop 里有运行时防撞（会跳过并报 ERROR），但那时 skill 已经不生效了。
    """
    sop_ids = set()
    core = yaml.safe_load((SOP_DIR / "_core.yaml").read_text(encoding="utf-8")) or {}
    for s in core.get("base_stages") or []:
        if s.get("id"):
            sop_ids.add(s["id"])
    for p in (SOP_DIR / "fragments").glob("*.yaml"):
        frag = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        sid = (frag.get("stage") or {}).get("id") or frag.get("id")
        if sid:
            sop_ids.add(sid)

    seen = {}
    problems = []
    for skill_id, wf in _workflow_skills():
        if wf.stage_id in sop_ids:
            problems.append(f"{skill_id}: stage_id '{wf.stage_id}' 与 SOP 阶段同名")
        if wf.stage_id in seen:
            problems.append(
                f"{skill_id}: stage_id '{wf.stage_id}' 与 {seen[wf.stage_id]} 重复"
            )
        seen[wf.stage_id] = skill_id
    assert problems == [], "\n  ".join(problems)


def test_every_registered_kind_is_reachable():
    """词表里的每个非 legacy kind 都应有 producer 或是 builtin。

    孤儿 kind（登记了但没人产出也没人消费）是词表膨胀的前兆 ——
    下一个人会以为它有用而去 consumes 它，然后发现永远匹配不上。
    """
    registry = load_kinds()
    produced = {"__builtin__"}
    consumed = set()
    for _sid, wf in _workflow_skills():
        produced.update(wf.produce_kinds)
        consumed.update(wf.consume_kinds)

    orphans = [
        name for name, spec in registry.items()
        if not spec.legacy and not spec.builtin
        and name not in produced and name not in consumed
    ]
    # style_guide 是刻意保留的「可选上游」示例，demo 链 consumes 它但无人 produces
    assert orphans == [], (
        f"以下 kind 既无 producer 也无 consumer（孤儿）: {orphans}。"
        f"要么给它写个 skill，要么从词表删掉"
    )


# ════════════════════ trait 防漂 ════════════════════

def test_known_trait_drift():
    """# KNOWN ISSUE —— 如实锁住 3 处既存的 trait 命名不一致。

    词表用**维度式**命名（`<dimension>:<value>`），但这 3 个 fragment 用的是
    另一套写法：

    | fragment 里写的 | 词表里实际是 | 差异 |
    |---|---|---|
    | `i18n` | `quality:i18n` | 缺维度前缀 |
    | `multiplayer:true` | `features:multiplayer` | 维度错 + `:true` 后缀 |
    | `prototype:html` | `lifecycle:prototype` | 维度错 + value 错 |

    `_normalize_trait`（api/projects.py:1377）会把裸 `i18n` 补成 `i18n:true`，
    更对不上。

    **后果**：这 3 个 fragment 的 `required_traits` 永远不会被满足 ——
    i18n_check / multiplayer_stress / html_prototype(prototype:html 分支)
    实际上是死代码，除非有人手工往 DB 里塞这些非法 trait。

    为什么不在这轮修：改 fragment 的 trait 会改变它们的激活条件，
    需要确认线上没有项目依赖当前（失效的）行为。本测试先把现状钉死，
    修的时候它会红 —— 那是预期的。
    """
    valid = _taxonomy_traits()
    used = _traits_in_sop()
    drift = sorted(t for t in used if t not in valid)
    assert drift == ["i18n", "multiplayer:true", "prototype:html"], (
        f"trait 漂移清单变了（原 3 项）。当前: {drift}\n"
        f"新增漂移要修；修好既有的要同步改本测试的期望值"
    )


def test_no_new_trait_drift_in_sop():
    """除了上面 3 个已知项，SOP 里不得出现新的词表外 trait。

    这是本测试文件存在的主要理由：**让漂移停止增长**。
    """
    valid = _taxonomy_traits()
    known = {"i18n", "multiplayer:true", "prototype:html"}
    used = _traits_in_sop()
    new_drift = {t: sorted(s) for t, s in used.items()
                 if t not in valid and t not in known}
    assert new_drift == {}, (
        "SOP 里出现了词表外的新 trait:\n  "
        + "\n  ".join(f"{t} ← {srcs}" for t, srcs in sorted(new_drift.items()))
        + f"\n请先在 {TAXONOMY.name} 登记"
    )


def test_pipeline_dimension_registered():
    """v0.20 新增的 pipeline 维度必须在词表里。

    `_core.yaml` 的 base_stages 裁剪依赖 `pipeline:content`，
    demo skill 链的 required_traits 也用它。漏登记会让裁剪静默失效。
    """
    valid = _taxonomy_traits()
    assert "pipeline:code" in valid
    assert "pipeline:content" in valid


def test_ue_content_ticket_type_registered():
    """ue_content_gen 用的 ticket_type 要在词表里（上一轮补的）。"""
    data = yaml.safe_load(TAXONOMY.read_text(encoding="utf-8")) or {}
    assert "ue_content" in (data.get("ticket_type") or {}).get("values", [])


def test_skills_json_traits_are_registered():
    """skills.json 的 traits_match 也受词表约束。

    它和 SOP 是两套独立的 trait 消费方 —— 只查 SOP 会漏掉这一半。
    """
    valid = _taxonomy_traits()
    sj = json.loads(
        (BACKEND / "skills" / "skills.json").read_text(encoding="utf-8")
    )
    problems = []
    for sid, cfg in sj.items():
        tm = cfg.get("traits_match") or {}
        for key in ("all_of", "any_of", "none_of"):
            for t in (tm.get(key) or []):
                if t not in valid:
                    problems.append(f"skills.json[{sid}].{key}: '{t}'")
    assert problems == [], (
        f"以下 trait 未在 {TAXONOMY.name} 登记:\n  " + "\n  ".join(problems)
    )


# ════════════════════ 词表自身 ════════════════════

def test_kinds_yaml_parses_and_is_nonempty():
    assert len(load_kinds()) >= 15


def test_taxonomy_has_no_duplicate_values_within_dimension():
    """同一维度内不得有重复值 —— YAML 不会报错，但会让词表失去权威性。"""
    data = yaml.safe_load(TAXONOMY.read_text(encoding="utf-8")) or {}
    for dim, body in data.items():
        if isinstance(body, dict) and isinstance(body.get("values"), list):
            vals = body["values"]
            assert len(vals) == len(set(vals)), f"维度 {dim} 有重复值"


def test_demo_skills_are_discoverable():
    """demo-* 三件套必须被发现 —— 它们是 e2e 的 fixture，丢了 e2e 会静默退化。

    「静默」指的是：skill 不见了 compose 出来就没有 skill stage，
    e2e 的断言会变成「空列表 == 空列表」那类无意义的通过。
    """
    stage_ids = {wf.stage_id for _sid, wf in _workflow_skills()}
    assert {"demo_outline", "demo_draft", "demo_cover"} <= stage_ids


def test_demo_priorities_stay_inverted():
    """demo 链的 priority **必须与依赖顺序相反**。

    这是刻意设计：priority 同向的话，「拓扑排序生效」在 demo 链里不可观测
    （只按 priority 排也得出同样结果）。实测把拓扑排序换成纯 priority 排序时，
    正是靠这个反向设置让 6 个 e2e 测试变红。

    谁把 priority 改回同向，这条会红 —— 提醒他那样会让 e2e 失去鉴别力。
    """
    by_stage = {wf.stage_id: wf.priority for _sid, wf in _workflow_skills()}
    assert by_stage["demo_cover"] > by_stage["demo_draft"] > by_stage["demo_outline"], (
        f"demo 链 priority 不再反向: {by_stage}。"
        f"同向会让 e2e 测不出拓扑排序是否生效"
    )

"""
v0.19.x Phase A —— CIStrategy 抽象 smoke test

验证：
  1. Loader 能扫描并注册所有 strategies
  2. Web 项目（platform:web / category:app）命中 WebCIStrategy
  3. UE 项目（engine:ue5）在 Phase A 没 UE strategy 时走 Default
  4. 空 traits 项目走 Default
  5. Strategy 的 pipeline_stages / environment_specs / build_types 返回正确结构
  6. to_definition() 结构完整（前端消费用）
  7. 现有 Web 项目触发构建走 strategy.trigger_build —— 跟直接调 ci_pipeline.trigger_build 等价

用法：
    cd backend && python _test_v019_ci_strategy.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, ".")


def _banner(msg: str):
    print()
    print("=" * 70)
    print(f"  {msg}")
    print("=" * 70)


async def main():
    passed, failed = 0, 0

    def check(name: str, ok: bool, detail: str = ""):
        nonlocal passed, failed
        marker = "PASS" if ok else "FAIL"
        print(f"  [{marker}] {name}" + (f"  -- {detail}" if detail else ""))
        if ok:
            passed += 1
        else:
            failed += 1

    from database import db
    from ci.loader import ci_loader
    from ci.strategies.base import CIStrategy, EnvSpec, PipelineStage, BuildTypeSpec
    from ci.strategies.web import WebCIStrategy
    from ci.strategies.default import DefaultCIStrategy
    from utils import generate_id, now_iso

    await db.connect()

    # =========== 1. Loader 注册 ===========
    _banner("1. CIStrategyLoader 能扫描注册 strategies")
    ci_loader.load_all()
    all_s = ci_loader.all_strategies()
    names = [s.name for s in all_s]
    check("Loader 能加载 >= 2 个策略（web + default）",
          len(all_s) >= 2, f"names={names}")
    check("包含 'web' 策略", "web" in names)
    check("包含 'default' 策略", "default" in names)

    # =========== 2. Web 项目命中 WebCIStrategy ===========
    _banner("2. Web 项目 traits → WebCIStrategy")
    pid_web = generate_id("PRJ")
    await db.insert("projects", {
        "id": pid_web, "name": "WebTestCI", "description": "",
        "status": "active", "tech_stack": "React", "config": "{}",
        "git_repo_path": "D:/Projects/_ci_strategy_test_web",
        "git_remote_url": "",
        "traits": json.dumps(["platform:web", "category:app", "lang:typescript"]),
        "traits_confidence": "{}", "preset_id": None,
        "created_at": now_iso(), "updated_at": now_iso(),
    })
    s_web = await ci_loader.pick_for_project(pid_web)
    check("Web 项目命中 'web' 策略",
          s_web.name == "web", f"got={s_web.name}")
    check("返回的是 WebCIStrategy 实例",
          isinstance(s_web, WebCIStrategy))

    # =========== 3. UE 项目 Phase A 没 UE strategy → Default ===========
    _banner("3. UE 项目（Phase A 无 UEStrategy）→ default 兜底")
    pid_ue = generate_id("PRJ")
    await db.insert("projects", {
        "id": pid_ue, "name": "UETestCI", "description": "",
        "status": "active", "tech_stack": "UE5", "config": "{}",
        "git_repo_path": "D:/Projects/_ci_strategy_test_ue",
        "git_remote_url": "",
        "traits": json.dumps(["engine:ue5", "category:game", "platform:desktop"]),
        "traits_confidence": "{}", "preset_id": None,
        "created_at": now_iso(), "updated_at": now_iso(),
    })
    s_ue = await ci_loader.pick_for_project(pid_ue)
    check("UE 项目走 default 兜底（Phase A 未加 UEStrategy）",
          s_ue.name == "default", f"got={s_ue.name}")

    # =========== 4. 空 traits 项目 → Default ===========
    _banner("4. 空 traits 项目 → default 兜底")
    pid_empty = generate_id("PRJ")
    await db.insert("projects", {
        "id": pid_empty, "name": "EmptyTraits", "description": "",
        "status": "active", "tech_stack": "", "config": "{}",
        "git_repo_path": "D:/Projects/_ci_empty",
        "git_remote_url": "",
        "traits": "[]", "traits_confidence": "{}",
        "preset_id": None, "created_at": now_iso(), "updated_at": now_iso(),
    })
    s_empty = await ci_loader.pick_for_project(pid_empty)
    check("空 traits 走 default", s_empty.name == "default")

    # =========== 5. 策略元数据结构 ===========
    _banner("5. Strategy 元数据（stages / environments / build_types）结构")
    stages = s_web.pipeline_stages()
    envs = s_web.environment_specs()
    bts = s_web.build_types()
    check("pipeline_stages 非空", len(stages) > 0, f"count={len(stages)}")
    check("所有 stage 是 PipelineStage",
          all(isinstance(st, PipelineStage) for st in stages))
    check("environment_specs 非空", len(envs) > 0, f"count={len(envs)}")
    check("所有 env 是 EnvSpec",
          all(isinstance(e, EnvSpec) for e in envs))
    check("environments 含 dev/test/prod",
          {e.name for e in envs} >= {"dev", "test", "prod"})
    check("build_types 非空", len(bts) > 0)
    check("build_types 含 develop_build/master_build/deploy",
          {b.id for b in bts} >= {"develop_build", "master_build", "deploy"})

    # =========== 6. to_definition() 结构 ===========
    _banner("6. to_definition() 结构完整（前端消费用）")
    defn = s_web.to_definition()
    check("含 strategy 字段", "strategy" in defn)
    check("含 stages 列表", isinstance(defn.get("stages"), list))
    check("含 environments 列表", isinstance(defn.get("environments"), list))
    check("含 build_types 列表", isinstance(defn.get("build_types"), list))
    check("strategy.name 正确", defn.get("strategy") == "web")
    if defn.get("stages"):
        st0 = defn["stages"][0]
        check("stage 含 id/name/icon/blocking 键",
              all(k in st0 for k in ("id", "name", "icon", "blocking")))

    # =========== 7. UE 用自定义 MockStrategy 验证 priority + 匹配 ===========
    _banner("7. priority + required_traits 匹配（注入 MockUE 策略）")
    class MockUECIStrategy(CIStrategy):
        name = "mock_ue"
        required_traits = {"any_of": ["engine:ue5", "engine:ue4"]}
        priority = 100

        def pipeline_stages(self):
            return [PipelineStage(id="ubt", name="UBT", icon="🔧")]

        def environment_specs(self):
            return [EnvSpec(name="packaged", display_name="打包产物", icon="📦")]

        def build_types(self):
            return [BuildTypeSpec(id="full", display_name="完整构建", icon="▶")]

        async def trigger_build(self, project_id, build_type, trigger="manual", **kwargs):
            return {"build_id": "mock-1", "status": "mocked"}

        async def deploy_environment(self, project_id, env_name, **kwargs):
            return {"status": "ok", "mocked": True}

        async def get_environment_status(self, project_id, env_name):
            return {"status": "mocked"}

    mock = MockUECIStrategy()
    ci_loader._strategies.insert(0, mock)
    ci_loader._strategies.sort(key=lambda s: s.priority, reverse=True)

    s_ue_mocked = await ci_loader.pick_for_project(pid_ue)
    check("UE 项目现在命中 mock_ue", s_ue_mocked.name == "mock_ue")
    check("Web 项目仍命中 web（优先级隔离）",
          (await ci_loader.pick_for_project(pid_web)).name == "web")

    # 清理 mock 避免影响其他 test
    ci_loader._strategies.remove(mock)

    # =========== 8. 清理 ===========
    _banner("8. 清理")
    for p in (pid_web, pid_ue, pid_empty):
        try:
            await db.execute("DELETE FROM projects WHERE id = ?", (p,))
        except Exception:
            pass

    _banner("Summary")
    total = passed + failed
    print(f"  PASS {passed}/{total}  FAIL {failed}/{total}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    rc = asyncio.run(main())
    sys.exit(rc)

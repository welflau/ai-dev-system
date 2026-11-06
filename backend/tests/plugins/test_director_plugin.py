"""Director 视频套件：词表隔离、compose、工作包、人审、生视频护栏。"""
import asyncio
from pathlib import Path

import pytest

from plugins.registry import create_action, get_ads_plugin, list_ads_plugins
from skills.executable_loader import discover_workflow_skills
from skills.loader import SkillLoader
from sop.loader import compose_sop, invalidate_sop_cache

pytestmark = [pytest.mark.real_plugin_skills, pytest.mark.real_builtin_skills]


@pytest.fixture(autouse=True)
def _clear_sop_cache():
    invalidate_sop_cache()
    yield
    invalidate_sop_cache()


VIDEO = ["category:video", "pipeline:video"]


def _ids(cfg):
    return [s["id"] for s in cfg["stages"]]


def test_catalog_director_active_only_for_video():
    plugins = {p["id"]: p for p in list_ads_plugins(traits=VIDEO)}
    assert plugins["director"]["active"] is True
    assert plugins["content"]["active"] is False
    assert plugins["h5"]["active"] is False
    assert plugins["ue5"]["active"] is False
    info = get_ads_plugin("director", traits=VIDEO)
    assert info["counts"]["actions"] >= 7
    skill_ids = {s["id"] for s in info["skills"]}
    assert "director-brief" in skill_ids
    assert "director-knowledge" in skill_ids


def test_workflow_skills_discovered():
    found = {wf.skill_id: wf for wf in discover_workflow_skills()}
    assert "director-brief" in found
    assert found["director-brief"].human_gate is True
    assert found["director-brief"].stage_id == "director_brief"
    assert found["director-brief"].agent == "SkillAgent"
    assert "video_brief" in found["director-brief"].produce_kinds
    assert "director-knowledge" not in found
    assert "director-polish" in found
    assert found["director-polish"].required_ticket_type == {"any_of": ["polish"]}


def test_compose_video_has_director_not_demo():
    cfg = compose_sop(traits=VIDEO, ticket_type="feature")
    ids = _ids(cfg)
    for sid in (
        "director_brief", "director_script", "director_visual",
        "director_prompts", "director_clip_trial", "director_batch_gen",
        "director_deliver",
    ):
        assert sid in ids, ids
    assert "demo_outline" not in ids
    assert "demo_draft" not in ids
    assert "demo_cover" not in ids
    assert "ux_design" not in ids
    assert "art_design" not in ids
    assert "asset_gen" not in ids
    assert "h5_typecheck" not in ids
    assert "engine_compile" not in ids
    assert "architecture" not in ids
    assert "development" not in ids
    assert ids.index("planning") < ids.index("director_brief")
    assert ids.index("director_deliver") < ids.index("acceptance")
    assert "director_polish" not in ids
    assert cfg["dropped_base_stages"] == [
        "architecture", "code_review", "development",
        "development_retry", "rework",
    ]


def test_compose_video_ignores_platform_web():
    """误加 platform:web 也不能把漫剧 SOP 变成网站流程。"""
    cfg = compose_sop(traits=VIDEO + ["platform:web"], ticket_type="feature")
    ids = _ids(cfg)
    assert "director_brief" in ids
    assert "ux_design" not in ids
    assert "art_design" not in ids
    assert "deploy_web" not in ids
    assert "development" not in ids


def test_compose_polish_only_has_director_polish():
    """polish 工单只重跑单片段，不能把简报/讲稿整链再跑一遍。"""
    cfg = compose_sop(traits=VIDEO, ticket_type="polish")
    ids = _ids(cfg)
    assert "director_polish" in ids
    assert "director_brief" not in ids
    assert "director_script" not in ids
    assert "director_batch_gen" not in ids
    assert "demo_outline" not in ids


def test_compose_content_skips_director():
    cfg = compose_sop(traits=["pipeline:content"], ticket_type="feature")
    ids = _ids(cfg)
    assert "demo_outline" in ids
    assert "director_brief" not in ids
    assert "director_deliver" not in ids


def test_knowledge_injects_for_chat():
    loader = SkillLoader()
    ids = loader.get_skills_for_agent("ChatAssistant", traits=VIDEO)
    assert "director-knowledge" in ids
    prompt = loader.get_skill_prompt("director-knowledge")
    assert prompt and "Mode" in prompt
    other = loader.get_skills_for_agent("ChatAssistant", traits=["engine:ue5"])
    assert "director-knowledge" not in other


def test_init_work_package_idempotent(tmp_path):
    action = create_action("init_work_package")
    assert action is not None
    first = asyncio.run(action.run({
        "repo_path": str(tmp_path),
        "title": "拖延症解说",
    }))
    assert first.success
    slug = first.data["slug"]
    assert (tmp_path / "works" / slug / "current-assets-manifest.md").is_file()
    second = asyncio.run(action.run({
        "repo_path": str(tmp_path),
        "title": "拖延症解说",
        "slug": slug,
    }))
    assert second.success
    assert second.data["slug"] == slug


def test_video_kinds_registered():
    from artifacts.kinds import load_kinds
    kinds = load_kinds()
    for k in (
        "video_brief", "narration_script", "drama_breakdown", "character_bible",
        "character_ref", "scene_bible", "voice_plan", "voice_anchor",
        "shot_prompts", "clip_trial", "video_clip", "video_package", "video_cover",
    ):
        assert k in kinds


def test_gen_video_rejects_bad_filename_and_missing_key(tmp_path, monkeypatch):
    from config import settings
    init = create_action("init_work_package")
    pack = asyncio.run(init.run({"repo_path": str(tmp_path), "title": "t"}))
    slug = pack.data["slug"]
    gen = create_action("gen_video")
    bad = asyncio.run(gen.run({
        "repo_path": str(tmp_path),
        "work_slug": slug,
        "prompt": "一只猫",
        "filename": "../x.mp4",
    }))
    assert bad.success is False
    assert "filename" in (bad.error or "")

    monkeypatch.setattr(settings, "LIGHTAI_API_KEY", "", raising=False)
    missing = asyncio.run(gen.run({
        "repo_path": str(tmp_path),
        "work_slug": slug,
        "prompt": "一只猫",
        "filename": "片段01.mp4",
        "ticket_id": "",
    }))
    assert missing.success is False
    assert missing.data.get("env_missing") is True
    assert not list((tmp_path / "works" / slug / "video").glob("*.mp4"))
    assert isinstance(missing.data.get("command"), str)


def test_gen_video_downloads_when_lightai_mocked(tmp_path, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "LIGHTAI_API_KEY", "test-key", raising=False)

    async def fake_create(req):
        assert req["prompt"]
        return "tid-video", "https://cdn.example/clip.mp4", ""

    async def fake_dl(url, dest):
        dest.write_bytes(b"fake-mp4-bytes")
        return True, ""

    monkeypatch.setattr(
        "plugins.director.lightai_video.create_and_poll_video", fake_create,
    )
    monkeypatch.setattr("plugins.director.lightai_video.download_url", fake_dl)

    init = create_action("init_work_package")
    pack = asyncio.run(init.run({"repo_path": str(tmp_path), "title": "t"}))
    slug = pack.data["slug"]
    gen = create_action("gen_video")
    res = asyncio.run(gen.run({
        "repo_path": str(tmp_path),
        "work_slug": slug,
        "prompt": "一只猫在阳光下",
        "filename": "片段01.mp4",
        "ticket_id": "",
    }))
    assert res.success, res.error
    out = tmp_path / "works" / slug / "video" / "片段01.mp4"
    assert out.is_file() and out.stat().st_size > 0
    assert res.data.get("command")
    assert isinstance(res.data.get("command"), str)


def test_human_gate_ready_status():
    cfg = compose_sop(traits=VIDEO, ticket_type="feature")
    by_id = {s["id"]: s for s in cfg["stages"]}
    assert by_id["director_brief"]["config"]["_human_gate"] is True
    assert by_id["director_brief"]["config"]["_ready_status"] == "director_brief_ready"
    assert by_id["director_clip_trial"]["config"]["_ready_status"] == "director_clip_trial_ready"
    assert by_id["director_prompts"]["config"]["_ready_status"] == "director_prompts_done"


def test_pick_chat_session_prefers_project_chat():
    from plugins.director.actions.confirm_video_gate import pick_chat_session
    assert pick_chat_session("sess--abc", None) == "sess--abc"
    assert pick_chat_session("default", "sess--abc") == "sess--abc"
    assert pick_chat_session("", "sess--abc") == "sess--abc"
    assert pick_chat_session("default", "default") == "default"


def test_director_visual_stops_on_image_backend_fail():
    from skills.executable_loader import load_executable_skill
    from skills.runner import SkillRunner
    skill = load_executable_skill("director-visual")
    assert skill is not None
    assert "禁止重试 gen_image" in skill.body
    prompt = SkillRunner(skill)._build_system({
        "ticket_title": "视觉锁定",
        "project_traits": VIDEO,
    })
    assert "禁止重试" in prompt


def test_clip_gate_inferred_from_skill_blocks_without_mp4(tmp_path):
    init = create_action("init_work_package")
    pack = asyncio.run(init.run({"repo_path": str(tmp_path), "title": "剧"}))
    slug = pack.data["slug"]
    (tmp_path / "works" / slug / "video_brief.json").write_text(
        '{"mode":"cinematic-drama"}', encoding="utf-8",
    )
    gate = create_action("confirm_video_gate")
    res = asyncio.run(gate.run({
        "title": "确认片段1",
        "repo_path": str(tmp_path),
        "work_slug": slug,
        "skill_id": "director-clip-trial",
    }))
    assert res.success is False
    assert res.data.get("waiting_human") is False
    assert "mp4" in (res.error or "").lower() or "片段" in (res.error or "")


def test_confirm_video_gate_sets_waiting_human():
    action = create_action("confirm_video_gate")
    result = asyncio.run(action.run({
        "title": "确认讲稿",
        "work_slug": "demo",
        "preview_paths": ["works/demo/旁白.md"],
    }))
    assert result.success
    assert result.data.get("waiting_human") is True
    assert result.data.get("type") == "confirm_video_gate"


def test_reflection_and_acceptance():
    from plugins.director.reflection import (
        HANDLED_FAILURE_TYPES,
        apply_deterministic_fixes,
        build_reflection_signal,
    )
    from plugins.director import acceptance

    assert "director_script_rejected" in HANDLED_FAILURE_TYPES
    signal = build_reflection_signal("director_script_rejected", {
        "director_reject_reason": "旁白太赶",
        "director_mode": "animated-explainer",
        "director_work_slug": "delay",
    })
    assert "旁白太赶" in signal
    assert apply_deterministic_fixes("x", ".", [], {}) == {}
    ev = asyncio.run(acceptance.build_acceptance_evidence({}))
    assert "不得因" in ev["acceptance_rules"]
    assert ev["extra_check_items"]
    assert ev["failed_items"]


def test_board_columns():
    from api.tickets import _classify_board_column
    from models import STATUS_LABELS
    assert _classify_board_column("director_clip_trial_ready", {}) == "in_review"
    assert _classify_board_column("director_batch_gen_failed", {}) == "blocked"
    assert _classify_board_column("director_brief_in_progress", {}) == "in_progress"
    assert _classify_board_column("cancelled", {}) == "cancelled"
    assert "director_clip_trial_ready" in STATUS_LABELS


def test_restore_cancelled_visual_goes_to_script_done():
    from sop.status_repair import (
        restore_target_from_cancelled_status,
        build_restore_cancelled_targets,
    )
    stages = compose_sop(traits=VIDEO, ticket_type="feature")["stages"]
    assert restore_target_from_cancelled_status(
        "director_visual_in_progress", stages,
    ) == "director_script_done"
    targets = build_restore_cancelled_targets(
        stages, "director_visual_in_progress",
    )
    assert targets[0]["status"] == "director_script_done"
    assert targets[0]["recommended"] is True
    assert any(t["status"] == "pending" for t in targets)


def test_video_unblock_does_not_offer_architecture():
    from sop.status_repair import (
        build_unblock_targets, next_status_if_outside_sop, sop_safe_unblock_target,
    )
    stages = compose_sop(traits=VIDEO, ticket_type="feature")["stages"]
    targets = build_unblock_targets(stages, blocked_from="planning_done")
    assert all(t["status"] != "architecture_done" for t in targets)
    assert targets[0]["status"] == "planning_done"
    assert sop_safe_unblock_target("architecture_done", stages, "planning_done") == "planning_done"
    assert next_status_if_outside_sop("architecture_done", stages) == "planning_done"
    assert next_status_if_outside_sop("planning_done", stages) is None
    assert next_status_if_outside_sop("director_brief_ready", stages) is None


def test_software_unblock_keeps_architecture():
    from sop.status_repair import (
        build_unblock_targets, next_status_if_outside_sop, sop_safe_unblock_target,
    )
    stages = compose_sop(traits=["platform:web"], ticket_type="feature")["stages"]
    targets = build_unblock_targets(stages, blocked_from="architecture_done")
    assert targets[0]["status"] == "architecture_done"
    assert sop_safe_unblock_target("architecture_done", stages) == "architecture_done"
    assert next_status_if_outside_sop("architecture_done", stages) is None


def test_software_bug_ux_done_not_rewound():
    """bug 工单 SOP 常常没有 ux_design，但不能因此把历史 ux_design_done 拉去重跑。"""
    from sop.status_repair import next_status_if_outside_sop
    stages = compose_sop(
        traits=["platform:web", "category:game", "lang:javascript"],
        ticket_type="bug",
    )["stages"]
    assert next_status_if_outside_sop("ux_design_done", stages) is None
    assert next_status_if_outside_sop("architecture_done", stages) is None


def test_workspace_roots(tmp_path):
    from plugins.director.workspace import workspace_roots
    missing = workspace_roots({"git_repo_path": str(tmp_path)})
    assert missing[0]["available"] is False
    (tmp_path / "works").mkdir()
    ok = workspace_roots({"git_repo_path": str(tmp_path)})
    assert ok[0]["available"] is True


def test_archive_paths_moves_rejected_files(tmp_path):
    from plugins.director.work_package import archive_paths, package_dir
    init = create_action("init_work_package")
    pack = asyncio.run(init.run({"repo_path": str(tmp_path), "title": "t"}))
    slug = pack.data["slug"]
    src = package_dir(str(tmp_path), slug) / "旁白.md"
    src.write_text("旧稿", encoding="utf-8")
    moved = archive_paths(str(tmp_path), slug, [f"works/{slug}/旁白.md"])
    assert moved
    assert not src.exists()
    assert (tmp_path / moved[0]).is_file()


def test_unknown_backend_does_not_fallback_to_lightai(tmp_path):
    init = create_action("init_work_package")
    pack = asyncio.run(init.run({"repo_path": str(tmp_path), "title": "t"}))
    slug = pack.data["slug"]
    gen = create_action("gen_video")
    res = asyncio.run(gen.run({
        "repo_path": str(tmp_path),
        "work_slug": slug,
        "prompt": "一只猫",
        "filename": "片段01.mp4",
        "backend": "runway",
    }))
    assert res.success is False
    assert "不会改打" in (res.error or "")
    assert "runway" in (res.error or "")
    assert not list((tmp_path / "works" / slug / "video").glob("*.mp4"))


def test_libtv_missing_cli_is_env_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("plugins.director.backends.which_binary", lambda _b: "")
    init = create_action("init_work_package")
    pack = asyncio.run(init.run({"repo_path": str(tmp_path), "title": "t"}))
    slug = pack.data["slug"]
    gen = create_action("gen_video")
    res = asyncio.run(gen.run({
        "repo_path": str(tmp_path),
        "work_slug": slug,
        "prompt": "一只猫",
        "filename": "片段01.mp4",
        "backend": "libtv",
    }))
    assert res.success is False
    assert res.data.get("env_missing") is True
    assert res.data.get("backend") == "libtv"
    assert isinstance(res.data.get("command"), str)
    assert not list((tmp_path / "works" / slug / "video").glob("*.mp4"))


def test_drama_cost_lock_rejects_1080p(tmp_path):
    init = create_action("init_work_package")
    pack = asyncio.run(init.run({"repo_path": str(tmp_path), "title": "t"}))
    slug = pack.data["slug"]
    gen = create_action("gen_video")
    res = asyncio.run(gen.run({
        "repo_path": str(tmp_path),
        "work_slug": slug,
        "prompt": "对打",
        "filename": "片段01.mp4",
        "backend": "lightai",
        "mode": "cinematic-drama",
        "resolution": "1080p",
    }))
    assert res.success is False
    assert res.data.get("cost_lock") is True
    assert "720p" in (res.error or "")


def test_dreamina_generate_when_cli_mocked(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "plugins.director.backends.which_binary",
        lambda b: "C:\\bin\\dreamina.exe" if b == "dreamina" else "",
    )

    async def fake_gen(**kw):
        dest = kw["dest"]
        dest.write_bytes(b"dreamina-mp4")
        return True, {
            "backend": "dreamina",
            "command": "dreamina text2video …",
            "task_id": "sub-1",
            "model": "seedance2.0fast",
        }, ""

    monkeypatch.setattr("plugins.director.cli_video.generate_dreamina", fake_gen)
    init = create_action("init_work_package")
    pack = asyncio.run(init.run({"repo_path": str(tmp_path), "title": "t"}))
    slug = pack.data["slug"]
    gen = create_action("gen_video")
    res = asyncio.run(gen.run({
        "repo_path": str(tmp_path),
        "work_slug": slug,
        "prompt": "一只猫",
        "filename": "片段01.mp4",
        "backend": "dreamina",
    }))
    assert res.success, res.error
    out = tmp_path / "works" / slug / "video" / "片段01.mp4"
    assert out.is_file() and out.read_bytes() == b"dreamina-mp4"
    assert res.data.get("backend") == "dreamina"
    assert isinstance(res.data.get("command"), str)


def _write_drama_package(root: Path, slug: str):
    pkg = root / "works" / slug
    (pkg / "video_brief.json").write_text(
        '{"mode":"cinematic-drama","backend":"lightai","resolution":"720p"}',
        encoding="utf-8",
    )
    (pkg / "片段表.md").write_text(
        "# 片段表\n\n"
        "片段01：开场走廊对峙，林舟拦住刺客。结束状态：主角拔剑，刺客后退半步。"
        "定稿对白：「站住。」出场角色：林舟、刺客。场景：夜巷。预计五镜。\n"
        "片段02：追逐转入内院，结束于门槛处对峙。对白：「你到底是谁。」\n",
        encoding="utf-8",
    )
    (pkg / "scene-bible.md").write_text(
        "# 场景资产表\n\n"
        "夜巷 V1：雨后青石路面，冷色路灯，两侧是低矮瓦房。"
        "空间从巷口到死胡同，出现于片段01–02。时间深夜，天气刚停雨。\n",
        encoding="utf-8",
    )
    (pkg / "character-bible.md").write_text(
        "# 角色资产表\n\n"
        "林舟：主角，黑衣青年，跨全部片段。服装 V1 黑袍。人物卡 refs/characters/lin.png。"
        "需要 16:9 三视图。刺客为一次性路人，不建资产。\n",
        encoding="utf-8",
    )
    (pkg / "voice-plan.md").write_text(
        "# 音色计划\n\n"
        "林舟使用已登记的沉静青年男声 WAV，听审通过，跨片段锁定。"
        "刺客无固定音色，仅在 Prompt 内描述。\n",
        encoding="utf-8",
    )
    (pkg / "continuity-matrix.md").write_text(
        "| 片段 | 可见人物 | 场景 | 武魂/道具 | 说话音色 | Prompt |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| 01 | 林舟 | 夜巷 | 长剑 | 林舟 | prompts/片段01.md |\n",
        encoding="utf-8",
    )
    (pkg / "refs" / "characters" / "lin.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 20)
    (pkg / "refs" / "scenes" / "alley.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 20)


def test_drama_visual_gate_blocks_incomplete_package(tmp_path):
    init = create_action("init_work_package")
    pack = asyncio.run(init.run({"repo_path": str(tmp_path), "title": "剧"}) )
    slug = pack.data["slug"]
    (tmp_path / "works" / slug / "video_brief.json").write_text(
        '{"mode":"cinematic-drama"}', encoding="utf-8",
    )
    gate = create_action("confirm_video_gate")
    res = asyncio.run(gate.run({
        "title": "确认视觉",
        "repo_path": str(tmp_path),
        "work_slug": slug,
        "gate": "visual",
        "mode": "cinematic-drama",
    }))
    assert res.success is False
    assert res.data.get("waiting_human") is False
    codes = {g["code"] for g in res.data.get("gaps") or []}
    assert "scene_bible" in codes or "continuity_matrix" in codes or "character_ref" in codes


def test_drama_visual_gate_passes_when_assets_ready(tmp_path):
    init = create_action("init_work_package")
    pack = asyncio.run(init.run({"repo_path": str(tmp_path), "title": "剧"}))
    slug = pack.data["slug"]
    _write_drama_package(tmp_path, slug)
    check = create_action("check_mode_assets")
    res = asyncio.run(check.run({
        "repo_path": str(tmp_path),
        "work_slug": slug,
        "gate": "visual",
    }))
    assert res.success, res.error
    gate = create_action("confirm_video_gate")
    ok = asyncio.run(gate.run({
        "title": "确认视觉",
        "repo_path": str(tmp_path),
        "work_slug": slug,
        "gate": "visual",
    }))
    assert ok.success
    assert ok.data.get("waiting_human") is True


def test_explainer_allows_no_character_ref(tmp_path):
    init = create_action("init_work_package")
    pack = asyncio.run(init.run({"repo_path": str(tmp_path), "title": "解说"}))
    slug = pack.data["slug"]
    pkg = tmp_path / "works" / slug
    (pkg / "video_brief.json").write_text(
        '{"mode":"animated-explainer"}', encoding="utf-8",
    )
    (pkg / "旁白.md").write_text(
        "拖延不是懒，是大脑在保护你免于被评判。"
        "十五秒口播要写满大约五十九到六十一个汉字，把概念讲完。\n",
        encoding="utf-8",
    )
    (pkg / "character-bible.md").write_text("# 角色\n\n无关键人物。\n", encoding="utf-8")
    check = create_action("check_mode_assets")
    res = asyncio.run(check.run({
        "repo_path": str(tmp_path),
        "work_slug": slug,
        "mode": "animated-explainer",
    }))
    assert res.success, res.error


def test_file_tree_skips_work_videos(tmp_path):
    from git_manager import GitManager
    works = tmp_path / "works" / "film" / "video"
    works.mkdir(parents=True)
    (works / "片段01.mp4").write_bytes(b"fake")
    (tmp_path / "works" / "film" / "旁白.md").write_text("hi", encoding="utf-8")
    gm = GitManager.__new__(GitManager)
    gm._repo_path = lambda _pid: tmp_path
    tree = asyncio.run(gm.get_file_tree("p"))
    blob = str(tree)
    assert "旁白.md" in blob
    assert "片段01.mp4" not in blob

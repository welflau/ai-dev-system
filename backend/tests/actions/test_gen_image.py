"""GenImageAction 的单测。

LightAI 的三个底层函数全部打桩 —— 真调一次要 30-300 秒且花钱。
但**参数校验、路径解析、失败分支、零字节检测**都是纯逻辑，必须真跑：
它们才是这个 Action 里会出 bug 的部分。

端到端真实出图留给任务 #15 的 demo 链（跑一次，确认 PNG 字节头）。

方案文档：docs/20261015_01_能力自描述与动态组装框架方案.md §3.7
"""
from pathlib import Path

import pytest

from actions.gen_image import GenImageAction
from skills.executable_loader import ExecutableSkill
from skills.runner import SkillRunner

PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(64))


@pytest.fixture
def fake_lightai(monkeypatch):
    """打桩 LightAI 三件套，返回一个可观测调用参数的 dict。

    注意 monkeypatch 的目标是 `image_processor` 模块的属性 —— GenImageAction
    在 `run()` 里才 `from image_processor import ...`，所以必须 patch 源模块
    而不是 actions.gen_image 的名字空间。
    """
    import image_processor as ip
    calls = {"create": [], "poll": [], "download": []}

    async def create(req):
        calls["create"].append(req)
        return "task-123"

    async def poll(task_id, engine):
        calls["poll"].append((task_id, engine))
        return "https://img.example/x.png"

    async def download(url, save_dir, filename):
        calls["download"].append((url, str(save_dir), filename))
        save_dir.mkdir(parents=True, exist_ok=True)
        p = save_dir / filename
        p.write_bytes(PNG)
        return str(p)

    monkeypatch.setattr(ip, "_create_lightai_task", create)
    monkeypatch.setattr(ip, "_poll_lightai_task", poll)
    monkeypatch.setattr(ip, "_download_image", download)
    return calls


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "LIGHTAI_API_KEY", "test-key", raising=False)


def ctx(tmp_path, **kw) -> dict:
    base = {
        "_skill_output_root": str(tmp_path / "out"),
        "prompt": "a cat on a roof, cinematic lighting",
        "filename": "cover.png",
    }
    base.update(kw)
    return base


# ════════════════════ tool schema ════════════════════

def test_schema_shape():
    schema = GenImageAction().tool_schema()
    assert schema["name"] == "gen_image"
    props = schema["input_schema"]["properties"]
    assert set(schema["input_schema"]["required"]) == {"prompt", "filename"}
    assert "16:9" in props["aspect_ratio"]["enum"]
    assert "2K" in props["image_size"]["enum"]


def test_description_warns_about_cost():
    """描述里必须写明「耗时长、别重复调」。

    LLM 看不到实现，只看 description。不写的话它会为同一张图反复调用 ——
    每次 30-300 秒且花钱，skill 的 budget 会被一张图耗光。
    """
    desc = GenImageAction().description
    assert "秒" in desc
    assert "不要" in desc or "重复" in desc


# ════════════════════ 成功路径 ════════════════════

def test_generates_and_saves(tmp_path, fake_lightai):
    import asyncio
    res = asyncio.run(GenImageAction().run(ctx(tmp_path)))
    assert res.success
    saved = tmp_path / "out" / "cover.png"
    assert saved.read_bytes() == PNG
    assert res.data["size_bytes"] == len(PNG)
    assert res.data["filename"] == "cover.png"


def test_passes_params_to_lightai(tmp_path, fake_lightai):
    import asyncio
    asyncio.run(GenImageAction().run(
        ctx(tmp_path, aspect_ratio="1:1", image_size="4K", engine="jimeng")
    ))
    req = fake_lightai["create"][0]
    assert req["aspect_ratio"] == "1:1"
    assert req["image_size"] == "4K"
    assert req["engine"] == "jimeng"
    assert fake_lightai["poll"][0] == ("task-123", "jimeng")


def test_subdir_routes_into_subfolder(tmp_path, fake_lightai):
    """`gen_image:images` → outputs.root/images/。

    配合 `globs: ["images/*.png"]` 让一次产出多张图归同一 kind。
    """
    import asyncio
    res = asyncio.run(GenImageAction(subdir="images").run(ctx(tmp_path)))
    assert res.success
    assert (tmp_path / "out" / "images" / "cover.png").is_file()


def test_invalid_enum_values_fall_back(tmp_path, fake_lightai):
    """非法 aspect_ratio / image_size 回退默认值，不报错。

    这些来自 LLM，enum 约束不是强制的（有些 provider 会忽略 schema）。
    回退比报错好 —— 一张比例不对的图远胜于整个 stage 失败。
    """
    import asyncio
    asyncio.run(GenImageAction().run(
        ctx(tmp_path, aspect_ratio="42:1", image_size="8K", engine="dall-e")
    ))
    req = fake_lightai["create"][0]
    assert req["aspect_ratio"] == "16:9"
    assert req["image_size"] == "2K"
    assert req["engine"] == "gemini"


# ════════════════════ 参数校验 ════════════════════

@pytest.mark.parametrize("bad", [
    "../../../etc/passwd.png",      # 路径穿越
    "sub/cover.png",                # 带目录
    "sub\\cover.png",               # Windows 分隔符
    "cover.exe",                    # 非图片扩展名
    "cover",                        # 无扩展名
    "c over.png",                   # 空格（可能被 shell 误解析）
    "",
])
def test_rejects_unsafe_filename(bad):
    """filename 来自 LLM，必须严格校验。

    **拒绝而不是悄悄改名**：改名会让 produces 声明的 glob 匹配不上，
    LLM 以为成功了但 _collect_outputs 回收到空 —— 整个 stage 判 partial
    却看不出原因。
    """
    assert GenImageAction()._safe_filename(bad) is None


def test_accepts_common_image_names():
    f = GenImageAction()._safe_filename
    for ok in ("cover.png", "shot_01.jpg", "a-b.webp", "X.JPEG"):
        assert f(ok) == ok


def test_empty_prompt_rejected(tmp_path, fake_lightai):
    import asyncio
    res = asyncio.run(GenImageAction().run(ctx(tmp_path, prompt="   ")))
    assert not res.success
    assert "prompt" in res.error
    assert fake_lightai["create"] == []      # 不该发起请求


def test_bad_filename_rejected_before_api_call(tmp_path, fake_lightai):
    """校验失败要在调 API 之前 —— 否则白花一次钱。"""
    import asyncio
    res = asyncio.run(GenImageAction().run(ctx(tmp_path, filename="x.exe")))
    assert not res.success
    assert fake_lightai["create"] == []


def test_missing_output_root_rejected(tmp_path, fake_lightai):
    """没有 outputs.root 时拒绝 —— 不该随便往仓库里写二进制文件。"""
    import asyncio
    c = ctx(tmp_path)
    del c["_skill_output_root"]
    res = asyncio.run(GenImageAction().run(c))
    assert not res.success
    assert "产出目录" in res.error
    assert fake_lightai["create"] == []


def test_missing_api_key_reports_config_error(tmp_path, fake_lightai, monkeypatch):
    """缺 API key 要明说，而不是让 LightAI 返回 401 后变成「生成失败」。"""
    import asyncio
    from config import settings
    monkeypatch.setattr(settings, "LIGHTAI_API_KEY", "", raising=False)
    res = asyncio.run(GenImageAction().run(ctx(tmp_path)))
    assert not res.success
    assert "LIGHTAI_API_KEY" in res.error
    assert fake_lightai["create"] == []


# ════════════════════ 失败分支 ════════════════════

def test_task_creation_failure(tmp_path, monkeypatch):
    import asyncio
    import image_processor as ip

    async def no_task(req):
        return None
    monkeypatch.setattr(ip, "_create_lightai_task", no_task)

    res = asyncio.run(GenImageAction().run(ctx(tmp_path)))
    assert not res.success
    assert "创建失败" in res.error


def test_poll_returns_nothing(tmp_path, monkeypatch):
    """超时或被内容策略拒绝 —— _poll_lightai_task 两种都返 None。"""
    import asyncio
    import image_processor as ip

    async def create(req):
        return "t1"

    async def no_url(task_id, engine):
        return None
    monkeypatch.setattr(ip, "_create_lightai_task", create)
    monkeypatch.setattr(ip, "_poll_lightai_task", no_url)

    res = asyncio.run(GenImageAction().run(ctx(tmp_path)))
    assert not res.success
    assert "未产出图片" in res.error


def test_download_failure(tmp_path, monkeypatch):
    import asyncio
    import image_processor as ip

    async def create(req):
        return "t1"

    async def poll(t, e):
        return "https://img/x.png"

    async def no_download(url, save_dir, filename):
        return None
    monkeypatch.setattr(ip, "_create_lightai_task", create)
    monkeypatch.setattr(ip, "_poll_lightai_task", poll)
    monkeypatch.setattr(ip, "_download_image", no_download)

    res = asyncio.run(GenImageAction().run(ctx(tmp_path)))
    assert not res.success
    assert "下载失败" in res.error


def test_zero_byte_download_is_failure(tmp_path, monkeypatch):
    """下载成功但零字节 → 判失败。

    不拦的话 `_collect_outputs` 会把空文件当成功产出回收，下游 consumes
    拿到一张坏图却显示「产出齐全」。
    """
    import asyncio
    import image_processor as ip

    async def create(req):
        return "t1"

    async def poll(t, e):
        return "https://img/x.png"

    async def empty(url, save_dir, filename):
        save_dir.mkdir(parents=True, exist_ok=True)
        p = save_dir / filename
        p.write_bytes(b"")
        return str(p)
    monkeypatch.setattr(ip, "_create_lightai_task", create)
    monkeypatch.setattr(ip, "_poll_lightai_task", poll)
    monkeypatch.setattr(ip, "_download_image", empty)

    res = asyncio.run(GenImageAction().run(ctx(tmp_path)))
    assert not res.success
    assert "空文件" in res.error


# ════════════════════ builtin 池注册 ════════════════════

def _skill(builtin_tools, globs=()) -> ExecutableSkill:
    return ExecutableSkill(
        skill_id="x", name="x", description="", body="",
        source_path=Path("SKILL.md"),
        builtin_tools=list(builtin_tools),
        outputs={"root": "out", "globs": list(globs)},
    )


def test_registered_in_builtin_pool():
    actions = SkillRunner(_skill(["gen_image"]))._build_actions()
    assert "gen_image" in actions
    assert actions["gen_image"]._subdir == ""


def test_subdir_syntax_parsed():
    actions = SkillRunner(_skill(["gen_image:images"]))._build_actions()
    assert actions["gen_image"]._subdir == "images"


def test_coexists_with_other_builtins():
    actions = SkillRunner(
        _skill(["write_file", "read_file", "gen_image"])
    )._build_actions()
    assert set(actions) == {"write_file", "read_file", "gen_image"}


def test_not_registered_when_undeclared():
    """没声明就不该有这个工具 —— 否则所有 skill 都能生图，预算失控。

    ⚠️ **不能只用 `["write_file"]` 做输入**：它被 `_build_actions` 的第一个
    `if` 捕获，根本进不到 gen_image 那条 `elif`。实测把分支条件改成
    `elif True:` 后测试照样绿（假绿）—— 必须给一个落到 elif 链末尾的值。

    `mcp__foo__bar` 正是这样一个真实存在的输入：它在 executor 层处理，
    `_build_actions` 里应当一个 Action 都不建。
    """
    # 只有 write_file：被第一个 if 接走，测不出 elif 的条件
    assert "gen_image" not in SkillRunner(_skill(["write_file"]))._build_actions()

    # 落到 elif 链末尾的声明 —— 这才能验证 gen_image 的条件判断
    for undeclared in (["mcp__openspec__validate"], ["read_file"], []):
        actions = SkillRunner(_skill(undeclared))._build_actions()
        assert "gen_image" not in actions, (
            f"builtin_tools={undeclared} 却注册了 gen_image —— "
            f"所有 skill 都能生图会让预算失控"
        )


# ════════════════ 与产物回收的衔接 ════════════════

def test_generated_image_is_collected_as_binary(tmp_path, fake_lightai):
    """生成的图能被 _collect_outputs 回收，且标记为 binary。

    这是 gen_image 接入产物总线的关键衔接点：图落在 outputs.root 下 →
    glob 命中 → ArtifactOut.is_binary=True → text_outputs 跳过它 →
    SkillAgent 按 kind 登记进 artifacts 表。
    """
    import asyncio

    skill = _skill(["gen_image:images"], globs=["images/*.png"])
    runner = SkillRunner(skill)
    out_root = tmp_path / "out"

    asyncio.run(GenImageAction(subdir="images").run(ctx(tmp_path)))

    outs = runner._collect_outputs(
        {"sop_config": {"_produces": [
            {"kind": "cover_image", "glob": "images/*.png"}
        ]}},
        out_root,
    )
    assert len(outs) == 1
    assert outs[0].kind == "cover_image"
    assert outs[0].is_binary is True
    assert outs[0].mime == "image/png"
    assert Path(outs[0].abs_path).read_bytes() == PNG

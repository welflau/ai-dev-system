"""验证借鉴落地第 1、2 项（临时验证脚本，跑完可删）"""
import asyncio
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

BACKEND = Path(__file__).parent
sys.path.insert(0, str(BACKEND))


async def test_1_path_guard_rejected():
    """第 1 项：越权路径（白名单外）应被拦截"""
    from ue_mcp_server import _ue_import_asset_impl

    mock_db = MagicMock()
    mock_db.fetch_one = AsyncMock(return_value={
        "file_path": "C:/Windows/System32/evil.png",
    })

    with patch("database.db", mock_db), \
         patch("config.settings.ART_ASSETS_LOCAL_PATH", ""):
        result = await _ue_import_asset_impl(asset_id="TEST-1", project_id="p1")

    assert result["success"] is False, f"应拒绝越权路径，实际: {result}"
    assert "越出" in result.get("message", ""), f"错误信息应含'越出'，实际: {result}"
    print("✅ 第 1 项（越权拦截）通过:", result["message"])


async def test_1_legal_path_allowed():
    """第 1 项：资产库内的合法路径不应被误拦"""
    from ue_mcp_server import _ue_import_asset_impl

    with tempfile.TemporaryDirectory() as art_root:
        legal_file = Path(art_root) / "photos" / "test.png"
        legal_file.parent.mkdir(parents=True, exist_ok=True)
        legal_file.write_bytes(b"\x89PNG")

        mock_db = MagicMock()
        mock_db.fetch_one = AsyncMock(return_value={"file_path": "photos/test.png"})
        mock_db.execute = AsyncMock(return_value=None)

        with patch("database.db", mock_db), \
             patch("config.settings.ART_ASSETS_LOCAL_PATH", art_root), \
             patch("ue_mcp_server._ue_run", AsyncMock(return_value={
                 "success": True,
                 "stdout": "IMPORT_OK=True\nUE_PATH=/Game/Textures/AI/T_TEST1",
                 "result": "",
             })):
            result = await _ue_import_asset_impl(asset_id="TEST-1", project_id="p1")

    assert result["success"] is True, f"合法路径不应被误拦，实际: {result}"
    print("✅ 第 1 项（合法路径放行）通过: ue_path =", result.get("ue_path"))


async def test_2_aigc_dispatched():
    """第 2 项：allow_aigc=True 时未命中本地库应投递 AIGC"""
    from plugins.content.actions.generate_assets import GenerateAssetsAction

    action = GenerateAssetsAction()
    action._search_library = AsyncMock(return_value=None)

    item = {"id": "hero_bg", "type": "illustration", "description": "forest background"}

    with patch("image_processor.request_image", AsyncMock(return_value="[IMG_PENDING:IMG-xxx]")) as mock_req:
        kind, payload = await action._resolve_one(
            item, allow_placeholder=True, docs_prefix="docs/",
            project_id="p1", ticket_id="t1", allow_aigc=True,
        )

    assert kind == "placeholder", f"应返回 placeholder，实际: {kind}"
    assert payload.get("aigc_tag") == "[IMG_PENDING:IMG-xxx]", f"应有 aigc_tag，实际: {payload}"
    assert mock_req.called, "request_image 应被调用"
    assert mock_req.await_args.kwargs.get("requester") == "ArtAgent", \
        f"requester 应为 ArtAgent，实际: {mock_req.await_args}"
    print("✅ 第 2 项（AIGC 投递）通过: aigc_tag =", payload["aigc_tag"])


async def test_2_aigc_off():
    """第 2 项：allow_aigc=False 时不投递 AIGC"""
    from plugins.content.actions.generate_assets import GenerateAssetsAction

    action = GenerateAssetsAction()
    action._search_library = AsyncMock(return_value=None)

    item = {"id": "hero_bg", "type": "illustration", "description": "forest background"}

    with patch("image_processor.request_image", AsyncMock(return_value="[IMG_PENDING:IMG-xxx]")) as mock_req:
        kind, payload = await action._resolve_one(
            item, allow_placeholder=True, docs_prefix="docs/",
            project_id="p1", ticket_id="t1", allow_aigc=False,
        )

    assert kind == "placeholder", f"应返回 placeholder，实际: {kind}"
    assert not payload.get("aigc_tag"), f"allow_aigc=False 不应有 aigc_tag，实际: {payload}"
    assert not mock_req.called, "request_image 不应被调用"
    print("✅ 第 2 项（AIGC 关闭不投递）通过")


async def test_2_sourced_no_aigc():
    """第 2 项：命中本地库时不投递 AIGC（优先级：搜库 > AIGC）"""
    from plugins.content.actions.generate_assets import GenerateAssetsAction

    action = GenerateAssetsAction()
    action._search_library = AsyncMock(return_value={
        "id": "AST-1", "name": "hero_bg", "file_path": "2d/hero_bg.png", "_score": 0.9,
    })

    item = {"id": "hero_bg", "type": "illustration", "description": "forest background"}

    with patch("image_processor.request_image", AsyncMock(return_value="[IMG_PENDING:IMG-xxx]")) as mock_req:
        kind, payload = await action._resolve_one(
            item, allow_placeholder=True, docs_prefix="docs/",
            project_id="p1", ticket_id="t1", allow_aigc=True,
        )

    assert kind == "sourced", f"命中库应返回 sourced，实际: {kind}"
    assert not mock_req.called, "命中库时不应投递 AIGC（搜库优先）"
    print("✅ 第 2 项（命中库不投递 AIGC）通过: status =", payload.get("status"))


async def main():
    await test_1_path_guard_rejected()
    await test_1_legal_path_allowed()
    await test_2_aigc_dispatched()
    await test_2_aigc_off()
    await test_2_sourced_no_aigc()
    print("\n🎉 全部 5 项验证通过")


if __name__ == "__main__":
    asyncio.run(main())

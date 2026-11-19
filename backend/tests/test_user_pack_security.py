"""2ec1fd3 用户级 ConfigPack 端点安全回归（评审意见 §11.4 / §12）。

覆盖真实生产代码路径（守卫、白名单、端点），不复制逻辑：
1. 端点默认关闭（USER_PACK_INSTALL_ENABLED=false）→ 403
2. 开启后仍仅本机可访问，非本机 → 403
3. pack_name 白名单：路径穿越 / 绝对路径 / 分隔符 → 400（或路由层 404）
4. 开启 + 本机：读取可用，且真实 install 端到端成功（临时 DB / 临时 home）
5. pack_installer.is_valid_pack_name 与直接调用 install_pack 的边界

隔离：TestClient 用 client=("127.0.0.1", port) 模拟本机；Path.home() 指到
tmp_path；db 用最小 async 替身。全程不碰真实用户主目录、不连实库。
关联：dev-notes/2026-11-19_01_... §11 / §12
"""
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import pack_installer as pi
from config import settings


# ── pack_name 白名单（单元）────────────────────────────────────────────────
@pytest.mark.parametrize("bad", [
    "", "..", "../etc", "../../backend", "a/b", r"a\b", "/etc", "C:/Windows",
    "a b", "a;b", "a'b", 'a"b', ".hidden", "a" * 65, None, 123,
])
def test_invalid_pack_name_rejected(bad):
    assert pi.is_valid_pack_name(bad) is False


@pytest.mark.parametrize("good", [
    "git-workflow", "ai-workflow", "ue5-prod-skills", "a", "A1_b-c.d", "123",
])
def test_valid_pack_name_accepted(good):
    assert pi.is_valid_pack_name(good) is True


def test_install_pack_rejects_traversal_even_directly():
    """绕过 API 直接调 install_pack 也要被白名单挡住（防御纵深）。"""
    for bad in ("../etc", "C:/Windows", "a/b"):
        r = pi.install_pack(bad, project_path="", project_ctx={}, scope="user")
        assert r["success"] is False, bad
        assert "非法 Pack 名称" in "; ".join(r["errors"]), bad


# ── 端点安全（TestClient 端到端，跑真实守卫）──────────────────────────────
class _FakeDB:
    """最小 async DB 替身，避免连真实 ai_dev_system_new.db。"""

    def __init__(self):
        self.rows = []

    async def fetch_all(self, sql, params=()):
        return list(self.rows)

    async def fetch_one(self, sql, params=()):
        return None

    async def insert(self, table, data):
        self.rows.append(dict(data))

    async def update(self, table, data, where, params=()):
        pass

    async def delete(self, table, where, params=()):
        pass


@pytest.fixture
def app_and_db(monkeypatch, tmp_path):
    """构造只挂 projects router 的最小 app，替换 db / home / 开关默认值。

    只替换外部依赖，不碰 _require_user_pack_access —— 测的就是生产守卫。
    """
    import api.projects as P

    db = _FakeDB()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(P, "db", db)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.setattr(settings, "USER_PACK_INSTALL_ENABLED", False)

    app = FastAPI()
    app.include_router(P.router)
    return app, db, home


def test_switch_default_off_returns_403(app_and_db):
    """默认 USER_PACK_INSTALL_ENABLED=false → 4 个用户级端点全部 403。"""
    app, _, _ = app_and_db
    with TestClient(app, client=("127.0.0.1", 51000)) as c:
        for method, path in (("get", "/api/projects/packs/user"),
                             ("get", "/api/projects/packs/user/available"),
                             ("post", "/api/projects/packs/user/git-workflow/install"),
                             ("delete", "/api/projects/packs/user/git-workflow")):
            r = getattr(c, method)(path)
            assert r.status_code == 403, (method, path, r.status_code, r.text)
            assert "未启用" in r.json()["detail"]


def test_non_local_host_rejected_even_when_enabled(monkeypatch, app_and_db):
    """开关开启但来源 IP 非本机 → 403（服务 bind 0.0.0.0 的关键防护）。"""
    monkeypatch.setattr(settings, "USER_PACK_INSTALL_ENABLED", True)
    app, _, _ = app_and_db
    with TestClient(app, client=("203.0.113.9", 51000)) as c:
        for method, path in (("get", "/api/projects/packs/user"),
                             ("post", "/api/projects/packs/user/git-workflow/install")):
            r = getattr(c, method)(path)
            assert r.status_code == 403, (method, path, r.status_code, r.text)
            assert "仅允许本机" in r.json()["detail"]


def test_local_host_allowed_when_enabled(monkeypatch, app_and_db):
    """开关开启 + 本机 → 端点可用；并跑通一次真实 install 端到端。"""
    monkeypatch.setattr(settings, "USER_PACK_INSTALL_ENABLED", True)
    app, db, home = app_and_db
    with TestClient(app, client=("127.0.0.1", 51000)) as c:
        r = c.get("/api/projects/packs/user")
        assert r.status_code == 200, r.text
        assert r.json()["packs"] == []
        assert r.json()["home"] == str(home)

        r2 = c.get("/api/projects/packs/user/available")
        assert r2.status_code == 200, r2.text
        assert len(r2.json()["packs"]) >= 13

        # 真实安装：写临时 home（4 个 CLI 顶层目录），并落一条 user_packs 记录
        r3 = c.post("/api/projects/packs/user/git-workflow/install")
        assert r3.status_code == 200, r3.text
        assert r3.json()["success"] is True
        assert set(r3.json()["installed_targets"]) == set(pi.ALL_CLI_TARGETS)
        assert len(db.rows) == 1 and db.rows[0]["pack_name"] == "git-workflow"
        written = [p for p in home.rglob("*") if p.is_file()]
        assert written, "用户级安装应向临时 home 写入文件"
        for cli in pi.ALL_CLI_TARGETS:
            root = home / f".{cli}"
            assert root.is_dir(), f"应有 .{cli}/ 目录"
            assert any(p.is_file() for p in root.rglob("*")), f".{cli}/ 下应有文件"

        # 重装走 upsert 分支，不新增第二条记录
        r4 = c.post("/api/projects/packs/user/git-workflow/install")
        assert r4.status_code == 200, r4.text

        # DELETE 只删记录，不删用户目录文件
        r5 = c.delete("/api/projects/packs/user/git-workflow")
        assert r5.status_code == 200, r5.text
        assert [p for p in home.rglob("*") if p.is_file()], "DELETE 不应删除用户目录下的文件"
        assert "记录已移除" in r5.json()["note"]


def test_pack_name_validation_blocks_traversal(monkeypatch, app_and_db):
    """本机 + 开关开启时，非法 pack_name 不会落到文件系统。

    能进入端点的非法名 → 400 白名单拒绝；含 URL 编码斜杠的会在路由层
    直接 404（同样不会落盘，也算安全）。两类都不允许 2xx。
    """
    monkeypatch.setattr(settings, "USER_PACK_INSTALL_ENABLED", True)
    app, db, _ = app_and_db
    with TestClient(app, client=("127.0.0.1", 51000)) as c:
        for bad in ("%2e%2e", "-bad", ".hidden", "a%20b", "a%3Bb", "a%27b", "C%3AWindows"):
            r = c.post(f"/api/projects/packs/user/{bad}/install")
            assert r.status_code == 400, (bad, r.status_code, r.text)
            assert "非法 Pack 名称" in r.json()["detail"]
        for bad in ("..%2fetc", "a%2fb"):
            r = c.post(f"/api/projects/packs/user/{bad}/install")
            assert r.status_code == 404, (bad, r.status_code, r.text)
        assert db.rows == [], "非法名称绝不能写入 user_packs 记录"

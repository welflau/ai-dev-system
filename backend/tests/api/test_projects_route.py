"""项目路由注册回归：`POST /api/projects` 必须落在 `create_project` 上。

历史问题：`@router.post("")` 曾被误挂在私有辅助函数 `_auto_init_ads_dir` 上，
导致新建 / 导入项目的请求体被当成该函数的 query 参数解析，接口直接 422。
这里只检查路由表，不起服务、不连数据库。
"""
from fastapi.routing import APIRoute

from api import projects


def _api_routes():
    return [r for r in projects.router.routes if isinstance(r, APIRoute)]


def test_post_projects_is_bound_to_create_project():
    matches = [
        r for r in _api_routes()
        if r.path == "/api/projects" and "POST" in r.methods
    ]
    assert len(matches) == 1, [r.endpoint.__name__ for r in matches]
    assert matches[0].endpoint is projects.create_project


def test_no_private_helper_is_registered_as_endpoint():
    private = [
        (sorted(r.methods), r.path, r.endpoint.__name__)
        for r in _api_routes()
        if r.endpoint.__name__.startswith("_")
    ]
    assert private == []


def test_no_duplicate_method_and_path():
    seen = {}
    dup = []
    for r in _api_routes():
        for m in r.methods:
            key = (m, r.path)
            if key in seen:
                dup.append((m, r.path, seen[key], r.endpoint.__name__))
            seen[key] = r.endpoint.__name__
    assert dup == []

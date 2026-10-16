"""测试级 fixture。

## 为什么需要 `isolate_builtin_skills`

`discover_workflow_skills` 会扫 `backend/skills/executable_skills/`。v0.20 之前
那里只有 openspec-*（没有 x-workflow），所以「内置目录零 workflow skill」
成了一堆测试的**隐含前提** —— 它们直接断言 `discover_workflow_skills() == []`
或「compose 出来只有 fragment stage」。

加了 demo-outline / demo-draft / demo-cover 之后这个前提破了，14 个测试红。
红得有道理：**内置目录的内容不该是测试的隐含依赖**。往里加一个 skill 就让
不相关的测试失败，说明隔离没做够。

所以提供一个 autouse fixture 把 `_BUILTIN_ROOT` 指到空目录。需要真实内置
skill 的测试（如「openspec-propose 仍能加载」）显式用 `real_builtin_skills`
覆盖回去。
"""
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_builtin_skills(request, tmp_path_factory, monkeypatch):
    """默认把内置 skill 目录指到空目录，除非测试显式声明要真实的。

    用 `@pytest.mark.real_builtin_skills` 标记可跳过隔离。
    """
    if request.node.get_closest_marker("real_builtin_skills"):
        yield
        return

    import skills.executable_loader as loader
    empty = tmp_path_factory.mktemp("empty_builtin_skills")
    monkeypatch.setattr(loader, "_BUILTIN_ROOT", empty)
    yield


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "real_builtin_skills: 不隔离 backend/skills/executable_skills/，"
        "用于验证真实内置 skill（openspec-* / demo-*）",
    )

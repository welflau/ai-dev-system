"""cloud_video 异常类拆到叶子模块后的兼容性回归。

拆环时把 `CloudVideoUnavailable` / `CloudVideoError` 从 `client` 挪到 `errors`。
旧的 import 路径必须继续可用，而且拿到的是同一个类对象，
否则 `except CloudVideoError` 会漏接从另一条路径抛出来的异常。
"""
import ast
from pathlib import Path

import cloud_video
from cloud_video import client, errors, lightai, queue


def test_exception_classes_are_the_same_object_on_every_path():
    assert cloud_video.CloudVideoError is errors.CloudVideoError
    assert client.CloudVideoError is errors.CloudVideoError
    assert lightai.CloudVideoError is errors.CloudVideoError
    assert cloud_video.CloudVideoUnavailable is errors.CloudVideoUnavailable
    assert client.CloudVideoUnavailable is errors.CloudVideoUnavailable
    assert queue.CloudVideoUnavailable is errors.CloudVideoUnavailable


def test_exception_classes_stay_runtime_errors():
    assert issubclass(errors.CloudVideoError, RuntimeError)
    assert issubclass(errors.CloudVideoUnavailable, RuntimeError)


def test_errors_module_has_no_project_imports():
    """errors 必须保持叶子：只许 import 标准库的 __future__。"""
    tree = ast.parse(Path(errors.__file__).read_text(encoding="utf-8"))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    assert imported == ["__future__"]


def test_queue_and_lightai_do_not_import_client():
    """queue / lightai 反向 import client 就会把环接回去。"""
    for mod in (queue, lightai):
        tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module != "cloud_video.client", mod.__name__
            elif isinstance(node, ast.Import):
                assert all(a.name != "cloud_video.client" for a in node.names), mod.__name__

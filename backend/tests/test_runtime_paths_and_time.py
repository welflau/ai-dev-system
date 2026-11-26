"""弃用 API 与写死的开发机路径回归。"""
import ast
import re
import warnings
from datetime import datetime
from pathlib import Path

from actions import diagnose_ticket

BACKEND = Path(__file__).resolve().parents[1]


def chat_sources():
    yield from (BACKEND / "api" / "chat").rglob("*.py")
    yield BACKEND / "agents" / "chat_assistant.py"


def test_utc_now_z_keeps_the_old_string_format():
    value = diagnose_ticket._utc_now_z()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z", value), value
    assert "+00:00" not in value
    parsed = datetime.fromisoformat(value[:-1])
    assert parsed.tzinfo is None


def test_utc_now_z_does_not_emit_deprecation_warning():
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        diagnose_ticket._utc_now_z()


def test_diagnose_ticket_no_longer_calls_utcnow():
    tree = ast.parse(Path(diagnose_ticket.__file__).read_text(encoding="utf-8"))
    calls = [
        node.lineno for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == "utcnow"
    ]
    assert calls == []


def test_chat_modules_compile_without_syntax_warning():
    """api/chat.py 的提示词里曾写死开发机的 Windows 绝对路径，其中的反斜杠加 A 是非法转义。"""
    for path in chat_sources():
        source = path.read_text(encoding="utf-8")
        with warnings.catch_warnings():
            warnings.simplefilter("error", SyntaxWarning)
            compile(source, str(path), "exec")


def test_prompts_do_not_embed_the_dev_machine_install_path():
    pattern = re.compile(r"[A-Za-z]:[\\/]+A_Works[\\/]+ai-dev-system[\\/]+backend", re.IGNORECASE)
    for path in chat_sources():
        source = path.read_text(encoding="utf-8")
        assert pattern.search(source) is None, path

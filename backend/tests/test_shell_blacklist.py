"""ShellAction / GenericCLIAction 共用的危险命令黑名单。

历史问题：旧正则把所有分支包在 `\b( ... )\b` 里，结尾的 `\b` 让 `rm -rf /`、
`format c:` 这类最典型的写法反而匹配不上；PowerShell 写法（Windows 上的实际执行
环境）则完全没有覆盖。这里把「必须拦」和「不能误伤」两张表都固定下来。

黑名单只是兜底，不是安全边界，所以这里不追求穷举绕过手法。
"""
import asyncio

import pytest

from actions.chat.shell_exec import ShellAction, _DANGEROUS_PATTERNS

MUST_BLOCK = [
    # bash
    "rm -rf /",
    "rm -fr x",
    "rm -r dir",
    "rm -f a.txt",
    "rm --recursive x",
    "rm x -rf",
    "sudo rm -Rf /tmp/x",
    "echo hi; rm -rf .",
    # PowerShell：Remove-Item 及其别名，-Recurse / -Force 及缩写
    "Remove-Item -Recurse -Force .",
    "Remove-Item C:\\Users -Recurse",
    "remove-item . -r -fo",
    "ri -r -fo build",
    "rm -Recurse build",
    "del a.txt -Force",
    "rmdir build -Recurse",
    "Get-ChildItem . | Remove-Item -Recurse -Force",
    # cmd
    "del /f a.txt",
    "del /s /q .",
    "DEL /F /Q *.log",
    "rd /s /q build",
    "rmdir /S build",
    'cmd /c "rd /s /q build"',
    # 磁盘
    "format c:",
    "format c: /q",
    "FORMAT D:",
    "Format-Volume -DriveLetter D",
    "Clear-Disk -Number 1",
    "diskpart /s x.txt",
    "mkfs.ext4 /dev/sda1",
    "dd if=/dev/zero of=/dev/sda",
    # SQL
    'sqlite3 a.db "DROP TABLE users"',
    "psql -c 'truncate table t'",
    "drop database prod",
    # 关机 / 重启
    "shutdown /s /t 0",
    "shutdown -h now",
    "reboot",
    "poweroff",
    "Stop-Computer -Force",
    "Restart-Computer",
    # 编码命令
    "powershell -enc SQBFAFgA",
    "pwsh -EncodedCommand SQBFAFgA",
    "powershell.exe -NoProfile -e SQBFAFgA",
]

MUST_ALLOW = [
    "git log --oneline -10",
    "git status",
    "git rm --cached a.txt",
    "git remote rm origin",
    "git diff -- src/rd.py",
    "python -m pytest tests/",
    "pip install -r requirements.txt",
    "npm run format",
    "npm rm lodash",
    "npm run graceful-shutdown",
    "pytest -k test_shutdown-handler",
    "cargo fmt",
    "echo reformat data",
    "cat format.md",
    "node informat.js c:",
    "rm a.txt",
    "Remove-Item a.txt",
    "ls -r",
    "dir /s",
    "Get-ChildItem -Recurse -Force",
    "Get-Content delete.log",
    "docker run --rm -f x img",
    "grep -r drop_table .",
    "echo rm && ls -rf",
    "powershell -ExecutionPolicy Bypass -File a.ps1",
]


@pytest.mark.parametrize("command", MUST_BLOCK)
def test_dangerous_command_is_blocked(command):
    assert _DANGEROUS_PATTERNS.search(command), command


@pytest.mark.parametrize("command", MUST_ALLOW)
def test_ordinary_command_is_not_blocked(command):
    hit = _DANGEROUS_PATTERNS.search(command)
    assert hit is None, (command, hit.group(0) if hit else None)


def test_shell_action_rejects_before_touching_project_or_subprocess():
    """黑名单在查项目目录、起子进程之前生效：不给 project_id 也应直接拒绝。"""
    result = asyncio.run(ShellAction().run({"command": "Remove-Item -Recurse -Force ."}))
    assert result.success is False
    assert "危险操作" in (result.error or "")

"""外科测试：codebuddy 子进程能否真正调用 skill_io MCP 工具。

不走 SkillRunner/QueryEngine，直接复刻 _call_cli_stream 会拼出的命令：
  codebuddy --print --output-format stream-json --include-partial-messages -y
            --model <model> --mcp-config <tmp.json>
prompt 走 stdin，让它调 mcp__skill_io__write_output 写一个文件。

验的是「嵌套 CLI 会不会真去选 MCP 工具」这个唯一未知数。
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

BACKEND = Path(__file__).parent
PYTHON = sys.executable
MODEL = os.environ.get("LLM_CLI_MODEL", "deepseek-v4-pro-ioa")


def main():
    out_root = Path(tempfile.mkdtemp(prefix="skillio_surgical_"))
    print(f"产出目录: {out_root}")

    mcp_cfg = {
        "mcpServers": {
            "skill_io": {
                "command": PYTHON,
                "args": [str(BACKEND / "skills" / "skill_io_mcp_server.py")],
                "env": {
                    "SKILL_OUTPUT_ROOT": str(out_root),
                    "SKILL_REPO": str(out_root.parent),
                    "SKILL_BACKEND_DIR": str(BACKEND),
                },
            }
        }
    }
    cfg_file = out_root.parent / f"_mcpcfg_{int(time.time())}.json"
    cfg_file.write_text(json.dumps(mcp_cfg, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    # Windows 下裸 `codebuddy` 是 POSIX 脚本，CreateProcess 起不来，
    # 必须经 cmd /c 解析到 codebuddy.cmd（与 llm_client._resolve_cmd 同逻辑）
    import shutil
    resolved = shutil.which("codebuddy")
    if sys.platform == "win32" and resolved and (
            resolved.lower().endswith(".cmd") or resolved.lower().endswith(".bat")):
        cli_prefix = ["cmd", "/c", "codebuddy"]
    else:
        cli_prefix = ["codebuddy"]
    cmd = cli_prefix + [
        "--print", "--output-format", "stream-json",
        "--include-partial-messages", "-y", "--model", MODEL,
        "--mcp-config", str(cfg_file),
    ]
    prompt = (
        "请用 MCP 工具 mcp__skill_io__write_output 写一个文件：\n"
        "filename=outline.md，content=以下三行：\n"
        "# 外科测试\n\n## 章节\n1. 背景 — 要点A / 要点B\n"
        "写完后再回复一句 DONE。不要用原生 Write，只用这个 MCP 工具。"
    )
    env = os.environ.copy()
    env["CODEBUDDY_API_KEY_DISABLED"] = "1"

    print(f"命令: {' '.join(cmd)}")
    print(f"prompt 长度: {len(prompt)} chars")
    print("--- 开始执行 ---")

    t0 = time.time()
    proc = subprocess.run(
        cmd, input=prompt.encode("utf-8"), stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, env=env, timeout=240,
    )
    dt = time.time() - t0

    stdout = proc.stdout.decode("utf-8", errors="replace")
    stderr = proc.stderr.decode("utf-8", errors="replace")

    print(f"\n=== 退出码 {proc.returncode}，耗时 {dt:.0f}s ===")
    print(f"--- stderr (末尾 1200) ---\n{stderr[-1200:]}")
    # 从 stream-json 里抽取文本
    texts = []
    for line in stdout.splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = obj.get("type", "")
        if t == "stream_event":
            ev = obj.get("event", {})
            d = ev.get("delta", {})
            if d.get("type") == "text_delta" and d.get("text"):
                texts.append(d["text"])
        elif t == "result":
            r = obj.get("result", "") or ""
            if isinstance(r, str) and r:
                texts.append(r)
    combined = "".join(texts)
    print(f"--- 抽取的文本 ({len(combined)} chars) ---\n{combined[-1500:]}")

    # 结果判定
    files = list(out_root.glob("*"))
    print(f"\n=== 产出目录内容 ===")
    for f in sorted(files):
        if f.is_file():
            print(f"  {f.name} ({f.stat().st_size} bytes)")
            if f.name == "outline.md":
                print("    --- 内容 ---")
                print(f.read_text(encoding="utf-8")[:500])
    outline = out_root / "outline.md"
    ok = outline.is_file() and outline.stat().st_size > 0
    print(f"\n{'✅ 成功' if ok else '❌ 失败'}: outline.md {'已落盘' if ok else '未落盘'}")
    print(f"(产出目录保留在 {out_root}，可手工检查)")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

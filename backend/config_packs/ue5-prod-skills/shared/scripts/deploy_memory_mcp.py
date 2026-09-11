"""
部署 MCP Memory Server 到 UE 项目

用法:
  python deploy_memory_mcp.py [--project-path <路径>] [--ads-tools <路径>]

功能:
  1. 找到 backend/tools/memory_mcp/ 源目录
  2. 复制到项目的 .codebuddy/mcp/memory/
  3. 创建虚拟环境并安装依赖
  4. 注册 MCP 服务器到 .codebuddy/mcp.json
"""
import argparse
import json
import shutil
import subprocess
import sys
import venv
from pathlib import Path


def find_ads_root(script_dir: Path) -> Path | None:
    """从脚本位置向上查找 ADS 根目录 (包含 backend/tools/)。"""
    candidates = [
        # ConfigPack 安装后: .codebuddy/packs/ue5-prod-skills/scripts/ → ADS root
        script_dir.parent.parent.parent.parent.parent,
        # 直接从源码运行时: backend/config_packs/ue5-prod-skills/shared/scripts/ → ADS root
        script_dir.parent.parent.parent.parent.parent.parent,
    ]
    for candidate in candidates:
        if (candidate / "backend" / "tools" / "memory_mcp").exists():
            return candidate
    return None


def find_ads_tools(script_dir: Path, explicit_path: str | None) -> Path:
    """定位 memory_mcp 源码目录。"""
    if explicit_path:
        p = Path(explicit_path).resolve()
        if p.exists():
            return p
        print(f"[ERROR] 指定路径不存在: {explicit_path}")
        sys.exit(1)

    # 从环境变量读取
    ads_root = Path("F:/A_Works/ai-dev-system")
    if ads_root.exists():
        tools = ads_root / "backend" / "tools" / "memory_mcp"
        if tools.exists():
            return tools
    return None


def merge_mcp_config(project_path: Path, server_name: str, server_config: dict):
    """注册 MCP 服务器到 .codebuddy/mcp.json，不覆盖已有服务器。"""
    mcp_file = project_path / ".codebuddy" / "mcp.json"

    if mcp_file.exists():
        with open(mcp_file, "r", encoding="utf-8") as f:
            config = json.load(f)
    else:
        config = {}

    if "mcpServers" not in config:
        config["mcpServers"] = {}

    if server_name in config["mcpServers"]:
        print(f"  [SKIP] MCP 服务器 '{server_name}' 已注册，跳过")
        return

    config["mcpServers"][server_name] = server_config

    mcp_file.parent.mkdir(parents=True, exist_ok=True)
    with open(mcp_file, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    print(f"  [OK] 已注册 MCP 服务器 '{server_name}' → {mcp_file}")


def main():
    parser = argparse.ArgumentParser(description="部署 MCP Memory Server")
    parser.add_argument("--project-path", default=str(Path.cwd()), help="UE 项目根目录")
    parser.add_argument("--ads-tools", help="memory_mcp 源码目录 (可选，自动检测)")
    args = parser.parse_args()

    project_path = Path(args.project_path).resolve()
    script_dir = Path(__file__).resolve().parent
    ads_tools = find_ads_tools(script_dir, args.ads_tools)

    if not ads_tools:
        print("[WARN] 无法自动定位 memory_mcp 源码")
        print("  请使用 --ads-tools 指定路径, 或确认 ADS 位于 F:/A_Works/ai-dev-system")
        sys.exit(1)

    print(f"[INFO] 源目录: {ads_tools}")
    print(f"[INFO] 目标项目: {project_path}")

    # 目标位置
    dest = project_path / ".codebuddy" / "mcp" / "memory"
    if dest.exists():
        shutil.rmtree(dest)
        print("  [OK] 已清理旧安装")

    # 跳过 vendor 目录 (第三方 wheels，体积大)，用 pip install 替代
    ignore_patterns = shutil.ignore_patterns("vendor", "__pycache__", "*.pyc", ".venv", "tests")
    shutil.copytree(ads_tools, dest, ignore=ignore_patterns, dirs_exist_ok=True)
    print(f"  [OK] 已复制 memory_mcp → {dest}")

    # 创建虚拟环境并安装依赖
    venv_dir = dest / ".venv"
    if not venv_dir.exists():
        print("  [INFO] 创建虚拟环境...")
        venv.create(venv_dir, with_pip=True)

    pip = str(venv_dir / "Scripts" / "pip.exe")
    python = str(venv_dir / "Scripts" / "python.exe")

    req_file = dest / "requirements.txt"
    if req_file.exists():
        print("  [INFO] 安装 Python 依赖...")
        subprocess.run([pip, "install", "-r", str(req_file)], check=True)
        print("  [OK] 依赖安装完成")

    # 验证服务可导入
    result = subprocess.run(
        [python, "-c", "import servers.memory_server"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print("  [OK] memory_server 模块验证通过")
    else:
        print(f"  [WARN] 模块导入测试失败: {result.stderr[:200]}")

    # 注册 MCP 服务器
    memory_command = str(dest / "servers" / "memory_server" / "cli.py")
    merge_mcp_config(project_path, "memory", {
        "command": str(python),
        "args": [memory_command],
        "cwd": str(dest),
        "env": {
            "PYTHONPATH": str(dest)
        }
    })

    print("\n[SUCCESS] MCP Memory Server 部署完成")
    print(f"  项目路径: {project_path}")
    print(f"  服务目录: {dest}")
    print(f"  Python:    {python}")


if __name__ == "__main__":
    main()

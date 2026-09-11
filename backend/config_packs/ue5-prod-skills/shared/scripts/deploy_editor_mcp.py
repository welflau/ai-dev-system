"""
部署 UEEditorMCP 插件到 UE 项目

用法:
  python deploy_editor_mcp.py [--project-path <路径>] [--ads-tools <路径>] [--run-setup]

功能:
  1. 找到 backend/tools/ue_editor_mcp/ 源目录
  2. 复制到项目的 Plugins/UEEditorMCP/
  3. 可选: 运行 setup_mcp.ps1 初始化 MCP 服务

前置条件:
  - 目标目录必须包含 .uproject 文件 (UE 项目根目录)
  - setup_mcp.ps1 需要 UE Editor Python (自动查找引擎内置 Python)
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def find_ads_tools(script_dir: Path, explicit_path: str | None) -> Path | None:
    """定位 ue_editor_mcp 源码目录。"""
    if explicit_path:
        p = Path(explicit_path).resolve()
        if p.exists():
            return p
        print(f"[ERROR] 指定路径不存在: {explicit_path}")
        sys.exit(1)

    ads_root = Path("F:/A_Works/ai-dev-system")
    if ads_root.exists():
        tools = ads_root / "backend" / "tools" / "ue_editor_mcp"
        if tools.exists():
            return tools
    return None


def validate_ue_project(project_path: Path) -> bool:
    """检查目录是否为 UE 项目根目录。"""
    uproject_files = list(project_path.glob("*.uproject"))
    if not uproject_files:
        print(f"[ERROR] 未找到 .uproject 文件: {project_path}")
        return False
    print(f"  [OK] 检测到 UE 项目: {uproject_files[0].name}")
    return True


def main():
    parser = argparse.ArgumentParser(description="部署 UEEditorMCP 插件")
    parser.add_argument("--project-path", default=str(Path.cwd()), help="UE 项目根目录")
    parser.add_argument("--ads-tools", help="ue_editor_mcp 源码目录 (可选，自动检测)")
    parser.add_argument("--run-setup", action="store_true", help="复制后运行 setup_mcp.ps1 初始化")
    parser.add_argument("--force", action="store_true", help="强制覆盖已有安装")
    args = parser.parse_args()

    project_path = Path(args.project_path).resolve()
    script_dir = Path(__file__).resolve().parent
    ads_tools = find_ads_tools(script_dir, args.ads_tools)

    if not ads_tools:
        print("[WARN] 无法自动定位 ue_editor_mcp 源码")
        print("  请使用 --ads-tools 指定路径, 或确认 ADS 位于 F:/A_Works/ai-dev-system")
        sys.exit(1)

    print(f"[INFO] 源目录: {ads_tools}")
    print(f"[INFO] 目标项目: {project_path}")

    if not validate_ue_project(project_path):
        sys.exit(1)

    # 目标位置
    dest = project_path / "Plugins" / "UEEditorMCP"

    if dest.exists():
        if args.force:
            shutil.rmtree(dest)
            print("  [OK] 已清理旧安装")
        else:
            print(f"  [SKIP] 插件已存在: {dest}")
            print("  使用 --force 强制覆盖")
            # 即使跳过安装，也可以运行 setup
            if args.run_setup:
                run_setup(dest)
            return

    # 复制插件 (跳过临时文件)
    ignore_patterns = shutil.ignore_patterns(
        "__pycache__", "*.pyc", ".venv",
        "Python/temp_*.py",      # P110_2 开发时临时脚本
        "Python/vendor",          # 第三方 wheels，setup_mcp.ps1 会自动处理
        "Python/tests",
    )
    shutil.copytree(ads_tools, dest, ignore=ignore_patterns, dirs_exist_ok=True)
    print(f"  [OK] 已复制 UEEditorMCP → {dest}")

    # 复制 .uplugin 到正确位置
    uplugin_src = ads_tools / "UEEditorMCP.uplugin"
    if uplugin_src.exists():
        shutil.copy2(uplugin_src, dest / "UEEditorMCP.uplugin")

    # 运行 setup
    if args.run_setup:
        run_setup(dest)

    print("\n[SUCCESS] UEEditorMCP 插件部署完成")
    print(f"  项目路径: {project_path}")
    print(f"  插件目录: {dest}")
    print(f"  下一步: 在项目中运行 setup_mcp.ps1 初始化 MCP 服务")


def run_setup(plugin_dir: Path):
    """执行 setup_mcp.ps1 初始化 MCP 服务。"""
    setup_script = plugin_dir / "setup_mcp.ps1"
    if not setup_script.exists():
        print(f"  [WARN] setup_mcp.ps1 未找到: {setup_script}")
        return

    print("  [INFO] 运行 setup_mcp.ps1...")
    try:
        subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(setup_script)],
            cwd=str(plugin_dir),
            check=True,
            timeout=600
        )
        print("  [OK] setup_mcp.ps1 执行完成")
    except subprocess.TimeoutExpired:
        print("  [WARN] setup_mcp.ps1 超时 (10 分钟)，请手动运行")
    except subprocess.CalledProcessError as e:
        print(f"  [WARN] setup_mcp.ps1 执行失败 (exit={e.returncode})")


if __name__ == "__main__":
    main()

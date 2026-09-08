"""
部署 UnrealClientProtocol (UCP) 插件到 UE 项目

用法:
  python deploy_ucp.py [--project-path <路径>] [--ads-root <ADS根目录>] [--force]

功能:
  将 ADS 内置的 UnrealClientProtocol 复制到 {project}/Plugins/UnrealClientProtocol/

前置条件:
  - 目标目录必须包含 .uproject 文件（UE 项目根目录）
  - ADS 仓库内存在 backend/ue_plugins/UnrealClientProtocol/

部署后:
  - 重启 UE Editor，完成插件编译
  - Edit → Plugins → 确认 UnrealClientProtocol 已启用（端口 9876）
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

_DEFAULT_ADS_ROOTS = [
    Path(r"F:/A_Works/ai-dev-system"),
    Path.home() / "ai-dev-system",
]


def find_ucp_source(ads_root: Path | None) -> Path | None:
    """定位 ADS 内置 UCP 插件源码。"""
    candidates: list[Path] = []
    if ads_root:
        candidates.append(Path(ads_root).resolve())
    candidates.extend(_DEFAULT_ADS_ROOTS)

    # 脚本在 .codebuddy/packs/.../scripts 或 config_packs/.../scripts 时，向上找仓库根
    here = Path(__file__).resolve().parent
    for up in [here, *here.parents]:
        if (up / "backend" / "ue_plugins" / "UnrealClientProtocol").is_dir():
            candidates.insert(0, up)
            break

    for root in candidates:
        src = root / "backend" / "ue_plugins" / "UnrealClientProtocol"
        if src.is_dir() and (src / "UnrealClientProtocol.uplugin").is_file():
            return src
    return None


def validate_ue_project(project_path: Path) -> bool:
    uprojects = list(project_path.glob("*.uproject"))
    if not uprojects:
        print(f"[ERROR] 未找到 .uproject 文件: {project_path}")
        return False
    print(f"  [OK] 检测到 UE 项目: {uprojects[0].name}")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="部署 UnrealClientProtocol (UCP) 插件")
    parser.add_argument("--project-path", default=str(Path.cwd()), help="UE 项目根目录")
    parser.add_argument("--ads-root", help="ADS 仓库根目录（含 backend/ue_plugins）")
    parser.add_argument("--force", action="store_true", help="强制覆盖已有安装")
    parser.add_argument("--status", action="store_true", help="仅检查是否已安装")
    args = parser.parse_args()

    project_path = Path(args.project_path).resolve()
    dest = project_path / "Plugins" / "UnrealClientProtocol"
    marker = dest / "UnrealClientProtocol.uplugin"

    if args.status:
        if marker.is_file():
            print(f"[OK] UCP 已安装: {dest}")
            sys.exit(0)
        print("[MISS] UCP 未安装（Plugins/UnrealClientProtocol 不存在）")
        sys.exit(1)

    print(f"[INFO] 目标项目: {project_path}")
    if not validate_ue_project(project_path):
        sys.exit(1)

    ads_root = Path(args.ads_root).resolve() if args.ads_root else None
    src = find_ucp_source(ads_root)
    if not src:
        print("[ERROR] 无法定位 ADS 内置 UCP 源码")
        print("  请用 --ads-root 指定 ADS 仓库根，例如:")
        print("  python deploy_ucp.py --ads-root F:/A_Works/ai-dev-system")
        sys.exit(1)

    print(f"[INFO] 源目录: {src}")

    if dest.exists() and not args.force:
        print(f"  [SKIP] 插件已存在: {dest}")
        print("  使用 --force 强制覆盖更新")
        print("\n[SUCCESS] UCP 已在工程中（未覆盖）")
        print("  下一步: 重启 UE Editor → Edit → Plugins → 启用 UnrealClientProtocol")
        return

    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and args.force:
        shutil.rmtree(dest)
        print("  [OK] 已清理旧安装")

    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".vs", "Binaries", "Intermediate")
    shutil.copytree(str(src), str(dest), dirs_exist_ok=True, ignore=ignore)
    print(f"  [OK] 已复制 UnrealClientProtocol → {dest}")

    print("\n[SUCCESS] UCP 插件部署完成")
    print(f"  项目路径: {project_path}")
    print(f"  插件目录: {dest}")
    print("  下一步: 重启 UE Editor，完成编译后确认插件已启用（TCP 9876）")


if __name__ == "__main__":
    main()

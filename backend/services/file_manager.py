"""定位本地文件或打开其目录；不等待桌面程序退出。"""
import os
from pathlib import Path
import stat
import subprocess
import sys


class RevealPathNotFound(FileNotFoundError):
    """请求的路径不存在（与桌面程序未安装区分）。"""


def reveal_path(path: Path) -> Path:
    try:
        mode = path.stat().st_mode
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise RevealPathNotFound(str(path)) from exc

    is_file = stat.S_ISREG(mode)
    if not is_file and not stat.S_ISDIR(mode):
        raise ValueError("仅支持文件或目录")
    folder = path.parent if is_file else path
    # 交给桌面程序绝对路径；HTTP 响应仍按请求路径返回所在目录。
    location = str(path.absolute())
    if sys.platform == "win32":
        if is_file:
            subprocess.Popen(["explorer", "/select,", location])
        else:
            os.startfile(location)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", location] if is_file else ["open", location])
    else:
        subprocess.Popen(["xdg-open", str(folder.absolute())])
    return folder

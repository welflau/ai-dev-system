"""系统健康状态和本地项目目录建议。"""
from pathlib import Path

from fastapi import APIRouter

from config import APP_VERSION

router = APIRouter(prefix="/api")

PROJECT_PATH_SUGGESTIONS = (
    Path("D:/Projects"), Path("D:/AIProjects"), Path("D:/MyProjects"),
    Path("D:/A_Works"), Path("D:/Works"), Path("C:/Projects"),
    Path("C:/Users/admin/Documents/Projects"), Path("C:/Users/admin/Documents"),
)


@router.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "version": APP_VERSION}


@router.get("/filesystem/available-paths")
async def get_available_paths():
    """获取常用的本地路径列表"""
    return {"paths": [
        {"path": str(path), "label": path.name, "exists": path.exists() and path.is_dir()}
        for path in PROJECT_PATH_SUGGESTIONS
    ]}

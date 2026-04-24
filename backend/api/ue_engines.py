"""
UE 引擎检测 API（v0.18 Phase A.3）

端点：
- GET /api/ue-engines/detect               —— 扫本机所有 UE 引擎
- GET /api/ue-engines/resolve?uproject=... —— 为指定 .uproject 定位对应引擎
- GET /api/ue-engines/verify?path=...      —— 给定路径做完整验证
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from engines.ue_resolver import (
    detect_installed_engines,
    resolve_project_engine,
    verify_engine,
)

router = APIRouter(prefix="/api/ue-engines", tags=["ue-engines"])


@router.get("/detect")
async def detect_engines():
    """列出本机注册的所有 UE 引擎（HKLM 官方 + HKCU 自编译）。"""
    engines = detect_installed_engines()
    return {
        "engines": [e.to_dict() for e in engines],
        "total": len(engines),
        "launcher_count": sum(1 for e in engines if e.type == "launcher"),
        "source_count": sum(1 for e in engines if e.type == "source_build"),
    }


@router.get("/resolve")
async def resolve_engine(uproject: str = Query(..., description=".uproject 文件绝对路径")):
    """根据 .uproject 的 EngineAssociation 找对应引擎。找不到返回 404 让前端引导用户手选。"""
    info = resolve_project_engine(uproject)
    if not info:
        raise HTTPException(404, "无法从 .uproject 关联到本机已知引擎，请从 /detect 列表里手选")
    return info.to_dict()


@router.get("/verify")
async def verify(path: str = Query(..., description="引擎根目录绝对路径")):
    """对任意路径做完整引擎验证（版本号 + 类型 + 工具链）。"""
    info = verify_engine(path)
    return info.to_dict()

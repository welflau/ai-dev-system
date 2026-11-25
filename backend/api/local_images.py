"""本地图片预览：按扩展名确定响应类型，原样发送文件。"""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter()
IMAGE_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp",
}


@router.get("/api/local-file", response_class=FileResponse, responses={
    200: {"content": {kind: {"schema": {"type": "string", "format": "binary"}}
                      for kind in IMAGE_TYPES.values()}},
    400: {"description": "不支持的文件类型", "content": {
        "application/json": {"example": {"detail": "不支持的文件类型"}}}},
    404: {"description": "文件不存在", "content": {
        "application/json": {"example": {"detail": "文件不存在"}}}},
})
async def serve_local_file(path: str):
    """按需读取本地文件并以图片形式返回（仅限图片格式，供前端预览 AI 生成图片）"""
    fp = Path(path)
    if not fp.is_file():
        raise HTTPException(404, "文件不存在")
    media_type = IMAGE_TYPES.get(fp.suffix.lower())
    if media_type is None:
        raise HTTPException(400, "不支持的文件类型")
    return FileResponse(fp, media_type=media_type)

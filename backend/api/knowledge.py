"""
知识库管理 API
- 全局知识库：BASE_DIR/docs/          （所有项目共享）
- 项目知识库：BASE_DIR/projects/{id}/docs/  （仅该项目使用）
"""
import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config import BASE_DIR

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

# ==================== 路径辅助 ====================

GLOBAL_DOCS_DIR = BASE_DIR / "docs"
GLOBAL_DOCS_DIR.mkdir(exist_ok=True)

PROJECTS_DIR = BASE_DIR / "projects"


def _safe_filename(name: str) -> str:
    """过滤文件名，只允许字母/数字/连字符/下划线/点"""
    name = re.sub(r"[^\w\-. ]", "", name).strip()
    if not name.endswith(".md"):
        name += ".md"
    return name


def _get_docs_dir(project_id: Optional[str]) -> Path:
    if project_id:
        d = PROJECTS_DIR / project_id / "docs"
    else:
        d = GLOBAL_DOCS_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _doc_info(path: Path, base: Path) -> dict:
    stat = path.stat()
    return {
        "filename": path.name,
        "size": stat.st_size,
        "modified_at": stat.st_mtime,
    }


# ==================== 列出文档 ====================

@router.get("/global")
async def list_global_docs():
    """列出全局知识库文档"""
    d = _get_docs_dir(None)
    files = sorted(d.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)
    return {"docs": [_doc_info(f, d) for f in files]}


@router.get("/projects/{project_id}")
async def list_project_docs(project_id: str):
    """列出项目知识库文档"""
    d = _get_docs_dir(project_id)
    files = sorted(d.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)
    return {"docs": [_doc_info(f, d) for f in files]}


# ==================== 读取文档内容 ====================

@router.get("/global/{filename}")
async def get_global_doc(filename: str):
    path = _get_docs_dir(None) / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="文档不存在")
    content = path.read_text(encoding="utf-8", errors="replace")
    return {"filename": filename, "content": content}


@router.get("/projects/{project_id}/{filename}")
async def get_project_doc(project_id: str, filename: str):
    path = _get_docs_dir(project_id) / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="文档不存在")
    content = path.read_text(encoding="utf-8", errors="replace")
    return {"filename": filename, "content": content}


# ==================== 保存文档（创建/更新） ====================

class DocBody(BaseModel):
    filename: str
    content: str


@router.put("/global")
async def save_global_doc(body: DocBody):
    """创建或更新全局文档"""
    fname = _safe_filename(body.filename)
    path = _get_docs_dir(None) / fname
    path.write_text(body.content, encoding="utf-8")
    return {"status": "ok", "filename": fname}


@router.put("/projects/{project_id}")
async def save_project_doc(project_id: str, body: DocBody):
    """创建或更新项目文档"""
    fname = _safe_filename(body.filename)
    path = _get_docs_dir(project_id) / fname
    path.write_text(body.content, encoding="utf-8")
    return {"status": "ok", "filename": fname}


# ==================== 上传文档 ====================

@router.post("/global/upload")
async def upload_global_doc(file: UploadFile = File(...)):
    fname = _safe_filename(file.filename or "document.md")
    content = (await file.read()).decode("utf-8", errors="replace")
    path = _get_docs_dir(None) / fname
    path.write_text(content, encoding="utf-8")
    return {"status": "ok", "filename": fname}


@router.post("/projects/{project_id}/upload")
async def upload_project_doc(project_id: str, file: UploadFile = File(...)):
    fname = _safe_filename(file.filename or "document.md")
    content = (await file.read()).decode("utf-8", errors="replace")
    path = _get_docs_dir(project_id) / fname
    path.write_text(content, encoding="utf-8")
    return {"status": "ok", "filename": fname}


# ==================== 删除文档 ====================

@router.delete("/global/{filename}")
async def delete_global_doc(filename: str):
    path = _get_docs_dir(None) / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="文档不存在")
    path.unlink()
    return {"status": "ok"}


@router.delete("/projects/{project_id}/{filename}")
async def delete_project_doc(project_id: str, filename: str):
    path = _get_docs_dir(project_id) / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="文档不存在")
    path.unlink()
    return {"status": "ok"}

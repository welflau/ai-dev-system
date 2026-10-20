"""仓库识别与浏览 API。

为什么单独一个模块而不是塞进 projects.py：projects.py 已经 3200+ 行，
而且这里的"仓库"是比 projects.git_repo_path 更大的概念 ——
一个项目可以有多个仓库（主路径 + extra_paths + 嵌套仓库），git 和 P4 各一批。

四个端点：
  GET /api/projects/{pid}/repos                  识别项目名下的所有仓库
  GET /api/projects/{pid}/repos/{key}/tree       按仓库根**懒加载**一层目录
  GET /api/projects/{pid}/repos/{key}/search     按文件名/路径过滤，只返回有限条
  GET /api/projects/{pid}/repos/{key}/file       按仓库根读文件

懒加载不是优化而是必需：项目 OG 的 I:\\A_Works\\OG2\\P4\\UE5 递归下去有
103 万个文件，projects.py 的 /git/tree 一次性返回整棵树，打开就卡死。
单层 os.scandir 只要 0ms —— 慢的是"一次要全部"。
"""
import asyncio
import hashlib
import json as _json
import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException

from database import db
from git_manager import git_manager

logger = logging.getLogger("api.repos")

router = APIRouter(prefix="/api/projects", tags=["repos"])

# 浅扫时不进入的目录。UE 项目不剪 Intermediate/Binaries 的话，
# 光这两个目录就能让"深度 2"退化成扫几万个子目录。
_SCAN_SKIP = {
    ".git", ".svn", ".hg", ".p4", "node_modules", "__pycache__",
    "Intermediate", "Binaries", "DerivedDataCache", "Saved", "DerivedData",
    ".vs", ".idea", "venv", ".venv", "dist", "build",
}

# 浅扫深度：1 = 只看项目根的直接子目录，2 = 再下一层（够覆盖 Plugins/XXX/.git）
_SCAN_DEPTH = 2

# 每层目录最多返回多少条。UE 的 Content 目录动辄上千个资产，
# 全渲染到树上前端也没法用。
_MAX_ENTRIES = 500

# 识别结果缓存：project_id → [entry, ...]。
# p4 info 走网络（10s 超时），每次切 tab 都重探太慢。?refresh=1 强制重算。
_repos_cache: dict[str, list] = {}


def _repo_key(path: str) -> str:
    """仓库路径 → 短 key。前端只拿 key，不拿绝对路径去请求 ——
    key 查不到就 404，这是防目录穿越的第一道防线。"""
    norm = str(Path(path)).replace("\\", "/").rstrip("/").lower()
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:12]


def _norm(path: str) -> str:
    """用于去重比较的规范化形式（大小写、分隔符、尾斜杠）"""
    try:
        return str(Path(path).resolve()).replace("\\", "/").rstrip("/").lower()
    except Exception:
        return (path or "").replace("\\", "/").rstrip("/").lower()


def _shallow_scan(root: str, depth: int = _SCAN_DEPTH) -> list[dict]:
    """在项目根下找嵌套仓库（有 .git 或 .p4config 的子目录）。

    为什么是浅扫而不是 os.walk：UE5 根下 103 万个文件，全量递归要几分钟。
    浅扫 UE5 根实测 118ms。代价是 Plugins/A/B/C/.git 这种三层以下的找不到，
    用户可以在「设置 → 仓库配置」手动加路径。
    """
    found = []
    p4config_name = os.environ.get("P4CONFIG", ".p4config")

    def walk(cur: str, d: int):
        if d > depth:
            return
        try:
            entries = list(os.scandir(cur))
        except (PermissionError, OSError):
            return
        for e in entries:
            try:
                if not e.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            if e.name in _SCAN_SKIP or e.name.startswith("."):
                continue
            if os.path.exists(os.path.join(e.path, ".git")):
                found.append({"path": e.path, "vcs": "git"})
            elif os.path.exists(os.path.join(e.path, p4config_name)):
                found.append({"path": e.path, "vcs": "p4"})
            else:
                # 本身不是仓库才继续往下找，避免把仓库内部的子目录也当仓库
                walk(e.path, d + 1)

    walk(root, 1)
    return found


async def _describe_repo(path: str, source: str, label: str = "",
                         writable: bool = True) -> Optional[dict]:
    """把一个路径描述成一条仓库记录（含 vcs 类型、分支、P4 workspace 信息）"""
    if not path or not os.path.isdir(path):
        return None

    from vcs_detector import detect_vcs, VCSType
    from p4_manager import p4_manager

    try:
        vcs = await detect_vcs(path)
    except Exception as e:
        logger.debug("detect_vcs 失败 %s: %s", path, e)
        vcs = VCSType.NONE

    entry = {
        "key": _repo_key(path),
        "path": str(Path(path)),
        "name": Path(path).name or path,
        "vcs": vcs.value,
        "also_p4": False,
        "source": source,
        "label": label,
        "writable": writable,
    }

    if vcs == VCSType.GIT:
        branch = await git_manager.get_branch_at_path(path)
        rc, remote, _ = await git_manager._run_git(path, "remote", "get-url", "origin")
        entry["git"] = {"branch": branch or "", "remote": remote if rc == 0 else ""}

        # detect_vcs 是 git 优先的**单值**返回：一个目录既是 git 仓库、又在 P4
        # workspace 下时（项目 OG 的 UE5 根就是），它只报 git，这条仓库就永远
        # 进不了 P4 子 Tab。所以这里补一次 P4 探测，命中就两边都出现。
        # 不去改 detect_vcs 的语义 —— ensure_writable 依赖它"git 直接写、
        # P4 先 p4 edit"的优先级，改成多值会动到写前检查。
        try:
            if await p4_manager.detect_p4_root(path):
                entry["also_p4"] = True
        except Exception as e:
            logger.debug("P4 兼容探测失败 %s: %s", path, e)

    if vcs == VCSType.P4 or entry["also_p4"]:
        try:
            info = await p4_manager.p4_info(cwd=path)
        except Exception:
            info = None
        if info:
            entry["p4"] = {
                "client": info.get("Client name", ""),
                "stream": info.get("Client stream", ""),
                "client_root": info.get("Client root", ""),
                "server": info.get("Server address", ""),
                "user": info.get("User name", ""),
            }

    return entry


async def _collect_repos(project_id: str) -> list[dict]:
    """识别项目名下的所有仓库。三个来源合并，按规范化路径去重（先到先得）。"""
    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    main_path = project.get("git_repo_path") or ""

    # 1) 主路径
    candidates = []
    if main_path:
        candidates.append({"path": main_path, "source": "primary", "label": "", "writable": True})

    # 2) extra_paths（已经存了 vcs / label / writable，但 vcs 可能过期，重新探）
    try:
        extras = _json.loads(project.get("extra_paths") or "[]") or []
    except Exception:
        extras = []
    for ep in extras:
        p = ep.get("path") if isinstance(ep, dict) else ep
        if not p:
            continue
        candidates.append({
            "path": p,
            "source": "configured",
            "label": (ep.get("label") or "") if isinstance(ep, dict) else "",
            "writable": (ep.get("writable", True)) if isinstance(ep, dict) else True,
        })

    # 3) 项目根下浅扫嵌套仓库
    if main_path and os.path.isdir(main_path):
        for hit in _shallow_scan(main_path):
            candidates.append({
                "path": hit["path"], "source": "detected", "label": "", "writable": True,
            })

    repos = []
    seen = set()
    for c in candidates:
        n = _norm(c["path"])
        if not n or n in seen:
            continue
        seen.add(n)
        entry = await _describe_repo(c["path"], c["source"], c["label"], c["writable"])
        if entry:
            repos.append(entry)

    return repos


async def _resolve_repo(project_id: str, key: str) -> dict:
    """key → 仓库记录。只认识别结果里的 key，别的一律 404。

    前端从不传绝对路径，服务端也只在这份白名单里查 —— 伪造 key 拿不到任何目录。
    """
    repos = _repos_cache.get(project_id)
    if repos is None:
        repos = await _collect_repos(project_id)
        _repos_cache[project_id] = repos
    for r in repos:
        if r["key"] == key:
            return r
    # 缓存可能过期（用户刚加了路径），重算一次再判
    repos = await _collect_repos(project_id)
    _repos_cache[project_id] = repos
    for r in repos:
        if r["key"] == key:
            return r
    raise HTTPException(404, "仓库不存在或已失效")


def _safe_join(root: str, rel: str) -> Path:
    """仓库根 + 相对路径 → 绝对路径，越界直接 400。

    照 git_manager._disk_file_exists 的写法：resolve() 之后再
    relative_to(root)，这样 `..`、盘符绝对路径、符号链接都挡得住。
    """
    rel = git_manager._normalize_rel_path(rel or "")
    root_p = Path(root).resolve()
    target = root_p.joinpath(*[s for s in rel.split("/") if s]) if rel else root_p
    try:
        target.resolve().relative_to(root_p)
    except ValueError:
        raise HTTPException(400, "路径越界")
    return target


# ==================== 端点 ====================


@router.get("/{project_id}/repos")
async def list_project_repos(project_id: str, refresh: int = 0):
    """识别项目名下的所有仓库（git / p4）。

    refresh=1 跳过缓存重新探测（p4 info 走网络，默认走缓存）。
    """
    if refresh or project_id not in _repos_cache:
        _repos_cache[project_id] = await _collect_repos(project_id)
    repos = _repos_cache[project_id]

    # 一条仓库可以同时出现在两边（既是 git 仓库又在 P4 workspace 下）
    git_repos = [r for r in repos if r["vcs"] == "git"]
    p4_repos = [r for r in repos if r["vcs"] == "p4" or r.get("also_p4")]
    # 两边都不属于的（配置里写着但实际没有 .git / 不在 workspace 下）。
    # 不能直接丢掉：用户在「仓库配置」里加了这条路径，页面上一条都不显示
    # 会让人以为配置没生效。挂到 Git 子 Tab 的选择器里，用 badge 区分。
    other_repos = [r for r in repos
                   if r["vcs"] not in ("git", "p4") and not r.get("also_p4")]

    return {
        "repos": repos,
        "git": git_repos,
        "p4": p4_repos,
        "other": other_repos,
        "counts": {
            "git": len(git_repos), "p4": len(p4_repos),
            "other": len(other_repos), "total": len(repos),
        },
    }


@router.get("/{project_id}/repos/{key}/tree")
async def get_repo_tree(project_id: str, key: str, path: str = "", depth: int = 1):
    """按仓库根**懒加载**一层目录。

    depth 默认 1：只返回这一层，目录项带 has_children 标记但不含 children。
    前端点开一个目录才请求它的下一层 —— 这是 103 万文件的仓库能打开的唯一办法。
    """
    repo = await _resolve_repo(project_id, key)
    target = _safe_join(repo["path"], path)

    if not target.is_dir():
        raise HTTPException(404, "目录不存在")

    rel_base = git_manager._normalize_rel_path(path or "")

    def _scan(d: Path, rel: str, cur_depth: int) -> tuple[list, bool, int]:
        try:
            items = list(os.scandir(d))
        except (PermissionError, OSError) as e:
            logger.debug("扫描目录失败 %s: %s", d, e)
            return [], False, 0

        # 先分好目录/文件（带上标记一起排），后面就不用再问一次 is_dir ——
        # 在网络盘 / 大目录上每次 is_dir 都是一次 stat
        dirs, files = [], []
        for it in items:
            if it.name.startswith(".") or it.name == "__pycache__":
                continue
            try:
                is_dir = it.is_dir(follow_symlinks=False)
            except OSError:
                continue
            (dirs if is_dir else files).append(it)

        dirs.sort(key=lambda x: x.name.lower())
        files.sort(key=lambda x: x.name.lower())
        # 目录在前、文件在后，和前端 renderFileTree 的排序一致
        ordered = [(it, True) for it in dirs] + [(it, False) for it in files]
        total = len(ordered)
        truncated = total > _MAX_ENTRIES
        ordered = ordered[:_MAX_ENTRIES]

        out = []
        for it, is_dir in ordered:
            child_rel = f"{rel}/{it.name}" if rel else it.name
            if is_dir:
                node = {
                    "name": it.name,
                    "path": child_rel,
                    "type": "directory",
                    "has_children": _has_children(it.path),
                }
                if cur_depth < depth:
                    sub, sub_trunc, _ = _scan(Path(it.path), child_rel, cur_depth + 1)
                    node["children"] = sub
                    if sub_trunc:
                        node["truncated"] = True
                out.append(node)
            else:
                try:
                    size = it.stat().st_size
                except OSError:
                    size = 0
                out.append({
                    "name": it.name, "path": child_rel, "type": "file", "size": size,
                })
        return out, truncated, total

    entries, truncated, total = _scan(target, rel_base, 1)
    return {
        "path": rel_base,
        "repo": {"key": repo["key"], "name": repo["name"], "vcs": repo["vcs"]},
        "entries": entries,
        "truncated": truncated,
        "total": total,
        "limit": _MAX_ENTRIES,
    }


_SEARCH_LIMIT = 200
_SEARCH_SCAN_BUDGET = 80000


def _search_git_index(root: Path, query: str, limit: int) -> Optional[tuple]:
    """用 git ls-files 过滤。UE 工程上 os.walk 会先钻进 Content，预算耗尽时目标文件还没扫到。"""
    if not (root / ".git").exists():
        return None
    q = query.strip().casefold()
    if not q:
        return [], False, 0
    try:
        proc = subprocess.run(
            ["git", "-c", "core.quotepath=false", "ls-files", "-z"],
            cwd=str(root),
            capture_output=True,
            timeout=45,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.debug("git ls-files 失败 %s: %s", root, e)
        return None
    if proc.returncode != 0:
        return None
    name_hits: list[str] = []
    path_hits: list[str] = []
    stopped = False
    for rel in proc.stdout.decode("utf-8", "replace").split("\0"):
        if not rel:
            continue
        rel = rel.replace("\\", "/")
        name = rel.rsplit("/", 1)[-1]
        if q in name.casefold():
            name_hits.append(rel)
            if len(name_hits) >= limit:
                stopped = True
                break
        elif len(path_hits) < limit and q in rel.casefold():
            path_hits.append(rel)
    chosen = name_hits[:limit]
    if len(chosen) < limit:
        chosen.extend(path_hits[:limit - len(chosen)])
    entries = [{
        "name": rel.rsplit("/", 1)[-1],
        "path": rel,
        "type": "file",
        "size": 0,
    } for rel in chosen]
    truncated = stopped or (len(name_hits) + len(path_hits) > len(entries))
    return entries, truncated, len(entries)


def _search_files(root: Path, query: str, limit: int = _SEARCH_LIMIT,
                  scan_budget: int = _SEARCH_SCAN_BUDGET) -> tuple[list, bool, int]:
    """在仓库根下按文件名或相对路径做子串匹配。

    有 .git 时走索引，一次就能覆盖全部已跟踪文件。
    否则 os.walk，凑满 limit 或扫过 scan_budget 个条目就停，
    并且不进入 Intermediate / Binaries 等生成目录。
    """
    git_hits = _search_git_index(root, query, limit)
    if git_hits is not None:
        return git_hits
    q = (query or "").strip().casefold()
    if not q:
        return [], False, 0
    hits: list = []
    scanned = 0
    stopped_early = False
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            (d for d in dirnames if d not in _SCAN_SKIP and not d.startswith(".")),
            key=str.lower,
        )
        filenames = sorted(
            (f for f in filenames if not f.startswith(".")),
            key=str.lower,
        )
        rel_dir = os.path.relpath(dirpath, root)
        if rel_dir == ".":
            rel_dir = ""
        entries = [(name, True) for name in dirnames] + [(name, False) for name in filenames]
        for name, is_dir in entries:
            scanned += 1
            rel = f"{rel_dir}/{name}" if rel_dir else name
            rel = rel.replace("\\", "/")
            name_hit = q in name.casefold()
            path_hit = q in rel.casefold()
            if name_hit or path_hit:
                size = 0
                if not is_dir:
                    try:
                        size = (Path(dirpath) / name).stat().st_size
                    except OSError:
                        size = 0
                hits.append({
                    "name": name,
                    "path": rel,
                    "type": "directory" if is_dir else "file",
                    "size": size,
                    "name_hit": name_hit,
                })
            if len(hits) >= limit or scanned >= scan_budget:
                stopped_early = True
                break
        if stopped_early:
            break
    hits.sort(key=lambda h: (not h["name_hit"], h["path"].lower()))
    trimmed = hits[:limit]
    for h in trimmed:
        h.pop("name_hit", None)
    partial = stopped_early or len(hits) > limit
    return trimmed, partial, scanned


def _has_children(path: str) -> bool:
    """目录里有没有东西（决定要不要渲染展开箭头）。
    用 scandir 取第一个就返回，不递归 —— UE 的 Content 目录不能数全。"""
    try:
        with os.scandir(path) as it:
            for e in it:
                if not e.name.startswith("."):
                    return True
    except (PermissionError, OSError):
        return False
    return False


@router.get("/{project_id}/repos/{key}/search")
async def search_repo_files(project_id: str, key: str, q: str = "", limit: int = _SEARCH_LIMIT):
    """按文件名或相对路径过滤。树是懒加载的，过滤不能靠前端已展开的那几层。"""
    query = (q or "").strip()
    if not query:
        return {"query": "", "entries": [], "truncated": False, "scanned": 0}
    repo = await _resolve_repo(project_id, key)
    root = Path(repo["path"])
    if not root.is_dir():
        raise HTTPException(404, "仓库目录不存在")
    cap = max(1, min(int(limit or _SEARCH_LIMIT), _SEARCH_LIMIT))
    entries, truncated, scanned = await asyncio.to_thread(_search_files, root, query, cap)
    return {
        "query": query,
        "entries": entries,
        "truncated": truncated,
        "scanned": scanned,
        "limit": cap,
    }


@router.get("/{project_id}/repos/{key}/file")
async def get_repo_file(project_id: str, key: str, path: str):
    """按仓库根读文本文件。返回形状和 /git/file 一致，前端渲染分支能直接复用。"""
    repo = await _resolve_repo(project_id, key)
    target = _safe_join(repo["path"], path)

    if not target.is_file():
        raise HTTPException(404, "文件不存在")

    # 太大的文件不读进内存（前端 2000 行就截断了，这里给 5MB 上限）
    try:
        size = target.stat().st_size
    except OSError:
        size = 0
    if size > 5 * 1024 * 1024:
        raise HTTPException(413, f"文件过大（{size // 1024 // 1024}MB），请在本地打开")

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        raise HTTPException(400, f"读取失败: {e}")

    return {
        "path": git_manager._normalize_rel_path(path),
        "content": content,
        "size": size,
        "repo": {"key": repo["key"], "name": repo["name"], "vcs": repo["vcs"]},
    }


@router.get("/{project_id}/repos/{key}/file-raw")
async def get_repo_file_raw(project_id: str, key: str, path: str):
    """按仓库根读二进制文件（图片预览用），对标 projects.py 的 /git/file-raw"""
    from fastapi.responses import FileResponse

    repo = await _resolve_repo(project_id, key)
    target = _safe_join(repo["path"], path)
    if not target.is_file():
        raise HTTPException(404, "文件不存在")
    return FileResponse(str(target))

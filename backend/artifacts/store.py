"""ArtifactStore —— 产物总线。

存储策略：**文件为主 + DB 索引**。
产物内容落盘到项目仓库的约定目录，`artifacts` 表只存 path / kind / mime / size 索引，
`content` 列留 NULL。这样二进制产物（图/音/视频）天然支持，git 可追溯，
大文件不撑爆 SQLite。

与老路径的关系（见 kinds.yaml 的 storage 字段）：
  老路径（orchestrator.py 13 处 db.insert）content 存 result_json，`_build_context`
  反序列化成 context["architecture"] 等。**本模块不碰它们**，只服务新 skill 链。
  两者在同一张表里靠 kind 是否为 NULL 区分。

落盘约定：
    <repo>/artifacts/{req_id[-6:]}/{ticket_id[-6:]}/{kind}/{filename}
与 orchestrator.py:3770 的 docs_prefix (`docs/Reqs/{req_short}/{ticket_short}/`)
同构 —— 按工单聚合便于人工翻看和 git diff 审阅。

方案文档：docs/20261015_01_能力自描述与动态组装框架方案.md §3.6
"""
from __future__ import annotations

import json
import logging
import mimetypes
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from artifacts.kinds import KindRegistryError, get_kind, validate_kind

logger = logging.getLogger("artifacts.store")

# 产物根目录名（相对 repo_path）。与 .gitignore 的 `artifacts/` 一致 ——
# 产物默认不入 git，需要追溯时由项目自行取消忽略。
ARTIFACT_ROOT_DIR = "artifacts"

# 无 requirement_id 的独立工单（见 orchestrator.py:3746 的同名约定）
STANDALONE = "standalone"

# 路径分段长度：取 id 末 6 位。与 docs_prefix / src_prefix 保持一致
_ID_TAIL = 6


class ArtifactStoreError(Exception):
    """产物写入失败（路径越界 / 源文件不存在 / 缺必要上下文）。"""


@dataclass
class ArtifactRef:
    """一条产物索引。rel_path 相对 repo_path，POSIX 分隔符。"""
    id: str
    kind: str
    name: str
    rel_path: str
    abs_path: str
    mime: str = ""
    size: int = 0
    project_id: str = ""
    requirement_id: str = ""
    ticket_id: str = ""
    produced_by: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    # inline 产物（老 Agent 路径）没有文件，内容在 DB content 列里
    inline_content: Optional[str] = None

    @property
    def is_inline(self) -> bool:
        return not self.rel_path and self.inline_content is not None

    @property
    def exists(self) -> bool:
        return bool(self.abs_path) and Path(self.abs_path).is_file()


def artifact_dir(
    *, requirement_id: str, ticket_id: str, kind: str, repo_path: str,
) -> Path:
    """产物目录的绝对路径。skill 的 x-runner.outputs.root 应渲染成同一位置，
    这样 SkillRunner 写出来就在位，put 只需登记、无需搬运。"""
    req_short = (requirement_id or STANDALONE)[-_ID_TAIL:]
    ticket_short = (ticket_id or "unknown")[-_ID_TAIL:]
    return (
        Path(repo_path).resolve()
        / ARTIFACT_ROOT_DIR / req_short / ticket_short / kind
    )


def _safe_filename(name: str, default: str) -> str:
    """取文件名部分并剔除路径穿越。

    name 可能来自 LLM（skill 的 produces glob 命中的文件名），不能信任。
    """
    cleaned = (name or "").replace("\\", "/").split("/")[-1].strip()
    if not cleaned or cleaned in (".", ".."):
        return default
    return cleaned


def _guess_mime(filename: str, kind: str) -> str:
    """优先用 kinds.yaml 声明的 mime —— 它是契约；文件名推断只是兜底。

    反过来（以扩展名为准）会让 skill 改个文件名就悄悄改变 kind 的语义。
    """
    spec = get_kind(kind)
    if spec and spec.mime:
        return spec.mime
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"


class ArtifactStore:
    """产物的写入 / 查询。不持有状态，方法级拿 db。"""

    async def put(
        self,
        *,
        project_id: str,
        ticket_id: str,
        kind: str,
        repo_path: str,
        src_path: str = "",
        content: Union[str, bytes, None] = None,
        filename: str = "",
        name: str = "",
        requirement_id: str = "",
        produced_by: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ArtifactRef:
        """登记一条产物。src_path 与 content 二选一。

        - src_path：文件已落盘（SkillRunner 的常规路径）。在目标目录内 → 原地登记；
          在目录外 → 复制进来再登记。
        - content：直接写（str 按 UTF-8，bytes 原样）。

        kind 未注册直接 raise（第 2 道闸，见 kinds.py）。
        """
        from database import db
        from utils import generate_id, now_iso

        spec = validate_kind(kind)          # 闸门：未注册 → KindRegistryError
        if spec.is_inline:
            raise ArtifactStoreError(
                f"kind '{kind}' 在词表里标记为 inline（老 Agent 路径，内容存 "
                f"artifacts.content 列）。ArtifactStore 只写文件，"
                f"用它登记会让下游 `WHERE type='{kind}'` 取 content 落空"
            )
        if not repo_path or not Path(repo_path).is_dir():
            raise ArtifactStoreError(f"repo_path 无效: {repo_path!r}")
        # 两者同真（都给）或同假（都没给）都是错。注意不能写成
        # `bool(src_path) == (content is None)` —— 那个条件恰好把两种**合法**
        # 情形判成错误（初版就是这么写的，被测试抓到）。
        if bool(src_path) == (content is not None):
            raise ArtifactStoreError("src_path 与 content 必须且只能提供一个")

        target_dir = artifact_dir(
            requirement_id=requirement_id, ticket_id=ticket_id,
            kind=kind, repo_path=repo_path,
        )
        repo_root = Path(repo_path).resolve()

        if src_path:
            src = Path(src_path).resolve()
            if not src.is_file():
                raise ArtifactStoreError(f"源文件不存在: {src_path}")
            fname = _safe_filename(filename or src.name, f"{kind}.bin")
            target = (target_dir / fname).resolve()
            if src != target:
                target_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, target)
        else:
            fname = _safe_filename(filename, f"{kind}.bin")
            target = (target_dir / fname).resolve()
            target_dir.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                target.write_bytes(content)
            else:
                target.write_text(str(content), encoding="utf-8")

        # 越界校验：filename 已清洗过，这里兜 repo_path 本身是符号链接等情况
        try:
            rel = target.relative_to(repo_root).as_posix()
        except ValueError:
            raise ArtifactStoreError(
                f"产物路径越出仓库: {target} 不在 {repo_root} 内"
            ) from None

        size = target.stat().st_size
        artifact_id = generate_id("ART")
        row = {
            "id": artifact_id,
            "project_id": project_id,
            "requirement_id": requirement_id or None,
            "ticket_id": ticket_id or None,
            # type 与 kind **双写**：老读取方（如 actions/write_ux_design.py:58
            # 的 `WHERE type='prd'`）只认 type 列，不双写它们看不到新产物。
            "type": kind,
            "kind": kind,
            "name": name or fname,
            "path": rel,
            "content": None,              # file 存储：内容在磁盘，不入库
            "mime": _guess_mime(fname, kind),
            "size_bytes": size,
            "produced_by": produced_by or None,
            "metadata": json.dumps(metadata, ensure_ascii=False) if metadata else None,
            "created_at": now_iso(),
        }
        await db.insert("artifacts", row)
        logger.info("📦 artifact 登记: %s kind=%s size=%d path=%s",
                    artifact_id, kind, size, rel)

        return ArtifactRef(
            id=artifact_id, kind=kind, name=row["name"],
            rel_path=rel, abs_path=str(target),
            mime=row["mime"], size=size,
            project_id=project_id, requirement_id=requirement_id,
            ticket_id=ticket_id, produced_by=produced_by,
            metadata=metadata or {}, created_at=row["created_at"],
        )

    async def get(self, artifact_id: str, *, repo_path: str = "") -> Optional[ArtifactRef]:
        from database import db
        row = await db.fetch_one("SELECT * FROM artifacts WHERE id = ?", (artifact_id,))
        return _row_to_ref(row, repo_path) if row else None

    async def list(
        self,
        *,
        ticket_id: str = "",
        requirement_id: str = "",
        project_id: str = "",
        kinds: Optional[List[str]] = None,
        latest_per_kind: bool = False,
        repo_path: str = "",
        include_legacy: bool = True,
    ) -> List[ArtifactRef]:
        """按工单/需求/项目查产物，created_at 倒序（最新在前）。

        include_legacy=True 时也返回老 Agent 写的 inline 产物
        （kind 列为 NULL，靠 COALESCE(kind, type) 取语义）。
        """
        from database import db

        where, params = [], []
        if ticket_id:
            where.append("ticket_id = ?"); params.append(ticket_id)
        if requirement_id:
            where.append("requirement_id = ?"); params.append(requirement_id)
        if project_id:
            where.append("project_id = ?"); params.append(project_id)
        if not where:
            raise ArtifactStoreError(
                "list 至少需要 ticket_id / requirement_id / project_id 之一"
            )
        if kinds:
            # 存量 2246 条的 kind 全是 NULL，只查 kind 列会漏掉所有老产物
            placeholders = ", ".join("?" * len(kinds))
            where.append(f"COALESCE(kind, type) IN ({placeholders})")
            params.extend(kinds)
        if not include_legacy:
            where.append("kind IS NOT NULL")

        rows = await db.fetch_all(
            f"SELECT * FROM artifacts WHERE {' AND '.join(where)} "
            f"ORDER BY created_at DESC, id DESC",
            tuple(params),
        )
        refs = [_row_to_ref(r, repo_path) for r in rows]

        if latest_per_kind:
            seen, deduped = set(), []
            for ref in refs:                       # 已按时间倒序，首次命中即最新
                if ref.kind in seen:
                    continue
                seen.add(ref.kind)
                deduped.append(ref)
            return deduped
        return refs

    async def read_text(self, ref: ArtifactRef, *, max_chars: int = 0) -> str:
        """读文本内容。inline 产物从 DB 的 content 取，file 产物读磁盘。

        二进制产物返回空串 —— 调用方应检查 ref.mime / kinds.yaml 的 binary 标记，
        而不是指望这里把 PNG 解码成字符串（那正是改造前 SkillRunner 的 bug）。
        """
        if ref.is_inline:
            text = ref.inline_content or ""
        else:
            spec = get_kind(ref.kind)
            if spec and spec.binary:
                return ""
            p = Path(ref.abs_path)
            if not p.is_file():
                logger.warning("artifact 文件缺失: %s (%s)", ref.abs_path, ref.id)
                return ""
            try:
                text = p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                logger.warning("artifact %s 非 UTF-8 文本，跳过读取", ref.id)
                return ""
        return text[:max_chars] if max_chars and len(text) > max_chars else text

    async def put_ticket_brief(
        self, *, project_id: str, ticket_id: str, repo_path: str,
        requirement_id: str = "", extra: Optional[Dict[str, Any]] = None,
    ) -> Optional[ArtifactRef]:
        """产出 `ticket_brief` —— skill 链的天然源（kinds.yaml builtin: true）。

        没有它，所有 consumes ticket_brief 的 skill 都会因「缺源」被剔除，
        整条链直接空掉。所以这是 SkillAgent 跑第一个 skill 之前的必要前置。

        幂等：已存在则直接返回，不重复写（返工重跑时需求快照不应变）。
        """
        existing = await self.list(
            ticket_id=ticket_id, kinds=["ticket_brief"],
            latest_per_kind=True, repo_path=repo_path, include_legacy=False,
        )
        if existing:
            return existing[0]

        from database import db
        ticket = await db.fetch_one("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
        if not ticket:
            logger.warning("put_ticket_brief: 工单不存在 %s", ticket_id)
            return None

        project = await db.fetch_one(
            "SELECT traits FROM projects WHERE id = ?", (project_id,)
        )
        try:
            traits = json.loads((project or {}).get("traits") or "[]")
        except Exception:
            traits = []

        brief = {
            "ticket_id": ticket_id,
            "title": ticket.get("title") or "",
            "description": ticket.get("description") or "",
            "type": ticket.get("type") or "",
            "module": ticket.get("module") or "",
            "requirement_id": requirement_id or ticket.get("requirement_id") or "",
            "project_traits": traits,
            **(extra or {}),
        }
        return await self.put(
            project_id=project_id, ticket_id=ticket_id,
            requirement_id=requirement_id or ticket.get("requirement_id") or "",
            kind="ticket_brief", repo_path=repo_path,
            content=json.dumps(brief, ensure_ascii=False, indent=2),
            filename="brief.json", name="工单简报",
            produced_by="ArtifactStore",
        )


def _row_to_ref(row: Dict[str, Any], repo_path: str = "") -> ArtifactRef:
    """DB 行 → ArtifactRef。兼容两套存储形态。

    老产物（kind 为 NULL）用 type 当 kind，内容塞 inline_content。
    """
    kind = row.get("kind") or row.get("type") or ""
    rel = row.get("path") or ""
    abs_path = ""
    if rel and repo_path:
        abs_path = str((Path(repo_path) / rel).resolve())
    try:
        metadata = json.loads(row["metadata"]) if row.get("metadata") else {}
    except Exception:
        metadata = {}
    return ArtifactRef(
        id=row.get("id") or "",
        kind=kind,
        name=row.get("name") or "",
        rel_path=rel,
        abs_path=abs_path,
        mime=row.get("mime") or "",
        size=row.get("size_bytes") or 0,
        project_id=row.get("project_id") or "",
        requirement_id=row.get("requirement_id") or "",
        ticket_id=row.get("ticket_id") or "",
        produced_by=row.get("produced_by") or "",
        metadata=metadata,
        created_at=row.get("created_at") or "",
        inline_content=row.get("content"),
    )


# 模块级单例，与 db / git_manager 一致
artifact_store = ArtifactStore()

from __future__ import annotations

import json
import os
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .memory_config import MemoryConfig
from .memory_events import append_event
from .memory_key_documents import KEY_DOCUMENT_KEYS, rebuild_key_documents
from .memory_locks import LockTimeoutError, file_lock
from .memory_request_id import content_sha, new_request_id
from .memory_result import error_result, ok_result

_STATE_REL = Path(".ai-memory") / "key_document_rebuild_jobs.json"
_WORKER_REL = Path(".ai-memory") / "key_document_rebuild_worker.lock"
_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state_path(config: MemoryConfig) -> Path:
    return config.repo_root / _STATE_REL


def _worker_path(config: MemoryConfig) -> Path:
    return config.repo_root / _WORKER_REL


def _empty_state() -> dict[str, Any]:
    return {"version": _VERSION, "jobs": {}, "queue": []}


def _read_state(path: Path) -> dict[str, Any]:
    try:
        if not path.is_file():
            return _empty_state()
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return _empty_state()
    if not isinstance(data, dict):
        return _empty_state()
    data.setdefault("version", _VERSION)
    data.setdefault("jobs", {})
    data.setdefault("queue", [])
    if not isinstance(data["jobs"], dict):
        data["jobs"] = {}
    if not isinstance(data["queue"], list):
        data["queue"] = []
    return data


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp-{new_request_id().replace('-', '')}")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _clean_targets(targets: list[str] | None) -> list[str]:
    values = targets or list(KEY_DOCUMENT_KEYS)
    cleaned = [str(item).strip() for item in values if str(item).strip() in KEY_DOCUMENT_KEYS]
    return list(dict.fromkeys(cleaned)) or list(KEY_DOCUMENT_KEYS)


def _scope_key(*, user: str | None, renderer: str, guard_prefer_llm: bool) -> str:
    return f"user={user or ''}|renderer={renderer}|guard_llm={int(bool(guard_prefer_llm))}"


def _is_record_source(rel_path: str) -> bool:
    rel = rel_path.replace("\\", "/").strip("/")
    if not rel.startswith("memory-bank/") or not rel.endswith(".md"):
        return False
    excluded = {
        "memory-bank/teamContext.md",
        "memory-bank/progress.md",
        "memory-bank/techContext.md",
        "memory-bank/systemPatterns.md",
        "memory-bank/projectbrief.md",
    }
    if rel in excluded or rel.startswith("memory-bank/activeContext/"):
        return False
    if rel.startswith("memory-bank/compiled/") or rel.startswith("memory-bank/archive/manual-edits/"):
        return False
    if rel.startswith("memory-bank/archive/activeContext/"):
        return False
    return True


def corpus_watermark(config: MemoryConfig) -> str:
    root = config.repo_root.resolve()
    bank = root / "memory-bank"
    parts: list[str] = []
    if bank.is_dir():
        for path in sorted(bank.rglob("*.md")):
            try:
                rel = path.resolve().relative_to(root).as_posix()
            except ValueError:
                continue
            if not _is_record_source(rel):
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            parts.append(f"{rel}:{stat.st_size}:{stat.st_mtime_ns}")
    return content_sha("\n".join(parts))


def _find_pending_job(state: dict[str, Any], scope_key: str) -> dict[str, Any] | None:
    jobs = state.get("jobs", {})
    for job_id in state.get("queue", []):
        job = jobs.get(str(job_id))
        if isinstance(job, dict) and job.get("status") == "pending" and job.get("scope_key") == scope_key:
            return job
    return None


def enqueue_key_document_rebuild(
    config: MemoryConfig,
    *,
    targets: list[str],
    user: str | None,
    renderer: str,
    guard_prefer_llm: bool,
    phase: str | None = None,
    layer: str | None = None,
    trigger: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Persist or coalesce an async key-document rebuild job."""

    selected_targets = _clean_targets(targets)
    watermark = corpus_watermark(config)
    scope_key = _scope_key(user=user, renderer=renderer, guard_prefer_llm=guard_prefer_llm)
    path = _state_path(config)
    with file_lock(config.repo_root, path):
        state = _read_state(path)
        job = _find_pending_job(state, scope_key)
        now = _now()
        if job is not None:
            existing_targets = _clean_targets(job.get("targets") if isinstance(job.get("targets"), list) else [])
            job["targets"] = _clean_targets(existing_targets + selected_targets)
            job["source_watermark"] = watermark
            job["updated_at"] = now
            job["phase"] = phase or job.get("phase")
            job["layer"] = layer or job.get("layer")
            job["trigger"] = trigger or job.get("trigger")
            if reason:
                job["reason"] = reason
            _write_state(path, state)
            append_event(config, "key_document_rebuild_queued", {"job_id": job.get("job_id"), "coalesced": True, "targets": job.get("targets")})
            return ok_result(
                "key-document rebuild job coalesced",
                queued=True,
                coalesced=True,
                job_id=job.get("job_id"),
                targets=job.get("targets"),
                user=user,
                source_watermark=watermark,
            )

        job_id = "kdj_" + new_request_id().replace("-", "")
        job = {
            "job_id": job_id,
            "status": "pending",
            "scope_key": scope_key,
            "targets": selected_targets,
            "user": user,
            "renderer": renderer,
            "guard_prefer_llm": bool(guard_prefer_llm),
            "phase": phase,
            "layer": layer,
            "trigger": trigger,
            "reason": reason,
            "source_watermark": watermark,
            "created_at": now,
            "updated_at": now,
            "attempts": 0,
        }
        state["jobs"][job_id] = job
        state["queue"].append(job_id)
        _write_state(path, state)
    append_event(config, "key_document_rebuild_queued", {"job_id": job_id, "coalesced": False, "targets": selected_targets})
    return ok_result(
        "key-document rebuild job queued",
        queued=True,
        coalesced=False,
        job_id=job_id,
        targets=selected_targets,
        user=user,
        source_watermark=watermark,
    )


def _claim_next(config: MemoryConfig, worker_id: str) -> dict[str, Any] | None:
    path = _state_path(config)
    with file_lock(config.repo_root, path):
        state = _read_state(path)
        queue = [str(item) for item in state.get("queue", [])]
        while queue:
            job_id = queue.pop(0)
            job = state.get("jobs", {}).get(job_id)
            if not isinstance(job, dict) or job.get("status") != "pending":
                continue
            job["status"] = "running"
            job["started_at"] = _now()
            job["worker_id"] = worker_id
            job["attempts"] = int(job.get("attempts") or 0) + 1
            state["queue"] = queue
            _write_state(path, state)
            return dict(job)
        state["queue"] = queue
        _write_state(path, state)
    return None


def _complete_job(config: MemoryConfig, job: dict[str, Any], result: dict[str, Any], *, stale: bool) -> None:
    path = _state_path(config)
    with file_lock(config.repo_root, path):
        state = _read_state(path)
        stored = state.get("jobs", {}).get(str(job.get("job_id")))
        if not isinstance(stored, dict):
            return
        stored["status"] = "stale" if stale and result.get("ok") else "done" if result.get("ok") else "failed"
        stored["finished_at"] = _now()
        stored["stale_at_publish"] = stale
        stored["result"] = {
            "ok": bool(result.get("ok")),
            "error": result.get("error"),
            "request_id": result.get("request_id"),
            "written": sorted((result.get("written") or {}).keys()),
            "errors": sorted((result.get("errors") or {}).keys()),
        }
        _write_state(path, state)


def drain_key_document_rebuild_jobs(
    config: MemoryConfig,
    *,
    max_jobs: int = 1,
    worker_id: str | None = None,
) -> dict[str, Any]:
    """Run queued key-document rebuild jobs sequentially.

    A single worker lock prevents older slow jobs from publishing after a newer
    job has already completed in another process. Enqueueing remains available
    while this worker is rebuilding.
    """

    worker = worker_id or f"{socket.gethostname()}:{os.getpid()}"
    processed: list[dict[str, Any]] = []
    limit = max(1, int(max_jobs or 1))
    try:
        with file_lock(config.repo_root, _worker_path(config), timeout=0.1):
            for _ in range(limit):
                job = _claim_next(config, worker)
                if job is None:
                    break
                result = rebuild_key_documents(
                    config,
                    targets=_clean_targets(job.get("targets") if isinstance(job.get("targets"), list) else []),
                    user=str(job["user"]) if job.get("user") is not None else None,
                    renderer=str(job.get("renderer") or "deterministic"),
                    guard_prefer_llm=bool(job.get("guard_prefer_llm", False)),
                )
                current_watermark = corpus_watermark(config)
                stale = current_watermark != str(job.get("source_watermark") or "")
                _complete_job(config, job, result, stale=stale)
                item = {
                    "job_id": job.get("job_id"),
                    "ok": bool(result.get("ok")),
                    "stale_at_publish": stale,
                    "targets": job.get("targets"),
                    "result": result,
                }
                processed.append(item)
                append_event(config, "key_document_rebuild_job_finished", {k: v for k, v in item.items() if k != "result"}, status="ok" if result.get("ok") else "error")
                if stale and result.get("ok"):
                    enqueue_key_document_rebuild(
                        config,
                        targets=_clean_targets(job.get("targets") if isinstance(job.get("targets"), list) else []),
                        user=str(job["user"]) if job.get("user") is not None else None,
                        renderer=str(job.get("renderer") or "deterministic"),
                        guard_prefer_llm=bool(job.get("guard_prefer_llm", False)),
                        phase=str(job.get("phase") or "") or None,
                        layer=str(job.get("layer") or "") or None,
                        trigger="stale_requeue",
                        reason="source watermark changed while rebuild job was running",
                    )
    except LockTimeoutError as exc:
        return error_result("worker_busy", str(exc), processed=processed)
    return ok_result("key-document rebuild queue drained", processed=len(processed), jobs=processed)


def read_key_document_rebuild_jobs(config: MemoryConfig) -> dict[str, Any]:
    state = _read_state(_state_path(config))
    jobs = state.get("jobs", {})
    queue = state.get("queue", [])
    return ok_result("key-document rebuild jobs read", queue=queue, jobs=jobs)


__all__ = [
    "corpus_watermark",
    "drain_key_document_rebuild_jobs",
    "enqueue_key_document_rebuild",
    "read_key_document_rebuild_jobs",
]
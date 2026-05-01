"""
ImageProcessor — LightAI 图片生成后台处理器

负责：
1. 轮询 image_requests 表中 pending 的请求
2. 调用 LightAI API（create_async_task → poll task_status）
3. 下载生成的图片 → 保存到 G_ArtRes 资产库
4. 替换项目文档中的 [IMG_PENDING:id] 占位符
5. 推送 SSE 事件通知前端刷新

支持的引擎（来自 LightAI 公开技能）：
  gemini   → nano-banana pro（推荐，model: gemini-3-pro-image-preview）
  gemini2  → nano-banana2（更快，model: gemini-3.1-flash-image-preview）
  jimeng   → 即梦（model: doubao-seedream-5-0-260128）
  midjourney → Midjourney v6
"""
import asyncio
import json
import logging
import os
import ssl
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

from config import settings
from database import db
from utils import generate_id, now_iso

logger = logging.getLogger("image_processor")

# ── SSL（禁用证书验证，与 LightAI _common.py 一致）────────
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

# 引擎 → API 参数映射
_ENGINE_CONFIG = {
    "gemini": {
        "service_name": "foreign",
        "api_name": "Genai-banana2img",
        "model": "gemini-3-pro-image-preview",
        "poll_interval": 15,
        "max_wait": 600,
    },
    "gemini2": {
        "service_name": "foreign",
        "api_name": "Genai-banana2img",
        "model": "gemini-3.1-flash-image-preview",
        "poll_interval": 10,
        "max_wait": 300,
    },
    "jimeng": {
        "service_name": "volces_ark",
        "api_name": "image40_generate",
        "model": "doubao-seedream-5-0-260128",
        "poll_interval": 8,
        "max_wait": 180,
    },
    "midjourney": {
        "service_name": "Midjoumey",
        "api_name": "text2img",
        "model": "v6",
        "poll_interval": 15,
        "max_wait": 600,
    },
}


def _lightai_headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.LIGHTAI_API_KEY}",
        "Content-Type": "application/json",
    }


def _lightai_post(path: str, body: dict, timeout: int = 60) -> dict:
    """同步调用 LightAI API（在 asyncio 线程池里运行）"""
    url = f"{settings.LIGHTAI_API_BASE.rstrip('/')}{path}"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers=_lightai_headers())
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _lightai_get(path: str, timeout: int = 30) -> dict:
    url = f"{settings.LIGHTAI_API_BASE.rstrip('/')}{path}"
    req = urllib.request.Request(url, method="GET", headers=_lightai_headers())
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _extract_image_urls(result: dict) -> list:
    """从 LightAI 任务结果中提取图片 URL（兼容多种响应格式）"""
    urls = []
    data = result.get("data", result)
    if isinstance(data, dict):
        for list_key in ("images", "results"):
            items = data.get(list_key, [])
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        url = item.get("url") or item.get("image_url", "")
                        if url:
                            urls.append(url)
                    elif isinstance(item, str) and item.startswith("http"):
                        urls.append(item)
        for key in ("url", "image_url", "output_url"):
            val = data.get(key, "")
            if isinstance(val, str) and val.startswith("http"):
                urls.append(val)
        inner = data.get("result", {})
        if isinstance(inner, dict):
            for key in ("url", "image_url", "output_url"):
                val = inner.get(key, "")
                if isinstance(val, str) and val.startswith("http"):
                    urls.append(val)
    return list(dict.fromkeys(urls))  # 去重保序


async def _create_lightai_task(req: dict) -> Optional[str]:
    """提交生图任务，返回 task_id"""
    engine = req.get("engine") or settings.LIGHTAI_IMAGE_ENGINE
    cfg = _ENGINE_CONFIG.get(engine, _ENGINE_CONFIG["gemini"])

    task_json: dict = {"model": cfg["model"], "prompt": req["prompt"]}

    if engine in ("gemini", "gemini2"):
        if req.get("aspect_ratio"):
            task_json["aspect_ratio"] = req["aspect_ratio"]
        task_json["image_size"] = req.get("image_size", "2K")
    elif engine == "jimeng":
        task_json["size"] = req.get("image_size", "2K")
        task_json["watermark"] = False
    elif engine == "midjourney":
        task_json = {"text": req["prompt"]}
        if req.get("aspect_ratio"):
            task_json["aspect_ratio"] = req["aspect_ratio"]

    payload = {
        "service_name": cfg["service_name"],
        "api_name": cfg["api_name"],
        "app_info": {"model": cfg["model"], "mode": ""},
        "task_query": {"path": {}, "params": {}, "json": task_json, "data": {}, "file": {}},
        "custom_data": {},
    }

    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _lightai_post("/api/lightai/create_async_task", payload)
        )
        task_id = (result.get("task_id") or result.get("taskId") or
                   result.get("data", {}).get("task_id") or
                   result.get("data", {}).get("taskId", ""))
        logger.info("LightAI 任务已提交: %s (engine=%s)", task_id, engine)
        return task_id or None
    except Exception as e:
        logger.warning("LightAI 创建任务失败: %s", e)
        return None


async def _poll_lightai_task(task_id: str, engine: str) -> Optional[str]:
    """轮询任务直到完成，返回第一张图片 URL"""
    cfg = _ENGINE_CONFIG.get(engine, _ENGINE_CONFIG["gemini"])
    interval = cfg["poll_interval"]
    max_wait = cfg["max_wait"]
    elapsed = 0

    await asyncio.sleep(interval)
    elapsed += interval

    while elapsed <= max_wait:
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None, lambda: _lightai_get(f"/api/lightai/get_task_status/{task_id}")
            )
            status = result.get("status")
            logger.debug("LightAI poll task=%s status=%s", task_id, status)

            if status == 2:  # 成功
                urls = _extract_image_urls(result)
                return urls[0] if urls else None

            if status is not None and (status < 0 or status >= 3):
                logger.warning("LightAI 任务失败: task=%s msg=%s", task_id, result.get("message", ""))
                return None

        except Exception as e:
            logger.warning("LightAI 轮询异常: %s", e)

        await asyncio.sleep(interval)
        elapsed += interval

    logger.warning("LightAI 任务超时: task=%s", task_id)
    return None


async def _download_image(url: str, save_dir: Path, filename: str) -> Optional[str]:
    """下载图片到资产库目录，返回相对路径"""
    save_dir.mkdir(parents=True, exist_ok=True)
    save_path = save_dir / filename

    def _do_download():
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60, context=_SSL_CTX) as resp:
            data = resp.read()
        save_path.write_bytes(data)

    try:
        await asyncio.get_event_loop().run_in_executor(None, _do_download)
        return str(save_path)
    except Exception as e:
        logger.warning("下载图片失败 %s: %s", url, e)
        return None


async def _generate_ascii_fallback(prompt: str) -> str:
    """调用 LLM 生成 ASCII 图作为兜底"""
    try:
        from llm_client import llm_client
        resp = await llm_client.generate(
            f"用 ASCII 艺术画出以下描述，20行以内，不要加解释：{prompt[:100]}"
        )
        return resp[:500]
    except Exception:
        return f"[ASCII Art: {prompt[:50]}]"


async def process_image_request(req_id: str) -> None:
    """处理单个图片请求的完整流程"""
    req = await db.fetch_one("SELECT * FROM image_requests WHERE id = ?", (req_id,))
    if not req:
        return

    logger.info("开始处理图片请求: %s (prompt: %s...)", req_id, req["prompt"][:30])

    # 标记处理中
    await db.update("image_requests", {"status": "processing", "updated_at": now_iso()}, "id = ?", (req_id,))

    # 检查 API Key
    if not settings.LIGHTAI_API_KEY:
        logger.warning("LIGHTAI_API_KEY 未配置，使用 ASCII 兜底: %s", req_id)
        await _finish_with_ascii(req)
        return

    # 提交任务
    task_id = await _create_lightai_task(dict(req))
    if not task_id:
        await _finish_with_ascii(req)
        return

    # 记录 task_id
    await db.update("image_requests", {"lightai_task_id": task_id, "updated_at": now_iso()}, "id = ?", (req_id,))

    # 轮询结果
    engine = req.get("engine") or settings.LIGHTAI_IMAGE_ENGINE
    image_url = await _poll_lightai_task(task_id, engine)
    if not image_url:
        await _finish_with_ascii(req)
        return

    # 下载图片到资产库 + 自动入库
    art_assets_path = Path(settings.ART_ASSETS_LOCAL_PATH) if settings.ART_ASSETS_LOCAL_PATH else None
    result_path = None
    if art_assets_path and art_assets_path.exists():
        ext = "png" if "png" in image_url else "jpg"
        filename = f"{req_id}.{ext}"
        save_dir = art_assets_path / "2d" / "generated"
        result_path = await _download_image(image_url, save_dir, filename)

        # P3-4：自动写入 art_assets 表（AI 生图结果入库）
        if result_path:
            await _store_generated_image(req_id, dict(req), result_path, image_url)

    # 替换文档占位符
    if req.get("callback_doc") and req.get("callback_tag") and req.get("project_id"):
        await _replace_placeholder(req, result_path or image_url)

    # 更新状态
    await db.update("image_requests", {
        "status": "done",
        "result_url": image_url,
        "result_path": result_path or "",
        "updated_at": now_iso(),
    }, "id = ?", (req_id,))

    # 推送 SSE
    try:
        from events import event_manager
        if req.get("project_id"):
            await event_manager.publish_to_project(req["project_id"], "image_generated", {
                "request_id": req_id,
                "callback_tag": req.get("callback_tag", ""),
                "result_url": image_url,
                "result_path": result_path or "",
            })
    except Exception:
        pass

    logger.info("图片生成完成: %s → %s", req_id, result_path or image_url[:60])


async def _finish_with_ascii(req: dict) -> None:
    """ASCII 兜底 + 替换占位符"""
    ascii_art = await _generate_ascii_fallback(req.get("prompt", ""))
    if req.get("callback_doc") and req.get("project_id"):
        await _replace_placeholder(req, ascii_art, is_ascii=True)
    await db.update("image_requests", {
        "status": "ascii_fallback",
        "result_path": "(ascii)",
        "updated_at": now_iso(),
    }, "id = ?", (req["id"],))


async def _replace_placeholder(req: dict, content: str, is_ascii: bool = False) -> None:
    """在项目 Git 仓库的文档中替换 [IMG_PENDING:id] 占位符"""
    try:
        from git_manager import git_manager
        project_id = req["project_id"]
        doc_path   = req["callback_doc"]
        tag        = req["callback_tag"]

        if not git_manager.repo_exists(project_id):
            return

        file_content = await git_manager.read_file(project_id, doc_path)
        if not file_content or tag not in file_content:
            return

        if is_ascii:
            replacement = f"\n```\n{content}\n```\n"
        else:
            replacement = f"\n![AI生成图片]({content})\n"

        new_content = file_content.replace(tag, replacement)
        await git_manager.write_file(project_id, doc_path, new_content)
        await git_manager.commit(project_id, f"[ImageAgent] 图片生成完成: {req['id']}", author="ImageAgent")
        logger.info("占位符替换完成: %s in %s", tag, doc_path)
    except Exception as e:
        logger.warning("替换占位符失败: %s", e)


# ── 后台轮询调度器 ─────────────────────────────────────────

async def image_processor_loop(interval: int = 10) -> None:
    """后台循环：每 interval 秒扫描 pending 请求并处理"""
    logger.info("🖼️ 图片处理调度器已启动（轮询间隔 %ds）", interval)
    while True:
        try:
            pending = await db.fetch_all(
                "SELECT id FROM image_requests WHERE status = 'pending' ORDER BY created_at LIMIT 3",
                ()
            )
            for row in pending:
                asyncio.create_task(process_image_request(row["id"]))
        except Exception as e:
            logger.warning("图片处理调度异常: %s", e)
        await asyncio.sleep(interval)


async def _store_generated_image(req_id: str, req: dict, file_path: str, source_url: str) -> None:
    """将 AI 生成的图片写入 art_assets 表和 manifest.json"""
    try:
        import json as _json
        prompt = req.get("prompt", "")[:80]
        style = req.get("style", "illustration") or "illustration"
        rel_path = file_path.replace(str(settings.ART_ASSETS_LOCAL_PATH), "").lstrip("/\\").replace("\\", "/")
        ext = rel_path.split(".")[-1].lower() if "." in rel_path else "jpg"
        tags = _json.dumps(["ai_generated", style] + prompt.split()[:3], ensure_ascii=False)

        await db.execute("""
            INSERT INTO art_assets
            (id, name, description, tags, type, style, format, width, height,
             file_path, source, source_ref, source_url, project_scope, used_count, added_at)
            VALUES (?,?,?,?,?,?,?,0,0,?,'ai_generated',?,?,'global',0,?)
            ON CONFLICT(id) DO UPDATE SET file_path=excluded.file_path
        """, (req_id, prompt, prompt, tags, style, style, ext,
              rel_path, f"lightai:{req_id}", source_url, now_iso()))

        # 更新 manifest.json
        base = Path(settings.ART_ASSETS_LOCAL_PATH)
        mf = base / "manifest.json"
        if mf.exists():
            data = _json.loads(mf.read_text(encoding="utf-8"))
            assets = data.get("assets", [])
            if not any(a["id"] == req_id for a in assets):
                assets.append({
                    "id": req_id, "name": prompt, "path": rel_path,
                    "type": style, "style": "ai_generated", "format": ext,
                    "tags": ["ai_generated", style], "source": "ai_generated",
                    "source_ref": f"lightai:{req_id}", "source_url": source_url,
                    "added_at": now_iso(), "used_count": 0,
                })
                data["assets"] = assets
                mf.write_text(_json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        logger.info("AI生图已入库: %s → %s", req_id, rel_path)
    except Exception as e:
        logger.warning("AI生图入库失败: %s", e)


# ── 公开的请求接口 ────────────────────────────────────────

async def request_image(
    prompt: str,
    project_id: str = "",
    ticket_id: str = "",
    requester: str = "ArtAgent",
    engine: str = "",
    style: str = "",
    aspect_ratio: str = "1:1",
    image_size: str = "2K",
    callback_doc: str = "",
    callback_tag: str = "",
) -> str:
    """提交图片生成请求，返回占位符标签 [IMG_PENDING:id]"""
    req_id = generate_id("IMG")
    tag = f"[IMG_PENDING:{req_id}]"

    await db.insert("image_requests", {
        "id": req_id,
        "project_id": project_id,
        "ticket_id": ticket_id,
        "requester": requester,
        "prompt": prompt,
        "engine": engine or settings.LIGHTAI_IMAGE_ENGINE,
        "style": style,
        "aspect_ratio": aspect_ratio,
        "image_size": image_size,
        "callback_doc": callback_doc,
        "callback_tag": tag,
        "status": "pending",
        "created_at": now_iso(),
        "updated_at": now_iso(),
    })

    logger.info("图片请求已入队: %s (%s...)", req_id, prompt[:30])
    return tag

"""准备并保存全局 LLM 设置；主配置成功后才更新运行时，技能同步允许失败。"""
import json
import logging
from pathlib import Path


logger = logging.getLogger(__name__)
_CLIENT_FIELDS = ("api_format", "base_url", "api_key", "model", "timeout", "max_retries",
                  "cli_type", "cli_cmd", "cli_model", "cli_timeout")
_SKILL_HOSTS = (".codebuddy", ".workbuddy", ".claude")


def _client_values(client, body: dict) -> dict:
    values = {key: getattr(client, key) for key in _CLIENT_FIELDS}
    if "api_format" in body:
        values["api_format"] = body["api_format"] or "anthropic"
    if "base_url" in body:
        values["base_url"] = (body["base_url"] or "").rstrip("/")
    if "api_key" in body:
        values["api_key"] = body["api_key"] or ""
    if "model" in body and values["api_format"] != "cli":
        values["model"] = body["model"] or "gpt-4"
    for field in ("timeout", "max_retries", "cli_timeout"):
        if field in body:
            values[field] = int(body[field])
    for field in ("cli_type", "cli_cmd"):
        if field in body:
            values[field] = body[field] or "claude"
    if "cli_model" in body:
        values["cli_model"] = body["cli_model"] or values["model"]
    return values


def _integration_values(body: dict) -> dict:
    updates = {}
    for field in ("pexels_api_key", "lightai_api_key", "lightai_api_base"):
        if body.get(field):
            updates[field.upper()] = body[field]
    if "lightai_engine" in body:
        updates["LIGHTAI_IMAGE_ENGINE"] = body["lightai_engine"] or "gemini"
    if "lightai_timeout" in body:
        updates["LIGHTAI_IMAGE_TIMEOUT"] = int(body["lightai_timeout"] or 300)
    return updates


def _write_env(path: Path, updates: dict) -> None:
    entries = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                entries[key.strip()] = value.strip()
    entries.update(updates)
    path.write_text("".join(f"{key}={value}\n" for key, value in entries.items()), encoding="utf-8")


def _sync_if_installed(path: Path, value: str) -> None:
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["LIGHTAI_API_KEY"] = value
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("同步 LightAI 配置到 %s 失败: %s", path, exc)


async def _sync_installed_skills(value: str) -> None:
    if not value:
        return
    try:
        from database import db

        rows = await db.fetch_all(
            "SELECT p.git_repo_path FROM projects p "
            "JOIN project_packs pp ON pp.project_id = p.id "
            "WHERE pp.pack_name = 'ue5-dev' AND p.git_repo_path IS NOT NULL AND p.git_repo_path != ''"
        )
        for row in rows:
            repo = Path(row["git_repo_path"])
            for suffix in ("packs/ue5-dev/scripts/env.json", "scripts/env.json"):
                for host in _SKILL_HOSTS:
                    _sync_if_installed(repo / host / suffix, value)
        for host in _SKILL_HOSTS:
            _sync_if_installed(Path.home() / host / "skills/lightai-skill/scripts/env.json", value)
    except Exception as exc:
        logger.warning("同步 LightAI 配置失败: %s", exc)


async def save_global_config(body: dict) -> dict:
    from config import BASE_DIR, settings
    from llm_client import llm_client

    client_values = _client_values(llm_client, body)
    changes = {f"LLM_{key.upper()}": value for key, value in client_values.items()}
    changes.update(_integration_values(body))
    disk_values = changes.copy()
    if client_values["api_format"] == "cli":
        # 主模型属于 API：保留文件中原有的一行，原来没有也不要创建。
        del disk_values["LLM_MODEL"]
    _write_env(BASE_DIR / ".env", disk_values)

    for key, value in client_values.items():
        setattr(llm_client, key, value)
    for key, value in changes.items():
        setattr(settings, key, value)

    result = {"status": "ok", "configured": llm_client.is_configured,
              "api_format": llm_client.api_format, "model": llm_client.model,
              "lightai_configured": bool(settings.LIGHTAI_API_KEY)}
    await _sync_installed_skills(settings.LIGHTAI_API_KEY)
    return result

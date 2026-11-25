"""SOP 编辑器的流程视图与配置保存；不依赖 HTTP 或全局编排器。"""
from datetime import datetime
from pathlib import Path
from typing import Callable

from sop.loader import get_sop_metadata, get_sop_stages
from sop.validator import validate_sop_config


class InvalidSopConfig(ValueError):
    def __init__(self, errors):
        super().__init__("SOP 配置校验失败")
        self.errors = errors


class SopSaveError(RuntimeError):
    """YAML 写入或热重载失败。"""


def workflow_view(config, rules):
    if not config:
        return {"metadata": {"name": "内置默认", "version": "1.0"}, "stages": [], "rules": rules}
    return {"metadata": get_sop_metadata(config), "stages": get_sop_stages(config), "rules": rules}


def save_config(body: dict, directory: Path, reload_sop: Callable[[], object]) -> dict:
    errors = validate_sop_config(body)
    if errors:
        raise InvalidSopConfig(errors)

    sop_file = directory / "default_sop.yaml"
    backup_dir = directory / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"default_sop_{datetime.now():%Y%m%d-%H%M%S}.yaml"
    if sop_file.exists():
        backup.write_text(sop_file.read_text(encoding="utf-8"), encoding="utf-8")

    try:
        import yaml
        content = yaml.safe_dump(body, allow_unicode=True, sort_keys=False, indent=2)
        sop_file.write_text(content, encoding="utf-8")
    except Exception as exc:
        raise SopSaveError(f"写入 yaml 失败: {exc}") from exc

    try:
        reload_sop()
    except Exception as exc:
        if backup.exists():
            sop_file.write_text(backup.read_text(encoding="utf-8"), encoding="utf-8")
            reload_sop()
        raise SopSaveError(f"热重载失败（已自动回滚）：{exc}") from exc

    return {"status": "ok", "backup": backup.name, "name": body.get("name", "?"),
            "stages_count": len(body.get("stages") or [])}

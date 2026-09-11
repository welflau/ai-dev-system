"""Shared UEEditorMCP plugin-root configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BRIDGE_HOST = "127.0.0.1"
DEFAULT_BRIDGE_PORT = 55558
CONFIG_FILENAME = "UEEditorMCP.config.json"


@dataclass(frozen=True)
class BridgeConfig:
    host: str = DEFAULT_BRIDGE_HOST
    port: int = DEFAULT_BRIDGE_PORT


def plugin_root() -> Path:
    return Path(__file__).resolve().parents[2]


def config_path() -> Path:
    return plugin_root() / CONFIG_FILENAME


def load_bridge_config() -> BridgeConfig:
    path = config_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return BridgeConfig()

    host = raw.get("bridge_host", DEFAULT_BRIDGE_HOST)
    port = raw.get("bridge_port", DEFAULT_BRIDGE_PORT)
    if not isinstance(host, str) or not host.strip():
        host = DEFAULT_BRIDGE_HOST
    try:
        port = int(port)
    except (TypeError, ValueError):
        port = DEFAULT_BRIDGE_PORT
    if not 1 <= port <= 65535:
        port = DEFAULT_BRIDGE_PORT

    return BridgeConfig(host=host.strip(), port=port)

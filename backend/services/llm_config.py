"""供顶栏和 Agent 配置编辑器展示的 LLM 只读数据。"""


def _display_model(api_format, model, cli_model):
    return (cli_model or model) if api_format == "cli" else model


def _cli_choices():
    from llm_client import _CLI_ADAPTERS, get_cli_model_options

    return {
        "cli_model_options": get_cli_model_options(),
        "cli_default_cmds": {name: adapter["default_cmd"] for name, adapter in _CLI_ADAPTERS.items()},
    }


def status_view():
    from llm_client import llm_client as client

    is_cli = client.api_format == "cli"
    cli_model = client.cli_model if is_cli else None
    return {
        "configured": client.is_configured,
        "api_format": client.api_format,
        "base_url": None if is_cli else client.base_url,
        "model": client.model,
        "display_model": _display_model(client.api_format, client.model, cli_model),
        "timeout": client.timeout,
        "max_retries": client.max_retries,
        "cli_type": client.cli_type if is_cli else None,
        "cli_cmd": client.cli_cmd if is_cli else None,
        "cli_model": cli_model,
        "cli_timeout": client.cli_timeout if is_cli else None,
        **_cli_choices(),
    }


def public_llm_fields(client, has_api_key: bool = False) -> dict:
    """返回编辑器允许展示的字段；凭据只以布尔标记表示。"""
    api_format = getattr(client, "api_format", None)
    model = getattr(client, "model", None)
    cli_model = getattr(client, "cli_model", None)
    return {
        "api_format": api_format,
        "base_url": getattr(client, "base_url", None),
        "model": model,
        "display_model": _display_model(api_format, model, cli_model),
        "cli_type": getattr(client, "cli_type", None),
        "cli_cmd": getattr(client, "cli_cmd", None),
        "cli_model": cli_model,
        "cli_timeout": getattr(client, "cli_timeout", None),
        "has_api_key": has_api_key,
    }


async def agent_config_view():
    from agent_registry import discover_agents, get_registry
    from llm_client import LLMClient, get_agent_llm_config, llm_client

    discover_agents()
    agents = []
    for name in sorted(get_registry()):
        override = await get_agent_llm_config(name)
        if override is None:
            effective = public_llm_fields(llm_client, has_api_key=bool(llm_client.api_key))
        else:
            effective = public_llm_fields(LLMClient(config=override), has_api_key=bool(override.get("api_key")))
        agents.append({"agent_type": name, "has_override": override is not None, "effective": effective})
    return {
        "agents": agents,
        "global": public_llm_fields(llm_client, has_api_key=bool(llm_client.api_key)),
        **_cli_choices(),
    }

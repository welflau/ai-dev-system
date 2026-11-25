"""保存 Agent 工具开关；失败时保留当前进程的设置。"""
import os

from dotenv import set_key

import config


def save_agent_tools_enabled(enabled: bool) -> None:
    value = "true" if enabled else "false"
    # 使用启动时读取的同一份配置，不误改其他变量的多行文本。
    set_key(str(config.ENV_PATH.resolve()), config.AGENT_TOOLS_ENV_KEY, value, quote_mode="never")
    os.environ[config.AGENT_TOOLS_ENV_KEY] = value
    config.settings.ENABLE_AGENT_TOOLS = enabled

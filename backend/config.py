"""
集中化配置管理
通过 .env 文件或环境变量加载配置
"""
import os
from typing import Optional

# 尝试加载 .env 文件（如果 python-dotenv 已安装）
try:
    from dotenv import load_dotenv

    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path)
except ImportError:
    pass


class Settings:
    """应用配置"""

    # --- LLM ---
    LLM_BASE_URL: str = os.getenv(
        "LLM_BASE_URL",
        os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
    )
    LLM_API_KEY: str = os.getenv(
        "LLM_API_KEY",
        os.getenv("OPENAI_API_KEY", ""),
    )
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4")
    LLM_TIMEOUT: float = float(os.getenv("LLM_TIMEOUT", "120"))
    LLM_MAX_RETRIES: int = int(os.getenv("LLM_MAX_RETRIES", "2"))

    # --- App ---
    APP_NAME: str = os.getenv("APP_NAME", "AI Dev System")
    APP_VERSION: str = "0.5.0"
    DEBUG: bool = os.getenv("DEBUG", "False").lower() in ("true", "1", "yes")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # --- Paths ---
    BASE_DIR: str = os.path.dirname(os.path.abspath(__file__))
    PROJECTS_DIR: str = os.path.join(BASE_DIR, "projects")
    DB_PATH: str = os.path.join(BASE_DIR, "ai_dev_system.db")

    @classmethod
    def llm_enabled(cls) -> bool:
        """LLM 是否已配置"""
        return bool(cls.LLM_API_KEY)


settings = Settings()

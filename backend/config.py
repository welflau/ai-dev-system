"""
AI 自动开发系统 - 配置管理
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)


class Settings:
    """应用配置"""

    # Server
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    DEBUG: bool = os.getenv("DEBUG", "true").lower() == "true"

    # Database
    DB_PATH: str = str(DATA_DIR / "ai_dev_system.db")

    # LLM
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "")
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "claude-sonnet-4-20250514")
    LLM_TIMEOUT: int = int(os.getenv("LLM_TIMEOUT", "120"))
    LLM_MAX_RETRIES: int = int(os.getenv("LLM_MAX_RETRIES", "3"))
    LLM_API_FORMAT: str = os.getenv("LLM_API_FORMAT", "anthropic")  # anthropic / openai

    # Agent 技能系统（Tool Use）
    ENABLE_AGENT_TOOLS: bool = os.getenv("ENABLE_AGENT_TOOLS", "false").lower() in ("1", "true", "yes")

    # AI 助手走 ChatAssistantAgent + tool_use 新路径
    # P3 起默认开启；新路径内部异常会自动降级到旧 [ACTION:XXX] 文本协议路径
    # 显式关闭：CHAT_USE_AGENT=0 / false / no
    CHAT_USE_AGENT: bool = os.getenv("CHAT_USE_AGENT", "true").lower() in ("1", "true", "yes")

    # Frontend
    FRONTEND_DIR: str = str(BASE_DIR.parent / "frontend")

    # 全局设计知识库（G_DesignKnowledge）
    GLOBAL_KNOWLEDGE_REPO_URL: str = os.getenv("GLOBAL_KNOWLEDGE_REPO_URL", "")
    GLOBAL_KNOWLEDGE_LOCAL_PATH: str = os.getenv("GLOBAL_KNOWLEDGE_LOCAL_PATH", "")
    GLOBAL_KNOWLEDGE_AUTO_PUSH: bool = os.getenv("GLOBAL_KNOWLEDGE_AUTO_PUSH", "false").lower() in ("1", "true", "yes")

    # 美术资产库（G_ArtRes）
    ART_ASSETS_REPO_URL: str = os.getenv("ART_ASSETS_REPO_URL", "")
    ART_ASSETS_LOCAL_PATH: str = os.getenv("ART_ASSETS_LOCAL_PATH", "")
    ART_ASSETS_AUTO_PUSH: bool = os.getenv("ART_ASSETS_AUTO_PUSH", "false").lower() in ("1", "true", "yes")

    # LightAI 图片生成（ai.lightai.woa.com）
    LIGHTAI_API_BASE: str = os.getenv("LIGHTAI_API_BASE", "https://api.lightai.woa.com")
    LIGHTAI_API_KEY: str = os.getenv("LIGHTAI_API_KEY", "")
    LIGHTAI_IMAGE_ENGINE: str = os.getenv("LIGHTAI_IMAGE_ENGINE", "gemini")   # gemini/gemini2/jimeng/midjourney
    LIGHTAI_IMAGE_TIMEOUT: int = int(os.getenv("LIGHTAI_IMAGE_TIMEOUT", "300"))  # 轮询最大等待秒


settings = Settings()

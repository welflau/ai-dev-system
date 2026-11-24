"""
AI 自动开发系统 - 配置管理
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv, dotenv_values

# PyInstaller 打包后：资源在 sys._MEIPASS，可写数据放 exe 旁
_FROZEN = getattr(sys, "frozen", False)
if _FROZEN:
    _MEIPASS = Path(sys._MEIPASS)
    _APP_DIR = Path(sys.executable).resolve().parent
    load_dotenv(_APP_DIR / ".env")
    load_dotenv(_MEIPASS / ".env", override=False)
    # 可写运行时目录（db / chat_images 等），避免写进只读解压区
    BASE_DIR = _APP_DIR / "runtime"
    BASE_DIR.mkdir(exist_ok=True)
    _FRONTEND_DEFAULT = str(_MEIPASS / "frontend")
else:
    load_dotenv()
    BASE_DIR = Path(__file__).resolve().parent
    _FRONTEND_DEFAULT = str(BASE_DIR.parent / "frontend")

# backend/.env 是权威配置源（image_gen 的 refresh 端点写的就是它）。
# 服务可能从项目根目录启动（start-backend.bat 会 cd 到项目根），此时
# load_dotenv() 加载的是根目录 .env（只有基础 LLM 配置），而 ART_ASSETS_LOCAL_PATH、
# GLOBAL_KNOWLEDGE_LOCAL_PATH、LIGHTAI_* 等都在 backend/.env 里，会读不到。
# 因此这里强制用 backend/.env 覆盖全部非空变量，确保配置一致、可读。
_ENV_PATH = (_APP_DIR if _FROZEN else BASE_DIR) / ".env"
try:
    _dotenv = dotenv_values(str(_ENV_PATH))
    for _k, _v in _dotenv.items():
        if _v:
            os.environ[_k] = _v
except Exception:
    pass

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# 应用版本号的唯一来源：启动日志、FastAPI 文档、/api/health 都读这里。
# 发版时只改这一处，并同步 README 顶部徽章与「版本历史」表。
APP_VERSION = "0.22.0"


class Settings:
    """应用配置"""

    # Server
    # 默认只监听本机回环：全部 API 没有鉴权，监听 0.0.0.0 等于把读写本机文件、
    # 驱动 Agent 跑 shell 的接口开放给整个局域网。确实要给其他机器访问时，
    # 在 backend/.env 里显式写 HOST=0.0.0.0（并自行保证网络环境可信）。
    HOST: str = os.getenv("HOST", "127.0.0.1")
    PORT: int = int(os.getenv("PORT", "8000"))
    DEBUG: bool = os.getenv("DEBUG", "true").lower() == "true"

    # 额外允许的跨域来源，逗号分隔，如 http://192.168.1.10:5173。
    # 本机来源（localhost / 127.0.0.1 / [::1]，任意端口）始终允许，无需配置；
    # 前端与后端同源部署，正常使用不需要填这一项。
    CORS_ALLOW_ORIGINS: list = [
        _o.strip() for _o in os.getenv("CORS_ALLOW_ORIGINS", "").split(",") if _o.strip()
    ]

    # 用户级 ConfigPack 安装：会写 ~/.claude/ 等用户主目录，属高权限操作。
    # 默认关闭；开启后 API 仍仅接受本机（127.0.0.1/::1）请求。见 api/projects.py
    USER_PACK_INSTALL_ENABLED: bool = os.getenv("USER_PACK_INSTALL_ENABLED", "false").lower() in ("1", "true", "yes")

    # Database
    DB_PATH: str = os.getenv("DB_PATH", str(DATA_DIR / "ai_dev_system.db"))

    # LLM
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "")
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "claude-sonnet-4-20250514")
    LLM_TIMEOUT: int = int(os.getenv("LLM_TIMEOUT", "120"))
    LLM_MAX_RETRIES: int = int(os.getenv("LLM_MAX_RETRIES", "3"))
    LLM_API_FORMAT: str = os.getenv("LLM_API_FORMAT", "anthropic")  # anthropic / openai / cli

    # OpenSpec 四件套生成：每件 LLM 调用的独立超时（秒）。
    # LLM 资源被占时会排队，无上限会静默拖死后台 propose；超时则跳过该件继续。
    OPENSPEC_ARTIFACT_TIMEOUT: int = int(os.getenv("OPENSPEC_ARTIFACT_TIMEOUT", "90"))

    # LLM CLI 模式（LLM_API_FORMAT=cli 时生效）
    LLM_CLI_TYPE:    str = os.getenv("LLM_CLI_TYPE",    "claude")   # claude / codebuddy / cursor / custom
    LLM_CLI_CMD:     str = os.getenv("LLM_CLI_CMD",     "claude")   # 可执行文件名或完整路径（cursor 默认 agent）
    LLM_CLI_MODEL:   str = os.getenv("LLM_CLI_MODEL",   "")         # 留空则复用 LLM_MODEL
    LLM_CLI_TIMEOUT: int = int(os.getenv("LLM_CLI_TIMEOUT", "1800")) # 子进程超时（秒），UBT/hy3等长任务需要更长时间

    # Agent 技能系统（Tool Use）
    ENABLE_AGENT_TOOLS: bool = os.getenv("ENABLE_AGENT_TOOLS", "false").lower() in ("1", "true", "yes")

    # AI 助手走 ChatAssistantAgent + tool_use 新路径
    # P3 起默认开启；新路径内部异常会自动降级到旧 [ACTION:XXX] 文本协议路径
    # 显式关闭：CHAT_USE_AGENT=0 / false / no
    CHAT_USE_AGENT: bool = os.getenv("CHAT_USE_AGENT", "true").lower() in ("1", "true", "yes")

    # Frontend（打包后指向 _MEIPASS/frontend）
    FRONTEND_DIR: str = os.getenv("FRONTEND_DIR", _FRONTEND_DEFAULT)

    # 全局设计知识库（G_DesignKnowledge）
    GLOBAL_KNOWLEDGE_REPO_URL: str = os.getenv("GLOBAL_KNOWLEDGE_REPO_URL", "")
    GLOBAL_KNOWLEDGE_LOCAL_PATH: str = os.getenv("GLOBAL_KNOWLEDGE_LOCAL_PATH", "")
    GLOBAL_KNOWLEDGE_AUTO_PUSH: bool = os.getenv("GLOBAL_KNOWLEDGE_AUTO_PUSH", "false").lower() in ("1", "true", "yes")

    # 美术资产库（G_ArtRes）
    ART_ASSETS_REPO_URL: str = os.getenv("ART_ASSETS_REPO_URL", "")
    ART_ASSETS_LOCAL_PATH: str = os.getenv("ART_ASSETS_LOCAL_PATH", "")
    ART_ASSETS_AUTO_PUSH: bool = os.getenv("ART_ASSETS_AUTO_PUSH", "false").lower() in ("1", "true", "yes")

    # 资产网络搜索 API（未配置则跳过该来源）
    PEXELS_API_KEY: str = os.getenv("PEXELS_API_KEY", "")
    PIXABAY_API_KEY: str = os.getenv("PIXABAY_API_KEY", "")
    # unDraw / Poly Haven 无需密钥，始终可用

    # LightAI 图片生成（ai.lightai.woa.com）
    LIGHTAI_API_BASE: str = os.getenv("LIGHTAI_API_BASE", "https://api.lightai.woa.com")
    LIGHTAI_API_KEY: str = os.getenv("LIGHTAI_API_KEY", "")
    LIGHTAI_IMAGE_ENGINE: str = os.getenv("LIGHTAI_IMAGE_ENGINE", "gemini")   # gemini/gemini2/jimeng/midjourney
    LIGHTAI_IMAGE_TIMEOUT: int = int(os.getenv("LIGHTAI_IMAGE_TIMEOUT", "300"))  # 轮询最大等待秒
    # 生图最大并发数：LightAI 服务端同一 key 只允许 1 个任务同时在生成，
    # 超出返回 429。本地用信号量串行化，其余任务在队列里等待而非立即失败。
    LIGHTAI_MAX_CONCURRENT: int = int(os.getenv("LIGHTAI_MAX_CONCURRENT", "1"))

    # ── 系统公共云端生视频（供多个 Plugin 适配调用，不属于任何 plugin）──
    # 见 backend/cloud_video/。⚠️ 这是第三方「鼠鼠工具」卡密中转
    # （https://www.runlive.top/mnmx，X-Card-Key），**不是 MiniMax 官方 API**：
    # 无 Bearer / 无 GroupID / 任务名 minimax_h3_v2|minimax_h3_multi_ref。
    # 官方 key 不能填在这里。真实卡密钥只放 backend/.env，不入库。
    MINIMAX_H3_BASE_URL: str = os.getenv("MINIMAX_H3_BASE_URL", "https://www.runlive.top/mnmx")
    MINIMAX_H3_CARD_KEY: str = os.getenv("MINIMAX_H3_CARD_KEY", "")
    MINIMAX_H3_ENABLED: bool = os.getenv("MINIMAX_H3_ENABLED", "false").lower() in ("1", "true", "yes")
    MINIMAX_H3_TIMEOUT: int = int(os.getenv("MINIMAX_H3_TIMEOUT", "120"))       # 单次 HTTP（提交 120s / 查询 30s）
    MINIMAX_H3_POLL_INTERVAL: int = int(os.getenv("MINIMAX_H3_POLL_INTERVAL", "5"))  # 查询限速 1 次/秒，留余量
    MINIMAX_H3_MAX_POLLS: int = int(os.getenv("MINIMAX_H3_MAX_POLLS", "180"))    # 5s × 180 = 15min 上限

    # ── 生成任务排队（时段感知 FIFO 信号量，参考 ComicAI index.ts:2551-2582）──
    # 上游规则：闲时每账号最多 5 个任务在排队/生成，白天不限。
    # 时区显式配置（ComicAI 用浏览器本地时区，服务端不能照抄）；一个名额覆盖提交+轮询全程。
    MINIMAX_H3_QUEUE_ENABLED: bool = os.getenv("MINIMAX_H3_QUEUE_ENABLED", "true").lower() in ("1", "true", "yes")
    MINIMAX_H3_QUEUE_IDLE_LIMIT: int = int(os.getenv("MINIMAX_H3_QUEUE_IDLE_LIMIT", "5"))
    MINIMAX_H3_QUEUE_IDLE_START: int = int(os.getenv("MINIMAX_H3_QUEUE_IDLE_START", "0"))
    MINIMAX_H3_QUEUE_IDLE_END: int = int(os.getenv("MINIMAX_H3_QUEUE_IDLE_END", "8"))
    MINIMAX_H3_QUEUE_TZ: str = os.getenv("MINIMAX_H3_QUEUE_TZ", "Asia/Shanghai")  # IANA 名
    MINIMAX_H3_QUEUE_TZ_OFFSET: float = float(os.getenv("MINIMAX_H3_QUEUE_TZ_OFFSET", "8"))  # ZoneInfo 不可用时回退
    MINIMAX_H3_QUEUE_WAIT_TIMEOUT: float = float(os.getenv("MINIMAX_H3_QUEUE_WAIT_TIMEOUT", "900"))  # 排队超时→blocked

    # VideoClaw sidecar（独立进程，REST + SSE；见 plugins/videoclaw/）
    # 8100 避开 ADS 自身的 8000；ENABLED=false 时插件直接判 env_missing → blocked。
    # 视频生成是分钟级长任务，超时不能复用 LLM_TIMEOUT(120s)。
    VIDEOCLAW_BASE_URL: str = os.getenv("VIDEOCLAW_BASE_URL", "http://127.0.0.1:8100")
    VIDEOCLAW_TIMEOUT: int = int(os.getenv("VIDEOCLAW_TIMEOUT", "600"))
    VIDEOCLAW_VIDEO_TIMEOUT: int = int(os.getenv("VIDEOCLAW_VIDEO_TIMEOUT", "900"))  # 生视频分钟级，单独放宽
    VIDEOCLAW_ENABLED: bool = os.getenv("VIDEOCLAW_ENABLED", "false").lower() in ("1", "true", "yes")

    # ── Phase 1B：预算/配额约束（.env 可覆盖）──────────────────────────
    # 工单 Agent：单次执行预算
    AGENT_MAX_TOKENS:  int   = int(os.getenv("AGENT_MAX_TOKENS",  "200000"))
    AGENT_MAX_TURNS:   int   = int(os.getenv("AGENT_MAX_TURNS",   "50"))
    AGENT_MAX_SECONDS: float = float(os.getenv("AGENT_MAX_SECONDS", "600"))
    # 聊天会话：单次对话预算（复杂架构类问题需要多轮工具调用，300k 更合理）
    CHAT_MAX_TOKENS:   int   = int(os.getenv("CHAT_MAX_TOKENS",   "300000"))
    CHAT_MAX_TURNS:    int   = int(os.getenv("CHAT_MAX_TURNS",    "50"))
    CHAT_MAX_SECONDS:  float = float(os.getenv("CHAT_MAX_SECONDS",  "300"))


settings = Settings()

# trigger reload

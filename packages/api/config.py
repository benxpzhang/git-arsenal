"""
Centralized configuration — reads from environment variables (.env file).
"""
import os
from pathlib import Path
from dotenv import load_dotenv

_project_root = Path(__file__).resolve().parent.parent.parent
load_dotenv(_project_root / ".env")

# ── Infrastructure ──
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_COLLECTION = "repos"
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://arsenal:arsenal@localhost:5432/git_arsenal",
)

# ── Embedding ──
EMBED_API_KEY = os.getenv("EMBED_API_KEY", os.getenv("OPENAI_API_KEY", ""))
EMBED_BASE_URL = os.getenv(
    "EMBED_BASE_URL",
    os.getenv("OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
)
EMBED_MODEL = os.getenv("EMBED_MODEL", os.getenv("EMBEDDING_MODEL", "text-embedding-v4"))
EMBED_DIM = 1024
EMBED_TIMEOUT = int(os.getenv("EMBED_TIMEOUT", "10"))
EMBED_MAX_RETRIES = int(os.getenv("EMBED_MAX_RETRIES", "2"))

# ── LLM (fallback, not used in main search path) ──
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
LLM_MODEL = os.getenv("LLM_MODEL", "glm-4-flash")
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "10"))

# ── Auth ──
JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me")
JWT_EXPIRE_DAYS = int(os.getenv("JWT_EXPIRE_DAYS", "7"))
ANON_DAILY_QUOTA = int(os.getenv("ANON_DAILY_QUOTA", "20"))

# ── Server ──
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8003"))
_cors_raw = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
CORS_ORIGINS: list[str] = [s.strip() for s in _cors_raw.split(",") if s.strip()]

# ── Data ──
_data_base = Path(__file__).resolve().parent / "data"
_data_profile = os.getenv("DATA_PROFILE", "dev")  # dev | product | bak
DATA_DIR = Path(os.getenv("DATA_DIR", str(_data_base / _data_profile)))

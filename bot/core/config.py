"""
bot/core/config.py
~~~~~~~~~~~~~~~~~~
Loads environment variables from a ``.env`` file (if present) and exposes
them as module-level constants used throughout the application.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (two directories up from this file).
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=_ENV_PATH)

# ── Telegram API credentials ────────────────────────────────────────────
API_ID: int = int(os.getenv("API_ID", "0"))
API_HASH: str = os.getenv("API_HASH", "")
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")

# ── RBAC: Owner ID ──────────────────────────────────────────────────────
OWNER_ID: int = int(os.getenv("OWNER_ID", "0"))

# ── Operational tunables ────────────────────────────────────────────────
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
MAX_WORKERS: int = int(os.getenv("MAX_WORKERS", "50"))
STATUS_INTERVAL: int = int(os.getenv("STATUS_INTERVAL", "5"))
DEFAULT_THREADS: int = int(os.getenv("DEFAULT_THREADS", "50"))

# ── Paths ───────────────────────────────────────────────────────────────
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH: str = str(DATA_DIR / "bot.db")
TEMP_DIR = Path(__file__).resolve().parents[2] / "data" / "tmp"
TEMP_DIR.mkdir(parents=True, exist_ok=True)
PROXY_FILE = str(DATA_DIR / "proxies.txt")

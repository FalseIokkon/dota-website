"""
core/config.py

Central configuration loader for environment variables.
Works with both:
- .env (local dev)
- system/cron environment variables
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from repo root
BASE_DIR = Path(__file__).resolve().parent.parent  # repo root
ENV_PATH = BASE_DIR / ".env"

load_dotenv(ENV_PATH)

# ---- Core paths ----
PROJECT_ROOT = Path(os.getenv("PROJECT_ROOT", "")).resolve()

DATA_DIR = Path(os.getenv("DATA_DIR", PROJECT_ROOT / "data")).resolve()
DB_PATH = Path(os.getenv("DB_PATH", DATA_DIR / "dota.db")).resolve()

# ---- External services ----
OPENDOTA_API_KEY = os.getenv("OPENDOTA_API_KEY", "").strip()
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()
DISCORD_GUILD_ID = os.getenv("DISCORD_GUILD_ID", "").strip()

# ---- Optional sanity checks (recommended) ----
if not DB_PATH.exists():
    print(f"[WARN] DB_PATH does not exist: {DB_PATH}")

if not PROJECT_ROOT:
    print("[WARN] PROJECT_ROOT is not set")

# ---- Convenience (string versions if needed) ----
PROJECT_ROOT_STR = str(PROJECT_ROOT)
DATA_DIR_STR = str(DATA_DIR)
DB_PATH_STR = str(DB_PATH)
"""
config.py

Central configuration loader for environment variables.
Works with both:
- .env (local dev)
- system/cron environment variables
"""

import os
from dotenv import load_dotenv
from pathlib import Path

# Load .env from same directory as this file
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# Core paths
PROJECT_ROOT = os.getenv("PROJECT_ROOT", "")
BACKEND_DIR = f"{PROJECT_ROOT}/backend"
DATA_DIR = os.getenv("DATA_DIR", f"{BACKEND_DIR}/data")

# API / external
OPENDOTA_API_KEY = os.getenv("OPENDOTA_API_KEY", "").strip()
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
"""
QVC Appointment Booking Bot - Configuration
Loads settings from .env file and provides typed constants.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
_PROJECT_DIR = Path(__file__).parent
load_dotenv(_PROJECT_DIR / ".env")


# --- Telegram ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

_raw_chat_id = os.getenv("TELEGRAM_CHAT_ID", "0")
try:
    TELEGRAM_CHAT_ID = int(_raw_chat_id)
except ValueError:
    TELEGRAM_CHAT_ID = 0  # Will be caught by validation in main.py

# --- Telegram API URL (Cloudflare Worker proxy — most reliable) ---
# If set, the bot routes all Telegram API calls through this URL
# Deploy the worker from telegram-proxy-worker.js to get this URL
TELEGRAM_API_URL = os.getenv("TELEGRAM_API_URL", "")

# --- HTTP Proxy (fallback if no Cloudflare Worker) ---
# Formats: "socks5://127.0.0.1:1080", "http://127.0.0.1:8080", "https://proxy:port"
PROXY_URL = os.getenv("PROXY_URL", "")

# --- QVC ---
QVC_URL = os.getenv("QVC_URL", "https://www.qatarvisacenter.com")

# --- Applicant Details (for auto-fill on recovery) ---
PASSPORT_NUMBER = os.getenv("PASSPORT_NUMBER", "")
VISA_REF_NUMBER = os.getenv("VISA_REF_NUMBER", "")
MOBILE_NUMBER = os.getenv("MOBILE_NUMBER", "")
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS", "")

# --- CAPTCHA Mode ---
# "telegram" = screenshot sent to Telegram, reply typed into field
# "manual"   = notification sent, user solves in browser
CAPTCHA_MODE = os.getenv("CAPTCHA_MODE", "telegram")

# --- Timing (seconds) ---
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "0.8"))
BURST_POLL_INTERVAL = float(os.getenv("BURST_POLL_INTERVAL", "0.3"))
BURST_DURATION = float(os.getenv("BURST_DURATION", "30"))
BURST_ERROR_THRESHOLD = int(os.getenv("BURST_ERROR_THRESHOLD", "3"))
BURST_ERROR_WINDOW = float(os.getenv("BURST_ERROR_WINDOW", "10"))
KEEPALIVE_INTERVAL = float(os.getenv("KEEPALIVE_INTERVAL", "40"))
CAPTCHA_TIMEOUT = float(os.getenv("CAPTCHA_TIMEOUT", "120"))

# --- Paths (relative to project directory, not CWD) ---
_screenshot_env = os.getenv("SCREENSHOT_DIR", "")
if _screenshot_env:
    SCREENSHOT_DIR = Path(_screenshot_env)
else:
    SCREENSHOT_DIR = _PROJECT_DIR / "screenshots"

# --- Browser ---
BROWSER_SLOW_MO = int(os.getenv("BROWSER_SLOW_MO", "50"))  # ms between actions


def ensure_dirs():
    """Create required directories. Called from main.py, not at import time."""
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

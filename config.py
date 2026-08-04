import os

from dotenv import load_dotenv

load_dotenv()

# Read but do not validate at import time: helper scripts such as seed.py need
# DB_PATH without requiring a bot token. bot.py calls require_token() instead.
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# Comma-separated Telegram numeric user IDs allowed to run admin commands.
# These are the bootstrap admins; more can be added to the `admins` table.
_admin_ids_raw = os.environ.get("ADMIN_TELEGRAM_IDS", "")
ADMIN_TELEGRAM_IDS = {
    int(uid.strip()) for uid in _admin_ids_raw.split(",") if uid.strip().isdigit()
}

DB_PATH = os.environ.get("DB_PATH", "wave_academy.db")

DEFAULT_CURRENCY = os.environ.get("DEFAULT_CURRENCY", "ETB")


def require_token() -> str:
    """Return BOT_TOKEN, or fail loudly with instructions."""
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN is not set. Copy .env.example to .env and fill in your "
            "token from @BotFather, or export BOT_TOKEN before running the bot."
        )
    return BOT_TOKEN


def require_admins() -> set[int]:
    """Warn if no bootstrap admin is configured — nobody could approve anything."""
    if not ADMIN_TELEGRAM_IDS:
        raise RuntimeError(
            "ADMIN_TELEGRAM_IDS is empty, so no one can approve tutors or "
            "payments. Add your numeric Telegram ID (from @userinfobot) to .env."
        )
    return ADMIN_TELEGRAM_IDS

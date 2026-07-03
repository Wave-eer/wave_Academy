import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ.get("7825222032:AAHxRSHpLuYEqYibpErJt7Jsp1NPeS_Dsn4")
if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN is not set. Create a .env file (see .env.example) "
        "or export BOT_TOKEN before running the bot."
    )

# Comma-separated Telegram numeric user IDs allowed to run admin commands.
_admin_ids_raw = os.environ.get("ADMIN_TELEGRAM_IDS", "")
ADMIN_TELEGRAM_IDS = {
    int(uid.strip()) for uid in _admin_ids_raw.split(",") if uid.strip().isdigit()
}

DB_PATH = os.environ.get("DB_PATH", "wave_academy.db")
import os
from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _require_one(*names: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    raise RuntimeError(f"Missing required environment variable (tried: {', '.join(names)})")


# Accept either TELEGRAM_BOT_TOKEN or TELEGRAM_TOKEN
TELEGRAM_BOT_TOKEN: str = _require_one("TELEGRAM_BOT_TOKEN", "TELEGRAM_TOKEN")
TELEGRAM_USER_ID: int = int(_require("TELEGRAM_USER_ID"))

OPENAI_API_KEY: str = _require("OPENAI_API_KEY")
ANTHROPIC_API_KEY: str = _require("ANTHROPIC_API_KEY")

DATABASE_URL: str = _require("DATABASE_URL")

DAILY_NUDGE_TIME: str = os.getenv("DAILY_NUDGE_TIME", "21:00")
TIMEZONE: str = os.getenv("TIMEZONE", "America/Denver")
WEEKLY_SUMMARY_DAY: str = os.getenv("WEEKLY_SUMMARY_DAY", "sunday")
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

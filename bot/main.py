import logging
from datetime import timezone as tz

from apscheduler.triggers.cron import CronTrigger
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot import config, parser, scheduler, transcriber
from core import database

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=getattr(logging, config.LOG_LEVEL),
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_user_local_date():
    import zoneinfo
    from datetime import datetime
    tz_local = zoneinfo.ZoneInfo(config.TIMEZONE)
    return datetime.now(tz_local).date()


def _is_authorized(update: Update) -> bool:
    if update.effective_user is None:
        return False
    uid = update.effective_user.id
    authorized = uid == config.TELEGRAM_USER_ID
    if not authorized:
        logger.warning("Rejected message from user ID %s (expected %s)", uid, config.TELEGRAM_USER_ID)
    return authorized


def _format_entry_summary(entries: list[dict]) -> str:
    lines = []
    for e in entries:
        emoji = {"liked": "✅", "disliked": "❌", "mixed": "🔀"}.get(e["sentiment"], "•")
        energy = {"energizing": "⚡", "draining": "🔋", "neutral": "➖"}.get(e["energy_effect"], "")
        tags = " ".join(f"#{t}" for t in e.get("tags", []))
        lines.append(
            f"{emoji}{energy} *{e['activity']}* (intensity {e['intensity']}/5)\n"
            f"   _{e.get('context', '')}_ {tags}"
        )
    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return
    await update.message.reply_text(
        "👋 Vibe Check is running! Send me a voice memo or text message about your day "
        "and I'll log it for you.\n\nCommands:\n"
        "/today — manually trigger today's check-in\n"
        "/history — show last 5 entries\n"
        "/stats — quick stats"
    )


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return
    await update.message.reply_text(scheduler.random_nudge())


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return
    entries = await database.get_recent_entries(limit=5)
    if not entries:
        await update.message.reply_text("No entries yet — send me your first voice memo!")
        return
    summary = _format_entry_summary(
        [
            {
                "activity": e.activity,
                "sentiment": e.sentiment,
                "energy_effect": e.energy_effect,
                "intensity": e.intensity,
                "context": e.context or "",
                "tags": e.tags or [],
            }
            for e in entries
        ]
    )
    await update.message.reply_text(f"Last {len(entries)} entries:\n\n{summary}", parse_mode="Markdown")


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return
    from datetime import date, timedelta
    week_ago = date.today() - timedelta(days=7)
    # Simple counts from tag vocabulary
    tags = await database.get_tag_vocabulary()
    await update.message.reply_text(
        f"📊 Tag vocabulary: {len(tags)} unique tags\n"
        f"Use the dashboard for full analytics."
    )


# ---------------------------------------------------------------------------
# Message handlers
# ---------------------------------------------------------------------------

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("Voice handler triggered by user %s", update.effective_user.id if update.effective_user else "unknown")
    if not _is_authorized(update):
        return

    await update.message.reply_text("🎙️ Got it! Transcribing your memo...")

    voice = update.message.voice
    file = await context.bot.get_file(voice.file_id)
    audio_bytes = await file.download_as_bytearray()

    transcript = await transcriber.transcribe(bytes(audio_bytes), duration=voice.duration)

    if not transcript:
        await update.message.reply_text(
            "Hmm, I couldn't make out anything from that. Try again?"
        )
        return

    entry_date = _get_user_local_date()

    memo = await database.create_memo(
        telegram_file_id=voice.file_id,
        transcript=transcript,
        duration_seconds=voice.duration,
        date=entry_date,
    )

    await update.message.reply_text("📝 Transcribed! Parsing activities...")

    try:
        entries = await parser.parse_transcript(transcript, entry_date)
    except Exception as exc:
        logger.exception("Parser failed for memo %s", memo.id)
        await database.mark_memo_failed(memo.id)
        await update.message.reply_text(
            f"⚠️ I saved your memo but couldn't parse it automatically. "
            f"Error: {exc}\n\nYou can try /correct to re-parse."
        )
        return

    for entry in entries:
        await database.create_entry(memo_id=memo.id, date=entry_date, **entry)

    summary = _format_entry_summary(entries)
    await update.message.reply_text(
        f"Got it! I parsed *{len(entries)} activit{'y' if len(entries) == 1 else 'ies'}*:\n\n"
        f"{summary}\n\n"
        f"Reply with `fix: ...` to correct anything.",
        parse_mode="Markdown",
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("Text handler triggered by user %s", update.effective_user.id if update.effective_user else "unknown")
    if not _is_authorized(update):
        return

    text = update.message.text or ""

    # Correction flow
    if text.lower().startswith("fix:"):
        await handle_correction(update, context, correction=text[4:].strip())
        return

    # Regular text memo — skip Whisper, parse directly
    entry_date = _get_user_local_date()

    memo = await database.create_memo(
        telegram_file_id=None,
        transcript=text,
        duration_seconds=None,
        date=entry_date,
    )

    await update.message.reply_text("📝 Parsing your entry...")

    try:
        entries = await parser.parse_transcript(text, entry_date)
    except Exception as exc:
        logger.exception("Parser failed for memo %s", memo.id)
        await database.mark_memo_failed(memo.id)
        await update.message.reply_text(
            f"⚠️ Saved your text but couldn't parse it. Error: {exc}"
        )
        return

    for entry in entries:
        await database.create_entry(memo_id=memo.id, date=entry_date, **entry)

    summary = _format_entry_summary(entries)
    await update.message.reply_text(
        f"Got it! Parsed *{len(entries)} activit{'y' if len(entries) == 1 else 'ies'}*:\n\n"
        f"{summary}\n\n"
        f"Reply with `fix: ...` to correct anything.",
        parse_mode="Markdown",
    )


async def handle_correction(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    correction: str,
) -> None:
    """Re-parse today's most recent memo with a correction instruction."""
    from datetime import date
    today = _get_user_local_date()
    existing = await database.get_entries_for_date(today)

    if not existing:
        await update.message.reply_text("No entries for today to correct.")
        return

    memo_id = existing[0].memo_id
    original_entries_json = [
        {
            "activity": e.activity,
            "sentiment": e.sentiment,
            "intensity": e.intensity,
            "energy_effect": e.energy_effect,
            "category": e.category,
            "tags": e.tags,
            "context": e.context,
        }
        for e in existing
    ]

    import json
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)

    correction_prompt = (
        f"The user wants to correct these entries:\n{json.dumps(original_entries_json, indent=2)}\n\n"
        f"Correction instruction: {correction}\n\n"
        f"Return the full corrected entry array as valid JSON only."
    )

    message = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": correction_prompt}],
    )

    try:
        import re
        raw = message.content[0].text
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        entries = json.loads(match.group()) if match else json.loads(raw)
    except Exception:
        await update.message.reply_text("⚠️ Couldn't parse the correction response. Please try again.")
        return

    from bot.parser import _validate_entry
    validated = [_validate_entry(e) for e in entries]

    if memo_id:
        await database.delete_entries_for_memo(memo_id)
    for entry in validated:
        await database.create_entry(memo_id=memo_id, date=today, **entry)

    summary = _format_entry_summary(validated)
    await update.message.reply_text(
        f"✅ Updated! New entries:\n\n{summary}", parse_mode="Markdown"
    )


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

def build_app():
    app = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN).build()

    async def debug_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.message or update.edited_message
        logger.info(
            "RAW UPDATE received — type: %s, user: %s, has_voice: %s, has_text: %s",
            update.update_id,
            update.effective_user.id if update.effective_user else "none",
            bool(msg and msg.voice) if msg else False,
            bool(msg and msg.text) if msg else False,
        )

    app.add_handler(MessageHandler(filters.ALL, debug_all), group=-1)  # group -1 = runs first, non-blocking
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    hour, minute = config.DAILY_NUDGE_TIME.split(":")
    app.job_queue.run_custom(
        scheduler.send_daily_nudge,
        job_kwargs={
            "trigger": CronTrigger(
                hour=int(hour),
                minute=int(minute),
                timezone=config.TIMEZONE,
            ),
            "id": "daily_nudge",
            "replace_existing": True,
        },
    )

    return app


async def _post_init(app) -> None:
    await database.init_db()


def main():
    app = build_app()
    app.post_init = _post_init
    logger.info("Starting Vibe Check bot...")
    app.run_polling(allowed_updates=["message", "edited_message"])


if __name__ == "__main__":
    main()

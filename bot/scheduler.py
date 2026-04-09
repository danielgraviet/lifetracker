import random

from bot import config

NUDGE_MESSAGES = [
    "Hey! What went well today — and what didn't?",
    "Quick check-in: what did you enjoy or not enjoy today?",
    "End of day debrief — send me a voice memo about your day.",
    "What energized you today? What drained you?",
    "Time for your daily vibe check — how was today?",
    "How's your energy after today? Tell me about it.",
    "What would you do more of, and what would you cut? Today's edition.",
    "Daily reflection time — what stood out about today?",
    "Hey, drop me a voice note about your day when you get a sec.",
    "What was the best part of today? What was the worst?",
    "Vibe check: send me a memo about what you enjoyed or didn't today.",
    "How'd today feel? I'm here to listen.",
    "Any highs or lows worth capturing from today?",
    "Tell me about today — what lit you up, what wore you down?",
    "End of day check-in: what's on your mind from today?",
]


def random_nudge() -> str:
    return random.choice(NUDGE_MESSAGES)


async def send_daily_nudge(context) -> None:
    await context.bot.send_message(
        chat_id=config.TELEGRAM_USER_ID,
        text=random_nudge(),
    )

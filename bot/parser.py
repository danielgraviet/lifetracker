import json
import logging
import re
from datetime import date
from pathlib import Path

import anthropic

from bot import config
from core import database

logger = logging.getLogger(__name__)

VALID_SENTIMENTS = {"liked", "disliked", "mixed"}
VALID_ENERGY = {"energizing", "draining", "neutral"}

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "parse_entry.txt"


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text()


def _validate_entry(raw: dict) -> dict:
    return {
        "activity": str(raw.get("activity", "unknown"))[:200],
        "sentiment": raw["sentiment"] if raw.get("sentiment") in VALID_SENTIMENTS else "mixed",
        "intensity": max(1, min(5, int(raw.get("intensity", 3)))),
        "energy_effect": raw["energy_effect"] if raw.get("energy_effect") in VALID_ENERGY else "neutral",
        "category": str(raw.get("category", "uncategorized"))[:50],
        "tags": [str(t).lower().strip()[:50] for t in raw.get("tags", [])][:5],
        "context": str(raw.get("context", ""))[:500],
    }


def _extract_json(text: str) -> list[dict]:
    """Try to extract a JSON array from raw LLM output."""
    text = text.strip()
    # Strip markdown fences if present
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    # Find the outermost [...] block
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        return json.loads(match.group())
    raise ValueError("No JSON array found in LLM response")


async def parse_transcript(transcript: str, entry_date: date) -> list[dict]:
    """Parse a transcript into validated activity entries using Claude."""
    tag_vocab = await database.get_tag_vocabulary()
    tag_list = ", ".join(tag_vocab) if tag_vocab else "(no tags yet — create as needed)"

    system_prompt = _load_prompt().format(
        tag_vocabulary=tag_list,
        date=str(entry_date),
    )

    client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)

    async def _call(messages: list[dict]) -> str:
        message = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=system_prompt,
            messages=messages,
        )
        return message.content[0].text

    messages = [{"role": "user", "content": transcript}]
    raw_text = await _call(messages)

    try:
        entries = _extract_json(raw_text)
    except (json.JSONDecodeError, ValueError):
        logger.warning("LLM returned invalid JSON; retrying with stricter prompt")
        messages.append({"role": "assistant", "content": raw_text})
        messages.append({
            "role": "user",
            "content": (
                "Your previous response was not valid JSON. "
                "Return ONLY a JSON array with no preamble or markdown."
            ),
        })
        raw_text = await _call(messages)
        entries = _extract_json(raw_text)  # raises if still broken

    validated = [_validate_entry(e) for e in entries]

    await database.update_tag_vocabulary(
        [tag for e in validated for tag in e["tags"]],
        entry_date,
    )

    return validated

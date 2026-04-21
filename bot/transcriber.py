import httpx

from bot import config


async def transcribe(audio_bytes: bytes, duration: int) -> str:
    """Send audio bytes to Whisper API and return the transcript text."""
    timeout = max(120.0, duration * 2)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
            files={"file": ("voice.ogg", audio_bytes, "audio/ogg")},
            data={
                "model": "whisper-1",
                "language": "en",
                "response_format": "text",
                "prompt": (
                    "This is a casual voice memo about daily activities, "
                    "things the speaker liked and disliked doing today."
                ),
            },
        )
        response.raise_for_status()
        return response.text.strip()

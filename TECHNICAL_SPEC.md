# Vibe Check — Technical Specification

This document is a detailed technical reference for implementing the Vibe Check system. It complements the README (which covers architecture and data model) with implementation-level specifics: exact prompt templates, message flows, error handling strategies, and edge cases.

---

## 1. Telegram Bot — Detailed Behavior

### 1.1 Bot Registration

Create the bot via [BotFather](https://t.me/BotFather). Required settings:

- Bot name: configurable, e.g. "Vibe Check"
- Commands to register with BotFather:
  - `/start` — Initialize the bot and confirm your user ID
  - `/today` — Manually trigger today's check-in prompt
  - `/history` — Show last 5 parsed entries
  - `/correct` — Re-parse or edit the most recent entry set
  - `/stats` — Quick stats (entries this week, top tags)
  - `/export` — Export all entries as JSON

### 1.2 Message Flow

```
┌─────────────────────────────────────────────────────────┐
│                    DAILY NUDGE FLOW                      │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  [Scheduler]  ──21:00──►  Bot sends nudge message       │
│                           "Hey! What did you enjoy or   │
│                            not enjoy today? Send me a   │
│                            voice memo or text."         │
│                                                         │
│  [User]  ──voice memo──►  Bot receives voice message    │
│                           │                             │
│                           ├─► Download .ogg file        │
│                           ├─► Send to Whisper API       │
│                           ├─► Store Memo record         │
│                           ├─► Send transcript to Claude │
│                           ├─► Store Entry records       │
│                           └─► Reply with parsed summary │
│                                                         │
│  [User]  ──text reply──►  Also accepted, skip Whisper   │
│                           Send text directly to Claude   │
│                                                         │
│  [User]  ──"fix: ..."──►  Correction flow               │
│                           Re-parse or update last entry  │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 1.3 Voice Memo Handling

Telegram voice messages arrive as `.ogg` (Opus codec). The Whisper API accepts this format directly — no conversion needed.

```python
async def handle_voice(update, context):
    # 1. Security: verify user
    if update.effective_user.id != int(config.TELEGRAM_USER_ID):
        return  # silently ignore

    # 2. Download the voice file
    voice = update.message.voice
    file = await context.bot.get_file(voice.file_id)
    audio_bytes = await file.download_as_bytearray()

    # 3. Transcribe
    transcript = await transcriber.transcribe(audio_bytes, duration=voice.duration)

    # 4. Store memo
    memo = await database.create_memo(
        telegram_file_id=voice.file_id,
        transcript=transcript,
        duration_seconds=voice.duration,
        date=get_user_local_date()
    )

    # 5. Parse with LLM
    entries = await parser.parse_transcript(transcript, date=memo.date)

    # 6. Store entries
    for entry in entries:
        await database.create_entry(memo_id=memo.id, **entry)

    # 7. Confirm
    summary = format_entry_summary(entries)
    await update.message.reply_text(
        f"Got it! I parsed {len(entries)} activities:\n\n{summary}\n\n"
        f"Reply with 'fix: ...' to correct anything."
    )
```

### 1.4 Text Message Handling

Users should also be able to type a text message instead of a voice memo. In that case, skip the Whisper step and pass the text directly to the Claude parser. Store a Memo record with `telegram_file_id=None` and the text as the transcript.

### 1.5 Daily Nudge Scheduling

Use `APScheduler` (bundled with python-telegram-bot v20) to schedule the daily nudge.

```python
from telegram.ext import ApplicationBuilder
from apscheduler.triggers.cron import CronTrigger

app = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN).build()

app.job_queue.run_custom(
    send_daily_nudge,
    job_kwargs={
        "trigger": CronTrigger(
            hour=int(config.DAILY_NUDGE_TIME.split(":")[0]),
            minute=int(config.DAILY_NUDGE_TIME.split(":")[1]),
            timezone=config.TIMEZONE
        ),
        "id": "daily_nudge",
        "replace_existing": True,
    }
)
```

The nudge message should vary slightly to avoid feeling robotic. Store 10–15 variations and pick one at random:

```python
NUDGE_MESSAGES = [
    "Hey! What went well today — and what didn't?",
    "Quick check-in: what did you enjoy or not enjoy today?",
    "End of day debrief — send me a voice memo about your day.",
    "What energized you today? What drained you?",
    "Time for your daily vibe check — how was today?",
    # ... more variations
]
```

### 1.6 Correction Flow

When the user replies with a message starting with `fix:`, the system should:

1. Load the most recent set of entries (from today).
2. Send the correction instruction + original entries + original transcript to Claude.
3. Claude returns an updated entry array.
4. Replace the existing entries in the database.
5. Confirm the update in Telegram.

---

## 2. Transcription — Whisper Integration

### 2.1 API Call

```python
import httpx

async def transcribe(audio_bytes: bytes, duration: int) -> str:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
            files={"file": ("voice.ogg", audio_bytes, "audio/ogg")},
            data={
                "model": "whisper-1",
                "language": "en",
                "response_format": "text",
                "prompt": "This is a casual voice memo about daily activities, "
                          "things the speaker liked and disliked doing today."
            }
        )
        response.raise_for_status()
        return response.text
```

### 2.2 Notes

- The `prompt` field is a Whisper hint, not a system prompt. It helps with domain-specific vocabulary and reduces hallucination on short clips.
- Set a generous timeout (30s) — longer memos take time.
- If Whisper returns empty text, reply to the user asking them to try again.

---

## 3. LLM Parsing — Claude Integration

### 3.1 System Prompt (store in `prompts/parse_entry.txt`)

```
You are a structured data extraction assistant. Your job is to parse a voice memo
transcript about someone's day into structured activity entries.

For each distinct activity the speaker mentions, extract:

- activity: A short name for the activity (2-5 words, lowercase)
- sentiment: "liked", "disliked", or "mixed"
- intensity: 1-5 integer (1 = slight preference, 3 = moderate, 5 = very strong feeling)
- energy_effect: "energizing", "draining", or "neutral"
- category: One of: work, health, social, creative, learning, chores, leisure
  (if none fit, create a new single-word category)
- tags: Array of 1-5 lowercase hyphenated tags. Use the provided tag vocabulary
  for consistency when a match exists. Create new tags when nothing fits.
- context: One sentence capturing WHY the speaker felt this way, in third person.
  This should add information beyond what "activity" and "sentiment" already convey.

Rules:
1. Extract EVERY distinct activity mentioned, even brief ones.
2. If the speaker's sentiment is unclear, use "mixed".
3. Sentiment and energy_effect are independent dimensions — someone can dislike
   something energizing or like something draining.
4. Never fabricate activities not mentioned in the transcript.
5. Respond with ONLY a JSON array. No preamble, no markdown, no explanation.

Current tag vocabulary (prefer these when they fit):
{tag_vocabulary}

Today's date: {date}
```

### 3.2 API Call

```python
import anthropic

async def parse_transcript(transcript: str, date: str) -> list[dict]:
    tag_vocab = await database.get_tag_vocabulary()
    tag_list = ", ".join(tag_vocab) if tag_vocab else "(no tags yet — create as needed)"

    system_prompt = load_prompt("prompts/parse_entry.txt").format(
        tag_vocabulary=tag_list,
        date=date
    )

    client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    message = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        system=system_prompt,
        messages=[
            {"role": "user", "content": transcript}
        ]
    )

    raw_text = message.content[0].text
    entries = json.loads(raw_text)

    # Validate each entry
    validated = [validate_entry(e) for e in entries]

    # Update tag vocabulary
    for entry in validated:
        await database.update_tag_vocabulary(entry["tags"], date)

    return validated
```

### 3.3 Validation

Every entry from the LLM must be validated before storage:

```python
VALID_SENTIMENTS = {"liked", "disliked", "mixed"}
VALID_ENERGY = {"energizing", "draining", "neutral"}
DEFAULT_CATEGORIES = {"work", "health", "social", "creative", "learning", "chores", "leisure"}

def validate_entry(raw: dict) -> dict:
    return {
        "activity": str(raw.get("activity", "unknown"))[:200],
        "sentiment": raw["sentiment"] if raw.get("sentiment") in VALID_SENTIMENTS else "mixed",
        "intensity": max(1, min(5, int(raw.get("intensity", 3)))),
        "energy_effect": raw["energy_effect"] if raw.get("energy_effect") in VALID_ENERGY else "neutral",
        "category": str(raw.get("category", "uncategorized"))[:50],
        "tags": [str(t).lower().strip()[:50] for t in raw.get("tags", [])][:5],
        "context": str(raw.get("context", ""))[:500],
    }
```

### 3.4 Error Recovery

If the LLM returns invalid JSON:
1. Attempt to extract JSON from the response (strip markdown fences, find `[...]`).
2. If still invalid, retry once with a stricter prompt appending: "Your previous response was not valid JSON. Return ONLY a JSON array."
3. If the retry fails, store the memo with a `parse_failed` flag and notify the user in Telegram that manual review is needed.

---

## 4. Database Schema (PostgreSQL + SQLAlchemy)

### 4.1 Migration: Initial Schema

```sql
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TYPE sentiment_type AS ENUM ('liked', 'disliked', 'mixed');
CREATE TYPE energy_type AS ENUM ('energizing', 'draining', 'neutral');

CREATE TABLE memos (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    date        DATE NOT NULL,
    telegram_file_id TEXT,
    transcript  TEXT NOT NULL,
    duration_seconds INTEGER,
    parse_failed BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE entries (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    memo_id         UUID REFERENCES memos(id) ON DELETE CASCADE,
    date            DATE NOT NULL,
    activity        TEXT NOT NULL,
    sentiment       sentiment_type NOT NULL,
    intensity       INTEGER NOT NULL CHECK (intensity BETWEEN 1 AND 5),
    energy_effect   energy_type NOT NULL,
    category        TEXT NOT NULL,
    tags            TEXT[] NOT NULL DEFAULT '{}',
    context         TEXT,
    source_transcript TEXT,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE tag_vocabulary (
    tag         TEXT PRIMARY KEY,
    usage_count INTEGER NOT NULL DEFAULT 1,
    first_seen  DATE NOT NULL,
    last_seen   DATE NOT NULL,
    aliases     TEXT[] NOT NULL DEFAULT '{}'
);

-- Indexes for common queries
CREATE INDEX idx_entries_date ON entries(date);
CREATE INDEX idx_entries_sentiment ON entries(sentiment);
CREATE INDEX idx_entries_category ON entries(category);
CREATE INDEX idx_entries_tags ON entries USING GIN(tags);
CREATE INDEX idx_entries_date_sentiment ON entries(date, sentiment);
CREATE INDEX idx_memos_date ON memos(date);
```

### 4.2 Full-Text Search

Add a generated tsvector column for full-text search across activity, context, and transcript:

```sql
ALTER TABLE entries ADD COLUMN search_vector tsvector
    GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(activity, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(context, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(source_transcript, '')), 'C')
    ) STORED;

CREATE INDEX idx_entries_search ON entries USING GIN(search_vector);
```

Query with: `WHERE search_vector @@ plainto_tsquery('english', :query)`

---

## 5. API Implementation Notes (FastAPI)

### 5.1 Entry List with Filters

```python
@router.get("/entries")
async def list_entries(
    date_from: date | None = None,
    date_to: date | None = None,
    sentiment: str | None = None,
    category: str | None = None,
    tags: str | None = None,          # comma-separated
    energy_effect: str | None = None,
    search: str | None = None,
    page: int = 1,
    per_page: int = 20,
    db: AsyncSession = Depends(get_db)
):
    query = select(Entry).order_by(Entry.date.desc(), Entry.created_at.desc())

    if date_from:
        query = query.where(Entry.date >= date_from)
    if date_to:
        query = query.where(Entry.date <= date_to)
    if sentiment:
        query = query.where(Entry.sentiment == sentiment)
    if category:
        query = query.where(Entry.category == category)
    if tags:
        tag_list = [t.strip() for t in tags.split(",")]
        query = query.where(Entry.tags.overlap(tag_list))
    if energy_effect:
        query = query.where(Entry.energy_effect == energy_effect)
    if search:
        query = query.where(
            Entry.search_vector.match(search, postgresql_regconfig="english")
        )

    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    return result.scalars().all()
```

### 5.2 Analytics: Sentiment Trend

Returns weekly buckets of sentiment counts for charting:

```python
@router.get("/analytics/sentiment-trend")
async def sentiment_trend(
    weeks: int = 12,  # how many weeks back
    db: AsyncSession = Depends(get_db)
):
    query = text("""
        SELECT
            date_trunc('week', date) AS week,
            sentiment,
            COUNT(*) AS count
        FROM entries
        WHERE date >= CURRENT_DATE - INTERVAL ':weeks weeks'
        GROUP BY week, sentiment
        ORDER BY week
    """)
    result = await db.execute(query, {"weeks": weeks})
    return result.mappings().all()
```

### 5.3 Analytics: Energy Map

Returns data for a scatter/quadrant chart — activities plotted by average sentiment score vs. energy:

```python
@router.get("/analytics/energy-map")
async def energy_map(
    days: int = 90,
    db: AsyncSession = Depends(get_db)
):
    # Map sentiment to numeric: liked=1, mixed=0, disliked=-1
    # Map energy: energizing=1, neutral=0, draining=-1
    query = text("""
        SELECT
            activity,
            COUNT(*) AS occurrences,
            AVG(CASE sentiment
                WHEN 'liked' THEN 1
                WHEN 'mixed' THEN 0
                WHEN 'disliked' THEN -1
            END) AS avg_sentiment,
            AVG(CASE energy_effect
                WHEN 'energizing' THEN 1
                WHEN 'neutral' THEN 0
                WHEN 'draining' THEN -1
            END) AS avg_energy,
            AVG(intensity) AS avg_intensity
        FROM entries
        WHERE date >= CURRENT_DATE - INTERVAL ':days days'
        GROUP BY activity
        HAVING COUNT(*) >= 2
        ORDER BY occurrences DESC
    """)
    result = await db.execute(query, {"days": days})
    return result.mappings().all()
```

---

## 6. Weekly Summary

Every Sunday, the bot generates and sends a weekly digest using Claude.

### 6.1 Summary Prompt (store in `prompts/weekly_summary.txt`)

```
You are a personal insights assistant. Given a week of activity log entries,
write a warm, concise weekly summary for the user.

Include:
1. A one-sentence overall vibe for the week.
2. Top 3 energizers (activities that were liked + energizing).
3. Top 3 drainers (activities that were disliked + draining).
4. One pattern or insight you notice (e.g., "You seem to enjoy solo deep work
   but find group planning meetings draining").
5. One gentle suggestion for the coming week.

Keep the tone conversational and encouraging — like a thoughtful friend, not a
therapist. Keep the whole summary under 200 words.

Entries for the week of {week_start} to {week_end}:
{entries_json}
```

---

## 7. Docker Compose

```yaml
version: "3.8"

services:
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: vibecheck
      POSTGRES_USER: vibecheck
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  bot:
    build: .
    command: python -m bot.main
    env_file: .env
    depends_on:
      - db
    restart: unless-stopped

  api:
    build: .
    command: uvicorn api.main:app --host 0.0.0.0 --port 8000
    env_file: .env
    depends_on:
      - db
    ports:
      - "8000:8000"
    restart: unless-stopped

  dashboard:
    build:
      context: ./dashboard
    ports:
      - "3000:3000"
    depends_on:
      - api

volumes:
  pgdata:
```

---

## 8. Testing Strategy

### 8.1 Parser Tests

The most critical tests are for the LLM parser. Use saved transcript fixtures:

```
tests/fixtures/
├── simple_two_activities.txt        # Basic happy path
├── ambiguous_sentiment.txt          # Tests "mixed" fallback
├── single_activity.txt              # Edge case: just one thing
├── long_rambling_memo.txt           # 3+ minutes of stream of consciousness
├── no_activities.txt                # "Today was fine, nothing special"
├── mixed_languages.txt              # If user code-switches
└── correction_request.txt           # "Actually the meeting was good"
```

Test that the parser:
- Returns valid JSON for every fixture
- Extracts the expected number of activities
- Never fabricates activities not in the transcript
- Handles empty/very short transcripts gracefully
- Validates all fields (sentiment in enum, intensity 1–5, etc.)

### 8.2 API Tests

Use `httpx.AsyncClient` with FastAPI's test client. Test all filter combinations on the entry list endpoint, and verify analytics queries return correct aggregations against a known test dataset.

### 8.3 Bot Tests

Mock the Telegram API and Whisper API. Test the full flow from voice memo receipt to entry storage. Test the correction flow. Test that the scheduler fires at the right time.

---

## 9. Future Considerations

Things intentionally deferred to keep the initial build focused:

- **Multi-user support**: Currently single-user by design. If expanding, add a `user_id` column to all tables and implement proper auth.
- **Voice memo storage**: Currently only the Telegram file_id is stored. For archival, consider downloading and storing audio in object storage (S3/Minio).
- **Re-parsing**: A management command to re-parse all historical memos with an updated prompt. The architecture supports this since transcripts are preserved.
- **Mobile app**: The Telegram interface is the mobile experience. A dedicated app would only be needed if the dashboard needs mobile-native features.
- **AI-powered queries**: Let the user ask natural language questions about their data ("What did I enjoy most last month?") and have Claude generate SQL or filter parameters.
- **Integrations**: Calendar integration to correlate activities with scheduled events. Spotify/health tracker data for richer context.

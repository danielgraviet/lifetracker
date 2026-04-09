---
name: Vibe Check project overview
description: Core facts about the lifetracker/Vibe Check project — goals, stack, phases
type: project
---

Personal life-logging system: Telegram bot → Whisper transcription → Claude parsing → PostgreSQL → React dashboard.

Stack: python-telegram-bot v20+, OpenAI Whisper, Anthropic Claude API (claude-sonnet-4-6), SQLAlchemy async + asyncpg, Alembic migrations, FastAPI, React + Vite, Docker Compose.

Build phases:
1. Bot + Transcription (in progress as of 2026-04-08)
2. LLM Parsing
3. API + Dashboard
4. Analytics + Insights
5. Polish

**Why:** Single-user personal tool. TELEGRAM_USER_ID restricts all access — no auth needed.
**How to apply:** Keep it simple, single-user, no multi-tenancy design. Start from Phase 1.

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot import config
from core.models import Base, Entry, Memo, TagVocabulary

# Railway (and many hosts) provide postgresql:// but asyncpg requires postgresql+asyncpg://
_db_url = config.DATABASE_URL
if _db_url.startswith("postgresql://") or _db_url.startswith("postgres://"):
    _db_url = _db_url.replace("://", "+asyncpg://", 1)

engine = create_async_engine(_db_url, echo=False, pool_pre_ping=True, pool_recycle=300)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


# ---------------------------------------------------------------------------
# Memo
# ---------------------------------------------------------------------------

async def create_memo(
    *,
    telegram_file_id: str | None,
    transcript: str,
    duration_seconds: int | None,
    date: date,
    parse_failed: bool = False,
) -> Memo:
    async with AsyncSessionLocal() as session:
        memo = Memo(
            telegram_file_id=telegram_file_id,
            transcript=transcript,
            duration_seconds=duration_seconds,
            date=date,
            parse_failed=parse_failed,
        )
        session.add(memo)
        await session.commit()
        await session.refresh(memo)
        return memo


async def mark_memo_failed(memo_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(Memo).where(Memo.id == memo_id).values(parse_failed=True)
        )
        await session.commit()


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

async def create_entry(*, memo_id: uuid.UUID | None, date: date, **fields: Any) -> Entry:
    async with AsyncSessionLocal() as session:
        entry = Entry(memo_id=memo_id, date=date, **fields)
        session.add(entry)
        await session.commit()
        await session.refresh(entry)
        return entry


async def get_recent_entries(limit: int = 10) -> list[Entry]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Entry).order_by(Entry.date.desc(), Entry.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())


async def get_entries_for_date(entry_date: date) -> list[Entry]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Entry).where(Entry.date == entry_date).order_by(Entry.created_at)
        )
        return list(result.scalars().all())


async def delete_entries_for_memo(memo_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as session:
        entries = await session.execute(
            select(Entry).where(Entry.memo_id == memo_id)
        )
        for entry in entries.scalars().all():
            await session.delete(entry)
        await session.commit()


# ---------------------------------------------------------------------------
# Tag Vocabulary
# ---------------------------------------------------------------------------

async def get_tag_vocabulary() -> list[str]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(TagVocabulary.tag).order_by(TagVocabulary.usage_count.desc())
        )
        return list(result.scalars().all())


async def update_tag_vocabulary(tags: list[str], seen_date: date) -> None:
    async with AsyncSessionLocal() as session:
        for tag in tags:
            existing = await session.get(TagVocabulary, tag)
            if existing:
                existing.usage_count += 1
                existing.last_seen = seen_date
            else:
                session.add(
                    TagVocabulary(
                        tag=tag,
                        usage_count=1,
                        first_seen=seen_date,
                        last_seen=seen_date,
                    )
                )
        await session.commit()

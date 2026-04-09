import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Memo(Base):
    __tablename__ = "memos"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    telegram_file_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript: Mapped[str] = mapped_column(Text, nullable=False)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parse_failed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    entries: Mapped[list["Entry"]] = relationship(
        "Entry", back_populates="memo", cascade="all, delete-orphan"
    )


class Entry(Base):
    __tablename__ = "entries"
    __table_args__ = (CheckConstraint("intensity BETWEEN 1 AND 5", name="ck_intensity"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    memo_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memos.id", ondelete="CASCADE"), nullable=True
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    activity: Mapped[str] = mapped_column(Text, nullable=False)
    sentiment: Mapped[str] = mapped_column(Text, nullable=False)   # liked | disliked | mixed
    intensity: Mapped[int] = mapped_column(Integer, nullable=False)
    energy_effect: Mapped[str] = mapped_column(Text, nullable=False)  # energizing | draining | neutral
    category: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    memo: Mapped["Memo | None"] = relationship("Memo", back_populates="entries")


class TagVocabulary(Base):
    __tablename__ = "tag_vocabulary"

    tag: Mapped[str] = mapped_column(Text, primary_key=True)
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_seen: Mapped[date] = mapped_column(Date, nullable=False)
    last_seen: Mapped[date] = mapped_column(Date, nullable=False)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)

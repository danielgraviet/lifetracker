"""Initial schema: memos, entries, tag_vocabulary

Revision ID: 001
Revises:
Create Date: 2026-04-08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    op.create_table(
        "memos",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("telegram_file_id", sa.Text(), nullable=True),
        sa.Column("transcript", sa.Text(), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("parse_failed", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
    )
    op.create_index("idx_memos_date", "memos", ["date"])

    op.create_table(
        "entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("memo_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("memos.id", ondelete="CASCADE"), nullable=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("activity", sa.Text(), nullable=False),
        sa.Column("sentiment", sa.Text(), nullable=False),
        sa.Column("intensity", sa.Integer(), nullable=False),
        sa.Column("energy_effect", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("context", sa.Text(), nullable=True),
        sa.Column("source_transcript", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.CheckConstraint("intensity BETWEEN 1 AND 5", name="ck_intensity"),
    )
    op.create_index("idx_entries_date", "entries", ["date"])
    op.create_index("idx_entries_sentiment", "entries", ["sentiment"])
    op.create_index("idx_entries_category", "entries", ["category"])
    op.create_index("idx_entries_date_sentiment", "entries", ["date", "sentiment"])
    op.execute(
        "CREATE INDEX idx_entries_tags ON entries USING GIN(tags)"
    )

    op.create_table(
        "tag_vocabulary",
        sa.Column("tag", sa.Text(), primary_key=True),
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("first_seen", sa.Date(), nullable=False),
        sa.Column("last_seen", sa.Date(), nullable=False),
        sa.Column("aliases", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
    )

    # Full-text search vector (PostgreSQL generated column)
    op.execute("""
        ALTER TABLE entries ADD COLUMN search_vector tsvector
            GENERATED ALWAYS AS (
                setweight(to_tsvector('english', coalesce(activity, '')), 'A') ||
                setweight(to_tsvector('english', coalesce(context, '')), 'B') ||
                setweight(to_tsvector('english', coalesce(source_transcript, '')), 'C')
            ) STORED
    """)
    op.execute("CREATE INDEX idx_entries_search ON entries USING GIN(search_vector)")


def downgrade() -> None:
    op.drop_table("tag_vocabulary")
    op.drop_table("entries")
    op.drop_table("memos")

from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import String, Text, DateTime, Integer, Float, Boolean, JSON
from sqlalchemy.orm import Mapped, mapped_column
from mozok.db.session import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MemoryRecord(Base):
    """A single long-term memory.

    PostgreSQL is the source of truth.
    FAISS only stores vectors that point back to these records by ID.
    """

    __tablename__ = "memories"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    agent_id: Mapped[str] = mapped_column(String(128), index=True)
    memory_type: Mapped[str] = mapped_column(String(64), default="event", index=True)

    content: Mapped[str] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    importance: Mapped[int] = mapped_column(Integer, default=5)
    emotional_weight: Mapped[float] = mapped_column(Float, default=0.0)

    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)

    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentRecord(Base):
    """A bot/agent identity record.

    Later this can store personality, base goals, species, role, etc.
    """

    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    state_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

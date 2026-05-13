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
    """Bot/agent profile.

    This is the agent's stable identity:
    who it is, how it behaves, and what current state it has.
    """

    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)

    description: Mapped[str] = mapped_column(Text, default="")
    personality: Mapped[str] = mapped_column(Text, default="")
    system_prompt: Mapped[str] = mapped_column(Text, default="")

    state_json: Mapped[dict] = mapped_column(JSON, default=dict)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class WorldEventRecord(Base):
    """Durable World Event Bus V2 record.

    V1 stored events in synthetic agent metadata. V2 gives events their own
    table so adapters can publish, consume, acknowledge, expire, and audit
    event history without bloating AgentRecord.metadata_json.
    """

    __tablename__ = "world_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    world_id: Mapped[str] = mapped_column(String(128), default="default", index=True)
    agent_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)

    event_type: Mapped[str] = mapped_column(String(128), default="world_event", index=True)
    content: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(128), default="external", index=True)
    channel_hint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    salience: Mapped[float] = mapped_column(Float, default=5.0)
    reliability: Mapped[float] = mapped_column(Float, default=1.0)
    visibility: Mapped[str] = mapped_column(String(64), default="local", index=True)

    tags_json: Mapped[list] = mapped_column(JSON, default=list)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    consumed_by_agent_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    acknowledged_by_agent_ids_json: Mapped[list] = mapped_column(JSON, default=list)

    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


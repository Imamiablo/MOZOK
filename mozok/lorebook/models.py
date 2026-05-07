"""
SQLAlchemy models for Lorebook.

Entity state = what a particular agent thinks/feels/tracks about an entity.
Lorebook = objective or author-defined knowledge about the world.
Agent lorebook knowledge = whether a specific agent knows a lorebook entry.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON
from sqlalchemy.orm import relationship

from mozok.db.models import Base


def utcnow() -> datetime:
    """Return timezone-aware UTC datetime for consistent timestamps."""
    return datetime.now(timezone.utc)


class LorebookEntryRecord(Base):
    """
    Objective / author-defined world knowledge.

    world_id:
        Allows multiple worlds/campaigns/projects to share the same backend.
        Use "default" if you do not need separate worlds yet.

    visibility:
        - "public": can be included for any agent by default.
        - "restricted": only included when explicitly linked to an agent.
        - "narrator_only": intended mainly for narrator/game-master agents.
    """

    __tablename__ = "lorebook_entries"

    id = Column(Integer, primary_key=True, index=True)
    world_id = Column(String(128), nullable=False, default="default", index=True)
    entry_key = Column(String(256), nullable=False, index=True)
    title = Column(String(512), nullable=False)
    content = Column(Text, nullable=False)

    category = Column(String(128), nullable=False, default="general", index=True)
    visibility = Column(String(64), nullable=False, default="restricted", index=True)
    importance = Column(Integer, nullable=False, default=5)

    tags = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    entry_metadata = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)

    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    agent_links = relationship(
        "AgentLorebookKnowledgeRecord",
        back_populates="entry",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_lorebook_world_entry_key_unique", "world_id", "entry_key", unique=True),
        Index("ix_lorebook_world_category", "world_id", "category"),
    )


class AgentLorebookKnowledgeRecord(Base):
    """
    Per-agent knowledge gate for a lorebook entry.

    knowledge_state:
        - "known": agent can use it as knowledge.
        - "rumored": agent may treat it as uncertain/rumour.
        - "partial": agent knows some part of it.
        - "hidden": agent should not use it, even if the entry exists.
    """

    __tablename__ = "agent_lorebook_knowledge"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(String(128), nullable=False, index=True)
    lorebook_entry_id = Column(Integer, ForeignKey("lorebook_entries.id"), nullable=False, index=True)

    knowledge_state = Column(String(64), nullable=False, default="known", index=True)
    confidence = Column(Integer, nullable=False, default=10)

    notes = Column(Text, nullable=True)
    knowledge_metadata = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)

    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    entry = relationship("LorebookEntryRecord", back_populates="agent_links")

    __table_args__ = (
        Index("ix_agent_lorebook_agent_entry_unique", "agent_id", "lorebook_entry_id", unique=True),
    )

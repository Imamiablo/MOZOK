from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON

from mozok.db.models import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


class KnowledgeRelationRecord(Base):
    """A directed edge between two knowledge nodes.

    This is intentionally generic: source and target may be memories, lorebook
    entries, entity states, goals, plan steps, concepts, factions, etc.

    The edge belongs to an agent_id. For global/world-level edges, use a system
    agent such as "world_state" or "narrator_001". This keeps private NPC
    knowledge from leaking into other agents' prompts.
    """

    __tablename__ = "knowledge_relations"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(String(120), nullable=False, index=True)
    world_id = Column(String(120), nullable=False, default="default", index=True)

    source_type = Column(String(80), nullable=False, index=True)
    source_id = Column(String(160), nullable=False, index=True)
    relation_type = Column(String(80), nullable=False, index=True)
    target_type = Column(String(80), nullable=False, index=True)
    target_id = Column(String(160), nullable=False, index=True)

    strength = Column(Float, nullable=False, default=1.0)
    confidence = Column(Float, nullable=False, default=1.0)
    description = Column(Text, nullable=False, default="")
    evidence_json = Column(JSON_TYPE, nullable=False, default=dict)
    metadata_json = Column(JSON_TYPE, nullable=False, default=dict)

    active = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        Index(
            "uq_knowledge_relation_edge",
            "agent_id",
            "world_id",
            "source_type",
            "source_id",
            "relation_type",
            "target_type",
            "target_id",
            unique=True,
        ),
        Index("ix_knowledge_relations_source", "agent_id", "world_id", "source_type", "source_id"),
        Index("ix_knowledge_relations_target", "agent_id", "world_id", "target_type", "target_id"),
    )

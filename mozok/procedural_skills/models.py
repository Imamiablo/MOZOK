from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON

from mozok.db.models import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


class AgentProceduralSkillRecord(Base):
    """Reusable procedure/strategy that an agent can apply in a context.

    Procedural skills are different from memories and goals:
    - Memory: what the agent remembers.
    - Goal: what the agent wants to do.
    - Procedural skill: how the agent tends to do something.

    Examples:
    - agent_id="npc_alice", skill_key="deflect_dangerous_questions";
    - agent_id="assistant_001", skill_key="explain_programming_step_by_step";
    - agent_id="narrator_001", skill_key="maintain_horror_pacing".
    """

    __tablename__ = "agent_procedural_skills"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(String(120), nullable=False, index=True)

    skill_key = Column(String(160), nullable=False, index=True)
    title = Column(String(240), nullable=False, default="")
    skill_type = Column(String(80), nullable=False, default="general", index=True)
    status = Column(String(60), nullable=False, default="active", index=True)
    priority = Column(Integer, nullable=False, default=0, index=True)

    description = Column(Text, nullable=False, default="")
    trigger_json = Column(JSON_TYPE, nullable=False, default=dict)
    procedure_json = Column(JSON_TYPE, nullable=False, default=list)
    examples_json = Column(JSON_TYPE, nullable=False, default=list)

    related_goal_keys_json = Column(JSON_TYPE, nullable=False, default=list)
    related_entity_ids_json = Column(JSON_TYPE, nullable=False, default=list)
    related_lorebook_keys_json = Column(JSON_TYPE, nullable=False, default=list)

    notes = Column(Text, nullable=False, default="")
    metadata_json = Column(JSON_TYPE, nullable=False, default=dict)

    active = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        Index(
            "uq_agent_procedural_skill_agent_key",
            "agent_id",
            "skill_key",
            unique=True,
        ),
        Index("ix_agent_procedural_skills_agent_status_priority", "agent_id", "status", "priority"),
    )


class AgentProceduralSkillUsageRecord(Base):
    """Observed usage/outcome for one procedural skill.

    This keeps learning evidence separate from the skill definition. Existing
    skill rows therefore do not need schema-altering migrations: ``create_all``
    can add this table in existing dev databases, while old skills remain valid.
    """

    __tablename__ = "agent_procedural_skill_usage"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(String(120), nullable=False, index=True)
    skill_id = Column(Integer, nullable=True, index=True)
    skill_key = Column(String(160), nullable=False, index=True)

    session_id = Column(String(160), nullable=False, default="", index=True)
    context = Column(Text, nullable=False, default="")
    outcome = Column(String(40), nullable=False, default="neutral", index=True)
    result_score = Column(Float, nullable=False, default=0.5)
    feedback = Column(Text, nullable=False, default="")
    learned_note = Column(Text, nullable=False, default="")
    metadata_json = Column(JSON_TYPE, nullable=False, default=dict)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)

    __table_args__ = (
        Index("ix_agent_procedural_skill_usage_agent_skill", "agent_id", "skill_id"),
        Index("ix_agent_procedural_skill_usage_agent_key", "agent_id", "skill_key"),
    )

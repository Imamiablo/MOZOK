from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON

from mozok.db.models import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


class AgentGoalRecord(Base):
    """A goal/plan that belongs to one agent.

    Goals are intentionally separate from EntityState.

    EntityState answers: "What structured state does this agent keep about X?"
    Goal answers: "What is this agent trying to do?"

    Plan steps stay in flexible JSON for the MVP so games/apps can experiment
    without a migration every time a project wants a different plan shape.
    """

    __tablename__ = "agent_goals"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(String(120), nullable=False, index=True)
    goal_key = Column(String(160), nullable=False, index=True)

    title = Column(String(240), nullable=False, default="")
    goal_type = Column(String(80), nullable=False, default="general")
    status = Column(String(80), nullable=False, default="active", index=True)
    priority = Column(Integer, nullable=False, default=5, index=True)

    description = Column(Text, nullable=False, default="")
    success_criteria_json = Column(JSON_TYPE, nullable=False, default=list)
    failure_conditions_json = Column(JSON_TYPE, nullable=False, default=list)
    related_entity_ids_json = Column(JSON_TYPE, nullable=False, default=list)
    related_lorebook_keys_json = Column(JSON_TYPE, nullable=False, default=list)
    plan_steps_json = Column(JSON_TYPE, nullable=False, default=list)

    notes = Column(Text, nullable=False, default="")
    metadata_json = Column(JSON_TYPE, nullable=False, default=dict)

    active = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        Index("uq_agent_goals_agent_key", "agent_id", "goal_key", unique=True),
        Index("ix_agent_goals_agent_status_priority", "agent_id", "status", "priority"),
    )

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON

from mozok.db.models import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


class AgentEntityStateRecord(Base):
    """Structured state that an agent keeps about an entity/subject.

    This is intentionally broader than relationship memory.

    Examples:
    - state_kind="social_relationship" for RPG/Simulacra-style NPC feelings;
    - state_kind="assistant_user_profile" for an assistant's model of the user;
    - state_kind="narrative_entity" for narrator continuity notes;
    - state_kind="faction_reputation" for game faction standings;
    - state_kind="quest_relevance" for story/quest state.

    The flexible attributes_json field keeps this table generic while still
    giving Mozok a first-class, queryable place for entity-specific state.
    """

    __tablename__ = "agent_entity_states"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(String(120), nullable=False, index=True)

    entity_id = Column(String(160), nullable=False, index=True)
    entity_name = Column(String(240), nullable=False, default="")
    entity_type = Column(String(80), nullable=False, default="entity")

    # Examples: primary_user, story_character, faction, quest, location, object.
    role = Column(String(120), nullable=False, default="")

    # Examples: social_relationship, assistant_user_profile, narrative_entity,
    # faction_reputation, quest_relevance. Keep this open-ended for backend reuse.
    state_kind = Column(String(120), nullable=False, index=True)

    # Flexible structured state. Do NOT hard-code trust/fear/etc into columns here.
    attributes_json = Column(JSON_TYPE, nullable=False, default=dict)
    notes = Column(Text, nullable=False, default="")
    metadata_json = Column(JSON_TYPE, nullable=False, default=dict)

    active = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        Index(
            "uq_agent_entity_state_agent_entity_kind",
            "agent_id",
            "entity_id",
            "state_kind",
            unique=True,
        ),
        Index("ix_agent_entity_states_agent_kind", "agent_id", "state_kind"),
    )

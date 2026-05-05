from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


COMMON_STATE_KINDS = [
    "social_relationship",
    "assistant_user_profile",
    "narrative_entity",
    "faction_reputation",
    "quest_relevance",
]


class EntityStateUpsert(BaseModel):
    """Create or update one entity-state record.

    state_kind is intentionally a string, not a strict enum. Mozok should support
    custom project-specific state kinds without a database migration.
    """

    agent_id: str = Field(..., examples=["cat_001", "assistant_001", "narrator_001"])
    entity_id: str = Field(..., examples=["denys", "neko_maria", "forest_faction"])
    entity_name: str = Field("", examples=["Denys", "Neko-Maria", "Northern Forest Faction"])
    entity_type: str = Field("entity", examples=["user", "character", "faction", "quest", "location", "object"])
    role: str = Field("", examples=["primary_user", "story_character", "player", "suspect", "ally"])
    state_kind: str = Field(
        "assistant_user_profile",
        description="Open-ended state type, e.g. social_relationship, assistant_user_profile, narrative_entity.",
        examples=COMMON_STATE_KINDS,
    )
    attributes: dict[str, Any] = Field(default_factory=dict)
    notes: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class EntityStatePatch(BaseModel):
    entity_name: str | None = None
    entity_type: str | None = None
    role: str | None = None
    attributes: dict[str, Any] | None = None
    notes: str | None = None
    metadata: dict[str, Any] | None = None
    active: bool | None = None


class EntityStateRead(BaseModel):
    id: int
    agent_id: str
    entity_id: str
    entity_name: str
    entity_type: str
    role: str
    state_kind: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    notes: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    active: bool = True

    @classmethod
    def from_record(cls, record):
        return cls(
            id=record.id,
            agent_id=record.agent_id,
            entity_id=record.entity_id,
            entity_name=record.entity_name or "",
            entity_type=record.entity_type or "entity",
            role=record.role or "",
            state_kind=record.state_kind,
            attributes=record.attributes_json or {},
            notes=record.notes or "",
            metadata=record.metadata_json or {},
            active=bool(record.active),
        )

    class Config:
        from_attributes = True


class EntityStateContextRequest(BaseModel):
    agent_id: str
    state_kind: str | None = None
    entity_id: str | None = None
    limit: int = Field(default=10, ge=1, le=50)


class EntityStateContextResponse(BaseModel):
    agent_id: str
    count: int
    lines: list[str]
    states: list[EntityStateRead]

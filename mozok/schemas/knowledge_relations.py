from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


COMMON_NODE_TYPES = [
    "memory",
    "lorebook",
    "entity_state",
    "goal",
    "plan_step",
    "agent",
    "entity",
    "faction",
    "quest",
    "location",
    "object",
    "concept",
]

COMMON_RELATION_TYPES = [
    "related_to",
    "about",
    "supports",
    "contradicts",
    "evidence_for",
    "caused_by",
    "causes",
    "depends_on",
    "blocks",
    "updates",
    "explains",
    "part_of",
    "similar_to",
    "derived_from",
    "motivates",
]


class KnowledgeRelationUpsert(BaseModel):
    """Create or update one directed knowledge relation edge.

    source_type/source_id --relation_type--> target_type/target_id

    Types are strings on purpose so projects can add their own node and relation
    categories without database migrations.
    """

    agent_id: str = Field(..., examples=["npc_alice", "narrator_001", "world_state"])
    world_id: str = Field("default", examples=["default", "from_like_world"])
    source_type: str = Field(..., examples=COMMON_NODE_TYPES)
    source_id: str = Field(..., examples=["42", "old_well", "hide_tunnel_secret"])
    relation_type: str = Field(..., examples=COMMON_RELATION_TYPES)
    target_type: str = Field(..., examples=COMMON_NODE_TYPES)
    target_id: str = Field(..., examples=["17", "old_well", "northern_forest_faction"])
    strength: float = Field(default=1.0, ge=0.0, le=1.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    description: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeRelationPatch(BaseModel):
    strength: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    description: str | None = None
    evidence: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    active: bool | None = None


class KnowledgeRelationRead(BaseModel):
    id: int
    agent_id: str
    world_id: str
    source_type: str
    source_id: str
    relation_type: str
    target_type: str
    target_id: str
    strength: float = 1.0
    confidence: float = 1.0
    description: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    active: bool = True

    @classmethod
    def from_record(cls, record):
        return cls(
            id=record.id,
            agent_id=record.agent_id,
            world_id=record.world_id or "default",
            source_type=record.source_type,
            source_id=record.source_id,
            relation_type=record.relation_type,
            target_type=record.target_type,
            target_id=record.target_id,
            strength=float(record.strength if record.strength is not None else 1.0),
            confidence=float(record.confidence if record.confidence is not None else 1.0),
            description=record.description or "",
            evidence=dict(record.evidence_json or {}),
            metadata=dict(record.metadata_json or {}),
            active=bool(record.active),
        )

    class Config:
        from_attributes = True


class KnowledgeRelationContextResponse(BaseModel):
    agent_id: str
    world_id: str | None = None
    count: int
    lines: list[str]
    relations: list[KnowledgeRelationRead]

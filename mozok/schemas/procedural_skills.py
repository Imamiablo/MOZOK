from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


COMMON_SKILL_TYPES = [
    "conversation",
    "reasoning",
    "planning",
    "social",
    "narration",
    "combat",
    "survival",
    "teaching",
    "debugging",
]

COMMON_SKILL_STATUSES = ["active", "inactive", "deprecated", "experimental"]


class AgentProceduralSkillUpsert(BaseModel):
    agent_id: str = Field(..., examples=["npc_alice", "assistant_001", "narrator_001"])
    skill_key: str = Field(..., examples=["deflect_dangerous_questions"])
    title: str = Field("", examples=["Deflect dangerous questions"])
    skill_type: str = Field("general", examples=COMMON_SKILL_TYPES)
    status: str = Field("active", examples=COMMON_SKILL_STATUSES)
    priority: int = Field(default=0, ge=0, le=100)

    description: str = ""
    trigger: dict[str, Any] = Field(default_factory=dict)
    procedure: list[Any] = Field(default_factory=list)
    examples: list[dict[str, Any]] = Field(default_factory=list)

    related_goal_keys: list[str] = Field(default_factory=list)
    related_entity_ids: list[str] = Field(default_factory=list)
    related_lorebook_keys: list[str] = Field(default_factory=list)

    notes: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentProceduralSkillPatch(BaseModel):
    title: str | None = None
    skill_type: str | None = None
    status: str | None = None
    priority: int | None = Field(default=None, ge=0, le=100)
    description: str | None = None
    trigger: dict[str, Any] | None = None
    procedure: list[Any] | None = None
    examples: list[dict[str, Any]] | None = None
    related_goal_keys: list[str] | None = None
    related_entity_ids: list[str] | None = None
    related_lorebook_keys: list[str] | None = None
    notes: str | None = None
    metadata: dict[str, Any] | None = None
    active: bool | None = None


class AgentProceduralSkillRead(BaseModel):
    id: int
    agent_id: str
    skill_key: str
    title: str
    skill_type: str
    status: str
    priority: int
    description: str = ""
    trigger: dict[str, Any] = Field(default_factory=dict)
    procedure: list[Any] = Field(default_factory=list)
    examples: list[dict[str, Any]] = Field(default_factory=list)
    related_goal_keys: list[str] = Field(default_factory=list)
    related_entity_ids: list[str] = Field(default_factory=list)
    related_lorebook_keys: list[str] = Field(default_factory=list)
    notes: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    active: bool = True

    @classmethod
    def from_record(cls, record):
        return cls(
            id=record.id,
            agent_id=record.agent_id,
            skill_key=record.skill_key,
            title=record.title or record.skill_key,
            skill_type=record.skill_type or "general",
            status=record.status or "active",
            priority=int(record.priority or 0),
            description=record.description or "",
            trigger=dict(record.trigger_json or {}),
            procedure=list(record.procedure_json or []),
            examples=list(record.examples_json or []),
            related_goal_keys=list(record.related_goal_keys_json or []),
            related_entity_ids=list(record.related_entity_ids_json or []),
            related_lorebook_keys=list(record.related_lorebook_keys_json or []),
            notes=record.notes or "",
            metadata=dict(record.metadata_json or {}),
            active=bool(record.active),
        )

    class Config:
        from_attributes = True


class ProceduralSkillContextResponse(BaseModel):
    agent_id: str
    count: int
    lines: list[str]
    skills: list[AgentProceduralSkillRead]


class ProceduralSkillSelectionDetail(BaseModel):
    procedural_skill_id: int
    skill_key: str
    title: str
    score: float
    reasons: list[str] = Field(default_factory=list)
    matched_keywords: list[str] = Field(default_factory=list)
    matched_goal_keys: list[str] = Field(default_factory=list)
    matched_lorebook_keys: list[str] = Field(default_factory=list)
    matched_entity_ids: list[str] = Field(default_factory=list)
    fallback_selected: bool = False


class ProceduralSkillSelectionResponse(BaseModel):
    agent_id: str
    count: int
    selection: list[ProceduralSkillSelectionDetail]
    lines: list[str]
    skills: list[AgentProceduralSkillRead]

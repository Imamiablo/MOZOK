from __future__ import annotations

from datetime import datetime
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
COMMON_SKILL_OUTCOMES = ["success", "failure", "neutral"]


class ProceduralSkillEffectivenessStats(BaseModel):
    """Small, inspectable success/failure summary for one skill."""

    skill_id: int
    skill_key: str
    usage_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    neutral_count: int = 0
    success_rate: float = 0.0
    average_score: float = 0.0
    last_used_at: datetime | None = None


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
    effectiveness: ProceduralSkillEffectivenessStats | None = None

    @classmethod
    def from_record(cls, record, effectiveness: ProceduralSkillEffectivenessStats | None = None):
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
            effectiveness=effectiveness,
        )

    class Config:
        from_attributes = True


class ProceduralSkillUsageCreate(BaseModel):
    """Record how a skill behaved in practice.

    The endpoint is intentionally explicit: callers decide whether a learned
    note should only be stored as evidence or also copied into the skill notes.
    """

    session_id: str = Field(default="", examples=["game_session_001"])
    context: str = Field(default="", description="Short scene/user-message summary where the skill was used.")
    outcome: str = Field(default="neutral", examples=COMMON_SKILL_OUTCOMES)
    score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Optional result score. If omitted: success=1.0, neutral=0.5, failure=0.0.",
    )
    feedback: str = ""
    learned_note: str = ""
    apply_learned_note: bool = Field(
        default=False,
        description="If true, append the learned note to the skill's visible notes as a safe strategy update.",
    )
    create_knowledge_relations: bool = Field(
        default=False,
        description="If true, create conservative skill→goal/lore/entity graph relations from the skill's existing links.",
    )
    world_id: str = Field(default="default")
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProceduralSkillUsageRead(BaseModel):
    id: int
    agent_id: str
    skill_id: int | None = None
    skill_key: str
    session_id: str = ""
    context: str = ""
    outcome: str = "neutral"
    score: float = 0.5
    feedback: str = ""
    learned_note: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None

    @classmethod
    def from_record(cls, record):
        return cls(
            id=int(record.id),
            agent_id=record.agent_id,
            skill_id=record.skill_id,
            skill_key=record.skill_key,
            session_id=record.session_id or "",
            context=record.context or "",
            outcome=record.outcome or "neutral",
            score=float(record.result_score if record.result_score is not None else 0.5),
            feedback=record.feedback or "",
            learned_note=record.learned_note or "",
            metadata=dict(record.metadata_json or {}),
            created_at=record.created_at,
        )

    class Config:
        from_attributes = True


class ProceduralSkillUsageResponse(BaseModel):
    skill: AgentProceduralSkillRead
    usage: ProceduralSkillUsageRead
    effectiveness: ProceduralSkillEffectivenessStats
    relation_ids: list[int] = Field(default_factory=list)
    relation_count: int = 0


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


class ProceduralSkillTemplateRead(BaseModel):
    template_key: str
    title: str
    skill_type: str = "general"
    description: str = ""
    trigger: dict[str, Any] = Field(default_factory=dict)
    procedure: list[Any] = Field(default_factory=list)
    examples: list[dict[str, Any]] = Field(default_factory=list)
    related_goal_keys: list[str] = Field(default_factory=list)
    related_entity_ids: list[str] = Field(default_factory=list)
    related_lorebook_keys: list[str] = Field(default_factory=list)
    notes: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProceduralSkillFromTemplateRequest(BaseModel):
    template_key: str = Field(..., examples=["careful_secret_deflection"])
    skill_key: str | None = Field(default=None, description="Override generated skill_key.")
    title: str | None = None
    status: str = Field(default="active", examples=COMMON_SKILL_STATUSES)
    priority: int = Field(default=5, ge=0, le=100)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProceduralSkillRelationSuggestion(BaseModel):
    source_type: str = "procedural_skill"
    source_id: str
    relation_type: str
    target_type: str
    target_id: str
    strength: float = 0.7
    confidence: float = 0.7
    description: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProceduralSkillRelationSuggestionsResponse(BaseModel):
    skill_id: int
    skill_key: str
    world_id: str
    count: int
    suggestions: list[ProceduralSkillRelationSuggestion]


class ProceduralSkillRelationSyncRequest(BaseModel):
    world_id: str = Field(default="default")
    dry_run: bool = Field(default=False)
    validate_nodes: bool = Field(default=False)


class ProceduralSkillRelationSyncResponse(BaseModel):
    skill_id: int
    skill_key: str
    world_id: str
    dry_run: bool
    requested: int
    created: int
    updated: int
    skipped: int
    errors: list[str] = Field(default_factory=list)
    relation_ids: list[int] = Field(default_factory=list)

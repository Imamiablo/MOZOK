from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


MemoryLevel = Literal["raw", "episodic", "semantic", "core"]
ForgetAction = Literal[
    "decay",
    "archive",
    "summarize",
    "summarize_then_archive",
    "soft_delete",
    "hard_delete",
    "protect",
]


class MemoryCreate(BaseModel):
    agent_id: str = Field(..., examples=["cat_001"])
    content: str
    memory_type: str = "episodic"
    session_id: str | None = Field(
        default=None,
        description=(
            "Optional session key for memories that came from a specific "
            "conversation/session. Mostly useful for raw memories. Stored in "
            "metadata_json, so no DB migration is needed."
        ),
        examples=["default", "game_session_001"],
    )
    importance: int = Field(default=5, ge=1, le=10)
    emotional_weight: float = 0.0
    metadata: dict = Field(default_factory=dict)


class MemoryRead(BaseModel):
    id: int
    agent_id: str
    content: str
    memory_type: str
    importance: int
    emotional_weight: float
    metadata: dict = Field(default_factory=dict)

    @classmethod
    def from_record(cls, record):
        return cls(
            id=record.id,
            agent_id=record.agent_id,
            content=record.content,
            memory_type=record.memory_type,
            importance=record.importance,
            emotional_weight=record.emotional_weight,
            metadata=record.metadata_json or {},
        )

    class Config:
        from_attributes = True


class MemorySearchRequest(BaseModel):
    agent_id: str
    query: str
    limit: int = Field(default=5, ge=1, le=50)
    memory_type: str | None = None


class MemorySearchResult(BaseModel):
    id: int
    content: str
    memory_type: str
    importance: int
    score: float
    metadata: dict = Field(default_factory=dict)


class MemoryForgetRequest(BaseModel):
    action: ForgetAction = "archive"
    reason: str = "manual"
    decay_amount: int = Field(default=1, ge=1, le=9)
    rebuild_index: bool = True


class MemoryForgetResponse(BaseModel):
    memory_id: int
    action: str
    changed: bool
    message: str


class MemoryMaintenanceRequest(BaseModel):
    # manual, every_n_memories, after_session, memory_limit, time_interval, important_event
    trigger: str = "manual"
    rebuild_index: bool = True


class MemoryMaintenanceResponse(BaseModel):
    agent_id: str
    trigger: str
    checked_memories: int
    summarized_memories: int
    decayed_memories: int
    archived_memories: int
    protected_memories: int
    deleted_memories: int
    created_summary_ids: list[int]
    rebuilt_index: bool
    indexed_memories: int | None = None
    notes: list[str] = Field(default_factory=list)


class MemoryPolicyUpdate(BaseModel):
    # Partial policy. Example:
    # {
    #   "triggers": {
    #     "every_n_memories": {"enabled": true, "n": 50},
    #     "time_interval": {"enabled": true, "hours": 12}
    #   }
    # }
    memory_policy: dict = Field(default_factory=dict)


MaintenanceSuggestionAction = Literal[
    "archive",
    "decay",
    "summarize",
    "summarize_then_archive",
    "protect",
    "review",
    "soft_delete",
    "hard_delete",
]

MaintenanceSuggestionSource = Literal[
    "rules",
    "relation_protection",
    "embedding_cluster",
    "text_cluster",
]


class MemoryMaintenanceSuggestionsRequest(BaseModel):
    """Read-only maintenance suggestion request.

    This is a preview endpoint: it must not mutate SQL records, FAISS, access
    counters, summaries, metadata, or relations.
    """

    trigger: str = "manual"
    limit: int = Field(default=200, ge=1, le=5000)
    world_id: str = "default"
    include_relation_protection: bool = True
    include_embedding_clusters: bool = True
    include_llm_reasons: bool = False
    min_cluster_size: int = Field(default=3, ge=2, le=50)
    max_clusters: int = Field(default=10, ge=1, le=100)
    similarity_threshold: float = Field(default=0.82, ge=0.1, le=1.0)


class MemoryMaintenanceSuggestion(BaseModel):
    suggestion_id: str
    action: MaintenanceSuggestionAction
    target_memory_ids: list[int]
    reason: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    source: MaintenanceSuggestionSource
    safe_to_auto_apply: bool = False
    relation_protected: bool = False
    blocked_by_relation_ids: list[int] = Field(default_factory=list)
    would_modify: bool = False
    metadata: dict = Field(default_factory=dict)


class MemoryMaintenanceSuggestionsResponse(BaseModel):
    agent_id: str
    trigger: str
    dry_run: bool = True
    scanned: int
    suggestions: list[MemoryMaintenanceSuggestion]
    summary: dict[str, int] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)

# --- PATCH_25_1_MAINTENANCE_APPLY_REJECT_SCHEMAS START ---
# Schemas for Patch 25 - Maintenance Apply/Reject Selected/All.
# These live in memory.py because the existing memory API imports all memory
# request/response models from this module.

MaintenanceSelection = Literal["selected", "all"]
MaintenanceApplyRejectMode = Literal["apply", "reject"]


class MemoryMaintenanceSuggestionInput(BaseModel):
    suggestion_id: str = Field(..., examples=["archive:memory:42"])
    action: ForgetAction = "archive"
    target_memory_ids: list[int] = Field(default_factory=list)
    reason: str = "maintenance suggestion"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    decay_amount: int = Field(default=1, ge=1, le=9)
    metadata: dict = Field(default_factory=dict)


class MemoryMaintenanceApplyRejectRequest(BaseModel):
    selection: MaintenanceSelection = Field(
        default="selected",
        description=(
            "Use 'all' to process every suggestion in the request, or "
            "'selected' to process selected_suggestion_ids only."
        ),
    )
    selected_suggestion_ids: list[str] = Field(default_factory=list)
    suggestions: list[MemoryMaintenanceSuggestionInput] = Field(default_factory=list)
    rebuild_index: bool = True
    override_relation_protection: bool = Field(
        default=False,
        description=(
            "If true, destructive actions can be applied even when a target "
            "memory is linked by active knowledge relations."
        ),
    )


class MemoryMaintenanceApplyRejectResult(BaseModel):
    suggestion_id: str
    action: str
    target_memory_ids: list[int] = Field(default_factory=list)
    status: str
    changed: bool
    message: str
    relation_ids: list[int] = Field(default_factory=list)
    created_summary_ids: list[int] = Field(default_factory=list)


class MemoryMaintenanceApplyRejectResponse(BaseModel):
    agent_id: str
    mode: MaintenanceApplyRejectMode
    selection: MaintenanceSelection
    requested_suggestions: int
    selected_suggestions: int
    applied: int
    rejected: int
    skipped: int
    relation_protected: int
    rebuilt_index: bool
    indexed_memories: int | None = None
    results: list[MemoryMaintenanceApplyRejectResult] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
# --- PATCH_25_1_MAINTENANCE_APPLY_REJECT_SCHEMAS END ---


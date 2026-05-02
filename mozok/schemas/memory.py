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

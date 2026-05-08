from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


COMMON_GOAL_STATUSES = ["active", "paused", "blocked", "completed", "failed", "abandoned"]
COMMON_GOAL_TYPES = ["personal", "social", "quest", "survival", "narrative", "assistant_task", "general"]


class AgentGoalUpsert(BaseModel):
    """Create or update one agent goal/plan.

    goal_key is unique per agent_id, so posting the same agent_id + goal_key
    updates the existing goal instead of creating duplicates.
    """

    agent_id: str = Field(..., examples=["npc_alice", "narrator_001", "assistant_001"])
    goal_key: str = Field(..., examples=["hide_tunnel_secret", "help_user_with_mozok"])
    title: str = Field("", examples=["Hide the tunnel secret"])
    goal_type: str = Field("general", examples=COMMON_GOAL_TYPES)
    status: str = Field("active", examples=COMMON_GOAL_STATUSES)
    priority: int = Field(5, ge=0, le=10, description="0=lowest, 10=highest")
    description: str = ""
    success_criteria: list[str] = Field(default_factory=list)
    failure_conditions: list[str] = Field(default_factory=list)
    related_entity_ids: list[str] = Field(default_factory=list)
    related_lorebook_keys: list[str] = Field(default_factory=list)
    plan_steps: list[dict[str, Any]] = Field(default_factory=list)
    notes: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentGoalPatch(BaseModel):
    title: str | None = None
    goal_type: str | None = None
    status: str | None = None
    priority: int | None = Field(default=None, ge=0, le=10)
    description: str | None = None
    success_criteria: list[str] | None = None
    failure_conditions: list[str] | None = None
    related_entity_ids: list[str] | None = None
    related_lorebook_keys: list[str] | None = None
    plan_steps: list[dict[str, Any]] | None = None
    notes: str | None = None
    metadata: dict[str, Any] | None = None
    active: bool | None = None


class AgentGoalRead(BaseModel):
    id: int
    agent_id: str
    goal_key: str
    title: str
    goal_type: str
    status: str
    priority: int
    description: str = ""
    success_criteria: list[str] = Field(default_factory=list)
    failure_conditions: list[str] = Field(default_factory=list)
    related_entity_ids: list[str] = Field(default_factory=list)
    related_lorebook_keys: list[str] = Field(default_factory=list)
    plan_steps: list[dict[str, Any]] = Field(default_factory=list)
    notes: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    active: bool = True

    @classmethod
    def from_record(cls, record):
        return cls(
            id=record.id,
            agent_id=record.agent_id,
            goal_key=record.goal_key,
            title=record.title or record.goal_key,
            goal_type=record.goal_type or "general",
            status=record.status or "active",
            priority=int(record.priority or 0),
            description=record.description or "",
            success_criteria=list(record.success_criteria_json or []),
            failure_conditions=list(record.failure_conditions_json or []),
            related_entity_ids=list(record.related_entity_ids_json or []),
            related_lorebook_keys=list(record.related_lorebook_keys_json or []),
            plan_steps=list(record.plan_steps_json or []),
            notes=record.notes or "",
            metadata=dict(record.metadata_json or {}),
            active=bool(record.active),
        )

    class Config:
        from_attributes = True


class AgentGoalContextResponse(BaseModel):
    agent_id: str
    status: str | None = None
    count: int
    lines: list[str]
    goals: list[AgentGoalRead]

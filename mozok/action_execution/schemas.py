from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from mozok.action_planning.schemas import ActionIntent, ActionKind, ActionRisk


ActionExecutionStatus = Literal[
    "dry_run",
    "queued_for_adapter",
    "completed",
    "failed",
    "blocked",
]
PermissionDecision = Literal["allowed", "blocked", "needs_approval"]


class ActionToolRegistryEntry(BaseModel):
    """One adapter-owned tool/action capability registered for an agent.

    Mozok records permissions and execution requests. The owning game/app/tool
    adapter still performs the real side effect and may report results back.
    """

    name: str = Field(..., examples=["move_to_location", "emit_world_event"])
    description: str = ""
    action_kind: ActionKind = "tool_call"
    risk_level: ActionRisk = "medium"
    requires_approval: bool = True
    enabled: bool = True
    adapter_owned: bool = True
    permission_scope: str = Field(default="agent", examples=["agent", "world", "external_tool"])
    allowed_agent_modes: list[str] = Field(default_factory=list)
    max_retries: int = Field(default=0, ge=0, le=10)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActionToolRegistryUpdateRequest(BaseModel):
    tools: list[ActionToolRegistryEntry] = Field(default_factory=list)
    replace: bool = Field(default=False, description="If true, replace the current registry. Otherwise merge by tool name.")


class ActionToolRegistryResponse(BaseModel):
    agent_id: str
    tool_count: int = 0
    tools: list[ActionToolRegistryEntry] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ActionExecutionRequest(BaseModel):
    """Request execution/queueing for a previously planned action intent."""

    intent: ActionIntent | None = None
    action_kind: ActionKind | None = None
    tool_name: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    approval_granted: bool = False
    dry_run: bool = False
    requested_by: str = Field(default="api", examples=["api", "runtime_tick", "chat", "game_adapter"])
    idempotency_key: str | None = None
    retry_of_execution_id: str | None = None
    store_execution: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActionExecutionPermission(BaseModel):
    decision: PermissionDecision = "blocked"
    risk_level: ActionRisk = "low"
    approval_required: bool = False
    approval_granted: bool = False
    reasons: list[str] = Field(default_factory=list)


class ActionExecutionRecord(BaseModel):
    execution_id: str
    agent_id: str
    action_id: str | None = None
    action_kind: ActionKind = "no_op"
    tool_name: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    status: ActionExecutionStatus = "queued_for_adapter"
    permission: ActionExecutionPermission = Field(default_factory=ActionExecutionPermission)
    attempt_count: int = 1
    max_retries: int = 0
    adapter_owned: bool = True
    adapter_instruction: str = ""
    requested_by: str = "api"
    idempotency_key: str | None = None
    retry_of_execution_id: str | None = None
    rollback_snapshot: dict[str, Any] | None = None
    result: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ActionExecutionResponse(BaseModel):
    agent_id: str
    read_only: bool = False
    execution: ActionExecutionRecord
    notes: list[str] = Field(default_factory=list)


class ActionExecutionListResponse(BaseModel):
    agent_id: str
    execution_count: int = 0
    executions: list[ActionExecutionRecord] = Field(default_factory=list)


class ActionExecutionResultUpdateRequest(BaseModel):
    status: ActionExecutionStatus = "completed"
    result: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)

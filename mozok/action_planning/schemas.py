from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ActionRisk = Literal["low", "medium", "high"]
ActionStatus = Literal["candidate", "needs_approval", "blocked", "ready"]
ActionKind = Literal["speak", "tool_call", "game_command", "world_event", "memory_operation", "no_op"]


class ActionToolSpec(BaseModel):
    """A generic adapter/tool available to the agent for this turn.

    Mozok does not execute tools in this MVP. External apps/games can expose
    their own tool names and schemas, and the planner will produce intents.
    """

    name: str = Field(..., examples=["move_to_location", "create_calendar_event"])
    description: str = ""
    action_kind: ActionKind = "tool_call"
    risk_level: ActionRisk = "medium"
    requires_approval: bool = True
    input_schema: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class ActionPlanRequest(BaseModel):
    user_message: str = ""
    agent_mode: str | None = None
    cognitive_field: dict[str, Any] | None = None
    self_model: dict[str, Any] | None = None
    sensory_inputs: list[dict[str, Any]] = Field(default_factory=list)
    available_tools: list[ActionToolSpec] = Field(default_factory=list)
    allowed_action_kinds: list[ActionKind] = Field(default_factory=list)
    require_approval_for_medium_risk: bool = True
    max_candidates: int = Field(default=8, ge=1, le=50)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActionIntent(BaseModel):
    action_id: str
    action_kind: ActionKind
    label: str
    rationale: str = ""
    tool_name: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    risk_level: ActionRisk = "low"
    status: ActionStatus = "candidate"
    score: float = 0.0
    evidence: list[str] = Field(default_factory=list)
    approval_required: bool = False


class ActionPlanResponse(BaseModel):
    agent_id: str
    read_only: bool = True
    selected_action_id: str | None = None
    selected_action: ActionIntent | None = None
    actions: list[ActionIntent] = Field(default_factory=list)
    execution_policy: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class ActionProposalRequest(ActionPlanRequest):
    store_proposal: bool = True
    approval_mode: str = "manual_review"


class ActionProposalResponse(BaseModel):
    agent_id: str
    plan: ActionPlanResponse
    proposal: dict[str, Any] | None = None

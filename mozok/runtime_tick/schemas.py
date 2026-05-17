from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mozok.action_planning.schemas import ActionPlanResponse, ActionToolSpec
from mozok.change_proposals.schemas import ApprovalMode
from mozok.cognition.schemas import SensoryInput
from mozok.perception.schemas import PerceptionEvent, PerceptionProfile
from mozok.self_model.schemas import SelfModelResponse
from mozok.world_events.schemas import WorldEventRead


class AgentRuntimeTickRequest(BaseModel):
    world_id: str = "default"
    session_id: str = "runtime_tick"
    agent_mode: str | None = None
    llm_model: str | None = Field(default=None, description="Reserved model override for future LLM-backed runtime tick steps.")
    llm_model_role: str | None = Field(default=None, description="Reserved model role hint such as fast or reasoning.")
    message: str = Field(default="", description="Optional current stimulus/task. Empty tick still processes events/goals.")
    pull_world_events: bool = True
    world_event_limit: int = Field(default=10, ge=0, le=100)
    perception_events: list[PerceptionEvent] = Field(default_factory=list)
    sensory_inputs: list[SensoryInput] = Field(default_factory=list)
    perception_profile: PerceptionProfile | None = None
    attention_focus_keywords: list[str] = Field(default_factory=list)
    available_tools: list[ActionToolSpec] = Field(default_factory=list)
    include_goals: bool = True
    include_procedural_skills: bool = True
    include_entity_states: bool = True
    include_knowledge_relations: bool = True
    include_related_knowledge_relations: bool = True
    enable_cognitive_field: bool = True
    create_change_proposals: bool = True
    approval_mode: ApprovalMode = "manual_review"
    store_proposals: bool = False
    auto_apply: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentRuntimeTickResponse(BaseModel):
    agent_id: str
    world_id: str
    read_only: bool = True
    tick_id: str
    context_debug: dict[str, Any] = Field(default_factory=dict)
    pulled_world_events: list[WorldEventRead] = Field(default_factory=list)
    cognitive_field: dict[str, Any] | None = None
    self_model: SelfModelResponse | None = None
    action_plan: ActionPlanResponse | None = None
    proposals: list[dict[str, Any]] = Field(default_factory=list)
    auto_apply_result: dict[str, Any] | None = None
    notes: list[str] = Field(default_factory=list)


class AgentRuntimeBatchTickRequest(BaseModel):
    world_id: str = "default"
    agent_ids: list[str] = Field(default_factory=list)
    shared_message: str = ""
    tick_request_overrides: dict[str, AgentRuntimeTickRequest] = Field(default_factory=dict)
    default_request: AgentRuntimeTickRequest = Field(default_factory=AgentRuntimeTickRequest)
    stop_on_error: bool = False


class AgentRuntimeBatchTickResponse(BaseModel):
    world_id: str
    requested_count: int = 0
    completed_count: int = 0
    failed_count: int = 0
    ticks: list[AgentRuntimeTickResponse] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)


class AgentRuntimeTickHistoryRequest(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)


class AgentRuntimeTickHistoryEntry(BaseModel):
    tick_id: str
    world_id: str
    message: str = ""
    selected_action_id: str | None = None
    selected_action_label: str | None = None
    cognitive_winner: str | None = None
    proposal_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentRuntimeTickHistoryResponse(BaseModel):
    agent_id: str
    count: int = 0
    history: list[AgentRuntimeTickHistoryEntry] = Field(default_factory=list)

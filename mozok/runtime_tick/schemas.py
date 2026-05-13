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

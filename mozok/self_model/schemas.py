from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

SelfModelMode = Literal["assistant", "roleplay_character", "simulacra_npc", "narrator", "world_director", "tool_agent"]


class SelfModelRequest(BaseModel):
    agent_mode: str | None = None
    current_task: str = ""
    user_message: str = ""
    cognitive_field: dict[str, Any] | None = None
    perception_summary: str = ""
    action_plan: dict[str, Any] | None = None
    reflection_summary: str = ""
    uncertainty: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SelfModelState(BaseModel):
    agent_id: str
    mode: str
    self_description: str
    current_task: str = ""
    active_focus: str = ""
    confidence: float = 0.5
    uncertainty: float = 0.5
    limitations: list[str] = Field(default_factory=list)
    needs: list[str] = Field(default_factory=list)
    behavioural_constraints: list[str] = Field(default_factory=list)
    reflective_notes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SelfModelResponse(BaseModel):
    agent_id: str
    read_only: bool = True
    state: SelfModelState
    prompt_block: str
    notes: list[str] = Field(default_factory=list)


class SelfModelProposalRequest(SelfModelRequest):
    store_proposal: bool = True
    approval_mode: str = "manual_review"


class SelfModelProposalResponse(BaseModel):
    agent_id: str
    self_model: SelfModelResponse
    proposal: dict[str, Any] | None = None

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from mozok.change_proposals.schemas import ApprovalMode, ChangeProposalRead


ReflectionOutcome = Literal["unknown", "success", "neutral", "failure"]


class ReflectionRequest(BaseModel):
    """Reflect on one completed turn and optionally create safe change proposals."""

    agent_id: str
    session_id: str = "default"
    user_message: str
    assistant_response: str = ""
    cognitive_field: dict[str, Any] | None = None
    used_memory_ids: list[int] = Field(default_factory=list)
    used_goal_ids: list[int] = Field(default_factory=list)
    used_procedural_skill_ids: list[int] = Field(default_factory=list)
    outcome: ReflectionOutcome = "unknown"
    feedback: str = ""
    create_change_proposals: bool = True
    approval_mode: ApprovalMode = "manual_review"
    auto_apply: bool = False
    store_proposals: bool = True
    memory_importance: int = Field(default=4, ge=1, le=10)
    max_summary_chars: int = Field(default=420, ge=80, le=2000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReflectionSignal(BaseModel):
    signal_type: str
    summary: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)


class ReflectionResponse(BaseModel):
    agent_id: str
    session_id: str = "default"
    read_only: bool = True
    proposal_count: int = 0
    auto_applied_count: int = 0
    signals: list[ReflectionSignal] = Field(default_factory=list)
    proposals: list[ChangeProposalRead] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

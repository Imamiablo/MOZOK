from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


RiskLevel = Literal["low", "medium", "high"]
ApprovalMode = Literal["manual_review", "apply_low_risk", "auto_with_rollback", "dry_run_only"]
ProposalStatus = Literal["pending", "applied", "rejected"]
OperationType = Literal[
    "add_memory",
    "update_agent_metadata",
    "update_goal",
    "update_entity_state",
    "add_knowledge_relation",
    "record_skill_usage_result",
    "no_op",
]


class ChangeOperation(BaseModel):
    """One atomic, reviewable change proposed by a cognitive/reflection/maintenance layer."""

    operation_type: OperationType = "no_op"
    target_type: str = Field(default="agent", examples=["memory", "agent", "procedural_skill"])
    target_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    risk_level: RiskLevel = "low"


class ChangeProposalCreate(BaseModel):
    proposal_type: str = Field(default="manual", examples=["reflection", "maintenance", "cognitive_broadcast"])
    summary: str
    rationale: str = ""
    risk_level: RiskLevel = "low"
    operations: list[ChangeOperation] = Field(default_factory=list)
    approval_mode: ApprovalMode = "manual_review"
    source: str = "api"
    metadata: dict[str, Any] = Field(default_factory=dict)
    store: bool = Field(default=True, description="If false, return a preview without storing it on the agent.")


class ChangeProposalRead(BaseModel):
    proposal_id: str
    agent_id: str
    proposal_type: str
    summary: str
    rationale: str = ""
    risk_level: RiskLevel = "low"
    operations: list[ChangeOperation] = Field(default_factory=list)
    approval_mode: ApprovalMode = "manual_review"
    source: str = "api"
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: ProposalStatus = "pending"
    created_at: datetime | None = None
    updated_at: datetime | None = None
    applied_at: datetime | None = None
    rejected_at: datetime | None = None
    applied_operation_count: int = 0
    rollback_snapshot: dict[str, Any] | None = None
    notes: list[str] = Field(default_factory=list)


class ChangeProposalListResponse(BaseModel):
    agent_id: str
    proposals: list[ChangeProposalRead]


class ChangeProposalDecisionRequest(BaseModel):
    proposal_ids: list[str] | None = Field(default=None, description="Null means all matching pending proposals.")
    proposal_type: str | None = None
    max_risk_level: RiskLevel = "high"
    dry_run: bool = False
    note: str | None = None


class ChangeProposalApplyResult(BaseModel):
    proposal_id: str
    status: ProposalStatus
    applied_operation_count: int = 0
    skipped_operation_count: int = 0
    rollback_snapshot: dict[str, Any] | None = None
    notes: list[str] = Field(default_factory=list)


class ChangeProposalDecisionResponse(BaseModel):
    agent_id: str
    dry_run: bool
    changed: bool
    results: list[ChangeProposalApplyResult]


class ChangeProposalAutoPolicyRequest(BaseModel):
    approval_mode: ApprovalMode = "apply_low_risk"
    proposal_type: str | None = None
    dry_run: bool = False
    max_to_apply: int = Field(default=25, ge=1, le=250)


class ChangeProposalAutoPolicyResponse(BaseModel):
    agent_id: str
    approval_mode: ApprovalMode
    dry_run: bool
    applied_count: int = 0
    skipped_count: int = 0
    results: list[ChangeProposalApplyResult] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

BeliefRelation = Literal["supports", "contradicts", "supersedes", "uncertain"]


class BeliefClaim(BaseModel):
    content: str
    source: str = "user_or_world"
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    source_trust: float = Field(default=0.7, ge=0.0, le=1.0)
    valid_from: str | None = Field(default=None, description="Optional ISO-ish temporal validity start for this claim.")
    valid_until: str | None = Field(default=None, description="Optional ISO-ish temporal validity end for this claim.")
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BeliefRevisionRequest(BaseModel):
    claim: BeliefClaim
    world_id: str = "default"
    memory_limit: int = Field(default=50, ge=0, le=500)
    min_token_overlap: float = Field(default=0.2, ge=0.0, le=1.0)
    include_inactive: bool = False
    create_change_proposal: bool = False
    store_proposal: bool = True
    approval_mode: str = "manual_review"
    metadata: dict[str, Any] = Field(default_factory=dict)


class BeliefGraphNode(BaseModel):
    node_type: str
    node_id: str
    content: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    source: str = "unknown"
    source_trust: float = Field(default=0.5, ge=0.0, le=1.0)
    temporal_status: str = "current"
    valid_from: str | None = None
    valid_until: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BeliefGraphEdge(BaseModel):
    source_node_id: str
    relation: BeliefRelation
    target_node_id: str
    strength: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    temporal_relation: str = "same_period"
    recommended_effect: str = "review"
    reasons: list[str] = Field(default_factory=list)


class BeliefGraphSummary(BaseModel):
    nodes: list[BeliefGraphNode] = Field(default_factory=list)
    edges: list[BeliefGraphEdge] = Field(default_factory=list)
    recommended_relation_payloads: list[dict[str, Any]] = Field(default_factory=list)


class BeliefRevisionCandidate(BaseModel):
    relation: BeliefRelation
    confidence: float
    memory_id: int | None = None
    memory_type: str | None = None
    memory_content: str | None = None
    token_overlap: float = 0.0
    source_trust: float = Field(default=0.5, ge=0.0, le=1.0)
    temporal_status: str = "current"
    suggested_confidence_delta: float = 0.0
    valid_from: str | None = None
    valid_until: str | None = None
    reasons: list[str] = Field(default_factory=list)


class BeliefRevisionResponse(BaseModel):
    agent_id: str
    read_only: bool = True
    claim: BeliefClaim
    candidates: list[BeliefRevisionCandidate] = Field(default_factory=list)
    recommended_action: str = "no_change"
    belief_graph: BeliefGraphSummary = Field(default_factory=BeliefGraphSummary)
    proposal: dict[str, Any] | None = None
    notes: list[str] = Field(default_factory=list)

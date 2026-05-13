from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

BeliefRelation = Literal["supports", "contradicts", "supersedes", "uncertain"]


class BeliefClaim(BaseModel):
    content: str
    source: str = "user_or_world"
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
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


class BeliefRevisionCandidate(BaseModel):
    relation: BeliefRelation
    confidence: float
    memory_id: int | None = None
    memory_type: str | None = None
    memory_content: str | None = None
    token_overlap: float = 0.0
    reasons: list[str] = Field(default_factory=list)


class BeliefRevisionResponse(BaseModel):
    agent_id: str
    read_only: bool = True
    claim: BeliefClaim
    candidates: list[BeliefRevisionCandidate] = Field(default_factory=list)
    recommended_action: str = "no_change"
    proposal: dict[str, Any] | None = None
    notes: list[str] = Field(default_factory=list)

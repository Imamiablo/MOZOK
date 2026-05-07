"""
Pydantic schemas for Lorebook API.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


LorebookVisibility = Literal["public", "restricted", "narrator_only"]
LorebookKnowledgeState = Literal["known", "rumored", "partial", "hidden"]


class LorebookEntryUpsert(BaseModel):
    world_id: str = Field("default", examples=["default", "from_series_world"])
    entry_key: str = Field(..., examples=["old_well_secret", "cats_are_insidious"])
    title: str = Field(..., examples=["The Old Well"])
    content: str = Field(..., examples=["The old well connects to ancient tunnels."])
    category: str = Field("general", examples=["location", "rule", "faction", "character", "world_truth"])
    visibility: LorebookVisibility = Field(
        "restricted",
        description="public = visible to everyone; restricted = only linked agents; narrator_only = mainly narrator/GM agents.",
    )
    importance: int = Field(5, ge=0, le=10)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LorebookEntryRead(BaseModel):
    id: int
    world_id: str
    entry_key: str
    title: str
    content: str
    category: str
    visibility: str
    importance: int
    tags: list[str]
    metadata: dict[str, Any]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AgentLorebookKnowledgeUpsert(BaseModel):
    agent_id: str = Field(..., examples=["npc_bob", "narrator_001", "assistant_001"])
    world_id: str = Field("default")
    entry_key: str = Field(..., examples=["old_well_secret"])
    knowledge_state: LorebookKnowledgeState = Field("known")
    confidence: int = Field(10, ge=0, le=10)
    notes: str | None = Field(None, examples=["Bob heard this as a rumour from Alice."])
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentLorebookKnowledgeRead(BaseModel):
    id: int
    agent_id: str
    lorebook_entry_id: int
    knowledge_state: str
    confidence: int
    notes: str | None
    metadata: dict[str, Any]
    is_active: bool
    entry: LorebookEntryRead

    class Config:
        from_attributes = True


class LorebookContextItem(BaseModel):
    source: str = "lorebook"
    lorebook_entry_id: int
    world_id: str
    entry_key: str
    title: str
    category: str
    visibility: str
    importance: int
    knowledge_state: str
    confidence: int | None = None
    content: str
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LorebookContextResponse(BaseModel):
    agent_id: str
    world_id: str
    include_public: bool
    include_narrator_only: bool
    count: int
    items: list[LorebookContextItem]
    context_text: str

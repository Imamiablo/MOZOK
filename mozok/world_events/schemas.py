from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from mozok.perception.schemas import PerceptionEvent


class WorldEventCreate(BaseModel):
    world_id: str = Field(default="default", examples=["old_well_world"])
    agent_id: str | None = Field(default=None, description="Optional agent primarily concerned by this event.")
    event_type: str = Field(default="world_event", examples=["sound_heard", "npc_entered", "tool_result"])
    content: str = Field(..., examples=["A metallic sound echoes from the old well."])
    source: str = Field(default="external", examples=["game_engine", "ui", "tool", "user"])
    channel_hint: str | None = Field(default=None, examples=["hearing", "vision", "tool", "world_event"])
    salience: float = Field(default=5.0, ge=0.0, le=10.0)
    reliability: float = Field(default=1.0, ge=0.0, le=1.0)
    visibility: str = Field(default="local", examples=["local", "agent", "world", "private"])
    tags: list[str] = Field(default_factory=list)
    ttl_seconds: int | None = Field(default=None, ge=1, le=31_536_000, description="Optional time-to-live. Expired events are hidden unless include_inactive=true.")
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorldEventRead(BaseModel):
    event_id: str = Field(default_factory=lambda: f"evt_{uuid4().hex[:16]}")
    world_id: str = "default"
    agent_id: str | None = None
    event_type: str = "world_event"
    content: str
    source: str = "external"
    channel_hint: str | None = None
    salience: float = 5.0
    reliability: float = 1.0
    visibility: str = "local"
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    consumed_by_agent_ids: list[str] = Field(default_factory=list)
    acknowledged_by_agent_ids: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    expires_at: datetime | None = None
    active: bool = True


class WorldEventCreateRequest(BaseModel):
    events: list[WorldEventCreate] = Field(default_factory=list)
    store: bool = True


class WorldEventCreateResponse(BaseModel):
    read_only: bool = False
    stored: bool = True
    event_count: int = 0
    events: list[WorldEventRead] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class WorldEventSearchRequest(BaseModel):
    world_id: str = "default"
    agent_id: str | None = None
    event_type: str | None = None
    tags_any: list[str] = Field(default_factory=list)
    include_inactive: bool = False
    include_consumed: bool = True
    limit: int = Field(default=25, ge=1, le=250)


class WorldEventSearchResponse(BaseModel):
    world_id: str
    read_only: bool = True
    event_count: int = 0
    events: list[WorldEventRead] = Field(default_factory=list)


class WorldEventConsumeRequest(WorldEventSearchRequest):
    include_consumed: bool = False
    mark_consumed: bool = True


class WorldEventConsumeResponse(BaseModel):
    world_id: str
    agent_id: str
    consumed_count: int = 0
    events: list[WorldEventRead] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class WorldEventAcknowledgeRequest(BaseModel):
    world_id: str = "default"
    agent_id: str
    event_ids: list[str] = Field(default_factory=list)
    acknowledge: bool = True


class WorldEventAcknowledgeResponse(BaseModel):
    world_id: str
    agent_id: str
    acknowledged_count: int = 0
    events: list[WorldEventRead] = Field(default_factory=list)


class WorldEventExpireRequest(BaseModel):
    world_id: str | None = None
    expire_before_now: bool = True
    event_ids: list[str] = Field(default_factory=list)


class WorldEventExpireResponse(BaseModel):
    expired_count: int = 0
    event_ids: list[str] = Field(default_factory=list)


class WorldEventToPerceptionRequest(WorldEventSearchRequest):
    message: str = ""


class WorldEventToPerceptionResponse(BaseModel):
    events: list[WorldEventRead] = Field(default_factory=list)
    perception_events: list[PerceptionEvent] = Field(default_factory=list)

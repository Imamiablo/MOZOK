from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mozok.cognition.schemas import SensoryInput


class PerceptionEvent(BaseModel):
    """Adapter-neutral event that can be compiled into attended sensory inputs.

    The event can come from a game engine, UI, tool result, robot sensor,
    simulation tick, chat attachment, or any other external system. MOZOK does
    not assume a fixed world model here.
    """

    content: str = Field(..., examples=["A metal key falls into the old well."])
    event_type: str = Field(default="world_event", examples=["world_event", "tool_result", "ui", "chat", "body"])
    source: str = Field(default="external", examples=["game", "desktop_app", "tool", "user", "system"])
    channel_hint: str | None = Field(default=None, examples=["hearing", "vision", "tool", "body"])
    salience: float = Field(default=5.0, ge=0.0, le=10.0, description="How noticeable/important the event is before attention gating.")
    distance: float | None = Field(default=None, ge=0.0, description="Optional adapter-defined distance. Lower distance can increase attention.")
    reliability: float = Field(default=1.0, ge=0.0, le=1.0, description="How reliable the upstream event/source is considered to be.")
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PerceptionProfile(BaseModel):
    """Small, adapter-neutral policy for compiling events into sensory inputs."""

    enabled_channels: list[str] = Field(
        default_factory=lambda: ["vision", "hearing", "body", "tool", "ui", "world_event", "text"],
        description="Channels this adapter/agent is allowed to attend to. Unknown channels are still allowed when allow_unknown_channels is true.",
    )
    allow_unknown_channels: bool = True
    channel_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "vision": 1.0,
            "hearing": 1.0,
            "body": 1.1,
            "tool": 0.9,
            "ui": 0.8,
            "world_event": 0.8,
            "text": 0.7,
        },
        description="Optional per-channel attention multiplier.",
    )
    attention_keywords: list[str] = Field(default_factory=list, description="Keywords that raise attention if found in event text/tags.")
    distance_falloff: bool = Field(default=True, description="If true, optional event.distance reduces intensity/attention when large.")
    min_attention: float = Field(default=0.0, ge=0.0, le=10.0)
    max_inputs: int = Field(default=12, ge=1, le=100)
    deterministic_summary: bool = Field(
        default=True,
        description="Keep perception compilation deterministic. LLM rewriting can be added later as an optional adapter.",
    )


class PerceptionCompileRequest(BaseModel):
    events: list[PerceptionEvent] = Field(default_factory=list)
    existing_sensory_inputs: list[SensoryInput] = Field(default_factory=list)
    profile: PerceptionProfile = Field(default_factory=PerceptionProfile)
    message: str = Field(default="", description="Optional current message/query; matching terms can raise attention.")


class PerceptionReport(BaseModel):
    enabled: bool = True
    read_only: bool = True
    architecture: str = "adapter_neutral_perception_compiler"
    event_count: int = 0
    existing_sensory_input_count: int = 0
    generated_sensory_input_count: int = 0
    output_sensory_input_count: int = 0
    channels: list[str] = Field(default_factory=list)
    skipped_events: list[dict[str, Any]] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class PerceptionCompileResponse(BaseModel):
    sensory_inputs: list[SensoryInput] = Field(default_factory=list)
    report: PerceptionReport = Field(default_factory=PerceptionReport)

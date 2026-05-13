from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AgentModeProfile(BaseModel):
    """Resolved operating-mode profile for an agent.

    A mode is not personality. It is a small policy bundle that tells Mozok what
    kind of agent it is running: assistant, roleplay character, narrator,
    simulacra NPC, world director, or tool agent.
    """

    mode: str = Field(..., examples=["assistant", "simulacra_npc", "narrator"])
    label: str = ""
    description: str = ""

    # Context visibility / permissions.
    allow_narrator_only_lore: bool = False
    allowed_entity_state_kinds: list[str] | None = None

    # Default feature switches. Request payloads may still opt in/out.
    enable_cognitive_field_by_default: bool = False
    enable_perception_by_default: bool = False
    enable_reflection_by_default: bool = False
    can_autonomously_tick: bool = False
    can_execute_actions: bool = False

    # Behaviour guidance that is safe to include in the prompt.
    prompt_guidance: list[str] = Field(default_factory=list)

    # Adapter/UI metadata. This is deliberately open-ended so Mozok can stay
    # flexible for chat apps, games, desktop pets, tools, or future robotics.
    permissions: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentModeResolveRequest(BaseModel):
    agent_mode: str | None = Field(default=None, examples=["assistant", "narrator", "simulacra_npc"])
    overrides: dict[str, Any] = Field(default_factory=dict)


class AgentModeResolveResponse(BaseModel):
    agent_id: str
    profile: AgentModeProfile
    source: str
    warnings: list[str] = Field(default_factory=list)


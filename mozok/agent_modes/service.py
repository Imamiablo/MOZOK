from __future__ import annotations

from typing import Any

from mozok.agent_modes.profiles import BUILTIN_AGENT_MODE_PROFILES, DEFAULT_AGENT_MODE
from mozok.agent_modes.schemas import AgentModeProfile, AgentModeResolveResponse
from mozok.db.models import AgentRecord


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


class AgentModeService:
    """Resolve built-in and metadata-defined agent operating modes.

    Resolution order:
    1. explicit request agent_mode
    2. agent.metadata_json["agent_mode"] or ["mode"]
    3. assistant fallback

    Then metadata/request overrides are applied. Overrides are intentionally
    open-ended but only known AgentModeProfile fields are accepted by Pydantic.
    """

    def list_profiles(self) -> list[AgentModeProfile]:
        return list(BUILTIN_AGENT_MODE_PROFILES.values())

    def get_profile(self, mode: str) -> AgentModeProfile | None:
        return BUILTIN_AGENT_MODE_PROFILES.get((mode or "").strip())

    def resolve(
        self,
        agent: AgentRecord,
        agent_mode: str | None = None,
        overrides: dict[str, Any] | None = None,
    ) -> AgentModeResolveResponse:
        metadata = _as_dict(getattr(agent, "metadata_json", None))
        warnings: list[str] = []

        requested_mode = (agent_mode or metadata.get("agent_mode") or metadata.get("mode") or DEFAULT_AGENT_MODE)
        requested_mode = str(requested_mode).strip() or DEFAULT_AGENT_MODE

        base = BUILTIN_AGENT_MODE_PROFILES.get(requested_mode)
        source = "request" if agent_mode else "agent_metadata" if (metadata.get("agent_mode") or metadata.get("mode")) else "default"
        if base is None:
            warnings.append(f"Unknown agent mode '{requested_mode}'. Falling back to '{DEFAULT_AGENT_MODE}'.")
            base = BUILTIN_AGENT_MODE_PROFILES[DEFAULT_AGENT_MODE]
            source = "fallback"

        profile_data = base.model_dump()

        metadata_overrides = _as_dict(metadata.get("agent_mode_profile") or metadata.get("mode_profile"))
        profile_data.update(metadata_overrides)
        profile_data.update(_as_dict(overrides))

        # Keep the selected mode stable unless an override intentionally supplies
        # a different mode. This lets a scenario rename/tune labels without losing
        # the built-in policy identity.
        if not profile_data.get("mode"):
            profile_data["mode"] = base.mode

        profile = AgentModeProfile(**profile_data)
        return AgentModeResolveResponse(
            agent_id=agent.id,
            profile=profile,
            source=source,
            warnings=warnings,
        )

    def is_entity_state_kind_allowed(self, profile: AgentModeProfile, state_kind: str | None) -> bool:
        if not state_kind:
            return True
        if profile.allowed_entity_state_kinds is None:
            return True
        return state_kind in set(profile.allowed_entity_state_kinds)

    def filter_entity_states(self, profile: AgentModeProfile, states: list) -> list:
        if profile.allowed_entity_state_kinds is None:
            return states
        allowed = set(profile.allowed_entity_state_kinds)
        return [state for state in states if getattr(state, "state_kind", None) in allowed]

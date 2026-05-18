from __future__ import annotations

from typing import TYPE_CHECKING

from mozok_game.engine.models import Agent, SocialState

if TYPE_CHECKING:
    from mozok_game.engine.world_state import WorldState


RELATIONSHIP_KEYS = ("trust", "fear", "affinity", "resentment")


def social_state_for(agent: Agent, target_id: str) -> SocialState:
    if target_id == "player":
        agent.relationships["player"] = agent.social_to_player
        return agent.social_to_player
    if target_id not in agent.relationships:
        agent.relationships[target_id] = SocialState()
    return agent.relationships[target_id]


def apply_relationship_delta(agent: Agent, target_id: str, deltas: dict[str, float]) -> SocialState:
    social = social_state_for(agent, target_id)
    for key, amount in deltas.items():
        if hasattr(social, str(key)):
            setattr(social, str(key), float(getattr(social, str(key))) + float(amount))
    social.clamp()
    if target_id == "player":
        agent.social_to_player = social
    return social


def initialise_world_relationships(world: WorldState) -> None:
    for agent in world.agents.values():
        agent.relationships["player"] = agent.social_to_player
        for other in world.agents.values():
            if other.id != agent.id:
                social_state_for(agent, other.id)


def relationship_snapshot(agent: Agent, target_id: str = "player") -> dict[str, float]:
    social = social_state_for(agent, target_id)
    return {key: float(getattr(social, key)) for key in RELATIONSHIP_KEYS}


def relationship_delta(before: dict[str, float], agent: Agent, target_id: str = "player") -> dict[str, float]:
    after = relationship_snapshot(agent, target_id)
    return {key: after[key] - float(before.get(key, after[key])) for key in RELATIONSHIP_KEYS}


def format_relationship_delta(delta: dict[str, float]) -> str:
    parts: list[str] = []
    labels = {
        "trust": "trust",
        "fear": "fear",
        "affinity": "affinity",
        "resentment": "resentment",
    }
    for key in RELATIONSHIP_KEYS:
        value = float(delta.get(key, 0.0))
        if abs(value) >= 0.05:
            parts.append(f"{labels[key]} {value:+.1f}")
    return ", ".join(parts) if parts else "no visible relationship shift"

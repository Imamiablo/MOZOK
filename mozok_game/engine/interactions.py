from __future__ import annotations

from mozok_game.engine.object_effects import execute_object_interaction
from mozok_game.engine.models import Agent, WorldObject
from mozok_game.engine.world_state import WorldState


def interact_with_object(world: WorldState, obj: WorldObject, interaction_id: str = "") -> None:
    execute_object_interaction(world, "player", obj, interaction_id, reason="player interact")


def talk_to_agent(world: WorldState, agent: Agent) -> None:
    agent.needs.social = max(0.0, agent.needs.social - 15.0)
    agent.social_to_player.affinity += 2.0
    agent.social_to_player.trust += 1.0
    agent.social_to_player.clamp()
    recent_tags = {tag for event in world.event_log[-8:] for tag in event.tags}
    memory = agent.memory_snippets[0] if agent.memory_snippets else ""
    templates = dict((world.dialogue_templates.get("direct_chat") or {}) if isinstance(world.dialogue_templates.get("direct_chat"), dict) else {})
    if agent.traits.get("dominance", 0.0) > 0.6 and (_tags_mean_resource_pressure(recent_tags) or agent.social_to_player.resentment > 25):
        line = _render_line(templates, "dominance_food", agent, memory, "I am watching the shared resources. Trust gets thin when resources do.")
    elif agent.traits.get("curiosity", 0.0) > 0.65 and (_tags_mean_mystery(recent_tags) or agent.needs.curiosity > 65):
        line = _render_line(templates, "curiosity_mystery", agent, memory, "Something here keeps becoming a pattern when we pay attention.")
    elif agent.traits.get("empathy", 0.0) > 0.65 and ("danger" in recent_tags or agent.needs.stress > 55):
        line = _render_line(templates, "empathy_danger", agent, memory, "Stay where I can see you. People get hurt when groups pretend they are fine.")
    elif agent.emotion == "afraid":
        line = _render_line(templates, "afraid", agent, memory, "Please tell me you heard that too. I do not want to be the only one scared.")
    elif agent.emotion == "angry":
        line = _render_line(templates, "angry", agent, memory, "We need rules before fear makes them for us.")
    elif agent.emotion == "curious":
        line = _render_line(templates, "curious", agent, memory, "This place is wrong in a way I can almost map.")
    elif agent.emotion == "tired":
        line = _render_line(templates, "tired", agent, memory, "I can barely stand. Whatever this place wants, it can wait a minute.")
    elif memory:
        line = _render_line(templates, "memory", agent, memory, f"I keep thinking about this: {memory}")
    else:
        line = _render_line(templates, "default", agent, memory, "I am still here. That has to count for something.")
    agent.last_dialogue = line
    world.log("player_talk", line, source=agent.id, salience=6, tags=["dialogue", "social"], metadata={"agent_id": agent.id, "memory_hint": memory})


def _render_line(templates: dict, key: str, agent: Agent, memory: str, fallback: str) -> str:
    template = str(templates.get(key) or "{name}: " + fallback)
    if not template.startswith("{name}:") and not template.startswith(agent.name + ":"):
        template = "{name}: " + template
    return template.replace("{name}", agent.name).replace("{memory}", memory)


def _tags_mean_resource_pressure(tags: set[str]) -> bool:
    return bool(tags & {"food", "supplies", "scarce", "scarcity", "resource", "resources", "shared_resource"})


def _tags_mean_mystery(tags: set[str]) -> bool:
    return bool(tags & {"mystery", "unknown", "evidence", "signal", "sound", "anomaly"})

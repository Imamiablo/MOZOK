from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mozok_game.engine.inventory import item_capabilities
from mozok_game.engine.models import Agent, WorldEvent, WorldObject
from mozok_game.engine.world_state import WorldState


@dataclass(slots=True)
class Impulse:
    kind: str
    label: str
    score: float
    reason: str
    tool_name: str = "wait"
    parameters: dict[str, Any] = field(default_factory=dict)
    dialogue: str = ""
    atom_id: str = ""
    pressure_axes: list[str] = field(default_factory=list)


def generate_impulses(world: WorldState, agent: Agent, recent_events: list[WorldEvent] | None = None) -> list[Impulse]:
    recent = recent_events or world.event_log[-10:]
    atoms = load_drama_atoms()
    impulses: list[Impulse] = []
    for atom in atoms:
        impulse = _impulse_from_atom(world, agent, recent, atom)
        if impulse and impulse.score >= 18.0:
            impulses.append(impulse)
    impulses.sort(key=lambda item: item.score, reverse=True)
    return impulses


def load_drama_atoms() -> list[dict[str, Any]]:
    path = Path(__file__).resolve().parents[1] / "data" / "drama_atoms" / "core_atoms.json"
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [dict(item) for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _impulse_from_atom(world: WorldState, agent: Agent, recent_events: list[WorldEvent], atom: dict[str, Any]) -> Impulse | None:
    axes = [str(axis) for axis in atom.get("activated_by") or []]
    pressure_score = sum(world.pressure.get(axis, 0.0) for axis in axes) * 42.0
    tag_score = _tag_match_score(atom, recent_events)
    trait_score = _trait_bias_score(agent, dict(atom.get("actor_bias") or {}))
    social_score = _social_bias_score(agent, dict(atom.get("social_bias") or {}))
    base = float(atom.get("base_score", 10.0))
    score = base + pressure_score + tag_score + trait_score + social_score
    if score <= 0:
        return None

    target_obj = _choose_target_object(world, atom)
    target_agent = _choose_target_agent(world, agent, atom)
    tool_name = str(atom.get("tool_name") or "wait")
    parameters: dict[str, Any] = {}

    if tool_name == "move_to_object":
        if not target_obj:
            return None
        parameters["object_id"] = target_obj.id
    elif tool_name == "talk_to_agent":
        if not target_agent:
            return None
        parameters["target_agent_id"] = target_agent.id
        if agent.position.manhattan(target_agent.position) > 4:
            score -= 12.0
    elif tool_name == "talk_to_player":
        if agent.position.manhattan(world.player.position) > 3:
            score -= 14.0
    elif tool_name == "use_item_on_target":
        if not target_obj:
            return None
        capability = str(atom.get("required_capability") or "")
        item_id = _choose_item_with_capability(agent, capability)
        if not item_id:
            return None
        parameters = {"item_id": item_id, "target_id": target_obj.id, "primitive": capability}

    if score < 18.0:
        return None

    dialogue = _render_dialogue(atom, agent, target_agent)
    reason = _reason(atom, axes, pressure_score, tag_score, trait_score, social_score)
    return Impulse(
        kind=str(atom.get("kind") or atom.get("id") or "impulse"),
        label=str(atom.get("label") or atom.get("id") or "impulse"),
        score=score,
        reason=reason,
        tool_name=tool_name,
        parameters=parameters,
        dialogue=dialogue,
        atom_id=str(atom.get("id") or ""),
        pressure_axes=axes,
    )


def _tag_match_score(atom: dict[str, Any], recent_events: list[WorldEvent]) -> float:
    wanted = set(str(tag) for tag in atom.get("event_tags") or [])
    if not wanted:
        return 0.0
    score = 0.0
    for event in recent_events[-8:]:
        overlap = wanted & set(event.tags)
        if overlap:
            score += min(14.0, len(overlap) * 5.0 + event.salience * 0.7)
    return min(score, 34.0)


def _trait_bias_score(agent: Agent, bias: dict[str, Any]) -> float:
    score = 0.0
    for trait, weight in bias.items():
        value = agent.traits.get(str(trait), 0.5)
        score += (value - 0.5) * float(weight) * 40.0
    return score


def _social_bias_score(agent: Agent, bias: dict[str, Any]) -> float:
    social = agent.social_to_player
    score = 0.0
    if "low_trust" in bias:
        score += (1.0 - social.trust / 100.0) * float(bias["low_trust"]) * 30.0
    if "resentment" in bias:
        score += (social.resentment / 100.0) * float(bias["resentment"]) * 30.0
    if "fear" in bias:
        score += (social.fear / 100.0) * float(bias["fear"]) * 30.0
    return score


def _choose_target_object(world: WorldState, atom: dict[str, Any]) -> WorldObject | None:
    tags = [str(tag) for tag in atom.get("target_tags") or []]
    for tag in tags:
        target = world.find_object_with_tag(tag)
        if target:
            return target
    return None


def _choose_target_agent(world: WorldState, agent: Agent, atom: dict[str, Any]) -> Agent | None:
    bias = dict(atom.get("target_agent_bias") or {})
    candidates = [other for other in world.agents.values() if other.id != agent.id and other.alive]
    if not candidates:
        return None
    scored: list[tuple[float, Agent]] = []
    for other in candidates:
        score = 0.0
        if bias.get("stress"):
            score += other.needs.stress * float(bias["stress"])
        if bias.get("wounded") and "wounded" in other.status_flags:
            score += 100.0 * float(bias["wounded"])
        score -= agent.position.manhattan(other.position) * 4.0
        scored.append((score, other))
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1] if scored and scored[0][0] > 0 else None


def _choose_item_with_capability(agent: Agent, capability: str) -> str:
    for item_id in agent.inventory:
        if capability in item_capabilities(item_id):
            return item_id
    return ""


def _render_dialogue(atom: dict[str, Any], agent: Agent, target: Agent | None) -> str:
    template = str(atom.get("dialogue_template") or "")
    if not template:
        return ""
    return template.format(actor=agent.name, target=target.name if target else "you")


def _reason(atom: dict[str, Any], axes: list[str], pressure_score: float, tag_score: float, trait_score: float, social_score: float) -> str:
    return (
        f"drama atom {atom.get('id')}: axes={','.join(axes) or 'none'} "
        f"pressure={pressure_score:.1f} tags={tag_score:.1f} traits={trait_score:.1f} social={social_score:.1f}"
    )

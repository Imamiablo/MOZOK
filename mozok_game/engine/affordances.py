from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mozok_game.engine.capabilities import target_primitives
from mozok_game.engine.impulses import generate_impulses
from mozok_game.engine.inventory import choose_item_for_agent_need, item_capabilities, item_name
from mozok_game.engine.models import Agent, AgentIntent, WorldEvent, WorldObject
from mozok_game.engine.world_state import WorldState


@dataclass(slots=True)
class Affordance:
    tool_name: str
    label: str
    score: float
    parameters: dict[str, Any]
    rationale: str
    dialogue: str = ""


NEED_OBJECT_TAGS = {
    "thirst": "water",
    "hunger": "food",
    "fatigue": "shelter",
    "stress": "safety",
}

CLAIM_OBJECT_HINTS = {
    "cave": "cave_entrance",
    "radio": "broken_radio",
    "water": "water_source",
    "spring": "water_source",
    "food": "food_crate",
    "crate": "food_crate",
    "fire": "campfire",
    "camp": "campfire",
}


def build_agent_affordances(world: WorldState, agent: Agent, recent_events: list[WorldEvent]) -> list[Affordance]:
    affordances: list[Affordance] = [
        Affordance("wait", "wait and observe", 8.0, {}, "no higher-priority affordance won"),
    ]
    affordances.extend(_need_affordances(world, agent))
    affordances.extend(_item_capability_affordances(world, agent))
    affordances.extend(_impulse_affordances(world, agent, recent_events))
    affordances.extend(_claim_affordances(world, agent))
    affordances.extend(_inventory_affordances(world, agent))
    affordances.extend(_social_affordances(world, agent, recent_events))
    affordances.extend(_curiosity_affordances(world, agent, recent_events))
    affordances.sort(key=lambda item: item.score, reverse=True)
    return affordances


def choose_offline_intent(world: WorldState, agent: Agent, recent_events: list[WorldEvent]) -> AgentIntent:
    affordances = build_agent_affordances(world, agent, recent_events)
    chosen = affordances[0]
    _apply_deliberation_trace(agent, affordances, chosen)
    return AgentIntent(
        agent_id=agent.id,
        action_kind="game_command" if chosen.tool_name != "wait" else "no_op",
        tool_name=chosen.tool_name,
        parameters=chosen.parameters,
        dialogue=chosen.dialogue,
        emotion=agent.emotion,
        rationale=f"OFFLINE DELIBERATION: {chosen.rationale}",
    )


def serialise_affordances(affordances: list[Affordance], limit: int = 8) -> list[dict[str, Any]]:
    return [
        {
            "tool_name": item.tool_name,
            "label": item.label,
            "score_hint": round(item.score, 2),
            "parameters": item.parameters,
            "rationale": item.rationale,
        }
        for item in affordances[:limit]
    ]


def _need_affordances(world: WorldState, agent: Agent) -> list[Affordance]:
    urgent, value = agent.needs.most_urgent
    if value < 48:
        return []
    if urgent == "hunger" and "ration" in agent.inventory:
        return [
            Affordance(
                "use_inventory_item",
                "eat carried ration",
                22.0 + value,
                {"item_id": "ration"},
                f"hunger={value:.0f} and {agent.name} has a ration",
            )
        ]
    target = _target_for_need(world, urgent)
    if not target:
        return []
    score = 18.0 + value * 0.75
    if urgent == "stress" and target.kind in {"campfire", "shelter"}:
        score += 8.0
    return [
        Affordance(
            "move_to_object",
            f"address {urgent}",
            score,
            {"object_id": target.id},
            f"{urgent}={value:.0f} makes {target.name} useful",
        )
    ]


def _inventory_affordances(world: WorldState, agent: Agent) -> list[Affordance]:
    result: list[Affordance] = []
    if "wounded" in agent.status_flags:
        if "medkit" in agent.inventory:
            result.append(
                Affordance(
                    "use_inventory_item",
                    "treat wound",
                    96.0 - agent.health * 0.25,
                    {"item_id": "medkit"},
                    f"{agent.name} is wounded and has a medkit",
                )
            )
        else:
            medkit = world.find_object_with_tag("medical")
            if medkit and not medkit.state.get("taken"):
                result.append(
                    Affordance(
                        "move_to_object",
                        "find medical supplies",
                        80.0 - agent.health * 0.2,
                        {"object_id": medkit.id},
                        f"{agent.name} is wounded and knows about {medkit.name}",
                    )
                )

    for other in world.agents.values():
        if other.id == agent.id or not other.alive:
            continue
        distance = agent.position.manhattan(other.position)
        if distance > 3:
            continue
        needed = choose_item_for_agent_need(other)
        if needed and needed in agent.inventory:
            result.append(
                Affordance(
                    "give_item",
                    f"give {item_name(needed)} to {other.name}",
                    74.0 - distance * 5.0,
                    {"target_agent_id": other.id, "item_id": needed},
                    f"{other.name} needs {item_name(needed)} and {agent.name} has one",
                    dialogue=f"{agent.name}: {other.name}, take this {item_name(needed)}. You need it more than I do.",
                )
            )
    return result


def _item_capability_affordances(world: WorldState, agent: Agent) -> list[Affordance]:
    result: list[Affordance] = []
    for item_id in set(agent.inventory):
        capabilities = item_capabilities(item_id)
        for obj in world.objects.values():
            if obj.state.get("taken"):
                continue
            supported = (capabilities & target_primitives(obj)) - {"carry", "consume", "drag", "give", "threaten", "throw", "trade"}
            for primitive in sorted(supported):
                if obj.state.get("open") and primitive in {"cut", "pry"}:
                    continue
                if obj.state.get(f"{primitive}ed") or obj.state.get(f"{primitive}_done"):
                    continue
                score = _score_item_primitive(world, agent, obj, primitive)
                if score < 34.0:
                    continue
                result.append(
                    Affordance(
                        "use_item_on_target",
                        f"{primitive} {obj.name}",
                        score,
                        {"item_id": item_id, "target_id": obj.id, "primitive": primitive},
                        f"{item_name(item_id)} supports {primitive}; {obj.name} accepts it via object data/tags",
                    )
                )
    return result


def _score_item_primitive(world: WorldState, agent: Agent, obj: WorldObject, primitive: str) -> float:
    tags = set(obj.tags)
    score = 18.0
    if primitive in obj.capability_effects:
        score += 20.0
    if primitive in {"pry", "cut"} and ("locked" in tags or "tool_required" in tags):
        score += 38.0 + world.pressure.get("opportunity", 0.0) * 20.0
    if primitive == "anchor" and ({"danger", "mystery", "safety"} & tags):
        stress = agent.needs.stress + agent.social_to_player.fear
        score += 28.0 + (world.pressure.get("danger", 0.0) + world.pressure.get("mystery", 0.0)) * 90.0 + min(20.0, stress * 0.16)
    if primitive == "test" and ({"food", "toxic", "unknown"} & tags):
        score += 24.0 + world.pressure.get("scarcity", 0.0) * 35.0 + world.pressure.get("danger", 0.0) * 22.0
    if primitive == "repair" and ("tool" in tags or "radio" in tags):
        score += 20.0 + world.pressure.get("opportunity", 0.0) * 45.0
    if primitive == "inspect" and ({"mystery", "danger", "evidence", "unknown", "tool"} & tags):
        score += 12.0 + agent.traits.get("curiosity", 0.0) * 16.0
    return score


def _claim_affordances(world: WorldState, agent: Agent) -> list[Affordance]:
    result: list[Affordance] = []
    claims = [
        claim
        for claim in world.claim_log[-8:]
        if claim.listener_id in {agent.id, "group"} and claim.claim_type not in {"player_intention", "player_commitment", "promise", "opinion", "navigation_status", "conversation"}
    ]
    for claim in claims[-3:]:
        target = world.objects.get(claim.target_object_id) if claim.target_object_id else _object_from_claim(world, claim.text)
        if not target:
            continue
        suspicion = 100.0 - agent.social_to_player.trust + agent.social_to_player.fear
        curiosity = agent.needs.curiosity
        score = 24.0 + curiosity * 0.45 + suspicion * 0.18 + claim.confidence * 12.0
        result.append(
            Affordance(
                "move_to_object",
                "verify an unconfirmed claim",
                score,
                {"object_id": target.id},
                f"unverified claim points at {target.name}: {claim.text[:80]}",
            )
        )
        if agent.position.manhattan(world.player.position) <= 2:
            result.append(
                Affordance(
                    "talk_to_player",
                    "challenge or clarify player claim",
                    score + 7.0,
                    {},
                    f"player made an unverified claim: {claim.text[:80]}",
                    dialogue=f"{agent.name}: I need to be clear: you said '{claim.text}'. I am not treating it as fact yet.",
                )
            )
    return result


def _impulse_affordances(world: WorldState, agent: Agent, recent_events: list[WorldEvent]) -> list[Affordance]:
    result: list[Affordance] = []
    for impulse in generate_impulses(world, agent, recent_events)[:4]:
        result.append(
            Affordance(
                impulse.tool_name,
                f"impulse: {impulse.label}",
                impulse.score,
                impulse.parameters,
                impulse.reason,
                impulse.dialogue,
            )
        )
    return result


def _social_affordances(world: WorldState, agent: Agent, recent_events: list[WorldEvent]) -> list[Affordance]:
    result: list[Affordance] = []
    near_player = agent.position.manhattan(world.player.position) <= 2
    recent_tags = {tag for event in recent_events for tag in event.tags}
    social_pressure = agent.needs.social + agent.social_to_player.fear * 0.3 + agent.social_to_player.resentment * 0.35
    if near_player and social_pressure > 44:
        result.append(
            Affordance(
                "talk_to_player",
                "initiate player conversation",
                20.0 + social_pressure,
                {},
                f"social pressure={social_pressure:.0f} and player is near",
                dialogue=_player_line(agent, recent_tags),
            )
        )
    for other in world.agents.values():
        if other.id == agent.id or not other.alive:
            continue
        distance = agent.position.manhattan(other.position)
        if distance <= 3 and (agent.needs.social > 58 or "conflict" in recent_tags or "social_risk" in recent_tags):
            result.append(
                Affordance(
                    "talk_to_agent",
                    "talk to another agent",
                    31.0 + agent.needs.social * 0.35 - distance * 3.0,
                    {"target_agent_id": other.id},
                    f"{other.name} is close and social pressure is active",
                    dialogue=f"{agent.name}: {other.name}, we should compare what we think is happening before this gets worse.",
                )
            )
    return result


def _curiosity_affordances(world: WorldState, agent: Agent, recent_events: list[WorldEvent]) -> list[Affordance]:
    recent_tags = {tag for event in recent_events for tag in event.tags}
    result: list[Affordance] = []
    if "cave" in recent_tags or "mystery" in recent_tags:
        cave = world.object_by_kind("cave_entrance")
        if cave:
            danger_penalty = agent.needs.stress * 0.35 + agent.social_to_player.fear * 0.45
            score = 18.0 + agent.needs.curiosity * 0.65 - danger_penalty
            if score > 25:
                result.append(
                    Affordance(
                        "move_to_object",
                        "investigate mystery",
                        score,
                        {"object_id": cave.id},
                        f"curiosity={agent.needs.curiosity:.0f} beat danger penalty {danger_penalty:.0f}",
                    )
                )
    if "radio" in recent_tags or "sound" in recent_tags:
        radio = world.object_by_kind("broken_radio")
        if radio:
            result.append(
                Affordance(
                    "move_to_object",
                    "inspect strange signal",
                    22.0 + agent.needs.curiosity * 0.45,
                    {"object_id": radio.id},
                    "recent signal event made the radio salient",
                )
            )
    return result


def _target_for_need(world: WorldState, need: str) -> WorldObject | None:
    if need == "hunger":
        crate = world.object_by_kind("food_crate")
        if crate and int(crate.state.get("food", 0)) > 0:
            return crate
        berries = world.object_by_kind("poisonous_berries")
        if berries and int(berries.state.get("berries", 0)) > 0:
            return berries
    tag = NEED_OBJECT_TAGS.get(need)
    if tag:
        target = _available_object_with_tag(world, tag)
        if target:
            return target
    if need == "stress":
        return world.object_by_kind("campfire") or world.find_object_with_tag("shelter")
    if need == "fatigue":
        return world.find_object_with_tag("shelter") or world.object_by_kind("campfire")
    return None


def _available_object_with_tag(world: WorldState, tag: str) -> WorldObject | None:
    for obj in world.objects.values():
        if tag not in obj.tags:
            continue
        if obj.state.get("taken"):
            continue
        if obj.kind == "food_crate" and int(obj.state.get("food", 0)) <= 0:
            continue
        if obj.kind == "poisonous_berries" and int(obj.state.get("berries", 0)) <= 0:
            continue
        return obj
    return None


def _object_from_claim(world: WorldState, text: str) -> WorldObject | None:
    lower = text.lower()
    for hint, kind in CLAIM_OBJECT_HINTS.items():
        if hint in lower:
            return world.object_by_kind(kind)
    return None


def _player_line(agent: Agent, tags: set[str]) -> str:
    if "cave" in tags and agent.traits.get("curiosity", 0.0) > 0.65:
        return f"{agent.name}: I need to say this before we move again: the cave is becoming a hypothesis, not just a place."
    if "food" in tags and (agent.traits.get("dominance", 0.0) > 0.6 or "control" in agent.values):
        return f"{agent.name}: We need an explicit rule about the crate before hunger writes one for us."
    if "danger" in tags and (agent.traits.get("empathy", 0.0) > 0.65 or agent.traits.get("caution", 0.0) > 0.65):
        return f"{agent.name}: I need everyone close enough to hear each other. That is not panic; that is medicine."
    return f"{agent.name}: Can we talk for a moment? I do not want silence making the decisions."


def _apply_deliberation_trace(agent: Agent, affordances: list[Affordance], chosen: Affordance) -> None:
    top = "; ".join(f"{item.label}:{item.score:.0f}" for item in affordances[:4])
    agent.current_target_object_id = str(chosen.parameters.get("object_id") or "")
    agent.current_target_agent_id = str(chosen.parameters.get("target_agent_id") or "")
    target = agent.current_target_object_id or agent.current_target_agent_id
    agent.current_plan = f"{chosen.tool_name} -> {target}" if target else chosen.tool_name
    agent.deliberation_summary = f"Chose {chosen.label}. Candidates: {top}"
    agent.brain_focus = chosen.label
    agent.brain_broadcast = f"{chosen.rationale}. Top affordances: {top}"
    agent.brain_focus_score = chosen.score

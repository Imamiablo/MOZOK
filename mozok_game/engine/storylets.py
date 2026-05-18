from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mozok_game.engine.models import Agent, Commitment, Position, WorldObject
from mozok_game.engine.relationships import apply_relationship_delta
from mozok_game.engine.world_state import WorldState


@dataclass(slots=True)
class StoryletSpec:
    id: str
    title: str
    tags: list[str] = field(default_factory=list)
    requires: dict[str, Any] = field(default_factory=dict)
    effects: list[dict[str, Any]] = field(default_factory=list)
    weight: float = 1.0
    max_occurrences: int = 1
    cooldown_turns: int = 0
    pacing_category: str = "pressure"
    cooldown_group: str = ""
    intensity: str = "minor"

    def can_fire(self, world: WorldState) -> bool:
        if _storylet_count(world, self.id) >= self.max_occurrences:
            return False
        last_turn = _storylet_last_turn(world, self.id)
        if self.cooldown_turns and last_turn >= 0 and world.turn - last_turn < self.cooldown_turns:
            return False
        if self.cooldown_group:
            group_turn = _storylet_group_last_turn(world, self.cooldown_group)
            if self.cooldown_turns and group_turn >= 0 and world.turn - group_turn < self.cooldown_turns:
                return False
        return _requirements_met(world, self.requires)

    def fire(self, world: WorldState) -> bool:
        if not self.can_fire(world):
            return False
        world.scripted_flags.add(self.id)
        world.scripted_flags.add(f"storylet:{self.id}:count:{_storylet_count(world, self.id) + 1}")
        world.scripted_flags.add(f"storylet:{self.id}:turn:{world.turn}")
        if self.cooldown_group:
            world.scripted_flags.add(f"storylet_group:{self.cooldown_group}:turn:{world.turn}")
        if self.pacing_category:
            world.scripted_flags.add(f"storylet_pacing:{self.pacing_category}:turn:{world.turn}")
        for effect in self.effects:
            _apply_effect(world, self, effect)
        return True


def run_storylet_director(world: WorldState) -> None:
    eligible = [storylet for storylet in load_storylet_specs(world) if storylet.can_fire(world)]
    if not eligible:
        return
    chosen = max(eligible, key=lambda storylet: _storylet_score(world, storylet))
    chosen.fire(world)


def load_storylet_specs(world: WorldState | None = None) -> list[StoryletSpec]:
    raw_specs = world.storylet_specs if world and world.storylet_specs else None
    if raw_specs is not None:
        return _specs_from_raw(raw_specs)
    path = Path(__file__).resolve().parents[1] / "data" / "storylets" / "storylets.json"
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return _specs_from_raw(raw)


def _specs_from_raw(raw: Any) -> list[StoryletSpec]:
    specs: list[StoryletSpec] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        specs.append(
            StoryletSpec(
                id=str(item.get("id") or ""),
                title=str(item.get("title") or item.get("id") or "Storylet"),
                tags=list(item.get("tags") or []),
                requires=dict(item.get("requires") or {}),
                effects=[dict(effect) for effect in item.get("effects") or [] if isinstance(effect, dict)],
                weight=float(item.get("weight", 1.0)),
                max_occurrences=max(1, int(item.get("max_occurrences", 1))),
                cooldown_turns=max(0, int(item.get("cooldown_turns", 0))),
                pacing_category=str(item.get("pacing_category") or "pressure"),
                cooldown_group=str(item.get("cooldown_group") or ""),
                intensity=str(item.get("intensity") or "minor"),
            )
        )
    return [spec for spec in specs if spec.id]


def _requirements_met(world: WorldState, requires: dict[str, Any]) -> bool:
    if int(requires.get("turn_gte", -1)) > world.turn:
        return False
    if int(requires.get("turn_lte", 10**9)) < world.turn:
        return False
    for axis, value in dict(requires.get("pressure_gte") or {}).items():
        if world.pressure.get(str(axis), 0.0) < float(value):
            return False
    for axis, value in dict(requires.get("pressure_lte") or {}).items():
        if world.pressure.get(str(axis), 0.0) > float(value):
            return False
    event_type = str(requires.get("trigger_event_type") or "")
    if event_type and not any(event.event_type == event_type for event in world.event_log[-10:]):
        return False
    trigger_tags = {str(tag) for tag in requires.get("trigger_tags") or []}
    if trigger_tags and not any(trigger_tags.intersection(set(event.tags)) for event in world.event_log[-10:]):
        return False
    world_flags = {str(flag) for flag in requires.get("world_flags") or []}
    if world_flags and not world_flags <= world.scripted_flags:
        return False
    absent_flags = {str(flag) for flag in requires.get("absent_world_flags") or []}
    if absent_flags and absent_flags.intersection(world.scripted_flags):
        return False
    pressure_sum = requires.get("pressure_sum_gt")
    if isinstance(pressure_sum, dict):
        axes = [str(axis) for axis in pressure_sum.get("axes") or []]
        if sum(world.pressure.get(axis, 0.0) for axis in axes) <= float(pressure_sum.get("value", 0.0)):
            return False
    if "chaos_gte" in requires and _chaos_level(world) < float(requires.get("chaos_gte", 0.0)):
        return False
    if "chaos_lte" in requires and _chaos_level(world) > float(requires.get("chaos_lte", 1.0)):
        return False
    if not _belief_requirement_met(world, requires.get("requires_agent_belief")):
        return False
    if not _claim_requirement_met(world, requires.get("requires_claim")):
        return False
    if not _object_state_requirement_met(world, requires.get("requires_object_state")):
        return False
    if not _inventory_requirement_met(world, requires.get("requires_inventory_item")):
        return False
    return True


def _storylet_score(world: WorldState, storylet: StoryletSpec) -> float:
    score = max(0.0, storylet.weight) * 100.0
    recent_tags = {tag for event in world.event_log[-8:] for tag in event.tags}
    storylet_tags = set(storylet.tags)
    score += len(storylet_tags & recent_tags) * 9.0
    for tag in storylet_tags:
        score += world.pressure.get(tag, 0.0) * 35.0
    category_turn = _storylet_pacing_last_turn(world, storylet.pacing_category)
    if category_turn >= 0:
        score -= max(0.0, 24.0 - (world.turn - category_turn) * 4.0)
    score += _pacing_score(world, storylet)
    return score


def _pacing_score(world: WorldState, storylet: StoryletSpec) -> float:
    chaos = _chaos_level(world)
    category = storylet.pacing_category
    intensity = storylet.intensity
    recovery_categories = {"recovery", "breather", "opportunity"}
    escalation_categories = {"pressure", "reveal", "complication", "danger"}
    score = 0.0
    if chaos > 0.68:
        if category in recovery_categories:
            score += 56.0
        if category in escalation_categories:
            score -= 46.0
        if intensity in {"major", "reveal"}:
            score -= 20.0
    elif chaos < 0.25:
        if category in escalation_categories:
            score += 16.0
        if category in recovery_categories:
            score -= 18.0
    recent_categories = _recent_storylet_categories(world, turns=8)
    if category in recent_categories:
        score -= 18.0
    if len(recent_categories) >= 2 and category not in recent_categories:
        score += 8.0
    return score


def _chaos_level(world: WorldState) -> float:
    axes = ("danger", "instability", "moral_pressure", "exhaustion", "scarcity")
    return sum(world.pressure.get(axis, 0.0) for axis in axes) / len(axes)


def _recent_storylet_categories(world: WorldState, turns: int) -> set[str]:
    categories: set[str] = set()
    for flag in world.scripted_flags:
        prefix = "storylet_pacing:"
        if not flag.startswith(prefix):
            continue
        rest = flag.removeprefix(prefix)
        if ":turn:" not in rest:
            continue
        category, raw_turn = rest.split(":turn:", 1)
        if raw_turn.isdigit() and world.turn - int(raw_turn) <= turns:
            categories.add(category)
    return categories


def _storylet_count(world: WorldState, storylet_id: str) -> int:
    prefix = f"storylet:{storylet_id}:count:"
    values = [int(flag.removeprefix(prefix)) for flag in world.scripted_flags if flag.startswith(prefix) and flag.removeprefix(prefix).isdigit()]
    return max(values, default=0)


def _storylet_last_turn(world: WorldState, storylet_id: str) -> int:
    prefix = f"storylet:{storylet_id}:turn:"
    values = [int(flag.removeprefix(prefix)) for flag in world.scripted_flags if flag.startswith(prefix) and flag.removeprefix(prefix).isdigit()]
    return max(values, default=-1)


def _storylet_group_last_turn(world: WorldState, group_id: str) -> int:
    prefix = f"storylet_group:{group_id}:turn:"
    values = [int(flag.removeprefix(prefix)) for flag in world.scripted_flags if flag.startswith(prefix) and flag.removeprefix(prefix).isdigit()]
    return max(values, default=-1)


def _storylet_pacing_last_turn(world: WorldState, category: str) -> int:
    if not category:
        return -1
    prefix = f"storylet_pacing:{category}:turn:"
    values = [int(flag.removeprefix(prefix)) for flag in world.scripted_flags if flag.startswith(prefix) and flag.removeprefix(prefix).isdigit()]
    return max(values, default=-1)


def _belief_requirement_met(world: WorldState, raw: Any) -> bool:
    if not raw:
        return True
    specs = raw if isinstance(raw, list) else [raw]
    for spec in specs:
        if not isinstance(spec, dict):
            return False
        if not any(_belief_matches(belief, spec) for belief in world.agent_beliefs[-40:]):
            return False
    return True


def _belief_matches(belief: Any, spec: dict[str, Any]) -> bool:
    if spec.get("agent_id") and belief.agent_id != str(spec["agent_id"]):
        return False
    if spec.get("subject") and belief.subject != str(spec["subject"]):
        return False
    if spec.get("predicate") and str(spec["predicate"]).lower() not in belief.predicate.lower():
        return False
    if spec.get("object") and belief.object != str(spec["object"]):
        return False
    if belief.confidence < float(spec.get("min_confidence", 0.0)):
        return False
    emotional_tags = {str(tag) for tag in spec.get("emotional_tags") or []}
    if emotional_tags and not emotional_tags.intersection(set(belief.emotional_tags)):
        return False
    return True


def _claim_requirement_met(world: WorldState, raw: Any) -> bool:
    if not raw:
        return True
    specs = raw if isinstance(raw, list) else [raw]
    for spec in specs:
        if not isinstance(spec, dict):
            return False
        if not any(_claim_matches(claim, spec) for claim in world.claim_log[-40:]):
            return False
    return True


def _claim_matches(claim: Any, spec: dict[str, Any]) -> bool:
    for key in ("speaker_id", "listener_id", "subject", "predicate", "object", "claim_type", "target_object_id", "truth_status"):
        if spec.get(key) and getattr(claim, key) != str(spec[key]):
            return False
    if claim.confidence < float(spec.get("min_confidence", 0.0)):
        return False
    return True


def _object_state_requirement_met(world: WorldState, raw: Any) -> bool:
    if not raw:
        return True
    specs = raw if isinstance(raw, list) else [raw]
    for spec in specs:
        if not isinstance(spec, dict):
            return False
        obj = _select_object(world, spec.get("select_object") or spec)
        if not obj:
            return False
        for key, expected in dict(spec.get("state") or {}).items():
            if obj.state.get(str(key)) != expected:
                return False
        for key, minimum in dict(spec.get("state_min") or {}).items():
            if float(obj.state.get(str(key), 0.0)) < float(minimum):
                return False
    return True


def _inventory_requirement_met(world: WorldState, raw: Any) -> bool:
    if not raw:
        return True
    specs = raw if isinstance(raw, list) else [raw]
    for spec in specs:
        if isinstance(spec, str):
            item_id = spec
            if item_id not in world.player.inventory and not any(item_id in agent.inventory for agent in world.agents.values()):
                return False
            continue
        if not isinstance(spec, dict):
            return False
        item_id = str(spec.get("item_id") or spec.get("id") or "")
        actor_id = str(spec.get("actor_id") or spec.get("agent_id") or "")
        if not item_id:
            return False
        if actor_id == "player":
            if item_id not in world.player.inventory:
                return False
        elif actor_id:
            agent = world.agents.get(actor_id)
            if not agent or item_id not in agent.inventory:
                return False
        elif item_id not in world.player.inventory and not any(item_id in agent.inventory for agent in world.agents.values()):
            return False
    return True


def _apply_effect(world: WorldState, storylet: StoryletSpec, effect: dict[str, Any]) -> None:
    effect_type = str(effect.get("type") or "")
    if effect_type == "log":
        world.log(
            str(effect.get("event_type") or storylet.id),
            str(effect.get("message") or storylet.title),
            source=str(effect.get("source") or "storylet"),
            salience=float(effect.get("salience", 7)),
            tags=list(effect.get("tags") or storylet.tags),
            metadata={"storylet_id": storylet.id, "pressure": dict(world.pressure)},
        )
        return
    if effect_type == "agent_need_delta_if_unprotected":
        _apply_need_delta_if_unprotected(world, effect)
        return
    if effect_type == "agent_need_delta":
        agent = _select_agent(world, effect.get("select_agent"))
        if agent:
            _apply_need_delta(agent, dict(effect.get("delta") or {}))
        return
    if effect_type == "agent_social_delta":
        agent = _select_agent(world, effect.get("select_agent"))
        if agent:
            for key, amount in dict(effect.get("delta") or {}).items():
                if hasattr(agent.social_to_player, str(key)):
                    setattr(agent.social_to_player, str(key), float(getattr(agent.social_to_player, str(key))) + float(amount))
            agent.social_to_player.clamp()
        return
    if effect_type == "agent_relationship_delta":
        agent = _select_agent(world, effect.get("select_agent"))
        target = str(effect.get("target") or effect.get("target_agent_id") or "player")
        if agent:
            apply_relationship_delta(agent, target, {str(key): float(amount) for key, amount in dict(effect.get("delta") or {}).items()})
            world.log(
                "relationship_delta",
                f"{agent.name}'s relationship pressure changed toward {target}.",
                source="storylet",
                salience=4,
                tags=["social", "relationship"],
                metadata={"storylet_id": storylet.id, "agent_id": agent.id, "target": target, "delta": dict(effect.get("delta") or {})},
            )
        return
    if effect_type == "all_agent_need_delta":
        for agent in world.agents.values():
            _apply_need_delta(agent, dict(effect.get("delta") or {}))
        return
    if effect_type == "flash":
        agent = _select_agent(world, effect.get("select_agent"))
        if agent:
            world.flash(
                agent.id,
                str(effect.get("title") or storylet.title),
                _format_template(str(effect.get("content") or effect.get("content_template") or ""), {"agent": agent.name}),
                kind=str(effect.get("kind") or "memory"),
                intensity=float(effect.get("intensity", 0.7)),
            )
        return
    if effect_type == "flash_all_agents":
        for agent in world.agents.values():
            world.flash(
                agent.id,
                str(effect.get("title") or storylet.title),
                _format_template(str(effect.get("content") or effect.get("content_template") or ""), {"agent": agent.name}),
                kind=str(effect.get("kind") or "memory"),
                intensity=float(effect.get("intensity", 0.7)),
            )
        return
    if effect_type == "set_world_flag":
        flag = str(effect.get("flag") or storylet.id)
        if flag:
            world.scripted_flags.add(flag)
        return
    if effect_type == "set_object_state":
        obj = _select_object(world, effect.get("select_object"))
        if obj:
            obj.state.update(dict(effect.get("state") or {}))
        return
    if effect_type == "set_location_access":
        obj = _select_object(world, effect.get("select_object") or effect.get("location") or effect.get("target"))
        if obj:
            obj.state["accessible"] = bool(effect.get("accessible", True))
            if effect.get("state"):
                obj.state.update(dict(effect.get("state") or {}))
        return
    if effect_type == "spawn_object":
        spec = effect.get("object")
        if isinstance(spec, dict) and spec.get("id") and spec.get("position"):
            world.objects[str(spec["id"])] = WorldObject(
                id=str(spec["id"]),
                name=str(spec.get("name") or spec["id"]),
                kind=str(spec.get("kind") or spec["id"]),
                position=Position(int(spec["position"][0]), int(spec["position"][1])),
                interactions=list(spec.get("interactions") or []),
                tags=list(spec.get("tags") or []),
                aliases=list(spec.get("aliases") or []),
                object_type=str(spec.get("object_type") or "object"),
                sprite=str(spec.get("sprite") or ""),
                properties=dict(spec.get("properties") or {}),
                render=dict(spec.get("render") or {}),
                interaction_defs=dict(spec.get("interaction_defs") or {}),
                state=dict(spec.get("state") or {}),
                capability_accepts=list(spec.get("capability_accepts") or []),
                capability_effects=dict(spec.get("capability_effects") or {}),
            )
        return
    if effect_type == "claim":
        world.claim(
            speaker_id=str(effect.get("speaker_id") or "director"),
            listener_id=str(effect.get("listener_id") or "group"),
            text=str(effect.get("text") or ""),
            truth_status=str(effect.get("truth_status") or "unverified"),
            confidence=float(effect.get("confidence", 0.5)),
            subject=str(effect.get("subject") or ""),
            predicate=str(effect.get("predicate") or ""),
            object=str(effect.get("object") or ""),
            claim_type=str(effect.get("claim_type") or "world_fact"),
            target_object_id=str(effect.get("target_object_id") or ""),
        )
        return
    if effect_type == "create_goal":
        agent = _select_agent(world, effect.get("select_agent"))
        goal = str(effect.get("goal") or effect.get("current_goal") or "")
        if agent and goal:
            agent.current_goal = goal
            agent.brain_focus = f"New goal: {goal}"
        return
    if effect_type == "create_commitment":
        agent = _select_agent(world, effect.get("select_agent"))
        if agent:
            commitment = Commitment(
                id=str(effect.get("id") or f"storylet_{storylet.id}_{agent.id}_{world.turn}"),
                agent_id=agent.id,
                issuer_id=str(effect.get("issuer_id") or "director"),
                type=str(effect.get("commitment_type") or effect.get("commitment", "promise")),
                status=str(effect.get("status") or "active"),
                priority=float(effect.get("priority", 55.0)),
                target_object_id=str(effect.get("target_object_id") or ""),
                target_agent_id=str(effect.get("target_agent_id") or ""),
                goal=str(effect.get("goal") or storylet.title),
                constraints=dict(effect.get("constraints") or {}),
                expiry_turns=int(effect.get("expiry_turns", 0) or 0),
                started_turn=world.turn,
                accepted_because=str(effect.get("accepted_because") or "storylet"),
                betrayal_if_broken=bool(effect.get("betrayal_if_broken", False)),
            )
            agent.active_commitment = commitment
            from mozok_game.engine.commitments import sync_legacy_commitment_cache

            sync_legacy_commitment_cache(agent)
        return
    if effect_type == "schedule_followup_storylet":
        followup_id = str(effect.get("storylet_id") or effect.get("id") or "")
        if followup_id:
            world.scripted_flags.add(f"storylet_followup:{followup_id}:available_turn:{world.turn + int(effect.get('delay_turns', 1) or 1)}")
        return
    if effect_type == "choice_offer":
        world.log(
            "storylet_choice_offer",
            str(effect.get("message") or effect.get("title") or storylet.title),
            source="storylet",
            salience=float(effect.get("salience", 7)),
            tags=list(effect.get("tags") or ["choice", *storylet.tags]),
            metadata={"storylet_id": storylet.id, "choices": list(effect.get("choices") or [])},
        )


def _apply_need_delta_if_unprotected(world: WorldState, effect: dict[str, Any]) -> None:
    protected_kinds = [str(kind) for kind in effect.get("protected_near_kinds") or []]
    protected_tags = {str(tag) for tag in effect.get("protected_near_tags") or []}
    protected_distance = int(effect.get("protected_distance", 2))
    protected_delta = dict(effect.get("protected_delta") or {})
    unprotected_delta = dict(effect.get("unprotected_delta") or {})
    flash = effect.get("unprotected_flash") if isinstance(effect.get("unprotected_flash"), dict) else {}
    protected_objects = [
        obj
        for obj in world.objects.values()
        if obj.kind in protected_kinds or protected_tags.intersection(set(obj.tags))
    ]
    for agent in world.agents.values():
        protected = any(agent.position.manhattan(obj.position) <= protected_distance for obj in protected_objects)
        delta = protected_delta if protected else unprotected_delta
        for need_name, amount in delta.items():
            if hasattr(agent.needs, str(need_name)):
                setattr(agent.needs, str(need_name), float(getattr(agent.needs, str(need_name))) + float(amount))
        agent.needs.clamp()
        if not protected and flash:
            world.flash(
                agent.id,
                str(flash.get("title") or "Pressure"),
                str(flash.get("content") or "The situation got worse."),
                kind=str(flash.get("kind") or "body"),
                intensity=float(flash.get("intensity", 0.7)),
            )


def _select_agent(world: WorldState, selector: Any) -> Agent | None:
    if isinstance(selector, str) and selector in world.agents:
        return world.agents[selector]
    spec = selector if isinstance(selector, dict) else {}
    if spec.get("id") in world.agents:
        return world.agents[str(spec["id"])]
    agents = [agent for agent in world.agents.values() if agent.alive]
    if not agents:
        return None
    traits = dict(spec.get("prefer_traits") or {})
    needs = dict(spec.get("prefer_needs") or {})
    return max(
        agents,
        key=lambda agent: sum(agent.traits.get(str(key), 0.0) * float(value) for key, value in traits.items())
        + sum(float(getattr(agent.needs, str(key), 0.0)) * float(value) for key, value in needs.items()),
    )


def _select_object(world: WorldState, selector: Any) -> WorldObject | None:
    if isinstance(selector, str):
        return world.objects.get(selector)
    spec = selector if isinstance(selector, dict) else {}
    if spec.get("id") in world.objects:
        return world.objects[str(spec["id"])]
    tags = {str(tag) for tag in spec.get("tags") or []}
    if tags:
        for obj in world.objects.values():
            if tags <= set(obj.tags):
                return obj
    return None


def _apply_need_delta(agent: Agent, delta: dict[str, Any]) -> None:
    for need_name, amount in delta.items():
        if hasattr(agent.needs, str(need_name)):
            setattr(agent.needs, str(need_name), float(getattr(agent.needs, str(need_name))) + float(amount))
    agent.needs.clamp()


def _format_template(template: str, context: dict[str, str]) -> str:
    result = template
    for key, value in context.items():
        result = result.replace("{" + key + "}", value)
    return result

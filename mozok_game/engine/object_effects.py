from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mozok_game.engine.inventory import add_item, actor_name, item_interactions, item_name, remove_item
from mozok_game.engine.models import WorldObject
from mozok_game.engine.world_state import WorldState


@dataclass(slots=True)
class InteractionResult:
    ok: bool
    message: str
    event_type: str = "object_interaction"
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def execute_object_interaction(world: WorldState, actor_id: str, obj: WorldObject, interaction_id: str = "", reason: str = "") -> InteractionResult:
    interaction_id = interaction_id or choose_default_interaction(world, actor_id, obj)
    spec = interaction_spec(obj, interaction_id)
    if not spec:
        result = InteractionResult(False, f"{obj.name} has no usable {interaction_id or 'default'} interaction.", tags=["object", "invalid"])
        _log_interaction(world, actor_id, obj, interaction_id, result, reason)
        return result
    blocked = _blocked_reason(obj, spec)
    if blocked:
        result = InteractionResult(False, _format_text(str(spec.get("blocked_message") or blocked), world, actor_id, obj), tags=list(spec.get("tags") or obj.tags))
        _log_interaction(world, actor_id, obj, interaction_id, result, reason, rejected=True)
        return result
    required_item = spec.get("requires_inventory_item") or spec.get("requires_item")
    if isinstance(required_item, dict):
        item_id = str(required_item.get("item_id") or "")
        if item_id and not _actor_has_item(world, actor_id, item_id):
            result = InteractionResult(False, str(required_item.get("failure_message") or f"{actor_name(world, actor_id)} needs {item_name(item_id)} to use {obj.name}."), tags=["object", "missing_item", *list(spec.get("tags") or [])])
            _log_interaction(world, actor_id, obj, interaction_id, result, reason, rejected=True)
            return result
        primitive = str(required_item.get("primitive") or "")
        if primitive:
            from mozok_game.engine.capabilities import execute_item_action

            return _from_primitive_result(execute_item_action(world, actor_id, item_id, obj.id, primitive, reason or interaction_id))

    _apply_effect_dict(world, actor_id, obj, spec)
    for moment_id in _as_list(spec.get("trigger_moment")):
        if moment_id:
            from mozok_game.engine.director import trigger_scripted_moment

            trigger_scripted_moment(world, str(moment_id))
    message = _format_text(str(spec.get("message") or "{actor} uses {target}."), world, actor_id, obj)
    result = InteractionResult(
        True,
        message,
        str(spec.get("event_type_player" if actor_id == "player" else "event_type_agent") or spec.get("event_type") or f"{'player' if actor_id == 'player' else 'agent'}_{interaction_id}"),
        list(spec.get("tags") or ["object", interaction_id, *obj.tags[:2]]),
        {"actor_id": actor_id, "target_id": obj.id, "item_id": _first_granted_item(spec), "interaction_id": interaction_id, "reason": reason, "data_driven": True},
    )
    _log_interaction(world, actor_id, obj, interaction_id, result, reason)
    return result


def execute_inventory_interaction(world: WorldState, actor_id: str, item_id: str, interaction_id: str = "use", reason: str = "") -> InteractionResult:
    specs = item_interactions(item_id)
    spec = specs.get(interaction_id) if isinstance(specs, dict) else None
    if not isinstance(spec, dict):
        from mozok_game.engine.capabilities import execute_item_action

        return _from_primitive_result(execute_item_action(world, actor_id, item_id, "", "consume", reason or interaction_id))
    virtual = WorldObject(
        id=item_id,
        name=item_name(item_id),
        kind=item_id,
        position=world.player.position.copy(),
        interactions=[interaction_id],
        tags=list(spec.get("tags") or []),
        interaction_defs={interaction_id: spec},
    )
    _apply_effect_dict(world, actor_id, virtual, spec, item_id=item_id)
    if spec.get("consume_item", True):
        remove_item(world, actor_id, item_id)
    message = _format_text(str(spec.get("message") or "{actor} uses {target}."), world, actor_id, virtual, item_id=item_id)
    result = InteractionResult(
        True,
        message,
        str(spec.get("event_type") or "inventory_interaction"),
        list(spec.get("tags") or ["item", interaction_id]),
        {"actor_id": actor_id, "item_id": item_id, "interaction_id": interaction_id, "reason": reason, "data_driven": True},
    )
    world.log(result.event_type, result.message, source=actor_id, salience=float(spec.get("salience", 6)), tags=result.tags, metadata=result.metadata, actor_id=actor_id, item_id=item_id)
    return result


def choose_default_interaction(world: WorldState, actor_id: str, obj: WorldObject) -> str:
    available = [interaction for interaction in obj.interactions if interaction_spec(obj, interaction)]
    if not available:
        return obj.interactions[0] if obj.interactions else "inspect"
    if obj.state.get("taken"):
        return "inspect" if "inspect" in available else available[0]
    actor = world.agents.get(actor_id)
    urgent = actor.needs.most_urgent[0] if actor else ""
    preferences = {
        "hunger": ("take_food", "pick", "eat", "consume", "take", "inspect"),
        "thirst": ("drink", "take", "inspect"),
        "fatigue": ("rest", "sleep", "warm", "take", "inspect"),
        "stress": ("warm", "rest", "light", "inspect", "take"),
        "curiosity": ("inspect", "read", "open", "take"),
    }.get(urgent, ())
    if actor_id == "player":
        preferences = ("take", "take_food", "pick", "drink", "open", "read", "light", "rest", "inspect")
    for candidate in preferences:
        if candidate in available:
            return candidate
    if "take" in available:
        return "take"
    if "inspect" in available:
        return "inspect"
    return available[0]


def interaction_spec(obj: WorldObject, interaction_id: str) -> dict[str, Any]:
    spec = obj.interaction_defs.get(interaction_id)
    if isinstance(spec, dict):
        return spec
    if interaction_id:
        return {"label": interaction_id.replace("_", " ").title(), "primitive": interaction_id, "message": "{actor} inspects {target}.", "tags": ["object", interaction_id, *obj.tags[:2]]}
    return {}


def _apply_effect_dict(world: WorldState, actor_id: str, obj: WorldObject, spec: dict[str, Any], item_id: str = "") -> None:
    for key, value in dict(spec.get("set_state") or spec.get("target_state") or {}).items():
        obj.state[str(key)] = _format_value(value, world, actor_id, obj, item_id)
    for key, delta in dict(spec.get("state_delta") or {}).items():
        obj.state[str(key)] = float(obj.state.get(str(key), 0)) + float(delta)
        if obj.state[str(key)].is_integer():
            obj.state[str(key)] = int(obj.state[str(key)])
    for granted in _as_list(spec.get("grants_item") or spec.get("grant_item")):
        granted_id = str(_format_value(granted, world, actor_id, obj, item_id))
        if granted_id:
            add_item(world, actor_id, granted_id)
    for grant in _as_list(spec.get("add_items")):
        if isinstance(grant, dict):
            recipient = actor_id if grant.get("actor") in {"self", "actor", None} else str(grant.get("actor"))
            granted_id = str(_format_value(grant.get("item_id", ""), world, actor_id, obj, item_id))
            if granted_id:
                add_item(world, recipient, granted_id)
    _apply_actor_delta(world, actor_id, dict(spec.get("actor_need_delta") or {}))
    _apply_actor_health_delta(world, actor_id, float(spec.get("actor_health_delta", 0.0) or 0.0))
    _apply_social_delta(world, actor_id, dict(spec.get("actor_social_delta") or {}))
    _apply_all_agent_delta(world, dict(spec.get("all_agent_need_delta") or {}))
    if isinstance(spec.get("nearby_agent_need_delta"), dict):
        nearby = dict(spec["nearby_agent_need_delta"])
        _apply_nearby_agent_delta(world, obj, int(nearby.get("distance", 3)), dict(nearby.get("delta") or {}))
    _apply_pressure_delta(world, dict(spec.get("pressure_delta") or {}))
    for flag in _as_list(spec.get("remove_status_flags")):
        agent = world.agents.get(actor_id)
        if agent and str(flag) in agent.status_flags:
            agent.status_flags.remove(str(flag))
    for flag in _as_list(spec.get("add_status_flags")):
        agent = world.agents.get(actor_id)
        if agent and str(flag) not in agent.status_flags:
            agent.status_flags.append(str(flag))
    claim = spec.get("claim")
    if isinstance(claim, dict):
        world.claim(
            speaker_id=str(_format_value(claim.get("speaker_id", actor_id), world, actor_id, obj, item_id)),
            listener_id=str(_format_value(claim.get("listener_id", "group"), world, actor_id, obj, item_id)),
            text=str(_format_value(claim.get("text", ""), world, actor_id, obj, item_id)),
            truth_status=str(claim.get("truth_status", "verified")),
            confidence=float(claim.get("confidence", 0.8)),
            object=str(_format_value(claim.get("object", obj.kind), world, actor_id, obj, item_id)),
            claim_type=str(claim.get("claim_type", "evidence")),
            target_object_id=str(_format_value(claim.get("target_object_id", obj.id), world, actor_id, obj, item_id)),
        )
    flash = spec.get("flash_best_agent")
    if isinstance(flash, dict):
        _flash_best_agent(world, flash)


def _blocked_reason(obj: WorldObject, spec: dict[str, Any]) -> str:
    for key, value in dict(spec.get("blocked_if_state") or {}).items():
        if obj.state.get(str(key)) == value:
            return f"{obj.name} cannot be used that way right now."
    for key, minimum in dict(spec.get("requires_state_min") or {}).items():
        if float(obj.state.get(str(key), 0)) < float(minimum):
            return f"{obj.name} does not have enough {key}."
    return ""


def _log_interaction(world: WorldState, actor_id: str, obj: WorldObject, interaction_id: str, result: InteractionResult, reason: str, rejected: bool = False) -> None:
    world.log(
        "object_interaction_rejected" if rejected or not result.ok else result.event_type,
        result.message,
        source=actor_id,
        salience=4 if rejected or not result.ok else float(result.metadata.get("salience", 6) or 6),
        tags=(["rejected"] if rejected or not result.ok else []) + result.tags,
        metadata={**result.metadata, "actor_id": actor_id, "target_id": obj.id, "interaction_id": interaction_id, "reason": reason},
        actor_id=actor_id,
        target_id=obj.id,
        item_id=str(result.metadata.get("item_id") or ""),
        visibility="witnessed",
    )


def _actor_has_item(world: WorldState, actor_id: str, item_id: str) -> bool:
    if actor_id == "player":
        return item_id in world.player.inventory
    agent = world.agents.get(actor_id)
    return bool(agent and item_id in agent.inventory)


def _apply_actor_delta(world: WorldState, actor_id: str, deltas: dict[str, Any]) -> None:
    if actor_id == "player":
        for key, delta in deltas.items():
            if hasattr(world.player, str(key)):
                setattr(world.player, str(key), max(0.0, float(getattr(world.player, str(key))) + float(delta)))
        return
    agent = world.agents.get(actor_id)
    if not agent:
        return
    for key, delta in deltas.items():
        if hasattr(agent.needs, str(key)):
            setattr(agent.needs, str(key), float(getattr(agent.needs, str(key))) + float(delta))
    agent.needs.clamp()


def _apply_actor_health_delta(world: WorldState, actor_id: str, delta: float) -> None:
    if not delta:
        return
    if actor_id == "player":
        world.player.health = max(1.0, min(100.0, world.player.health + delta))
        return
    agent = world.agents.get(actor_id)
    if agent:
        agent.health = max(1.0, min(100.0, agent.health + delta))


def _apply_social_delta(world: WorldState, actor_id: str, deltas: dict[str, Any]) -> None:
    agent = world.agents.get(actor_id)
    if not agent:
        return
    for key, delta in deltas.items():
        if hasattr(agent.social_to_player, str(key)):
            setattr(agent.social_to_player, str(key), float(getattr(agent.social_to_player, str(key))) + float(delta))
    agent.social_to_player.clamp()


def _apply_all_agent_delta(world: WorldState, deltas: dict[str, Any]) -> None:
    for agent in world.agents.values():
        for key, delta in deltas.items():
            if hasattr(agent.needs, str(key)):
                setattr(agent.needs, str(key), float(getattr(agent.needs, str(key))) + float(delta))
        agent.needs.clamp()


def _apply_nearby_agent_delta(world: WorldState, obj: WorldObject, distance: int, deltas: dict[str, Any]) -> None:
    for agent in world.agents.values():
        if agent.position.manhattan(obj.position) > distance:
            continue
        for key, delta in deltas.items():
            if hasattr(agent.needs, str(key)):
                setattr(agent.needs, str(key), float(getattr(agent.needs, str(key))) + float(delta))
        agent.needs.clamp()


def _apply_pressure_delta(world: WorldState, deltas: dict[str, Any]) -> None:
    for key, delta in deltas.items():
        world.pressure[str(key)] = max(0.0, min(1.0, float(world.pressure.get(str(key), 0.0)) + float(delta)))


def _flash_best_agent(world: WorldState, spec: dict[str, Any]) -> None:
    trait = str(spec.get("trait") or "curiosity")
    agents = [agent for agent in world.agents.values() if agent.alive]
    if not agents:
        return
    chosen = max(agents, key=lambda agent: agent.traits.get(trait, 0.0))
    world.flash(
        chosen.id,
        str(spec.get("title") or "Object insight"),
        str(spec.get("content") or "Something about the object mattered."),
        kind=str(spec.get("kind") or "belief"),
        intensity=float(spec.get("intensity", 0.7)),
    )


def _format_text(template: str, world: WorldState, actor_id: str, obj: WorldObject, item_id: str = "") -> str:
    context: dict[str, Any] = {
        "actor": actor_name(world, actor_id),
        "actor_id": actor_id,
        "target": obj.name,
        "target_id": obj.id,
        "target_kind": obj.kind,
        "item": item_name(item_id) if item_id else "",
        "item_id": item_id,
    }
    for key, value in obj.state.items():
        context[f"state_{key}"] = value
    return template.format(**context)


def _format_value(value: Any, world: WorldState, actor_id: str, obj: WorldObject, item_id: str = "") -> Any:
    if isinstance(value, str):
        return _format_text(value, world, actor_id, obj, item_id)
    return value


def _from_primitive_result(result: Any) -> InteractionResult:
    return InteractionResult(bool(result.ok), str(result.message), str(result.event_type), list(result.tags), dict(result.metadata))


def _first_granted_item(spec: dict[str, Any]) -> str:
    granted = spec.get("grants_item") or spec.get("grant_item")
    if isinstance(granted, str):
        return granted
    if isinstance(granted, list) and granted:
        return str(granted[0])
    for item in _as_list(spec.get("add_items")):
        if isinstance(item, dict) and item.get("item_id"):
            return str(item["item_id"])
    return ""


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]

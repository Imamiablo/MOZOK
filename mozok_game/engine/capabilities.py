from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mozok_game.engine.inventory import add_item, actor_name, has_item, item_capabilities, item_name, item_properties, item_tags, remove_item
from mozok_game.engine.models import WorldObject
from mozok_game.engine.world_state import WorldState


GENERIC_PRIMITIVES = {
    "cut",
    "pry",
    "tie",
    "bind",
    "burn",
    "carry",
    "drag",
    "consume",
    "inspect",
    "repair",
    "threaten",
    "carve",
    "prepare_food",
    "trade",
    "give",
    "throw",
    "block",
    "anchor",
    "climb",
    "set_trap",
    "test",
    "combine",
    "craft_simple",
    "treat",
    "reveal",
}


@dataclass(slots=True)
class PrimitiveResult:
    ok: bool
    message: str
    event_type: str = "item_action"
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def target_primitives(obj: WorldObject) -> set[str]:
    primitives = set(obj.capability_accepts)
    for interaction in obj.interactions:
        if interaction in GENERIC_PRIMITIVES:
            primitives.add(interaction)
        if interaction == "open":
            primitives.update({"pry", "inspect"})
        if interaction == "enter":
            primitives.update({"inspect", "anchor", "climb"})
        if interaction == "read":
            primitives.update({"inspect", "reveal"})
        if interaction == "rest":
            primitives.update({"inspect"})
        if interaction == "drink":
            primitives.update({"inspect", "test"})
    if "locked" in obj.tags:
        primitives.add("pry")
    if "tool_required" in obj.tags:
        primitives.update({"pry", "cut"})
    if "mystery" in obj.tags:
        primitives.update({"inspect", "test"})
    if "safety" in obj.tags:
        primitives.update({"inspect", "anchor", "tie"})
    if "toxic" in obj.tags or "unknown" in obj.tags:
        primitives.update({"inspect", "test"})
    if "evidence" in obj.tags or "lore" in obj.tags:
        primitives.update({"inspect", "reveal"})
    if "repair" in obj.interactions or "broken" in obj.tags:
        primitives.update({"inspect", "repair", "pry"})
    return primitives


def validate_item_action(world: WorldState, actor_id: str, item_id: str, target_id: str, primitive: str) -> PrimitiveResult:
    primitive = _clean_primitive(primitive)
    if primitive not in GENERIC_PRIMITIVES:
        return PrimitiveResult(False, f"Unknown primitive: {primitive or 'none'}.", tags=["item", "invalid"])
    if primitive not in item_capabilities(item_id):
        return PrimitiveResult(False, f"{item_name(item_id)} cannot {primitive}.", tags=["item", "invalid"])
    if not has_item(world, actor_id, item_id):
        return PrimitiveResult(False, f"{actor_name(world, actor_id)} does not have {item_name(item_id)}.", tags=["item", "missing"])

    if primitive in {"consume", "threaten", "give", "trade"} and not target_id:
        return PrimitiveResult(True, "Inventory-only primitive is valid.", tags=["item"])

    obj = world.objects.get(target_id)
    if not obj:
        return PrimitiveResult(False, f"Target object is not known: {target_id or 'none'}.", tags=["item", "invalid"])
    if primitive not in target_primitives(obj):
        return PrimitiveResult(False, f"{obj.name} does not support {primitive}.", tags=["item", "invalid"])
    if not _actor_near_object(world, actor_id, obj):
        return PrimitiveResult(False, f"{actor_name(world, actor_id)} is not close enough to {obj.name}.", tags=["item", "distance"])
    return PrimitiveResult(True, f"{item_name(item_id)} can {primitive} {obj.name}.", tags=["item"])


def execute_item_action(world: WorldState, actor_id: str, item_id: str, target_id: str = "", primitive: str = "inspect", reason: str = "") -> PrimitiveResult:
    primitive = _clean_primitive(primitive)
    valid = validate_item_action(world, actor_id, item_id, target_id, primitive)
    if not valid.ok:
        world.log(
            "item_action_rejected",
            valid.message,
            source=actor_id,
            salience=4,
            tags=["item", "rejected", *valid.tags],
            metadata={"actor_id": actor_id, "item_id": item_id, "target_id": target_id, "primitive": primitive, "reason": reason},
        )
        return valid

    obj = world.objects.get(target_id) if target_id else None
    if obj and primitive in obj.capability_effects:
        return _execute_data_effect(world, actor_id, item_id, obj, primitive, obj.capability_effects[primitive], reason)
    if primitive == "inspect":
        return _inspect_target(world, actor_id, item_id, obj, reason)
    if primitive == "consume":
        return _consume_item(world, actor_id, item_id, reason)
    result = PrimitiveResult(
        True,
        f"{actor_name(world, actor_id)} uses {item_name(item_id)} to {primitive} {obj.name if obj else 'the situation'}.",
        event_type="item_action",
        tags=["item", "capability", primitive],
        metadata={"actor_id": actor_id, "item_id": item_id, "target_id": target_id, "primitive": primitive, "reason": reason},
    )
    world.log(result.event_type, result.message, source=actor_id, salience=6, tags=result.tags, metadata=result.metadata)
    return result


def _execute_data_effect(world: WorldState, actor_id: str, item_id: str, obj: WorldObject, primitive: str, effect: Any, reason: str) -> PrimitiveResult:
    if not isinstance(effect, dict):
        return PrimitiveResult(False, f"{obj.name} has an invalid effect for {primitive}.", tags=["item", "invalid"])
    if effect.get("requires_closed") and obj.state.get("open"):
        result = PrimitiveResult(True, f"{actor_name(world, actor_id)} checks {obj.name}; it is already open.", "item_action", ["item", "inspect"])
        world.log(result.event_type, result.message, source=actor_id, tags=result.tags, actor_id=actor_id, target_id=obj.id, item_id=item_id)
        return result

    for key, value in dict(effect.get("target_state") or {}).items():
        obj.state[str(key)] = _format_effect_value(value, world, actor_id, item_id, obj)

    for grant in _as_list(effect.get("add_items")):
        if not isinstance(grant, dict):
            continue
        recipient = actor_id if grant.get("actor") in {"self", "actor", None} else str(grant.get("actor"))
        granted_item = str(grant.get("item_id") or "")
        if granted_item:
            add_item(world, recipient, granted_item)

    if effect.get("consume_item"):
        remove_item(world, actor_id, item_id)

    agent = world.agents.get(actor_id)
    if agent:
        for need_name, delta in dict(effect.get("agent_need_delta") or {}).items():
            if hasattr(agent.needs, str(need_name)):
                setattr(agent.needs, str(need_name), float(getattr(agent.needs, str(need_name))) + float(delta))
        agent.needs.clamp()
        for social_name, delta in dict(effect.get("agent_social_delta") or {}).items():
            if hasattr(agent.social_to_player, str(social_name)):
                setattr(agent.social_to_player, str(social_name), float(getattr(agent.social_to_player, str(social_name))) + float(delta))
        agent.social_to_player.clamp()

    claim = effect.get("claim")
    if isinstance(claim, dict):
        world.claim(
            speaker_id=str(_format_effect_value(claim.get("speaker_id", actor_id), world, actor_id, item_id, obj)),
            listener_id=str(_format_effect_value(claim.get("listener_id", "group"), world, actor_id, item_id, obj)),
            text=str(_format_effect_value(claim.get("text", ""), world, actor_id, item_id, obj)),
            truth_status=str(claim.get("truth_status", "verified")),
            confidence=float(claim.get("confidence", 0.8)),
            object=str(_format_effect_value(claim.get("object", obj.kind), world, actor_id, item_id, obj)),
            claim_type=str(claim.get("claim_type", "evidence")),
            target_object_id=str(_format_effect_value(claim.get("target_object_id", obj.id), world, actor_id, item_id, obj)),
        )

    flash = effect.get("flash")
    if isinstance(flash, dict) and actor_id in world.agents:
        world.flash(
            actor_id,
            str(flash.get("title") or "Item effect"),
            str(flash.get("content") or "The item changed the local plan."),
            kind=str(flash.get("kind") or "decision"),
            intensity=float(flash.get("intensity", 0.7)),
        )

    message = str(effect.get("message") or "{actor} uses {item} on {target}.")
    message = _format_effect_text(message, world, actor_id, item_id, obj)
    result = PrimitiveResult(
        True,
        message,
        str(effect.get("event_type") or "item_action"),
        list(effect.get("tags") or ["item", "capability", primitive]),
        {"actor_id": actor_id, "item_id": item_id, "target_id": obj.id, "primitive": primitive, "reason": reason, "data_driven": True},
    )
    world.log(
        result.event_type,
        result.message,
        source=actor_id,
        salience=float(effect.get("salience", 6)),
        tags=result.tags,
        metadata=result.metadata,
        actor_id=actor_id,
        target_id=obj.id,
        item_id=item_id,
    )
    return result


def _inspect_target(world: WorldState, actor_id: str, item_id: str, obj: WorldObject | None, reason: str) -> PrimitiveResult:
    if not obj:
        return PrimitiveResult(False, "There is no target to inspect.", tags=["item", "invalid"])
    message = f"{actor_name(world, actor_id)} inspects {obj.name} with {item_name(item_id)}."
    tags = ["item", "inspect", "capability", *[tag for tag in obj.tags if tag in {"mystery", "danger", "evidence", "food", "tool", "safety"}]]
    result = PrimitiveResult(
        True,
        message,
        "item_action_inspect",
        tags,
        {"actor_id": actor_id, "item_id": item_id, "target_id": obj.id, "primitive": "inspect", "reason": reason},
    )
    world.log(result.event_type, result.message, source=actor_id, salience=7, tags=result.tags, metadata=result.metadata)
    return result


def _consume_item(world: WorldState, actor_id: str, item_id: str, reason: str) -> PrimitiveResult:
    tags = item_tags(item_id)
    props = item_properties(item_id)
    if "consume" not in item_capabilities(item_id) and "consumable" not in tags:
        message = f"{actor_name(world, actor_id)} cannot safely consume {item_name(item_id)}."
        result = PrimitiveResult(False, message, tags=["item", "invalid"])
        world.log("item_action_rejected", message, source=actor_id, tags=result.tags)
        return result
    remove_item(world, actor_id, item_id)
    nutrition = max(0.0, min(1.0, float(props.get("nutrition", 0.25))))
    danger = max(0.0, min(1.0, float(props.get("danger", 0.0))))
    hunger_delta = 74.0 * nutrition
    agent = world.agents.get(actor_id)
    if agent:
        agent.needs.hunger = max(0.0, agent.needs.hunger - hunger_delta)
        if danger:
            agent.health = max(1.0, agent.health - 14.0 * danger)
            agent.needs.stress += 12.0 * danger
        agent.needs.clamp()
    else:
        world.player.hunger = max(0.0, world.player.hunger - hunger_delta)
        if danger:
            world.player.health = max(1.0, world.player.health - 14.0 * danger)
    danger_line = " and immediately pays for the risk" if danger >= 0.45 else ""
    message = f"{actor_name(world, actor_id)} consumes {item_name(item_id)}{danger_line}."
    event_tags = ["item", "capability", "consume", *sorted(tags & {"food", "toxic", "medical", "danger"})]
    if danger:
        event_tags.append("danger")
    result = PrimitiveResult(
        True,
        message,
        "item_action_consume",
        event_tags,
        {"actor_id": actor_id, "item_id": item_id, "primitive": "consume", "reason": reason, "nutrition": nutrition, "danger": danger},
    )
    world.log(result.event_type, result.message, source=actor_id, salience=7, tags=result.tags, metadata=result.metadata)
    return result


def _actor_near_object(world: WorldState, actor_id: str, obj: WorldObject) -> bool:
    if actor_id == "player":
        return world.player.position.manhattan(obj.position) <= 1
    actor = world.agents.get(actor_id)
    return bool(actor and actor.position.manhattan(obj.position) <= 1)


def _format_effect_text(template: str, world: WorldState, actor_id: str, item_id: str, obj: WorldObject) -> str:
    return template.format(
        actor=actor_name(world, actor_id),
        actor_id=actor_id,
        item=item_name(item_id),
        item_id=item_id,
        target=obj.name,
        target_id=obj.id,
        target_kind=obj.kind,
    )


def _format_effect_value(value: Any, world: WorldState, actor_id: str, item_id: str, obj: WorldObject) -> Any:
    if isinstance(value, str):
        return _format_effect_text(value, world, actor_id, item_id, obj)
    return value


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _clean_primitive(value: str) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")

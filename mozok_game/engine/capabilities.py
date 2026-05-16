from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mozok_game.engine.inventory import add_item, actor_name, has_item, item_capabilities, item_name, remove_item
from mozok_game.engine.models import Agent, WorldObject
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


TARGET_PRIMITIVES: dict[str, set[str]] = {
    "cave_entrance": {"inspect", "anchor", "climb", "test", "block"},
    "locked_supply_box": {"inspect", "pry", "cut"},
    "food_crate": {"inspect", "pry", "carry"},
    "campfire": {"inspect", "burn", "prepare_food"},
    "water_source": {"inspect", "test"},
    "broken_radio": {"inspect", "repair", "pry"},
    "shelter": {"inspect", "tie", "anchor", "repair"},
    "poisonous_berries": {"inspect", "test", "cut", "consume"},
    "knife": {"inspect", "carry"},
    "rope": {"inspect", "carry"},
    "medkit": {"inspect", "carry"},
    "journal_page": {"inspect", "reveal", "carry"},
}


@dataclass(slots=True)
class PrimitiveResult:
    ok: bool
    message: str
    event_type: str = "item_action"
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def target_primitives(obj: WorldObject) -> set[str]:
    primitives = set(TARGET_PRIMITIVES.get(obj.kind, set()))
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
    if primitive == "pry" and obj and obj.kind == "locked_supply_box":
        return _pry_lockbox(world, actor_id, item_id, obj, reason)
    if primitive == "anchor" and obj and obj.kind == "cave_entrance":
        return _anchor_cave(world, actor_id, item_id, obj, reason)
    if primitive == "inspect":
        return _inspect_target(world, actor_id, item_id, obj, reason)
    if primitive == "test" and obj and obj.kind == "poisonous_berries":
        return _test_berries(world, actor_id, item_id, obj, reason)
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


def _pry_lockbox(world: WorldState, actor_id: str, item_id: str, obj: WorldObject, reason: str) -> PrimitiveResult:
    if obj.state.get("open"):
        result = PrimitiveResult(True, f"{actor_name(world, actor_id)} checks {obj.name}; it is already open.", "item_action", ["item", "inspect", "supplies"])
        world.log(result.event_type, result.message, source=actor_id, tags=result.tags)
        return result
    obj.state["open"] = True
    add_item(world, actor_id, "ration")
    add_item(world, actor_id, "rope")
    message = f"{actor_name(world, actor_id)} pries open {obj.name} with {item_name(item_id)}. Inside: a ration and rope."
    result = PrimitiveResult(
        True,
        message,
        "item_action_pry",
        ["item", "capability", "pry", "supplies", "tool"],
        {"actor_id": actor_id, "item_id": item_id, "target_id": obj.id, "primitive": "pry", "gained": ["ration", "rope"], "reason": reason},
    )
    world.log(result.event_type, result.message, source=actor_id, salience=8, tags=result.tags, metadata=result.metadata)
    return result


def _anchor_cave(world: WorldState, actor_id: str, item_id: str, obj: WorldObject, reason: str) -> PrimitiveResult:
    if obj.state.get("rope_anchored"):
        result = PrimitiveResult(True, f"{actor_name(world, actor_id)} checks the rope already anchored at {obj.name}.", "item_action_anchor", ["item", "safety", "cave"])
        world.log(result.event_type, result.message, source=actor_id, tags=result.tags)
        return result
    obj.state["rope_anchored"] = True
    obj.state["anchored_by"] = actor_id
    obj.state["anchored_item"] = item_id
    remove_item(world, actor_id, item_id)
    agent = world.agents.get(actor_id)
    if agent:
        agent.needs.stress = max(0.0, agent.needs.stress - 14.0)
        agent.social_to_player.fear = max(0.0, agent.social_to_player.fear - 5.0)
        agent.social_to_player.clamp()
    message = f"{actor_name(world, actor_id)} anchors {item_name(item_id)} at {obj.name}, making the cave approach feel less reckless."
    result = PrimitiveResult(
        True,
        message,
        "item_action_anchor",
        ["item", "capability", "anchor", "safety", "cave", "tool"],
        {"actor_id": actor_id, "item_id": item_id, "target_id": obj.id, "primitive": "anchor", "reason": reason},
    )
    world.log(result.event_type, result.message, source=actor_id, salience=9, tags=result.tags, metadata=result.metadata)
    world.flash(actor_id, "Safety plan", "Rope converted cave fear into a concrete precaution.", kind="decision", intensity=0.82)
    return result


def _inspect_target(world: WorldState, actor_id: str, item_id: str, obj: WorldObject | None, reason: str) -> PrimitiveResult:
    if not obj:
        return PrimitiveResult(False, "There is no target to inspect.", tags=["item", "invalid"])
    if obj.kind == "cave_entrance":
        agent = world.agents.get(actor_id)
        if agent:
            risk_reduction = 8.0 if obj.state.get("rope_anchored") else 0.0
            agent.needs.stress += max(3.0, 10.0 - risk_reduction)
            agent.needs.curiosity = max(0.0, agent.needs.curiosity - 15.0)
            agent.needs.clamp()
        message = f"{actor_name(world, actor_id)} inspects {obj.name}; the cave clicks back like something listening."
        tags = ["agent", "inspect", "cave", "mystery"]
    elif obj.kind == "journal_page":
        world.claim("journal_page", "group", "A torn journal page says the cave machinery wakes when people gather near it.", truth_status="verified", confidence=0.85, object="cave_entrance", claim_type="evidence", target_object_id="cave_01")
        message = f"{actor_name(world, actor_id)} reads {obj.name} and surfaces evidence about the cave machinery."
        tags = ["item", "inspect", "evidence", "cave", "mystery"]
    else:
        message = f"{actor_name(world, actor_id)} inspects {obj.name} with {item_name(item_id)}."
        tags = ["item", "inspect", "capability"]
    result = PrimitiveResult(
        True,
        message,
        "item_action_inspect",
        tags,
        {"actor_id": actor_id, "item_id": item_id, "target_id": obj.id, "primitive": "inspect", "reason": reason},
    )
    world.log(result.event_type, result.message, source=actor_id, salience=7, tags=result.tags, metadata=result.metadata)
    return result


def _test_berries(world: WorldState, actor_id: str, item_id: str, obj: WorldObject, reason: str) -> PrimitiveResult:
    obj.state["tested_poisonous"] = True
    world.claim("test", "group", "The berries show signs of toxicity when tested.", truth_status="verified", confidence=0.9, object="poisonous_berries", claim_type="evidence", target_object_id=obj.id)
    message = f"{actor_name(world, actor_id)} tests {obj.name} with {item_name(item_id)}. The result looks poisonous enough to avoid."
    result = PrimitiveResult(
        True,
        message,
        "item_action_test",
        ["item", "capability", "test", "toxic", "evidence", "food"],
        {"actor_id": actor_id, "item_id": item_id, "target_id": obj.id, "primitive": "test", "reason": reason},
    )
    world.log(result.event_type, result.message, source=actor_id, salience=8, tags=result.tags, metadata=result.metadata)
    return result


def _consume_item(world: WorldState, actor_id: str, item_id: str, reason: str) -> PrimitiveResult:
    if item_id == "ration":
        remove_item(world, actor_id, item_id)
        agent = world.agents.get(actor_id)
        if agent:
            agent.needs.hunger = max(0.0, agent.needs.hunger - 48.0)
        else:
            world.player.hunger = max(0.0, world.player.hunger - 48.0)
        message = f"{actor_name(world, actor_id)} eats a ration from inventory."
        tags = ["item", "capability", "consume", "food"]
    elif item_id == "poison_berries":
        remove_item(world, actor_id, item_id)
        agent = world.agents.get(actor_id)
        if agent:
            agent.needs.hunger = max(0.0, agent.needs.hunger - 20.0)
            agent.health = max(1.0, agent.health - 10.0)
            agent.needs.stress += 10.0
            agent.needs.clamp()
        else:
            world.player.hunger = max(0.0, world.player.hunger - 20.0)
            world.player.health = max(1.0, world.player.health - 10.0)
        message = f"{actor_name(world, actor_id)} eats suspicious berries and immediately pays for the risk."
        tags = ["item", "capability", "consume", "food", "toxic", "danger"]
    else:
        message = f"{actor_name(world, actor_id)} cannot safely consume {item_name(item_id)}."
        result = PrimitiveResult(False, message, tags=["item", "invalid"])
        world.log("item_action_rejected", message, source=actor_id, tags=result.tags)
        return result
    result = PrimitiveResult(
        True,
        message,
        "item_action_consume",
        tags,
        {"actor_id": actor_id, "item_id": item_id, "primitive": "consume", "reason": reason},
    )
    world.log(result.event_type, result.message, source=actor_id, salience=7, tags=result.tags, metadata=result.metadata)
    return result


def _actor_near_object(world: WorldState, actor_id: str, obj: WorldObject) -> bool:
    if actor_id == "player":
        return world.player.position.manhattan(obj.position) <= 1
    actor = world.agents.get(actor_id)
    return bool(actor and actor.position.manhattan(obj.position) <= 1)


def _clean_primitive(value: str) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")

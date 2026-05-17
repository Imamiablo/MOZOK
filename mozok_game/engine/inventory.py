from __future__ import annotations

import json
from pathlib import Path

from mozok_game.engine.models import Agent
from mozok_game.engine.world_state import WorldState


FALLBACK_ITEM_DEFS: dict[str, dict[str, object]] = {}


def _item_pack_path(base_dir: Path, ref: str) -> Path:
    ref_path = Path(ref)
    if ref_path.suffix:
        return ref_path if ref_path.is_absolute() else base_dir / "data" / "items" / ref_path
    return base_dir / "data" / "items" / f"{ref}.json"


def _load_item_defs(base_dir: Path | None = None, refs: list[str] | None = None) -> dict[str, dict[str, object]]:
    base_dir = base_dir or Path(__file__).resolve().parents[1]
    refs = refs or ["items"]
    merged: dict[str, dict[str, object]] = {}
    for ref in refs:
        path = _item_pack_path(base_dir, ref)
        if not path.exists():
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            if isinstance(raw.get("items"), dict):
                raw = raw["items"]
            merged.update({str(item_id): dict(config) for item_id, config in raw.items() if isinstance(config, dict)})
    if merged:
        return merged
    path = Path(__file__).resolve().parents[1] / "data" / "items" / "items.json"
    if not path.exists():
        return dict(FALLBACK_ITEM_DEFS)
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {str(item_id): dict(config) for item_id, config in raw.items() if isinstance(config, dict)}


ITEM_DEFS: dict[str, dict[str, object]] = _load_item_defs()


def load_item_definitions(base_dir: Path, refs: list[str] | None = None) -> None:
    """Load scenario item packs into the small synchronous game runtime."""

    global ITEM_DEFS
    ITEM_DEFS = _load_item_defs(base_dir, refs)


def item_name(item_id: str) -> str:
    return str(ITEM_DEFS.get(item_id, {}).get("name") or item_id.replace("_", " ").title())


def item_tags(item_id: str) -> set[str]:
    return set(ITEM_DEFS.get(item_id, {}).get("tags") or [])


def item_capabilities(item_id: str) -> set[str]:
    return set(ITEM_DEFS.get(item_id, {}).get("capabilities") or [])


def item_properties(item_id: str) -> dict[str, object]:
    return dict(ITEM_DEFS.get(item_id, {}).get("properties") or {})


def item_interactions(item_id: str) -> dict[str, object]:
    return dict(ITEM_DEFS.get(item_id, {}).get("inventory_interactions") or ITEM_DEFS.get(item_id, {}).get("interactions") or {})


def items_with_capability(items: list[str], capability: str) -> list[str]:
    return [item for item in items if capability in item_capabilities(item)]


def inventory_label(items: list[str]) -> str:
    if not items:
        return "empty"
    counts: dict[str, int] = {}
    for item in items:
        counts[item] = counts.get(item, 0) + 1
    return ", ".join(f"{item_name(item)} x{count}" if count > 1 else item_name(item) for item, count in counts.items())


def inventory_for_actor(world: WorldState, actor_id: str) -> list[str] | None:
    if actor_id == "player":
        return world.player.inventory
    agent = world.agents.get(actor_id)
    return agent.inventory if agent else None


def actor_name(world: WorldState, actor_id: str) -> str:
    if actor_id == "player":
        return "You"
    agent = world.agents.get(actor_id)
    return agent.name if agent else actor_id


def add_item(world: WorldState, actor_id: str, item_id: str) -> bool:
    inventory = inventory_for_actor(world, actor_id)
    if inventory is None:
        return False
    inventory.append(item_id)
    return True


def remove_item(world: WorldState, actor_id: str, item_id: str) -> bool:
    inventory = inventory_for_actor(world, actor_id)
    if inventory is None or item_id not in inventory:
        return False
    inventory.remove(item_id)
    return True


def has_item(world: WorldState, actor_id: str, item_id: str) -> bool:
    inventory = inventory_for_actor(world, actor_id)
    return bool(inventory and item_id in inventory)


def transfer_item(world: WorldState, from_actor_id: str, to_actor_id: str, item_id: str, reason: str = "") -> bool:
    if not remove_item(world, from_actor_id, item_id):
        return False
    if not add_item(world, to_actor_id, item_id):
        add_item(world, from_actor_id, item_id)
        return False
    world.log(
        "item_transfer",
        f"{actor_name(world, from_actor_id)} gives {item_name(item_id)} to {actor_name(world, to_actor_id)}.",
        source=from_actor_id,
        salience=7,
        tags=["item", "inventory", "transfer"],
        metadata={"from": from_actor_id, "to": to_actor_id, "item_id": item_id, "reason": reason},
        actor_id=from_actor_id,
        target_id=to_actor_id,
        item_id=item_id,
        visibility="witnessed",
    )
    return True


def choose_item_for_agent_need(agent: Agent) -> str:
    if "wounded" in agent.status_flags:
        return "medkit"
    if agent.needs.hunger > 70:
        return "ration"
    return ""


def first_transferable_item(items: list[str]) -> str:
    for item in items:
        if item in ITEM_DEFS:
            return item
    return items[0] if items else ""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from mozok_game.engine.inventory import ITEM_DEFS, item_name
from mozok_game.engine.models import Agent, WorldObject
from mozok_game.engine.world_state import WorldState


_STAGE_RE = re.compile(r"\*([^*]+)\*")
_POSSESSION_VERBS = (
    "fidget with",
    "fidgets with",
    "hold",
    "holds",
    "holding",
    "grip",
    "grips",
    "clutch",
    "clutches",
    "twirl",
    "twirls",
    "draw",
    "draws",
    "grab",
    "grabs",
    "take",
    "takes",
    "hand",
    "hands",
    "give",
    "gives",
    "throw",
    "throws",
    "load",
    "loads",
    "cut",
    "cuts",
    "tie",
    "ties",
    "bind",
    "binds",
    "eat",
    "eats",
    "drink",
    "drinks",
    "bandage",
    "bandages",
)
_OBJECT_MUTATION_VERBS = (
    "open",
    "opens",
    "unlock",
    "unlocks",
    "light",
    "lights",
    "extinguish",
    "extinguishes",
    "repair",
    "repairs",
    "touch",
    "touches",
    "pull",
    "pulls",
    "push",
    "pushes",
    "move",
    "moves",
)
_REFERENCE_VERBS = (
    "glance",
    "glances",
    "look",
    "looks",
    "watch",
    "watches",
    "eye",
    "eyes",
    "nod",
    "nods",
    "point",
    "points",
    "gesture",
    "gestures",
)


@dataclass(slots=True)
class SceneGrounding:
    speaker_id: str
    speaker_name: str
    inventory: list[str] = field(default_factory=list)
    nearby_objects: list[dict[str, Any]] = field(default_factory=list)
    legal_interactions: list[dict[str, str]] = field(default_factory=list)


@dataclass(slots=True)
class SceneValidationResult:
    text: str
    rewrites: list[str] = field(default_factory=list)
    rejected_physical_claims: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.text != "" and bool(self.rewrites or self.rejected_physical_claims)


def build_scene_grounding(world: WorldState, agent: Agent, visible_distance: int = 6) -> SceneGrounding:
    nearby: list[dict[str, Any]] = []
    legal: list[dict[str, str]] = []
    for obj in world.objects.values():
        distance = agent.position.manhattan(obj.position)
        if distance > visible_distance:
            continue
        record = {
            "id": obj.id,
            "name": obj.name,
            "kind": obj.kind,
            "distance": distance,
            "tags": list(obj.tags),
            "state": dict(obj.state),
        }
        nearby.append(record)
        if distance <= 1:
            for interaction_id in obj.interactions:
                spec = obj.interaction_defs.get(interaction_id) or {}
                legal.append(
                    {
                        "action": "interact_with_object",
                        "target_object_id": obj.id,
                        "interaction_id": interaction_id,
                        "label": str(spec.get("label") or interaction_id),
                    }
                )
    return SceneGrounding(
        speaker_id=agent.id,
        speaker_name=agent.name,
        inventory=list(agent.inventory),
        nearby_objects=nearby,
        legal_interactions=legal,
    )


def grounding_prompt(world: WorldState, agent: Agent) -> str:
    grounding = build_scene_grounding(world, agent)
    inventory = ", ".join(f"{item_id}:{item_name(item_id)}" for item_id in grounding.inventory) or "empty"
    objects = "; ".join(
        f"{obj['id']} name={obj['name']} kind={obj['kind']} distance={obj['distance']} tags={obj['tags']}"
        for obj in grounding.nearby_objects[:12]
    ) or "none nearby"
    legal = "; ".join(
        f"{item['action']} {item['target_object_id']}:{item['interaction_id']} ({item['label']})"
        for item in grounding.legal_interactions[:12]
    ) or "no adjacent object interactions"
    return (
        f"Physical grounding for {agent.name}: inventory=[{inventory}]. "
        f"Visible/nearby objects: {objects}. Legal physical interactions now: {legal}. "
        "You may dramatise speech and emotion, but do not describe the speaker holding, using, drawing, handing, "
        "opening, taking, lighting, cutting, repairing, eating, drinking, tying, or fidgeting with any item/object "
        "unless it is in inventory or listed as a legal/recent physical interaction. "
        "Looking/glancing/pointing toward visible objects is allowed."
    )


def validate_agent_dialogue(world: WorldState, agent: Agent, text: str) -> SceneValidationResult:
    if not text or "*" not in text:
        return SceneValidationResult(text=text)

    rewrites: list[str] = []
    rejected: list[str] = []

    def replace_stage(match: re.Match[str]) -> str:
        stage = match.group(1)
        grounded = _ground_stage_direction(world, agent, stage, rewrites, rejected)
        return f"*{grounded}*"

    grounded_text = _STAGE_RE.sub(replace_stage, text)
    return SceneValidationResult(text=grounded_text, rewrites=rewrites, rejected_physical_claims=rejected)


def _ground_stage_direction(
    world: WorldState,
    agent: Agent,
    stage: str,
    rewrites: list[str],
    rejected: list[str],
) -> str:
    lower = stage.lower()
    if not _mentions_physical_verb(lower):
        return stage
    item_id = _mentioned_item_id(stage)
    obj = _mentioned_object(world, stage)

    if item_id:
        if item_id in agent.inventory or _recent_validated_use(world, agent.id, item_id=item_id):
            return stage
        rejected.append(f"{agent.name} does not possess {item_name(item_id)}")
        replacement = _rewrite_invalid_prop_stage(stage, _visible_object_for_item(world, agent, item_id))
        rewrites.append(f"{stage} -> {replacement}")
        return replacement

    if obj and _mentions_mutating_verb(lower):
        if agent.position.manhattan(obj.position) <= 1 and _recent_validated_use(world, agent.id, target_id=obj.id):
            return stage
        if _mentions_reference_verb(lower) and agent.position.manhattan(obj.position) <= 6:
            return stage
        rejected.append(f"{agent.name} cannot assert physical use of {obj.name}")
        replacement = _rewrite_invalid_prop_stage(stage, obj if agent.position.manhattan(obj.position) <= 6 else None)
        rewrites.append(f"{stage} -> {replacement}")
        return replacement

    return stage


def _mentions_physical_verb(text: str) -> bool:
    return any(verb in text for verb in (*_POSSESSION_VERBS, *_OBJECT_MUTATION_VERBS))


def _mentions_mutating_verb(text: str) -> bool:
    return any(verb in text for verb in (*_POSSESSION_VERBS, *_OBJECT_MUTATION_VERBS))


def _mentions_reference_verb(text: str) -> bool:
    return any(verb in text for verb in _REFERENCE_VERBS)


def _mentioned_item_id(text: str) -> str:
    lower = _normalise(text)
    candidates: list[tuple[int, str]] = []
    for item_id, config in ITEM_DEFS.items():
        labels = {item_id, str(config.get("name") or ""), *(str(tag) for tag in config.get("tags") or [])}
        for label in labels:
            clean = _normalise(label)
            if len(clean) >= 3 and _contains_label(lower, clean):
                candidates.append((len(clean), item_id))
    return max(candidates, default=(0, ""))[1]


def _mentioned_object(world: WorldState, text: str) -> WorldObject | None:
    lower = _normalise(text)
    candidates: list[tuple[int, WorldObject]] = []
    for obj in world.objects.values():
        labels = {obj.id, obj.kind, obj.name, *obj.tags, *obj.aliases}
        for label in labels:
            clean = _normalise(label)
            if len(clean) >= 3 and _contains_label(lower, clean):
                candidates.append((len(clean), obj))
    return max(candidates, key=lambda item: item[0], default=(0, None))[1]


def _visible_object_for_item(world: WorldState, agent: Agent, item_id: str) -> WorldObject | None:
    labels = {_normalise(item_id), _normalise(item_name(item_id))}
    best: tuple[int, WorldObject] | None = None
    for obj in world.objects.values():
        obj_labels = {_normalise(obj.id), _normalise(obj.kind), _normalise(obj.name), *(_normalise(tag) for tag in obj.tags), *(_normalise(alias) for alias in obj.aliases)}
        if not labels.intersection(obj_labels):
            continue
        distance = agent.position.manhattan(obj.position)
        if distance > 6:
            continue
        if best is None or distance < best[0]:
            best = (distance, obj)
    return best[1] if best else None


def _rewrite_invalid_prop_stage(stage: str, visible_obj: WorldObject | None) -> str:
    tail = ""
    if "," in stage:
        tail = ", " + stage.split(",", 1)[1].strip()
    if visible_obj:
        return f"glances toward {visible_obj.name}{tail}"
    return f"fidgets with a sleeve{tail}"


def _recent_validated_use(world: WorldState, actor_id: str, item_id: str = "", target_id: str = "") -> bool:
    for event in world.event_log[-5:]:
        if event.actor_id != actor_id:
            continue
        if item_id and event.item_id == item_id:
            return True
        if target_id and event.target_id == target_id:
            return True
    return False


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9_ ]+", " ", str(text).lower().replace("_", " "))).strip()


def _contains_label(text: str, label: str) -> bool:
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(label)}(?![a-z0-9])", text))

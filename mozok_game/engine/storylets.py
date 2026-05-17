from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mozok_game.engine.world_state import WorldState


@dataclass(slots=True)
class StoryletSpec:
    id: str
    title: str
    tags: list[str] = field(default_factory=list)
    requires: dict[str, Any] = field(default_factory=dict)
    effects: list[dict[str, Any]] = field(default_factory=list)

    def can_fire(self, world: WorldState) -> bool:
        if self.id in world.scripted_flags:
            return False
        return _requirements_met(world, self.requires)

    def fire(self, world: WorldState) -> bool:
        if not self.can_fire(world):
            return False
        world.scripted_flags.add(self.id)
        for effect in self.effects:
            _apply_effect(world, self, effect)
        return True


def run_storylet_director(world: WorldState) -> None:
    for storylet in load_storylet_specs():
        if storylet.fire(world):
            return


def load_storylet_specs() -> list[StoryletSpec]:
    path = Path(__file__).resolve().parents[1] / "data" / "storylets" / "storylets.json"
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
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
    pressure_sum = requires.get("pressure_sum_gt")
    if isinstance(pressure_sum, dict):
        axes = [str(axis) for axis in pressure_sum.get("axes") or []]
        if sum(world.pressure.get(axis, 0.0) for axis in axes) <= float(pressure_sum.get("value", 0.0)):
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


def _apply_need_delta_if_unprotected(world: WorldState, effect: dict[str, Any]) -> None:
    protected_kinds = [str(kind) for kind in effect.get("protected_near_kinds") or []]
    protected_distance = int(effect.get("protected_distance", 2))
    protected_delta = dict(effect.get("protected_delta") or {})
    unprotected_delta = dict(effect.get("unprotected_delta") or {})
    flash = effect.get("unprotected_flash") if isinstance(effect.get("unprotected_flash"), dict) else {}
    protected_objects = [obj for obj in world.objects.values() if obj.kind in protected_kinds]
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

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from mozok_game.engine.world_state import WorldState


@dataclass(slots=True)
class Storylet:
    id: str
    title: str
    tags: list[str] = field(default_factory=list)
    condition: Callable[[WorldState], bool] | None = None
    effect: Callable[[WorldState], None] | None = None

    def can_fire(self, world: WorldState) -> bool:
        if self.id in world.scripted_flags:
            return False
        return bool(self.condition(world) if self.condition else True)

    def fire(self, world: WorldState) -> bool:
        if not self.can_fire(world):
            return False
        world.scripted_flags.add(self.id)
        if self.effect:
            self.effect(world)
        return True


def run_storylet_director(world: WorldState) -> None:
    for storylet in STORYLET_DECK:
        if storylet.fire(world):
            return


def _cold_rain_condition(world: WorldState) -> bool:
    if world.turn < 6:
        return False
    if world.pressure.get("exhaustion", 0.0) > 0.72:
        return False
    if world.pressure.get("danger", 0.0) > 0.82:
        return False
    scarcity = world.pressure.get("scarcity", 0.0)
    mystery = world.pressure.get("mystery", 0.0)
    return scarcity + mystery > 0.08


def _cold_rain_effect(world: WorldState) -> None:
    world.log(
        "weather_rain_squall",
        "Cold rain rolls over the camp. The fire hisses and everyone starts losing warmth.",
        source="weather",
        salience=9,
        tags=["weather", "cold", "rain", "survival"],
        metadata={"storylet_id": "rain_squall", "pressure": dict(world.pressure)},
    )
    campfire = world.object_by_kind("campfire")
    shelter = world.object_by_kind("shelter")
    for agent in world.agents.values():
        protected = bool(
            (campfire and agent.position.manhattan(campfire.position) <= 2)
            or (shelter and agent.position.manhattan(shelter.position) <= 1)
        )
        agent.needs.fatigue += 4.0 if protected else 12.0
        agent.needs.stress += 3.0 if protected else 10.0
        agent.needs.clamp()
        if not protected:
            world.flash(agent.id, "Cold stress", "Rain made shelter and fire immediately more important.", kind="body", intensity=0.7)


STORYLET_DECK = [
    Storylet(
        id="rain_squall",
        title="Cold Rain Squall",
        tags=["weather", "survival", "exhaustion"],
        condition=_cold_rain_condition,
        effect=_cold_rain_effect,
    )
]

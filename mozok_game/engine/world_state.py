from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mozok_game.engine.map_grid import MapGrid
from mozok_game.engine.models import Agent, BrainFlash, ChatLine, Needs, Player, Position, SocialState, WorldEvent, WorldObject


@dataclass
class WorldState:
    grid: MapGrid
    player: Player
    agents: dict[str, Agent]
    objects: dict[str, WorldObject]
    turn: int = 0
    player_facing: str = "north"
    event_log: list[WorldEvent] = field(default_factory=list)
    brain_flashes: list[BrainFlash] = field(default_factory=list)
    chat_log: list[ChatLine] = field(default_factory=list)
    scripted_flags: set[str] = field(default_factory=set)
    last_agent_conversation_turn: int = -99
    selected_agent_id: str | None = None
    last_message: str = "Welcome to Island Camp. Something moved near the cave."

    def log(self, event_type: str, content: str, source: str = "game", salience: float = 5.0, tags: list[str] | None = None, metadata: dict[str, Any] | None = None) -> WorldEvent:
        event = WorldEvent(
            turn=self.turn,
            event_type=event_type,
            content=content,
            source=source,
            salience=salience,
            tags=tags or [],
            metadata=metadata or {},
        )
        self.event_log.append(event)
        self.event_log = self.event_log[-80:]
        self.last_message = content
        return event

    def flash(self, agent_id: str, title: str, content: str, kind: str = "memory", intensity: float = 0.5) -> BrainFlash:
        flash = BrainFlash(
            turn=self.turn,
            agent_id=agent_id,
            title=title,
            content=content,
            kind=kind,
            intensity=max(0.0, min(1.0, intensity)),
        )
        self.brain_flashes.append(flash)
        self.brain_flashes = self.brain_flashes[-12:]
        return flash

    def chat(self, speaker_id: str, speaker_name: str, content: str, source: str = "player") -> ChatLine:
        line = ChatLine(
            turn=self.turn,
            speaker_id=speaker_id,
            speaker_name=speaker_name,
            content=content,
            source=source,
        )
        self.chat_log.append(line)
        self.chat_log = self.chat_log[-30:]
        return line

    def occupied_positions(self, exclude_agent_id: str | None = None) -> set[tuple[int, int]]:
        result = {(self.player.position.x, self.player.position.y)}
        for agent in self.agents.values():
            if exclude_agent_id and agent.id == exclude_agent_id:
                continue
            if agent.alive:
                result.add((agent.position.x, agent.position.y))
        return result

    def nearby_agents(self, distance: int = 1) -> list[Agent]:
        return [agent for agent in self.agents.values() if agent.alive and agent.position.manhattan(self.player.position) <= distance]

    def nearby_objects(self, distance: int = 1) -> list[WorldObject]:
        return [obj for obj in self.objects.values() if obj.position.manhattan(self.player.position) <= distance]

    def object_by_kind(self, kind: str) -> WorldObject | None:
        for obj in self.objects.values():
            if obj.kind == kind:
                return obj
        return None

    def find_object_with_tag(self, tag: str) -> WorldObject | None:
        for obj in self.objects.values():
            if tag in obj.tags:
                return obj
        return None


def _pos(raw: list[int] | tuple[int, int]) -> Position:
    return Position(int(raw[0]), int(raw[1]))


def load_world(base_dir: Path) -> WorldState:
    scenario_path = base_dir / "data" / "scenarios" / "island_camp_demo.json"
    data = json.loads(scenario_path.read_text(encoding="utf-8"))
    grid = MapGrid.from_ascii(data["map"]["rows"])
    player = Player(position=_pos(data["player"]["position"]))
    agents: dict[str, Agent] = {}
    for item in data["agents"]:
        agents[item["id"]] = Agent(
            id=item["id"],
            name=item["name"],
            role=item.get("role", "survivor"),
            position=_pos(item["position"]),
            avatar_folder=item.get("avatar_folder", item["id"]),
            personality=item.get("personality", "survivor"),
            needs=Needs(**item.get("needs", {})),
            social_to_player=SocialState(**item.get("social_to_player", {})),
            emotion=item.get("emotion", "neutral"),
            current_goal=item.get("current_goal", "stay_alive"),
            memory_snippets=list(item.get("memory_snippets", [])),
        )
    objects: dict[str, WorldObject] = {}
    for item in data["objects"]:
        objects[item["id"]] = WorldObject(
            id=item["id"],
            name=item["name"],
            kind=item["kind"],
            position=_pos(item["position"]),
            interactions=list(item.get("interactions", [])),
            tags=list(item.get("tags", [])),
            state=dict(item.get("state", {})),
        )
    world = WorldState(grid=grid, player=player, agents=agents, objects=objects)
    for event in data.get("opening_events", []):
        world.log(event.get("event_type", "opening"), event["content"], source="scenario", salience=event.get("salience", 7), tags=event.get("tags", []))
    return world

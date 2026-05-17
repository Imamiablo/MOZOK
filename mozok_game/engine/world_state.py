from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from mozok_game.engine.map_grid import MapGrid
from mozok_game.engine.models import Agent, BrainFlash, ChatLine, ClaimRecord, Needs, Player, Position, SocialState, WorldEvent, WorldObject
from mozok_game.engine.pressure import apply_event_pressure, default_pressure_field


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
    claim_log: list[ClaimRecord] = field(default_factory=list)
    scripted_flags: set[str] = field(default_factory=set)
    pressure: dict[str, float] = field(default_factory=default_pressure_field)
    event_counter: int = 0
    last_agent_conversation_turn: int = -99
    selected_agent_id: str | None = None
    last_message: str = "Welcome to Island Camp. Something moved near the cave."

    def log(
        self,
        event_type: str,
        content: str,
        source: str = "game",
        salience: float = 5.0,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        actor_id: str = "",
        target_id: str = "",
        item_id: str = "",
        location_id: str = "",
        witness_ids: list[str] | None = None,
        visibility: str = "public",
        reliability: float = 1.0,
        truth_status: str = "observed",
        idempotency_key: str = "",
    ) -> WorldEvent:
        self.event_counter += 1
        event_id = f"evt_{self.turn:04d}_{self.event_counter:05d}"
        event_metadata = dict(metadata or {})
        event_metadata.setdefault("event_id", event_id)
        event_actor_id = actor_id or str(event_metadata.get("actor_id") or event_metadata.get("actor") or "")
        event_target_id = target_id or str(event_metadata.get("target_id") or event_metadata.get("target") or event_metadata.get("object_id") or "")
        event_item_id = item_id or str(event_metadata.get("item_id") or "")
        event_witness_ids = list(witness_ids if witness_ids is not None else self._infer_witness_ids(event_actor_id, event_target_id, visibility))
        event_metadata.setdefault("actor_id", event_actor_id)
        event_metadata.setdefault("target_id", event_target_id)
        event_metadata.setdefault("item_id", event_item_id)
        event_metadata.setdefault("witness_ids", event_witness_ids)
        event_metadata.setdefault("visibility", visibility)
        event_truth_status = str(event_metadata.get("truth_status") or truth_status or "observed")
        event_idempotency_key = str(event_metadata.get("idempotency_key") or idempotency_key or event_id)
        event_metadata.setdefault("truth_status", event_truth_status)
        event_metadata.setdefault("idempotency_key", event_idempotency_key)
        event = WorldEvent(
            event_id=event_id,
            turn=self.turn,
            event_type=event_type,
            content=content,
            source=source,
            salience=salience,
            tags=tags or [],
            metadata=event_metadata,
            actor_id=event_actor_id,
            target_id=event_target_id,
            item_id=event_item_id,
            location_id=location_id or str(event_metadata.get("location_id") or ""),
            witness_ids=event_witness_ids,
            visibility=visibility,
            reliability=max(0.0, min(1.0, float(reliability))),
            truth_status=event_truth_status,
            idempotency_key=event_idempotency_key,
        )
        self.event_log.append(event)
        self.event_log = self.event_log[-80:]
        apply_event_pressure(self.pressure, event)
        self.last_message = content
        return event

    def _infer_witness_ids(self, actor_id: str, target_id: str, visibility: str) -> list[str]:
        if visibility in {"hidden", "private"}:
            return []
        anchor: Position | None = None
        if target_id and target_id in self.objects:
            anchor = self.objects[target_id].position
        elif actor_id == "player":
            anchor = self.player.position
        elif actor_id in self.agents:
            anchor = self.agents[actor_id].position
        if not anchor:
            return []
        distance = 6 if visibility in {"public", "visible", "witnessed"} else 3
        return [agent.id for agent in self.agents.values() if agent.alive and agent.position.manhattan(anchor) <= distance]

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

    def chat(self, speaker_id: str, speaker_name: str, content: str, source: str = "player", audience_ids: list[str] | None = None) -> ChatLine:
        line = ChatLine(
            turn=self.turn,
            speaker_id=speaker_id,
            speaker_name=speaker_name,
            content=content,
            source=source,
            audience_ids=list(audience_ids or []),
        )
        self.chat_log.append(line)
        self.chat_log = self.chat_log[-30:]
        return line

    def claim(
        self,
        speaker_id: str,
        listener_id: str,
        text: str,
        truth_status: str = "unverified",
        confidence: float = 0.0,
        subject: str = "",
        predicate: str = "",
        object: str = "",
        claim_type: str = "world_fact",
        target_object_id: str = "",
    ) -> ClaimRecord:
        record = ClaimRecord(
            turn=self.turn,
            speaker_id=speaker_id,
            listener_id=listener_id,
            text=text,
            subject=subject,
            predicate=predicate,
            object=object,
            claim_type=claim_type,
            target_object_id=target_object_id,
            truth_status=truth_status,
            confidence=max(0.0, min(1.0, float(confidence))),
        )
        self.claim_log.append(record)
        self.claim_log = self.claim_log[-40:]
        return record

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
            if tag not in obj.tags:
                continue
            if obj.state.get("taken"):
                continue
            if obj.kind == "food_crate" and int(obj.state.get("food", 0)) <= 0:
                continue
            if obj.kind == "poisonous_berries" and int(obj.state.get("berries", 0)) <= 0:
                continue
            if obj.kind == "locked_supply_box" and obj.state.get("open"):
                continue
            if tag in obj.tags:
                return obj
        return None

    def export_authoritative_state(self) -> dict[str, Any]:
        return {
            "turn": self.turn,
            "player": {
                "position": {"x": self.player.position.x, "y": self.player.position.y},
                "inventory": list(self.player.inventory),
                "health": self.player.health,
                "hunger": self.player.hunger,
                "thirst": self.player.thirst,
                "fatigue": self.player.fatigue,
            },
            "agents": {
                agent_id: {
                    "name": agent.name,
                    "position": {"x": agent.position.x, "y": agent.position.y},
                    "health": agent.health,
                    "inventory": list(agent.inventory),
                    "status_flags": list(agent.status_flags),
                    "needs": {
                        "hunger": agent.needs.hunger,
                        "thirst": agent.needs.thirst,
                        "fatigue": agent.needs.fatigue,
                        "stress": agent.needs.stress,
                        "social": agent.needs.social,
                        "curiosity": agent.needs.curiosity,
                    },
                    "active_commitment": asdict(agent.active_commitment) if agent.active_commitment else None,
                }
                for agent_id, agent in self.agents.items()
            },
            "objects": {
                object_id: {
                    "name": obj.name,
                    "kind": obj.kind,
                    "position": {"x": obj.position.x, "y": obj.position.y},
                    "tags": list(obj.tags),
                    "state": dict(obj.state),
                    "capability_accepts": list(obj.capability_accepts),
                    "capability_effects": dict(obj.capability_effects),
                }
                for object_id, obj in self.objects.items()
            },
            "pressure": dict(self.pressure),
        }


def _pos(raw: list[int] | tuple[int, int]) -> Position:
    return Position(int(raw[0]), int(raw[1]))


def load_world(base_dir: Path) -> WorldState:
    scenario_path = base_dir / "data" / "scenarios" / "island_camp_demo.json"
    data = json.loads(scenario_path.read_text(encoding="utf-8"))
    grid = MapGrid.from_ascii(data["map"]["rows"])
    player = Player(position=_pos(data["player"]["position"]))
    agents: dict[str, Agent] = {}
    for item in data["agents"]:
        merged = _merged_agent_card(base_dir, item)
        agents[merged["id"]] = Agent(
            id=merged["id"],
            name=merged["name"],
            role=merged.get("role", "survivor"),
            position=_pos(merged["position"]),
            avatar_folder=merged.get("avatar_folder", merged["id"]),
            personality=merged.get("personality", merged.get("summary", "survivor")),
            traits={key: float(value) for key, value in dict(merged.get("traits", {})).items()},
            values=list(merged.get("values", [])),
            fears=list(merged.get("fears", [])),
            skills=list(merged.get("skills", [])),
            appearance=dict(merged.get("appearance", {})),
            voice=dict(merged.get("voice", {})),
            limits=list(merged.get("limits", [])),
            temptations=list(merged.get("temptations", [])),
            stress_response=list(merged.get("stress_response", [])),
            authority_response=list(merged.get("authority_response", [])),
            trust_response=list(merged.get("trust_response", [])),
            action_biases={key: float(value) for key, value in dict(merged.get("action_biases", {})).items()},
            needs=Needs(**merged.get("needs", {})),
            social_to_player=SocialState(**merged.get("social_to_player", {})),
            emotion=merged.get("emotion", "neutral"),
            health=float(merged.get("health", 100.0)),
            status_flags=list(merged.get("status_flags", [])),
            current_goal=merged.get("current_goal", "stay_alive"),
            inventory=list(merged.get("inventory", [])),
            memory_snippets=list(merged.get("memory_snippets", [])),
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
            capability_accepts=list(item.get("capability_accepts") or item.get("accepts") or []),
            capability_effects=dict(item.get("capability_effects", {})),
        )
    world = WorldState(grid=grid, player=player, agents=agents, objects=objects)
    for event in data.get("opening_events", []):
        world.log(event.get("event_type", "opening"), event["content"], source="scenario", salience=event.get("salience", 7), tags=event.get("tags", []))
    return world


def _merged_agent_card(base_dir: Path, scenario_agent: dict[str, Any]) -> dict[str, Any]:
    card_path = base_dir / "data" / "agents" / f"{scenario_agent['id']}.json"
    if not card_path.exists():
        return dict(scenario_agent)
    card = json.loads(card_path.read_text(encoding="utf-8"))
    merged = dict(card)
    for key, value in scenario_agent.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            nested = dict(merged[key])
            nested.update(value)
            merged[key] = nested
        else:
            merged[key] = value
    return merged

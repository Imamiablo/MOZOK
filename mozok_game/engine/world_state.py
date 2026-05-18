from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from mozok_game.engine.map_grid import MapGrid
from mozok_game.engine.models import Agent, AgentBelief, BrainFlash, ChatLine, ClaimRecord, Needs, Player, Position, SocialState, WorldEvent, WorldObject
from mozok_game.engine.pressure import apply_event_pressure, default_pressure_field
from mozok_game.engine.relationships import initialise_world_relationships


@dataclass
class WorldState:
    grid: MapGrid
    player: Player
    agents: dict[str, Agent]
    objects: dict[str, WorldObject]
    scenario_id: str = "scenario"
    scenario_title: str = "Scenario"
    setting_summary: str = ""
    tone: dict[str, Any] = field(default_factory=dict)
    themes: list[str] = field(default_factory=list)
    art_pack: str = "island_ruins"
    dialogue_templates: dict[str, Any] = field(default_factory=dict)
    scripted_moments: dict[str, Any] = field(default_factory=dict)
    storylet_specs: list[dict[str, Any]] = field(default_factory=list)
    drama_atoms: list[dict[str, Any]] = field(default_factory=list)
    appraisal_rules: list[dict[str, Any]] = field(default_factory=list)
    pack_refs: dict[str, list[str]] = field(default_factory=dict)
    pressure_tag_deltas: dict[str, dict[str, float]] = field(default_factory=dict)
    pressure_event_deltas: dict[str, dict[str, float]] = field(default_factory=dict)
    turn: int = 0
    player_facing: str = "north"
    event_log: list[WorldEvent] = field(default_factory=list)
    brain_flashes: list[BrainFlash] = field(default_factory=list)
    chat_log: list[ChatLine] = field(default_factory=list)
    claim_log: list[ClaimRecord] = field(default_factory=list)
    agent_beliefs: list[AgentBelief] = field(default_factory=list)
    scripted_flags: set[str] = field(default_factory=set)
    pressure: dict[str, float] = field(default_factory=default_pressure_field)
    event_counter: int = 0
    last_agent_conversation_turn: int = -99
    selected_agent_id: str | None = None
    last_message: str = "Welcome to the sandbox. The world is waiting for input."

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
        self._record_perception_beliefs(event)
        apply_event_pressure(self.pressure, event, self.pressure_tag_deltas, self.pressure_event_deltas)
        self.last_message = content
        return event

    def _record_perception_beliefs(self, event: WorldEvent) -> None:
        if event.visibility in {"hidden", "private"}:
            return
        if not event.witness_ids or not (event.actor_id or event.target_id or event.item_id):
            return
        predicate = event.event_type.replace("_", " ")
        obj = event.item_id or event.target_id
        subject = event.actor_id or event.source
        emotional_tags = [tag for tag in event.tags if tag in {"scarcity", "food", "danger", "mystery", "conflict", "social_risk", "hostile_alarm", "item", "medical"}]
        for agent_id in event.witness_ids:
            if agent_id not in self.agents:
                continue
            self.agent_beliefs.append(
                AgentBelief(
                    turn=event.turn,
                    agent_id=agent_id,
                    subject=subject,
                    predicate=predicate,
                    object=obj,
                    confidence=max(0.0, min(1.0, event.reliability)),
                    source="witnessed",
                    world_event_id=event.event_id,
                    emotional_tags=emotional_tags,
                    text=event.content,
                )
            )
        self.agent_beliefs = self.agent_beliefs[-80:]

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
            if not self.is_object_available(obj):
                continue
            return obj
        return None

    def is_object_available(self, obj: WorldObject) -> bool:
        if obj.state.get("taken"):
            return False
        for interaction_id, spec in obj.interaction_defs.items():
            if not isinstance(spec, dict):
                continue
            for key, minimum in dict(spec.get("requires_state_min") or {}).items():
                if float(obj.state.get(str(key), 0)) >= float(minimum):
                    return True
        return True

    def export_authoritative_state(self) -> dict[str, Any]:
        return {
            "turn": self.turn,
            "scenario": {
                "id": self.scenario_id,
                "title": self.scenario_title,
                "setting_summary": self.setting_summary,
                "tone": dict(self.tone),
                "themes": list(self.themes),
                "pack_refs": {key: list(value) for key, value in self.pack_refs.items()},
            },
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
                    "social_to_player": {
                        "trust": agent.social_to_player.trust,
                        "fear": agent.social_to_player.fear,
                        "affinity": agent.social_to_player.affinity,
                        "resentment": agent.social_to_player.resentment,
                    },
                    "relationships": {
                        target_id: {
                            "trust": social.trust,
                            "fear": social.fear,
                            "affinity": social.affinity,
                            "resentment": social.resentment,
                        }
                        for target_id, social in agent.relationships.items()
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
                    "aliases": list(obj.aliases),
                    "object_type": obj.object_type,
                    "sprite": obj.sprite,
                    "properties": dict(obj.properties),
                    "render": dict(obj.render),
                    "interactions": list(obj.interactions),
                    "interaction_defs": dict(obj.interaction_defs),
                    "state": dict(obj.state),
                    "capability_accepts": list(obj.capability_accepts),
                    "capability_effects": dict(obj.capability_effects),
                }
                for object_id, obj in self.objects.items()
            },
            "pressure": dict(self.pressure),
            "beliefs": [
                {
                    "turn": belief.turn,
                    "agent_id": belief.agent_id,
                    "subject": belief.subject,
                    "predicate": belief.predicate,
                    "object": belief.object,
                    "confidence": belief.confidence,
                    "source": belief.source,
                    "world_event_id": belief.world_event_id,
                    "emotional_tags": list(belief.emotional_tags),
                    "text": belief.text,
                }
                for belief in self.agent_beliefs[-20:]
            ],
        }


def _pos(raw: list[int] | tuple[int, int]) -> Position:
    return Position(int(raw[0]), int(raw[1]))


def _relationships_from_dict(raw: Any) -> dict[str, SocialState]:
    if not isinstance(raw, dict):
        return {}
    result: dict[str, SocialState] = {}
    for target_id, data in raw.items():
        if isinstance(data, dict):
            result[str(target_id)] = SocialState(**{key: value for key, value in data.items() if key in {"trust", "fear", "affinity", "resentment"}})
    return result


def load_world(base_dir: Path, scenario_id: str = "island_camp_demo") -> WorldState:
    return load_world_from_path(base_dir, base_dir / "data" / "scenarios" / f"{scenario_id}.json")


def load_world_from_path(base_dir: Path, scenario_path: Path) -> WorldState:
    data = _load_json(scenario_path)
    item_refs = _as_ref_list(data.get("item_pack_refs")) or ["items"]
    from mozok_game.engine.inventory import load_item_definitions

    load_item_definitions(base_dir, item_refs)
    map_data = _load_map_data(base_dir, data)
    tile_defs = {str(key): dict(value) for key, value in dict(map_data.get("tile_defs") or data.get("tile_defs") or {}).items() if isinstance(value, dict)}
    grid = MapGrid.from_ascii(map_data["rows"], legend=dict(map_data.get("legend") or {}), tile_defs=tile_defs)
    player = Player(position=_pos(data.get("player", {}).get("position", [0, 0])))
    agents: dict[str, Agent] = {}
    for item in _load_agent_entries(base_dir, data):
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
            relationships=_relationships_from_dict(merged.get("relationships")),
            emotion=merged.get("emotion", "neutral"),
            health=float(merged.get("health", 100.0)),
            status_flags=list(merged.get("status_flags", [])),
            current_goal=merged.get("current_goal", "stay_alive"),
            inventory=list(merged.get("inventory", [])),
            memory_snippets=list(merged.get("memory_snippets", [])),
        )
    objects: dict[str, WorldObject] = {}
    for item in _load_object_entries(base_dir, data):
        obj = _world_object_from_dict(item)
        objects[obj.id] = obj
    setting = data.get("setting") if isinstance(data.get("setting"), dict) else {}
    pack_refs = {
        "map": _as_ref_list(data.get("map_ref")),
        "items": item_refs,
        "objects": _as_ref_list(data.get("object_pack_refs")),
        "characters": [str(item.get("id") if isinstance(item, dict) else item) for item in _as_list(data.get("character_refs"))],
        "dialogue": _as_ref_list(data.get("dialogue_pack_refs")),
        "director_moments": _as_ref_list(data.get("director_moment_pack_refs")),
        "storylets": _as_ref_list(data.get("storylet_pack_refs")),
        "drama_atoms": _as_ref_list(data.get("drama_atom_pack_refs")),
        "appraisals": _as_ref_list(data.get("appraisal_pack_refs")),
    }
    world = WorldState(
        grid=grid,
        player=player,
        agents=agents,
        objects=objects,
        scenario_id=str(data.get("scenario_id") or scenario_path.stem),
        scenario_title=str(data.get("title") or data.get("scenario_id") or scenario_path.stem),
        setting_summary=str(setting.get("summary") or data.get("setting_summary") or data.get("summary") or ""),
        tone=dict(data.get("tone") or {}),
        themes=list(data.get("themes") or data.get("drama_model", {}).get("themes") or []),
        art_pack=str(data.get("art_pack") or "island_ruins"),
        dialogue_templates=_load_dialogue_templates(base_dir, data),
        scripted_moments=_load_director_moments(base_dir, data),
        storylet_specs=_load_storylet_pack_entries(base_dir, data),
        drama_atoms=_load_drama_atom_entries(base_dir, data),
        appraisal_rules=_load_appraisal_rule_entries(base_dir, data),
        pack_refs=pack_refs,
        pressure_tag_deltas=_float_delta_table((data.get("pressure_model") or {}).get("tag_deltas") if isinstance(data.get("pressure_model"), dict) else {}),
        pressure_event_deltas=_float_delta_table((data.get("pressure_model") or {}).get("event_deltas") if isinstance(data.get("pressure_model"), dict) else {}),
    )
    for event in data.get("opening_events", []):
        world.log(event.get("event_type", "opening"), event["content"], source="scenario", salience=event.get("salience", 7), tags=event.get("tags", []))
    initialise_world_relationships(world)
    return world


def _merged_agent_card(base_dir: Path, scenario_agent: dict[str, Any]) -> dict[str, Any]:
    card_id = str(scenario_agent.get("id") or scenario_agent.get("character_id") or "")
    card_path = _data_ref_path(base_dir, "agents", str(scenario_agent.get("ref") or card_id))
    if not card_path.exists():
        return dict(scenario_agent)
    card = json.loads(card_path.read_text(encoding="utf-8"))
    merged = dict(card)
    for key, value in _flatten_overrides(scenario_agent).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            nested = dict(merged[key])
            nested.update(value)
            merged[key] = nested
        else:
            merged[key] = value
    return merged


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_map_data(base_dir: Path, data: dict[str, Any]) -> dict[str, Any]:
    if isinstance(data.get("map"), dict) and data["map"].get("rows"):
        return dict(data["map"])
    map_ref = str(data.get("map_ref") or "")
    if not map_ref:
        raise KeyError("Scenario must define either map.rows or map_ref.")
    path = _data_ref_path(base_dir, "maps", map_ref)
    map_data = _load_json(path)
    if isinstance(map_data.get("map"), dict):
        return dict(map_data["map"])
    return map_data


def _load_agent_entries(base_dir: Path, data: dict[str, Any]) -> list[dict[str, Any]]:
    inline = data.get("agents")
    if isinstance(inline, list) and inline:
        return [dict(item) for item in inline if isinstance(item, dict)]
    entries: list[dict[str, Any]] = []
    for item in _as_list(data.get("character_refs")):
        if isinstance(item, str):
            entries.append({"id": item})
        elif isinstance(item, dict):
            entries.append(_flatten_overrides(item))
    return entries


def _load_object_entries(base_dir: Path, data: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for ref in _as_ref_list(data.get("object_pack_refs")):
        path = _data_ref_path(base_dir, "objects", ref)
        entries.extend(_object_entries_from_pack(_load_json(path)))
    inline = data.get("objects")
    if isinstance(inline, list):
        entries.extend(dict(item) for item in inline if isinstance(item, dict))
    return entries


def _object_entries_from_pack(pack: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(pack.get("objects"), list):
        return [dict(item) for item in pack["objects"] if isinstance(item, dict)]
    templates = pack.get("templates")
    instances = pack.get("instances")
    if not isinstance(templates, dict) or not isinstance(instances, list):
        return []
    result: list[dict[str, Any]] = []
    for instance in instances:
        if not isinstance(instance, dict):
            continue
        template_id = str(instance.get("template_id") or instance.get("template") or "")
        template = templates.get(template_id)
        if not isinstance(template, dict):
            continue
        merged = _deep_merge(dict(template), dict(instance))
        merged.setdefault("kind", template_id)
        merged.pop("template_id", None)
        merged.pop("template", None)
        result.append(merged)
    return result


def _world_object_from_dict(item: dict[str, Any]) -> WorldObject:
    raw_interactions = item.get("interactions", [])
    if isinstance(raw_interactions, dict):
        interaction_ids = list(raw_interactions.keys())
        interaction_defs = {str(key): dict(value) for key, value in raw_interactions.items() if isinstance(value, dict)}
    else:
        interaction_ids = list(raw_interactions)
        interaction_defs = {str(key): dict(value) for key, value in dict(item.get("interaction_defs") or {}).items() if isinstance(value, dict)}
    return WorldObject(
        id=str(item["id"]),
        name=str(item["name"]),
        kind=str(item["kind"]),
        position=_pos(item["position"]),
        interactions=interaction_ids,
        tags=list(item.get("tags", [])),
        aliases=list(item.get("aliases", [])),
        object_type=str(item.get("object_type") or item.get("type") or "object"),
        sprite=str(item.get("sprite") or ""),
        properties=dict(item.get("properties", {})),
        render=dict(item.get("render", {})),
        interaction_defs=interaction_defs,
        state=dict(item.get("state", {})),
        capability_accepts=list(item.get("capability_accepts") or item.get("accepts") or []),
        capability_effects=dict(item.get("capability_effects", {})),
    )


def _load_storylet_pack_entries(base_dir: Path, data: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for ref in _as_ref_list(data.get("storylet_pack_refs")):
        raw = json.loads(_data_ref_path(base_dir, "storylets", ref).read_text(encoding="utf-8"))
        if isinstance(raw, list):
            entries.extend(dict(item) for item in raw if isinstance(item, dict))
        elif isinstance(raw, dict):
            entries.extend(dict(item) for item in raw.get("storylets", []) if isinstance(item, dict))
    inline = data.get("storylets")
    if isinstance(inline, list):
        entries.extend(dict(item) for item in inline if isinstance(item, dict))
    return entries


def _load_drama_atom_entries(base_dir: Path, data: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for ref in _as_ref_list(data.get("drama_atom_pack_refs")):
        raw = json.loads(_data_ref_path(base_dir, "drama_atoms", ref).read_text(encoding="utf-8"))
        if isinstance(raw, list):
            entries.extend(dict(item) for item in raw if isinstance(item, dict))
        elif isinstance(raw, dict):
            entries.extend(dict(item) for item in raw.get("drama_atoms", []) if isinstance(item, dict))
    inline = data.get("drama_atoms")
    if isinstance(inline, list):
        entries.extend(dict(item) for item in inline if isinstance(item, dict))
    return entries


def _load_appraisal_rule_entries(base_dir: Path, data: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for ref in _as_ref_list(data.get("appraisal_pack_refs")):
        raw = json.loads(_data_ref_path(base_dir, "appraisals", ref).read_text(encoding="utf-8"))
        if isinstance(raw, list):
            entries.extend(dict(item) for item in raw if isinstance(item, dict))
        elif isinstance(raw, dict):
            entries.extend(dict(item) for item in raw.get("appraisals", raw.get("rules", [])) if isinstance(item, dict))
    inline = data.get("appraisal_rules")
    if isinstance(inline, list):
        entries.extend(dict(item) for item in inline if isinstance(item, dict))
    return entries


def _load_dialogue_templates(base_dir: Path, data: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for ref in _as_ref_list(data.get("dialogue_pack_refs")):
        path = _data_ref_path(base_dir, "dialogue", ref)
        raw = _load_json(path)
        source = raw.get("dialogue_templates") if isinstance(raw.get("dialogue_templates"), dict) else raw
        if isinstance(source, dict):
            merged = _deep_merge(merged, source)
    if isinstance(data.get("dialogue_templates"), dict):
        merged = _deep_merge(merged, dict(data["dialogue_templates"]))
    return merged


def _load_director_moments(base_dir: Path, data: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for ref in _as_ref_list(data.get("director_moment_pack_refs")):
        path = _data_ref_path(base_dir, "director_moments", ref)
        raw = _load_json(path)
        source = raw.get("scripted_moments") if isinstance(raw.get("scripted_moments"), dict) else raw.get("moments", raw)
        if isinstance(source, dict):
            merged = _deep_merge(merged, source)
    if isinstance(data.get("scripted_moments"), dict):
        merged = _deep_merge(merged, dict(data["scripted_moments"]))
    return merged


def _data_ref_path(base_dir: Path, folder: str, ref: str) -> Path:
    ref_path = Path(ref)
    if ref_path.suffix:
        return ref_path if ref_path.is_absolute() else base_dir / "data" / folder / ref_path
    return base_dir / "data" / folder / f"{ref}.json"


def _flatten_overrides(entry: dict[str, Any]) -> dict[str, Any]:
    result = dict(entry)
    overrides = result.pop("overrides", None)
    if isinstance(overrides, dict):
        result = _deep_merge(result, overrides)
    if "ref" in result and "id" not in result:
        result["id"] = result["ref"]
    return result


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(dict(result[key]), value)
        else:
            result[key] = value
    return result


def _as_ref_list(value: Any) -> list[str]:
    return [str(item) for item in _as_list(value) if str(item)]


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _float_delta_table(raw: Any) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for key, value in dict(raw or {}).items():
        if isinstance(value, dict):
            result[str(key)] = {str(axis): float(delta) for axis, delta in value.items()}
    return result

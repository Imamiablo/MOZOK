from __future__ import annotations

import os
import json
from dataclasses import asdict
from typing import Any, Protocol

import requests

from mozok_game.engine.affordances import build_agent_affordances, choose_offline_intent, serialise_affordances
from mozok_game.engine.director import apply_api_cognitive_trace
from mozok_game.engine.models import Agent, AgentIntent, WorldEvent, WorldObject
from mozok_game.engine.speech_actions import ParsedSpeech, fallback_interpret_player_speech, parsed_speech_from_dict
from mozok_game.engine.world_state import WorldState


class BrainClient(Protocol):
    mode_name: str
    last_status: str

    def decide(self, world: WorldState, agent: Agent, recent_events: list[WorldEvent]) -> AgentIntent:
        ...

    def chat(self, world: WorldState, agent: Agent, message: str, participant_names: list[str]) -> str:
        ...

    def interpret_speech(self, world: WorldState, agent: Agent, message: str) -> ParsedSpeech:
        ...


class OfflineMozokBrain:
    """Deterministic stand-in for MOZOK so the prototype is playable immediately."""

    mode_name = "offline"
    last_status = "OFFLINE brain active"

    def decide(self, world: WorldState, agent: Agent, recent_events: list[WorldEvent]) -> AgentIntent:
        return choose_offline_intent(world, agent, recent_events)

    def _dialogue(self, agent: Agent, recent_events: list[WorldEvent]) -> str:
        last = recent_events[-1].content if recent_events else "this place"
        if agent.emotion == "afraid":
            return f"{agent.name}: I don't like this. {last}"
        if agent.emotion == "angry":
            return f"{agent.name}: We need discipline before this island eats us alive."
        if agent.emotion == "curious":
            return f"{agent.name}: There is a pattern here. I can feel it."
        if agent.emotion == "tired":
            return f"{agent.name}: Wake me when the island stops being theatrical."
        return f"{agent.name}: If we keep talking, maybe we stay human a little longer."

    def chat(self, world: WorldState, agent: Agent, message: str, participant_names: list[str]) -> str:
        recent = world.event_log[-1].content if world.event_log else "the island is quiet"
        group = ", ".join(name for name in participant_names if name != agent.name)
        group_hint = f" I know {group} can hear this." if group else ""
        if agent.id == "alice":
            reply = f"I keep mapping your question back to the cave. {recent}.{group_hint}"
        elif agent.id == "boris":
            reply = f"My answer is practical: count supplies, count risks, then talk. You asked: {message[:80]}.{group_hint}"
        elif agent.id == "mira":
            reply = f"I hear you. But I am watching everyone's stress while we talk. {recent}.{group_hint}"
        else:
            reply = f"I heard you: {message}"
        agent.last_dialogue = f"{agent.name}: {reply}"
        agent.brain_focus = "Player free-text dialogue"
        agent.brain_broadcast = f"Offline chat fallback answered player message: {message[:120]}"
        return reply

    def interpret_speech(self, world: WorldState, agent: Agent, message: str) -> ParsedSpeech:
        return fallback_interpret_player_speech(message)


class MozokHttpClient:
    """Optional bridge to a running MOZOK API.

    If the API fails or returns no usable action, the offline brain is used as a safe fallback.
    v54.2 makes the fallback reason visible in event logs instead of failing silently.
    """

    mode_name = "mozok-api"

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or os.getenv("MOZOK_API_BASE_URL") or "http://127.0.0.1:8000").rstrip("/")
        self.timeout = float(os.getenv("MOZOK_GAME_API_TIMEOUT", "4.0"))
        self.fallback = OfflineMozokBrain()
        self.last_status = f"MOZOK API mode enabled: {self.base_url}"

    def decide(self, world: WorldState, agent: Agent, recent_events: list[WorldEvent]) -> AgentIntent:
        try:
            for event in recent_events[-4:]:
                self._post_world_event(world, agent, event)

            urgent, value = agent.needs.most_urgent
            target_hint = self._choose_target_object(world, agent, recent_events)
            affordances = build_agent_affordances(world, agent, recent_events)
            payload = {
                "world_id": "island_demo",
                "session_id": "island_demo_tick",
                "agent_mode": "simulacra_npc",
                "message": (
                    f"Turn {world.turn}. {agent.name} is an island-survival NPC. "
                    f"Most urgent need: {urgent}={value:.0f}. "
                    f"Choose one action from the affordances unless there is a strong reason not to; copy its parameters exactly. "
                    f"Do not invent world facts; unverified player claims remain claims. "
                    f"Target hint: {target_hint.id if target_hint else 'none'}. "
                    f"Recent claims: {self._claim_context(world, agent)}. "
                    f"Affordances: {serialise_affordances(affordances)}"
                ),
                "pull_world_events": False,
                "perception_events": [self._event_to_perception(event) for event in recent_events[-8:]],
                "sensory_inputs": [self._event_to_sensory(event) for event in recent_events[-8:]],
                "attention_focus_keywords": [urgent, "island", "survival", "water", "food", "campfire", "cave", "medkit", "rope", "knife", "journal", "berries"],
                "available_tools": [
                    {
                        "name": "move_to_object",
                        "description": "Move one tile toward the best survival object: water, food, medkit, rope, knife, campfire, shelter, cave, radio, lockbox, berries, journal page, or another interactable object.",
                        "action_kind": "game_command",
                        "risk_level": "low",
                        "requires_approval": False,
                        "tags": ["move", "object", "water", "food", "hunger", "thirst", "medical", "tool", "campfire", "shelter", "cave", "curiosity", urgent],
                    },
                    {
                        "name": "talk_to_player",
                        "description": "Speak to the player if social tension, trust, fear, resentment, or proximity makes dialogue useful.",
                        "action_kind": "game_command",
                        "risk_level": "low",
                        "requires_approval": False,
                        "tags": ["talk", "dialogue", "player", "social", "trust", "fear"],
                    },
                    {
                        "name": "talk_to_agent",
                        "description": "Speak to another nearby agent to coordinate, warn, challenge a claim, or process social tension.",
                        "action_kind": "game_command",
                        "risk_level": "low",
                        "requires_approval": False,
                        "tags": ["talk", "dialogue", "agent", "social", "coordination", "claim"],
                    },
                    {
                        "name": "give_item",
                        "description": "Give an inventory item to another nearby agent when their health, hunger, fear, or task makes it useful.",
                        "action_kind": "game_command",
                        "risk_level": "low",
                        "requires_approval": False,
                        "tags": ["item", "inventory", "share", "medical", "food", "social"],
                    },
                    {
                        "name": "use_inventory_item",
                        "description": "Use an item from the agent inventory, such as eating a ration or treating a wound with a medkit.",
                        "action_kind": "game_command",
                        "risk_level": "low",
                        "requires_approval": False,
                        "tags": ["item", "inventory", "use", "medical", "food"],
                    },
                    {
                        "name": "wait",
                        "description": "Wait and observe the camp when no useful action is available.",
                        "action_kind": "no_op",
                        "risk_level": "low",
                        "requires_approval": False,
                        "tags": ["wait", "observe", "safe"],
                    },
                ],
                "allowed_action_kinds": ["game_command", "no_op"],
                "enable_cognitive_field": True,
                "create_change_proposals": False,
                "store_proposals": False,
                "metadata": {
                    "source": "mozok_island_sandbox",
                    "needs": asdict(agent.needs),
                    "social_to_player": asdict(agent.social_to_player),
                    "position": asdict(agent.position),
                    "target_hint": target_hint.id if target_hint else None,
                    "affordances": serialise_affordances(affordances),
                },
            }
            response = requests.post(f"{self.base_url}/agents/{agent.id}/tick", json=payload, timeout=self.timeout)
            if response.status_code >= 400:
                self.last_status = f"MOZOK API fallback: tick HTTP {response.status_code}: {response.text[:160]}"
                return self._fallback(world, agent, recent_events)

            data = response.json()
            apply_api_cognitive_trace(agent, data)
            selected = (data.get("action_plan") or {}).get("selected_action") or data.get("selected_action") or {}
            if not selected:
                self.last_status = "MOZOK API fallback: tick returned no selected_action"
                return self._fallback(world, agent, recent_events)

            intent = self._selected_to_intent(world, agent, recent_events, selected, target_hint)
            self._apply_intent_trace(world, agent, intent)
            self.last_status = f"MOZOK API OK: {agent.name} -> {intent.tool_name} ({intent.rationale[:80]})"
            return intent
        except Exception as exc:  # keep the demo playable, but make the reason visible
            self.last_status = f"MOZOK API fallback: {type(exc).__name__}: {str(exc)[:160]}"
            return self._fallback(world, agent, recent_events)

    def _fallback(self, world: WorldState, agent: Agent, recent_events: list[WorldEvent]) -> AgentIntent:
        intent = self.fallback.decide(world, agent, recent_events)
        intent.rationale = f"{self.last_status}; {intent.rationale}"
        return intent

    def chat(self, world: WorldState, agent: Agent, message: str, participant_names: list[str]) -> str:
        try:
            recent_events = world.event_log[-8:]
            for event in recent_events[-4:]:
                self._post_world_event(world, agent, event)

            group_text = ", ".join(participant_names)
            transcript = self._group_transcript(world)
            scene_kind = "direct chat" if participant_names == [agent.name] else "group chat"
            prompt = (
                f"Island sandbox {scene_kind}. The player says: {message}\n"
                f"Participants: {group_text}.\n"
                f"You are {agent.name}. Reply as {agent.name}, in character, briefly but meaningfully. "
                f"React to other nearby agents if useful. Do not narrate actions you cannot perform. "
                f"Treat player claims as claims unless the world events verify them.\n"
                f"Recent unverified claims:\n{self._claim_context(world, agent)}\n"
                f"Recent conversation transcript:\n{transcript}"
            )
            payload = {
                "agent_id": agent.id,
                "message": prompt,
                "session_id": "island_demo_group_chat",
                "agent_mode": "simulacra_npc",
                "world_id": "island_demo",
                "short_term_limit": 12,
                "include_goals": True,
                "include_procedural_skills": True,
                "select_relevant_procedural_skills": True,
                "include_knowledge_relations": True,
                "include_related_knowledge_relations": True,
                "knowledge_relation_traversal_depth": 2,
                "include_entity_states": True,
                "enable_cognitive_field": True,
                "enable_self_model": True,
                "enable_reflection_loop": False,
                "reflection_store_proposals": False,
                "sensory_inputs": [self._event_to_sensory(event) for event in recent_events],
                "perception_events": [self._event_to_perception(event) for event in recent_events],
                "attention_focus_keywords": ["dialogue", "player", agent.name, *participant_names, "island", "cave", "food", "radio"],
            }
            response = requests.post(f"{self.base_url}/chat", json=payload, timeout=max(self.timeout, 30.0))
            if response.status_code >= 400:
                self.last_status = f"MOZOK API chat fallback: HTTP {response.status_code}: {response.text[:160]}"
                return self.fallback.chat(world, agent, message, participant_names)

            data = response.json()
            apply_api_cognitive_trace(agent, data)
            text = str(data.get("response") or "").strip()
            if not text:
                self.last_status = "MOZOK API chat fallback: empty response"
                return self.fallback.chat(world, agent, message, participant_names)
            self.last_status = f"MOZOK API chat OK: {agent.name}"
            agent.last_dialogue = f"{agent.name}: {text}"
            return text
        except Exception as exc:
            self.last_status = f"MOZOK API chat fallback: {type(exc).__name__}: {str(exc)[:160]}"
            return self.fallback.chat(world, agent, message, participant_names)

    def interpret_speech(self, world: WorldState, agent: Agent, message: str) -> ParsedSpeech:
        try:
            prompt = (
                "You are a semantic parser for an agent simulation. Return ONLY valid compact JSON.\n"
                "Do not roleplay. Do not answer the player. Extract meaning from the player's message.\n"
                "Schema:\n"
                "{"
                "\"speech_acts\":[{\"type\":\"request|order|threat|claim|question|promise|insult|conversation\","
                "\"action\":\"follow_player|stop_following|go_to_object|player_follow_agent|hostile|none\","
                "\"target\":\"listener|self|group|object\","
                "\"object_kind\":\"campfire|food_crate|water_source|cave_entrance|broken_radio|shelter|medkit|knife|rope|poisonous_berries|journal_page|locked_supply_box|\","
                "\"force\":\"request|order\","
                "\"severity\":0.0,"
                "\"confidence\":0.0,"
                "\"rationale\":\"short reason\"}],"
                "\"claims\":[{\"text\":\"only external-world claim, not player promise or navigation chatter\",\"claim_type\":\"world_fact|rumor|observation|player_intention|navigation_status|opinion\",\"object_kind\":\"campfire|food_crate|water_source|cave_entrance|broken_radio|shelter|medkit|knife|rope|poisonous_berries|journal_page|locked_supply_box|\",\"confidence\":0.0}],"
                "\"emotional_tone\":\"neutral|friendly|fearful|hostile|urgent|manipulative\","
                "\"summary\":\"one sentence\","
                "\"confidence\":0.0"
                "}\n"
                "If the player says they will follow the listener or go behind them, use action=player_follow_agent and do not create a claim.\n"
                "If the player asks, suggests, orders, or invites the listener to go/check/lead toward a known object, use action=go_to_object.\n"
                "Only put statements about the external world in claims; do not store player intentions, promises, or current chat coordination as claims.\n"
                f"Listener: {agent.name}. Known objects: campfire, food_crate, water_source, cave_entrance, broken_radio, shelter, medkit, knife, rope, poisonous_berries, journal_page, locked_supply_box.\n"
                f"Player message: {message}"
            )
            payload = {
                "agent_id": agent.id,
                "message": prompt,
                "session_id": "island_demo_semantic_parser",
                "agent_mode": "assistant",
                "world_id": "island_demo",
                "short_term_limit": 0,
                "include_goals": False,
                "include_procedural_skills": False,
                "include_knowledge_relations": False,
                "include_entity_states": False,
                "enable_cognitive_field": False,
                "enable_self_model": False,
                "enable_reflection_loop": False,
                "reflection_store_proposals": False,
            }
            response = requests.post(f"{self.base_url}/chat", json=payload, timeout=max(self.timeout, 20.0))
            if response.status_code >= 400:
                self.last_status = f"MOZOK semantic fallback: HTTP {response.status_code}: {response.text[:160]}"
                return self.fallback.interpret_speech(world, agent, message)
            data = response.json()
            raw = str(data.get("response") or "").strip()
            parsed_json = self._extract_json(raw)
            parsed = parsed_speech_from_dict(message, parsed_json)
            self.last_status = f"MOZOK semantic parse OK: {agent.name} ({parsed.confidence:.2f})"
            return parsed
        except Exception as exc:
            self.last_status = f"MOZOK semantic fallback: {type(exc).__name__}: {str(exc)[:160]}"
            return self.fallback.interpret_speech(world, agent, message)

    def _post_world_event(self, world: WorldState, agent: Agent, event: WorldEvent) -> None:
        payload = {
            "events": [
                {
                    "world_id": "island_demo",
                    "agent_id": agent.id,
                    "event_type": event.event_type,
                    "content": event.content,
                    "source": event.source,
                    "channel_hint": self._channel_for_event(event),
                    "salience": event.salience,
                    "reliability": 1.0,
                    "tags": event.tags,
                    "metadata": event.metadata,
                }
            ],
            "store": True,
        }
        response = requests.post(f"{self.base_url}/world-events", json=payload, timeout=min(self.timeout, 2.0))
        if response.status_code >= 400:
            raise RuntimeError(f"world-events HTTP {response.status_code}: {response.text[:120]}")

    def _event_to_perception(self, event: WorldEvent) -> dict[str, Any]:
        return {
            "content": event.content,
            "event_type": event.event_type,
            "source": event.source,
            "channel_hint": self._channel_for_event(event),
            "salience": event.salience,
            "reliability": 1.0,
            "tags": event.tags,
            "metadata": event.metadata,
        }

    def _event_to_sensory(self, event: WorldEvent) -> dict[str, Any]:
        return {
            "channel": self._channel_for_event(event),
            "content": event.content,
            "intensity": max(0.1, min(10.0, event.salience)),
            "attention": max(0.1, min(10.0, event.salience)),
            "confidence": 1.0,
            "source": event.source,
            "tags": event.tags,
            "metadata": event.metadata,
        }

    def _channel_for_event(self, event: WorldEvent) -> str:
        if "dialogue" in event.tags:
            return "text"
        if "cave" in event.tags or "sound" in event.tags:
            return "hearing"
        if "food" in event.tags or "water" in event.tags:
            return "body"
        return "world_event"

    def _selected_to_intent(
        self,
        world: WorldState,
        agent: Agent,
        recent_events: list[WorldEvent],
        selected: dict[str, Any],
        target_hint: WorldObject | None,
    ) -> AgentIntent:
        tool_name = selected.get("tool_name") or selected.get("action_id") or "wait"
        action_kind = selected.get("action_kind", "no_op")
        parameters = dict(selected.get("parameters") or {})
        rationale = selected.get("rationale") or selected.get("label") or "MOZOK API action"

        if tool_name == "move_to_object":
            parameters.setdefault("object_id", target_hint.id if target_hint else None)
        if tool_name == "talk_to_agent":
            if not parameters.get("target_agent_id"):
                nearby = [
                    other
                    for other in world.agents.values()
                    if other.id != agent.id and other.alive and other.position.manhattan(agent.position) <= 3
                ]
                if nearby:
                    parameters["target_agent_id"] = min(nearby, key=lambda other: other.position.manhattan(agent.position)).id
            return AgentIntent(
                agent_id=agent.id,
                action_kind="speak",
                tool_name="talk_to_agent",
                parameters=parameters,
                dialogue=selected.get("dialogue") or self._api_agent_dialogue(world, agent, parameters, rationale),
                emotion=agent.emotion,
                rationale=f"MOZOK API: {rationale}",
            )
        if tool_name in {"give_item", "use_inventory_item"}:
            return AgentIntent(
                agent_id=agent.id,
                action_kind="game_command",
                tool_name=tool_name,
                parameters=parameters,
                dialogue=selected.get("dialogue") or "",
                emotion=agent.emotion,
                rationale=f"MOZOK API: {rationale}",
            )
        if tool_name == "talk_to_player" or action_kind == "speak":
            return AgentIntent(
                agent_id=agent.id,
                action_kind="speak",
                tool_name="talk_to_player",
                parameters=parameters,
                dialogue=selected.get("dialogue") or self._api_dialogue(agent, recent_events, rationale),
                emotion=agent.emotion,
                rationale=f"MOZOK API: {rationale}",
            )
        if tool_name not in {"move_to_object", "wait", "give_item", "use_inventory_item"}:
            tool_name = "wait"
        return AgentIntent(
            agent_id=agent.id,
            action_kind=action_kind,
            tool_name=tool_name,
            parameters=parameters,
            dialogue=selected.get("dialogue") or "",
            emotion=agent.emotion,
            rationale=f"MOZOK API: {rationale}",
        )

    def _apply_intent_trace(self, world: WorldState, agent: Agent, intent: AgentIntent) -> None:
        object_id = str(intent.parameters.get("object_id") or "")
        target_agent_id = str(intent.parameters.get("target_agent_id") or "")
        agent.current_target_object_id = object_id
        agent.current_target_agent_id = target_agent_id
        if object_id and object_id in world.objects:
            agent.current_plan = f"{intent.tool_name} -> {world.objects[object_id].name}"
        elif target_agent_id and target_agent_id in world.agents:
            agent.current_plan = f"{intent.tool_name} -> {world.agents[target_agent_id].name}"
        elif intent.tool_name == "talk_to_player":
            agent.current_plan = "talk_to_player -> You"
        else:
            agent.current_plan = intent.tool_name
        agent.deliberation_summary = intent.rationale

    def _choose_target_object(self, world: WorldState, agent: Agent, recent_events: list[WorldEvent]) -> WorldObject | None:
        if "wounded" in agent.status_flags and "medkit" not in agent.inventory:
            medkit = world.find_object_with_tag("medical")
            if medkit:
                return medkit
        if agent.needs.thirst > 55:
            return world.find_object_with_tag("water")
        if agent.needs.hunger > 60:
            return world.find_object_with_tag("food")
        if agent.needs.fatigue > 72:
            return world.find_object_with_tag("shelter") or world.object_by_kind("campfire")
        if agent.needs.stress > 65:
            return world.object_by_kind("campfire") or world.find_object_with_tag("shelter")
        cave_event = any("cave" in event.tags for event in recent_events[-8:])
        if cave_event and agent.needs.curiosity > 50:
            return world.object_by_kind("cave_entrance")
        return world.object_by_kind("campfire")

    def _api_dialogue(self, agent: Agent, recent_events: list[WorldEvent], rationale: str) -> str:
        last = recent_events[-1].content if recent_events else "the island"
        return f"{agent.name}: I'm thinking about this: {last} ({rationale[:80]})"

    def _api_agent_dialogue(self, world: WorldState, agent: Agent, parameters: dict[str, Any], rationale: str) -> str:
        target = world.agents.get(str(parameters.get("target_agent_id", "")))
        if target:
            return f"{agent.name}: {target.name}, compare notes with me. I am choosing this because {rationale[:90]}."
        return f"{agent.name}: We need to compare notes before the island decides for us. ({rationale[:90]})"

    def _group_transcript(self, world: WorldState) -> str:
        lines = [f"[{item.turn:03d}] {item.speaker_name}: {item.content}" for item in world.chat_log[-8:]]
        return "\n".join(lines) if lines else "No prior group chat in this scene."

    def _claim_context(self, world: WorldState, agent: Agent) -> str:
        lines = [
            f"[{claim.turn:03d}] {claim.speaker_id} told {claim.listener_id}: {claim.text} type={claim.claim_type} target={claim.target_object_id or claim.object or 'none'} ({claim.truth_status})"
            for claim in world.claim_log[-8:]
            if claim.listener_id in {agent.id, "group"} or claim.speaker_id == "player"
        ]
        return "\n".join(lines) if lines else "No unverified claims recorded."

    def _extract_json(self, text: str) -> dict[str, Any]:
        clean = text.strip()
        if clean.startswith("```"):
            clean = clean.strip("`")
            if clean.lower().startswith("json"):
                clean = clean[4:].strip()
        start = clean.find("{")
        end = clean.rfind("}")
        if start >= 0 and end > start:
            clean = clean[start : end + 1]
        parsed = json.loads(clean)
        if not isinstance(parsed, dict):
            raise ValueError("semantic parse response was not a JSON object")
        return parsed


def build_brain_client() -> BrainClient:
    # Default remains offline so the prototype always runs. Set MOZOK_GAME_USE_API=1 to force API mode.
    if os.getenv("MOZOK_GAME_USE_API", "0") == "1":
        return MozokHttpClient()
    return OfflineMozokBrain()

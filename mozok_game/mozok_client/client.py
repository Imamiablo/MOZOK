from __future__ import annotations

import os
import json
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from copy import deepcopy
from typing import Any, Protocol

import requests

from mozok_game.engine.affordances import build_agent_affordances, choose_offline_intent, serialise_affordances
from mozok_game.engine.director import apply_api_cognitive_trace
from mozok_game.engine.model_settings import load_game_model_settings
from mozok_game.engine.models import Agent, AgentIntent, WorldEvent, WorldObject
from mozok_game.engine.performance import load_performance_settings
from mozok_game.engine.scene_context import build_scene_context
from mozok_game.engine.scene_proposal import scene_proposal_from_dict, scene_proposal_prompt_contract, validate_scene_proposal
from mozok_game.engine.scene_validation import grounding_prompt, validate_agent_dialogue
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
            return f"{agent.name}: We need discipline before the situation pulls us apart."
        if agent.emotion == "curious":
            return f"{agent.name}: There is a pattern here. I can feel it."
        if agent.emotion == "tired":
            return f"{agent.name}: Wake me when the situation stops being theatrical."
        return f"{agent.name}: If we keep talking, maybe we stay human a little longer."

    def chat(self, world: WorldState, agent: Agent, message: str, participant_names: list[str]) -> str:
        configured = world.dialogue_templates.get("direct_chat") if isinstance(world.dialogue_templates.get("direct_chat"), dict) else {}
        recent = world.event_log[-1].content if world.event_log else "the scene is quiet"
        group = ", ".join(name for name in participant_names if name != agent.name)
        group_hint = f" I know {group} can hear this." if group else ""
        if agent.traits.get("curiosity", 0.0) > 0.65:
            reply = str(configured.get("curiosity_mystery") or "{name}: I keep mapping your question back to the strongest mystery here. {recent}.").format(name=agent.name, recent=recent).removeprefix(f"{agent.name}: ") + group_hint
        elif agent.traits.get("dominance", 0.0) > 0.65:
            reply = str(configured.get("dominance_food") or "{name}: My answer is practical: count resources, count risks, then talk.").format(name=agent.name, recent=recent).removeprefix(f"{agent.name}: ") + f" You asked: {message[:80]}.{group_hint}"
        elif agent.traits.get("empathy", 0.0) > 0.65:
            reply = str(configured.get("empathy_danger") or "{name}: I hear you, and I am watching everyone's stress while we talk.").format(name=agent.name, recent=recent).removeprefix(f"{agent.name}: ") + group_hint
        else:
            reply = str(configured.get("default") or "{name}: I heard you: {message}").format(name=agent.name, message=message, recent=recent).removeprefix(f"{agent.name}: ")
        agent.last_dialogue = f"{agent.name}: {reply}"
        agent.brain_focus = "Player free-text dialogue"
        agent.brain_broadcast = f"Offline chat fallback answered player message: {message[:120]}"
        return reply

    def interpret_speech(self, world: WorldState, agent: Agent, message: str) -> ParsedSpeech:
        return fallback_interpret_player_speech(message, world)

    def weave_social_scene(self, world: WorldState, speaker: Agent, listener: Agent, motive: dict[str, Any]) -> str:
        return ""

    def voice_agent_decision(self, world: WorldState, agent: Agent, parsed: ParsedSpeech, decision: Any) -> str:
        return ""


class MozokHttpClient:
    """Optional bridge to a running MOZOK API.

    If the API fails or returns no usable action, the offline brain is used as a safe fallback.
    v54.2 makes the fallback reason visible in event logs instead of failing silently.
    """

    mode_name = "mozok-api"

    def __init__(self, base_url: str | None = None, base_dir: Path | None = None) -> None:
        self.base_url = (base_url or os.getenv("MOZOK_API_BASE_URL") or "http://127.0.0.1:8000").rstrip("/")
        self.timeout = float(os.getenv("MOZOK_GAME_API_TIMEOUT", "4.0"))
        self.fallback = OfflineMozokBrain()
        self.last_status = f"MOZOK API mode enabled: {self.base_url}"
        self._posted_event_ids: set[str] = set()
        self.base_dir = base_dir or Path(__file__).resolve().parents[1]
        self.model_settings = load_game_model_settings(self.base_dir)
        self.performance = load_performance_settings()
        self._llm_tick_counts: dict[int, int] = {}
        self._last_llm_tick_turn: dict[str, int] = {}
        self._semantic_cache: dict[tuple[str, int, str, str], ParsedSpeech] = {}
        self._social_scene_turns: dict[str, int] = {}

    def reload_model_settings(self) -> None:
        self.model_settings = load_game_model_settings(self.base_dir)
        self.performance = load_performance_settings()

    def decide(self, world: WorldState, agent: Agent, recent_events: list[WorldEvent], force_api: bool = False) -> AgentIntent:
        if not force_api and not self._should_use_llm_tick(world, agent, recent_events):
            self.last_status = f"MOZOK API budget: local planner for {agent.name}"
            return self._fallback(world, agent, recent_events)
        try:
            recent_limit = max(1, self.performance.recent_event_limit)
            for event in recent_events[-recent_limit:]:
                self._post_world_event(world, agent, event)

            urgent, value = agent.needs.most_urgent
            target_hint = self._choose_target_object(world, agent, recent_events)
            affordances = build_agent_affordances(world, agent, recent_events)
            scene_context = build_scene_context(world, agent)
            known_object_context = self._known_object_context(world, agent=agent)
            attention_keywords = self._attention_keywords(world, urgent)
            payload = {
                "world_id": self._world_id(world),
                "session_id": self._session_id(world, "tick"),
                "agent_mode": "simulacra_npc",
                **self._model_hints("tick", "fast"),
                "message": (
                    f"Turn {world.turn}. {agent.name} is an NPC in scenario '{world.scenario_title}'. "
                    f"Setting: {world.setting_summary or 'No setting summary provided'}. "
                    f"Tone: {self._tone_context(world)}. Themes: {', '.join(world.themes) or 'none'}. "
                    f"Most urgent need: {urgent}={value:.0f}. "
                    f"Choose one action from the affordances unless there is a strong reason not to; copy its parameters exactly. "
                    f"Do not invent world facts; unverified player claims remain claims. "
                    f"Target hint: {target_hint.id if target_hint else 'none'}. "
                    f"Known objects and interactions: {known_object_context}. "
                    f"Recent claims: {self._claim_context(world, agent)}. "
                    f"Affordances: {serialise_affordances(affordances)}"
                ),
                "pull_world_events": False,
                "perception_events": [self._event_to_perception(event) for event in recent_events[-recent_limit:]],
                "sensory_inputs": [self._event_to_sensory(event) for event in recent_events[-recent_limit:]],
                "attention_focus_keywords": attention_keywords,
                "available_tools": [
                    {
                        "name": "move_to_object",
                        "description": "Move one tile toward an existing world object and optionally perform a listed interaction_id from the affordance parameters.",
                        "action_kind": "game_command",
                        "risk_level": "low",
                        "requires_approval": False,
                        "tags": ["move", "object", "interaction", urgent, *attention_keywords[:10]],
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
                        "name": "use_item_on_target",
                        "description": "Use an inventory item's capability on an existing world object. Parameters must include item_id, target_id, and primitive such as pry, anchor, inspect, test, cut, repair, or block.",
                        "action_kind": "game_command",
                        "risk_level": "medium",
                        "requires_approval": False,
                        "tags": ["item", "capability", "tool", "validated", "pry", "anchor", "inspect", "test"],
                    },
                    {
                        "name": "wait",
                        "description": "Wait and observe the scene when no useful action is available.",
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
                    "source": "mozok_sandbox",
                    "needs": asdict(agent.needs),
                    "social_to_player": asdict(agent.social_to_player),
                    "traits": dict(agent.traits),
                    "values": list(agent.values),
                    "fears": list(agent.fears),
                    "skills": list(agent.skills),
                    "voice": dict(agent.voice),
                    "position": asdict(agent.position),
                    "target_hint": target_hint.id if target_hint else None,
                    "affordances": serialise_affordances(affordances),
                    "authoritative_state": self._authoritative_state_context(world, agent, recent_events),
                    "known_objects": self._visible_object_records(world, agent=agent),
                    "scene_context": self._scene_context_payload(scene_context),
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
            recent_limit = max(1, self.performance.recent_event_limit)
            recent_events = world.event_log[-recent_limit:]
            for event in recent_events:
                self._post_world_event(world, agent, event)

            group_text = ", ".join(participant_names)
            transcript = self._group_transcript(world)
            known_object_context = self._known_object_context(world, agent=agent)
            scene_kind = "direct chat" if participant_names == [agent.name] else "group chat"
            scene_context = build_scene_context(world, agent).to_prompt_dict()
            scene_context_text = json.dumps(scene_context, ensure_ascii=False)[: self.performance.scene_context_chars]
            prompt = (
                f"Sandbox {scene_kind} in scenario '{world.scenario_title}'. Setting: {world.setting_summary or 'No setting summary provided'}.\n"
                f"The player says: {message}\n"
                f"Participants: {group_text}.\n"
                f"Known world objects/interactions: {known_object_context}.\n"
                f"Scene context JSON: {scene_context_text}\n"
                f"{grounding_prompt(world, agent)}\n"
                f"{scene_proposal_prompt_contract()}\n"
                f"You are {agent.name}. Reply as {agent.name}, in character, briefly but meaningfully. "
                f"React to other nearby agents if useful. Do not narrate actions you cannot perform. "
                f"Treat player claims as claims unless the world events verify them.\n"
                f"Recent unverified claims:\n{self._claim_context(world, agent)}\n"
                f"Recent conversation transcript:\n{transcript}"
            )
            payload = {
                "agent_id": agent.id,
                "message": prompt,
                "session_id": self._session_id(world, "group_chat"),
                "agent_mode": "simulacra_npc",
                "world_id": self._world_id(world),
                **self._model_hints("chat", "scene"),
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
                "attention_focus_keywords": ["dialogue", "player", agent.name, *participant_names, *self._attention_keywords(world, "")],
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
            proposal = self._try_scene_proposal(text, agent.id)
            if proposal is not None:
                proposal_result = validate_scene_proposal(world, agent, proposal)
                if proposal_result.text:
                    text = proposal_result.text
                if proposal_result.rejected_actions or proposal_result.rejected_physical_claims:
                    agent.brain_risk = "Scene validation: " + "; ".join([*proposal_result.rejected_actions, *proposal_result.rejected_physical_claims][:2])
                for claim in proposal_result.accepted_claims:
                    world.claim(
                        speaker_id=agent.id,
                        listener_id="player",
                        text=claim.text,
                        truth_status=claim.truth_status,
                        confidence=claim.confidence,
                        subject=claim.subject,
                        predicate=claim.predicate,
                        object=claim.object,
                        target_object_id=claim.target_object_id,
                    )
            validation = validate_agent_dialogue(world, agent, text)
            text = validation.text
            if validation.changed:
                agent.brain_risk = "Grounded dialogue rewrite: " + "; ".join(validation.rejected_physical_claims[:2])
            self.last_status = f"MOZOK API chat OK: {agent.name}"
            agent.last_dialogue = f"{agent.name}: {text}"
            return text
        except Exception as exc:
            self.last_status = f"MOZOK API chat fallback: {type(exc).__name__}: {str(exc)[:160]}"
            return self.fallback.chat(world, agent, message, participant_names)

    def interpret_speech(self, world: WorldState, agent: Agent, message: str) -> ParsedSpeech:
        cache_key = self._semantic_cache_key(world, message)
        if cache_key in self._semantic_cache:
            cached = deepcopy(self._semantic_cache[cache_key])
            self.last_status = f"MOZOK semantic cache: {agent.name}"
            return cached
        try:
            object_kinds = "|".join(self._known_object_kinds(world))
            known_object_context = self._known_object_context(world, agent=agent)
            prompt = (
                "You are a semantic parser for an agent simulation. Return ONLY valid compact JSON.\n"
                "Do not roleplay. Do not answer the player. Extract meaning from the player's message.\n"
                "Schema:\n"
                "{"
                "\"speech_acts\":[{\"type\":\"request|order|threat|claim|question|promise|insult|conversation\","
                "\"action\":\"follow_player|stop_following|go_to_object|player_follow_agent|hostile|none\","
                "\"target\":\"listener|self|group|object\","
                f"\"object_kind\":\"{object_kinds}|\","
                "\"target_object_id\":\"exact id from known_objects when clear\","
                "\"force\":\"request|order\","
                "\"severity\":0.0,"
                "\"confidence\":0.0,"
                "\"rationale\":\"short reason\"}],"
                f"\"claims\":[{{\"text\":\"only external-world claim, not player promise or navigation chatter\",\"claim_type\":\"world_fact|rumor|observation|player_intention|navigation_status|opinion\",\"object_kind\":\"{object_kinds}|\",\"target_object_id\":\"exact id if clear\",\"confidence\":0.0}}],"
                "\"emotional_tone\":\"neutral|friendly|fearful|hostile|urgent|manipulative\","
                "\"summary\":\"one sentence\","
                "\"confidence\":0.0"
                "}\n"
                "If the player says they will follow the listener or go behind them, use action=player_follow_agent and do not create a claim.\n"
                "If the player asks, suggests, orders, or invites the listener to go/check/lead toward a known object, use action=go_to_object.\n"
                "Only put statements about the external world in claims; do not store player intentions, promises, or current chat coordination as claims.\n"
                f"Listener: {agent.name}. known_objects: {known_object_context}.\n"
                f"Player message: {message}"
            )
            payload = {
                "agent_id": agent.id,
                "message": prompt,
                "session_id": self._session_id(world, "semantic_parser"),
                "agent_mode": "assistant",
                "world_id": self._world_id(world),
                **self._model_hints("semantic", "semantic"),
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
            self._remember_semantic_parse(cache_key, parsed)
            self.last_status = f"MOZOK semantic parse OK: {agent.name} ({parsed.confidence:.2f})"
            return parsed
        except Exception as exc:
            self.last_status = f"MOZOK semantic fallback: {type(exc).__name__}: {str(exc)[:160]}"
            return self.fallback.interpret_speech(world, agent, message)

    def weave_social_scene(self, world: WorldState, speaker: Agent, listener: Agent, motive: dict[str, Any]) -> str:
        if not self._should_weave_social_scene(world, speaker, listener, motive):
            return ""
        try:
            scene_context = build_scene_context(world, speaker).to_prompt_dict()
            scene_context_text = json.dumps(scene_context, ensure_ascii=False)[: self.performance.scene_context_chars]
            prompt = (
                "You are a grounded scene weaver for an agent simulation. Return ONLY compact JSON matching the SceneProposal contract.\n"
                f"Speaker: {speaker.name}. Listener: {listener.name}. Scenario: {world.scenario_title}.\n"
                f"Motive: {json.dumps(motive, ensure_ascii=False)}\n"
                f"Scene context: {scene_context_text}\n"
                f"{grounding_prompt(world, speaker)}\n"
                f"{scene_proposal_prompt_contract()}\n"
                "Write exactly one short in-character line from speaker to listener. No physical state changes unless requested_actions are legal."
            )
            payload = {
                "agent_id": speaker.id,
                "message": prompt,
                "session_id": self._session_id(world, "social_scene"),
                "agent_mode": "simulacra_npc",
                "world_id": self._world_id(world),
                **self._model_hints("social_scene", "scene"),
                "short_term_limit": 8,
                "include_goals": True,
                "include_procedural_skills": True,
                "include_knowledge_relations": True,
                "include_entity_states": True,
                "enable_cognitive_field": True,
                "enable_self_model": True,
                "enable_reflection_loop": False,
                "reflection_store_proposals": False,
                "attention_focus_keywords": ["dialogue", "social", speaker.name, listener.name, *self._attention_keywords(world, "")],
            }
            response = requests.post(f"{self.base_url}/chat", json=payload, timeout=max(self.timeout, 20.0))
            if response.status_code >= 400:
                self.last_status = f"MOZOK social scene fallback: HTTP {response.status_code}: {response.text[:160]}"
                return ""
            text = str(response.json().get("response") or "").strip()
            proposal = self._try_scene_proposal(text, speaker.id)
            if proposal is not None:
                result = validate_scene_proposal(world, speaker, proposal)
                if result.text:
                    self.last_status = f"MOZOK social scene OK: {speaker.name}"
                    return result.text.splitlines()[0].strip()
                if result.rejected_actions or result.rejected_physical_claims:
                    speaker.brain_risk = "Scene validation: " + "; ".join([*result.rejected_actions, *result.rejected_physical_claims][:2])
                    return ""
            validation = validate_agent_dialogue(world, speaker, text)
            if validation.changed:
                speaker.brain_risk = "Grounded dialogue rewrite: " + "; ".join(validation.rejected_physical_claims[:2])
            return validation.text.strip()
        except Exception as exc:
            self.last_status = f"MOZOK social scene fallback: {type(exc).__name__}: {str(exc)[:160]}"
            return ""

    def voice_agent_decision(self, world: WorldState, agent: Agent, parsed: ParsedSpeech, decision: Any) -> str:
        if not self._should_voice_decision(decision):
            return ""
        try:
            scene_context = build_scene_context(world, agent).to_prompt_dict()
            scene_context_text = json.dumps(scene_context, ensure_ascii=False)[: self.performance.scene_context_chars]
            prompt = (
                "You are voicing a structured NPC decision. Return ONLY SceneProposal JSON.\n"
                f"NPC: {agent.name}. Raw player message: {parsed.raw_text}\n"
                f"Parsed speech summary: {parsed.summary}. Tone: {parsed.tone}. Confidence: {parsed.confidence:.2f}\n"
                f"Decision: action={decision.action}, accepted={decision.accepted}, reason={decision.reason}, fallback_reply={decision.reply}\n"
                f"Scene context: {scene_context_text}\n"
                f"{grounding_prompt(world, agent)}\n"
                f"{scene_proposal_prompt_contract()}\n"
                "Write one concise in-character reply that preserves the decision and does not invent physical props or facts."
            )
            payload = {
                "agent_id": agent.id,
                "message": prompt,
                "session_id": self._session_id(world, "decision_voice"),
                "agent_mode": "simulacra_npc",
                "world_id": self._world_id(world),
                **self._model_hints("decision_voice", "scene"),
                "short_term_limit": 8,
                "include_goals": True,
                "include_procedural_skills": True,
                "include_knowledge_relations": True,
                "include_entity_states": True,
                "enable_cognitive_field": True,
                "enable_self_model": True,
                "enable_reflection_loop": False,
                "reflection_store_proposals": False,
            }
            response = requests.post(f"{self.base_url}/chat", json=payload, timeout=max(self.timeout, 20.0))
            if response.status_code >= 400:
                self.last_status = f"MOZOK decision voice fallback: HTTP {response.status_code}: {response.text[:160]}"
                return ""
            text = str(response.json().get("response") or "").strip()
            proposal = self._try_scene_proposal(text, agent.id)
            if proposal is not None:
                result = validate_scene_proposal(world, agent, proposal)
                if result.text:
                    return result.text.splitlines()[0].strip()
                return ""
            validation = validate_agent_dialogue(world, agent, text)
            return validation.text.strip()
        except Exception as exc:
            self.last_status = f"MOZOK decision voice fallback: {type(exc).__name__}: {str(exc)[:160]}"
            return ""

    def _try_scene_proposal(self, text: str, default_speaker_id: str):
        stripped = text.strip()
        if "{" not in stripped:
            return None
        try:
            data = self._extract_json(stripped)
            if not isinstance(data, dict) or not any(key in data for key in ("dialogue", "requested_actions", "claims")):
                return None
            return scene_proposal_from_dict(data, default_speaker_id=default_speaker_id)
        except Exception:
            return None

    def _should_use_llm_tick(self, world: WorldState, agent: Agent, recent_events: list[WorldEvent]) -> bool:
        budget = self.performance.max_llm_ticks_per_turn
        if budget <= 0:
            return False
        if world.turn not in self._llm_tick_counts:
            self._llm_tick_counts = {world.turn: 0}
        if self._llm_tick_counts.get(world.turn, 0) >= budget:
            return False

        critical = self._agent_has_critical_reason(world, agent, recent_events)
        salient = critical or world.selected_agent_id == agent.id or agent.position.manhattan(world.player.position) <= 1
        last_turn = self._last_llm_tick_turn.get(agent.id, -999)
        if not critical and world.turn - last_turn < self.performance.llm_tick_cooldown_turns:
            return False

        if not critical:
            agents = sorted((item for item in world.agents.values() if item.alive), key=lambda item: item.id)
            if agents:
                selected_agent = world.agents.get(world.selected_agent_id or "")
                selected_is_relevant = bool(selected_agent and selected_agent.alive and selected_agent.position.manhattan(world.player.position) <= 2)
                preferred_id = selected_agent.id if selected_is_relevant else agents[world.turn % len(agents)].id
                if not salient:
                    preferred_id = agents[world.turn % len(agents)].id
                if preferred_id != agent.id:
                    return False
            elif not salient:
                return False

        self._llm_tick_counts[world.turn] = self._llm_tick_counts.get(world.turn, 0) + 1
        self._last_llm_tick_turn[agent.id] = world.turn
        return True

    def _agent_has_critical_reason(self, world: WorldState, agent: Agent, recent_events: list[WorldEvent]) -> bool:
        if agent.active_commitment and agent.active_commitment.priority >= 75:
            return True
        urgent, value = agent.needs.most_urgent
        if value >= 82 or agent.health < 55:
            return True
        if agent.social_to_player.fear + agent.social_to_player.resentment >= 125:
            return True
        salient_tags = {"danger", "mystery", "scarcity", "conflict", "social_risk", "hostile_alarm", "injury", "medical"}
        for event in recent_events[-max(1, self.performance.recent_event_limit):]:
            if event.salience >= 8 and (agent.id in event.witness_ids or event.actor_id == agent.id or event.target_id == agent.id):
                return True
            if salient_tags & set(event.tags) and (not event.witness_ids or agent.id in event.witness_ids or agent.position.manhattan(world.player.position) <= 2):
                return True
        return False

    def _semantic_cache_key(self, world: WorldState, message: str) -> tuple[str, int, str, str]:
        object_signature = ",".join(sorted(f"{obj.id}:{obj.kind}:{'|'.join(obj.aliases[:3])}" for obj in world.objects.values()))
        return (self._world_id(world), world.turn, message.strip().lower(), object_signature)

    def _remember_semantic_parse(self, cache_key: tuple[str, int, str, str], parsed: ParsedSpeech) -> None:
        self._semantic_cache[cache_key] = deepcopy(parsed)
        if len(self._semantic_cache) > 80:
            self._semantic_cache = dict(list(self._semantic_cache.items())[-40:])

    def _should_weave_social_scene(self, world: WorldState, speaker: Agent, listener: Agent, motive: dict[str, Any]) -> bool:
        interval = self.performance.social_scene_llm_interval
        if interval <= 0:
            return False
        key = f"{speaker.id}:{listener.id}:{motive.get('kind') or motive.get('impulse') or motive.get('id') or 'social'}"
        last_turn = self._social_scene_turns.get(key, -999)
        if world.turn - last_turn < interval:
            return False
        self._social_scene_turns[key] = world.turn
        return True

    def _should_voice_decision(self, decision: Any) -> bool:
        policy = self.performance.decision_voice_policy
        if policy in {"0", "off", "none", "never"}:
            return False
        if policy in {"1", "all", "always"}:
            return True
        action = str(getattr(decision, "action", "") or "")
        accepted = bool(getattr(decision, "accepted", False))
        return action in {"hostile_alarm", "refuse"} or (accepted and action in {"follow_player", "go_to_object"})

    def _authoritative_state_context(self, world: WorldState, agent: Agent, recent_events: list[WorldEvent]) -> dict[str, Any]:
        if not self.performance.compact_payloads:
            return world.export_authoritative_state()
        nearby_agents = [
            {
                "id": other.id,
                "name": other.name,
                "position": asdict(other.position),
                "distance": other.position.manhattan(agent.position),
                "emotion": other.emotion,
                "current_plan": other.current_plan,
            }
            for other in world.agents.values()
            if other.alive and other.id != agent.id and other.position.manhattan(agent.position) <= 4
        ]
        return {
            "turn": world.turn,
            "scenario": {"id": world.scenario_id, "title": world.scenario_title, "themes": list(world.themes), "tone": dict(world.tone)},
            "player": {
                "position": asdict(world.player.position),
                "inventory": list(world.player.inventory),
                "health": world.player.health,
                "hunger": world.player.hunger,
                "thirst": world.player.thirst,
                "fatigue": world.player.fatigue,
                "distance": world.player.position.manhattan(agent.position),
            },
            "agent": {
                "id": agent.id,
                "name": agent.name,
                "position": asdict(agent.position),
                "health": agent.health,
                "inventory": list(agent.inventory),
                "status_flags": list(agent.status_flags),
                "needs": asdict(agent.needs),
                "social_to_player": asdict(agent.social_to_player),
                "emotion": agent.emotion,
                "current_goal": agent.current_goal,
                "current_plan": agent.current_plan,
                "active_commitment": asdict(agent.active_commitment) if agent.active_commitment else None,
            },
            "nearby_agents": nearby_agents[:6],
            "objects": self._visible_object_records(world, agent=agent),
            "pressure": dict(world.pressure),
            "recent_events": [self._event_to_perception(event) for event in recent_events[-max(1, self.performance.recent_event_limit):]],
        }

    def _scene_context_payload(self, scene_context: Any) -> dict[str, Any]:
        raw = scene_context.to_prompt_dict()
        if not self.performance.compact_payloads:
            return raw
        limit = max(1, self.performance.known_object_limit)
        compact = dict(raw)
        compact["visible_objects"] = list(raw.get("visible_objects") or [])[:limit]
        compact["legal_interactions"] = list(raw.get("legal_interactions") or [])[:limit]
        compact["candidate_impulses"] = list(raw.get("candidate_impulses") or [])[:6]
        compact["beliefs"] = list(raw.get("beliefs") or [])[-6:]
        compact["hard_facts"] = list(raw.get("hard_facts") or [])[:8]
        return compact

    def _model_hints(self, purpose: str, default_role: str) -> dict[str, str]:
        key = purpose.upper()
        role = os.getenv(f"MOZOK_GAME_{key}_MODEL_ROLE") or os.getenv("MOZOK_GAME_MODEL_ROLE") or default_role
        model = os.getenv(f"MOZOK_GAME_{key}_MODEL") or self.model_settings.model_for_role(role) or ""
        hints = {"llm_model_role": role}
        if model:
            hints["llm_model"] = model
        return hints

    def _post_world_event(self, world: WorldState, agent: Agent, event: WorldEvent) -> None:
        perception_id = f"{agent.id}:{event.event_id}"
        post_key = f"{agent.id}:{event.idempotency_key or event.event_id}"
        if post_key in self._posted_event_ids:
            return
        payload = {
            "events": [
                {
                    "world_id": self._world_id(world),
                    "agent_id": agent.id,
                    "event_id": event.event_id,
                    "world_event_id": event.event_id,
                    "perception_id": perception_id,
                    "idempotency_key": event.idempotency_key or event.event_id,
                    "event_type": event.event_type,
                    "content": event.content,
                    "source": event.source,
                    "actor_id": event.actor_id,
                    "target_id": event.target_id,
                    "item_id": event.item_id,
                    "location_id": event.location_id,
                    "witness_ids": event.witness_ids,
                    "visibility": event.visibility,
                    "truth_status": event.truth_status,
                    "channel_hint": self._channel_for_event(event),
                    "salience": event.salience,
                    "reliability": event.reliability,
                    "tags": event.tags,
                    "metadata": event.metadata,
                }
            ],
            "store": True,
        }
        response = requests.post(f"{self.base_url}/world-events", json=payload, timeout=min(self.timeout, 2.0))
        if response.status_code >= 400:
            raise RuntimeError(f"world-events HTTP {response.status_code}: {response.text[:120]}")
        self._posted_event_ids.add(post_key)
        if len(self._posted_event_ids) > 500:
            self._posted_event_ids = set(list(self._posted_event_ids)[-250:])

    def _event_to_perception(self, event: WorldEvent) -> dict[str, Any]:
        return {
            "content": event.content,
            "event_id": event.event_id,
            "world_event_id": event.event_id,
            "idempotency_key": event.idempotency_key or event.event_id,
            "event_type": event.event_type,
            "source": event.source,
            "actor_id": event.actor_id,
            "target_id": event.target_id,
            "item_id": event.item_id,
            "location_id": event.location_id,
            "witness_ids": event.witness_ids,
            "visibility": event.visibility,
            "truth_status": event.truth_status,
            "channel_hint": self._channel_for_event(event),
            "salience": event.salience,
            "reliability": event.reliability,
            "tags": event.tags,
            "metadata": event.metadata,
        }

    def _event_to_sensory(self, event: WorldEvent) -> dict[str, Any]:
        return {
            "channel": self._channel_for_event(event),
            "content": event.content,
            "event_id": event.event_id,
            "world_event_id": event.event_id,
            "idempotency_key": event.idempotency_key or event.event_id,
            "actor_id": event.actor_id,
            "target_id": event.target_id,
            "item_id": event.item_id,
            "witness_ids": event.witness_ids,
            "visibility": event.visibility,
            "truth_status": event.truth_status,
            "intensity": max(0.1, min(10.0, event.salience)),
            "attention": max(0.1, min(10.0, event.salience)),
            "confidence": event.reliability,
            "source": event.source,
            "tags": event.tags,
            "metadata": event.metadata,
        }

    def _channel_for_event(self, event: WorldEvent) -> str:
        if "dialogue" in event.tags:
            return "text"
        if {"sound", "hearing", "noise", "signal"} & set(event.tags):
            return "hearing"
        if {"food", "water", "medical", "injury", "cold", "fatigue"} & set(event.tags):
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
                dialogue=self._ground_dialogue(world, agent, selected.get("dialogue") or self._api_agent_dialogue(world, agent, parameters, rationale)),
                emotion=agent.emotion,
                rationale=f"MOZOK API: {rationale}",
            )
        if tool_name in {"give_item", "use_inventory_item", "use_item_on_target"}:
            return AgentIntent(
                agent_id=agent.id,
                action_kind="game_command",
                tool_name=tool_name,
                parameters=parameters,
                dialogue=self._ground_dialogue(world, agent, selected.get("dialogue") or ""),
                emotion=agent.emotion,
                rationale=f"MOZOK API: {rationale}",
            )
        if tool_name == "talk_to_player" or action_kind == "speak":
            return AgentIntent(
                agent_id=agent.id,
                action_kind="speak",
                tool_name="talk_to_player",
                parameters=parameters,
                dialogue=self._ground_dialogue(world, agent, selected.get("dialogue") or self._api_dialogue(agent, recent_events, rationale)),
                emotion=agent.emotion,
                rationale=f"MOZOK API: {rationale}",
            )
        if tool_name not in {"move_to_object", "wait", "give_item", "use_inventory_item", "use_item_on_target"}:
            tool_name = "wait"
        return AgentIntent(
            agent_id=agent.id,
            action_kind=action_kind,
            tool_name=tool_name,
            parameters=parameters,
            dialogue=self._ground_dialogue(world, agent, selected.get("dialogue") or ""),
            emotion=agent.emotion,
            rationale=f"MOZOK API: {rationale}",
        )

    def _apply_intent_trace(self, world: WorldState, agent: Agent, intent: AgentIntent) -> None:
        object_id = str(intent.parameters.get("object_id") or intent.parameters.get("target_id") or "")
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
            return world.find_object_with_tag("shelter") or world.find_object_with_tag("rest") or world.find_object_with_tag("safety")
        if agent.needs.stress > 65:
            return world.find_object_with_tag("safety") or world.find_object_with_tag("shelter")
        mystery_event = any({"mystery", "sound", "unknown"} & set(event.tags) for event in recent_events[-8:])
        if mystery_event and agent.needs.curiosity > 50:
            return world.find_object_with_tag("mystery") or world.find_object_with_tag("unknown")
        return world.find_object_with_tag("safety") or next(iter(world.objects.values()), None)

    def _ranked_objects_for_context(self, world: WorldState, agent: Agent | None = None) -> list[WorldObject]:
        anchor = agent.position if agent else world.player.position
        priority_tags = {"danger", "mystery", "food", "water", "shelter", "rest", "medical", "tool", "weapon", "social"}

        def score(obj: WorldObject) -> tuple[int, int, str]:
            distance = obj.position.manhattan(anchor)
            nearby_player = obj.position.manhattan(world.player.position) <= 3
            tag_bonus = len(priority_tags & set(obj.tags))
            availability_bonus = 1 if world.is_object_available(obj) else 0
            return (-(tag_bonus + availability_bonus + (1 if nearby_player else 0)), distance, obj.id)

        objects = sorted(world.objects.values(), key=score)
        if self.performance.compact_payloads:
            return objects[: max(1, self.performance.known_object_limit)]
        return objects

    def _visible_object_records(self, world: WorldState, agent: Agent | None = None) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        anchor = agent.position if agent else world.player.position
        for obj in self._ranked_objects_for_context(world, agent):
            records.append(
                {
                    "id": obj.id,
                    "name": obj.name,
                    "kind": obj.kind,
                    "distance": obj.position.manhattan(anchor),
                    "tags": list(obj.tags),
                    "aliases": list(obj.aliases),
                    "state": dict(obj.state),
                    "interactions": [
                        {
                            "id": interaction_id,
                            "label": str((obj.interaction_defs.get(interaction_id) or {}).get("label") or interaction_id),
                            "primitive": str((obj.interaction_defs.get(interaction_id) or {}).get("primitive") or interaction_id),
                            "affordance_tags": list((obj.interaction_defs.get(interaction_id) or {}).get("affordance_tags") or []),
                        }
                        for interaction_id in obj.interactions
                    ],
                }
            )
        return records

    def _known_object_context(self, world: WorldState, agent: Agent | None = None) -> str:
        pieces = []
        for obj in self._ranked_objects_for_context(world, agent):
            interactions = ",".join(obj.interactions[:5]) if obj.interactions else "none"
            tags = ",".join(obj.tags[:5])
            aliases = ",".join(obj.aliases[:5])
            distance = obj.position.manhattan(agent.position if agent else world.player.position)
            pieces.append(f"{obj.id} name={obj.name} kind={obj.kind} dist={distance} aliases=[{aliases}] tags=[{tags}] interactions=[{interactions}]")
        text = "; ".join(pieces)
        return text[: self.performance.chat_context_chars] if self.performance.compact_payloads else text

    def _known_object_kinds(self, world: WorldState) -> list[str]:
        return sorted({obj.kind for obj in world.objects.values() if obj.kind})

    def _attention_keywords(self, world: WorldState, urgent: str) -> list[str]:
        keywords = [urgent, *world.themes] if urgent else list(world.themes)
        keywords.extend([world.scenario_title, world.setting_summary])
        for obj in self._ranked_objects_for_context(world):
            keywords.extend([obj.name, obj.kind, *obj.tags])
        deduped: list[str] = []
        for item in keywords:
            clean = str(item or "").strip()
            if clean and clean not in deduped:
                deduped.append(clean)
        return deduped[:40]

    def _api_dialogue(self, agent: Agent, recent_events: list[WorldEvent], rationale: str) -> str:
        last = recent_events[-1].content if recent_events else "this place"
        return f"{agent.name}: I'm thinking about this: {last} ({rationale[:80]})"

    def _api_agent_dialogue(self, world: WorldState, agent: Agent, parameters: dict[str, Any], rationale: str) -> str:
        target = world.agents.get(str(parameters.get("target_agent_id", "")))
        if target:
            return f"{agent.name}: {target.name}, compare notes with me. I am choosing this because {rationale[:90]}."
        return f"{agent.name}: We need to compare notes before the situation decides for us. ({rationale[:90]})"

    def _world_id(self, world: WorldState) -> str:
        return world.scenario_id or "mozok_sandbox"

    def _session_id(self, world: WorldState, suffix: str) -> str:
        return f"{self._world_id(world)}_{suffix}"

    def _tone_context(self, world: WorldState) -> str:
        return ", ".join(f"{key}={value}" for key, value in world.tone.items()) or "unspecified"

    def _ground_dialogue(self, world: WorldState, agent: Agent, text: str) -> str:
        validation = validate_agent_dialogue(world, agent, text)
        if validation.changed:
            agent.brain_risk = "Grounded dialogue rewrite: " + "; ".join(validation.rejected_physical_claims[:2])
        return validation.text

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


class AsyncMozokBrain:
    """Non-blocking wrapper around the HTTP bridge.

    The game keeps using cheap local behaviour immediately, while LLM decisions
    and chat replies are computed in a small background queue and applied later
    on the pygame thread.
    """

    mode_name = "mozok-api-async"

    def __init__(self, inner: MozokHttpClient) -> None:
        self.inner = inner
        self.fallback = inner.fallback
        self.performance = inner.performance
        self.executor = ThreadPoolExecutor(max_workers=max(1, self.performance.async_workers), thread_name_prefix="mozok-llm")
        self._pending_decisions: dict[str, tuple[int, Future]] = {}
        self._ready_decisions: dict[str, tuple[int, AgentIntent]] = {}
        self.last_status = f"MOZOK API async mode enabled: {inner.base_url}"

    def reload_model_settings(self) -> None:
        self.inner.reload_model_settings()
        self.performance = self.inner.performance

    def decide(self, world: WorldState, agent: Agent, recent_events: list[WorldEvent]) -> AgentIntent:
        self._harvest_decisions()
        ready = self._ready_decisions.pop(agent.id, None)
        if ready:
            submitted_turn, intent = ready
            if world.turn - submitted_turn <= self.performance.async_decision_ttl_turns:
                self.last_status = f"MOZOK async ready: {agent.name} -> {intent.tool_name}"
                return intent

        if agent.id not in self._pending_decisions and len(self._pending_decisions) < self.performance.async_pending_limit:
            if self.inner._should_use_llm_tick(world, agent, recent_events):
                snapshot = deepcopy(world)
                snapshot_agent = snapshot.agents.get(agent.id)
                snapshot_recent = list(snapshot.event_log[-max(1, self.performance.recent_event_limit):])
                if snapshot_agent:
                    self._pending_decisions[agent.id] = (
                        world.turn,
                        self.executor.submit(
                            self.inner.decide,
                            snapshot,
                            snapshot_agent,
                            snapshot_recent,
                            True,
                        ),
                    )
                    agent.brain_focus = "LLM thinking in background"
                    agent.brain_broadcast = "Using local behaviour now; a grounded MOZOK action is queued."

        self.last_status = f"MOZOK async: local planner for {agent.name}"
        intent = self.fallback.decide(world, agent, recent_events)
        intent.rationale = f"{self.last_status}; {intent.rationale}"
        return intent

    def chat(self, world: WorldState, agent: Agent, message: str, participant_names: list[str]) -> str:
        self.last_status = f"MOZOK async chat fallback: queued responses should use submit_chat_response"
        return self.fallback.chat(world, agent, message, participant_names)

    def interpret_speech(self, world: WorldState, agent: Agent, message: str) -> ParsedSpeech:
        self.last_status = f"MOZOK async semantic fallback: queued responses should use submit_chat_response"
        return self.fallback.interpret_speech(world, agent, message)

    def weave_social_scene(self, world: WorldState, speaker: Agent, listener: Agent, motive: dict[str, Any]) -> str:
        return ""

    def voice_agent_decision(self, world: WorldState, agent: Agent, parsed: ParsedSpeech, decision: Any) -> str:
        return ""

    def submit_chat_response(
        self,
        world: WorldState,
        agent_id: str,
        message: str,
        participant_names: list[str],
        use_llm_reply: bool = True,
        use_voice: bool = True,
    ) -> Future:
        snapshot = deepcopy(world)
        return self.executor.submit(self._chat_response_worker, snapshot, agent_id, message, participant_names, use_llm_reply, use_voice)

    def _chat_response_worker(
        self,
        world: WorldState,
        agent_id: str,
        message: str,
        participant_names: list[str],
        use_llm_reply: bool,
        use_voice: bool,
    ) -> dict[str, Any]:
        from mozok_game.engine.speech_actions import decide_agent_response

        agent = world.agents[agent_id]
        parsed = self.inner.interpret_speech(world, agent, message)
        decision = decide_agent_response(world, agent, parsed)
        if decision.handled:
            reply = decision.reply
            if use_voice:
                voiced = str(self.inner.voice_agent_decision(world, agent, parsed, decision) or "").strip()
                if voiced:
                    decision.reply = voiced
                    reply = voiced
            return {"agent_id": agent_id, "parsed": parsed, "decision": decision, "reply": reply}
        if use_llm_reply:
            reply = self.inner.chat(world, agent, message, participant_names)
        else:
            reply = self.fallback.chat(world, agent, message, participant_names)
        return {"agent_id": agent_id, "parsed": parsed, "decision": decision, "reply": reply}

    def _harvest_decisions(self) -> None:
        for agent_id, (submitted_turn, future) in list(self._pending_decisions.items()):
            if not future.done():
                continue
            self._pending_decisions.pop(agent_id, None)
            try:
                intent = future.result()
            except Exception as exc:
                self.last_status = f"MOZOK async decision dropped: {type(exc).__name__}: {str(exc)[:120]}"
                continue
            self._ready_decisions[agent_id] = (submitted_turn, intent)

    def pending_count(self) -> int:
        self._harvest_decisions()
        return len(self._pending_decisions)

    def shutdown(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)


def build_brain_client(base_dir: Path | None = None) -> BrainClient:
    # Default remains offline so the prototype always runs. Set MOZOK_GAME_USE_API=1 to force API mode.
    if os.getenv("MOZOK_GAME_USE_API", "0") == "1":
        client = MozokHttpClient(base_dir=base_dir)
        if client.performance.async_llm_enabled:
            return AsyncMozokBrain(client)
        return client
    return OfflineMozokBrain()

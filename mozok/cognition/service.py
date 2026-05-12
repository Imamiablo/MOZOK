from __future__ import annotations

import hashlib
import re
from typing import Any

from mozok.cognition.schemas import CandidateThought, CognitiveFieldReport, CognitiveFieldScore, ConsciousBroadcast, SensoryInput

_WORD_RE = re.compile(r"[\w']+", re.UNICODE)
_RISK_WORDS = {"secret", "restricted", "private", "danger", "dangerous", "weapon", "poison", "kill", "hidden", "forbidden"}
_CONTRADICTION_WORDS = {"contradict", "contradicts", "conflict", "conflicts", "false", "unreliable", "uncertain", "denies", "supersedes"}


def _stable_id(*parts: Any) -> str:
    raw = "|".join(str(part) for part in parts)
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:10]


def _norm(value: Any) -> str:
    return " ".join(str(value or "").lower().replace("_", " ").replace("-", " ").split())


def _tokens(value: Any) -> set[str]:
    return {token for token in _WORD_RE.findall(_norm(value)) if len(token) > 2}


def _token_overlap(query: str, text: str) -> float:
    query_tokens = _tokens(query)
    text_tokens = _tokens(text)
    if not query_tokens or not text_tokens:
        return 0.0
    return len(query_tokens & text_tokens) / max(1, len(query_tokens))


def _focus_overlap(focus_keywords: list[str], text: str) -> float:
    if not focus_keywords:
        return 0.0
    clean = _norm(text)
    hits = sum(1 for keyword in focus_keywords if _norm(keyword) and _norm(keyword) in clean)
    return hits / max(1, len(focus_keywords))


def _clamp(value: float, low: float = 0.0, high: float = 10.0) -> float:
    return max(low, min(high, float(value)))


def _compact(value: Any, max_chars: int = 280) -> str:
    text = str(value or "").replace("\n", " ").strip()
    return text if len(text) <= max_chars else text[: max_chars - 3] + "..."


def _item_id(item: Any) -> str | None:
    for attr in ("id", "goal_key", "skill_key", "entry_key", "entity_id"):
        value = getattr(item, attr, None)
        if value not in (None, ""):
            return str(value)
    return None


def _item_text(item: Any, attrs: tuple[str, ...]) -> str:
    return " | ".join(str(getattr(item, attr, "")) for attr in attrs if getattr(item, attr, None))


def _metadata(item: Any) -> dict[str, Any]:
    for attr in ("metadata", "metadata_json"):
        value = getattr(item, attr, None)
        if isinstance(value, dict):
            return value
    return {}


class CognitiveFieldService:
    """Deterministic attention/resonance competition for a context package.

    It does not modify SQL, FAISS, memories, goals, skills, or entity states.
    """

    def run(
        self,
        *,
        context_package: Any,
        sensory_inputs: list[SensoryInput] | None = None,
        attention_focus_keywords: list[str] | None = None,
        max_candidates: int = 12,
        broadcast_top_n: int = 3,
        min_score: float = 0.0,
    ) -> CognitiveFieldReport:
        message = getattr(context_package, "current_user_message", "")
        focus = [str(item).strip() for item in (attention_focus_keywords or []) if str(item).strip()]
        sensory = list(sensory_inputs or [])
        candidates: list[CandidateThought] = [self._candidate_from_message(message, focus)]

        candidates.extend(self._candidate_from_sensory_input(item, message, focus) for item in sensory)
        for source in ("core", "semantic", "episodic", "raw"):
            for memory in list(getattr(context_package, f"{source}_memories", [])):
                candidates.append(self._candidate_from_memory(memory, source, message, focus))
        candidates.extend(self._candidate_from_goal(item, message, focus) for item in getattr(context_package, "goal_items", []))
        candidates.extend(self._candidate_from_skill(item, message, focus) for item in getattr(context_package, "procedural_skill_items", []))
        candidates.extend(self._candidate_from_entity_state(item, message, focus) for item in getattr(context_package, "entity_state_items", []))
        candidates.extend(self._candidate_from_lore(item, message, focus) for item in getattr(context_package, "lorebook_items", []))
        candidates.extend(self._candidate_from_relation(item, message, focus) for item in getattr(context_package, "knowledge_relation_items", []))

        retained = [item for item in candidates if item.score.final_score >= float(min_score)]
        retained.sort(key=lambda item: (-item.score.final_score, item.thought_id))
        retained = retained[: max(1, int(max_candidates))]
        top = retained[: max(1, int(broadcast_top_n))]
        winner = retained[0] if retained else None
        broadcast = self._broadcast(winner=winner, top=top, focus_keywords=focus, sensory=sensory)
        return CognitiveFieldReport(
            candidate_count=len(retained),
            broadcast_top_n=max(1, int(broadcast_top_n)),
            winning_thought_id=winner.thought_id if winner else None,
            winning_score=round(winner.score.final_score, 3) if winner else None,
            candidates=retained,
            broadcast=broadcast,
            attention_report={
                "focus_keywords": focus,
                "competition": "highest final_score wins; ties are stable by thought_id",
                "scoring_weights": {
                    "attention_weight": 1.0,
                    "sensory_weight": 0.8,
                    "memory_resonance": 1.2,
                    "goal_relevance": 1.3,
                    "emotional_weight": 0.6,
                    "procedural_skill_relevance": 1.0,
                    "relation_graph_support": 0.8,
                    "confidence": 0.5,
                    "contradiction_penalty": -1.0,
                    "risk_penalty": -0.7,
                },
            },
            sensory_report={
                "sensory_input_count": len(sensory),
                "channels": sorted({item.channel for item in sensory}),
                "attended_inputs": [item.model_dump() for item in sensory if item.attention > 0],
            },
        )

    def _score(self, *, text: str, message: str, focus_keywords: list[str], attention_weight: float = 0.0, sensory_weight: float = 0.0, memory_resonance: float = 0.0, goal_relevance: float = 0.0, emotional_weight: float = 0.0, procedural_skill_relevance: float = 0.0, relation_graph_support: float = 0.0, contradiction_penalty: float = 0.0, risk_penalty: float = 0.0, confidence: float = 1.0) -> CognitiveFieldScore:
        attention = _clamp(attention_weight + _token_overlap(message, text) * 4.0 + _focus_overlap(focus_keywords, text) * 3.0)
        risk = _clamp(risk_penalty + (1.5 if _tokens(text) & _RISK_WORDS else 0.0))
        contradiction = _clamp(contradiction_penalty + (2.5 if _tokens(text) & _CONTRADICTION_WORDS else 0.0))
        final = attention + _clamp(sensory_weight) * 0.8 + _clamp(memory_resonance) * 1.2 + _clamp(goal_relevance) * 1.3 + _clamp(emotional_weight) * 0.6 + _clamp(procedural_skill_relevance) + _clamp(relation_graph_support) * 0.8 + _clamp(confidence, 0.0, 1.0) * 0.5 - contradiction - risk * 0.7
        return CognitiveFieldScore(attention_weight=round(attention, 3), sensory_weight=round(_clamp(sensory_weight), 3), memory_resonance=round(_clamp(memory_resonance), 3), goal_relevance=round(_clamp(goal_relevance), 3), emotional_weight=round(_clamp(emotional_weight), 3), procedural_skill_relevance=round(_clamp(procedural_skill_relevance), 3), relation_graph_support=round(_clamp(relation_graph_support), 3), contradiction_penalty=round(contradiction, 3), risk_penalty=round(risk, 3), confidence=round(_clamp(confidence, 0.0, 1.0), 3), final_score=round(final, 3))

    def _candidate_from_message(self, message: str, focus_keywords: list[str]) -> CandidateThought:
        return CandidateThought(thought_id="message:current", thought_type="respond_to_user", label="Respond to the current user message", content=_compact(message, 320), source="current_user_message", score=self._score(text=message, message=message, focus_keywords=focus_keywords, attention_weight=2.0, confidence=1.0), evidence=["The current message is always an active candidate for attention."], broadcast_recommendation="Answer the user directly unless a higher-scoring context candidate changes the focus.")

    def _candidate_from_sensory_input(self, sensory_input: SensoryInput, message: str, focus_keywords: list[str]) -> CandidateThought:
        strength = float(sensory_input.intensity) * 0.55 + float(sensory_input.attention) * 0.45
        text = f"{sensory_input.channel}: {sensory_input.content}"
        channel = _norm(sensory_input.channel).replace(" ", "_") or "signal"
        return CandidateThought(thought_id=f"sensory:{channel}:{_stable_id(sensory_input.channel, sensory_input.content)}", thought_type="attend_sensory_signal", label=f"Attend {sensory_input.channel} signal", content=_compact(sensory_input.content, 320), source=sensory_input.source, sensory_channel=sensory_input.channel, focus_tags=list(sensory_input.tags), score=self._score(text=text, message=message, focus_keywords=focus_keywords + list(sensory_input.tags), attention_weight=float(sensory_input.attention) * 0.5, sensory_weight=strength, confidence=float(sensory_input.confidence)), evidence=[f"intensity={sensory_input.intensity}", f"attention={sensory_input.attention}", f"confidence={sensory_input.confidence}"], broadcast_recommendation="Treat this as currently attended sensory/tool/world context, not as long-term memory.")

    def _candidate_from_memory(self, memory: Any, source: str, message: str, focus_keywords: list[str]) -> CandidateThought:
        text = _item_text(memory, ("content", "summary"))
        importance = float(getattr(memory, "importance", 5) or 5)
        search_score = float(getattr(memory, "score", 0.0) or 0.0)
        emotional = abs(float(getattr(memory, "emotional_weight", 0.0) or 0.0)) * 4.0
        reranking = _metadata(memory).get("_reranking", {})
        rerank_score = float(reranking.get("final_score", 0.0) or 0.0) if isinstance(reranking, dict) else 0.0
        memory_id = _item_id(memory)
        return CandidateThought(thought_id=f"memory:{source}:{memory_id or _stable_id(text)}", thought_type="recall_memory", label=f"Recall {source} memory", content=_compact(text, 360), source=source, source_id=memory_id, score=self._score(text=text, message=message, focus_keywords=focus_keywords, memory_resonance=importance * 0.7 + search_score * 3.0 + min(rerank_score, 3.0), emotional_weight=emotional, confidence=0.85 if source != "raw" else 0.55, risk_penalty=0.5 if source == "raw" else 0.0), evidence=[f"importance={importance}", f"search_score={search_score}", f"source={source}"], broadcast_recommendation="Use this memory only if it is relevant and permitted by the surrounding context.")

    def _candidate_from_goal(self, goal: Any, message: str, focus_keywords: list[str]) -> CandidateThought:
        text = _item_text(goal, ("title", "description", "notes"))
        priority = float(getattr(goal, "priority", 5) or 5)
        goal_id = _item_id(goal)
        return CandidateThought(thought_id=f"goal:{goal_id or _stable_id(text)}", thought_type="pursue_goal", label=f"Pursue goal: {getattr(goal, 'title', goal_id or 'goal')}", content=_compact(text, 360), source="goal", source_id=goal_id, score=self._score(text=text, message=message, focus_keywords=focus_keywords, goal_relevance=priority, confidence=0.9), evidence=[f"priority={priority}"], broadcast_recommendation="Let this goal guide intent, but do not force it if unrelated.")

    def _candidate_from_skill(self, skill: Any, message: str, focus_keywords: list[str]) -> CandidateThought:
        trigger = getattr(skill, "trigger", None) or getattr(skill, "trigger_json", None) or {}
        procedure = getattr(skill, "procedure", None) or getattr(skill, "procedure_json", None) or []
        text = " | ".join(str(part) for part in [getattr(skill, "title", ""), getattr(skill, "description", ""), trigger, procedure, getattr(skill, "notes", "")] if part)
        priority = float(getattr(skill, "priority", 5) or 5)
        skill_id = _item_id(skill)
        return CandidateThought(thought_id=f"skill:{skill_id or _stable_id(text)}", thought_type="use_skill", label=f"Use skill: {getattr(skill, 'title', skill_id or 'skill')}", content=_compact(text, 360), source="procedural_skill", source_id=skill_id, score=self._score(text=text, message=message, focus_keywords=focus_keywords, procedural_skill_relevance=priority, confidence=0.9), evidence=[f"priority={priority}"], broadcast_recommendation="Use this procedural strategy when shaping the response or action.")

    def _candidate_from_entity_state(self, state: Any, message: str, focus_keywords: list[str]) -> CandidateThought:
        attributes = getattr(state, "attributes", None) or getattr(state, "attributes_json", None) or {}
        text = " | ".join(str(part) for part in [getattr(state, "entity_name", ""), getattr(state, "state_kind", ""), attributes, getattr(state, "notes", "")] if part)
        emotional = 0.0
        if isinstance(attributes, dict):
            for key, value in attributes.items():
                if str(key).lower() in {"fear", "trust", "respect", "resentment", "stress", "urgency"}:
                    try: emotional += abs(float(value))
                    except (TypeError, ValueError): pass
        state_id = _item_id(state)
        return CandidateThought(thought_id=f"entity_state:{state_id or _stable_id(text)}", thought_type="track_entity_state", label=f"Track entity state: {getattr(state, 'entity_name', state_id or 'entity')}", content=_compact(text, 360), source="entity_state", source_id=state_id, score=self._score(text=text, message=message, focus_keywords=focus_keywords, emotional_weight=emotional, attention_weight=1.0, confidence=0.85), evidence=["entity-state attributes can affect emotional and social attention."], broadcast_recommendation="Use this as current state from the agent's perspective, not universal truth.")

    def _candidate_from_lore(self, lore: Any, message: str, focus_keywords: list[str]) -> CandidateThought:
        text = _item_text(lore, ("title", "content", "category"))
        importance = float(getattr(lore, "importance", 5) or 5)
        confidence = float(getattr(lore, "confidence", 8) or 8) / 10.0
        lore_id = _item_id(lore)
        return CandidateThought(thought_id=f"lore:{lore_id or _stable_id(text)}", thought_type="use_lore", label=f"Use lore: {getattr(lore, 'title', lore_id or 'lore')}", content=_compact(text, 360), source="lorebook", source_id=lore_id, score=self._score(text=text, message=message, focus_keywords=focus_keywords, memory_resonance=importance, confidence=confidence, risk_penalty=0.4 if getattr(lore, "visibility", "public") != "public" else 0.0), evidence=[f"visibility={getattr(lore, 'visibility', 'unknown')}", f"importance={importance}"], broadcast_recommendation="Use lore as canonical world knowledge only within this agent's access level.")

    def _candidate_from_relation(self, relation: Any, message: str, focus_keywords: list[str]) -> CandidateThought:
        text = " | ".join(str(part) for part in [getattr(relation, "source_type", ""), getattr(relation, "source_id", ""), getattr(relation, "relation_type", ""), getattr(relation, "target_type", ""), getattr(relation, "target_id", ""), getattr(relation, "description", ""), getattr(relation, "evidence", "")] if part)
        strength = float(getattr(relation, "strength", 1.0) or 1.0)
        confidence = float(getattr(relation, "confidence", 0.8) or 0.8)
        relation_id = _item_id(relation)
        is_contradiction = _norm(getattr(relation, "relation_type", "")) in {"contradicts", "conflicts with"}
        return CandidateThought(thought_id=f"relation:{relation_id or _stable_id(text)}", thought_type="follow_relation", label=f"Follow relation: {getattr(relation, 'relation_type', 'relation')}", content=_compact(text, 360), source="knowledge_relation", source_id=relation_id, score=self._score(text=text, message=message, focus_keywords=focus_keywords, relation_graph_support=strength * 5.0, confidence=confidence, contradiction_penalty=3.0 if is_contradiction else 0.0), evidence=[f"strength={strength}", f"confidence={confidence}"], broadcast_recommendation="Use this relation as structural support, especially for contradictions or dependencies.")

    def _broadcast(self, *, winner: CandidateThought | None, top: list[CandidateThought], focus_keywords: list[str], sensory: list[SensoryInput]) -> ConsciousBroadcast:
        if winner is None:
            return ConsciousBroadcast(summary="No candidate thought passed the minimum score.", attention_focus=focus_keywords, prompt_guidance="Proceed from ordinary context without an extra broadcast state.")
        focus = list(dict.fromkeys(focus_keywords + winner.focus_tags))
        if winner.sensory_channel:
            focus.append(winner.sensory_channel)
        if not focus:
            focus = [winner.thought_type]
        recommendations = ["Do not write memory/entity/skill changes automatically from the broadcast alone.", "Use the broadcast as soft focus for this turn's response or action selection."]
        if sensory:
            recommendations.append("Sensory inputs are transient unless a later reflection/change proposal stores them.")
        return ConsciousBroadcast(selected_thought_id=winner.thought_id, selected_label=winner.label, selected_type=winner.thought_type, summary=f"Winning state: {winner.label}.", attention_focus=focus, top_thought_ids=[item.thought_id for item in top], working_memory_line=f"Attend to: {winner.label} — {winner.content}", update_recommendations=recommendations, prompt_guidance=f"Current broadcast focus: {winner.label}. Primary intent: {winner.broadcast_recommendation}")

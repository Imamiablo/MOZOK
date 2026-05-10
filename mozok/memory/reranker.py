"""Deterministic memory reranking for MOZOK.

The reranker is deliberately transparent and non-LLM-based. It does not decide
what the agent should say; it only scores retrieved memory candidates before the
ContextBuilder places them into the prompt.

Every score is returned with a small explanation so /debug/context can show why a
memory was selected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import exp, log1p
from typing import Any, Mapping, Sequence


MEMORY_TYPE_WEIGHTS: dict[str, float] = {
    "core": 0.20,
    "semantic": 0.12,
    "episodic": 0.08,
    "raw": 0.02,
}


@dataclass(slots=True)
class MemoryRelationSignal:
    """Small summary of graph links touching one memory."""

    relation_count: int = 0
    active_goal_count: int = 0
    lorebook_count: int = 0
    entity_state_count: int = 0
    max_strength: float = 0.0
    max_confidence: float = 0.0
    relation_types: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "relation_count": self.relation_count,
            "active_goal_count": self.active_goal_count,
            "lorebook_count": self.lorebook_count,
            "entity_state_count": self.entity_state_count,
            "max_strength": self.max_strength,
            "max_confidence": self.max_confidence,
            "relation_types": list(dict.fromkeys(self.relation_types)),
        }


@dataclass(slots=True)
class MemoryRerankingContext:
    """Extra information used when scoring memory candidates."""

    now: datetime | None = None
    relation_signals: dict[int, MemoryRelationSignal] = field(default_factory=dict)


@dataclass(slots=True)
class MemoryRerankingExplanation:
    memory_id: int
    final_score: float
    score_parts: dict[str, float]
    reason: str
    relation_signal: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "final_score": self.final_score,
            "score_parts": dict(self.score_parts),
            "reason": self.reason,
            "relation_signal": dict(self.relation_signal),
        }


@dataclass(slots=True)
class RerankedMemory:
    record: Any
    explanation: MemoryRerankingExplanation


class MemoryReranker:
    """Transparent deterministic reranker for memory search results."""

    def rerank(
        self,
        records: Sequence[Any],
        *,
        vector_scores: Mapping[int, float],
        context: MemoryRerankingContext | None = None,
        limit: int | None = None,
    ) -> list[RerankedMemory]:
        context = context or MemoryRerankingContext()
        now = context.now or datetime.now(timezone.utc)

        reranked: list[RerankedMemory] = []
        for record in records:
            memory_id = int(getattr(record, "id"))
            explanation = self.explain_record(
                record,
                vector_score=float(vector_scores.get(memory_id, 0.0)),
                relation_signal=context.relation_signals.get(memory_id),
                now=now,
            )
            reranked.append(RerankedMemory(record=record, explanation=explanation))

        reranked.sort(key=lambda item: item.explanation.final_score, reverse=True)
        if limit is not None:
            return reranked[: max(0, int(limit))]
        return reranked

    def explain_record(
        self,
        record: Any,
        *,
        vector_score: float,
        relation_signal: MemoryRelationSignal | None = None,
        now: datetime | None = None,
    ) -> MemoryRerankingExplanation:
        now = now or datetime.now(timezone.utc)
        relation_signal = relation_signal or MemoryRelationSignal()

        memory_id = int(getattr(record, "id"))
        memory_type = str(getattr(record, "memory_type", "semantic") or "semantic").lower()
        importance = _safe_float(getattr(record, "importance", 0), 0.0)
        emotional_weight = abs(_safe_float(getattr(record, "emotional_weight", 0.0), 0.0))
        access_count = _access_count(record)

        score_parts = {
            "vector_score": vector_score,
            "importance": min(max(importance, 0.0), 10.0) * 0.020,
            "emotional_weight": min(max(emotional_weight, 0.0), 10.0) * 0.015,
            "recency": self._recency_score(record, now),
            "access_count": min(log1p(max(access_count, 0)), 8.0) * 0.020,
            "memory_type_weight": MEMORY_TYPE_WEIGHTS.get(memory_type, 0.06),
            "active_goal_boost": min(float(relation_signal.active_goal_count), 3.0) * 0.070,
            "relation_boost": min(float(relation_signal.relation_count), 5.0) * 0.025,
            "lore_entity_boost": min(float(relation_signal.lorebook_count + relation_signal.entity_state_count), 4.0) * 0.030,
            "relation_strength": min(max(relation_signal.max_strength, 0.0), 1.0) * 0.030,
            "relation_confidence": min(max(relation_signal.max_confidence, 0.0), 1.0) * 0.020,
        }
        final_score = round(sum(score_parts.values()), 6)

        return MemoryRerankingExplanation(
            memory_id=memory_id,
            final_score=final_score,
            score_parts={key: round(value, 6) for key, value in score_parts.items()},
            reason=self._reason(record, score_parts, relation_signal),
            relation_signal=relation_signal.to_dict(),
        )

    def _recency_score(self, record: Any, now: datetime) -> float:
        timestamp = (
            getattr(record, "last_accessed_at", None)
            or getattr(record, "updated_at", None)
            or getattr(record, "created_at", None)
        )
        if timestamp is None:
            return 0.0
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        age_days = max((now - timestamp).total_seconds() / 86400.0, 0.0)
        return 0.12 * exp(-age_days / 30.0)

    def _reason(
        self,
        record: Any,
        score_parts: Mapping[str, float],
        relation_signal: MemoryRelationSignal,
    ) -> str:
        reasons: list[str] = []

        if score_parts.get("vector_score", 0.0) >= 0.65:
            reasons.append("strong semantic match")
        elif score_parts.get("vector_score", 0.0) >= 0.35:
            reasons.append("moderate semantic match")

        if score_parts.get("importance", 0.0) >= 0.14:
            reasons.append("high importance")
        if score_parts.get("emotional_weight", 0.0) >= 0.06:
            reasons.append("emotional salience")
        if score_parts.get("recency", 0.0) >= 0.08:
            reasons.append("recently created or accessed")
        if score_parts.get("access_count", 0.0) >= 0.04:
            reasons.append("frequently accessed")

        memory_type = str(getattr(record, "memory_type", "memory") or "memory")
        if memory_type in {"core", "semantic"}:
            reasons.append(f"{memory_type} memory type")

        if relation_signal.active_goal_count:
            reasons.append("linked to active goal context")
        if relation_signal.lorebook_count or relation_signal.entity_state_count:
            reasons.append("linked to lore/entity context")
        if relation_signal.relation_count and not relation_signal.active_goal_count:
            reasons.append("connected in the knowledge graph")

        if not reasons:
            reasons.append("kept by baseline retrieval score")

        return "Selected because of " + ", ".join(dict.fromkeys(reasons)) + "."


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _access_count(record: Any) -> int:
    metadata = getattr(record, "metadata_json", None)
    if not isinstance(metadata, dict):
        metadata = getattr(record, "metadata", None)
    if not isinstance(metadata, dict):
        return 0
    try:
        return int(metadata.get("access_count", 0))
    except (TypeError, ValueError):
        return 0


def explanation_from_memory_metadata(memory: Any) -> dict[str, Any] | None:
    """Extract reranking details from either SQL records or search result models."""

    metadata = getattr(memory, "metadata_json", None)
    if not isinstance(metadata, dict):
        metadata = getattr(memory, "metadata", None)
    if not isinstance(metadata, dict):
        return None
    explanation = metadata.get("_reranking")
    if isinstance(explanation, dict):
        return explanation
    return None

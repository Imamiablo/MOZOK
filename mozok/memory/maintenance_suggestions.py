from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import sqrt
from typing import Any, Iterable

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from mozok.db.models import AgentRecord, MemoryRecord
from mozok.embeddings.base import EmbeddingService
from mozok.knowledge_relations.models import KnowledgeRelationRecord
from mozok.llm.ollama_openai import OllamaOpenAIClient
from mozok.memory.policy import (
    MEMORY_LEVEL_CORE,
    MEMORY_LEVEL_EPISODIC,
    MEMORY_LEVEL_RAW,
    coerce_memory_policy,
    fresh_default_memory_policy,
)
from mozok.schemas.memory import (
    MemoryMaintenanceSuggestion,
    MemoryMaintenanceSuggestionsRequest,
    MemoryMaintenanceSuggestionsResponse,
)


ARCHIVE_FRIENDLY_RELATION_TYPES = {
    "duplicate_of",
    "near_duplicate_of",
    "summarised_by",
    "summarized_by",
    "superseded_by",
    "obsolete_after",
}

DESTRUCTIVE_MAINTENANCE_ACTIONS = {
    "archive",
    "decay",
    "soft_delete",
    "hard_delete",
    "summarize_then_archive",
}


@dataclass(slots=True)
class _RelationSignal:
    relation_ids: list[int]
    relation_types: list[str]
    archive_friendly_only: bool
    contradiction_risk: bool


class MemoryMaintenanceSuggestionService:
    """Read-only maintenance suggestion engine.

    This service does not commit, index, rebuild FAISS, archive, decay, delete,
    protect, or create summaries. It only produces suggestions that later
    apply/reject endpoints can accept or reject.
    """

    def __init__(
        self,
        db: Session,
        embedding_service: EmbeddingService | None = None,
        llm_client: Any | None = None,
    ):
        self.db = db
        self.embedding_service = embedding_service
        self.llm_client = llm_client

    def preview(
        self,
        *,
        agent_id: str,
        request: MemoryMaintenanceSuggestionsRequest | None = None,
    ) -> MemoryMaintenanceSuggestionsResponse:
        request = request or MemoryMaintenanceSuggestionsRequest()
        now = datetime.now(timezone.utc)
        policy = self._get_policy(agent_id)
        rules = dict(policy.get("rules") or {})

        records = (
            self.db.query(MemoryRecord)
            .filter(MemoryRecord.agent_id == agent_id, MemoryRecord.active == True)  # noqa: E712
            .order_by(MemoryRecord.created_at.asc(), MemoryRecord.id.asc())
            .limit(request.limit)
            .all()
        )

        relation_signals = self._relation_signals(agent_id=agent_id, records=records, world_id=request.world_id)
        suggestions: list[MemoryMaintenanceSuggestion] = []
        suggested_keys: set[tuple[str, tuple[int, ...]]] = set()

        protect_importance = int(rules.get("protect_importance_at_or_above", 8))
        archive_below = float(rules.get("archive_retention_score_below", 0.20))
        raw_ttl_days = float(rules.get("raw_ttl_days", 7))
        episodic_decay_after_days = float(rules.get("episodic_decay_after_days", 30))

        for record in records:
            signal = relation_signals.get(record.id)
            relation_protected = bool(
                request.include_relation_protection
                and signal is not None
                and not signal.archive_friendly_only
            )

            if relation_protected:
                self._append_unique(
                    suggestions,
                    suggested_keys,
                    self._suggestion(
                        action="protect",
                        target_memory_ids=[record.id],
                        source="relation_protection",
                        reason=(
                            "Memory is linked by active knowledge relations, so it should not be "
                            "automatically archived, decayed, deleted, or summarised away."
                        ),
                        confidence=0.92,
                        safe_to_auto_apply=True,
                        relation_protected=True,
                        blocked_by_relation_ids=signal.relation_ids,
                    ),
                )
                if signal.contradiction_risk:
                    self._append_unique(
                        suggestions,
                        suggested_keys,
                        self._suggestion(
                            action="review",
                            target_memory_ids=[record.id],
                            source="relation_protection",
                            reason=(
                                "Memory is part of a contradiction relation. Review it before applying "
                                "automatic maintenance."
                            ),
                            confidence=0.86,
                            safe_to_auto_apply=False,
                            relation_protected=True,
                            blocked_by_relation_ids=signal.relation_ids,
                        ),
                    )
                continue

            metadata = self._metadata(record)
            if record.memory_type == MEMORY_LEVEL_CORE or metadata.get("protected") or record.importance >= protect_importance:
                self._append_unique(
                    suggestions,
                    suggested_keys,
                    self._suggestion(
                        action="protect",
                        target_memory_ids=[record.id],
                        source="rules",
                        reason="Core, explicitly protected, or high-importance memory should remain protected.",
                        confidence=0.90,
                        safe_to_auto_apply=True,
                    ),
                )
                continue

            age_days = self._age_days(record, now)
            retention_score = self._retention_score(record, now)

            if record.memory_type == MEMORY_LEVEL_RAW and age_days >= raw_ttl_days and retention_score < max(archive_below, 0.30):
                self._append_unique(
                    suggestions,
                    suggested_keys,
                    self._suggestion(
                        action="archive",
                        target_memory_ids=[record.id],
                        source="rules",
                        reason=(
                            f"Old raw memory with low retention score ({retention_score:.2f}); "
                            "safe candidate for archive."
                        ),
                        confidence=min(0.95, max(0.55, 1.0 - retention_score)),
                        safe_to_auto_apply=True,
                    ),
                )
            elif record.memory_type == MEMORY_LEVEL_EPISODIC and age_days >= episodic_decay_after_days and retention_score < 0.55:
                self._append_unique(
                    suggestions,
                    suggested_keys,
                    self._suggestion(
                        action="decay",
                        target_memory_ids=[record.id],
                        source="rules",
                        reason=(
                            f"Old episodic memory with modest retention score ({retention_score:.2f}); "
                            "candidate for gentle decay rather than archive."
                        ),
                        confidence=min(0.85, max(0.50, 0.80 - retention_score / 2)),
                        safe_to_auto_apply=True,
                    ),
                )

        if request.include_embedding_clusters:
            for suggestion in self._cluster_suggestions(
                records=records,
                relation_signals=relation_signals,
                request=request,
            ):
                self._append_unique(suggestions, suggested_keys, suggestion)

        if request.include_llm_reasons:
            suggestions = [self._with_llm_reason(suggestion) for suggestion in suggestions]

        summary = self._summary(suggestions)
        notes = [
            "Read-only preview: no SQL records, FAISS entries, access counters, summaries, or relations were modified."
        ]
        if request.include_llm_reasons:
            notes.append("LLM reasons are explanatory only; deterministic rule/cluster logic still owns the actions.")
        if request.include_embedding_clusters:
            notes.append("Embedding clustering is suggest-only and proposes consolidation candidates; it does not create summaries.")

        return MemoryMaintenanceSuggestionsResponse(
            agent_id=agent_id,
            trigger=request.trigger,
            dry_run=True,
            scanned=len(records),
            suggestions=suggestions,
            summary=summary,
            notes=notes,
        )

    def _suggestion(
        self,
        *,
        action: str,
        target_memory_ids: list[int],
        source: str,
        reason: str,
        confidence: float,
        safe_to_auto_apply: bool,
        relation_protected: bool = False,
        blocked_by_relation_ids: list[int] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryMaintenanceSuggestion:
        ids_key = ":".join(str(memory_id) for memory_id in sorted(target_memory_ids))
        suggestion_id = f"{source}:{action}:memory:{ids_key}"
        return MemoryMaintenanceSuggestion(
            suggestion_id=suggestion_id,
            action=action,
            target_memory_ids=target_memory_ids,
            reason=reason,
            confidence=max(0.0, min(1.0, float(confidence))),
            source=source,
            safe_to_auto_apply=safe_to_auto_apply,
            relation_protected=relation_protected,
            blocked_by_relation_ids=blocked_by_relation_ids or [],
            would_modify=False,
            metadata=metadata or {},
        )

    def _append_unique(
        self,
        suggestions: list[MemoryMaintenanceSuggestion],
        keys: set[tuple[str, tuple[int, ...]]],
        suggestion: MemoryMaintenanceSuggestion,
    ) -> None:
        key = (suggestion.action, tuple(sorted(suggestion.target_memory_ids)))
        if key in keys:
            return
        keys.add(key)
        suggestions.append(suggestion)

    def _cluster_suggestions(
        self,
        *,
        records: list[MemoryRecord],
        relation_signals: dict[int, _RelationSignal],
        request: MemoryMaintenanceSuggestionsRequest,
    ) -> list[MemoryMaintenanceSuggestion]:
        raw_records = [record for record in records if record.memory_type == MEMORY_LEVEL_RAW]
        if len(raw_records) < request.min_cluster_size:
            return []

        vectors = self._record_vectors(raw_records)
        clusters: list[tuple[list[MemoryRecord], float, str]] = []

        if vectors:
            unused = set(record.id for record in raw_records)
            by_id = {record.id: record for record in raw_records}
            for record in raw_records:
                if record.id not in unused:
                    continue
                cluster = [record]
                similarities: list[float] = []
                unused.remove(record.id)
                for other_id in list(unused):
                    similarity = self._cosine(vectors[record.id], vectors[other_id])
                    if similarity >= request.similarity_threshold:
                        cluster.append(by_id[other_id])
                        similarities.append(similarity)
                        unused.remove(other_id)
                if len(cluster) >= request.min_cluster_size:
                    clusters.append((cluster, sum(similarities or [request.similarity_threshold]) / max(1, len(similarities or [1])), "embedding_cluster"))
        else:
            # Cheap fallback for test/dev environments without an embedding service.
            unused = set(record.id for record in raw_records)
            by_id = {record.id: record for record in raw_records}
            for record in raw_records:
                if record.id not in unused:
                    continue
                cluster = [record]
                scores: list[float] = []
                unused.remove(record.id)
                for other_id in list(unused):
                    score = self._token_jaccard(record.content, by_id[other_id].content)
                    if score >= max(0.45, request.similarity_threshold - 0.30):
                        cluster.append(by_id[other_id])
                        scores.append(score)
                        unused.remove(other_id)
                if len(cluster) >= request.min_cluster_size:
                    clusters.append((cluster, sum(scores or [0.50]) / max(1, len(scores or [1])), "text_cluster"))

        suggestions: list[MemoryMaintenanceSuggestion] = []
        for cluster, score, source in clusters[: request.max_clusters]:
            ids = [record.id for record in cluster]
            blocked_relations: list[int] = []
            relation_protected = False
            for memory_id in ids:
                signal = relation_signals.get(memory_id)
                if signal and not signal.archive_friendly_only:
                    relation_protected = True
                    blocked_relations.extend(signal.relation_ids)

            suggestions.append(
                self._suggestion(
                    action="summarize_then_archive",
                    target_memory_ids=ids,
                    source=source,
                    reason=(
                        f"{len(ids)} similar raw memories look suitable for consolidation into one "
                        f"semantic summary before archiving the noisy sources. Average similarity: {score:.2f}."
                    ),
                    confidence=max(0.55, min(0.90, score)),
                    safe_to_auto_apply=not relation_protected,
                    relation_protected=relation_protected,
                    blocked_by_relation_ids=sorted(set(blocked_relations)),
                    metadata={"cluster_size": len(ids), "average_similarity": round(score, 3)},
                )
            )
        return suggestions

    def _record_vectors(self, records: list[MemoryRecord]) -> dict[int, Any]:
        if self.embedding_service is None:
            return {}
        vectors: dict[int, Any] = {}
        try:
            for record in records:
                vectors[record.id] = self.embedding_service.embed_text(record.content or "")
        except Exception:
            return {}
        return vectors

    def _with_llm_reason(self, suggestion: MemoryMaintenanceSuggestion) -> MemoryMaintenanceSuggestion:
        llm_client = self.llm_client
        if llm_client is None:
            try:
                llm_client = OllamaOpenAIClient(default_role="maintenance")
            except Exception as exc:  # noqa: BLE001 - preview must remain safe.
                suggestion.metadata["llm_reason_error"] = f"{type(exc).__name__}: {exc}"
                suggestion.metadata["reason_method"] = "deterministic"
                return suggestion

        try:
            prompt = (
                "You are Mozok's memory maintenance reviewer. Rewrite the reason for this "
                "maintenance suggestion in one short, careful sentence. Do not change the action. "
                "Do not invent facts. Mention uncertainty if the evidence is weak. Use British English."
            )
            user_message = (
                f"Action: {suggestion.action}\n"
                f"Target memory IDs: {suggestion.target_memory_ids}\n"
                f"Source: {suggestion.source}\n"
                f"Current reason: {suggestion.reason}\n"
                f"Relation protected: {suggestion.relation_protected}\n"
                f"Safe to auto apply: {suggestion.safe_to_auto_apply}\n"
            )
            response = str(llm_client.chat(system_prompt=prompt, user_message=user_message, temperature=0.1)).strip()
            if response:
                suggestion.metadata["deterministic_reason"] = suggestion.reason
                suggestion.reason = " ".join(response.split())[:600]
                suggestion.metadata["reason_method"] = "llm_explanation"
                suggestion.metadata["reason_model"] = getattr(llm_client, "model", None)
        except Exception as exc:  # noqa: BLE001 - preview must remain safe.
            suggestion.metadata["llm_reason_error"] = f"{type(exc).__name__}: {exc}"
            suggestion.metadata["reason_method"] = "deterministic"
        return suggestion

    def _relation_signals(
        self,
        *,
        agent_id: str,
        records: list[MemoryRecord],
        world_id: str,
    ) -> dict[int, _RelationSignal]:
        if not records:
            return {}
        memory_ids = {str(record.id) for record in records}
        relations = (
            self.db.query(KnowledgeRelationRecord)
            .filter(
                KnowledgeRelationRecord.agent_id == agent_id,
                KnowledgeRelationRecord.world_id == world_id,
                KnowledgeRelationRecord.active == True,  # noqa: E712
                or_(
                    and_(
                        KnowledgeRelationRecord.source_type == "memory",
                        KnowledgeRelationRecord.source_id.in_(memory_ids),
                    ),
                    and_(
                        KnowledgeRelationRecord.target_type == "memory",
                        KnowledgeRelationRecord.target_id.in_(memory_ids),
                    ),
                ),
            )
            .all()
        )

        bucket: dict[int, list[KnowledgeRelationRecord]] = {}
        for relation in relations:
            candidate_ids: list[str] = []
            if relation.source_type == "memory":
                candidate_ids.append(str(relation.source_id))
            if relation.target_type == "memory":
                candidate_ids.append(str(relation.target_id))
            for candidate in candidate_ids:
                try:
                    memory_id = int(candidate)
                except (TypeError, ValueError):
                    continue
                bucket.setdefault(memory_id, []).append(relation)

        signals: dict[int, _RelationSignal] = {}
        for memory_id, related in bucket.items():
            relation_types = [str(relation.relation_type or "").strip().lower() for relation in related]
            archive_friendly_only = all(relation_type in ARCHIVE_FRIENDLY_RELATION_TYPES for relation_type in relation_types)
            contradiction_risk = any("contradict" in relation_type for relation_type in relation_types)
            signals[memory_id] = _RelationSignal(
                relation_ids=[int(relation.id) for relation in related if relation.id is not None],
                relation_types=relation_types,
                archive_friendly_only=archive_friendly_only,
                contradiction_risk=contradiction_risk,
            )
        return signals

    def _get_policy(self, agent_id: str) -> dict[str, Any]:
        agent = self.db.get(AgentRecord, agent_id)
        if agent is None:
            return fresh_default_memory_policy()
        metadata = dict(agent.metadata_json or {})
        return coerce_memory_policy(metadata.get("memory_policy") or {})

    def _metadata(self, record: MemoryRecord) -> dict[str, Any]:
        return dict(record.metadata_json or {})

    def _access_count(self, record: MemoryRecord) -> int:
        return int(self._metadata(record).get("access_count", 0))

    def _age_days(self, record: MemoryRecord, now: datetime | None = None) -> float:
        now = now or datetime.now(timezone.utc)
        created_at = record.created_at or now
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return max(0.0, (now - created_at).total_seconds() / 86400.0)

    def _retention_score(self, record: MemoryRecord, now: datetime | None = None) -> float:
        now = now or datetime.now(timezone.utc)
        age_days = self._age_days(record, now)
        access_count = min(self._access_count(record), 20)
        base = record.importance / 10.0
        emotion_bonus = min(abs(record.emotional_weight), 1.0) * 0.20
        access_bonus = access_count * 0.02
        if record.memory_type == MEMORY_LEVEL_RAW:
            age_penalty = age_days * 0.08
        elif record.memory_type == MEMORY_LEVEL_EPISODIC:
            age_penalty = age_days * 0.02
        else:
            age_penalty = age_days * 0.005
        return base + emotion_bonus + access_bonus - age_penalty

    def _summary(self, suggestions: Iterable[MemoryMaintenanceSuggestion]) -> dict[str, int]:
        summary: dict[str, int] = {}
        for suggestion in suggestions:
            summary[suggestion.action] = summary.get(suggestion.action, 0) + 1
        return summary

    def _cosine(self, first: Any, second: Any) -> float:
        first_values = list(float(value) for value in first)
        second_values = list(float(value) for value in second)
        if not first_values or not second_values or len(first_values) != len(second_values):
            return 0.0
        numerator = sum(a * b for a, b in zip(first_values, second_values))
        first_norm = sqrt(sum(a * a for a in first_values))
        second_norm = sqrt(sum(b * b for b in second_values))
        if first_norm == 0.0 or second_norm == 0.0:
            return 0.0
        return numerator / (first_norm * second_norm)

    def _token_jaccard(self, first: str, second: str) -> float:
        first_tokens = self._tokens(first)
        second_tokens = self._tokens(second)
        if not first_tokens or not second_tokens:
            return 0.0
        return len(first_tokens & second_tokens) / len(first_tokens | second_tokens)

    def _tokens(self, text: str) -> set[str]:
        return {
            token.strip(".,!?;:()[]{}\"'`).“”‘’").lower()
            for token in str(text or "").split()
            if len(token.strip(".,!?;:()[]{}\"'`).“”‘’")) >= 3
        }

"""Live MemoryService.search reranking wrapper.

This module is a deliberately small safety wrapper around MemoryService.search.
It fixes the live API path where /debug/context can receive normal search
results without `_reranking` metadata even though the ContextPackage debug layer
already knows how to display it.

The wrapper does not mutate SQL or FAISS. It only reranks the outgoing
MemorySearchResult objects and attaches an explanation to their response
metadata.
"""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable, Iterable

from sqlalchemy import and_, or_

from mozok.db.models import MemoryRecord
from mozok.knowledge_relations.models import KnowledgeRelationRecord
from mozok.memory.reranker import MemoryRelationSignal, MemoryReranker, MemoryRerankingContext
from mozok.schemas.memory import MemorySearchResult


class _SearchResultRecordAdapter:
    """Small adapter so the reranker can explain results even if DB lookup fails."""

    def __init__(self, result: MemorySearchResult):
        self.id = result.id
        self.content = result.content
        self.memory_type = result.memory_type
        self.importance = result.importance
        metadata = dict(result.metadata or {})
        self.metadata_json = metadata
        self.emotional_weight = metadata.get("emotional_weight", 0.0)
        self.created_at = None
        self.updated_at = None
        self.last_accessed_at = None


def install_live_search_reranking(service_cls: type[Any]) -> bool:
    """Wrap MemoryService.search so live responses include reranking details.

    Returns True when a wrapper was installed, False when it was already present.
    """

    original = getattr(service_cls, "search", None)
    if original is None or not callable(original):
        raise AttributeError("MemoryService.search was not found; cannot install live reranking wrapper.")

    if getattr(original, "_mozok_live_reranking_wrapped", False):
        return False

    @wraps(original)
    def wrapped(self: Any, *args: Any, **kwargs: Any) -> list[MemorySearchResult]:
        results = original(self, *args, **kwargs)
        if not results:
            return results

        if all(isinstance(getattr(result, "metadata", None), dict) and result.metadata.get("_reranking") for result in results):
            return results

        agent_id = _find_agent_id(args, kwargs)
        return _rerank_search_results(self, results, agent_id=agent_id)

    setattr(wrapped, "_mozok_live_reranking_wrapped", True)
    setattr(service_cls, "search", wrapped)
    return True


def _find_agent_id(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str | None:
    if "agent_id" in kwargs:
        return str(kwargs["agent_id"])
    if args:
        return str(args[0])
    return None


def _rerank_search_results(
    service: Any,
    results: list[MemorySearchResult],
    *,
    agent_id: str | None,
) -> list[MemorySearchResult]:
    ids = [int(result.id) for result in results]
    score_by_id = {int(result.id): float(result.score or 0.0) for result in results}
    result_by_id = {int(result.id): result for result in results}

    records_by_id = _records_by_id(service, ids)
    records: list[Any] = [records_by_id.get(memory_id) or _SearchResultRecordAdapter(result_by_id[memory_id]) for memory_id in ids]
    relation_signals = _relation_signals(service, agent_id=agent_id, memory_ids=ids)

    reranked = MemoryReranker().rerank(
        records,
        vector_scores=score_by_id,
        context=MemoryRerankingContext(
            now=_utc_now(service),
            relation_signals=relation_signals,
        ),
        limit=len(results),
    )

    output: list[MemorySearchResult] = []
    for item in reranked:
        memory_id = int(getattr(item.record, "id"))
        original = result_by_id[memory_id]
        metadata = dict(original.metadata or {})
        metadata["_reranking"] = item.explanation.to_dict()
        output.append(
            MemorySearchResult(
                id=original.id,
                content=original.content,
                memory_type=original.memory_type,
                importance=original.importance,
                score=original.score,
                metadata=metadata,
            )
        )
    return output


def _records_by_id(service: Any, memory_ids: Iterable[int]) -> dict[int, MemoryRecord]:
    try:
        records = (
            service.db.query(MemoryRecord)
            .filter(MemoryRecord.id.in_(list(memory_ids)))
            .all()
        )
        return {int(record.id): record for record in records}
    except Exception:
        return {}


def _utc_now(service: Any):
    try:
        return service._utc_now()  # noqa: SLF001 - wrapper lives beside MemoryService internals.
    except Exception:
        return None


def _relation_signals(
    service: Any,
    *,
    agent_id: str | None,
    memory_ids: list[int],
) -> dict[int, MemoryRelationSignal]:
    signals: dict[int, MemoryRelationSignal] = {
        int(memory_id): MemoryRelationSignal() for memory_id in memory_ids
    }
    if not agent_id or not memory_ids:
        return signals

    memory_id_strings = [str(memory_id) for memory_id in memory_ids]
    try:
        relations = (
            service.db.query(KnowledgeRelationRecord)
            .filter(
                KnowledgeRelationRecord.agent_id == agent_id,
                KnowledgeRelationRecord.active == True,  # noqa: E712 - SQLAlchemy expression.
                or_(
                    and_(
                        KnowledgeRelationRecord.source_type == "memory",
                        KnowledgeRelationRecord.source_id.in_(memory_id_strings),
                    ),
                    and_(
                        KnowledgeRelationRecord.target_type == "memory",
                        KnowledgeRelationRecord.target_id.in_(memory_id_strings),
                    ),
                ),
            )
            .all()
        )
    except Exception:
        return signals

    for relation in relations:
        try:
            if relation.source_type == "memory":
                memory_id = int(relation.source_id)
                other_type = str(relation.target_type or "")
            else:
                memory_id = int(relation.target_id)
                other_type = str(relation.source_type or "")
        except (TypeError, ValueError):
            continue

        signal = signals.setdefault(memory_id, MemoryRelationSignal())
        signal.relation_count += 1
        signal.max_strength = max(signal.max_strength, float(relation.strength or 0.0))
        signal.max_confidence = max(signal.max_confidence, float(relation.confidence or 0.0))
        if relation.relation_type:
            signal.relation_types.append(str(relation.relation_type))

        normalised_other_type = other_type.lower()
        if normalised_other_type in {"goal", "agent_goal", "plan_step"}:
            signal.active_goal_count += 1
        elif normalised_other_type in {"lorebook", "lorebook_entry", "lore"}:
            signal.lorebook_count += 1
        elif normalised_other_type in {"entity_state", "entity", "faction", "quest", "location", "object"}:
            signal.entity_state_count += 1

    return signals

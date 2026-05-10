from __future__ import annotations

from datetime import datetime, timedelta, timezone

from mozok.memory.reranker import (
    MemoryRelationSignal,
    MemoryReranker,
    MemoryRerankingContext,
    explanation_from_memory_metadata,
)


class FakeMemory:
    def __init__(
        self,
        memory_id: int,
        *,
        memory_type: str = "semantic",
        importance: int = 5,
        emotional_weight: float = 0.0,
        access_count: int = 0,
        created_at=None,
    ):
        self.id = memory_id
        self.memory_type = memory_type
        self.importance = importance
        self.emotional_weight = emotional_weight
        self.created_at = created_at
        self.updated_at = created_at
        self.last_accessed_at = None
        self.metadata_json = {"access_count": access_count}


def test_reranker_prefers_important_recent_connected_memory():
    now = datetime(2026, 5, 10, tzinfo=timezone.utc)
    weak = FakeMemory(1, memory_type="raw", importance=2, created_at=now - timedelta(days=300))
    strong = FakeMemory(
        2,
        memory_type="semantic",
        importance=9,
        emotional_weight=2.0,
        access_count=7,
        created_at=now - timedelta(days=2),
    )

    result = MemoryReranker().rerank(
        [weak, strong],
        vector_scores={1: 0.70, 2: 0.70},
        context=MemoryRerankingContext(
            now=now,
            relation_signals={
                2: MemoryRelationSignal(
                    relation_count=2,
                    active_goal_count=1,
                    lorebook_count=1,
                    max_strength=1.0,
                    max_confidence=1.0,
                    relation_types=["supports", "depends_on"],
                )
            },
        ),
    )

    assert [item.record.id for item in result] == [2, 1]
    explanation = result[0].explanation.to_dict()
    assert explanation["memory_id"] == 2
    assert explanation["score_parts"]["active_goal_boost"] > 0
    assert explanation["score_parts"]["lore_entity_boost"] > 0
    assert "linked to active goal context" in explanation["reason"]


def test_reranking_explanation_can_be_read_from_metadata():
    memory = FakeMemory(10)
    memory.metadata_json["_reranking"] = {
        "memory_id": 10,
        "final_score": 1.23,
        "score_parts": {"vector_score": 0.7},
        "reason": "Selected because of strong semantic match.",
    }

    assert explanation_from_memory_metadata(memory)["final_score"] == 1.23

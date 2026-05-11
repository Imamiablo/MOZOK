from mozok.context.context_builder import _sort_memory_search_results_by_reranking_score
from mozok.schemas.memory import MemorySearchResult


def make_memory(memory_id: int, final_score: float | None) -> MemorySearchResult:
    metadata = {}
    if final_score is not None:
        metadata["_reranking"] = {
            "memory_id": memory_id,
            "final_score": final_score,
            "score_parts": {"vector_score": final_score},
            "reason": "Test reranking explanation.",
        }
    return MemorySearchResult(
        id=memory_id,
        content=f"memory {memory_id}",
        memory_type="semantic",
        importance=5,
        score=0.0,
        metadata=metadata,
    )


def test_final_order_prefers_reranking_final_score() -> None:
    memories = [
        make_memory(63, 1.333182),
        make_memory(64, 0.835145),
        make_memory(65, 1.065888),
    ]

    ordered = _sort_memory_search_results_by_reranking_score(memories)

    assert [memory.id for memory in ordered] == [63, 65, 64]


def test_final_order_keeps_ties_stable_and_unscored_last() -> None:
    memories = [
        make_memory(1, None),
        make_memory(2, 0.4),
        make_memory(3, 0.4),
        make_memory(4, None),
    ]

    ordered = _sort_memory_search_results_by_reranking_score(memories)

    assert [memory.id for memory in ordered] == [2, 3, 1, 4]

from types import SimpleNamespace

from mozok.context.dedup import ContextMemoryDeduplicator


def memory(memory_id: int, content: str, memory_type: str, importance: int = 5, score: float = 0.0):
    return SimpleNamespace(
        id=memory_id,
        content=content,
        memory_type=memory_type,
        importance=importance,
        score=score,
        metadata={},
    )


def test_context_dedup_keeps_core_over_near_duplicate_semantic():
    deduplicator = ContextMemoryDeduplicator()
    core = memory(
        1,
        "Denys prefers direct practical programming help with exact file by file instructions.",
        "core",
        importance=9,
    )
    duplicate_semantic = memory(
        2,
        "Denys prefers direct practical programming help with exact file-by-file instructions.",
        "semantic",
        importance=8,
        score=0.95,
    )

    result = deduplicator.deduplicate(
        core_memories=[core],
        semantic_memories=[duplicate_semantic],
        episodic_memories=[],
        raw_memories=[],
    )

    assert [m.id for m in result.core_memories] == [1]
    assert result.semantic_memories == []
    assert result.removed_memory_ids == [2]
    assert result.removed[0].kept_id == 1
    assert result.removed[0].kept_source == "core"
    assert result.removed[0].removed_source == "semantic"


def test_context_dedup_keeps_specific_event_separate_from_general_pattern():
    deduplicator = ContextMemoryDeduplicator()
    general_pattern = memory(
        10,
        "Neko-Maria usually steals food and often commits misdeeds in the kitchen.",
        "semantic",
        importance=7,
    )
    specific_event = memory(
        11,
        "Yesterday Neko-Maria stole a beef steak from Denys during dinner.",
        "episodic",
        importance=5,
    )

    result = deduplicator.deduplicate(
        core_memories=[],
        semantic_memories=[general_pattern],
        episodic_memories=[specific_event],
        raw_memories=[],
    )

    assert [m.id for m in result.semantic_memories] == [10]
    assert [m.id for m in result.episodic_memories] == [11]
    assert result.removed_count == 0

from types import SimpleNamespace

from mozok.context.context_builder import ContextBuilder, ContextPackage
from mozok.context.dedup import DedupRemovedMemory
from mozok.context.token_budget import ContextBudgetReport


def memory(memory_id: int, content: str, memory_type: str, importance: int = 5, score: float = 0.0):
    return SimpleNamespace(
        id=memory_id,
        content=content,
        memory_type=memory_type,
        importance=importance,
        score=score,
        metadata={},
        metadata_json={},
    )


class FakeQuery:
    def __init__(self, records):
        self.records = records

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, value):
        return self

    def all(self):
        return list(self.records)


class FakeDb:
    def __init__(self, core_records):
        self.core_records = core_records

    def query(self, model):
        return FakeQuery(self.core_records)


class FakeMemoryService:
    def __init__(self):
        self.calls = []

    def search(self, *, agent_id, query, limit, memory_type, update_access=True):
        self.calls.append(
            {
                "agent_id": agent_id,
                "query": query,
                "limit": limit,
                "memory_type": memory_type,
                "update_access": update_access,
            }
        )
        if memory_type == "semantic":
            return [memory(45, "Denys prefers beginner-friendly programming explanations.", "semantic", 8, 0.4)]
        if memory_type == "episodic":
            return [memory(48, "Yesterday Denys worked on MOZOK context debugging.", "episodic", 5, 0.5)]
        if memory_type == "raw":
            return [memory(49, "User said: pineapple raw memory test special fruit.", "raw", 2, 0.9)]
        return []


def agent():
    return SimpleNamespace(
        id="debug_test_001",
        name="debug_test_001",
        description="Default Mozok agent.",
        personality="Helpful and curious.",
        system_prompt="Use memories when relevant. Do not invent memories.",
    )


def test_context_builder_passes_read_only_flag_to_memory_search():
    core = memory(46, "Core profile: Denys prefers file-by-file instructions.", "core", 9)
    memory_service = FakeMemoryService()
    builder = ContextBuilder(db=FakeDb([core]), memory_service=memory_service)

    context = builder.build(
        agent=agent(),
        user_message="How should you help me with programming?",
        session_id="debug_test_001",
        short_term_limit=0,
        core_limit=10,
        semantic_limit=10,
        episodic_limit=10,
        raw_limit=10,
        update_memory_access=False,
        enforce_token_budget=False,
    )

    assert context.used_memory_ids() == [46, 45, 48, 49]
    assert [call["memory_type"] for call in memory_service.calls] == ["semantic", "episodic", "raw"]
    assert all(call["update_access"] is False for call in memory_service.calls)


def test_context_package_pipeline_steps_show_retrieved_dedup_budget_and_final_prompt():
    core = memory(46, "Core profile: Denys prefers direct programming help.", "core", 9)
    semantic_removed = memory(47, "Denys prefers direct programming help.", "semantic", 8)
    semantic_kept = memory(45, "Denys prefers beginner-friendly explanations.", "semantic", 8)
    episodic = memory(48, "Yesterday Denys worked on MOZOK context debugging.", "episodic", 5)

    package = ContextPackage(
        agent_id="debug_test_001",
        session_id="debug_test_001",
        system_prompt="Use memories when relevant.",
        agent_name="debug_test_001",
        agent_description="Default Mozok agent.",
        agent_personality="Helpful and curious.",
        current_user_message="How should you help me with programming?",
        core_memories=[core],
        semantic_memories=[semantic_kept],
        episodic_memories=[episodic],
        raw_memories=[],
        dedup_removed_memories=[
            DedupRemovedMemory(
                removed_id=47,
                removed_source="semantic",
                kept_id=46,
                kept_source="core",
                similarity=0.92,
                token_overlap=1.0,
                reason="near_duplicate_context_memory; hidden from this prompt only; database memory was not modified",
            )
        ],
        context_budget=ContextBudgetReport(
            enabled=True,
            max_prompt_tokens=6000,
            reserved_response_tokens=1000,
            available_prompt_tokens=5000,
            estimated_prompt_tokens_before=300,
            estimated_prompt_tokens_after=300,
        ),
        retrieved_core_memories=[core],
        retrieved_semantic_memories=[semantic_removed, semantic_kept],
        retrieved_episodic_memories=[episodic],
        retrieved_raw_memories=[],
        post_dedup_core_memories=[core],
        post_dedup_semantic_memories=[semantic_kept],
        post_dedup_episodic_memories=[episodic],
        post_dedup_raw_memories=[],
    )

    steps = package.pipeline_steps()

    assert [step["step"] for step in steps] == ["retrieved", "deduped", "budget_trimmed", "final_prompt"]
    assert steps[0]["counts"]["total_long_term_memories"] == 4
    assert steps[1]["status"] == "changed"
    assert steps[1]["removed_memory_ids"] == [47]
    assert steps[2]["status"] == "ok"
    assert steps[3]["status"] == "ok"
    assert steps[3]["used_memory_ids"] == [46, 45, 48]

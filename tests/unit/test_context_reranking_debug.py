from __future__ import annotations

from mozok.context.context_builder import ContextPackage
from mozok.schemas.memory import MemorySearchResult


def test_context_debug_exposes_memory_reranking_report():
    memory = MemorySearchResult(
        id=42,
        content="Alice knows the old well connects to tunnels.",
        memory_type="semantic",
        importance=8,
        score=1.37,
        metadata={
            "_reranking": {
                "memory_id": 42,
                "final_score": 1.37,
                "score_parts": {"vector_score": 0.72, "importance": 0.16},
                "reason": "Selected because of strong semantic match and high importance.",
            }
        },
    )
    context = ContextPackage(
        agent_id="npc_alice",
        session_id="default",
        system_prompt="Use context only.",
        agent_name="Alice",
        agent_description="Test NPC.",
        agent_personality="Careful.",
        current_user_message="What about the old well?",
        semantic_memories=[memory],
        retrieved_semantic_memories=[memory],
    )

    report = context.memory_reranking_report()
    debug = context.to_debug_dict(include_full_prompt=False)

    assert report[0]["memory_id"] == 42
    assert debug["memory_reranking"][0]["final_score"] == 1.37
    assert debug["pipeline_steps"][0]["memory_reranking"][0]["memory_id"] == 42
    assert debug["pipeline_steps"][-1]["memory_reranking"][0]["reason"].startswith("Selected because")

from types import SimpleNamespace

from mozok.context.context_builder import ContextBuilder, ContextPackage
from mozok.context.token_budget import ContextBudgetPolicy, ContextBudgeter, estimate_tokens
from mozok.memory.short_term_memory import ShortTermMessage


def memory(memory_id: int, content: str, memory_type: str = "semantic"):
    return SimpleNamespace(
        id=memory_id,
        content=content,
        memory_type=memory_type,
        importance=5,
        score=0.5,
        metadata={},
        metadata_json={},
    )


def make_package(**overrides) -> ContextPackage:
    defaults = dict(
        agent_id="budget_v2_agent",
        session_id="budget_v2_session",
        system_prompt="Use provided context only.",
        agent_name="Budget Tester",
        agent_description="Test agent.",
        agent_personality="Careful.",
        current_user_message="What matters here?",
    )
    defaults.update(overrides)
    return ContextPackage(**defaults)


def test_model_aware_token_estimation_changes_estimate_for_cjk_profile():
    text = "これは日本語の長い文章です。" * 20

    generic_tokens = estimate_tokens(text, model_name="generic")
    japanese_tokens = estimate_tokens(text, model_name="japanese")

    assert japanese_tokens > generic_tokens


def test_explicit_section_budget_compresses_memory_before_dropping():
    long_fact = "The old well tunnel detail is important. " * 80
    package = make_package(semantic_memories=[memory(10, long_fact)])

    report = ContextBudgeter(
        ContextBudgetPolicy(
            enforce=True,
            max_prompt_tokens=1200,
            reserved_response_tokens=0,
            section_budget_tokens={"semantic": 90},
            compression_enabled=True,
        )
    ).apply(package)

    prompt = package.to_system_prompt()
    semantic_report = next(item for item in report.section_reports if item.section == "semantic")

    assert report.compressed_count == 1
    assert report.trimmed_count == 0
    assert semantic_report.compressed_count == 1
    assert semantic_report.estimated_tokens_after <= semantic_report.budget_tokens
    assert "[compressed for context budget]" in prompt
    assert package.semantic_memories[0].content == long_fact


def test_short_term_summarisation_keeps_recent_messages_when_over_budget():
    messages = [
        ShortTermMessage(role="user" if i % 2 == 0 else "assistant", content=(f"turn {i} " + "detail " * 80))
        for i in range(8)
    ]
    package = make_package(short_term_messages=messages)

    report = ContextBudgeter(
        ContextBudgetPolicy(
            enforce=True,
            max_prompt_tokens=900,
            reserved_response_tokens=0,
            short_term_summarization_enabled=True,
        )
    ).apply(package)

    assert report.short_term_summary is not None
    assert report.short_term_summary.original_message_count == 8
    assert len(package.short_term_messages) <= 3
    assert package.short_term_messages[0].role == "system"
    assert package.short_term_messages[0].content.startswith("Earlier short-term conversation summary:")


def test_budget_aware_graph_expansion_caps_related_relation_limit():
    builder = ContextBuilder(db=None, memory_service=None)
    policy = ContextBudgetPolicy(
        enforce=True,
        max_prompt_tokens=1000,
        reserved_response_tokens=0,
        section_budget_tokens={"knowledge_relations": 56},
        budget_aware_graph_expansion=True,
    )

    effective_limit = builder._budget_aware_related_relation_limit(
        policy=policy,
        requested_limit=10,
        explicit_relation_count=1,
    )

    assert effective_limit == 1

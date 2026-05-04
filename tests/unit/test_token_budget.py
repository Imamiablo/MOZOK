from types import SimpleNamespace

from mozok.context.token_budget import ContextBudgetPolicy, ContextBudgeter, estimate_tokens


def memory(memory_id: int, content: str):
    return SimpleNamespace(id=memory_id, content=content)


class FakeContextPackage:
    def __init__(self):
        self.core_memories = []
        self.semantic_memories = []
        self.episodic_memories = []
        self.raw_memories = []
        self.short_term_messages = []
        self.base_prompt = "Base prompt and response guidance. " * 8

    def to_system_prompt(self) -> str:
        parts = [self.base_prompt]
        for bucket in [
            self.core_memories,
            self.semantic_memories,
            self.episodic_memories,
            self.raw_memories,
            self.short_term_messages,
        ]:
            parts.extend(item.content for item in bucket)
        return "\n".join(parts)


def test_estimate_tokens_uses_cheap_character_based_estimate():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2


def test_budget_trims_raw_then_episodic_then_semantic_but_keeps_core_when_protected():
    context = FakeContextPackage()
    context.core_memories = [memory(1, "core memory " * 40)]
    context.semantic_memories = [memory(2, "semantic memory " * 40)]
    context.episodic_memories = [memory(3, "episodic memory " * 40)]
    context.raw_memories = [memory(4, "raw memory " * 40)]

    report = ContextBudgeter(
        ContextBudgetPolicy(
            enforce=True,
            max_prompt_tokens=130,
            reserved_response_tokens=0,
            allow_core_trimming=False,
        )
    ).apply(context)

    trimmed_sources = [item.source for item in report.trimmed_items]

    assert trimmed_sources[:3] == ["raw", "episodic", "semantic"]
    assert "core" not in trimmed_sources
    assert [m.id for m in context.core_memories] == [1]
    assert context.raw_memories == []
    assert context.episodic_memories == []
    assert context.semantic_memories == []
    assert "Core/profile memories are protected" in " ".join(report.notes)


def test_budget_can_trim_core_as_last_resort_when_explicitly_allowed():
    context = FakeContextPackage()
    context.core_memories = [memory(1, "core memory " * 80)]

    report = ContextBudgeter(
        ContextBudgetPolicy(
            enforce=True,
            max_prompt_tokens=90,
            reserved_response_tokens=0,
            allow_core_trimming=True,
        )
    ).apply(context)

    assert context.core_memories == []
    assert report.trimmed_items[-1].source == "core"
    assert report.trimmed_items[-1].memory_id == 1
    assert report.trimmed_items[-1].reason == "context_budget_exceeded_trim_core_last_resort"

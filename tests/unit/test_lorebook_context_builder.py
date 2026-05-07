from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from mozok.context.context_builder import ContextBuilder
from mozok.context.token_budget import ContextBudgetPolicy, ContextBudgeter
from mozok.db.models import AgentRecord, Base
from mozok.lorebook.models import AgentLorebookKnowledgeRecord, LorebookEntryRecord  # noqa: F401
from mozok.lorebook.schemas import AgentLorebookKnowledgeUpsert, LorebookContextItem, LorebookEntryUpsert
from mozok.lorebook.service import LorebookService


class FakeMemoryService:
    def search(self, *, agent_id, query, limit, memory_type, update_access=True):
        return []


def make_db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return SessionLocal()


def make_agent(agent_id: str = "npc_bob") -> AgentRecord:
    return AgentRecord(
        id=agent_id,
        name="NPC Bob",
        description="A test NPC.",
        personality="Cautious.",
        system_prompt="Use provided context only.",
    )


def test_context_builder_injects_public_lorebook_into_prompt_and_debug_sections():
    db = make_db_session()
    try:
        LorebookService(db).upsert_entry(
            LorebookEntryUpsert(
                world_id="test_world",
                entry_key="ash_war_history",
                title="Ash War History",
                content="The kingdom was founded after the Ash War.",
                category="history",
                visibility="public",
                importance=7,
            )
        )

        context = ContextBuilder(db=db, memory_service=FakeMemoryService()).build(
            agent=make_agent(),
            user_message="Tell me about the kingdom.",
            short_term_limit=0,
            core_limit=0,
            semantic_limit=0,
            episodic_limit=0,
            raw_limit=0,
            update_memory_access=False,
            enforce_token_budget=False,
            world_id="test_world",
            lorebook_limit=10,
        )

        prompt = context.to_system_prompt()
        debug = context.to_debug_dict()

        assert "Lorebook / world knowledge available to this agent:" in prompt
        assert "The kingdom was founded after the Ash War." in prompt
        assert context.used_lorebook_entry_ids() == [1]
        assert debug["used_lorebook_entry_ids"] == [1]
        assert debug["sections"]["lorebook"][0]["entry_key"] == "ash_war_history"
        assert debug["pipeline_steps"][-1]["used_lorebook_entry_ids"] == [1]
    finally:
        db.close()


def test_context_builder_injects_restricted_lore_only_when_agent_has_knowledge_link():
    db = make_db_session()
    try:
        service = LorebookService(db)
        service.upsert_entry(
            LorebookEntryUpsert(
                world_id="test_world",
                entry_key="old_well_secret",
                title="Old Well Secret",
                content="The old well connects to ancient tunnels.",
                category="location_secret",
                visibility="restricted",
                importance=9,
            )
        )
        service.upsert_agent_knowledge(
            AgentLorebookKnowledgeUpsert(
                agent_id="npc_bob",
                world_id="test_world",
                entry_key="old_well_secret",
                knowledge_state="rumored",
                confidence=4,
            )
        )

        bob_context = ContextBuilder(db=db, memory_service=FakeMemoryService()).build(
            agent=make_agent("npc_bob"),
            user_message="What is near the well?",
            short_term_limit=0,
            core_limit=0,
            semantic_limit=0,
            episodic_limit=0,
            raw_limit=0,
            update_memory_access=False,
            enforce_token_budget=False,
            world_id="test_world",
            lorebook_limit=10,
        )
        alice_context = ContextBuilder(db=db, memory_service=FakeMemoryService()).build(
            agent=make_agent("npc_alice"),
            user_message="What is near the well?",
            short_term_limit=0,
            core_limit=0,
            semantic_limit=0,
            episodic_limit=0,
            raw_limit=0,
            update_memory_access=False,
            enforce_token_budget=False,
            world_id="test_world",
            lorebook_limit=10,
        )

        assert "old well connects" in bob_context.to_system_prompt()
        assert "state=rumored, confidence=4/10" in bob_context.to_system_prompt()
        assert "old well connects" not in alice_context.to_system_prompt()
        assert alice_context.used_lorebook_entry_ids() == []
    finally:
        db.close()


def test_token_budget_can_trim_lorebook_context_after_memory_context():
    context = type("FakeContextPackage", (), {})()
    context.core_memories = []
    context.semantic_memories = []
    context.episodic_memories = []
    context.raw_memories = []
    context.short_term_messages = []
    context.lorebook_items = [
        LorebookContextItem(
            lorebook_entry_id=99,
            world_id="test_world",
            entry_key="large_lore",
            title="Large Lore",
            category="world_truth",
            visibility="public",
            importance=5,
            knowledge_state="public",
            content="lore content " * 120,
        )
    ]

    def to_system_prompt() -> str:
        return "base prompt " * 20 + "\n" + "\n".join(item.content for item in context.lorebook_items)

    context.to_system_prompt = to_system_prompt

    report = ContextBudgeter(
        ContextBudgetPolicy(
            enforce=True,
            max_prompt_tokens=90,
            reserved_response_tokens=0,
            allow_core_trimming=False,
        )
    ).apply(context)

    assert context.lorebook_items == []
    assert report.trimmed_items[-1].source == "lorebook"
    assert report.trimmed_items[-1].memory_id == 99
    assert report.trimmed_items[-1].reason == "context_budget_exceeded_trim_lorebook_after_memories"

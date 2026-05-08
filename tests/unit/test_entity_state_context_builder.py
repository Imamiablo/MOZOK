from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from mozok.context.context_builder import ContextBuilder
from mozok.context.token_budget import ContextBudgetPolicy, ContextBudgeter
from mozok.db.models import AgentRecord, Base
from mozok.entity_state.models import AgentEntityStateRecord  # noqa: F401
from mozok.entity_state.service import EntityStateService
from mozok.schemas.entity_state import EntityStateRead, EntityStateUpsert


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
        name=agent_id,
        description="A test agent.",
        personality="Careful and grounded.",
        system_prompt="Use provided context only.",
    )


def test_context_builder_injects_entity_state_into_prompt_and_debug_sections():
    db = make_db_session()
    try:
        EntityStateService(db).upsert(
            EntityStateUpsert(
                agent_id="npc_bob",
                entity_id="npc_alice",
                entity_name="Alice",
                entity_type="character",
                role="village_healer",
                state_kind="social_relationship",
                attributes={
                    "trust": 0.75,
                    "fear": 0.05,
                    "relationship_label": "trusted healer",
                },
                notes="Bob trusts Alice because she healed him after a wolf attack.",
            )
        )

        context = ContextBuilder(db=db, memory_service=FakeMemoryService()).build(
            agent=make_agent("npc_bob"),
            user_message="How do you feel about Alice?",
            short_term_limit=0,
            core_limit=0,
            semantic_limit=0,
            episodic_limit=0,
            raw_limit=0,
            update_memory_access=False,
            enforce_token_budget=False,
            include_entity_states=True,
            entity_state_limit=10,
        )

        prompt = context.to_system_prompt()
        debug = context.to_debug_dict()

        assert "Entity state context available to this agent:" in prompt
        assert "Alice (npc_alice)" in prompt
        assert "kind=social_relationship" in prompt
        assert "trust=0.75" in prompt
        assert "Bob trusts Alice" in prompt
        assert context.used_entity_state_ids() == [1]
        assert debug["used_entity_state_ids"] == [1]
        assert debug["used_entity_states_count"] == 1
        assert debug["sections"]["entity_states"][0]["state_kind"] == "social_relationship"
        assert debug["pipeline_steps"][-1]["used_entity_state_ids"] == [1]
    finally:
        db.close()


def test_context_builder_entity_state_kind_filter_and_agent_isolation():
    db = make_db_session()
    try:
        service = EntityStateService(db)
        service.upsert(
            EntityStateUpsert(
                agent_id="npc_bob",
                entity_id="npc_alice",
                entity_name="Alice",
                entity_type="character",
                state_kind="social_relationship",
                attributes={"trust": 0.4},
                notes="Bob is cautious around Alice.",
            )
        )
        service.upsert(
            EntityStateUpsert(
                agent_id="npc_bob",
                entity_id="quest_well",
                entity_name="Old Well Quest",
                entity_type="quest",
                state_kind="quest_relevance",
                attributes={"status": "active"},
                notes="Bob thinks the old well quest is urgent.",
            )
        )
        service.upsert(
            EntityStateUpsert(
                agent_id="npc_alice",
                entity_id="npc_bob",
                entity_name="Bob",
                entity_type="character",
                state_kind="social_relationship",
                attributes={"trust": -0.2},
                notes="Alice distrusts Bob.",
            )
        )

        bob_social_context = ContextBuilder(db=db, memory_service=FakeMemoryService()).build(
            agent=make_agent("npc_bob"),
            user_message="Tell me about Alice.",
            short_term_limit=0,
            core_limit=0,
            semantic_limit=0,
            episodic_limit=0,
            raw_limit=0,
            update_memory_access=False,
            enforce_token_budget=False,
            include_entity_states=True,
            entity_state_limit=10,
            entity_state_kind="social_relationship",
        )
        alice_context = ContextBuilder(db=db, memory_service=FakeMemoryService()).build(
            agent=make_agent("npc_alice"),
            user_message="Tell me about Bob.",
            short_term_limit=0,
            core_limit=0,
            semantic_limit=0,
            episodic_limit=0,
            raw_limit=0,
            update_memory_access=False,
            enforce_token_budget=False,
            include_entity_states=True,
            entity_state_limit=10,
        )

        bob_prompt = bob_social_context.to_system_prompt()
        alice_prompt = alice_context.to_system_prompt()

        assert "Bob is cautious around Alice" in bob_prompt
        assert "old well quest is urgent" not in bob_prompt
        assert "Alice distrusts Bob" not in bob_prompt
        assert "Alice distrusts Bob" in alice_prompt
    finally:
        db.close()


def test_token_budget_can_trim_entity_state_context_after_lorebook_context():
    context = type("FakeContextPackage", (), {})()
    context.core_memories = []
    context.semantic_memories = []
    context.episodic_memories = []
    context.raw_memories = []
    context.lorebook_items = []
    context.short_term_messages = []
    context.entity_state_items = [
        EntityStateRead(
            id=123,
            agent_id="npc_bob",
            entity_id="npc_alice",
            entity_name="Alice",
            entity_type="character",
            role="ally",
            state_kind="social_relationship",
            attributes={"trust": 0.9, "long_notes": "relationship context " * 120},
            notes="Bob trusts Alice because she repeatedly helped him survive.",
            metadata={},
            active=True,
        )
    ]

    def to_system_prompt() -> str:
        return "base prompt " * 20 + "\n" + "\n".join(item.notes + str(item.attributes) for item in context.entity_state_items)

    context.to_system_prompt = to_system_prompt

    report = ContextBudgeter(
        ContextBudgetPolicy(
            enforce=True,
            max_prompt_tokens=90,
            reserved_response_tokens=0,
            allow_core_trimming=False,
        )
    ).apply(context)

    assert context.entity_state_items == []
    assert report.trimmed_items[-1].source == "entity_state"
    assert report.trimmed_items[-1].memory_id == 123
    assert report.trimmed_items[-1].reason == "context_budget_exceeded_trim_entity_state_after_lorebook"

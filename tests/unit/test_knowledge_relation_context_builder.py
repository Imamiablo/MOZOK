from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from mozok.context.context_builder import ContextBuilder
from mozok.context.token_budget import ContextBudgetPolicy, ContextBudgeter
from mozok.db.models import AgentRecord, Base
from mozok.knowledge_relations.service import KnowledgeRelationService
from mozok.schemas.knowledge_relations import KnowledgeRelationRead, KnowledgeRelationUpsert


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


def make_agent(agent_id: str = "npc_alice") -> AgentRecord:
    return AgentRecord(
        id=agent_id,
        name="NPC Alice",
        description="A test NPC.",
        personality="Careful.",
        system_prompt="Use provided context only.",
    )


def test_context_builder_injects_knowledge_relation_when_enabled():
    db = make_db_session()
    try:
        KnowledgeRelationService(db).upsert(
            KnowledgeRelationUpsert(
                agent_id="npc_alice",
                world_id="test_world",
                source_type="goal",
                source_id="hide_tunnel_secret",
                relation_type="depends_on",
                target_type="lorebook",
                target_id="old_well",
                strength=1.0,
                confidence=1.0,
                description="Alice's goal depends on the old well secret.",
            )
        )

        context = ContextBuilder(db=db, memory_service=FakeMemoryService()).build(
            agent=make_agent("npc_alice"),
            user_message="What about the well?",
            short_term_limit=0,
            core_limit=0,
            semantic_limit=0,
            episodic_limit=0,
            raw_limit=0,
            update_memory_access=False,
            enforce_token_budget=False,
            include_knowledge_relations=True,
            knowledge_relation_limit=10,
            knowledge_relation_world_id="test_world",
        )

        prompt = context.to_system_prompt()
        debug = context.to_debug_dict()

        assert "Knowledge relations / links available to this agent:" in prompt
        assert "goal:\"hide_tunnel_secret\" depends_on lorebook:\"old_well\"" in prompt
        assert context.used_knowledge_relation_ids() == [1]
        assert debug["used_knowledge_relation_ids"] == [1]
        assert debug["sections"]["knowledge_relations"][0]["target_id"] == "old_well"
        assert debug["pipeline_steps"][-1]["used_knowledge_relation_ids"] == [1]
    finally:
        db.close()


def test_context_builder_does_not_include_knowledge_relation_by_default():
    db = make_db_session()
    try:
        KnowledgeRelationService(db).upsert(
            KnowledgeRelationUpsert(
                agent_id="npc_alice",
                world_id="test_world",
                source_type="goal",
                source_id="hide_tunnel_secret",
                relation_type="depends_on",
                target_type="lorebook",
                target_id="old_well",
                description="Should not appear unless explicitly enabled.",
            )
        )

        context = ContextBuilder(db=db, memory_service=FakeMemoryService()).build(
            agent=make_agent("npc_alice"),
            user_message="What about the well?",
            short_term_limit=0,
            core_limit=0,
            semantic_limit=0,
            episodic_limit=0,
            raw_limit=0,
            update_memory_access=False,
            enforce_token_budget=False,
        )

        assert "Knowledge relations / links" not in context.to_system_prompt()
        assert context.used_knowledge_relation_ids() == []
    finally:
        db.close()


def test_context_builder_filters_knowledge_relations_by_agent():
    db = make_db_session()
    try:
        service = KnowledgeRelationService(db)
        service.upsert(
            KnowledgeRelationUpsert(
                agent_id="npc_alice",
                world_id="test_world",
                source_type="goal",
                source_id="hide_tunnel_secret",
                relation_type="depends_on",
                target_type="lorebook",
                target_id="old_well",
            )
        )

        bob_context = ContextBuilder(db=db, memory_service=FakeMemoryService()).build(
            agent=make_agent("npc_bob"),
            user_message="What about the well?",
            short_term_limit=0,
            core_limit=0,
            semantic_limit=0,
            episodic_limit=0,
            raw_limit=0,
            update_memory_access=False,
            enforce_token_budget=False,
            include_knowledge_relations=True,
            knowledge_relation_limit=10,
            knowledge_relation_world_id="test_world",
        )

        assert bob_context.used_knowledge_relation_ids() == []
        assert "hide_tunnel_secret" not in bob_context.to_system_prompt()
    finally:
        db.close()


def test_token_budget_can_trim_knowledge_relation_context_before_semantic_context():
    context = type("FakeContextPackage", (), {})()
    context.core_memories = []
    context.semantic_memories = []
    context.episodic_memories = []
    context.raw_memories = []
    context.short_term_messages = []
    context.lorebook_items = []
    context.entity_state_items = []
    context.goal_items = []
    context.knowledge_relation_items = [
        KnowledgeRelationRead(
            id=99,
            agent_id="npc_alice",
            world_id="test_world",
            source_type="goal",
            source_id="hide_tunnel_secret",
            relation_type="depends_on",
            target_type="lorebook",
            target_id="old_well",
            description="relation content " * 80,
        )
    ]

    def to_system_prompt() -> str:
        return "base prompt " * 20 + "\n" + "\n".join(item.description for item in context.knowledge_relation_items)

    context.to_system_prompt = to_system_prompt

    report = ContextBudgeter(
        ContextBudgetPolicy(
            enforce=True,
            max_prompt_tokens=90,
            reserved_response_tokens=0,
            allow_core_trimming=False,
        )
    ).apply(context)

    assert context.knowledge_relation_items == []
    assert report.trimmed_items[-1].source == "knowledge_relation"
    assert report.trimmed_items[-1].memory_id == 99


def test_context_builder_auto_expands_related_relation_from_selected_goal():
    from mozok.goals.service import GoalService
    from mozok.schemas.goals import AgentGoalUpsert

    db = make_db_session()
    try:
        GoalService(db).upsert(
            AgentGoalUpsert(
                agent_id="npc_alice",
                goal_key="hide_tunnel_secret",
                title="Hide the tunnel secret",
                goal_type="personal",
                status="active",
                priority=8,
                description="Alice wants to keep outsiders away from the old well.",
                related_lorebook_keys=["old_well"],
            )
        )
        KnowledgeRelationService(db).upsert(
            KnowledgeRelationUpsert(
                agent_id="npc_alice",
                world_id="test_world",
                source_type="goal",
                source_id="hide_tunnel_secret",
                relation_type="depends_on",
                target_type="lorebook",
                target_id="old_well",
                description="This relation should be auto-expanded from the selected goal.",
            )
        )

        context = ContextBuilder(db=db, memory_service=FakeMemoryService()).build(
            agent=make_agent("npc_alice"),
            user_message="What are you trying to do?",
            short_term_limit=0,
            core_limit=0,
            semantic_limit=0,
            episodic_limit=0,
            raw_limit=0,
            update_memory_access=False,
            enforce_token_budget=False,
            include_goals=True,
            goal_limit=10,
            goal_status="active",
            include_knowledge_relations=False,
            include_related_knowledge_relations=True,
            related_knowledge_relation_limit=10,
            knowledge_relation_world_id="test_world",
        )

        prompt = context.to_system_prompt()
        debug = context.to_debug_dict()
        assert context.used_goal_ids() == [1]
        assert context.used_knowledge_relation_ids() == [1]
        assert context.explicit_knowledge_relation_ids() == []
        assert context.auto_expanded_knowledge_relation_ids() == [1]
        assert "goal:\"hide_tunnel_secret\" depends_on lorebook:\"old_well\"" in prompt
        assert debug["auto_expanded_knowledge_relation_ids"] == [1]
        assert any(step["step"] == "related_relations_expanded" for step in debug["pipeline_steps"])
    finally:
        db.close()


def test_context_builder_auto_expanded_relation_does_not_leak_to_other_agent():
    from mozok.goals.service import GoalService
    from mozok.schemas.goals import AgentGoalUpsert

    db = make_db_session()
    try:
        GoalService(db).upsert(
            AgentGoalUpsert(
                agent_id="npc_bob",
                goal_key="hide_tunnel_secret",
                title="Hide the tunnel secret",
                status="active",
            )
        )
        KnowledgeRelationService(db).upsert(
            KnowledgeRelationUpsert(
                agent_id="npc_alice",
                world_id="test_world",
                source_type="goal",
                source_id="hide_tunnel_secret",
                relation_type="depends_on",
                target_type="lorebook",
                target_id="old_well",
                description="Alice-only relation.",
            )
        )

        context = ContextBuilder(db=db, memory_service=FakeMemoryService()).build(
            agent=make_agent("npc_bob"),
            user_message="What are you trying to do?",
            short_term_limit=0,
            core_limit=0,
            semantic_limit=0,
            episodic_limit=0,
            raw_limit=0,
            update_memory_access=False,
            enforce_token_budget=False,
            include_goals=True,
            goal_limit=10,
            include_related_knowledge_relations=True,
            related_knowledge_relation_limit=10,
            knowledge_relation_world_id="test_world",
        )

        assert context.used_knowledge_relation_ids() == []
        assert "Alice-only relation" not in context.to_system_prompt()
    finally:
        db.close()

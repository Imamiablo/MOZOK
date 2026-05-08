from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from mozok.context.context_builder import ContextBuilder
from mozok.context.token_budget import ContextBudgetPolicy, ContextBudgeter
from mozok.db.models import AgentRecord, Base
from mozok.goals.models import AgentGoalRecord  # noqa: F401
from mozok.goals.service import GoalService, format_goal_for_prompt_line
from mozok.schemas.goals import AgentGoalRead, AgentGoalUpsert


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
        name=agent_id,
        description="A test agent.",
        personality="Careful and secretive.",
        system_prompt="Use provided context only.",
    )


def test_goal_prompt_line_is_compact_and_contains_plan_steps():
    goal = AgentGoalRead(
        id=1,
        agent_id="npc_alice",
        goal_key="hide_tunnel_secret",
        title="Hide the tunnel secret",
        goal_type="personal",
        status="active",
        priority=8,
        description="Alice wants to prevent outsiders from learning that the old well connects to tunnels.",
        success_criteria=["The player leaves the well alone"],
        related_entity_ids=["old_well", "npc_bob"],
        related_lorebook_keys=["old_well"],
        plan_steps=[
            {"step_key": "deflect_questions", "description": "Give vague answers about the well.", "status": "active"},
        ],
        notes="Alice is protective of the tunnel secret.",
        metadata={},
        active=True,
    )

    line = format_goal_for_prompt_line(goal)

    assert "Hide the tunnel secret" in line
    assert "status=active" in line
    assert "priority=8" in line
    assert "Give vague answers" in line
    assert "old_well" in line


def test_context_builder_injects_goals_into_prompt_and_debug_sections():
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
                description="Alice wants to prevent outsiders from learning that the old well connects to tunnels.",
                success_criteria=["The player leaves the well alone"],
                related_entity_ids=["old_well", "npc_bob"],
                related_lorebook_keys=["old_well"],
                plan_steps=[
                    {"step_key": "deflect_questions", "description": "Give vague answers about the well.", "status": "active"}
                ],
                notes="Alice is protective of the tunnel secret.",
            )
        )

        context = ContextBuilder(db=db, memory_service=FakeMemoryService()).build(
            agent=make_agent("npc_alice"),
            user_message="What do you want to do about the old well?",
            short_term_limit=0,
            core_limit=0,
            semantic_limit=0,
            episodic_limit=0,
            raw_limit=0,
            update_memory_access=False,
            enforce_token_budget=False,
            include_goals=True,
            goal_limit=10,
        )

        prompt = context.to_system_prompt()
        debug = context.to_debug_dict()

        assert "Goals / plans currently active for this agent" in prompt
        assert "Hide the tunnel secret" in prompt
        assert "Give vague answers" in prompt
        assert context.used_goal_ids()
        assert debug["used_goals_count"] == 1
        assert debug["sections"]["goals"][0]["goal_key"] == "hide_tunnel_secret"
        assert debug["pipeline_steps"][0]["counts"]["goal_items"] == 1
    finally:
        db.close()


def test_context_builder_goal_status_filter_and_agent_isolation():
    db = make_db_session()
    try:
        service = GoalService(db)
        service.upsert(
            AgentGoalUpsert(
                agent_id="npc_alice",
                goal_key="active_secret_goal",
                title="Keep the secret",
                status="active",
                priority=9,
                description="Alice must keep the old well secret.",
            )
        )
        service.upsert(
            AgentGoalUpsert(
                agent_id="npc_alice",
                goal_key="completed_errand",
                title="Completed errand",
                status="completed",
                priority=2,
                description="Alice already delivered the herbs.",
            )
        )
        service.upsert(
            AgentGoalUpsert(
                agent_id="npc_bob",
                goal_key="ask_alice",
                title="Ask Alice",
                status="active",
                priority=4,
                description="Bob wants to ask Alice about the well.",
            )
        )

        alice_active_context = ContextBuilder(db=db, memory_service=FakeMemoryService()).build(
            agent=make_agent("npc_alice"),
            user_message="What is your current priority?",
            short_term_limit=0,
            core_limit=0,
            semantic_limit=0,
            episodic_limit=0,
            raw_limit=0,
            update_memory_access=False,
            enforce_token_budget=False,
            include_goals=True,
            goal_status="active",
        )
        bob_context = ContextBuilder(db=db, memory_service=FakeMemoryService()).build(
            agent=make_agent("npc_bob"),
            user_message="What is your current priority?",
            short_term_limit=0,
            core_limit=0,
            semantic_limit=0,
            episodic_limit=0,
            raw_limit=0,
            update_memory_access=False,
            enforce_token_budget=False,
            include_goals=True,
        )

        alice_prompt = alice_active_context.to_system_prompt()
        bob_prompt = bob_context.to_system_prompt()

        assert "Keep the secret" in alice_prompt
        assert "Completed errand" not in alice_prompt
        assert "Ask Alice" not in alice_prompt
        assert "Ask Alice" in bob_prompt
        assert "Keep the secret" not in bob_prompt
    finally:
        db.close()


def test_token_budget_can_trim_goal_context_after_entity_state_context():
    context = type("FakeContextPackage", (), {})()
    context.core_memories = []
    context.semantic_memories = []
    context.episodic_memories = []
    context.raw_memories = []
    context.lorebook_items = []
    context.entity_state_items = []
    context.short_term_messages = []
    context.goal_items = [
        AgentGoalRead(
            id=456,
            agent_id="npc_alice",
            goal_key="very_long_goal",
            title="Very Long Goal",
            goal_type="narrative",
            status="active",
            priority=10,
            description="goal context " * 150,
            success_criteria=[],
            failure_conditions=[],
            related_entity_ids=[],
            related_lorebook_keys=[],
            plan_steps=[],
            notes="Protect the plot secret.",
            metadata={},
            active=True,
        )
    ]

    def to_system_prompt() -> str:
        return "base prompt " * 20 + "\n" + "\n".join(item.description for item in context.goal_items)

    context.to_system_prompt = to_system_prompt

    report = ContextBudgeter(
        ContextBudgetPolicy(
            enforce=True,
            max_prompt_tokens=90,
            reserved_response_tokens=0,
            allow_core_trimming=False,
        )
    ).apply(context)

    assert context.goal_items == []
    assert report.trimmed_items[-1].source == "goal"
    assert report.trimmed_items[-1].memory_id == 456
    assert report.trimmed_items[-1].reason == "context_budget_exceeded_trim_goal_after_entity_state"

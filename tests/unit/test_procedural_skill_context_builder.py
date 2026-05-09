from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from mozok.context.context_builder import ContextBuilder
from mozok.context.token_budget import ContextBudgetPolicy, ContextBudgeter
from mozok.db.models import AgentRecord, Base
from mozok.procedural_skills.service import ProceduralSkillService
from mozok.schemas.procedural_skills import AgentProceduralSkillRead, AgentProceduralSkillUpsert


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


def make_skill(agent_id: str = "npc_alice", status: str = "active") -> AgentProceduralSkillUpsert:
    return AgentProceduralSkillUpsert(
        agent_id=agent_id,
        skill_key="deflect_dangerous_questions",
        title="Deflect dangerous questions",
        skill_type="conversation",
        status=status,
        priority=8,
        description="Avoid revealing dangerous secrets while sounding calm and helpful.",
        trigger={"when": "Someone asks about a secret or forbidden place."},
        procedure=[
            "Acknowledge the question without panic.",
            "Give a partial truth if possible.",
            "Redirect toward safety or uncertainty.",
        ],
        examples=[
            {
                "situation": "Player asks about the old well.",
                "good_response": "The well is old. People here prefer to leave old things alone.",
            }
        ],
        related_goal_keys=["hide_tunnel_secret"],
        related_lorebook_keys=["old_well"],
        notes="Alice should sound evasive but not obviously guilty.",
    )


def test_context_builder_injects_procedural_skill_when_enabled():
    db = make_db_session()
    try:
        ProceduralSkillService(db).upsert(make_skill())

        context = ContextBuilder(db=db, memory_service=FakeMemoryService()).build(
            agent=make_agent("npc_alice"),
            user_message="What do you know about the old well?",
            short_term_limit=0,
            core_limit=0,
            semantic_limit=0,
            episodic_limit=0,
            raw_limit=0,
            update_memory_access=False,
            enforce_token_budget=False,
            include_procedural_skills=True,
            procedural_skill_limit=10,
            procedural_skill_status="active",
        )

        prompt = context.to_system_prompt()
        debug = context.to_debug_dict()

        assert "Procedural skills / behavior strategies available to this agent:" in prompt
        assert "Deflect dangerous questions" in prompt
        assert "Redirect toward safety" in prompt
        assert context.used_procedural_skill_ids() == [1]
        assert debug["used_procedural_skill_ids"] == [1]
        assert debug["sections"]["procedural_skills"][0]["skill_key"] == "deflect_dangerous_questions"
    finally:
        db.close()


def test_context_builder_does_not_include_procedural_skills_by_default():
    db = make_db_session()
    try:
        ProceduralSkillService(db).upsert(make_skill())

        context = ContextBuilder(db=db, memory_service=FakeMemoryService()).build(
            agent=make_agent("npc_alice"),
            user_message="What do you know about the old well?",
            short_term_limit=0,
            core_limit=0,
            semantic_limit=0,
            episodic_limit=0,
            raw_limit=0,
            update_memory_access=False,
            enforce_token_budget=False,
        )

        assert context.used_procedural_skill_ids() == []
        assert "Procedural skills / behavior strategies" not in context.to_system_prompt()
    finally:
        db.close()


def test_context_builder_filters_procedural_skills_by_agent():
    db = make_db_session()
    try:
        ProceduralSkillService(db).upsert(make_skill(agent_id="npc_alice"))

        bob_context = ContextBuilder(db=db, memory_service=FakeMemoryService()).build(
            agent=make_agent("npc_bob"),
            user_message="What do you know about the old well?",
            short_term_limit=0,
            core_limit=0,
            semantic_limit=0,
            episodic_limit=0,
            raw_limit=0,
            update_memory_access=False,
            enforce_token_budget=False,
            include_procedural_skills=True,
            procedural_skill_limit=10,
        )

        assert bob_context.used_procedural_skill_ids() == []
        assert "Deflect dangerous questions" not in bob_context.to_system_prompt()
    finally:
        db.close()


def test_token_budget_can_trim_procedural_skill_context():
    context = type("FakeContextPackage", (), {})()
    context.core_memories = []
    context.semantic_memories = []
    context.episodic_memories = []
    context.raw_memories = []
    context.short_term_messages = []
    context.lorebook_items = []
    context.entity_state_items = []
    context.goal_items = []
    context.knowledge_relation_items = []
    context.procedural_skill_items = [
        AgentProceduralSkillRead(
            id=99,
            agent_id="npc_alice",
            skill_key="very_long_skill",
            title="Very Long Skill",
            skill_type="conversation",
            status="active",
            priority=8,
            description="skill content " * 80,
            procedure=["step content " * 80],
        )
    ]

    def to_system_prompt() -> str:
        return "base prompt " * 20 + "\n" + "\n".join(item.description for item in context.procedural_skill_items)

    context.to_system_prompt = to_system_prompt

    report = ContextBudgeter(
        ContextBudgetPolicy(
            enforce=True,
            max_prompt_tokens=90,
            reserved_response_tokens=0,
            allow_core_trimming=False,
        )
    ).apply(context)

    assert context.procedural_skill_items == []
    assert report.trimmed_items[-1].source == "procedural_skill"
    assert report.trimmed_items[-1].memory_id == 99


def make_teaching_skill(agent_id: str = "npc_alice") -> AgentProceduralSkillUpsert:
    return AgentProceduralSkillUpsert(
        agent_id=agent_id,
        skill_key="explain_herbal_medicine",
        title="Explain herbal medicine",
        skill_type="teaching",
        status="active",
        priority=9,
        description="Explain safe use of herbs and remedies.",
        trigger={"when": "Someone asks about healing herbs.", "keywords": ["herb", "medicine", "healing"]},
        procedure=["Explain the herb clearly."],
        related_goal_keys=[],
        related_lorebook_keys=["moonflower"],
        related_entity_ids=[],
    )


def test_relevant_procedural_skill_selection_prefers_matching_skill_over_priority():
    db = make_db_session()
    try:
        ProceduralSkillService(db).upsert(make_skill())
        ProceduralSkillService(db).upsert(make_teaching_skill())

        context = ContextBuilder(db=db, memory_service=FakeMemoryService()).build(
            agent=make_agent("npc_alice"),
            user_message="What do you know about the old well and the tunnels?",
            short_term_limit=0,
            core_limit=0,
            semantic_limit=0,
            episodic_limit=0,
            raw_limit=0,
            update_memory_access=False,
            enforce_token_budget=False,
            include_procedural_skills=True,
            procedural_skill_limit=1,
            select_relevant_procedural_skills=True,
            procedural_skill_fallback_to_priority=True,
        )

        assert context.used_procedural_skill_ids() == [1]
        assert context.procedural_skill_items[0].skill_key == "deflect_dangerous_questions"
        assert context.procedural_skill_selection[0]["skill_key"] == "deflect_dangerous_questions"
        assert context.procedural_skill_selection[0]["matched_keywords"]
        reasons_text = "; ".join(context.procedural_skill_selection[0]["reasons"])

        assert (
                "trigger keyword match" in reasons_text
                or "trigger description overlaps current message" in reasons_text
                or "related lorebook key" in reasons_text
        )
    finally:
        db.close()


def test_relevant_procedural_skill_selection_can_match_active_goal_key():
    db = make_db_session()
    try:
        ProceduralSkillService(db).upsert(make_skill())
        ProceduralSkillService(db).upsert(make_teaching_skill())

        context = ContextBuilder(db=db, memory_service=FakeMemoryService()).build(
            agent=make_agent("npc_alice"),
            user_message="Please answer carefully.",
            short_term_limit=0,
            core_limit=0,
            semantic_limit=0,
            episodic_limit=0,
            raw_limit=0,
            update_memory_access=False,
            enforce_token_budget=False,
            include_goals=True,
            goal_limit=10,
            include_procedural_skills=True,
            procedural_skill_limit=1,
            select_relevant_procedural_skills=True,
            procedural_skill_fallback_to_priority=False,
        )

        # No goals were created, so there is no related_goal_keys match and no fallback.
        assert context.used_procedural_skill_ids() == []

        from mozok.goals.service import GoalService
        from mozok.schemas.goals import AgentGoalUpsert
        GoalService(db).upsert(AgentGoalUpsert(
            agent_id="npc_alice",
            goal_key="hide_tunnel_secret",
            title="Hide the tunnel secret",
            goal_type="personal",
            status="active",
            priority=8,
            description="Avoid revealing the well tunnels.",
        ))

        context = ContextBuilder(db=db, memory_service=FakeMemoryService()).build(
            agent=make_agent("npc_alice"),
            user_message="Please answer carefully.",
            short_term_limit=0,
            core_limit=0,
            semantic_limit=0,
            episodic_limit=0,
            raw_limit=0,
            update_memory_access=False,
            enforce_token_budget=False,
            include_goals=True,
            goal_limit=10,
            include_procedural_skills=True,
            procedural_skill_limit=1,
            select_relevant_procedural_skills=True,
            procedural_skill_fallback_to_priority=False,
        )

        assert context.procedural_skill_items[0].skill_key == "deflect_dangerous_questions"
        assert context.procedural_skill_selection[0]["matched_goal_keys"] == ["hide_tunnel_secret"]
    finally:
        db.close()

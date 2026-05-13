from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from mozok.agent_modes.service import AgentModeService
from mozok.context.context_builder import ContextBuilder
from mozok.db.models import AgentRecord, Base
from mozok.entity_state.service import EntityStateService
from mozok.schemas.entity_state import EntityStateUpsert


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


def make_agent(agent_id="agent_1", metadata=None):
    return AgentRecord(
        id=agent_id,
        name=agent_id,
        description="Test agent.",
        personality="Careful.",
        system_prompt="Use provided context only.",
        metadata_json=metadata or {},
    )


def test_agent_mode_resolver_uses_builtin_and_metadata_overrides():
    agent = make_agent(
        "npc_alice",
        metadata={
            "agent_mode": "simulacra_npc",
            "agent_mode_profile": {
                "label": "Village NPC",
                "metadata": {"scenario": "old_well"},
            },
        },
    )

    resolved = AgentModeService().resolve(agent)

    assert resolved.profile.mode == "simulacra_npc"
    assert resolved.profile.label == "Village NPC"
    assert resolved.profile.enable_cognitive_field_by_default is True
    assert resolved.profile.enable_perception_by_default is True
    assert resolved.profile.can_autonomously_tick is True
    assert resolved.profile.metadata["scenario"] == "old_well"


def test_context_builder_includes_mode_guidance_and_debug_report():
    db = make_db_session()
    try:
        context = ContextBuilder(db=db, memory_service=FakeMemoryService()).build(
            agent=make_agent("npc_alice", metadata={"agent_mode": "simulacra_npc"}),
            user_message="What do you do next?",
            short_term_limit=0,
            core_limit=0,
            semantic_limit=0,
            episodic_limit=0,
            raw_limit=0,
            update_memory_access=False,
            enforce_token_budget=False,
        )

        debug = context.to_debug_dict()
        prompt = context.to_system_prompt()

        assert debug["agent_mode"]["mode"] == "simulacra_npc"
        assert debug["agent_mode_resolution"]["source"] == "agent_metadata"
        assert "Agent operating mode:" in prompt
        assert "simulacra_npc" in prompt
        assert "local world participant" in prompt
    finally:
        db.close()


def test_agent_mode_filters_entity_state_kinds_for_assistant():
    db = make_db_session()
    try:
        service = EntityStateService(db)
        service.upsert(
            EntityStateUpsert(
                agent_id="assistant_1",
                entity_id="user_1",
                entity_name="User",
                state_kind="assistant_user_profile",
                notes="The user prefers concise explanations.",
            )
        )
        service.upsert(
            EntityStateUpsert(
                agent_id="assistant_1",
                entity_id="npc_bob",
                entity_name="Bob",
                state_kind="social_relationship",
                notes="This kind should not be included by assistant mode defaults.",
            )
        )

        context = ContextBuilder(db=db, memory_service=FakeMemoryService()).build(
            agent=make_agent("assistant_1", metadata={"agent_mode": "assistant"}),
            user_message="What do you know about me?",
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

        assert [item.state_kind for item in context.entity_state_items] == ["assistant_user_profile"]
        assert "The user prefers concise explanations" in context.to_system_prompt()
        assert "This kind should not be included" not in context.to_system_prompt()
    finally:
        db.close()


def test_narrator_mode_defaults_allow_narrator_only_lore_flag_in_resolution():
    agent = make_agent("narrator", metadata={"agent_mode": "narrator"})
    resolved = AgentModeService().resolve(agent)

    assert resolved.profile.allow_narrator_only_lore is True
    assert "narrator" in resolved.profile.mode


def test_agent_mode_routes_are_registered_in_openapi():
    from fastapi.testclient import TestClient

    from mozok.api.main import app

    schema = app.openapi()
    assert "/agent-modes" in schema["paths"]
    assert "/agent-modes/{mode}" in schema["paths"]
    assert "/agents/{agent_id}/agent-mode/resolve" in schema["paths"]

    served_schema = TestClient(app).get("/openapi.json").json()
    assert "/agents/{agent_id}/agent-mode/resolve" in served_schema["paths"]
    assert "agent_mode" in schema["components"]["schemas"]["ChatRequest"]["properties"]
    assert "agent_mode" in schema["components"]["schemas"]["ContextDebugRequest"]["properties"]

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from mozok.action_execution.schemas import (
    ActionExecutionRequest,
    ActionExecutionResultUpdateRequest,
    ActionToolRegistryEntry,
    ActionToolRegistryUpdateRequest,
)
from mozok.action_execution.service import ActionExecutionService
from mozok.action_planning.schemas import ActionToolSpec
from mozok.belief_revision.schemas import BeliefClaim, BeliefRevisionRequest
from mozok.belief_revision.service import BeliefRevisionService
from mozok.core.bot_core import BotCore
from mozok.db.models import AgentRecord, MemoryRecord
from mozok.db.session import Base
from mozok.entity_state.models import AgentEntityStateRecord
from mozok.goals.models import AgentGoalRecord
from mozok.reflection.schemas import (
    ReflectionBeliefRevisionTrigger,
    ReflectionEntityStateUpdateHint,
    ReflectionGoalUpdateHint,
    ReflectionRequest,
)
from mozok.reflection.service import ReflectionService
from mozok.world_events.schemas import (
    WorldEventAcknowledgeRequest,
    WorldEventConsumeRequest,
    WorldEventCreate,
    WorldEventCreateRequest,
    WorldEventExpireRequest,
    WorldEventSearchRequest,
)
from mozok.world_events.service import WorldEventService


class FakeMemoryService:
    def search(self, *args, **kwargs):
        return []

    def add_memory(self, data):
        return MemoryRecord(id=999, agent_id=data.agent_id, memory_type=data.memory_type, content=data.content, metadata_json={})


class FakeLLM:
    def chat(self, system_prompt: str, user_message: str) -> str:
        assert "Self-model / reflective state" in system_prompt
        assert "Action plan / adapter intent" in system_prompt
        return "I will handle this carefully."


def make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def seed_tool_agent(db):
    db.add(AgentRecord(id="tool_agent", name="Tool Agent", metadata_json={"agent_mode": "tool_agent"}))
    db.commit()


def test_action_execution_layer_registers_permissions_queues_and_records_adapter_result():
    db = make_db()
    seed_tool_agent(db)
    service = ActionExecutionService(db)

    registry = service.update_registry(
        "tool_agent",
        ActionToolRegistryUpdateRequest(
            tools=[
                ActionToolRegistryEntry(
                    name="move_to_location",
                    description="Move a character to a named place.",
                    action_kind="game_command",
                    risk_level="medium",
                    requires_approval=True,
                    max_retries=1,
                    tags=["move", "location"],
                )
            ]
        ),
    )
    assert registry.tool_count == 1

    blocked = service.execute(
        "tool_agent",
        ActionExecutionRequest(tool_name="move_to_location", action_kind="game_command", parameters={"location": "old_well"}),
    )
    assert blocked.execution.status == "blocked"
    assert blocked.execution.permission.decision == "needs_approval"
    assert blocked.execution.rollback_snapshot is not None

    queued = service.execute(
        "tool_agent",
        ActionExecutionRequest(
            tool_name="move_to_location",
            action_kind="game_command",
            parameters={"location": "old_well"},
            approval_granted=True,
        ),
    )
    assert queued.execution.status == "queued_for_adapter"
    assert queued.execution.adapter_owned is True

    updated = service.update_result(
        "tool_agent",
        queued.execution.execution_id,
        ActionExecutionResultUpdateRequest(status="completed", result={"ok": True}, notes=["Adapter moved NPC."]),
    )
    assert updated is not None
    assert updated.execution.status == "completed"
    assert updated.execution.result["ok"] is True


def test_chat_can_inject_self_model_and_action_plan(monkeypatch):
    db = make_db()
    seed_tool_agent(db)

    import mozok.core.bot_core as bot_core

    monkeypatch.setattr(bot_core, "get_memory_service", lambda db: FakeMemoryService())
    monkeypatch.setattr(bot_core, "OllamaOpenAIClient", lambda: FakeLLM())

    response = BotCore(db).chat(
        agent_id="tool_agent",
        message="Move to the old well if that is allowed.",
        enable_cognitive_field=True,
        enable_self_model=True,
        enable_action_planning=True,
        available_tools=[
            ActionToolSpec(
                name="move_to_location",
                description="Move a character to a named place.",
                action_kind="game_command",
                risk_level="medium",
                tags=["move", "old", "well"],
            )
        ],
    )

    assert response.self_model is not None
    assert response.action_plan is not None
    assert response.action_plan["selected_action"] is not None
    assert response.response == "I will handle this carefully."


def test_reflection_learning_v2_creates_first_class_goal_entity_and_belief_proposals():
    db = make_db()
    db.add(AgentRecord(id="reflect_agent", name="Reflect Agent"))
    db.add(AgentGoalRecord(id=1, agent_id="reflect_agent", goal_key="investigate_well", title="Investigate well"))
    db.add(
        AgentEntityStateRecord(
            id=1,
            agent_id="reflect_agent",
            entity_id="npc_alice",
            entity_name="Alice",
            state_kind="narrative_entity",
            attributes_json={"location": "village"},
        )
    )
    db.commit()

    response = ReflectionService(db).reflect(
        ReflectionRequest(
            agent_id="reflect_agent",
            user_message="Actually, Alice is now near the old well.",
            assistant_response="Noted.",
            goal_update_hints=[ReflectionGoalUpdateHint(goal_id=1, patch={"status": "active", "notes": "Alice moved closer to the old well."})],
            entity_state_update_hints=[ReflectionEntityStateUpdateHint(state_id=1, patch={"attributes": {"location": "old_well"}})],
            belief_revision_triggers=[ReflectionBeliefRevisionTrigger(claim_content="Alice is now near the old well.")],
            create_change_proposals=True,
            store_proposals=True,
        )
    )

    proposal_types = {proposal.proposal_type for proposal in response.proposals}
    assert "reflection_goal_update" in proposal_types
    assert "reflection_entity_state_update" in proposal_types
    assert "reflection_belief_revision" in proposal_types

    goal_proposal = next(proposal for proposal in response.proposals if proposal.proposal_type == "reflection_goal_update")
    entity_proposal = next(proposal for proposal in response.proposals if proposal.proposal_type == "reflection_entity_state_update")
    belief_proposal = next(proposal for proposal in response.proposals if proposal.proposal_type == "reflection_belief_revision")
    assert goal_proposal.operations[0].operation_type == "update_goal"
    assert entity_proposal.operations[0].operation_type == "update_entity_state"
    assert belief_proposal.operations[0].operation_type == "update_agent_metadata"


def test_belief_graph_v2_adds_temporal_confidence_and_relation_payloads():
    db = make_db()
    db.add(AgentRecord(id="npc_alice", name="Alice"))
    db.add(
        MemoryRecord(
            agent_id="npc_alice",
            memory_type="semantic",
            content="Bob trusts Alice near the old well.",
            importance=8,
            metadata_json={"belief_confidence": 0.8, "source_trust": 0.6, "valid_until": "2026-01-01"},
        )
    )
    db.commit()

    response = BeliefRevisionService(db).preview(
        "npc_alice",
        BeliefRevisionRequest(
            claim=BeliefClaim(
                content="Bob does not trust Alice near the old well anymore.",
                confidence=0.9,
                source_trust=0.8,
                valid_from="2026-05-01",
            ),
            min_token_overlap=0.2,
            create_change_proposal=True,
        ),
    )

    assert response.belief_graph.edges
    assert response.belief_graph.edges[0].relation == "contradicts"
    assert response.candidates[0].temporal_status == "outdated_by_claim"
    assert response.belief_graph.recommended_relation_payloads
    assert response.proposal is not None
    assert any(op["operation_type"] == "add_knowledge_relation" for op in response.proposal["operations"])


def test_world_event_bus_v2_consumes_acknowledges_and_expires_sql_events():
    db = make_db()
    service = WorldEventService(db)
    created = service.create(
        WorldEventCreateRequest(
            events=[
                WorldEventCreate(
                    world_id="w1",
                    agent_id="npc_alice",
                    content="A metallic sound echoes from the old well.",
                    channel_hint="hearing",
                    salience=8,
                    tags=["well", "sound"],
                    ttl_seconds=60,
                )
            ],
            store=True,
        )
    )
    event_id = created.events[0].event_id

    consumed = service.consume(WorldEventConsumeRequest(world_id="w1", agent_id="npc_alice", tags_any=["well"]))
    assert consumed.consumed_count == 1
    assert "npc_alice" in consumed.events[0].consumed_by_agent_ids

    search_after_consume = service.search(WorldEventSearchRequest(world_id="w1", agent_id="npc_alice", include_consumed=False))
    assert search_after_consume.event_count == 0

    acked = service.acknowledge(WorldEventAcknowledgeRequest(world_id="w1", agent_id="npc_alice", event_ids=[event_id]))
    assert acked.acknowledged_count == 1
    assert "npc_alice" in acked.events[0].acknowledged_by_agent_ids

    expired = service.expire(WorldEventExpireRequest(world_id="w1", event_ids=[event_id]))
    assert expired.expired_count == 1
    inactive = service.search(WorldEventSearchRequest(world_id="w1", include_inactive=True))
    assert inactive.events[0].active is False


def test_v44_48_routes_are_registered_in_openapi():
    from mozok.api.main import app

    schema = app.openapi()
    expected = [
        "/agents/{agent_id}/action-tools",
        "/agents/{agent_id}/actions/execute",
        "/agents/{agent_id}/actions/executions",
        "/world-events/consume",
        "/world-events/ack",
        "/world-events/expire",
    ]
    for path in expected:
        assert path in schema["paths"]

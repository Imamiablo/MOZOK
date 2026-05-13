from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from mozok.action_planning.schemas import ActionPlanRequest, ActionToolSpec, ActionProposalRequest
from mozok.action_planning.service import ActionPlanningService
from mozok.belief_revision.schemas import BeliefClaim, BeliefRevisionRequest
from mozok.belief_revision.service import BeliefRevisionService
from mozok.db.models import AgentRecord, MemoryRecord
from mozok.db.session import Base
from mozok.self_model.schemas import SelfModelProposalRequest, SelfModelRequest
from mozok.self_model.service import SelfModelService


def make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def test_action_planner_returns_intents_without_execution():
    response = ActionPlanningService().plan(
        "npc_alice",
        ActionPlanRequest(
            agent_mode="simulacra_npc",
            user_message="Go to the old well and listen for the metallic sound.",
            cognitive_field={"broadcast": {"selected_label": "Attend well sound", "prompt_guidance": "Investigate cautiously."}},
            sensory_inputs=[{"content": "A metallic sound echoes from the old well.", "attention": 8, "tags": ["well", "sound"]}],
            available_tools=[
                ActionToolSpec(
                    name="move_to_location",
                    description="Move an NPC to a named place in the game world.",
                    action_kind="game_command",
                    risk_level="medium",
                    tags=["go", "move", "location", "well"],
                )
            ],
        ),
    )

    assert response.read_only is True
    assert response.execution_policy["executes_tools"] is False
    assert any(action.tool_name == "move_to_location" for action in response.actions)
    tool_action = next(action for action in response.actions if action.tool_name == "move_to_location")
    assert tool_action.approval_required is True


def test_action_planner_can_store_reviewable_proposal():
    db = make_db()
    db.add(AgentRecord(id="tool_agent", name="Tool Agent", metadata_json={"agent_mode": "tool_agent"}))
    db.commit()

    response = ActionPlanningService(db).propose(
        "tool_agent",
        ActionProposalRequest(
            user_message="Create a calendar event for tomorrow.",
            available_tools=[ActionToolSpec(name="create_calendar_event", description="Create calendar events", tags=["calendar", "event"])],
        ),
    )

    assert response.proposal is not None
    assert response.proposal["proposal_type"] == "action_intent"
    assert response.proposal["status"] == "pending"


def test_self_model_preview_builds_prompt_block_and_proposal():
    db = make_db()
    db.add(AgentRecord(id="npc_alice", name="Alice", metadata_json={"agent_mode": "simulacra_npc"}))
    db.commit()

    preview = SelfModelService(db).preview(
        "npc_alice",
        SelfModelRequest(
            user_message="What is that sound?",
            cognitive_field={"winning_score": 10, "candidate_count": 5, "broadcast": {"working_memory_line": "Attend to the sound near the well."}},
        ),
    )

    assert preview.read_only is True
    assert preview.state.mode == "simulacra_npc"
    assert "Self-model / reflective state" in preview.prompt_block
    assert "Attend to the sound" in preview.prompt_block

    proposed = SelfModelService(db).propose_update(
        "npc_alice",
        SelfModelProposalRequest(user_message="What is that sound?", store_proposal=True),
    )
    assert proposed.proposal is not None
    assert proposed.proposal["proposal_type"] == "self_model"


def test_belief_revision_detects_contradiction_and_creates_proposal():
    db = make_db()
    db.add(AgentRecord(id="npc_alice", name="Alice"))
    db.add(
        MemoryRecord(
            agent_id="npc_alice",
            memory_type="semantic",
            content="Bob trusts Alice near the old well.",
            importance=5,
            emotional_weight=0.0,
            metadata_json={},
        )
    )
    db.commit()

    response = BeliefRevisionService(db).preview(
        "npc_alice",
        BeliefRevisionRequest(
            claim=BeliefClaim(content="Bob does not trust Alice near the old well anymore."),
            min_token_overlap=0.2,
            create_change_proposal=True,
        ),
    )

    assert response.read_only is False
    assert response.recommended_action == "review_contradiction"
    assert any(candidate.relation == "contradicts" for candidate in response.candidates)
    assert response.proposal is not None
    assert response.proposal["proposal_type"] == "belief_revision"


def test_v38_routes_are_registered_in_openapi():
    from fastapi.testclient import TestClient

    from mozok.api.main import app

    schema = app.openapi()
    expected = [
        "/agents/{agent_id}/actions/plan",
        "/agents/{agent_id}/actions/propose",
        "/agents/{agent_id}/self-model/preview",
        "/agents/{agent_id}/self-model/propose-update",
        "/agents/{agent_id}/belief-revision/preview",
        "/agents/{agent_id}/belief-revision/propose",
    ]
    for path in expected:
        assert path in schema["paths"]

    served_schema = TestClient(app).get("/openapi.json").json()
    for path in expected:
        assert path in served_schema["paths"]

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from mozok.action_planning.schemas import ActionToolSpec
from mozok.agent_modes.service import AgentModeService
from mozok.db.models import AgentRecord, MemoryRecord
from mozok.db.session import Base
from mozok.evaluation_packs.schemas import EvaluationCase, EvaluationExpectations, EvaluationPackRunRequest
from mozok.evaluation_packs.service import EvaluationPackService
from mozok.perception.schemas import PerceptionEvent
from mozok.runtime_tick.schemas import AgentRuntimeTickRequest
from mozok.runtime_tick.service import AgentRuntimeTickService
from mozok.world_events.schemas import WorldEventCreate, WorldEventCreateRequest, WorldEventSearchRequest, WorldEventToPerceptionRequest
from mozok.world_events.service import WorldEventService


class FakeEmbeddingService:
    def embed(self, text: str):
        return [0.1, 0.2, 0.3]


class FakeVectorIndex:
    def __init__(self):
        self.items = []

    def add(self, memory_id: int, vector):
        self.items.append((memory_id, vector))

    def search(self, vector, limit: int):
        return []

    def save(self):
        pass


class FakeMemoryService:
    def search(self, agent_id: str, query: str, limit: int = 5, memory_type: str | None = None, update_access: bool = False):
        from mozok.schemas.memory import MemorySearchResult
        if memory_type == "semantic":
            return [MemorySearchResult(id=1, agent_id=agent_id, memory_type="semantic", content="Alice knows the old well connects to hidden tunnels.", importance=8, emotional_weight=0.0, score=0.9, metadata={})][:limit]
        return []


def make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def seed_agent(db):
    db.add(AgentRecord(id="npc_alice", name="Alice", metadata_json={"agent_mode": "simulacra_npc"}))
    db.add(MemoryRecord(agent_id="npc_alice", memory_type="semantic", content="Alice knows the old well connects to hidden tunnels.", importance=8, emotional_weight=0, metadata_json={}))
    db.commit()


def test_v38_agent_mode_resolve_bugfix_still_works():
    db = make_db()
    db.add(AgentRecord(id="npc_alice", name="Alice", metadata_json={"agent_mode": "simulacra_npc"}))
    db.commit()
    agent = db.get(AgentRecord, "npc_alice")
    resolved = AgentModeService().resolve(agent, agent_mode="narrator")
    assert resolved.profile.mode == "narrator"


def test_world_event_bus_stores_searches_and_compiles_to_perception():
    db = make_db()
    service = WorldEventService(db)
    created = service.create(WorldEventCreateRequest(events=[WorldEventCreate(world_id="w1", agent_id="npc_alice", content="A metallic sound echoes from the old well.", channel_hint="hearing", salience=8, tags=["well", "sound"])], store=True))
    assert created.event_count == 1

    found = service.search(WorldEventSearchRequest(world_id="w1", agent_id="npc_alice", tags_any=["well"]))
    assert found.event_count == 1

    compiled = service.to_perception_events(WorldEventToPerceptionRequest(world_id="w1", agent_id="npc_alice", limit=5))
    assert compiled.perception_events[0].channel_hint == "hearing"
    assert compiled.perception_events[0].metadata["world_event_id"].startswith("evt_")


def test_runtime_tick_plans_without_executing(monkeypatch):
    db = make_db()
    seed_agent(db)
    WorldEventService(db).create(WorldEventCreateRequest(events=[WorldEventCreate(world_id="w1", agent_id="npc_alice", content="A metallic sound echoes from the old well.", channel_hint="hearing", salience=8, tags=["well", "sound"])], store=True))

    import mozok.runtime_tick.service as tick_service
    monkeypatch.setattr(tick_service, "get_memory_service", lambda db: FakeMemoryService())

    response = AgentRuntimeTickService(db).tick(
        "npc_alice",
        AgentRuntimeTickRequest(
            world_id="w1",
            message="Check the old well sound.",
            store_proposals=False,
            available_tools=[ActionToolSpec(name="move_to_location", description="Move NPC to old well", action_kind="game_command", tags=["move", "well"])],
        ),
    )
    assert response.tick_id.startswith("tick_")
    assert response.read_only is True
    assert response.cognitive_field is not None
    assert response.action_plan is not None
    assert response.action_plan.execution_policy["executes_tools"] is False


def test_evaluation_pack_v2_checks_prompt_and_action(monkeypatch):
    db = make_db()
    seed_agent(db)

    import mozok.evaluation_packs.service as eval_service
    monkeypatch.setattr(eval_service, "get_memory_service", lambda db: FakeMemoryService())

    response = EvaluationPackService(db).run(EvaluationPackRunRequest(pack_name="old_well_eval", cases=[EvaluationCase(case_id="c1", agent_id="npc_alice", message="What about the old well sound?", perception_events=[PerceptionEvent(content="A metallic sound echoes from the old well.", channel_hint="hearing", salience=8, tags=["well", "sound"])], available_tools=[ActionToolSpec(name="move_to_location", description="Move NPC to old well", action_kind="game_command", tags=["move", "well"])], expectations=EvaluationExpectations(prompt_contains=["old well"], prompt_not_contains=["Mara poisoned"], expected_min_candidates=1))]))
    assert response.passed is True
    assert response.case_count == 1


def test_v39_42_routes_are_registered_in_openapi():
    from fastapi.testclient import TestClient
    from mozok.api.main import app

    expected = [
        "/runtime/integration/status",
        "/agents/{agent_id}/tick",
        "/world-events",
        "/world-events/search",
        "/world-events/to-perception",
        "/evaluation-packs/run",
    ]
    schema = app.openapi()
    for path in expected:
        assert path in schema["paths"]
    served_schema = TestClient(app).get("/openapi.json").json()
    for path in expected:
        assert path in served_schema["paths"]

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from mozok.db.models import AgentRecord
from mozok.db.session import Base
from mozok.knowledge_relations.service import KnowledgeRelationService
from mozok.runtime_tick.schemas import AgentRuntimeBatchTickRequest, AgentRuntimeTickRequest
from mozok.runtime_tick.service import AgentRuntimeTickService
from mozok.scenario_studio.schemas import (
    ScenarioStudioAgentDraft,
    ScenarioStudioBuildRequest,
    ScenarioStudioGoalDraft,
    ScenarioStudioLoreDraft,
    ScenarioStudioSaveRequest,
    ScenarioStudioSkillDraft,
)
from mozok.scenario_studio.service import ScenarioStudioService
from mozok.schemas.knowledge_relations import KnowledgeRelationUpsert
from mozok.visual_graph.schemas import VisualKnowledgeGraphRequest
from mozok.visual_graph.service import VisualKnowledgeGraphService


class FakeMemoryService:
    def search(self, *args, **kwargs):
        return []


def make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def test_scenario_studio_builds_importable_brain_pack_with_auto_relations():
    response = ScenarioStudioService().build(
        ScenarioStudioBuildRequest(
            world_id="demo_world",
            title="Demo World",
            agents=[ScenarioStudioAgentDraft(agent_id="npc_demo", name="Demo NPC", mode="roleplay_character")],
            lorebook_entries=[ScenarioStudioLoreDraft(entry_key="old_well", title="Old Well", content="A well beside a chapel.")],
            goals=[ScenarioStudioGoalDraft(agent_id="npc_demo", goal_key="protect_secret", title="Protect secret", related_lorebook_keys=["old_well"])],
            procedural_skills=[ScenarioStudioSkillDraft(agent_id="npc_demo", skill_key="deflect", title="Deflect", related_goal_keys=["protect_secret"])],
        )
    )
    assert response.valid is True
    assert response.brain_pack["world_id"] == "demo_world"
    assert response.brain_pack["agents"][0]["agent_id"] == "npc_demo"
    relation_types = {item["relation_type"] for item in response.brain_pack["knowledge_relations"]}
    assert {"depends_on", "supports"}.issubset(relation_types)
    assert response.evaluation_pack is not None


def test_scenario_studio_can_save_pack(tmp_path: Path):
    request = ScenarioStudioSaveRequest(
        filename="My Demo Pack.json",
        overwrite=True,
        world_id="demo_world",
        title="Demo World",
        agents=[ScenarioStudioAgentDraft(agent_id="npc_demo", name="Demo NPC")],
    )
    response = ScenarioStudioService().save(request, root=tmp_path)
    assert response.saved is True
    path = Path(response.path)
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8"))["world_id"] == "demo_world"


def test_visual_knowledge_graph_exports_nodes_edges_cytoscape_and_mermaid():
    db = make_db()
    KnowledgeRelationService(db).upsert(
        KnowledgeRelationUpsert(
            agent_id="npc_demo",
            world_id="demo_world",
            source_type="goal",
            source_id="protect_secret",
            relation_type="depends_on",
            target_type="lorebook",
            target_id="old_well",
            strength=0.9,
            confidence=0.8,
        )
    )
    response = VisualKnowledgeGraphService(db).build("npc_demo", VisualKnowledgeGraphRequest(world_id="demo_world"))
    assert response.node_count == 2
    assert response.edge_count == 1
    assert response.cytoscape["elements"]["edges"][0]["data"]["relation_type"] == "depends_on"
    assert "graph TD" in response.mermaid


def test_runtime_tick_v2_batch_and_history(monkeypatch):
    db = make_db()
    db.add(AgentRecord(id="npc_demo", name="Demo NPC", metadata_json={"agent_mode": "simulacra_npc"}))
    db.commit()

    import mozok.runtime_tick.service as tick_service

    monkeypatch.setattr(tick_service, "get_memory_service", lambda db: FakeMemoryService())

    service = AgentRuntimeTickService(db)
    batch = service.batch_tick(
        AgentRuntimeBatchTickRequest(
            world_id="demo_world",
            agent_ids=["npc_demo"],
            shared_message="Check the old well scene.",
            default_request=AgentRuntimeTickRequest(world_id="demo_world", create_change_proposals=False),
        )
    )
    assert batch.completed_count == 1
    history = service.history("npc_demo")
    assert history.count == 1
    assert history.history[0].world_id == "demo_world"


def test_v49_53_routes_are_registered_in_openapi():
    from mozok.api.main import app

    schema = app.openapi()
    expected = [
        "/ui",
        "/ui/scenario-studio",
        "/ui/knowledge-graph",
        "/scenario-studio/build",
        "/scenario-studio/save",
        "/agents/{agent_id}/knowledge-graph/visual",
        "/runtime/tick/batch",
        "/agents/{agent_id}/tick/history",
    ]
    for path in expected:
        assert path in schema["paths"]

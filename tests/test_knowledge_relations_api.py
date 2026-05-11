from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from mozok.api import knowledge_relation_routes
from mozok.api.main import app
from mozok.db.models import Base
from mozok.db.session import get_db
from mozok.goals.models import AgentGoalRecord  # noqa: F401
from mozok.knowledge_relations.models import KnowledgeRelationRecord  # noqa: F401
from mozok.lorebook.models import LorebookEntryRecord  # noqa: F401


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[knowledge_relation_routes.get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _upsert_relation(client: TestClient, payload: dict) -> dict:
    response = client.post("/knowledge-relations/upsert", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_upsert_and_context_endpoint(client: TestClient):
    created = _upsert_relation(
        client,
        {
            "agent_id": "npc_alice",
            "world_id": "test_world",
            "source_type": "goal",
            "source_id": "hide_tunnel_secret",
            "relation_type": "depends_on",
            "target_type": "lorebook",
            "target_id": "old_well",
            "strength": 1.0,
            "confidence": 0.9,
            "description": "Alice's goal depends on the old well secret.",
            "evidence": {"reason": "old_well has tunnel lore"},
            "metadata": {"source": "pytest"},
        },
    )

    assert created["agent_id"] == "npc_alice"
    assert created["source_type"] == "goal"
    assert created["target_id"] == "old_well"

    response = client.get(
        "/agents/npc_alice/knowledge-relations/context",
        params={"world_id": "test_world", "limit": 10},
    )
    assert response.status_code == 200, response.text
    context = response.json()

    assert context["count"] == 1
    assert "goal:\"hide_tunnel_secret\" depends_on lorebook:\"old_well\"" in context["lines"][0]
    assert "Alice's goal depends" in context["lines"][0]


def test_upsert_updates_existing_relation_instead_of_creating_duplicate(client: TestClient):
    payload = {
        "agent_id": "npc_alice",
        "world_id": "test_world",
        "source_type": "memory",
        "source_id": "42",
        "relation_type": "evidence_for",
        "target_type": "entity_state",
        "target_id": "17",
        "strength": 0.6,
        "confidence": 0.7,
        "description": "Initial relation.",
    }
    first = _upsert_relation(client, payload)
    payload["strength"] = 0.95
    payload["description"] = "Updated relation."
    second = _upsert_relation(client, payload)

    assert second["id"] == first["id"]
    assert second["strength"] == 0.95
    assert second["description"] == "Updated relation."

    response = client.get("/agents/npc_alice/knowledge-relations", params={"world_id": "test_world"})
    assert response.status_code == 200
    relations = response.json()
    assert len(relations) == 1


def test_relation_does_not_leak_between_agents(client: TestClient):
    _upsert_relation(
        client,
        {
            "agent_id": "npc_alice",
            "world_id": "test_world",
            "source_type": "goal",
            "source_id": "hide_tunnel_secret",
            "relation_type": "depends_on",
            "target_type": "lorebook",
            "target_id": "old_well",
            "description": "Alice-only relation.",
        },
    )

    alice = client.get("/agents/npc_alice/knowledge-relations", params={"world_id": "test_world"})
    bob = client.get("/agents/npc_bob/knowledge-relations", params={"world_id": "test_world"})

    assert len(alice.json()) == 1
    assert bob.json() == []


def test_validate_nodes_rejects_missing_known_nodes(client: TestClient):
    response = client.post(
        "/knowledge-relations/upsert",
        json={
            "agent_id": "npc_alice",
            "world_id": "test_world",
            "source_type": "goal",
            "source_id": "missing_goal",
            "relation_type": "depends_on",
            "target_type": "lorebook",
            "target_id": "missing_lore",
            "validate_nodes": True,
        },
    )
    assert response.status_code == 400
    assert "node validation failed" in response.json()["detail"]


def test_validate_nodes_accepts_existing_goal_and_lorebook_then_resolves(client: TestClient):
    goal_response = client.post(
        "/goals/upsert",
        json={
            "agent_id": "npc_alice",
            "goal_key": "hide_tunnel_secret",
            "title": "Hide the tunnel secret",
            "goal_type": "personal",
            "status": "active",
            "priority": 8,
            "description": "Alice wants to keep outsiders away from the old well.",
            "success_criteria": [],
            "failure_conditions": [],
            "related_entity_ids": [],
            "related_lorebook_keys": ["old_well"],
            "plan_steps": [],
            "notes": "",
            "metadata": {},
        },
    )
    assert goal_response.status_code == 200, goal_response.text

    lore_response = client.post(
        "/lorebook/upsert",
        json={
            "world_id": "test_world",
            "entry_key": "old_well",
            "title": "The Old Well",
            "content": "The old well connects to ancient underground tunnels.",
            "category": "location",
            "visibility": "public",
            "importance": 8,
            "tags": ["well", "tunnels"],
            "metadata": {},
        },
    )
    assert lore_response.status_code == 200, lore_response.text

    relation = _upsert_relation(
        client,
        {
            "agent_id": "npc_alice",
            "world_id": "test_world",
            "source_type": "goal",
            "source_id": "hide_tunnel_secret",
            "relation_type": "depends_on",
            "target_type": "lorebook",
            "target_id": "old_well",
            "description": "The hiding goal depends on the old well lore.",
            "validate_nodes": True,
        },
    )

    resolved = client.get(f"/knowledge-relations/{relation['id']}/resolved")
    assert resolved.status_code == 200, resolved.text
    body = resolved.json()
    assert body["source"]["found"] is True
    assert body["source"]["title"] == "Hide the tunnel secret"
    assert body["target"]["found"] is True
    assert body["target"]["title"] == "The Old Well"


def test_neighborhood_endpoint_returns_incoming_and_outgoing_edges(client: TestClient):
    _upsert_relation(
        client,
        {
            "agent_id": "npc_alice",
            "world_id": "test_world",
            "source_type": "goal",
            "source_id": "hide_tunnel_secret",
            "relation_type": "depends_on",
            "target_type": "lorebook",
            "target_id": "old_well",
        },
    )
    _upsert_relation(
        client,
        {
            "agent_id": "npc_alice",
            "world_id": "test_world",
            "source_type": "memory",
            "source_id": "42",
            "relation_type": "evidence_for",
            "target_type": "goal",
            "target_id": "hide_tunnel_secret",
        },
    )

    both = client.get(
        "/agents/npc_alice/knowledge-relations/neighborhood",
        params={
            "world_id": "test_world",
            "node_type": "goal",
            "node_id": "hide_tunnel_secret",
            "direction": "both",
        },
    )
    assert both.status_code == 200, both.text
    assert both.json()["count"] == 2

    outgoing = client.get(
        "/agents/npc_alice/knowledge-relations/neighborhood",
        params={
            "world_id": "test_world",
            "node_type": "goal",
            "node_id": "hide_tunnel_secret",
            "direction": "outgoing",
        },
    )
    assert outgoing.status_code == 200, outgoing.text
    assert outgoing.json()["count"] == 1
    assert outgoing.json()["relations"][0]["target_id"] == "old_well"


def test_graph_debug_traverses_multi_hop_and_reports_cycle(client: TestClient):
    for payload in [
        {
            "agent_id": "npc_alice",
            "world_id": "graph_world",
            "source_type": "concept",
            "source_id": "old_well",
            "relation_type": "leads_to",
            "target_type": "concept",
            "target_id": "tunnels",
            "strength": 0.9,
            "confidence": 0.9,
        },
        {
            "agent_id": "npc_alice",
            "world_id": "graph_world",
            "source_type": "concept",
            "source_id": "tunnels",
            "relation_type": "hides",
            "target_type": "concept",
            "target_id": "map_room",
            "strength": 0.8,
            "confidence": 0.9,
        },
        {
            "agent_id": "npc_alice",
            "world_id": "graph_world",
            "source_type": "concept",
            "source_id": "map_room",
            "relation_type": "loops_back_to",
            "target_type": "concept",
            "target_id": "old_well",
            "strength": 0.7,
            "confidence": 0.8,
        },
    ]:
        _upsert_relation(client, payload)

    response = client.post(
        "/agents/npc_alice/knowledge-relations/graph/debug",
        json={
            "world_id": "graph_world",
            "roots": [{"node_type": "concept", "node_id": "old_well"}],
            "direction": "outgoing",
            "max_depth": 3,
            "max_relations": 10,
            "per_node_limit": 10,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["relation_count"] == 3
    assert body["cycle_count"] == 1
    assert body["traversal_report"]["read_only"] is True
    assert body["traversal_report"]["multi_hop"] is True
    assert {node["node_id"] for node in body["nodes"]} >= {"old_well", "tunnels", "map_room"}
    assert any("concept:old_well" in cycle["nodes"] for cycle in body["cycles"])
    assert body["rerank_hints"]


def test_graph_debug_respects_token_budget(client: TestClient):
    _upsert_relation(
        client,
        {
            "agent_id": "npc_alice",
            "world_id": "graph_world",
            "source_type": "concept",
            "source_id": "old_well",
            "relation_type": "leads_to",
            "target_type": "concept",
            "target_id": "very_long_tunnel_name",
            "description": "A deliberately verbose relation line should exceed a tiny traversal budget.",
        },
    )

    response = client.post(
        "/agents/npc_alice/knowledge-relations/graph/debug",
        json={
            "world_id": "graph_world",
            "roots": [{"node_type": "concept", "node_id": "old_well"}],
            "direction": "outgoing",
            "max_depth": 2,
            "estimated_token_budget": 1,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["relation_count"] == 0
    assert body["traversal_report"]["budget_aware"] is True
    assert body["traversal_report"]["skipped_for_budget"] == 1


def test_reviewed_auto_create_endpoint_can_dry_run_and_create_relations(client: TestClient):
    dry_run = client.post(
        "/agents/npc_alice/knowledge-relations/auto-create",
        json={
            "world_id": "graph_world",
            "dry_run": True,
            "suggestions": [
                {
                    "source_type": "memory",
                    "source_id": "1",
                    "relation_type": "similar_to",
                    "target_type": "memory",
                    "target_id": "2",
                    "description": "Reviewed dedup suggestion.",
                }
            ],
        },
    )
    assert dry_run.status_code == 200, dry_run.text
    assert dry_run.json()["dry_run"] is True
    assert dry_run.json()["created"] == 0
    assert dry_run.json()["skipped"] == 1

    created = client.post(
        "/agents/npc_alice/knowledge-relations/auto-create",
        json={
            "world_id": "graph_world",
            "suggestions": [
                {
                    "source_type": "memory",
                    "source_id": "1",
                    "relation_type": "similar_to",
                    "target_type": "memory",
                    "target_id": "2",
                    "description": "Reviewed dedup suggestion.",
                }
            ],
        },
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["created"] == 1
    assert body["relation_ids"]
    assert body["relations"][0]["relation_type"] == "similar_to"

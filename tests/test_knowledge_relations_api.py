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

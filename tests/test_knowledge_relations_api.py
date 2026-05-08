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
from mozok.knowledge_relations.models import KnowledgeRelationRecord  # noqa: F401


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
    assert "goal:hide_tunnel_secret depends_on lorebook:old_well" in context["lines"][0]
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

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from mozok.api import procedural_skill_routes
from mozok.api.main import app
from mozok.db.models import Base
from mozok.db.session import get_db
from mozok.procedural_skills.models import AgentProceduralSkillRecord  # noqa: F401


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
    app.dependency_overrides[procedural_skill_routes.get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _payload(**overrides):
    data = {
        "agent_id": "npc_alice",
        "skill_key": "deflect_dangerous_questions",
        "title": "Deflect dangerous questions",
        "skill_type": "conversation",
        "status": "active",
        "priority": 8,
        "description": "Use this when Alice needs to avoid revealing a dangerous secret while sounding calm.",
        "trigger": {
            "when": "Someone asks about a secret, forbidden place, or dangerous topic.",
            "keywords": ["secret", "old well", "tunnels"],
            "applies_to_goal_keys": ["hide_tunnel_secret"],
        },
        "procedure": [
            "Acknowledge the question without panic.",
            "Give a partial truth if possible.",
            "Avoid revealing restricted or narrator-only lore.",
            "Redirect toward safety or uncertainty.",
        ],
        "examples": [
            {
                "situation": "The player asks what Alice knows about the old well.",
                "good_response": "The well is old, and people around here prefer not to disturb old things.",
                "bad_response": "The well connects to secret tunnels under the village.",
            }
        ],
        "related_goal_keys": ["hide_tunnel_secret"],
        "related_entity_ids": ["old_well"],
        "related_lorebook_keys": ["old_well"],
        "notes": "Alice should sound evasive but not obviously guilty.",
        "metadata": {"source": "pytest"},
    }
    data.update(overrides)
    return data


def test_upsert_list_and_context_endpoint(client: TestClient):
    response = client.post("/procedural-skills/upsert", json=_payload())
    assert response.status_code == 200, response.text
    created = response.json()
    assert created["agent_id"] == "npc_alice"
    assert created["skill_key"] == "deflect_dangerous_questions"
    assert created["priority"] == 8

    listed = client.get("/agents/npc_alice/procedural-skills", params={"status": "active"})
    assert listed.status_code == 200, listed.text
    assert len(listed.json()) == 1

    context = client.get("/agents/npc_alice/procedural-skills/context", params={"status": "active", "limit": 10})
    assert context.status_code == 200, context.text
    body = context.json()
    assert body["count"] == 1
    assert "Deflect dangerous questions" in body["lines"][0]
    assert "Avoid revealing restricted" in body["lines"][0]


def test_duplicate_upsert_updates_existing_skill(client: TestClient):
    first = client.post("/procedural-skills/upsert", json=_payload(priority=4))
    assert first.status_code == 200, first.text
    second = client.post("/procedural-skills/upsert", json=_payload(priority=9, description="Updated skill."))
    assert second.status_code == 200, second.text

    assert second.json()["id"] == first.json()["id"]
    assert second.json()["priority"] == 9
    assert second.json()["description"] == "Updated skill."

    listed = client.get("/agents/npc_alice/procedural-skills")
    assert len(listed.json()) == 1


def test_inactive_skill_does_not_appear_in_active_context(client: TestClient):
    created = client.post("/procedural-skills/upsert", json=_payload()).json()
    patch = client.patch(f"/procedural-skills/{created['id']}", json={"status": "inactive"})
    assert patch.status_code == 200, patch.text

    active_context = client.get("/agents/npc_alice/procedural-skills/context", params={"status": "active"})
    assert active_context.status_code == 200
    assert active_context.json()["count"] == 0

    inactive_context = client.get("/agents/npc_alice/procedural-skills/context", params={"status": "inactive"})
    assert inactive_context.status_code == 200
    assert inactive_context.json()["count"] == 1


def test_skill_does_not_leak_between_agents(client: TestClient):
    response = client.post("/procedural-skills/upsert", json=_payload(agent_id="npc_alice"))
    assert response.status_code == 200, response.text

    alice = client.get("/agents/npc_alice/procedural-skills/context")
    bob = client.get("/agents/npc_bob/procedural-skills/context")

    assert alice.json()["count"] == 1
    assert bob.json()["count"] == 0

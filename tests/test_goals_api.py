"""
Automated tests for Goals/Plans API.

These tests use an in-memory SQLite database and should not touch your real PostgreSQL database.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from mozok.api.main import app
from mozok.api import goal_routes
from mozok.db.models import Base

# Register table on Base.metadata.
from mozok.goals.models import AgentGoalRecord  # noqa: F401


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

    app.dependency_overrides[goal_routes.get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def _upsert_goal(client: TestClient, payload: dict) -> dict:
    response = client.post("/goals/upsert", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_upsert_and_list_agent_goal(client: TestClient):
    payload = {
        "agent_id": "npc_alice_goal_api",
        "goal_key": "hide_tunnel_secret",
        "title": "Hide the tunnel secret",
        "goal_type": "personal",
        "status": "active",
        "priority": 8,
        "description": "Alice wants to prevent outsiders from learning that the old well connects to tunnels.",
        "success_criteria": ["The player leaves the well alone"],
        "failure_conditions": ["Bob reveals Alice's past"],
        "related_entity_ids": ["old_well", "npc_bob"],
        "related_lorebook_keys": ["old_well"],
        "plan_steps": [
            {"step_key": "deflect_questions", "description": "Give vague answers about the well.", "status": "active"},
            {"step_key": "watch_bob", "description": "Watch whether Bob says too much.", "status": "pending"},
        ],
        "notes": "Alice is protective of the tunnel secret.",
        "metadata": {"source": "pytest"},
    }

    created = _upsert_goal(client, payload)

    assert created["agent_id"] == "npc_alice_goal_api"
    assert created["goal_key"] == "hide_tunnel_secret"
    assert created["priority"] == 8
    assert created["plan_steps"][0]["step_key"] == "deflect_questions"

    response = client.get("/agents/npc_alice_goal_api/goals")
    assert response.status_code == 200, response.text

    goals = response.json()
    assert len(goals) == 1
    assert goals[0]["title"] == "Hide the tunnel secret"


def test_upsert_updates_existing_goal_instead_of_creating_duplicate(client: TestClient):
    first = _upsert_goal(
        client,
        {
            "agent_id": "npc_alice_goal_api_update",
            "goal_key": "find_bob",
            "title": "Find Bob",
            "goal_type": "quest",
            "status": "active",
            "priority": 5,
            "description": "Find Bob near the old well.",
        },
    )
    second = _upsert_goal(
        client,
        {
            "agent_id": "npc_alice_goal_api_update",
            "goal_key": "find_bob",
            "title": "Find Bob",
            "goal_type": "quest",
            "status": "blocked",
            "priority": 9,
            "description": "Find Bob, but the bridge is currently blocked.",
        },
    )

    assert second["id"] == first["id"]
    assert second["status"] == "blocked"
    assert second["priority"] == 9

    response = client.get("/agents/npc_alice_goal_api_update/goals")
    assert response.status_code == 200, response.text
    assert len(response.json()) == 1


def test_patch_goal_status_and_context_endpoint(client: TestClient):
    goal = _upsert_goal(
        client,
        {
            "agent_id": "npc_bob_goal_api",
            "goal_key": "warn_alice",
            "title": "Warn Alice",
            "goal_type": "social",
            "status": "active",
            "priority": 6,
            "description": "Bob wants to warn Alice about the old well.",
            "plan_steps": [
                {"step_key": "find_alice", "description": "Find Alice at the healer's hut.", "status": "active"}
            ],
        },
    )

    patch_response = client.patch(
        f"/goals/{goal['id']}",
        json={"status": "completed", "notes": "Bob warned Alice before sunset."},
    )
    assert patch_response.status_code == 200, patch_response.text
    patched = patch_response.json()
    assert patched["status"] == "completed"

    all_context = client.get("/agents/npc_bob_goal_api/goals/context")
    assert all_context.status_code == 200, all_context.text
    assert all_context.json()["count"] == 1
    assert "Bob warned Alice" in all_context.text

    active_context = client.get("/agents/npc_bob_goal_api/goals/context", params={"status": "active"})
    assert active_context.status_code == 200, active_context.text
    assert active_context.json()["count"] == 0


def test_delete_goal_soft_deletes_it(client: TestClient):
    goal = _upsert_goal(
        client,
        {
            "agent_id": "npc_delete_goal_api",
            "goal_key": "temporary_goal",
            "title": "Temporary Goal",
            "status": "active",
        },
    )

    delete_response = client.delete(f"/goals/{goal['id']}")
    assert delete_response.status_code == 200, delete_response.text

    active_list = client.get("/agents/npc_delete_goal_api/goals")
    assert active_list.status_code == 200, active_list.text
    assert active_list.json() == []

    inactive_list = client.get("/agents/npc_delete_goal_api/goals", params={"include_inactive": True})
    assert inactive_list.status_code == 200, inactive_list.text
    assert len(inactive_list.json()) == 1
    assert inactive_list.json()[0]["active"] is False

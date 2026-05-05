"""
Automated tests for the Entity State API.

These tests use FastAPI's TestClient and an in-memory SQLite database.
That means they do NOT touch your real PostgreSQL database and should be safe
to run repeatedly.

Covered:
- assistant_user_profile state
- social_relationship state
- quest_relevance state
- upsert update behaviour
- formatted context endpoint
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from mozok.api.main import app
from mozok.api import entity_state_routes
from mozok.db.models import Base

# Important: importing this model registers the entity_states table on Base.metadata.
from mozok.entity_state.models import AgentEntityStateRecord  # noqa: F401


@pytest.fixture()
def client():
    """
    Create a temporary test client with an in-memory SQLite database.

    The real app normally gets DB sessions from mozok.db.session.get_db.
    Here we override the dependency imported by entity_state_routes so the
    tests don't use the real PostgreSQL database.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )

    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[entity_state_routes.get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def _upsert_entity_state(client: TestClient, payload: dict) -> dict:
    response = client.post("/entity-states/upsert", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_upsert_and_list_assistant_user_profile(client: TestClient):
    payload = {
        "agent_id": "assistant_test_unit_001",
        "entity_id": "denys",
        "entity_name": "Denys",
        "entity_type": "user",
        "role": "primary_user",
        "state_kind": "assistant_user_profile",
        "attributes": {
            "prefers": [
                "exact file names",
                "step-by-step patches",
                "beginner-friendly explanations",
            ],
            "skill_level": "learning programming",
            "tone": "practical and direct",
        },
        "notes": "Denys prefers practical programming help with exact file-by-file instructions.",
        "metadata": {
            "source": "pytest",
        },
    }

    created = _upsert_entity_state(client, payload)

    assert created["agent_id"] == "assistant_test_unit_001"
    assert created["entity_id"] == "denys"
    assert created["state_kind"] == "assistant_user_profile"
    assert created["attributes"]["skill_level"] == "learning programming"

    response = client.get("/agents/assistant_test_unit_001/entity-states")
    assert response.status_code == 200, response.text

    states = response.json()
    assert isinstance(states, list)
    assert len(states) == 1
    assert states[0]["entity_name"] == "Denys"
    assert states[0]["state_kind"] == "assistant_user_profile"


def test_upsert_updates_existing_state_instead_of_creating_duplicate(client: TestClient):
    first_payload = {
        "agent_id": "assistant_test_unit_002",
        "entity_id": "denys",
        "entity_name": "Denys",
        "entity_type": "user",
        "role": "primary_user",
        "state_kind": "assistant_user_profile",
        "attributes": {
            "skill_level": "learning programming",
        },
        "notes": "Initial profile.",
        "metadata": {
            "source": "pytest_first_write",
        },
    }

    second_payload = {
        "agent_id": "assistant_test_unit_002",
        "entity_id": "denys",
        "entity_name": "Denys",
        "entity_type": "user",
        "role": "primary_user",
        "state_kind": "assistant_user_profile",
        "attributes": {
            "skill_level": "learning programming",
            "preferred_format": "exact file-by-file instructions",
        },
        "notes": "Updated profile.",
        "metadata": {
            "source": "pytest_second_write",
        },
    }

    first = _upsert_entity_state(client, first_payload)
    second = _upsert_entity_state(client, second_payload)

    assert second["id"] == first["id"]
    assert second["notes"] == "Updated profile."
    assert second["attributes"]["preferred_format"] == "exact file-by-file instructions"

    response = client.get("/agents/assistant_test_unit_002/entity-states")
    assert response.status_code == 200, response.text

    states = response.json()
    matching_states = [
        state
        for state in states
        if state["entity_id"] == "denys"
        and state["state_kind"] == "assistant_user_profile"
    ]
    assert len(matching_states) == 1


def test_social_relationship_context_for_npc(client: TestClient):
    payload = {
        "agent_id": "npc_bob_unit",
        "entity_id": "npc_alice",
        "entity_name": "Alice",
        "entity_type": "character",
        "role": "village_healer",
        "state_kind": "social_relationship",
        "attributes": {
            "trust": 0.75,
            "fear": 0.05,
            "affection": 0.4,
            "resentment": 0.0,
            "last_interaction": "Alice healed Bob after a wolf attack.",
        },
        "notes": "Bob trusts Alice because she helped him survive.",
        "metadata": {
            "source": "pytest",
        },
    }

    created = _upsert_entity_state(client, payload)

    assert created["state_kind"] == "social_relationship"
    assert created["attributes"]["trust"] == 0.75

    response = client.get("/agents/npc_bob_unit/entity-states/context")
    assert response.status_code == 200, response.text

    # We check response.text rather than assuming an exact JSON shape.
    # This makes the test resilient if the endpoint returns either a string
    # or an object containing a context string.
    context_text = response.text
    assert "Alice" in context_text
    assert "social_relationship" in context_text
    assert "Bob trusts Alice" in context_text


def test_quest_relevance_context_for_narrator(client: TestClient):
    payload = {
        "agent_id": "narrator_unit_001",
        "entity_id": "quest_missing_child",
        "entity_name": "The Missing Child Quest",
        "entity_type": "quest",
        "role": "active_plot_thread",
        "state_kind": "quest_relevance",
        "attributes": {
            "status": "active",
            "importance": 9,
            "known_clues": [
                "red scarf near the well",
                "villagers avoid the forest at night",
            ],
            "tone": "ominous",
        },
        "notes": "The narrator should keep this quest active and maintain a mysterious tone around it.",
        "metadata": {
            "source": "pytest",
        },
    }

    created = _upsert_entity_state(client, payload)

    assert created["state_kind"] == "quest_relevance"
    assert created["attributes"]["status"] == "active"

    response = client.get("/agents/narrator_unit_001/entity-states/context")
    assert response.status_code == 200, response.text

    context_text = response.text
    assert "The Missing Child Quest" in context_text
    assert "quest_relevance" in context_text
    assert "red scarf near the well" in context_text

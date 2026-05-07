"""
Automated tests for Lorebook API.

These tests use an in-memory SQLite database and should not touch your real PostgreSQL database.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from mozok.api.main import app
from mozok.api import lorebook_routes
from mozok.db.models import Base

# Register tables on Base.metadata.
from mozok.lorebook.models import AgentLorebookKnowledgeRecord, LorebookEntryRecord  # noqa: F401


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

    app.dependency_overrides[lorebook_routes.get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def test_public_lorebook_entry_is_visible_to_any_agent(client: TestClient):
    response = client.post(
        "/lorebook/upsert",
        json={
            "world_id": "test_world",
            "entry_key": "cats_are_insidious",
            "title": "Cats Are Insidious",
            "content": "In this world, cats are famously insidious and strategic.",
            "category": "world_truth",
            "visibility": "public",
            "importance": 6,
            "tags": ["cats", "truth"],
            "metadata": {"source": "pytest"},
        },
    )
    assert response.status_code == 200, response.text

    context_response = client.get(
        "/agents/random_agent/lorebook/context",
        params={"world_id": "test_world"},
    )
    assert context_response.status_code == 200, context_response.text

    body = context_response.json()
    assert body["count"] == 1
    assert body["items"][0]["entry_key"] == "cats_are_insidious"
    assert body["items"][0]["knowledge_state"] == "public"
    assert "cats are famously insidious" in body["context_text"]


def test_restricted_lorebook_entry_requires_agent_knowledge_link(client: TestClient):
    entry_response = client.post(
        "/lorebook/upsert",
        json={
            "world_id": "test_world",
            "entry_key": "old_well_secret",
            "title": "Old Well Secret",
            "content": "The old well connects to ancient tunnels.",
            "category": "location_secret",
            "visibility": "restricted",
            "importance": 9,
            "tags": ["well", "secret"],
            "metadata": {"source": "pytest"},
        },
    )
    assert entry_response.status_code == 200, entry_response.text

    before_link = client.get("/agents/npc_bob/lorebook/context", params={"world_id": "test_world"})
    assert before_link.status_code == 200, before_link.text
    assert before_link.json()["count"] == 0

    link_response = client.post(
        "/agents/npc_bob/lorebook/knowledge",
        json={
            "agent_id": "npc_bob",
            "world_id": "test_world",
            "entry_key": "old_well_secret",
            "knowledge_state": "rumored",
            "confidence": 4,
            "notes": "Bob heard this from Alice but is not sure.",
            "metadata": {"source": "pytest"},
        },
    )
    assert link_response.status_code == 200, link_response.text

    after_link = client.get("/agents/npc_bob/lorebook/context", params={"world_id": "test_world"})
    assert after_link.status_code == 200, after_link.text

    body = after_link.json()
    assert body["count"] == 1
    assert body["items"][0]["entry_key"] == "old_well_secret"
    assert body["items"][0]["knowledge_state"] == "rumored"
    assert body["items"][0]["confidence"] == 4
    assert "old well connects" in body["context_text"]


def test_hidden_agent_knowledge_blocks_even_public_lore(client: TestClient):
    response = client.post(
        "/lorebook/upsert",
        json={
            "world_id": "test_world",
            "entry_key": "public_kingdom_fact",
            "title": "Kingdom Fact",
            "content": "The kingdom was founded after the Ash War.",
            "category": "history",
            "visibility": "public",
            "importance": 5,
            "tags": ["history"],
            "metadata": {},
        },
    )
    assert response.status_code == 200, response.text

    hidden_response = client.post(
        "/agents/amnesiac_agent/lorebook/knowledge",
        json={
            "agent_id": "amnesiac_agent",
            "world_id": "test_world",
            "entry_key": "public_kingdom_fact",
            "knowledge_state": "hidden",
            "confidence": 0,
            "notes": "This agent should not know this public fact.",
            "metadata": {},
        },
    )
    assert hidden_response.status_code == 200, hidden_response.text

    context_response = client.get("/agents/amnesiac_agent/lorebook/context", params={"world_id": "test_world"})
    assert context_response.status_code == 200, context_response.text
    assert context_response.json()["count"] == 0


def test_narrator_only_lore_requires_flag_or_explicit_link(client: TestClient):
    response = client.post(
        "/lorebook/upsert",
        json={
            "world_id": "test_world",
            "entry_key": "final_boss_identity",
            "title": "Final Boss Identity",
            "content": "The final boss is secretly the village mayor.",
            "category": "plot_secret",
            "visibility": "narrator_only",
            "importance": 10,
            "tags": ["secret", "plot"],
            "metadata": {},
        },
    )
    assert response.status_code == 200, response.text

    normal_context = client.get("/agents/npc_bob/lorebook/context", params={"world_id": "test_world"})
    assert normal_context.status_code == 200, normal_context.text
    assert normal_context.json()["count"] == 0

    narrator_context = client.get(
        "/agents/narrator_001/lorebook/context",
        params={"world_id": "test_world", "include_narrator_only": True},
    )
    assert narrator_context.status_code == 200, narrator_context.text
    body = narrator_context.json()
    assert body["count"] == 1
    assert body["items"][0]["entry_key"] == "final_boss_identity"
    assert "village mayor" in body["context_text"]

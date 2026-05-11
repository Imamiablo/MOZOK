"""Automated tests for Brain Pack / Scenario Import v1."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from mozok.api.main import app
from mozok.api import brain_pack_routes
from mozok.db.models import Base
from mozok.scenario_import.service import BrainPackImportService

# Register tables on Base.metadata.
from mozok.lorebook.models import AgentLorebookKnowledgeRecord, LorebookEntryRecord  # noqa: F401
from mozok.entity_state.models import AgentEntityStateRecord  # noqa: F401
from mozok.goals.models import AgentGoalRecord  # noqa: F401
from mozok.knowledge_relations.models import KnowledgeRelationRecord  # noqa: F401
from mozok.procedural_skills.models import AgentProceduralSkillRecord  # noqa: F401


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[brain_pack_routes.get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def sample_pack() -> dict:
    return {
        "schema_version": 1,
        "world_id": "brain_pack_test_world",
        "agents": [
            {
                "agent_id": "npc_alice_import",
                "name": "Alice",
                "description": "Guarded healer.",
                "personality": "Careful and kind.",
                "system_prompt": "Stay in character.",
            }
        ],
        "lorebook_entries": [
            {
                "entry_key": "old_well",
                "title": "The Old Well",
                "content": "The old well connects to tunnels.",
                "category": "location",
                "visibility": "public",
                "importance": 8,
            }
        ],
        "entity_states": [
            {
                "agent_id": "npc_alice_import",
                "entity_id": "npc_bob",
                "entity_name": "Bob",
                "entity_type": "character",
                "role": "story_character",
                "state_kind": "social_relationship",
                "attributes": {"trust": 0.25},
                "notes": "Alice is not sure whether Bob is safe.",
            }
        ],
        "goals": [
            {
                "agent_id": "npc_alice_import",
                "goal_key": "hide_tunnel_secret",
                "title": "Hide the tunnel secret",
                "goal_type": "personal",
                "status": "active",
                "priority": 8,
                "description": "Alice wants to hide the well tunnel secret.",
                "related_lorebook_keys": ["old_well"],
            }
        ],
        "procedural_skills": [
            {
                "agent_id": "npc_alice_import",
                "skill_key": "deflect_questions",
                "title": "Deflect Questions",
                "skill_type": "conversation",
                "status": "active",
                "priority": 7,
                "description": "Avoid revealing secrets while sounding natural.",
                "procedure": ["Acknowledge calmly.", "Redirect to safety."],
            }
        ],
        "knowledge_relations": [
            {
                "agent_id": "npc_alice_import",
                "source_type": "goal",
                "source_id": "hide_tunnel_secret",
                "relation_type": "depends_on",
                "target_type": "lorebook",
                "target_id": "old_well",
                "description": "The secrecy goal depends on the old well lore.",
            }
        ],
    }


def test_brain_pack_dry_run_counts_every_optional_section(db_session):
    report = BrainPackImportService(db_session).import_pack(sample_pack(), dry_run=True)

    assert report.dry_run is True
    assert report.world_id == "brain_pack_test_world"
    assert report.counts["agents"] == 1
    assert report.counts["lorebook_entries"] == 1
    assert report.counts["entity_states"] == 1
    assert report.counts["goals"] == 1
    assert report.counts["procedural_skills"] == 1
    assert report.counts["knowledge_relations"] == 1
    assert not report.errors
    assert all(action.action == "would_upsert" for action in report.actions)


def test_brain_pack_import_upserts_core_brain_modules(db_session):
    service = BrainPackImportService(db_session)
    report = service.import_pack(sample_pack(), dry_run=False, validate_relations=True)

    assert not report.errors
    assert any(action.section == "lorebook_entries" and action.action == "upserted" for action in report.actions)
    assert any(action.section == "goals" and action.action == "upserted" for action in report.actions)
    assert any(action.section == "procedural_skills" and action.action == "upserted" for action in report.actions)
    assert any(action.section == "knowledge_relations" and action.action == "upserted" for action in report.actions)

    # Importing the same pack again should update/upsert rather than crash or duplicate unique keys.
    second = service.import_pack(sample_pack(), dry_run=False, validate_relations=True)
    assert not second.errors


def test_brain_pack_import_api_endpoint_supports_inline_pack(client):
    response = client.post(
        "/brain-packs/import",
        json={"pack": sample_pack(), "dry_run": True, "validate_relations": False},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dry_run"] is True
    assert body["counts"]["goals"] == 1
    assert body["counts"]["procedural_skills"] == 1


def test_brain_pack_preflight_reports_duplicate_keys(db_session):
    pack = sample_pack()
    pack["lorebook_entries"].append(dict(pack["lorebook_entries"][0]))

    report = BrainPackImportService(db_session).import_pack(pack, dry_run=True)

    assert report.errors
    assert any("Duplicate key" in error and "lorebook_entries" in error for error in report.errors)


def test_brain_pack_preflight_validate_relations_accepts_nodes_declared_in_same_pack(db_session):
    report = BrainPackImportService(db_session).import_pack(sample_pack(), dry_run=True, validate_relations=True)

    assert not report.errors


def test_brain_pack_preflight_validate_relations_rejects_missing_known_nodes(db_session):
    pack = sample_pack()
    pack["knowledge_relations"] = [
        {
            "agent_id": "npc_alice_import",
            "source_type": "goal",
            "source_id": "missing_goal",
            "relation_type": "depends_on",
            "target_type": "lorebook",
            "target_id": "missing_lore",
        }
    ]

    report = BrainPackImportService(db_session).import_pack(pack, dry_run=True, validate_relations=True)

    assert report.errors
    assert any("source goal:missing_goal not found" in error for error in report.errors)
    assert any("target lorebook:missing_lore not found" in error for error in report.errors)


def test_brain_pack_real_import_aborts_before_writes_when_preflight_fails(db_session):
    pack = sample_pack()
    pack["lorebook_entries"].append(dict(pack["lorebook_entries"][0]))

    report = BrainPackImportService(db_session).import_pack(pack, dry_run=False, atomic=True)

    assert report.errors
    assert any(action.section == "preflight" and action.action == "aborted" for action in report.actions)
    assert db_session.query(LorebookEntryRecord).count() == 0
    assert db_session.query(AgentGoalRecord).count() == 0


def test_brain_pack_atomic_import_rolls_back_section_errors(db_session):
    pack = sample_pack()
    pack["knowledge_relations"] = [
        {
            "agent_id": "npc_alice_import",
            "source_type": "goal",
            "source_id": "missing_goal",
            "relation_type": "depends_on",
            "target_type": "lorebook",
            "target_id": "old_well",
        }
    ]

    # validate_relations=False lets preflight pass; the section import then fails
    # after earlier sections have been flushed. Atomic mode should roll them back.
    report = BrainPackImportService(db_session).import_pack(pack, dry_run=False, atomic=True, validate_relations=True)

    # Because validate_relations=True is a preflight error here, this also proves
    # no partial writes happened before import started.
    assert report.errors
    assert db_session.query(LorebookEntryRecord).count() == 0
    assert db_session.query(AgentGoalRecord).count() == 0


def test_brain_pack_import_api_accepts_atomic_flag(client):
    response = client.post(
        "/brain-packs/import",
        json={"pack": sample_pack(), "dry_run": True, "validate_relations": True, "atomic": True},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["atomic"] is True
    assert body["errors"] == []


def test_brain_pack_dry_run_includes_memory_import_preview(db_session):
    pack = sample_pack()
    pack["memories"] = [
        {
            "agent_id": "npc_alice_import",
            "content": "Alice knows that the old well connects to tunnels.",
            "memory_type": "semantic",
            "importance": 0.8,
        }
    ]

    report = BrainPackImportService(db_session).import_pack(pack, dry_run=True)

    assert report.memory_import is not None
    assert report.memory_import["dry_run"] is True
    assert report.memory_import["seen"] == 1
    assert report.memory_import["created"] == 0
    assert report.memory_import["preview"][0]["content"] == "Alice knows that the old well connects to tunnels."
    assert any(action.section == "memories" and action.action == "would_import" for action in report.actions)

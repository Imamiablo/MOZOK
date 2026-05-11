from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from mozok.api import procedural_skill_routes
from mozok.api.main import app
from mozok.db.models import Base
from mozok.db.session import get_db
from mozok.knowledge_relations.models import KnowledgeRelationRecord  # noqa: F401
from mozok.procedural_skills.models import AgentProceduralSkillRecord, AgentProceduralSkillUsageRecord  # noqa: F401


def make_client():
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
    return TestClient(app)


def payload(**overrides):
    data = {
        "agent_id": "npc_alice",
        "skill_key": "deflect_dangerous_questions",
        "title": "Deflect dangerous questions",
        "skill_type": "conversation",
        "status": "active",
        "priority": 8,
        "description": "Avoid revealing dangerous secrets while sounding calm.",
        "trigger": {"keywords": ["secret", "old well", "tunnels"]},
        "procedure": ["Acknowledge calmly.", "Redirect if needed."],
        "examples": [],
        "related_goal_keys": ["hide_tunnel_secret"],
        "related_lorebook_keys": ["old_well"],
        "related_entity_ids": ["old_well"],
        "notes": "Start careful.",
        "metadata": {},
    }
    data.update(overrides)
    return data


def test_procedural_skill_templates_can_seed_agent_skill():
    client = make_client()
    try:
        templates = client.get("/procedural-skills/templates")
        assert templates.status_code == 200, templates.text
        keys = {item["template_key"] for item in templates.json()}
        assert "careful_secret_deflection" in keys

        created = client.post(
            "/agents/npc_alice/procedural-skills/from-template",
            json={"template_key": "careful_secret_deflection", "priority": 7},
        )
        assert created.status_code == 200, created.text
        body = created.json()
        assert body["agent_id"] == "npc_alice"
        assert body["skill_key"] == "careful_secret_deflection"
        assert body["metadata"]["created_from_template"] == "careful_secret_deflection"
    finally:
        app.dependency_overrides.clear()


def test_usage_results_update_effectiveness_and_learned_notes():
    client = make_client()
    try:
        created = client.post("/procedural-skills/upsert", json=payload()).json()
        skill_id = created["id"]

        success = client.post(
            f"/procedural-skills/{skill_id}/usage-results",
            json={
                "session_id": "s1",
                "context": "Player asked about tunnels.",
                "outcome": "success",
                "feedback": "Deflection worked.",
                "learned_note": "Mention weathered stones before redirecting.",
                "apply_learned_note": True,
            },
        )
        assert success.status_code == 200, success.text
        assert success.json()["effectiveness"]["usage_count"] == 1
        assert success.json()["effectiveness"]["success_rate"] == 1.0
        assert "Learned strategy" in success.json()["skill"]["notes"]

        failure = client.post(
            f"/procedural-skills/{skill_id}/usage-results",
            json={"session_id": "s1", "outcome": "failure", "score": 0.1},
        )
        assert failure.status_code == 200, failure.text

        stats = client.get(f"/procedural-skills/{skill_id}/effectiveness")
        assert stats.status_code == 200, stats.text
        body = stats.json()
        assert body["usage_count"] == 2
        assert body["success_count"] == 1
        assert body["failure_count"] == 1
        assert body["success_rate"] == 0.5

        usages = client.get(f"/procedural-skills/{skill_id}/usage-results")
        assert usages.status_code == 200, usages.text
        assert len(usages.json()) == 2
    finally:
        app.dependency_overrides.clear()


def test_shared_skill_library_is_opt_in_for_selection():
    client = make_client()
    try:
        shared = payload(agent_id="ignored", skill_key="shared_secret_guard", title="Shared Secret Guard")
        response = client.post("/procedural-skills/shared/upsert", json=shared)
        assert response.status_code == 200, response.text
        assert response.json()["agent_id"] == "__shared__"

        without_shared = client.get(
            "/agents/npc_alice/procedural-skills/select",
            params={"message": "Tell me the old well secret.", "fallback_to_priority": False},
        )
        assert without_shared.status_code == 200, without_shared.text
        assert without_shared.json()["count"] == 0

        with_shared = client.get(
            "/agents/npc_alice/procedural-skills/select",
            params={
                "message": "Tell me the old well secret.",
                "fallback_to_priority": False,
                "include_shared": True,
            },
        )
        assert with_shared.status_code == 200, with_shared.text
        body = with_shared.json()
        assert body["count"] == 1
        assert body["skills"][0]["agent_id"] == "__shared__"
        assert body["selection"][0]["skill_key"] == "shared_secret_guard"
    finally:
        app.dependency_overrides.clear()


def test_skill_relation_suggestions_and_sync_create_graph_edges():
    client = make_client()
    try:
        created = client.post("/procedural-skills/upsert", json=payload()).json()
        skill_id = created["id"]

        suggestions = client.get(f"/procedural-skills/{skill_id}/relation-suggestions", params={"world_id": "default"})
        assert suggestions.status_code == 200, suggestions.text
        body = suggestions.json()
        assert body["count"] == 3
        relation_types = {item["relation_type"] for item in body["suggestions"]}
        assert {"supports", "about"}.issubset(relation_types)

        dry_run = client.post(f"/procedural-skills/{skill_id}/relations/sync", json={"dry_run": True})
        assert dry_run.status_code == 200, dry_run.text
        assert dry_run.json()["created"] == 0
        assert dry_run.json()["skipped"] == 3

        created_relations = client.post(f"/procedural-skills/{skill_id}/relations/sync", json={"dry_run": False})
        assert created_relations.status_code == 200, created_relations.text
        assert created_relations.json()["created"] == 3
        assert len(created_relations.json()["relation_ids"]) == 3
    finally:
        app.dependency_overrides.clear()


def test_procedural_skills_v3_routes_are_registered_in_openapi():
    schema = app.openapi()
    paths = schema["paths"]
    assert "/procedural-skills/{skill_id}/usage-results" in paths
    assert "/procedural-skills/{skill_id}/effectiveness" in paths
    assert "/procedural-skills/templates" in paths
    assert "/agents/{agent_id}/procedural-skills/from-template" in paths
    assert "/procedural-skills/{skill_id}/relations/sync" in paths

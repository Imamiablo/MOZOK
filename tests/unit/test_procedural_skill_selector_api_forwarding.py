from __future__ import annotations

from fastapi.testclient import TestClient

import mozok.api.main as api_main
from mozok.api.main import app


client = TestClient(app)


def _chat_response_payload() -> dict:
    return {
        "agent_id": "npc_alice",
        "session_id": "selector_api_test",
        "response": "ok",
        "used_memory_ids": [],
        "used_short_term_messages_count": 0,
        "used_goal_ids": [],
        "used_goals_count": 0,
        "used_procedural_skill_ids": [],
        "used_procedural_skills_count": 0,
        "procedural_skill_selection": [],
        "used_knowledge_relation_ids": [],
        "used_knowledge_relations_count": 0,
        "explicit_knowledge_relation_ids": [],
        "explicit_knowledge_relations_count": 0,
        "auto_expanded_knowledge_relation_ids": [],
        "auto_expanded_knowledge_relations_count": 0,
        "used_lorebook_entry_ids": [],
        "used_lorebook_entries_count": 0,
        "used_entity_state_ids": [],
        "used_entity_states_count": 0,
        "dedup_removed_memories_count": 0,
        "context_budget": None,
    }


def test_chat_forwards_procedural_skill_selector_fields(monkeypatch):
    captured: dict = {}

    class DummyBotCore:
        def __init__(self, db):
            self.db = db

        def chat(self, **kwargs):
            captured.update(kwargs)
            return _chat_response_payload()

    monkeypatch.setattr(api_main, "BotCore", DummyBotCore)

    response = client.post(
        "/chat",
        json={
            "agent_id": "npc_alice",
            "message": "What do you know about the old well?",
            "session_id": "selector_api_test",
            "include_procedural_skills": True,
            "procedural_skill_limit": 3,
            "select_relevant_procedural_skills": True,
            "procedural_skill_min_score": 2.5,
            "procedural_skill_fallback_to_priority": False,
        },
    )

    assert response.status_code == 200
    assert captured["select_relevant_procedural_skills"] is True
    assert captured["procedural_skill_min_score"] == 2.5
    assert captured["procedural_skill_fallback_to_priority"] is False


def test_debug_context_forwards_procedural_skill_selector_fields(monkeypatch):
    captured: dict = {}

    class DummyAgentService:
        def __init__(self, db):
            self.db = db

        def get_or_create_default_agent(self, agent_id: str):
            return type(
                "Agent",
                (),
                {
                    "id": agent_id,
                    "name": "Alice",
                    "description": "Test agent.",
                    "personality": "Careful.",
                    "system_prompt": "Use context only.",
                },
            )()

    class DummyContext:
        def to_debug_dict(self, *, include_full_prompt: bool, prompt_preview_chars: int):
            return {
                "ok": True,
                "include_full_prompt": include_full_prompt,
                "prompt_preview_chars": prompt_preview_chars,
                "forwarded": captured,
            }

    class DummyContextBuilder:
        def __init__(self, db, memory_service):
            self.db = db
            self.memory_service = memory_service

        def build(self, **kwargs):
            captured.update(kwargs)
            return DummyContext()

    monkeypatch.setattr(api_main, "AgentService", DummyAgentService)
    monkeypatch.setattr(api_main, "ContextBuilder", DummyContextBuilder)
    monkeypatch.setattr(api_main, "get_memory_service", lambda db: object())

    response = client.post(
        "/debug/context",
        json={
            "agent_id": "npc_alice",
            "message": "What do you know about the old well?",
            "session_id": "selector_api_test",
            "include_procedural_skills": True,
            "procedural_skill_limit": 3,
            "select_relevant_procedural_skills": True,
            "procedural_skill_min_score": 2.5,
            "procedural_skill_fallback_to_priority": False,
            "include_full_prompt": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    forwarded = payload["forwarded"]

    assert forwarded["select_relevant_procedural_skills"] is True
    assert forwarded["procedural_skill_min_score"] == 2.5
    assert forwarded["procedural_skill_fallback_to_priority"] is False

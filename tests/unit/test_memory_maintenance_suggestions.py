from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from mozok.db.models import AgentRecord, Base, MemoryRecord
from mozok.knowledge_relations.models import KnowledgeRelationRecord
from mozok.memory.maintenance_suggestions import MemoryMaintenanceSuggestionService
from mozok.schemas.memory import MemoryMaintenanceSuggestionsRequest


class FakeEmbeddingService:
    def embed_text(self, text: str):
        lowered = text.lower()
        if "old well" in lowered or "tunnel" in lowered:
            return [1.0, 0.0, 0.0]
        return [0.0, 1.0, 0.0]


class FakeLLM:
    model = "fake-maintenance-reviewer"

    def chat(self, *, system_prompt: str, user_message: str, temperature: float = 0.7):
        return "This is a careful read-only maintenance explanation."


def make_db_session():
    # Importing KnowledgeRelationRecord above registers its table on Base.metadata.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return SessionLocal()


def add_agent(db, agent_id: str = "npc_alice"):
    agent = AgentRecord(
        id=agent_id,
        name="NPC Alice",
        description="A careful test agent.",
        personality="Careful.",
        system_prompt="Use provided context only.",
        metadata_json={},
    )
    db.add(agent)
    db.commit()
    return agent


def add_memory(db, *, agent_id="npc_alice", content="memory", memory_type="raw", importance=1, days_old=20):
    created_at = datetime.now(timezone.utc) - timedelta(days=days_old)
    record = MemoryRecord(
        agent_id=agent_id,
        memory_type=memory_type,
        content=content,
        importance=importance,
        emotional_weight=0.0,
        metadata_json={},
        active=True,
        created_at=created_at,
        updated_at=created_at,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def test_relation_linked_memory_gets_protect_suggestion_without_mutation():
    db = make_db_session()
    try:
        add_agent(db)
        memory = add_memory(
            db,
            content="Alice heard a dangerous secret near the old well.",
            memory_type="raw",
            importance=1,
            days_old=30,
        )
        db.add(
            KnowledgeRelationRecord(
                agent_id="npc_alice",
                world_id="default",
                source_type="memory",
                source_id=str(memory.id),
                relation_type="supports",
                target_type="goal",
                target_id="hide_tunnel_secret",
                active=True,
            )
        )
        db.commit()

        response = MemoryMaintenanceSuggestionService(db).preview(
            agent_id="npc_alice",
            request=MemoryMaintenanceSuggestionsRequest(include_embedding_clusters=False),
        )

        actions_by_id = {
            suggestion.action
            for suggestion in response.suggestions
            if memory.id in suggestion.target_memory_ids
        }
        assert "protect" in actions_by_id
        assert "archive" not in actions_by_id
        assert response.suggestions[0].would_modify is False

        db.refresh(memory)
        assert memory.active is True
        assert memory.metadata_json == {}
    finally:
        db.close()


def test_embedding_cluster_suggests_summarize_then_archive_for_similar_raw_memories():
    db = make_db_session()
    try:
        add_agent(db)
        memories = [
            add_memory(db, content="Alice saw tracks by the old well and tunnel entrance."),
            add_memory(db, content="Alice found more old well tunnel tracks at dusk."),
            add_memory(db, content="Alice noticed tunnel dust beside the old well."),
        ]

        response = MemoryMaintenanceSuggestionService(db, embedding_service=FakeEmbeddingService()).preview(
            agent_id="npc_alice",
            request=MemoryMaintenanceSuggestionsRequest(
                include_embedding_clusters=True,
                include_relation_protection=True,
                min_cluster_size=3,
                similarity_threshold=0.80,
            ),
        )

        cluster_suggestions = [
            suggestion
            for suggestion in response.suggestions
            if suggestion.action == "summarize_then_archive" and suggestion.source == "embedding_cluster"
        ]
        assert cluster_suggestions
        assert set(cluster_suggestions[0].target_memory_ids) == {memory.id for memory in memories}
        assert cluster_suggestions[0].would_modify is False
        assert cluster_suggestions[0].safe_to_auto_apply is True
    finally:
        db.close()


def test_llm_reason_is_explanatory_only_and_keeps_action():
    db = make_db_session()
    try:
        add_agent(db)
        memory = add_memory(db, content="Temporary raw note with little long-term value.", days_old=30)

        response = MemoryMaintenanceSuggestionService(db, llm_client=FakeLLM()).preview(
            agent_id="npc_alice",
            request=MemoryMaintenanceSuggestionsRequest(
                include_embedding_clusters=False,
                include_llm_reasons=True,
            ),
        )

        suggestion = next(item for item in response.suggestions if memory.id in item.target_memory_ids)
        assert suggestion.action == "archive"
        assert suggestion.reason == "This is a careful read-only maintenance explanation."
        assert suggestion.metadata["reason_method"] == "llm_explanation"
        assert suggestion.metadata["deterministic_reason"]
        assert suggestion.would_modify is False
    finally:
        db.close()

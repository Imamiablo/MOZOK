from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from mozok.db.models import AgentRecord, MemoryRecord
from mozok.db.session import Base
from mozok.knowledge_relations.models import KnowledgeRelationRecord
from mozok.memory.maintenance_suggestions import MemoryMaintenanceSuggestionService
from mozok.schemas.memory import MemoryMaintenanceSuggestionsRequest


class FakeEmbeddingService:
    def embed_text(self, text: str):
        lower = text.lower()
        if "old well" in lower or "tunnel" in lower:
            return [1.0, 0.0, 0.0]
        return [0.0, 1.0, 0.0]


class FakeLlmClient:
    model = "fake-maintenance-explainer"

    def chat(self, system_prompt: str, user_message: str, temperature: float = 0.1):
        assert "Do not change the action" in system_prompt
        return "Keep this suggestion, but explain it cautiously because it is only a maintenance hint."


def make_db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return SessionLocal()


def add_agent(db, agent_id: str = "npc_alice"):
    agent = AgentRecord(id=agent_id, name="Alice", metadata_json={})
    db.add(agent)
    db.commit()
    return agent


def add_memory(db, *, agent_id: str = "npc_alice", content: str, memory_type: str = "raw", importance: int = 2):
    record = MemoryRecord(
        agent_id=agent_id,
        memory_type=memory_type,
        content=content,
        importance=importance,
        emotional_weight=0.0,
        metadata_json={},
        active=True,
        created_at=datetime.now(timezone.utc) - timedelta(days=20),
        updated_at=datetime.now(timezone.utc) - timedelta(days=20),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def test_embedding_clustering_suggests_consolidating_similar_raw_memories():
    db = make_db_session()
    try:
        add_agent(db)
        first = add_memory(db, content="Alice heard a rumour about the old well tunnel.")
        second = add_memory(db, content="The old well tunnel was mentioned again by Bob.")
        third = add_memory(db, content="Someone mapped the old well tunnel entrance.")
        add_memory(db, content="Maria likes quiet mornings and tea.")

        response = MemoryMaintenanceSuggestionService(
            db=db,
            embedding_service=FakeEmbeddingService(),
        ).preview(
            agent_id="npc_alice",
            request=MemoryMaintenanceSuggestionsRequest(
                include_embedding_clusters=True,
                include_llm_reasons=False,
                min_cluster_size=3,
                similarity_threshold=0.95,
            ),
        )

        cluster_suggestions = [
            suggestion
            for suggestion in response.suggestions
            if suggestion.source == "embedding_cluster"
            and suggestion.action == "summarize_then_archive"
        ]

        assert cluster_suggestions
        assert set(cluster_suggestions[0].target_memory_ids) == {first.id, second.id, third.id}
        assert cluster_suggestions[0].would_modify is False
    finally:
        db.close()


def test_llm_explanation_rewrites_reason_without_changing_action():
    db = make_db_session()
    try:
        add_agent(db)
        add_memory(db, content="Old raw note about a market conversation.")

        response = MemoryMaintenanceSuggestionService(
            db=db,
            llm_client=FakeLlmClient(),
        ).preview(
            agent_id="npc_alice",
            request=MemoryMaintenanceSuggestionsRequest(
                include_embedding_clusters=False,
                include_llm_reasons=True,
            ),
        )

        assert response.suggestions
        suggestion = response.suggestions[0]
        assert suggestion.action in {"archive", "protect", "decay", "review", "summarize_then_archive"}
        assert suggestion.metadata["reason_method"] == "llm_explanation"
        assert suggestion.metadata["deterministic_reason"]
        assert "maintenance hint" in suggestion.reason
    finally:
        db.close()


def test_relation_protection_still_blocks_cluster_auto_apply():
    db = make_db_session()
    try:
        add_agent(db)
        first = add_memory(db, content="Alice heard a rumour about the old well tunnel.")
        second = add_memory(db, content="The old well tunnel was mentioned again by Bob.")
        third = add_memory(db, content="Someone mapped the old well tunnel entrance.")

        relation = KnowledgeRelationRecord(
            agent_id="npc_alice",
            world_id="default",
            source_type="memory",
            source_id=str(first.id),
            relation_type="supports",
            target_type="concept",
            target_id="old_well_secret",
            confidence=1.0,
            active=True,
        )
        db.add(relation)
        db.commit()

        response = MemoryMaintenanceSuggestionService(
            db=db,
            embedding_service=FakeEmbeddingService(),
        ).preview(
            agent_id="npc_alice",
            request=MemoryMaintenanceSuggestionsRequest(
                include_relation_protection=True,
                include_embedding_clusters=True,
                min_cluster_size=3,
                similarity_threshold=0.95,
            ),
        )

        protected = [suggestion for suggestion in response.suggestions if suggestion.action == "protect"]
        assert protected
        assert first.id in protected[0].target_memory_ids

        clusters = [suggestion for suggestion in response.suggestions if suggestion.source == "embedding_cluster"]
        assert clusters
        assert clusters[0].relation_protected is True
        assert clusters[0].safe_to_auto_apply is False
        assert relation.id in clusters[0].blocked_by_relation_ids
    finally:
        db.close()

from __future__ import annotations

import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from mozok.db.models import Base
from mozok.knowledge_relations.models import KnowledgeRelationRecord  # noqa: F401 - ensure table is registered.
from mozok.knowledge_relations.service import KnowledgeRelationService
from mozok.memory.search_reranking import install_live_search_reranking
from mozok.memory.service import MemoryService
from mozok.schemas.knowledge_relations import KnowledgeRelationUpsert


class FakeEmbeddingService:
    def embed_text(self, text: str):
        return np.array([1.0, 0.0, 0.0], dtype="float32")


class FakeVectorIndex:
    def __init__(self):
        self.candidates = []
        self.added = []

    def add(self, memory_id: int, vector):
        self.added.append(memory_id)

    def search(self, vector, limit: int):
        return list(self.candidates)[:limit]

    def clear(self):
        self.candidates = []

    def reset(self, dim: int):
        self.candidates = []


def make_db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return SessionLocal()


def test_live_search_wrapper_attaches_reranking_metadata_without_persisting_it():
    install_live_search_reranking(MemoryService)
    db = make_db_session()
    try:
        vector_index = FakeVectorIndex()
        memory_service = MemoryService(db, FakeEmbeddingService(), vector_index)

        weak = memory_service._create_memory_record(  # noqa: SLF001 - unit test setup.
            agent_id="npc_alice",
            content="Alice once ate soup near the market.",
            memory_type="semantic",
            importance=3,
            emotional_weight=0.0,
            metadata={"test": "reranking_soup"},
            index=False,
        )
        strong = memory_service._create_memory_record(  # noqa: SLF001 - unit test setup.
            agent_id="npc_alice",
            content="Alice knows that the old well connects to hidden tunnels.",
            memory_type="semantic",
            importance=9,
            emotional_weight=1.0,
            metadata={"test": "reranking_old_well"},
            index=False,
        )
        vector_index.candidates = [
            (weak.id, 0.70),
            (strong.id, 0.70),
        ]

        results = memory_service.search(
            agent_id="npc_alice",
            query="old well tunnels",
            limit=2,
            update_access=False,
        )

        assert [result.id for result in results] == [strong.id, weak.id]
        assert results[0].metadata["_reranking"]["memory_id"] == strong.id
        assert results[0].metadata["_reranking"]["score_parts"]["importance"] > 0
        assert results[0].metadata["_reranking"]["reason"].startswith("Selected because")

        db.refresh(strong)
        assert "_reranking" not in (strong.metadata_json or {})
    finally:
        db.close()


def test_live_search_wrapper_uses_relation_signal_when_available():
    install_live_search_reranking(MemoryService)
    db = make_db_session()
    try:
        vector_index = FakeVectorIndex()
        memory_service = MemoryService(db, FakeEmbeddingService(), vector_index)
        record = memory_service._create_memory_record(  # noqa: SLF001 - unit test setup.
            agent_id="npc_alice",
            content="Alice knows that the old well connects to hidden tunnels.",
            memory_type="semantic",
            importance=5,
            emotional_weight=0.0,
            metadata={},
            index=False,
        )
        KnowledgeRelationService(db).upsert(
            KnowledgeRelationUpsert(
                agent_id="npc_alice",
                world_id="test_world",
                source_type="memory",
                source_id=str(record.id),
                relation_type="supports",
                target_type="goal",
                target_id="hide_tunnel_secret",
                strength=1.0,
                confidence=1.0,
                description="The memory supports an active goal.",
            )
        )
        vector_index.candidates = [(record.id, 0.50)]

        result = memory_service.search(
            agent_id="npc_alice",
            query="old well",
            limit=1,
            update_access=False,
        )[0]

        explanation = result.metadata["_reranking"]
        assert explanation["score_parts"]["active_goal_boost"] > 0
        assert explanation["relation_signal"]["active_goal_count"] == 1
        assert "linked to active goal context" in explanation["reason"]
    finally:
        db.close()

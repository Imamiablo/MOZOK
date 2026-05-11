from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from mozok.context.dedup import fingerprint_text, language_aware_tokens, normalize_text
from mozok.db.models import Base, MemoryRecord
from mozok.memory.dedup_audit import MemoryDedupAuditService
from mozok.schemas.memory import MemoryDedupAuditRequest


class FakeEmbeddingService:
    def embed_text(self, text: str):
        clean = text.lower()
        if any(word in clean for word in ["well", "tunnel", "map", "passage", "chapel"]):
            return [1.0, 0.0, 0.0]
        if any(word in clean for word in ["cat", "neko", "maria"]):
            return [0.0, 1.0, 0.0]
        return [0.0, 0.0, 1.0]


def make_db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return TestingSessionLocal()


def add_memory(db, memory_id: int, content: str, memory_type: str = "semantic", importance: int = 5):
    record = MemoryRecord(
        id=memory_id,
        agent_id="dedup_agent",
        memory_type=memory_type,
        content=content,
        importance=importance,
        emotional_weight=0.0,
        metadata_json={},
        active=True,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def test_language_aware_tokenisation_handles_ukrainian_and_cjk_text():
    ua_tokens = language_aware_tokens(normalize_text("Аліса знає про старий колодязь і тунелі."))
    jp_tokens = language_aware_tokens(normalize_text("古い井戸の地下通路"))

    assert "аліса" in ua_tokens
    assert "про" not in ua_tokens
    assert any(len(token) == 2 for token in jp_tokens)


def test_dedup_v2_audit_reports_duplicate_and_relation_suggestion_without_mutating_db():
    db = make_db_session()
    try:
        add_memory(db, 1, "Alice saw a locked tunnel map behind the seventh stone.", "semantic", importance=8)
        add_memory(db, 2, "Alice saw a locked tunnel map behind seventh stone.", "episodic", importance=5)

        response = MemoryDedupAuditService(db, FakeEmbeddingService()).audit(
            "dedup_agent",
            MemoryDedupAuditRequest(min_confidence=0.1),
        )

        assert response.dry_run is True
        assert response.scanned_memories == 2
        assert response.compared_pairs == 1
        assert response.candidates_count == 1
        candidate = response.candidates[0]
        assert candidate.suggested_relation_type == "duplicate_of"
        assert candidate.would_modify is False
        assert candidate.would_delete is False
        assert candidate.relation_suggestion is not None
        assert candidate.relation_suggestion.relation_type == "duplicate_of"
        assert candidate.relation_suggestion.source_id == "2"
        assert candidate.relation_suggestion.target_id == "1"

        records = db.query(MemoryRecord).all()
        assert len(records) == 2
        assert all(record.active for record in records)
    finally:
        db.close()


def test_dedup_v2_audit_uses_embedding_similarity_for_similar_memories():
    db = make_db_session()
    try:
        add_memory(db, 10, "Alice remembers the old well tunnel map under the chapel.")
        add_memory(db, 11, "The hidden passage map is connected to the chapel well.")

        response = MemoryDedupAuditService(db, FakeEmbeddingService()).audit(
            "dedup_agent",
            MemoryDedupAuditRequest(
                min_text_similarity=0.95,
                min_token_overlap=0.95,
                min_embedding_similarity=0.8,
                min_confidence=0.1,
            ),
        )

        assert response.candidates_count == 1
        candidate = response.candidates[0]
        assert candidate.suggested_relation_type in {"similar_to", "duplicate_of"}
        assert candidate.embedding_similarity is not None
        assert candidate.embedding_similarity >= 0.8
    finally:
        db.close()


def test_dedup_v2_audit_detects_contradictory_memory_candidates():
    db = make_db_session()
    try:
        add_memory(db, 20, "Bob knows the old well tunnel secret and has the tunnel map.")
        add_memory(db, 21, "Bob does not know the old well tunnel secret and has no tunnel map.")

        response = MemoryDedupAuditService(db, FakeEmbeddingService()).audit(
            "dedup_agent",
            MemoryDedupAuditRequest(min_confidence=0.1),
        )

        assert response.candidates_count == 1
        candidate = response.candidates[0]
        assert candidate.suggested_relation_type == "contradicts"
        assert candidate.relation_suggestion is not None
        assert candidate.relation_suggestion.relation_type == "contradicts"
    finally:
        db.close()


def test_dedup_v2_audit_detects_superseding_memory_candidates():
    db = make_db_session()
    try:
        add_memory(db, 30, "The tunnel entrance is in the cellar.", "episodic", importance=4)
        add_memory(db, 31, "Updated: the tunnel entrance is behind the seventh stone instead of the cellar.", "semantic", importance=8)

        response = MemoryDedupAuditService(db, FakeEmbeddingService()).audit(
            "dedup_agent",
            MemoryDedupAuditRequest(min_confidence=0.1),
        )

        assert response.candidates_count == 1
        candidate = response.candidates[0]
        assert candidate.suggested_relation_type == "supersedes"
        assert candidate.relation_suggestion is not None
        assert candidate.relation_suggestion.source_id == "31"
        assert candidate.relation_suggestion.target_id == "30"
    finally:
        db.close()

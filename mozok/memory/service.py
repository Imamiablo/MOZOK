from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy.orm import Session
from mozok.db.models import MemoryRecord
from mozok.embeddings.base import EmbeddingService
from mozok.faiss_index.store import FaissMemoryIndex
from mozok.schemas.memory import MemoryCreate, MemorySearchResult


class MemoryService:
    """The only public doorway to bot memory.

    This class deliberately hides the SQL + FAISS split from the rest of the app.
    Other modules should not manually write memories to SQL or FAISS.
    """

    def __init__(
        self,
        db: Session,
        embedding_service: EmbeddingService,
        vector_index: FaissMemoryIndex,
    ):
        self.db = db
        self.embedding_service = embedding_service
        self.vector_index = vector_index

    def add_memory(self, data: MemoryCreate) -> MemoryRecord:
        """Save memory in SQL, then index it in FAISS.

        Current simplification:
        - If FAISS indexing fails after SQL commit, index can be rebuilt later.
        - Production version should use pending-index jobs.
        """

        record = MemoryRecord(
            agent_id=data.agent_id,
            memory_type=data.memory_type,
            content=data.content,
            importance=data.importance,
            emotional_weight=data.emotional_weight,
            metadata_json=data.metadata,
        )

        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)

        vector = self.embedding_service.embed_text(data.content)
        self.vector_index.add(record.id, vector)

        return record

    def search(
        self,
        agent_id: str,
        query: str,
        limit: int = 5,
        memory_type: str | None = None,
    ) -> list[MemorySearchResult]:
        """Semantic search.

        FAISS returns candidate IDs.
        SQL validates/filter/sorts them.
        This means FAISS is fast, while SQL remains the source of truth.
        """

        query_vector = self.embedding_service.embed_text(query)

        # Ask FAISS for more than we need because SQL filters may remove some.
        candidate_count = max(limit * 10, 25)
        candidates = self.vector_index.search(query_vector, limit=candidate_count)
        if not candidates:
            return []

        score_by_id = {memory_id: score for memory_id, score in candidates}
        ids = list(score_by_id.keys())

        query_obj = self.db.query(MemoryRecord).filter(
            MemoryRecord.id.in_(ids),
            MemoryRecord.agent_id == agent_id,
            MemoryRecord.active == True,  # noqa: E712 - SQLAlchemy syntax
        )

        if memory_type is not None:
            query_obj = query_obj.filter(MemoryRecord.memory_type == memory_type)

        records = query_obj.all()

        # Lightweight reranking: vector score + importance bonus.
        # Later: add recency, emotional weight, relationship score, reranker model.
        ranked = sorted(
            records,
            key=lambda r: score_by_id.get(r.id, -999.0) + (r.importance * 0.01),
            reverse=True,
        )[:limit]

        now = datetime.now(timezone.utc)
        for record in ranked:
            record.last_accessed_at = now
        self.db.commit()

        return [
            MemorySearchResult(
                id=r.id,
                content=r.content,
                memory_type=r.memory_type,
                importance=r.importance,
                score=score_by_id.get(r.id, 0.0),
            )
            for r in ranked
        ]

    def soft_delete(self, memory_id: int) -> bool:
        """Deactivate a memory in SQL.

        FAISS may still contain the vector, but search() filters inactive records out.
        This is intentional; periodic rebuild_index() removes dead vectors.
        """

        record = self.db.get(MemoryRecord, memory_id)
        if record is None:
            return False

        record.active = False
        record.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        return True

    def rebuild_index(self) -> int:
        """Rebuild FAISS from active SQL memories.

        This is the safety valve that makes SQL + FAISS manageable.
        """

        records = self.db.query(MemoryRecord).filter(MemoryRecord.active == True).all()  # noqa: E712
        if not records:
            return 0

        first_vector = self.embedding_service.embed_text(records[0].content)
        self.vector_index.reset(dim=first_vector.shape[0])
        self.vector_index.add(records[0].id, first_vector)

        for record in records[1:]:
            vector = self.embedding_service.embed_text(record.content)
            self.vector_index.add(record.id, vector)

        return len(records)

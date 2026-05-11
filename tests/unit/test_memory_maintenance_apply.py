from __future__ import annotations

import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from mozok.db.models import Base, MemoryRecord
from mozok.knowledge_relations.models import KnowledgeRelationRecord  # noqa: F401 - imported so metadata creates the table.
from mozok.knowledge_relations.service import KnowledgeRelationService
from mozok.memory.maintenance_apply import MemoryMaintenanceApplyService
from mozok.memory.service import MemoryService
from mozok.schemas.knowledge_relations import KnowledgeRelationUpsert
from mozok.schemas.memory import (
    MemoryMaintenanceApplyRejectRequest,
    MemoryMaintenanceSuggestionInput,
)


class FakeEmbeddingService:
    def embed_text(self, text: str):
        return np.array([1.0, 0.0, 0.0], dtype="float32")


class FakeVectorIndex:
    def __init__(self):
        self.added = []
        self.rebuilt = 0
        self.cleared = False

    def add(self, memory_id: int, vector):
        self.added.append(memory_id)

    def search(self, vector, limit: int):
        return []

    def clear(self):
        self.cleared = True

    def reset(self, dim: int):
        self.rebuilt += 1
        self.added = []


def make_db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return SessionLocal()


def make_memory_service(db):
    return MemoryService(db, FakeEmbeddingService(), FakeVectorIndex())


def create_memory(memory_service, agent_id="npc_alice", memory_type="raw", importance=2, content="old raw note"):
    return memory_service._create_memory_record(  # noqa: SLF001 - unit test setup.
        agent_id=agent_id,
        content=content,
        memory_type=memory_type,
        importance=importance,
        emotional_weight=0.0,
        metadata={},
        index=True,
    )


def test_apply_selected_archive_blocks_related_memory_and_protects_it():
    db = make_db_session()
    try:
        memory_service = make_memory_service(db)
        record = create_memory(memory_service)
        KnowledgeRelationService(db).upsert(
            KnowledgeRelationUpsert(
                agent_id="npc_alice",
                world_id="test_world",
                source_type="memory",
                source_id=str(record.id),
                relation_type="depends_on",
                target_type="goal",
                target_id="hide_tunnel_secret",
                confidence=1.0,
                strength=1.0,
                description="This memory is needed for an active plot goal.",
            )
        )

        response = MemoryMaintenanceApplyService(db, memory_service).apply_suggestions(
            agent_id="npc_alice",
            request=MemoryMaintenanceApplyRejectRequest(
                selection="selected",
                selected_suggestion_ids=["archive:memory:1"],
                suggestions=[
                    MemoryMaintenanceSuggestionInput(
                        suggestion_id="archive:memory:1",
                        action="archive",
                        target_memory_ids=[record.id],
                        reason="Low retention score.",
                    )
                ],
            ),
        )

        db.refresh(record)
        assert response.applied == 0
        assert response.relation_protected == 1
        assert response.results[0].status == "relation_protected"
        assert record.active is True
        assert record.metadata_json["protected"] is True
        assert record.metadata_json["protected_reason"] == "maintenance_apply_relation_protection"
    finally:
        db.close()


def test_apply_all_archives_unrelated_memory_and_rebuilds_once():
    db = make_db_session()
    try:
        memory_service = make_memory_service(db)
        record = create_memory(memory_service, content="unrelated noisy raw note")

        response = MemoryMaintenanceApplyService(db, memory_service).apply_suggestions(
            agent_id="npc_alice",
            request=MemoryMaintenanceApplyRejectRequest(
                selection="all",
                suggestions=[
                    MemoryMaintenanceSuggestionInput(
                        suggestion_id="archive:memory:unrelated",
                        action="archive",
                        target_memory_ids=[record.id],
                        reason="Low retention score.",
                    )
                ],
                rebuild_index=True,
            ),
        )

        archived = db.get(MemoryRecord, record.id)
        assert response.applied == 1
        assert response.relation_protected == 0
        assert response.rebuilt_index is True
        assert archived.active is False
        assert archived.metadata_json["archived"] is True
    finally:
        db.close()


def test_reject_selected_records_rejection_without_applying_action():
    db = make_db_session()
    try:
        memory_service = make_memory_service(db)
        record = create_memory(memory_service, content="candidate raw note")

        response = MemoryMaintenanceApplyService(db, memory_service).reject_suggestions(
            agent_id="npc_alice",
            request=MemoryMaintenanceApplyRejectRequest(
                selection="selected",
                selected_suggestion_ids=["decay:memory:candidate"],
                suggestions=[
                    MemoryMaintenanceSuggestionInput(
                        suggestion_id="decay:memory:candidate",
                        action="decay",
                        target_memory_ids=[record.id],
                        reason="Rejected by user.",
                    )
                ],
            ),
        )

        db.refresh(record)
        assert response.rejected == 1
        assert response.results[0].status == "rejected"
        assert record.active is True
        assert record.importance == 2
        assert record.metadata_json["maintenance_rejections"][0]["suggestion_id"] == "decay:memory:candidate"
    finally:
        db.close()

from mozok.memory.summarizer import MemorySummarizer


def test_summarise_apply_auto_creates_summary_graph_relations():
    db = make_db_session()
    try:
        memory_service = make_memory_service(db)
        memory_service.summarizer = MemorySummarizer(llm_client=None)
        first = create_memory(memory_service, content="Alice heard water under the chapel.")
        second = create_memory(memory_service, content="Alice saw a map behind the seventh stone.")

        response = MemoryMaintenanceApplyService(db, memory_service).apply_suggestions(
            agent_id="npc_alice",
            request=MemoryMaintenanceApplyRejectRequest(
                selection="all",
                suggestions=[
                    MemoryMaintenanceSuggestionInput(
                        suggestion_id="summarise:old_well_cluster",
                        action="summarize",
                        target_memory_ids=[first.id, second.id],
                        reason="Cluster should be summarised.",
                    )
                ],
                rebuild_index=False,
            ),
        )

        assert response.applied == 1
        summary_ids = response.results[0].created_summary_ids
        assert len(summary_ids) == 1
        summary_id = str(summary_ids[0])

        relations = db.query(KnowledgeRelationRecord).filter(
            KnowledgeRelationRecord.agent_id == "npc_alice",
            KnowledgeRelationRecord.active == True,  # noqa: E712
        ).all()
        relation_types = {(item.source_id, item.relation_type, item.target_id) for item in relations}
        assert (str(first.id), "summarised_by", summary_id) in relation_types
        assert (str(second.id), "summarised_by", summary_id) in relation_types
        assert (summary_id, "derived_from", str(first.id)) in relation_types
        assert (summary_id, "derived_from", str(second.id)) in relation_types
        assert all(item.metadata_json.get("created_by") == "memory_summarizer" for item in relations)
    finally:
        db.close()

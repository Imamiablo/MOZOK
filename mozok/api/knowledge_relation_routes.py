from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from mozok.db.session import get_db
from mozok.knowledge_relations.service import (
    KnowledgeRelationService,
    format_knowledge_relation_for_prompt_line,
    reads_from_records,
)
from mozok.schemas.knowledge_relations import (
    KnowledgeRelationContextResponse,
    KnowledgeRelationPatch,
    KnowledgeRelationRead,
    KnowledgeRelationUpsert,
)


router = APIRouter(tags=["knowledge-relations"])


@router.post("/knowledge-relations/upsert", response_model=KnowledgeRelationRead)
def upsert_knowledge_relation(data: KnowledgeRelationUpsert, db: Session = Depends(get_db)):
    record = KnowledgeRelationService(db).upsert(data)
    return KnowledgeRelationRead.from_record(record)


@router.patch("/knowledge-relations/{relation_id}", response_model=KnowledgeRelationRead)
def patch_knowledge_relation(relation_id: int, data: KnowledgeRelationPatch, db: Session = Depends(get_db)):
    record = KnowledgeRelationService(db).patch(relation_id, data)
    if record is None:
        raise HTTPException(status_code=404, detail="Knowledge relation not found")
    return KnowledgeRelationRead.from_record(record)


@router.delete("/knowledge-relations/{relation_id}")
def delete_knowledge_relation(relation_id: int, db: Session = Depends(get_db)):
    ok = KnowledgeRelationService(db).soft_delete(relation_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Knowledge relation not found")
    return {"deleted": True, "relation_id": relation_id}


@router.get("/agents/{agent_id}/knowledge-relations", response_model=list[KnowledgeRelationRead])
def list_agent_knowledge_relations(
    agent_id: str,
    world_id: str | None = Query(default=None),
    source_type: str | None = Query(default=None),
    source_id: str | None = Query(default=None),
    target_type: str | None = Query(default=None),
    target_id: str | None = Query(default=None),
    relation_type: str | None = Query(default=None),
    include_inactive: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    records = KnowledgeRelationService(db).list_relations(
        agent_id=agent_id,
        world_id=world_id,
        source_type=source_type,
        source_id=source_id,
        target_type=target_type,
        target_id=target_id,
        relation_type=relation_type,
        include_inactive=include_inactive,
        limit=limit,
    )
    return reads_from_records(records)


@router.get("/agents/{agent_id}/knowledge-relations/context", response_model=KnowledgeRelationContextResponse)
def get_agent_knowledge_relations_context(
    agent_id: str,
    world_id: str | None = Query(default=None),
    source_type: str | None = Query(default=None),
    source_id: str | None = Query(default=None),
    target_type: str | None = Query(default=None),
    target_id: str | None = Query(default=None),
    relation_type: str | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    records = KnowledgeRelationService(db).list_relations(
        agent_id=agent_id,
        world_id=world_id,
        source_type=source_type,
        source_id=source_id,
        target_type=target_type,
        target_id=target_id,
        relation_type=relation_type,
        include_inactive=False,
        limit=limit,
    )
    relations = reads_from_records(records)
    lines = [format_knowledge_relation_for_prompt_line(relation) for relation in relations]
    return KnowledgeRelationContextResponse(
        agent_id=agent_id,
        world_id=world_id,
        count=len(relations),
        lines=lines,
        relations=relations,
    )
